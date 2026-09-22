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
            # 유휴 내림 없음(idle_seconds=0) — Auto Boost 가 켜진 동안 계속 올려 둔다(llama_test 와 같다).
            # 매번 다시 올리면 호출마다 로드 ~2.6초가 붙는다(사용자 실측 "3초 느리다"). 끄기·백엔드 전환 때 내린다.
            runtime = LlamaServerRuntime(engine, model, idle_seconds=0,
                                         log_path=save_root / "logs" / "boost_llama_server.log")
            context.boost_llama_runtime = runtime
        else:
            runtime.configure(engine, model)
        return runtime


def get_model_downloader(context: Any) -> Any:
    """모델 다운로더 싱글턴. 대상은 설정/환경변수와 무관하게 **기본 모델 위치**다 —
    사용자가 다른 경로를 지정했다면 그 파일은 사용자가 관리한다."""
    from core.llama_model_download import LlamaModelDownloadService
    from core.llama_runtime import default_model_path

    with _RUNTIME_LOCK:
        svc = getattr(context, "boost_model_downloader", None)
        if svc is None:
            svc = LlamaModelDownloadService(default_model_path(_save_root(context)))
            context.boost_model_downloader = svc
        return svc


def boost_v2_status(context: Any) -> dict[str, Any]:
    """설정 화면용 상태: 설정 · 엔진/모델 경로와 존재 여부 · 실행 여부 · 다운로드 진행."""
    from core.llama_model_download import MODEL_SHA256, MODEL_SIZE, MODEL_URL
    from core.llama_runtime import default_model_path, resolve_paths

    settings = boost_v2_settings(context)
    save_root = _save_root(context)
    engine, model = resolve_paths(settings, repo_root=getattr(context, "repo_root", "."), save_root=save_root)
    runtime = getattr(context, "boost_llama_runtime", None)
    running = bool(runtime is not None and runtime.is_running())
    return {
        "ok": True,
        "settings": settings,
        "engine_path": str(engine),
        "engine_ready": engine.is_file(),
        "model_path": str(model),
        "model_ready": model.is_file(),
        "model_is_default": model == default_model_path(save_root),
        "running": running,
        "last_load_seconds": getattr(runtime, "last_load_seconds", None) if runtime is not None else None,
        "download": get_model_downloader(context).snapshot(),
        "model_source": {"url": MODEL_URL, "sha256": MODEL_SHA256, "size": MODEL_SIZE, "license": "Apache-2.0"},
    }


def warm_boost_runtime(context: Any) -> None:
    """Auto Boost 를 켤 때 엔진을 미리 올린다(백그라운드) — 첫 Random 이 로드를 기다리지 않게."""
    def _warm() -> None:
        try:
            runtime = get_boost_runtime(context)
            if runtime.status().get("engine_exists") and runtime.status().get("model_exists"):
                runtime.warm()
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True, name="boost-v2-warm").start()


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
        from core.boost_v2 import inject_block, prune_used_tags

        # 응답이 이미 쓴 입력 태그는 main 에서 걷어내고(인원수 태그 제외), 안 쓴 태그만 앞에 남긴다.
        pruned, removed = prune_used_tags(prompt, tags.split(", "), resp.get("text", ""))
        new_prompt = inject_block(pruned, addition)
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
            "removed_from_main": removed,
            "text": resp.get("text", ""),
            "elapsed": resp.get("elapsed"),
            "load_seconds": resp.get("load_seconds"),
            "usage": resp.get("usage"),
            "settings": {"sections": settings.get("sections"), "preferences": settings.get("preferences")},
        })
        return True
    except Exception:
        return False
