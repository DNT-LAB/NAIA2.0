"""Boost v2 앱 레이어 — 설정 로드, llama-server 런타임 싱글턴, 랜덤 결과에 끼우기.

Ollama Chat(Assist)과 아무것도 공유하지 않는다: 서비스·모델 선택·큐·상주 관리가 전부 따로다.
켜기/끄기는 기존 세션 토글(``context.ollama_auto_boost``)을 쓰고, 설정의 ``backend`` 가
``"llamacpp"`` 일 때만 이 경로가 돈다.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

_RUNTIME_LOCK = threading.Lock()


def _save_root(context: Any) -> Path:
    runtime_paths = getattr(context, "runtime_paths", None)
    save_dir = getattr(runtime_paths, "save_dir", None)
    if save_dir:
        return Path(save_dir)
    return Path(getattr(context, "repo_root", ".")) / "save"


def boost_v2_settings(context: Any) -> dict[str, Any]:
    """매 호출 디스크에서 읽는다(모드별 PE 캐시 staleness 회피 — ollama_boost_settings 와 같은 이유)."""
    from core.boost_v2 import load_boost_v2_settings, normalize_boost_v2_settings

    try:
        return load_boost_v2_settings(save_root=_save_root(context))
    except Exception:
        return normalize_boost_v2_settings(None)


def boost_v2_selected(context: Any, settings: dict[str, Any] | None = None) -> bool:
    """백엔드로 llama.cpp 가 골라졌는가(토글 ON 여부와 별개)."""
    try:
        s = settings if settings is not None else boost_v2_settings(context)
        return s.get("backend") == "llamacpp"
    except Exception:
        return False


def get_boost_runtime(context: Any, settings: dict[str, Any] | None = None) -> Any:
    """세션 컨텍스트에 붙은 런타임 하나. 설정 경로가 바뀌면 다음 요청에서 새로 올린다."""
    from core.llama_runtime import LlamaServerRuntime, resolve_paths

    s = settings if settings is not None else boost_v2_settings(context)
    save_root = _save_root(context)
    engine, model = resolve_paths(s, repo_root=getattr(context, "repo_root", "."), save_root=save_root)
    with _RUNTIME_LOCK:
        runtime = getattr(context, "boost_llama_runtime", None)
        if runtime is None:
            runtime = LlamaServerRuntime(engine, model, log_path=save_root / "logs" / "boost_llama_server.log")
            context.boost_llama_runtime = runtime
        else:
            runtime.configure(engine, model)
        return runtime


def stop_boost_runtime(context: Any) -> None:
    runtime = getattr(context, "boost_llama_runtime", None)
    if runtime is not None:
        try:
            runtime.stop()
        except Exception:
            pass


def _color_list(context: Any) -> list[str]:
    """PE "색상" 라운드와 같은 사전(color.txt). 매니저를 못 얻으면 파일을 직접 읽는다."""
    try:
        from core.headless_random_prompt_service import ensure_filter_data_manager

        manager = ensure_filter_data_manager(context)
        colors = list(getattr(manager, "color_list", None) or [])
        if colors:
            return colors
    except Exception:
        pass
    try:
        path = Path(getattr(context, "repo_root", Path(__file__).resolve().parents[3])) / "data" / "color.txt"
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return []


def _grounding_tags(context: Any, result: Any) -> str:
    """조건부까지 반영된 main 스냅샷(boost_v2_main_tags). 없으면 main_tags. 가중치는 벗기고
    색상 태그는 설정과 무관하게 뺀다. 캐릭터 프롬프트·prefix/postfix 는 넣지 않는다."""
    from core.boost_v2 import drop_color_tags
    from core.scene_boost import strip_weight_syntax

    ctx = getattr(result, "context", None)
    if ctx is None:
        return ""
    meta = getattr(ctx, "metadata", None) or {}
    tags = meta.get("boost_v2_main_tags")
    if not (isinstance(tags, list) and any(str(t).strip() for t in tags)):
        tags = list(getattr(ctx, "main_tags", None) or [])
    bare = [t for t in strip_weight_syntax(", ".join(str(t) for t in tags)).split(", ") if t]
    return ", ".join(drop_color_tags(bare, _color_list(context)))


def _record(context: Any, result: Any, payload: dict[str, Any]) -> None:
    """이미지 메타데이터(ctx.metadata)와 프롬프트 실행 기록(derived) 둘 다에 남긴다.
    실행 기록은 파이프라인 끝에 이미 저장돼 Boost 를 모르므로 derived 로 덧붙인다."""
    ctx = getattr(result, "context", None)
    meta = getattr(ctx, "metadata", None) if ctx is not None else None
    if isinstance(meta, dict):
        meta["boost_v2"] = payload
        run_id = str(meta.get("prompt_run_id") or "")
        recorder = getattr(context, "record_prompt_run_derived", None)
        if run_id and callable(recorder):
            try:
                recorder(run_id, {"boost_v2": payload})
            except Exception:
                pass


async def apply_boost_v2(context: Any, result: Any, settings: dict[str, Any]) -> bool:
    """랜덤 결과 프롬프트의 main 끝에 Boost v2 섹션을 붙인다. 실패하면 원문 그대로(raise 없음).

    성공 시 result.prompt · context.prompt_text · ctx.final_prompt 셋을 함께 갱신한다 — 화면 표시와
    실제 전송, 네거티브 조건부 바인딩(final_prompt 비교)이 모두 같은 문자열을 보게 하려는 것.
    """
    from core.boost_v2 import build_instruction, enabled_sections, format_output

    try:
        prompt = str(getattr(result, "prompt", "") or "")
        if not prompt.strip() or not enabled_sections(settings):
            return False
        tags = _grounding_tags(context, result)
        if not tags:
            return False
        instruction = build_instruction(tags, settings)
        runtime = get_boost_runtime(context, settings)
        resp = await asyncio.to_thread(runtime.chat, instruction)
        if not resp.get("ok"):
            _record(context, result, {"ok": False, "error": resp.get("error"), "elapsed": resp.get("elapsed")})
            return False
        is_nai = str(getattr(context, "current_api_mode", "") or "").upper() == "NAI"
        addition = format_output(resp.get("text", ""), is_nai=is_nai)
        if not addition:
            _record(context, result, {"ok": False, "error": "빈 응답"})
            return False
        from app.backend.server.generation_commands import _inject_boost_at_main

        new_prompt = _inject_boost_at_main(prompt, addition)
        if new_prompt == prompt:
            return False
        result.prompt = new_prompt
        context.prompt_text = new_prompt
        ctx = getattr(result, "context", None)
        if ctx is not None:
            try:
                ctx.final_prompt = new_prompt
            except Exception:
                pass
        _record(context, result, {
            "ok": True,
            "input": tags,
            "text": resp.get("text", ""),
            "elapsed": resp.get("elapsed"),
            "load_seconds": resp.get("load_seconds"),
            "usage": resp.get("usage"),
            "settings": {"sections": settings.get("sections"), "preferences": settings.get("preferences")},
        })
        return True
    except Exception:
        return False
