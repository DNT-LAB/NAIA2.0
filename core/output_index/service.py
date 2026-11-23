"""One writer per session; readers see a committed DB page and matching bit positions."""
from collections import deque
from concurrent.futures import Future
from contextlib import closing, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import threading
import time

from app.backend.server.startup_work import background_cpu_slot
from .store import DECODED, EXIST, META_HEAD, NEEDS_DECODE, NO_META, READ_ERROR, IndexStore


_SOURCES = ("unknown", "NAI", "WEBUI", "ComfyUI", "NAIA")
_FLAGS = {EXIST: "EXIST", META_HEAD: "META_HEAD", NEEDS_DECODE: "NEEDS_DECODE",
          NO_META: "NO_META", DECODED: "DECODED", READ_ERROR: "READ_ERROR"}
_SOURCE_IDS = {name.upper(): i for i, name in enumerate(_SOURCES)}
_CREATION = threading.Lock()


@dataclass(frozen=True)
class _IndexedFile:
    path: Path
    root_id: int
    dir_id: int
    root_path: str
    rel: str
    name: str
    size: int
    mtime_ns: int


def output_index_service(context):
    with _CREATION:
        service = getattr(context, "_output_index_service", None)
        if service is None:
            context._output_index_service = service = OutputIndexService(context)
        return service


class _Reader(IndexStore):
    """Reuse fetch/counts, but never run writer setup, recovery or quick_check.

    Create and close on the requesting thread; no live reader can pin the old
    WAL when the writer replaces the database under the publication lock.
    """
    def __init__(self, path):
        self._db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        self._db.row_factory = sqlite3.Row


class OutputIndexService:
    def __init__(self, context):
        self.context = context
        self._lock = threading.RLock()  # protects published roots, bits and reader lifetime
        self._cv = threading.Condition()  # independent: saving never waits on a query or disk
        self._thread = None
        self._stop = False
        self._closed = False  # set by stop(); a later start() (queued before shutdown) does nothing
        self._rescan = False
        self._scanning = False
        self._busy = False
        self._folders_done = self._files_read = 0
        self._files = deque()
        self._commands = deque()
        self._thumbs = None
        self._roots = {}
        self._bits = None
        self._partial = True
        self._pending = 0
        self._current = None
        self._error = None

    @property
    def path(self):
        return Path(self.context.runtime_paths.cache_dir).absolute() / "output_index" / "index.sqlite3"

    def start(self):
        with self._cv:
            if self._closed:
                return
            if self._thread is None or not self._thread.is_alive():
                self._stop = False
                self._rescan = True
                self._thread = threading.Thread(target=self._run, name="naia-output-index", daemon=True)
                self._thread.start()

    def stop(self, timeout=5.0):
        with self._cv:
            self._stop = True
            self._closed = True
            self._cv.notify_all()
            thread = self._thread
        if thread:
            thread.join(timeout)

    def request_rescan(self):
        with self._cv:
            if not self._scanning:
                self._rescan = True
            self._cv.notify()

    def note_saved(self, path):
        with self._cv:
            self._files.append(path)
            self._cv.notify()

    def _command(self, op, *args):
        result = Future()
        with self._cv:
            if self._stop or not self._thread or not self._thread.is_alive():
                raise RuntimeError("index worker is not running")
            self._commands.append((op, args, result))
            self._cv.notify()
        return result.result()

    def add_root(self, path):
        path = Path(path)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("expected an existing absolute directory")
        path = path.resolve()
        self._check_cache(path)
        return self._command("add", path)

    def remove_root(self, root_id):
        return self._command("remove", root_id)

    def set_root_enabled(self, root_id, enabled):
        return self._command("enable", root_id, enabled)

    def forget_paths(self, paths):
        try:
            with self._cv:
                if self._stop or not self._thread or not self._thread.is_alive():
                    return
            files = []
            with self._reader() as reader:
                if reader is None:
                    return
                roots = reader.roots()
                for value in dict.fromkeys(paths):
                    path = Path(value)
                    if not path.is_absolute():
                        continue
                    path = path.resolve()
                    for root in roots:
                        try:
                            relative = path.relative_to(Path(root["path"]).resolve())
                        except ValueError:
                            continue
                        rel = relative.parent.as_posix() if relative.parent != Path(".") else ""
                        row = reader._db.execute(
                            "SELECT dir_id,name,size,mtime_ns FROM files f JOIN dirs d ON d.id=f.dir_id "
                            "WHERE d.root_id=? AND d.rel=? AND f.name=? AND f.flags & 1",
                            (root["id"], rel, relative.name)).fetchone()
                        if row is not None:
                            files.append(_IndexedFile(path=path, root_id=root["id"], root_path=root["path"],
                                                      rel=rel, **row))
            if files:
                self._command("forget", files)
        except Exception:
            pass

    def delete_rows(self, rows, move_to_trash):
        from .scanner import safe_file

        # Resolve the selection at one set of row numbers. Compaction may run
        # while the OS moves files, so the writer also receives stable identities.
        with self._lock:
            with self._cv:
                if self._stop:
                    raise RuntimeError("index worker stopped")
            files = [(row, self.file_path(row, with_identity=True)) for row in rows]
        deleted, failed, forgotten = [], [], []
        try:
            for row, file in files:
                if file is None or safe_file(file.root_path, Path(file.rel) / file.name) is None:
                    failed.append({"row": row, "error": "not found"})
                elif move_to_trash(file.path):
                    deleted.append(row)
                    forgotten.append(file)
                else:
                    failed.append({"row": row, "error": "could not move to recycle bin"})
        finally:
            if forgotten:
                self._command("forget", forgotten)
        return {"ok": bool(deleted), "deleted": deleted, "failed": failed}

    def _forget(self, store, files, saved):
        rows, dirs = [], []
        with self._reader() as reader, store._db:
            for file in files:
                if self._scanning:
                    saved.add((file.root_id, file.rel, file.name))
                live = reader._db.execute(
                    "SELECT row,size,mtime_ns FROM files f JOIN dirs d ON d.id=f.dir_id "
                    "JOIN roots r ON r.id=d.root_id WHERE dir_id=? AND name=? AND flags & 1 "
                    "AND r.path=? AND d.rel=?", (file.dir_id, file.name, file.root_path, file.rel)).fetchone()
                if live is None:
                    continue
                if live[1:] != (file.size, file.mtime_ns) and file.path.exists():
                    continue  # A newly saved replacement is already indexed.
                rows.append(live[0])
                dirs.append((file.dir_id,))
            store._db.executemany("UPDATE dirs SET files=max(0,files-1) WHERE id=?", dirs)
            store.mark_dead(rows)
            for row in rows:
                self._bits.set_dead(row)

    def _configured(self):
        from core.headless_save_service import HeadlessSaveService
        ctx = self.context
        save = ctx._save_service() if hasattr(ctx, "_save_service") else HeadlessSaveService(ctx)
        base = Path(os.path.abspath(save.current_save_directory(use_timestamp_folder=False)))
        settings = {base: "save"}
        if str(ctx.auto_save_state.get("quicksave_dir") or "").strip():
            quick = Path(os.path.abspath(save.quicksave_directory()))
            if (ctx.auto_save_state.get("quicksave_folder") or "date") == "date":
                quick = quick.parent
            if not quick.is_relative_to(base):
                settings[quick] = "quicksave"
        return settings

    def _check_cache(self, path):
        if self.path.resolve().is_relative_to(path.resolve()):
            raise ValueError("the index cache cannot be inside an indexed root")

    def _sync(self, store):
        settings = self._configured()
        registered = {Path(r["path"]) for r in store.roots()}
        for path, kind in settings.items():
            self._check_cache(path)
            if path not in registered:
                store.add_root(path, kind)
        roots = store.roots()
        prefs = dict(store._db.execute("SELECT key,value FROM meta WHERE key LIKE 'enabled:%'"))
        for r in roots:
            path = Path(r["path"])
            # Preserve user registration when a setting happens to use the same path.
            kind = r["kind"] if r["kind"] == "user" else settings.get(path, r["kind"])
            default = str(r["enabled"]) if kind == "user" else "1"
            enabled = (path in settings or kind == "user") and prefs.get(f"enabled:{r['id']}", default) == "1"
            if enabled != bool(r["enabled"]) or kind != r["kind"]:
                store.update_root(r["id"], enabled=enabled, kind=kind)
            r.update(enabled=bool(enabled), kind=settings.get(path, kind))
        active = [Path(r["path"]) for r in roots if r["enabled"]]
        with self._lock:
            for r in roots:
                path = Path(r["path"])
                r["shadowed"] = any(parent in path.parents for parent in active)
                previous = self._roots.get(r["id"], {})
                r["unreachable"] = previous.get("unreachable", True)
                r["unreachable_folders"] = previous.get("unreachable_folders", [])
            self._roots = {r["id"]: r for r in roots}

    def _control(self, store, op, args, saved):
        if op == "forget":
            return self._forget(store, args[0], saved)
        if op == "add":
            existing = next((r for r in store.roots() if Path(r["path"]) == args[0]), None)
            root_id = existing["id"] if existing else store.add_root(args[0], "user")
            if existing:
                # Explicitly re-adding an old settings path registers a user root.
                if args[0] not in self._configured():
                    store.update_root(root_id, kind="user", enabled=True)
                with store._db:
                    store._db.execute("DELETE FROM meta WHERE key=?", (f"enabled:{root_id}",))
        else:
            root_id = args[0]
            if root_id not in self._roots:
                raise ValueError("unknown root")
            if op == "remove":
                if self._roots[root_id]["kind"] != "user":
                    raise ValueError("disable a configured root instead")
                with self._lock:
                    store.remove_root(root_id)
                    self._rebuild_locked(store)
            elif op == "enable":
                with store._db:
                    store._db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                                      (f"enabled:{root_id}", str(int(args[1]))))
        self._sync(store)
        with self._cv:
            self._rescan = True
        return root_id

    def _plan(self, store):
        from . import scanner

        self._sync(store)
        jobs, unfinished = {}, set()
        for rid, root in self._roots.items():
            if not root["enabled"] or root["shadowed"]:
                # An unavailable disabled root still vetoes compaction.
                available = Path(root["path"]).is_dir()
                with self._lock:
                    root["unreachable"] = not available or bool(root.get("unreachable_folders"))
                continue
            listing, unreachable = scanner.list_tree(root["path"])
            with self._lock:
                root["unreachable"] = bool(unreachable)
                root["unreachable_folders"] = sorted(unreachable)
            existing = {d["rel"]: d for d in store.dirs(rid)}
            for rel in existing.keys() - listing.keys():
                if not any(not u or rel == u or rel.startswith(u + "/") for u in unreachable):
                    listing[rel] = []  # its parent was successfully listed; folder was removed
            for rel, entries in listing.items():
                if rel not in existing:
                    store.get_or_create_dir(rid, rel)
                if existing.get(rel, {}).get("state") != 2:
                    unfinished.add((rid, rel))
                jobs[rid, rel] = entries
        return jobs, unfinished

    def _scan(self, store, saved, resume):
        from . import scanner

        jobs, unfinished = self._plan(store)
        order = scanner.plan_folders(jobs)
        if resume:
            order.sort(key=lambda key: key not in unfinished)
        with self._lock:
            self._pending = len(order)
            self._folders_done = self._files_read = 0
        yield
        for rid, rel in order:
            with self._lock:
                self._current = {"root_id": rid, "path": rel}
            batches = scanner.folder_batches(store, self._bits, rid, rel, jobs[rid, rel], time.time,
                                             lock=self._lock, saved=saved)
            for batch in batches:
                with self._lock:
                    self._files_read += batch["read"]
                yield
            with self._lock:
                self._pending -= 1
                self._folders_done += 1
        with self._lock:
            self._partial = False
            self._current = None

    def _hidden(self):
        return {rid for rid, r in self._roots.items()
                if not r["enabled"] or r["shadowed"] or r["unreachable"]}

    def _saved(self, store, path, saved):
        from . import scanner

        path = Path(path).absolute()
        for rid, root in self._roots.items():
            base = Path(root["path"])
            if not root["enabled"] or root["shadowed"] or not path.is_relative_to(base):
                continue
            key = scanner.index_saved(store, self._bits, self._lock, root, path.relative_to(base))
            if key:
                if self._scanning:
                    saved.add(key)
                if root["unreachable"]:
                    with self._cv:
                        self._rescan = True
            return
        # A save setting may have changed since the last pass.
        if any(path.is_relative_to(base) for base in self._configured()):
            with self._cv:
                self._rescan = True

    def _run(self):
        store = None
        try:
            from .bits import IndexBits

            for path in self._configured():
                self._check_cache(path)
            with self._lock:
                self._bits = None
                self._roots = {}
            store = IndexStore(self.path)
            self._sync(store)
            bits = IndexBits(store.iter_rows())
            with self._lock:
                self._bits = bits
            self._loop(store)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            if store is not None:
                store.close()
            with self._cv:
                self._stop = True
                self._scanning = False
                while self._commands:
                    self._commands.popleft()[2].set_exception(RuntimeError("index worker stopped"))

    def _loop(self, store):
        resume = True
        scan = None
        saved = set()
        maintenance = False
        while True:
            with self._cv:
                if self._stop:
                    return
                if self._commands:
                    op, args, reply = self._commands.popleft()
                else:
                    reply = None
                restart = not reply and self._rescan
                if restart:
                    self._scanning, self._rescan = True, False
                elif not reply:
                    if not (self._files or scan or maintenance):
                        self._busy = False
                        self._cv.wait()
                        continue
                    if self.context.is_generating:
                        self._cv.wait(0.5)
                        continue
                self._busy = True
                path = self._files.popleft() if self._files and not (reply or restart) else None
            try:
                if reply:
                    reply.set_result(self._control(store, op, args, saved))
                elif restart:
                    with self._lock:
                        self._partial, self._current, self._error = True, None, None
                    saved = set()
                    scan = self._scan(store, saved, resume)
                    resume = False
                    next(scan)  # listing only
                else:
                    # Generation or shutdown can start while waiting for another
                    # warmup to release the slot. Recheck before touching a file.
                    with background_cpu_slot(self.context):
                        if self.context.is_generating or self._stop:
                            if path is not None:
                                with self._cv:
                                    self._files.appendleft(path)
                            continue
                        if path is not None:
                            self._saved(store, path, saved)
                        elif scan:
                            if next(scan, False) is False:
                                scan = None
                                saved.clear()
                                with self._cv:
                                    self._scanning = False
                                maintenance = True
                        else:
                            maintenance = False
                            self._compact_if_idle(store)
            except Exception as exc:
                if reply:
                    reply.set_exception(exc)
                else:
                    with self._lock:
                        self._error = str(exc)
                    if scan and path is None:
                        with self._cv:
                            self._scanning = False
                        scan = None
                if self._bits is None:
                    raise

    def _rebuild_locked(self, store):
        from .bits import IndexBits

        # Fail closed even if allocating the replacement index fails.
        self._bits = None
        self._bits = IndexBits(store.iter_rows())

    def _compact_if_idle(self, store):
        with self._lock:
            if any(r["unreachable"] for r in self._roots.values()) or not store.needs_compaction():
                return
            with self._cv:
                if self._stop or self._commands or self._rescan or self._files:
                    return
            if store.compact():
                self._rebuild_locked(store)

    @contextmanager
    def _reader(self):
        with self._lock:
            if self._bits is None:
                yield None
            else:
                with closing(_Reader(self.path)) as reader:
                    yield reader

    def _progress(self):
        return {"partial": self._partial, "pending_dirs": self._pending}

    def status(self):
        with self._reader() as reader:
            counts = reader.counts() if reader else {}
            with self._cv:
                alive = bool(self._thread and self._thread.is_alive())
                running = alive and bool(self._busy or self._rescan or self._scanning or self._files or self._commands)
            return {**self._progress(), "roots": [r.copy() for r in self._roots.values()],
                    "rows": self._bits.n_rows if reader else 0, "live_rows": counts.get(EXIST, 0),
                    "counts": {name: counts.get(bit, 0) for bit, name in _FLAGS.items()},
                    "current_folder": self._current, "last_error": self._error,
                    "folders_done": self._folders_done, "files_read": self._files_read,
                    "running": running, "worker_alive": alive}

    @staticmethod
    def _item(r):
        rel = Path(r["rel"]) / r["name"]
        # A malformed cache row must not disclose an absolute host path.
        display_path = rel.as_posix() if not rel.anchor and ".." not in rel.parts else ""
        return {"row": r["row"], "path": display_path, "root_id": r["root_id"],
                "mtime": r["mtime_ns"] / 1e9, "width": r["width"], "height": r["height"],
                "source": _SOURCES[r["source"]], "seed": r["seed"], "prompt": r["prompt"][:300]}

    def query(self, *, include=(), exclude=(), source=None, roots=None, sort="mtime_desc",
              offset=0, limit=100, text="", dir_id=None):
        sources = None if source is None else [_SOURCE_IDS[s.upper()] for s in source]
        dirs = None if dir_id is None else [dir_id]
        with self._reader() as reader:
            if reader is None:
                return {**self._progress(), "count": 0, "items": [], "matched": [], "matched_total": 0}
            result = self._bits.query(include, exclude, sources, roots, self._hidden(), sort,
                                      0 if text else offset, self._bits.n_rows if text else limit, dirs)
            rows = result.pop("rows")
            if text:
                items, count = [], 0
                needle = text.casefold()
                for start in range(0, len(rows), 500):
                    for r in reader.fetch(rows[start:start+500]):
                        if any(needle in s.casefold() for s in (r["prompt"], r["negative"], *r["chars"])):
                            if offset <= count < offset + limit:
                                items.append(self._item(r))
                            count += 1
                result["count"] = count
            else:
                items = [self._item(r) for r in reader.fetch(rows)]
            return {**result, "items": items, **self._progress()}

    def folders(self, *, include=(), exclude=(), source=None, roots=None, sort="mtime_desc",
                offset=0, limit=40, text="", samples=3):
        """Folder overview: one entry per folder with its size and first `samples` images."""
        sources = None if source is None else [_SOURCE_IDS[s.upper()] for s in source]
        with self._reader() as reader:
            if reader is None:
                return {**self._progress(), "count": 0, "folder_count": 0, "folders": [],
                        "matched": [], "matched_total": 0}
            mask, top, total = self._bits.select(include, exclude, sources, roots, self._hidden())
            rows = self._bits.rows_of(mask)
            if text:
                needle, keep = text.casefold(), []
                for start in range(0, len(rows), 500):
                    for r in reader.fetch(rows[start:start+500].tolist()):
                        if any(needle in s.casefold() for s in (r["prompt"], r["negative"], *r["chars"])):
                            keep.append(r["row"])
                rows = keep
            folder_count, groups = self._bits.group(rows, sort == "mtime_desc", offset, limit, samples)
            fetched = {r["row"]: r for r in reader.fetch([row for _, _, picked in groups for row in picked])}
            folders = []
            for dir_id, size, picked in groups:
                lines = [fetched[row] for row in picked if row in fetched]
                rel = Path(lines[0]["rel"]) if lines else Path()
                # A malformed cache row must not disclose an absolute host path.
                safe = rel.as_posix() if not rel.anchor and ".." not in rel.parts else ""
                folders.append({"dir_id": dir_id, "root_id": lines[0]["root_id"] if lines else None,
                                "rel": "" if safe == "." else safe, "count": size,
                                "items": [self._item(r) for r in lines]})
            return {"count": len(rows), "folder_count": folder_count, "folders": folders,
                    "matched": top, "matched_total": total, **self._progress()}

    def suggest(self, q, limit=20, include=(), exclude=()):
        with self._lock:
            items = self._bits.suggest(q, limit, include, exclude, self._hidden()) if self._bits else []
            return {"items": [{"tag": t, "count": n, "condition_count": c} for t, n, c in items],
                    **self._progress()}

    def _visible(self, root_id):
        return root_id in self._roots and root_id not in self._hidden()

    def metadata(self, row):
        with self._reader() as reader:
            rows = reader.fetch([row]) if reader and 0 <= row < self._bits.n_rows else []
            if not rows or not self._visible(rows[0]["root_id"]):
                return None
            r = rows[0]
            return {**self._item(r), "model": r["model"], "prompt": r["prompt"], "negative": r["negative"],
                    "characters": r["chars"], "flags": [name for bit, name in _FLAGS.items() if r["flags"] & bit]}

    def file_path(self, row, *, with_identity=False):
        from . import scanner

        with self._reader() as reader:
            if reader is None or not 0 <= row < self._bits.n_rows:
                return None
            r = reader._db.execute(
                "SELECT root_id,dir_id,rel,name,size,mtime_ns FROM files JOIN dirs ON dirs.id=files.dir_id "
                "WHERE row=? AND flags & 1", (row,)).fetchone()
            if r is None or not self._visible(r["root_id"]):
                return None
            root = self._roots[r["root_id"]]["path"]
            path = scanner.safe_file(root, Path(r["rel"]) / r["name"])
            if with_identity and path is not None:
                return _IndexedFile(path=path, root_path=root, **r)
            return path

    def thumbnail(self, row, size):
        from .thumbs import ThumbnailCache

        file = self.file_path(row, with_identity=True)
        if file is None:
            return None
        with self._lock:
            if self._thumbs is None:
                self._thumbs = ThumbnailCache(self.path.parent)
        return self._thumbs.get(file, size)
