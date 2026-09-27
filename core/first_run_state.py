"""첫 설치에서 한 번만 하는 일 - 검색 풀이 처음 채워지면 Tag Filter 에 "1girl, solo" (사용자 지정 2026-09-27).

새로 받은 NAIA 는 검색 풀이 비어 있다. 태그 데이터를 받은 뒤 풀이 처음으로 채워질 때(태그 아카이브의 마지막
조각 하나 - `runner_parquet_sources` 의 끝) 그 풀에 Tag Filter "1girl, solo" 를 걸고, 화면은 Tag Filter 창을
한 번 연다. **풀을 다 읽은 뒤에** 건다 - 비어 있는 풀에 칩만 걸면 아무 일도 없다(사용자 지적).

'첫 설치' 판정 = 기동할 때 태그 아카이브가 **하나도 없다**. 표식(`save/first_run.json`)에 한 번 적고 끝:
  pending  아카이브 없이 켜졌다(새 설치) - 풀이 처음 채워질 때 건다
  skip     아카이브를 가진 채 켜졌다(기존 사용자) - 업데이트했다고 필터가 갑자기 걸리지 않는다
  done     한 번 처리했다
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any

MARKER_NAME = "first_run.json"
FIRST_RUN_TAG_FILTER = ("1girl", "solo")

_LOCK = threading.Lock()


def _marker_path(context: Any):
    return context._save_path(MARKER_NAME)


def _read(context: Any) -> dict[str, Any]:
    try:
        data = json.loads(_marker_path(context).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write(context: Any, data: dict[str, Any]) -> None:
    path = _marker_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def note_startup(context: Any) -> str:
    """기동 때 한 번 - 표식이 없으면 지금 상태로 정한다(아카이브 없음 = pending, 있음 = skip)."""
    with _LOCK:
        state = _read(context).get("tag_filter")
        if state in ("pending", "skip", "done"):
            return state
        sources = getattr(context, "tag_archive_parquet_sources", None)
        try:
            has_archive = bool(sources()) if callable(sources) else True
        except Exception:
            has_archive = True          # 모르면 기존 사용자로 본다 - 멀쩡한 풀에 필터를 걸지 않는다
        state = "skip" if has_archive else "pending"
        _write(context, {"tag_filter": state, "at": _now()})
        return state


def consume(context: Any, *, apply: bool) -> bool:
    """풀이 디스크에서 처음 채워졌다. pending 이면 done 으로 넘기고, `apply` 면 Tag Filter 를 건다.

    `apply` 는 그 풀이 태그 아카이브 조각에서 왔을 때만 참이다 - 가져온 옛 설치의 마지막 검색 등이
    먼저 채워졌으면 사용자의 것이라 건드리지 않고 끝낸다. 걸었으면 True.
    """
    with _LOCK:
        if _read(context).get("tag_filter") != "pending":
            return False
        applied = False
        if apply and not _user_has_filter(context):
            context.save_search_filter_state(
                tag_filter=list(FIRST_RUN_TAG_FILTER), tag_filter_exclude=[], tag_filter_active=True,
            )
            context.first_run_tag_filter_notice = True
            applied = True
        _write(context, {"tag_filter": "done", "at": _now(), "applied": applied})
        return applied


def _user_has_filter(context: Any) -> bool:
    """풀이 채워지기 전에 사용자가 검색어나 Tag Filter 를 이미 걸었으면 그것이 이긴다."""
    normalize = getattr(context, "normalize_search_filter_state", None)
    raw = getattr(context, "search_filter_state", None)
    state = normalize(raw) if callable(normalize) else (raw if isinstance(raw, dict) else {})
    return bool(state.get("query") or state.get("exclude") or state.get("tag_filter")
                or state.get("tag_filter_exclude") or state.get("tag_filter_branches")
                or state.get("tag_filter_applied_branches"))


def take_notice(context: Any) -> bool:
    """화면이 Tag Filter 창을 열 차례인가 - **한 번만** 참이다(`get_search_state` 응답이 싣는다)."""
    if getattr(context, "first_run_tag_filter_notice", False):
        context.first_run_tag_filter_notice = False
        return True
    return False
