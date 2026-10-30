"""Disposable, process-versioned autocomplete snapshots; never a source of tag data."""
from __future__ import annotations

import gc
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import pickle
import struct
import sys
import tempfile
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass

from core.kr_tag_loader import DICT_SOURCES, TAG_LOADER_OPTIONS, _unique_data_roots, enumerate_tag_inputs
from core.tag_search_index import TagSearchEntry, TagSearchIndex


MAGIC = b"NAIA_TAG_INDEX\x00"
FORMAT_VERSION = 1
MAX_HEADER_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
WRITE_DELAY_SECONDS = 30.0
CODE_FILES = (
    "core/kr_tag_loader.py",
    "core/tag_search_index.py",
    "core/named_entity_aliases.py",
    "core/tag_knowledge.py",
    "core/tag_axis_registry.py",
    "core/tag_relation_pack.py",
    "app/backend/server/autocomplete_commands.py",
    "core/tag_index_disk_cache.py",
)
STATE_TYPES = {
    "_entries": dict,
    "_blob_by_tag": dict,
    "_sorted_tags": tuple,
    "_term_to_tags": dict,
    "_noisy_metadata_tags": frozenset,
}
_source_lock = threading.Lock()
_source_baselines: dict[str, str] = {}


@dataclass(frozen=True)
class Fingerprint:
    value: str
    namespace: str
    repo_root: Path
    data_roots: tuple[Path, ...]
    options: dict[str, bool]


def _json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _module_origin(name: str, repo_root: Path) -> Path:
    module = sys.modules.get(name)
    if module is not None:
        spec = module.__spec__
        origin = Path(spec.origin).resolve()
        if Path(module.__file__).resolve() != origin:
            raise ValueError("module source mismatch")
        return origin
    # 사전 import 직전 로더가 넣는 repo 경로까지 같은 순서로 확인한다.
    if "." not in name and str(repo_root) not in sys.path:
        spec = importlib.machinery.PathFinder.find_spec(name, [str(repo_root)])
    else:
        spec = importlib.util.find_spec(name)
    return Path(spec.origin).resolve()


def _source_hashes(repo_root: Path) -> dict[str, str]:
    from core.tag_search_index import KR_METADATA_SEARCH_RULES_PATH

    hashes = {}
    for relative in (*CODE_FILES, *(f"{row[0]}.py" for row in DICT_SOURCES)):
        path = (repo_root / relative).resolve()
        name = relative[:-3].replace("/", ".")
        if _module_origin(name, repo_root) != path:
            raise ValueError("unexpected module origin")
        hashes[str(path)] = _hash_file(path)
    # 이미 import한 규칙/사전/코드의 hot update는 새 프로세스에서만 캐시한다.
    rules = KR_METADATA_SEARCH_RULES_PATH.resolve()
    hashes[str(rules)] = _hash_file(rules) if rules.exists() else "missing"
    with _source_lock:
        for path, digest in hashes.items():
            if _source_baselines.setdefault(path, digest) != digest:
                raise ValueError("source changed after import")
    return hashes


def _runtime_versions() -> dict:
    import pandas as pd
    from pandas.io.parquet import get_engine

    engine = pd.get_option("io.parquet.engine")
    versions = {
        "python": list(sys.version_info),
        "implementation": sys.implementation.name,
        "implementation_version": list(sys.implementation.version),
        "cache_tag": sys.implementation.cache_tag,
        "pandas": pd.__version__,
        "parquet_option": engine,
        "parquet_engine": type(get_engine(engine)).__name__,
    }
    for name in ("pyarrow", "fastparquet"):
        versions[name] = (importlib.import_module(name).__version__
                          if importlib.util.find_spec(name) is not None else None)
    return versions


def fingerprint(repo_root, data_roots=None, options=None) -> Fingerprint | None:
    """입력 오류/출처 불명은 캐시 비활성화다. 원본 로더의 오류 정책은 바꾸지 않는다."""
    try:
        root = Path(repo_root).resolve()
        roots = tuple(_unique_data_roots(root, data_roots))
        flags = dict(TAG_LOADER_OPTIONS if options is None else options)
        if set(flags) != set(TAG_LOADER_OPTIONS) or any(type(value) is not bool for value in flags.values()):
            return None
        namespace = hashlib.sha256(_json_bytes(
            [os.path.normcase(str(root)), [os.path.normcase(str(path)) for path in roots]],
        )).hexdigest()
        inputs = []
        for path, selected in enumerate_tag_inputs(root, roots):
            resolved = path.resolve()
            row = {"path": str(path), "target": str(resolved), "kind": "missing"}
            try:
                stat = resolved.stat()
            except FileNotFoundError:
                pass
            else:
                if not resolved.is_file():
                    return None
                row.update(kind="file", size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                if selected:
                    row["sha256"] = _hash_file(resolved)
            inputs.append(row)
        manifest = {"namespace": namespace, "inputs": inputs, "options": flags,
                    "code": _source_hashes(root), "runtime": _runtime_versions()}
        return Fingerprint(hashlib.sha256(_json_bytes(manifest)).hexdigest(), namespace, root, roots, flags)
    except Exception:
        return None


def cache_path(cache_dir, key: Fingerprint) -> Path:
    root = Path(cache_dir).resolve()
    directory = root / "tag_index"
    path = directory / f"autocomplete-{key.namespace[:16]}.cache"
    if (directory.is_symlink() or directory.resolve().parent != root
            or path.is_symlink() or path.resolve().parent != directory.resolve()):
        raise ValueError("cache path escapes cache directory")
    return path


class _RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) == ("core.tag_search_index", "TagSearchEntry"):
            return TagSearchEntry
        raise pickle.UnpicklingError("forbidden global")

    def persistent_load(self, pid):
        raise pickle.UnpicklingError("persistent ids are forbidden")


class _PayloadReader:
    def __init__(self, stream, length):
        self.stream = stream
        self.remaining = length

    def read(self, size=-1):
        size = self.remaining if size < 0 else min(size, self.remaining)
        data = self.stream.read(size)
        self.remaining -= len(data)
        return data

    def readline(self):
        data = self.stream.readline(self.remaining)
        self.remaining -= len(data)
        return data


def read_cache(cache_dir, key: Fingerprint):
    """길이/해시를 먼저 검증하고 __init__ 없이 eager state만 복원한다."""
    try:
        with cache_path(cache_dir, key).open("rb") as stream:
            if stream.read(len(MAGIC)) != MAGIC:
                return None
            header_size, = struct.unpack("<I", stream.read(4))
            if not 0 < header_size <= MAX_HEADER_BYTES:
                return None
            header = json.loads(stream.read(header_size))
            if header["format"] != FORMAT_VERSION or header["fingerprint"] != key.value:
                return None
            length = header["payload_length"]
            if type(length) is not int or not 0 < length <= MAX_PAYLOAD_BYTES:
                return None
            start = stream.tell()
            if os.fstat(stream.fileno()).st_size != start + length:
                return None
            digest = hashlib.sha256()
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    return None
                digest.update(chunk)
                remaining -= len(chunk)
            if digest.hexdigest() != header["payload_sha256"] or stream.read(1):
                return None
            stream.seek(start)
            bounded = _PayloadReader(stream, length)
            # 수백만 개를 만드는 동안 순환 GC 가 거듭 전체를 훑는다 - 멈춰 두면 2.6 -> 1.4초(2026-10-30 실측).
            gc_enabled = gc.isenabled()
            gc.disable()
            try:
                payload = _RestrictedUnpickler(bounded).load()
            finally:
                if gc_enabled:
                    gc.enable()
            if bounded.remaining or type(payload) is not tuple or len(payload) != 2:
                return None
        raw, state = payload
        if type(raw) is not dict or type(state) is not dict or set(state) != set(STATE_TYPES):
            return None
        if any(type(state[name]) is not kind for name, kind in STATE_TYPES.items()):
            return None
        if len(raw) != header["raw_count"] or len(state["_entries"]) != header["entry_count"] or not raw:
            return None
        index = TagSearchIndex.__new__(TagSearchIndex)
        index.__dict__.update(state)
        index._metadata_index_lock = threading.Lock()
        index._metadata_term_to_tags = None
        index._metadata_terms_by_tag = {}
        index._metadata_text_by_tag = {}
        # 세션 내내 사는 색인이다 - 영구 세대로 옮겨 이후 GC 가 다시 훑지 않게(이름 색인 1.1 -> 0.4초).
        gc.freeze()
        return raw, index
    except Exception:
        return None


class _PayloadWriter:
    def __init__(self, stream):
        self.stream = stream
        self.length = 0
        self.digest = hashlib.sha256()

    def write(self, data):
        self.length += len(data)
        if self.length > MAX_PAYLOAD_BYTES:
            raise ValueError("cache payload too large")
        self.digest.update(data)
        return self.stream.write(data)


def write_cache(cache_dir, key: Fingerprint, raw: dict, index: TagSearchIndex) -> bool:
    """동일 디렉터리의 고유 temp만 소유한다. 실패하면 이전 캐시는 그대로 둔다."""
    temporary = None
    try:
        current = fingerprint(key.repo_root, key.data_roots, key.options)
        if not raw or current is None or current.value != key.value:
            return False
        state = {name: getattr(index, name) for name in STATE_TYPES}
        path = cache_path(cache_dir, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(MAGIC + struct.pack("<I", MAX_HEADER_BYTES) + b" " * MAX_HEADER_BYTES)
            payload = _PayloadWriter(stream)
            pickle.dump((raw, state), payload, protocol=5)
            header = _json_bytes({
                "format": FORMAT_VERSION, "fingerprint": key.value,
                "raw_count": len(raw), "entry_count": len(state["_entries"]),
                "payload_length": payload.length, "payload_sha256": payload.digest.hexdigest(),
            })
            if len(header) > MAX_HEADER_BYTES:
                return False
            stream.seek(len(MAGIC) + 4)
            stream.write(header.ljust(MAX_HEADER_BYTES, b" "))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return True
    except Exception:
        return False
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _delayed_write(context, key, raw, index, slot=None):
    try:
        while not getattr(context, "headless_tag_index_warmup_done", False):
            time.sleep(0.25)
        # 완료 시각을 늦게 관측해도 괜찮다. 요청/베일은 이 스레드를 기다리지 않는다.
        deadline = time.monotonic() + WRITE_DELAY_SECONDS
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(remaining)
        with slot() if slot is not None else nullcontext():
            # 슬롯 대기 중 재설치로 색인이 바뀔 수 있어 획득 뒤에 확인한다.
            if context.kr_tags_raw is raw and context.tag_search_index is index:
                write_cache(context.runtime_paths.cache_dir, key, raw, index)
    except Exception:
        pass


def schedule_write(context, key, raw, index, slot=None):
    """호출자는 context의 tag-index 잠금을 보유한다. context당 pending write는 하나다."""
    try:
        thread = getattr(context, "_tag_cache_write_thread", None)
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=_delayed_write, args=(context, key, raw, index, slot),
                                  daemon=True, name="naia-tag-index-cache-write")
        context._tag_cache_write_thread = thread
        thread.start()
    except Exception:
        pass
