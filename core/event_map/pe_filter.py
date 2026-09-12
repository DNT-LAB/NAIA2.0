# -*- coding: utf-8 -*-
"""이벤트 맵 후보·실제 조합에 **사용자의 프롬프트 엔지니어링 설정**을 비춰 본다.

사용자가 "Remove Clothing" 을 켜 두었거나 Auto-Hide 에 `loli` 를 적어 두었으면, 맵이 보여 주는
태그 중 그것들은 생성 때 어차피 빠진다. 그 사실을 화면에서 미리 보여 주려고(진한 회색), 태그
목록을 받아 **어느 라운드가 지우는지**를 돌려준다. 사용자 지정 2026-09-12 밤.

⚠️ 설정 **파일을 읽지 않는다.** Quick Preset 이 걸려 있으면 파일에는 프리셋 적용 전 값이 들어
   있다 - `headless_v5_scene_service._pe_options` 가 같은 이유로 훅의 `_current_options` 를 쓴다.
   여기서도 그 입구를 쓴다(이벤트 스트림 freeze · 세션 override · 로드된 모듈 순).
⚠️ 거르는 규칙은 새로 쓰지 않는다. 생성이 쓰는 `apply_tag_filters` 를 **그대로** 돌리고
   `filter_log` 만 읽는다 - 규칙을 베끼면 언젠가 화면과 생성이 어긋난다.
"""
from __future__ import annotations

from typing import Any

from core.tag_filter_helpers import apply_tag_filters

MAX_TAGS = 400


def _pe_options(context: Any) -> dict[str, Any]:
    try:
        from core.prompt_engineering_runtime import PromptEngineeringHeadlessPostHook

        return PromptEngineeringHeadlessPostHook(context)._current_options() or {}
    except Exception:
        return {}


def _category_overrides(context: Any) -> dict[str, Any]:
    try:
        from core.prompt_engineering_runtime import PromptEngineeringHeadlessPostHook

        return PromptEngineeringHeadlessPostHook(context)._category_filter_overrides() or {}
    except Exception:
        return {}


def _filter_manager(context: Any):
    try:
        from core.headless_random_prompt_service import ensure_filter_data_manager

        return ensure_filter_data_manager(context)
    except Exception:
        return getattr(context, "filter_data_manager", None)


def hidden_by_prompt_engineering(context: Any, tags: list[str]) -> dict[str, Any]:
    """`tags` 중 지금 설정이 지우는 것 -> `{tag: 라운드 이름}`.

    돌려주는 것:
        hidden   {tag: name}   지워지는 태그와 어느 라운드가 지웠는지("Auto Hide", "의상", ...)
        enabled  [key, ...]    켜져 있는 라운드 키(화면 설명용)
        dictionary bool        사전(filter_data_manager)이 있었나 - 없으면 Auto Hide 만 본 것이다
    """
    clean: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        t = str(tag or "").strip()
        if t and t not in seen:
            seen.add(t)
            clean.append(t)
    options = _pe_options(context)
    checkbox = dict(options.get("preprocessing_options") or {})
    auto_hide = [str(x) for x in (options.get("auto_hide") or []) if str(x).strip()]
    manager = _filter_manager(context)
    main = list(clean)
    removed: list[str] = []
    result = apply_tag_filters(
        main, removed, checkbox, auto_hide, manager,
        category_overrides=_category_overrides(context),
    )
    hidden: dict[str, str] = {}
    enabled: list[str] = []
    for entry in result.get("filter_log") or []:
        key = str(entry.get("key") or "")
        if entry.get("enabled") and key not in ("auto_hide", "category_hide"):
            enabled.append(key)
        name = str(entry.get("name") or key)
        for tag in entry.get("removed") or []:
            hidden.setdefault(str(tag), name)
    return {
        "ok": True,
        "hidden": hidden,
        "enabled": enabled,
        "dictionary": manager is not None,
        "auto_hide_count": len(auto_hide),
    }
