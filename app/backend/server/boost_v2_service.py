"""Boost v2 앱 레이어 — 설정 로드, llama-server 런타임 싱글턴, 랜덤 결과에 끼우기.

Auto Boost 는 이것 하나다(Ollama 파이프라인은 2026-09-26 회수). 켜기/끄기는 세션 토글(``context.ollama_auto_boost``
— 이름만 옛것)을 쓴다. 엔진은 Assist v2 와 함께 쓴다(누가 쓰는지는 임대로 센다 — core/llama_runtime).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

_RUNTIME_LOCK = threading.Lock()
# 처음 쓰는 모델 · 장치는 첫 요청에 셰이더 준비가 붙는다(5090 실측 2026-09-26: E2B 34초 · 26B 로드 23초 + 42초, 두 번째
# 실행부터 1~2초 — 드라이버가 디스크에 캐시한다). 요청의 제한시간(60초)에 걸리지 않게 받은 직후 · 바꾼 직후 뒤에서 태운다.
PRIME_TIMEOUT = 240.0
PRIME_LEASE_SECONDS = 600.0


def _save_root(context: Any) -> Path:
    runtime_paths = getattr(context, "runtime_paths", None)
    save_dir = getattr(runtime_paths, "save_dir", None)
    if save_dir:
        return Path(save_dir)
    return Path(getattr(context, "repo_root", ".")) / "save"


def boost_v2_settings(context: Any) -> dict[str, Any]:
    """매 호출 디스크에서 읽는다(모드별 PE 캐시 staleness 회피 — 전역 설정이라 모드 캐시에 싣지 않는다)."""
    from core.boost_v2 import load_boost_v2_settings, normalize_boost_v2_settings

    try:
        return load_boost_v2_settings(save_root=_save_root(context))
    except Exception:
        return normalize_boost_v2_settings(None)


def get_boost_runtime(context: Any, settings: dict[str, Any] | None = None) -> Any:
    """세션 컨텍스트에 붙은 런타임 하나. 설정 경로가 바뀌면 다음 요청에서 새로 올린다."""
    from core.llama_runtime import LlamaServerRuntime, resolve_paths

    s = settings if settings is not None else boost_v2_settings(context)
    save_root = _save_root(context)
    engine, model = resolve_paths(s, repo_root=getattr(context, "repo_root", "."), save_root=save_root)
    use_gpu, device = _allocation(engine, s)
    with _RUNTIME_LOCK:
        runtime = getattr(context, "boost_llama_runtime", None)
        if runtime is None:
            # 유휴 내림 없음(idle_seconds=0) — Auto Boost 가 켜진 동안 계속 올려 둔다(llama_test 와 같다).
            # 매번 다시 올리면 호출마다 로드 ~2.6초가 붙는다(사용자 실측 "3초 느리다"). 끄기·백엔드 전환 때
            # Boost 의 임대를 놓는다 — 아무도 안 쥐면 그 자리에서 내리고, Assist 가 쥐고 있으면 그 임대가 끝날 때.
            runtime = LlamaServerRuntime(engine, model, idle_seconds=0, use_gpu=use_gpu, device=device,
                                         log_path=save_root / "logs" / "boost_llama_server.log")
            context.boost_llama_runtime = runtime
        else:
            runtime.configure(engine, model, use_gpu=use_gpu, device=device)
        return runtime


def _allocation(engine: Any, settings: dict[str, Any]) -> tuple[bool, str | None]:
    """설정의 할당 장치를 엔진 인자로: ('cpu' | GPU 없음) -> CPU, 그 밖엔 고른 GPU id."""
    from core.llama_runtime import choose_device, list_device_entries

    pref = str(settings.get("device") or "auto")
    entries = list_device_entries(engine) if pref != "cpu" else []
    if not entries:
        return False, None
    return True, choose_device(entries, pref)


def get_model_downloader(context: Any, model_id: Any = None) -> Any:
    """모델마다 다운로더 하나(없으면 설정에서 고른 모델). 대상은 설정/환경변수와 무관하게 **기본 모델 위치**다 —
    사용자가 다른 경로를 지정했다면 그 파일은 사용자가 관리한다."""
    from core.llama_model_download import LlamaModelDownloadService
    from core.llama_models import model_by_id

    model = model_by_id(model_id if model_id else boost_v2_settings(context).get("model"))
    with _RUNTIME_LOCK:
        downloaders = getattr(context, "llama_model_downloaders", None)
        if downloaders is None:
            downloaders = context.llama_model_downloaders = {}
        svc = downloaders.get(model.id)
        if svc is None:
            def _installed(model_id: str = model.id) -> None:
                # [받기] 를 눌렀다 = 그 모델을 쓰겠다 — 다 받으면 그 모델로 바꾸고(경로를 직접 지정했으면 그대로) 곧바로
                # 준비한다(첫 요청이 셰이더 준비를 기다리지 않게). 바꾸는 알림은 장치 변경과 같은 길(boost_v2_routes)이 받는다.
                from core.boost_v2 import save_boost_v2_settings

                current = boost_v2_settings(context)
                if current.get("model") != model_id and not current.get("model_path"):
                    save_boost_v2_settings({**current, "model": model_id}, save_root=_save_root(context))
                    try:
                        context.publish("boost_v2_device_changed", {"model": model_id})
                        return
                    except Exception:
                        pass
                prime_runtime(context)

            svc = downloaders[model.id] = LlamaModelDownloadService.for_model(model, _save_root(context),
                                                                             on_complete=_installed)
        return svc


def get_engine_installer(context: Any) -> Any:
    """엔진 받기(소스 체크아웃처럼 엔진이 동봉되지 않은 설치용). 대상은 기본 엔진 위치 — 경로를 직접 지정했으면
    그 엔진은 사용자가 관리한다."""
    from core.llama_engine_install import LlamaEngineInstallService
    from core.llama_runtime import default_engine_path

    with _RUNTIME_LOCK:
        svc = getattr(context, "llama_engine_installer", None)
        if svc is None:
            target = default_engine_path(getattr(context, "repo_root", ".")).parent
            svc = context.llama_engine_installer = LlamaEngineInstallService(
                target, on_complete=lambda: prime_runtime(context))
        return svc


def active_model_download(context: Any) -> Any:
    """지금 받는 중(또는 검증 중)인 다운로더 — 한 번에 하나만 받는다."""
    for svc in list((getattr(context, "llama_model_downloaders", None) or {}).values()):
        snap = svc.snapshot()
        if snap.get("active"):
            return svc
    return None


def start_model_download(context: Any, model_id: Any = None) -> dict[str, Any]:
    """모델 받기. 다른 모델을 받는 중이면 거절한다(3~14GB 를 둘씩 받지 않는다)."""
    svc = get_model_downloader(context, model_id)
    busy = active_model_download(context)
    if busy is not None and busy is not svc:
        return {**busy.snapshot(), "ok": False, "error": "다른 모델을 받는 중입니다 — 끝나거나 취소한 뒤에 받으세요."}
    return {**svc.start(), "ok": True}


def cancel_model_download(context: Any) -> dict[str, Any]:
    busy = active_model_download(context)
    return busy.cancel() if busy is not None else get_model_downloader(context).snapshot()


def boost_v2_status(context: Any) -> dict[str, Any]:
    """설정 화면용 상태: 설정 · 엔진/모델 경로와 존재 여부 · 모델 목록(설치 · 권장) · 실행 여부 · 다운로드 진행."""
    from core.llama_models import catalog, model_by_id
    from core.llama_runtime import default_engine_path, default_model_path, hardware_summary, resolve_paths

    settings = boost_v2_settings(context)
    save_root = _save_root(context)
    engine, model = resolve_paths(settings, repo_root=getattr(context, "repo_root", "."), save_root=save_root)
    runtime = getattr(context, "boost_llama_runtime", None)
    running = bool(runtime is not None and runtime.is_running())
    hardware = hardware_summary(engine)
    entries = hardware["gpus"]
    use_gpu, chosen = _allocation(engine, settings)
    rt = runtime.status() if runtime is not None else {}
    fallback = rt.get("gpu_failed") if rt.get("use_gpu") and rt.get("device") == chosen else None
    selected = model_by_id(settings.get("model"))
    active = active_model_download(context)
    return {
        "ok": True,
        "settings": settings,
        "engine_path": str(engine),
        "engine_ready": engine.is_file(),
        # 이 PC 의 할당 가능한 자원 · 설정의 할당 장치 · 실제로 고른 장치 · GPU 실패로 CPU 로 내려왔는지.
        "hardware": hardware,
        "device_pref": settings.get("device", "auto"),
        "gpu_devices": [entry["name"] for entry in entries],
        "gpu_device_entries": entries,
        "gpu_device_chosen": chosen,
        # '자동' 을 골랐다면 쓰게 될 장치(선택 목록의 설명용 — 지금 선택과 무관).
        "gpu_device_auto": _allocation(engine, {"device": "auto"})[1],
        "gpu_device_chosen_name": next((e["name"] for e in entries if e["id"] == chosen), ""),
        "engine_is_default": engine == default_engine_path(getattr(context, "repo_root", ".")),
        "engine_install": get_engine_installer(context).snapshot(),
        "use_gpu": use_gpu,
        "gpu_fallback": fallback,
        "swapping": bool(rt.get("stale")),
        "model_path": str(model),
        "model_ready": model.is_file(),
        "model_is_default": model == default_model_path(save_root, selected.id),
        # 고른 모델 · 목록(설치 여부 · 이 PC 에 맞는지). 경로를 직접 지정했으면 model_is_default=False — 그 파일이 쓰인다.
        "model_id": selected.id,
        "model_label": selected.label,
        # [CPU 모드 | GPU 모드] — 설정의 device 가 'cpu' 면 CPU, 아니면(자동 · GPU id) GPU. GPU 가 없으면 CPU 뿐.
        "mode": "gpu" if use_gpu else "cpu",
        "gpu_available": bool(entries),
        "models": catalog(save_root, hardware, chosen),
        "running": running,
        "priming": bool(getattr(context, "llama_priming", False)),
        "last_load_seconds": getattr(runtime, "last_load_seconds", None) if runtime is not None else None,
        # 받는 중이면 그 모델, 아니면 고른 모델의 다운로드 상태.
        "download": (active or get_model_downloader(context, selected.id)).snapshot(),
        "model_source": {"url": selected.url, "sha256": selected.sha256, "size": selected.size,
                         "license": selected.license, "ollama": selected.ollama_name},
    }


def warm_boost_runtime(context: Any) -> None:
    """Auto Boost 를 켤 때 엔진을 미리 올린다(백그라운드) — 첫 Random 이 로드를 기다리지 않게.
    켜져 있는 동안은 임대를 쥔다(Assist 가 엔진을 같이 쓴다 — 누가 쓰는지는 임대로 센다)."""
    def _warm() -> None:
        try:
            runtime = get_boost_runtime(context)
            runtime.hold("boost")
            if runtime.status().get("engine_exists") and runtime.status().get("model_exists"):
                runtime.warm()
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True, name="boost-v2-warm").start()


def prime_runtime(context: Any) -> bool:
    """고른 모델을 뒤에서 올리고 Assist 지시문을 한 번 태운다(처음 쓰는 모델 · 장치의 셰이더 준비 — ``PRIME_TIMEOUT``).
    이미 준비 중이거나 엔진 · 모델이 없으면 아무것도 안 한다. 준비하는 동안 ``context.llama_priming`` 이 참이다."""
    with _RUNTIME_LOCK:
        if getattr(context, "llama_priming", False):
            return False
        context.llama_priming = True

    def _run() -> None:
        try:
            runtime = get_boost_runtime(context)
            status = runtime.status()
            if not (status.get("engine_exists") and status.get("model_exists")):
                return
            runtime.hold("setup", PRIME_LEASE_SECONDS)   # 받자마자 쓸 공산이 크다 — 잠시 올려 둔다
            if runtime.warm(timeout=PRIME_TIMEOUT):
                from core.assist_v2 import SYSTEM_PROMPT, compact_grammar, user_message

                runtime.chat(user_message("안녕"), system=SYSTEM_PROMPT, grammar=compact_grammar(), max_tokens=80,
                             timeout=PRIME_TIMEOUT)
        except Exception:
            pass
        finally:
            context.llama_priming = False

    threading.Thread(target=_run, daemon=True, name="llama-prime").start()
    return True


def release_boost_runtime(context: Any) -> None:
    """Auto Boost 를 끄거나 백엔드를 바꿨다 — Boost 의 임대만 놓는다. Assist 가 방금 썼다면 그 임대가 끝날 때 내린다."""
    runtime = getattr(context, "boost_llama_runtime", None)
    if runtime is not None:
        try:
            runtime.release("boost")
        except Exception:
            pass


def stop_boost_runtime(context: Any) -> None:
    """[엔진 내리기] — 누가 쥐고 있든 지금 내린다(다음 요청이 다시 올린다)."""
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
    from core.boost_v2 import drop_color_tags, strip_weight_syntax

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


async def apply_boost_v2(
    context: Any, result: Any, settings: dict[str, Any], *, update_context: bool = True,
) -> bool:
    """랜덤 결과 프롬프트의 main 끝에 Boost v2 섹션을 붙인다. 실패하면 원문 그대로(raise 없음).

    성공 시 result.prompt · context.prompt_text · ctx.final_prompt 셋을 함께 갱신한다 — 화면 표시와
    실제 전송, 네거티브 조건부 바인딩(final_prompt 비교)이 모두 같은 문자열을 보게 하려는 것.
    ``update_context=False`` 면 context.prompt_text 는 건드리지 않는다(Auto Gen 다음 컷 미리 만들기 —
    소비할 때 설치한다).
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
        if update_context:
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
