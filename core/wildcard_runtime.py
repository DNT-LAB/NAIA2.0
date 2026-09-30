"""headless 의 와일드카드 관리자 하나를 세우는 곳 - 만드는 길이 넷이라(Random 워밍업 · 입력창 전개 · PromptProcessor ·
캐릭터 굴림) 규칙을 여기 한 곳에 둔다.

⚠️ 청크(인스턴트 와일드카드, 'Chunk' 창)도 **여기서 함께 싣는다**(사용자 제보 2026-09-30: 와일드카드 Chunk 창을 한 번
   열어야 캐릭터 프롬프트가 제대로 나갔다). 데스크톱 AppContext 는 만들 때 청크를 실었는데(core/context.py 의
   apply_instant_wildcards_to_context), headless 는 Chunk · 인스턴트 창이 상태를 청할 때만 실었다 - 그 창을 열기 전까지
   관리자에 청크가 없어 청크를 쓰는 프롬프트가 풀리지 않았다.
⚠️ 관리자가 아직 없을 때(기동 직후 워밍업 전) 캐릭터를 굴리면 와일드카드가 글자 그대로 나갔다 - 캐릭터 굴림도 여기서
   세운다(character_settings.character_params_from_settings).
"""
from __future__ import annotations

import os
import weakref
from typing import Any


def runtime_wildcards_dir(context: Any):
    """포터블(사용자 데이터가 따로 있다)이면 그 wildcards, 아니면 None(= WildcardManager 의 기본 자리)."""
    runtime_paths = getattr(context, "runtime_paths", None)
    if runtime_paths is None or not (os.environ.get("NAIA_USER_DATA_DIR") or os.environ.get("NAIA_PORTABLE")):
        return None
    return getattr(runtime_paths, "wildcards_dir", None)


def ensure_wildcard_manager(context: Any):
    """context.wildcard_manager 를 돌려준다 - 없으면 만들고, 청크를 아직 안 실었으면 싣는다(관리자마다 한 번)."""
    manager = getattr(context, "wildcard_manager", None)
    if manager is None:
        from core.wildcard_manager import WildcardManager

        manager = WildcardManager(wildcards_dir=runtime_wildcards_dir(context))
        context.wildcard_manager = manager
    if getattr(manager, "_app_context_ref", None) is None:
        try:
            manager._app_context_ref = weakref.ref(context)
        except TypeError:
            pass
    sync_instant_wildcards(context, manager)
    return manager


def sync_instant_wildcards(context: Any, manager: Any) -> bool:
    """청크(인스턴트 와일드카드)를 관리자에 싣는다 - 관리자마다 한 번(실었으면 True).

    청크 저장소를 모르는 맥락(시험의 가짜 · 데스크톱)은 건너뛴다. 실패해도 생성은 막지 않는다 - 청크만 빠진다(예전과 같다).
    나중에 Chunk 창에서 고치면 그 창이 관리자에 다시 싣는다(HeadlessInstantWildcardService.store(force=True)).
    """
    if manager is None or getattr(manager, "_naia_instant_synced", False):
        return False
    load = getattr(context, "_instant_wildcard_store", None)
    apply = getattr(context, "_apply_instant_wildcard_to_manager", None)
    if not callable(load) or not callable(apply):
        return False
    try:
        store = load()
        tree = store.get("instant_wildcard_tree") if isinstance(store, dict) else None
        # store() 는 새로 읽을 때만 관리자에 싣고, 받아 둔 것이 있으면 싣지 않고 돌려준다(청크 창이 관리자보다 먼저
        # 열렸으면 그때는 관리자가 없어 맥락에만 남아 있었다) - 관리자에 없을 때만 한 번 더 싣는다(같은 것을 두 번 안 싣게)
        if getattr(manager, "instant_wildcard_tree", None) != (tree or {}):
            apply(store)
        manager._naia_instant_synced = True
        return True
    except Exception as exc:  # noqa: BLE001 - 청크를 못 실어도 생성은 계속한다
        print(f"Wildcard: chunk (instant wildcard) sync failed - {ascii(str(exc))}", flush=True)
        return False
