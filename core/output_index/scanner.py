"""Header-only directory reconciliation. No scheduler or background threads here."""
from contextlib import nullcontext
import os
from pathlib import Path
import stat

from utils.image_info import parse_metadata_texts

from .head_reader import read_head
from .store import (COMFYUI, EXIST, META_HEAD, NAI, NAIA, NEEDS_DECODE, NO_META,
                    READ_ERROR, UNKNOWN, WEBUI)
from .tags import prompt_tags


EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
BATCH_SIZE = 500


def _link(st):
    return (stat.S_ISLNK(st.st_mode) or
            getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def list_tree(root_path):
    root = Path(root_path)
    listing, unreachable = {}, set()
    todo = [""]
    while todo:
        rel = todo.pop()
        folder = root / rel
        files, children = [], []
        try:
            # The root itself may be a junction/link the user chose (output moved to another drive);
            # only links found INSIDE the root are refused.
            if rel and _link(folder.lstat()):
                unreachable.add(rel)
                continue
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.name.startswith(".") or entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if _link(st):
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        if entry.name != "_deleted":
                            children.append((Path(rel) / entry.name).as_posix())
                    elif stat.S_ISREG(st.st_mode) and Path(entry.name).suffix.lower() in EXTENSIONS:
                        files.append((entry.name, st.st_size, st.st_mtime_ns))
        except OSError:
            # A partially enumerated directory is NOT a deletion list.
            unreachable.add(rel)
            continue
        listing[rel] = files
        todo.extend(children)
    return listing, unreachable


def newest(entries):
    return max((mtime for _, _, mtime in entries), default=-1)


def plan_folders(listing):
    return sorted(listing, key=lambda rel: (-newest(listing[rel]), rel))


def safe_file(root, relative):
    """Also reject a directory that was replaced with a junction after listing."""
    rel = Path(relative)
    if (rel.anchor or not rel.parts or any(p.startswith(".") or p == "_deleted" for p in rel.parts)
            or rel.suffix.lower() not in EXTENSIONS):
        return None
    try:
        root = Path(root)
        path = root / rel
        # Compare resolved forms: a mapped network drive resolves to a UNC path and a junction root
        # resolves to its target, so the unresolved path never equals its resolved form there.
        base = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(base):
            return None
        current = path
        while current != root:
            if _link(current.lstat()):
                return None
            current = current.parent
        if path.is_file():
            return path
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def metadata_fields(meta, keys=(), exif=None):
    kind = meta.get("type")
    if any(key.startswith("naia_") for key in meta) or kind == "naia":
        source = NAIA
    elif {"prompt", "workflow", "workflow_api"}.intersection(keys) or kind == "comfyui":
        source = COMFYUI
    elif "parameters" in keys or exif or kind == "webui":
        source = WEBUI
    elif "Comment" in meta or kind == "nai" or meta.get("Software") == "NovelAI":
        source = NAI
    else:
        source = UNKNOWN
    params = meta.get("parameters")
    params = params if isinstance(params, dict) else {}
    try:
        seed = int(meta.get("seed", params.get("seed")))
        if not -(2**63) <= seed < 2**63:
            seed = None
    except (ValueError, TypeError, OverflowError):
        seed = None

    def text(*values):
        return next((v for v in values if isinstance(v, str) and v), "")

    prompt = text(meta.get("prompt"), meta.get("Description"), meta.get("ImageDescription"))
    characters = meta.get("characters")
    chars = [v for v in characters if isinstance(v, str)] if isinstance(characters, list) else []
    return dict(source=source, seed=seed, model=text(meta.get("model"), params.get("model"), meta.get("Source")),
                prompt=prompt, negative=text(meta.get("uc"), meta.get("negative_prompt"), meta.get("negative")),
                chars=chars, tags=prompt_tags(prompt, chars))


def _read_row(root, rel, directory, entry):
    name, size, mtime = entry
    item = dict(dir_id=directory, name=name, size=size, mtime_ns=mtime)
    try:
        # The entry comes from list_tree, which never follows links inside the root, so the plain path
        # is used here. safe_file (resolve + walk per file) tripled the per-file cost and is kept for
        # serving files (/file route, decode backfill) where the path is not fresh from a listing.
        path = Path(root) / rel / name
        head = read_head(path)
        meta = parse_metadata_texts(head.texts, head.exif_user_comment, (head.width, head.height))
        flag = META_HEAD if head.texts or head.exif_user_comment else NEEDS_DECODE if head.alpha else NO_META
        item.update(metadata_fields(meta or {}, head.texts, head.exif_user_comment),
                    width=head.width, height=head.height, flags=EXIST | flag)
    except (OSError, ValueError):
        item["flags"] = EXIST | READ_ERROR
    return item


def publish(store, bits, rows, replaced, missing=()):
    """Caller holds the publication lock. add_rows tombstones replacements atomically."""
    if rows:
        numbers = store.add_rows(rows)
        for old in replaced:
            bits.set_dead(old)
        bits.append(store.iter_rows(numbers[0]))
    if missing:
        store.mark_dead(missing)
        for old in missing:
            bits.set_dead(old)


def folder_batches(store, bits, root_id, folder_rel, entries, now, *, lock=None, saved=None):
    """Yield after each committed batch, never holding a lock across a yield.

    saved contains files published by priority notifications since the listing;
    the older snapshot must neither replace those rows nor tombstone them.
    """
    lock = lock or nullcontext()
    saved = saved if saved is not None else set()
    root = next(r["path"] for r in store.roots() if r["id"] == root_id)
    directory = store.get_or_create_dir(root_id, folder_rel)
    store.set_state(directory, 1)
    live = store.live_files(directory)
    retry = {r[0] for r in store._db.execute(
        "SELECT row FROM files WHERE dir_id=? AND flags & 1 AND flags & ?", (directory, READ_ERROR))}
    remaining = live.keys() - {name for name, _, _ in entries}
    for start in range(0, len(entries), BATCH_SIZE):
        rows, replaced = [], []
        for entry in entries[start:start+BATCH_SIZE]:
            name = entry[0]
            old = live.get(name)
            if (root_id, folder_rel, name) in saved or (old and old[1:] == entry[1:] and old[0] not in retry):
                continue
            rows.append(_read_row(root, folder_rel, directory, entry))
            if old:
                replaced.append(old[0])
        with lock:
            publish(store, bits, rows, replaced)
        yield {"read": len(rows), "removed": 0}
    missing = list(remaining)
    for start in range(0, len(missing), BATCH_SIZE):
        removed = [live[name][0] for name in missing[start:start+BATCH_SIZE]
                   if (root_id, folder_rel, name) not in saved]
        with lock:
            publish(store, bits, [], [], removed)
        yield {"read": 0, "removed": len(removed)}
    with lock:
        count = store._db.execute("SELECT count(*) FROM files WHERE dir_id=? AND flags & 1", (directory,)).fetchone()[0]
        with store._db:
            store._db.execute("UPDATE dirs SET state=2,files=?,done_at=? WHERE id=?", (count, now() if callable(now) else now, directory))
    yield {"read": 0, "removed": 0}


def index_folder(store, bits, root_id, folder_rel, entries, now):
    stats = {"read": 0, "removed": 0}
    for batch in folder_batches(store, bits, root_id, folder_rel, entries, now):
        for key in stats:
            stats[key] += batch[key]
    return stats


def index_saved(store, bits, lock, root, relative):
    path = safe_file(root["path"], relative)
    if path is None:
        return None
    st = path.stat()
    rel = relative.parent.as_posix() if relative.parent.parts else ""
    directory = store.get_or_create_dir(root["id"], rel)
    old = store._db.execute("SELECT row,size,mtime_ns,flags FROM files WHERE dir_id=? AND name=? AND flags & 1",
                            (directory, path.name)).fetchone()
    entry = (path.name, st.st_size, st.st_mtime_ns)
    if not old or old[1:3] != entry[1:] or old[3] & READ_ERROR:
        item = _read_row(root["path"], rel, directory, entry)
        with lock:
            publish(store, bits, [item], [old[0]] if old else [])
            if not old:
                with store._db:
                    store._db.execute("UPDATE dirs SET files=files+1 WHERE id=?", (directory,))
    return root["id"], rel, path.name
