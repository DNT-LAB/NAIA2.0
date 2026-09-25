"""Custom Parquet 라이브러리 - '이 파일에 무엇이 들었나' 를 파일과 함께 들고 다닌다.

사용자 제보(2026-09-21): 저장한 parquet 에 무엇이 들었는지 알 수 없다(가장 큰 개선점).

- **명함**: 저장할 때 parquet 스키마 메타데이터의 ``naia`` 키에 JSON 을 넣는다
  ``{v, created_at, source, recipe, rows}``. 파일 하나가 제 출처를 들고 다닌다(사이드카 없음).
  pandas 가 쓰는 ``pandas`` 키와 함께 둔다 - 다시 읽어도 dtype 이 그대로다.
- **목록**: 행 수·명함은 파일 **꼬리(footer)** 만 읽는다. ``(이름, mtime, 크기)`` 로 캐시.
- **기존 파일은 고쳐 쓰지 않는다** - 명함이 없으면 "조건 기록 없음" 이다.
- **삭제 = 휴지통**: ``custom_tags/.trash/`` 로 옮긴다(되살릴 수 있다, 사용자 결정 D1).

출처(provenance) 레시피 모양 - 프론트가 요약해 보여 준다:
  search    {source, query, exclude, ratings, bucket:[s,e], period:"YYYY/MM~YYYY/MM"}
  file      {source, name, recipe}              - 불러온 파일(그 파일의 명함 recipe 를 품는다)
  merge     {source, parts:[...]}               - 합치기(평평하게 펴서 상한까지)
  refine    {source, parent, query, exclude, ratings, filters}
  export    {source, parent, ratings, tag_filter:{include, exclude}}  - 조건을 걸어 저장
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

NAIA_META_KEY = b"naia"
META_VERSION = 1
TRASH_DIR = ".trash"
_MAX_MERGE_PARTS = 24          # 합치기 명함이 끝없이 불지 않게
_MAX_RECIPE_BYTES = 64 * 1024  # 명함 상한(스키마 메타데이터는 작아야 한다)

_DESCRIBE_CACHE: dict[str, tuple[tuple[str, int, int], dict[str, Any]]] = {}
_DESCRIBE_LOCK = threading.Lock()


# ---- 명함 쓰기/읽기 ------------------------------------------------------------
def make_meta(source: str, recipe: dict[str, Any] | None, rows: int) -> dict[str, Any]:
    return {
        "v": META_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": str(source or ""),
        "recipe": _bounded(recipe),
        "rows": int(rows),
    }


def _bounded(recipe: Any) -> Any:
    """명함이 너무 크면 부모 사슬을 잘라 낸다(최신 조건은 남긴다)."""
    try:
        text = json.dumps(recipe, ensure_ascii=False, default=str)
    except Exception:
        return None
    if len(text.encode("utf-8")) <= _MAX_RECIPE_BYTES:
        return recipe
    if isinstance(recipe, dict):
        trimmed = {k: v for k, v in recipe.items() if k not in ("parent", "parts", "recipe")}
        trimmed["truncated"] = True
        return trimmed
    return None


def write_parquet(frame: Any, path: Path, meta: dict[str, Any] | None = None) -> None:
    """``frame.to_parquet(path, index=False)`` 과 같은 파일 + 명함. 원자적 교체(tmp → replace)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    table = pa.Table.from_pandas(frame, preserve_index=False)
    if meta is not None:
        merged = dict(table.schema.metadata or {})
        merged[NAIA_META_KEY] = json.dumps(meta, ensure_ascii=False, default=str).encode("utf-8")
        table = table.replace_schema_metadata(merged)
    pq.write_table(table, tmp)
    os.replace(tmp, path)


def read_meta(path: Path) -> dict[str, Any] | None:
    """명함(없거나 깨졌으면 None). 파일 꼬리만 읽는다."""
    try:
        import pyarrow.parquet as pq

        raw = (pq.read_schema(path).metadata or {}).get(NAIA_META_KEY)
        if not raw:
            return None
        meta = json.loads(raw.decode("utf-8"))
        return meta if isinstance(meta, dict) else None
    except Exception:
        return None


# ---- 목록 ------------------------------------------------------------------------
def describe(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return {"name": path.name, "missing": True}
    key = (path.name, int(st.st_mtime_ns), int(st.st_size))
    with _DESCRIBE_LOCK:
        hit = _DESCRIBE_CACHE.get(str(path))
        if hit is not None and hit[0] == key:
            return dict(hit[1])
    rows = None
    try:
        import pyarrow.parquet as pq

        rows = int(pq.read_metadata(path).num_rows)
    except Exception:
        rows = None
    meta = read_meta(path)
    card = {
        "name": path.name,
        "rows": rows,
        "size": int(st.st_size),
        "mtime": int(st.st_mtime),
        "source": (meta or {}).get("source"),
        "recipe": (meta or {}).get("recipe"),
        "created_at": (meta or {}).get("created_at"),
        "has_meta": meta is not None,
    }
    with _DESCRIBE_LOCK:
        _DESCRIBE_CACHE[str(path)] = (key, card)
    return dict(card)


def list_library(directory: Path) -> list[dict[str, Any]]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    paths = sorted(p for p in directory.glob("*.parquet") if p.is_file())
    return [describe(p) for p in paths]


# ---- 관리 ------------------------------------------------------------------------
def _safe_name(name: str) -> str | None:
    """경로 탈출·빈 이름·확장자 누락을 거른다. 확장자는 붙여 준다."""
    raw = str(name or "").strip()
    clean = Path(raw).name
    if not clean or clean != raw or clean.startswith("."):
        return None
    if not clean.lower().endswith(".parquet"):
        clean += ".parquet"
    if any(ch in clean for ch in '<>:"/\\|?*'):
        return None
    return clean


def rename(directory: Path, old: str, new: str) -> tuple[bool, str]:
    """(성공, 새 이름 또는 오류 사유). 덮어쓰기는 하지 않는다."""
    directory = Path(directory)
    src_name, dst_name = _safe_name(old), _safe_name(new)
    if src_name is None:
        return False, "invalid_source"
    if dst_name is None:
        return False, "invalid_name"
    src, dst = directory / src_name, directory / dst_name
    if not src.is_file():
        return False, "not_found"
    if src_name == dst_name:
        return True, dst_name
    # 대소문자만 바꾸는 이름 변경(Windows)은 같은 파일이라 exists 가 참이다 - 그건 허용한다.
    if dst.exists() and not (src_name.lower() == dst_name.lower()):
        return False, "exists"
    os.replace(src, dst)
    return True, dst_name


def trash(directory: Path, name: str) -> tuple[bool, str]:
    """휴지통으로 옮긴다. (성공, 휴지통 안의 이름 또는 오류 사유)."""
    directory = Path(directory)
    clean = _safe_name(name)
    if clean is None:
        return False, "invalid_name"
    src = directory / clean
    if not src.is_file():
        return False, "not_found"
    bin_dir = directory / TRASH_DIR
    bin_dir.mkdir(parents=True, exist_ok=True)
    dst = bin_dir / clean
    if dst.exists():
        dst = bin_dir / f"{src.stem}_{time.strftime('%Y%m%d_%H%M%S')}{src.suffix}"
        n = 2
        while dst.exists():
            dst = bin_dir / f"{src.stem}_{time.strftime('%Y%m%d_%H%M%S')}_{n}{src.suffix}"
            n += 1
    shutil.move(str(src), str(dst))
    return True, dst.name


# ---- 출처 레시피 --------------------------------------------------------------------
def merge_recipe(current: Any, added: Any) -> dict[str, Any]:
    parts: list[Any] = []
    for item in (current, added):
        if isinstance(item, dict) and item.get("source") == "merge":
            parts.extend(item.get("parts") or [])
        elif item:
            parts.append(item)
    if len(parts) > _MAX_MERGE_PARTS:
        parts = parts[: _MAX_MERGE_PARTS - 1] + [{"source": "more", "count": len(parts) - _MAX_MERGE_PARTS + 1}]
    return {"source": "merge", "parts": parts}


def file_recipe(path: Path) -> dict[str, Any]:
    meta = read_meta(path)
    return {"source": "file", "name": Path(path).name, "recipe": (meta or {}).get("recipe")}
