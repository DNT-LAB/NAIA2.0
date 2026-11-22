"""Single-owner SQLite forward index. Row numbers are zero-based bit positions."""
from collections.abc import Collection, Iterable, Iterator, Sequence
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
import time
import zlib


EXIST, META_HEAD, NEEDS_DECODE, NO_META, DECODED, READ_ERROR = (1, 2, 4, 8, 16, 32)
UNKNOWN, NAI, WEBUI, COMFYUI, NAIA = range(5)
SCHEMA_VERSION = "1"
_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE roots(id INTEGER PRIMARY KEY, path TEXT UNIQUE, kind TEXT, enabled INTEGER, added_at REAL);
CREATE TABLE dirs(id INTEGER PRIMARY KEY, root_id INTEGER, rel TEXT, state INTEGER, files INTEGER,
                  done_at REAL, UNIQUE(root_id, rel));
CREATE TABLE files(row INTEGER PRIMARY KEY, dir_id INTEGER, name TEXT, size INTEGER, mtime_ns INTEGER,
                   flags INTEGER, source INTEGER, width INTEGER, height INTEGER, seed INTEGER,
                   model TEXT, prompt BLOB, negative BLOB, chars BLOB, tags BLOB);
CREATE INDEX files_live ON files(dir_id, name) WHERE flags & 1;
CREATE TABLE vocab(id INTEGER PRIMARY KEY, tag TEXT UNIQUE);
"""
_FILE_FIELDS = "dir_id,name,size,mtime_ns,flags,source,width,height,seed,model,prompt,negative,chars,tags"
_COLUMNS = {"meta": "key,value", "roots": "id,path,kind,enabled,added_at",
            "dirs": "id,root_id,rel,state,files,done_at", "files": "row," + _FILE_FIELDS, "vocab": "id,tag"}


class _InvalidIndex(ValueError):
    pass


def _corrupt(exc: sqlite3.DatabaseError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        return (code & 255) in (11, 26)  # SQLITE_CORRUPT, SQLITE_NOTADB
    # Python 3.10 does not expose SQLite result codes.
    return str(exc) in {"database disk image is malformed", "file is not a database"}


def _setup(db: sqlite3.Connection) -> None:
    db.executescript(_SCHEMA)
    with db:
        db.executemany("INSERT INTO meta VALUES (?,?)", {
            "schema_version": SCHEMA_VERSION, "created_at": str(time.time()),
            "rows": "0", "dead": "0", "vocab_version": "0",
        }.items())


def _blob(text: str) -> bytes:
    return zlib.compress(text.encode("utf8"))


def _decode_tags(blob: bytes, vocab: dict[int, str]) -> list[str]:
    return [vocab[i] for (i,) in struct.iter_unpack("<I", blob)]


class IndexStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = self._open()
        self._vocab: dict[int, str] = {}
        self._last_tag = 0

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables:
                _setup(db)
            else:
                if tables != _COLUMNS.keys():
                    raise _InvalidIndex("unexpected schema")
                for table, expected in _COLUMNS.items():
                    columns = db.execute(f"PRAGMA table_info({table})")
                    if ",".join(c[1] for c in columns) != expected:
                        raise _InvalidIndex("incompatible columns")
                if (dict(db.execute("SELECT key,value FROM meta")).get("schema_version") != SCHEMA_VERSION
                        or db.execute("PRAGMA quick_check").fetchone() != ("ok",)):
                    raise _InvalidIndex("invalid cache")
            db.execute("PRAGMA journal_mode=WAL")
        except (_InvalidIndex, sqlite3.DatabaseError) as exc:
            db.close()
            if isinstance(exc, sqlite3.DatabaseError) and not _corrupt(exc):
                raise  # A locked, full or read-only disk is not a corrupt cache.
            for suffix in ("-shm", "-wal", "-journal", ""):
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            return self._open()
        db.row_factory = sqlite3.Row
        return db

    def close(self) -> None:
        self._db.close()

    def _bump(self, key: str, delta: int) -> None:
        self._db.execute("UPDATE meta SET value=value+? WHERE key=?", (delta, key))

    def add_root(self, path: str | Path, kind: str, enabled: bool = True) -> int:
        with self._db:
            # Removed roots can still be referenced by historical (dead) rows.
            self._db.execute("INSERT INTO roots VALUES (1+max((SELECT coalesce(max(id),0) FROM roots),"
                             "(SELECT coalesce(max(root_id),0) FROM dirs)),?,?,?,?) "
                             "ON CONFLICT(path) DO NOTHING", (str(path), kind, enabled, time.time()))
            return self._db.execute("SELECT id FROM roots WHERE path=?", (str(path),)).fetchone()[0]

    def roots(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM roots ORDER BY id")]

    def update_root(self, root_id: int, *, enabled: bool | None = None, kind: str | None = None,
                    path: str | Path | None = None) -> None:
        with self._db:
            self._db.execute("UPDATE roots SET enabled=coalesce(?,enabled), kind=coalesce(?,kind), "
                             "path=coalesce(?,path) WHERE id=?",
                             (enabled, kind, str(path) if path is not None else None, root_id))

    def remove_root(self, root_id: int) -> None:
        with self._db:
            changed = self._db.execute("UPDATE files SET flags=flags & ~1 WHERE flags & 1 AND "
                                       "dir_id IN (SELECT id FROM dirs WHERE root_id=?)", (root_id,))
            self._bump("dead", changed.rowcount)
            self._db.execute("DELETE FROM roots WHERE id=?", (root_id,))

    def get_or_create_dir(self, root_id: int, rel: str) -> int:
        with self._db:
            if not self._db.execute("SELECT 1 FROM roots WHERE id=?", (root_id,)).fetchone():
                raise ValueError("unknown root")
            self._db.execute("INSERT INTO dirs(root_id,rel,state,files) VALUES (?,?,0,0) "
                             "ON CONFLICT(root_id,rel) DO NOTHING", (root_id, rel))
            return self._db.execute("SELECT id FROM dirs WHERE root_id=? AND rel=?", (root_id, rel)).fetchone()[0]

    def set_state(self, dir_id: int, state: int, files: int | None = None) -> None:
        if state not in (0, 1, 2):
            raise ValueError("invalid directory state")
        with self._db:
            self._db.execute("UPDATE dirs SET state=?,files=coalesce(?,files),done_at=? WHERE id=?",
                             (state, files, time.time() if state == 2 else None, dir_id))

    def dirs(self, root_id: int) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM dirs WHERE root_id=? ORDER BY id", (root_id,))]

    def live_files(self, dir_id: int) -> dict[str, tuple[int, int, int]]:
        rows = self._db.execute("SELECT name,row,size,mtime_ns FROM files WHERE dir_id=? AND flags & 1", (dir_id,))
        return {name: (row, size, mtime) for name, row, size, mtime in rows}

    def _tag_blob(self, tags: Iterable[str], cache: dict[str, int]) -> bytes:
        ids = []
        for tag in set(tags):
            if tag not in cache:
                added = self._db.execute("INSERT INTO vocab(tag) VALUES (?) ON CONFLICT(tag) DO NOTHING", (tag,))
                if added.rowcount:
                    self._bump("vocab_version", 1)
                    cache[tag] = added.lastrowid
                else:
                    cache[tag] = self._db.execute("SELECT id FROM vocab WHERE tag=?", (tag,)).fetchone()[0]
            ids.append(cache[tag])
        return struct.pack(f"<{len(ids)}I", *sorted(ids))

    def add_rows(self, rows: list[dict]) -> list[int]:
        cache: dict[str, int] = {}
        with self._db:
            start = self._db.execute("SELECT coalesce(max(row)+1,0) FROM files").fetchone()[0]
            dead = 0
            for number, item in enumerate(rows, start):
                dir_id, name = item["dir_id"], item["name"]
                flags = item.get("flags", EXIST)
                if not self._db.execute("SELECT 1 FROM dirs JOIN roots ON roots.id=dirs.root_id "
                                        "WHERE dirs.id=?", (dir_id,)).fetchone():
                    raise ValueError("unknown directory")
                if flags & EXIST:
                    dead += self._db.execute("UPDATE files SET flags=flags & ~1 WHERE dir_id=? AND name=? "
                                             "AND flags & 1", (dir_id, name)).rowcount
                else:
                    dead += 1
                self._db.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    number, dir_id, name, item["size"], item["mtime_ns"], flags, item.get("source", UNKNOWN),
                    item.get("width"), item.get("height"), item.get("seed"), item.get("model"),
                    _blob(item.get("prompt", "")), _blob(item.get("negative", "")),
                    _blob(json.dumps(item.get("chars", []), ensure_ascii=False)), self._tag_blob(item.get("tags", []), cache),
                ))
            self._bump("rows", len(rows))
            self._bump("dead", dead)
        return list(range(start, start + len(rows)))

    def mark_dead(self, rows: Iterable[int]) -> None:
        with self._db:
            changed = self._db.executemany("UPDATE files SET flags=flags & ~1 WHERE row=? AND flags & 1",
                                           ((r,) for r in rows))
            self._bump("dead", changed.rowcount)

    def iter_rows(self, start: int = 0) -> Iterator[dict]:
        """Only bitmap fields; never fetch or decompress the prompt columns."""
        # In particular, the save hook need not reload the whole vocabulary
        # to feed just one newly committed row to IndexBits.append().
        for tag_id, tag in self._db.execute("SELECT id,tag FROM vocab WHERE id>? ORDER BY id", (self._last_tag,)):
            self._vocab[tag_id] = tag
            self._last_tag = tag_id
        for r in self._db.execute("SELECT row,flags,source,mtime_ns,root_id,tags FROM files "
                                  "LEFT JOIN dirs ON dirs.id=files.dir_id WHERE row>=? ORDER BY row", (start,)):
            yield {**r, "tags": _decode_tags(r["tags"], self._vocab)}

    def fetch(self, rows: Sequence[int]) -> list[dict]:
        """Return live result lines in page order."""
        found = {}
        for i in range(0, len(rows), 500):
            batch = rows[i:i+500]
            params = ",".join("?" for _ in batch)
            for r in self._db.execute(f"SELECT f.*,d.rel,d.root_id FROM files f JOIN dirs d ON d.id=f.dir_id "
                                      f"WHERE f.flags & 1 AND row IN ({params})", tuple(batch)):
                item = dict(r)
                del item["tags"]
                for key in ("prompt", "negative", "chars"):
                    item[key] = zlib.decompress(item[key]).decode("utf8")
                item["chars"] = json.loads(item["chars"])
                found[r["row"]] = item
        return [found[n] for n in rows if n in found]

    def counts(self) -> dict[int, int]:
        """Counts by flag among live rows (EXIST is the live total)."""
        flags = (EXIST, META_HEAD, NEEDS_DECODE, NO_META, DECODED, READ_ERROR)
        columns = ",".join(f"count(CASE WHEN flags & {bit} THEN 1 END)" for bit in flags)
        return dict(zip(flags, self._db.execute(f"SELECT {columns} FROM files WHERE flags & 1").fetchone()))

    def needs_compaction(self) -> bool:
        stats = dict(self._db.execute("SELECT key,value FROM meta WHERE key IN ('rows','dead')"))
        return int(stats["dead"]) > 5000 and int(stats["dead"]) * 4 > int(stats["rows"])

    def compact(self, unreachable_roots: Collection[int] = ()) -> bool:
        """Explicit maintenance; idle callers consult needs_compaction() first."""
        if unreachable_roots:
            return False
        fd, name = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        os.close(fd)
        temp = Path(name)
        try:
            with closing(sqlite3.connect(temp)) as dest:
                _setup(dest)
                dest.execute("ATTACH DATABASE ? AS old", (str(self.path),))
                with dest:
                    for table in ("roots", "vocab"):
                        dest.execute(f"INSERT INTO main.{table} SELECT * FROM old.{table}")
                    dest.execute("INSERT INTO main.dirs SELECT d.* FROM old.dirs d JOIN old.roots r ON r.id=d.root_id")
                    dest.execute("INSERT OR REPLACE INTO main.meta SELECT * FROM old.meta")
                    dest.execute(f"INSERT INTO main.files SELECT row_number() OVER (ORDER BY row)-1,"
                                 f"{_FILE_FIELDS} FROM old.files WHERE flags & 1 ORDER BY row")
                    dest.execute("UPDATE main.meta SET value=(SELECT count(*) FROM main.files) WHERE key='rows'")
                    dest.execute("UPDATE main.meta SET value='0' WHERE key='dead'")
            # Never replace a main database with outstanding WAL pages.
            if self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                raise sqlite3.OperationalError("index in use during compaction")
            self.close()
            try:
                os.replace(temp, self.path)
            finally:
                self._db = self._open()
            return True
        finally:
            temp.unlink(missing_ok=True)
