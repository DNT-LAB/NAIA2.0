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


def _grounding_tags(result: Any) -> str:
    """조건부까지 반영된 main 스냅샷(boost_v2_main_tags). 없으면 main_tags. 가중치는 벗긴다.
    캐릭터 프롬프트·prefix/postfix 는 넣지 않는다(사양: 초기엔 랜덤 프롬프트만)."""
    from core.scene_boost import strip_weight_syntax

    ctx = getattr(result, "context", None)
    if ctx is None:
        return ""
    meta = getattr(ctx, "metadata", None) or {}
    tags = meta.get("boost_v2_main_tags")
    if not (isinstance(tags, list) and any(str(t).strip() for t in tags)):
        tags = list(getattr(ctx, "main_tags", None) or [])
    return strip_weight_syntax(", ".join(str(t) for t in tags))


def _record(result: Any, payload: dict[str, Any]) -> None:
    ctx = getattr(result, "context", None)
    meta = getattr(ctx, "metadata", None) if ctx is not None else None
    if isinstance(meta, dict):
        meta["boost_v2"] = payload


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
        tags = _grounding_tags(result)
        if not tags:
            return False
        instruction = build_instruction(tags, settings)
        runtime = get_boost_runtime(context, settings)
        resp = await asyncio.to_thread(runtime.chat, instruction)
        if not resp.get("ok"):
            _record(result, {"ok": False, "error": resp.get("error"), "elapsed": resp.get("elapsed")})
            return False
        is_nai = str(getattr(context, "current_api_mode", "") or "").upper() == "NAI"
        addition = format_output(resp.get("text", ""), is_nai=is_nai)
        if not addition:
            _record(result, {"ok": False, "error": "빈 응답"})
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
        _record(result, {
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
