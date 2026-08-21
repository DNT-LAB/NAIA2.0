"""NAI Anlas 잔액 폴링 + 브로드캐스트 (헤드리스 웹 viewer pill).

171에서 desktop remote_api_server(QTimer)로 구현됐던 Anlas 5분 폴링이 headless
전환 시 유실됐다. 프론트(`anlasPill` + `onAnlasUpdate`)와 fetch 함수
(`core.api_verification.fetch_nai_anlas`)는 그대로 있으나 둘을 잇는 서버 폴링/
브로드캐스트가 없어 pill이 데이터를 받지 못했다. 이 모듈이 그 연결을 복원한다.

계약: `{"type": "anlas_update", "available": bool, "anlas": int, "fetched_at": str}`.
NAI 모드 + 토큰일 때만 available=True. Opus 등급도 Anlas를 소모하므로 무제한/∞
sentinel은 쓰지 않고 `fixedTrainingStepsLeft + purchasedTrainingSteps` 숫자만 노출.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.backend.server.websocket_broadcast import broadcast_json
from core import api_verification

ANLAS_POLL_INTERVAL_SECONDS = 300  # 5분


def _unavailable_payload() -> dict[str, Any]:
    return {"type": "anlas_update", "available": False, "anlas": 0, "fetched_at": ""}


def build_anlas_payload(context: Any) -> dict[str, Any]:
    """현재 모드/토큰 기준 Anlas 페이로드 (blocking — 스레드에서 호출)."""
    mode = str(context.get_api_mode() or "").upper()
    token = ""
    try:
        token = str(context.secure_token_manager.get_token("nai_token") or "").strip()
    except Exception:
        token = ""
    if mode != "NAI" or not token:
        return _unavailable_payload()
    try:
        value = api_verification.fetch_nai_anlas(token)
    except Exception as exc:  # pragma: no cover - 네트워크/응답 오류
        print(f"⚠️ Anlas 조회 실패: {exc}")
        value = None
    if value is None:
        return _unavailable_payload()
    return {
        "type": "anlas_update",
        "available": True,
        "anlas": int(value),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


async def broadcast_anlas(context: Any, clients: set) -> None:
    """접속 중인 클라이언트에 현재 Anlas 상태를 브로드캐스트 (없으면 skip)."""
    if not clients:
        return
    payload = await asyncio.to_thread(build_anlas_payload, context)
    await broadcast_json(clients, payload)


async def broadcast_anlas_if_vibe_encoded(context: Any, clients: set) -> None:
    """Storyteller Use Vibe 인코딩(2 Anlas) 직후 차감분이 pill에 즉시 반영되도록 1회
    재조회 브로드캐스트 — 인코딩이 일어날 수 있는 랜덤/자동 진행 경로가 generate 후
    호출한다(플래그 없으면 no-op, 네트워크 0)."""
    runtime = getattr(context, "event_stream_runtime", None)
    consume = getattr(runtime, "consume_anlas_refresh", None) if runtime is not None else None
    try:
        if callable(consume) and consume():
            await broadcast_anlas(context, clients)
    except Exception as exc:  # pragma: no cover - 잔액 갱신 실패가 생성 흐름을 막으면 안 됨
        print(f"⚠️ Use Vibe Anlas 갱신 실패: {exc}")


def _current_model_uses_usage_limit(context: Any) -> bool:
    """지금 고른 NAI 모델이 별도 사용량 한도를 쓰는가(= V5).

    ⚠️ 모델 키는 `context._current_model_key()` 로 읽는다. 처음엔 있지도 않은
    `get_generation_params()` 를 불렀는데, 아래 `except` 가 그 AttributeError 를
    삼켜 **항상 False** 가 됐다 - 배지가 영영 안 뜨는데 오류도 안 보였다(실측).
    """
    try:
        from core.nai_model_contract import resolve_nai_model_for_context

        key = context._current_model_key()
        return bool(resolve_nai_model_for_context(context, key).uses_opus_usage_limit)
    except Exception as exc:  # pragma: no cover - 조회 실패가 생성 흐름을 막으면 안 됨
        print(f"[warn] NAI usage-limit model check failed: {exc}")
        return False


def build_nai_usage_payload(context: Any) -> dict[str, Any]:
    """V5 Opus 사용량 한도 페이로드 (blocking — 스레드에서 호출).

    **V5 가 아니면 조회하지 않는다.** 배지는 V5 를 고른 동안에만 뜬다(사용자 지정
    2026-08-19). 계약:
    `{"type":"nai_usage_update","available":bool,"percent":int,
      "is_negative":bool,"seconds_until_next_percent":int,"fetched_at":str}`
    """
    unavailable = {
        "type": "nai_usage_update", "available": False, "percent": 0,
        "is_negative": False, "seconds_until_next_percent": 0, "fetched_at": "",
    }
    mode = str(context.get_api_mode() or "").upper()
    if mode != "NAI" or not _current_model_uses_usage_limit(context):
        return unavailable
    try:
        token = str(context.secure_token_manager.get_token("nai_token") or "").strip()
    except Exception:
        token = ""
    if not token:
        return unavailable
    try:
        usage = api_verification.fetch_nai_usage_limit(token)
    except Exception as exc:  # pragma: no cover - 네트워크/응답 오류
        print(f"[warn] NAI usage limit fetch failed: {exc}")
        usage = None
    if not usage:
        return unavailable
    return {
        "type": "nai_usage_update",
        "available": True,
        "percent": int(usage.get("percent", 0)),
        "is_negative": bool(usage.get("is_negative", False)),
        "seconds_until_next_percent": int(usage.get("seconds_until_next_percent", 0)),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_both_payloads(context: Any) -> list[dict[str, Any]]:
    """Anlas + V5 사용량을 **구독 조회 1회**로 만들어 둘 다 돌려준다."""
    anlas_off = _unavailable_payload()
    usage_off = {
        "type": "nai_usage_update", "available": False, "percent": 0,
        "is_negative": False, "seconds_until_next_percent": 0, "fetched_at": "",
    }
    mode = str(context.get_api_mode() or "").upper()
    try:
        token = str(context.secure_token_manager.get_token("nai_token") or "").strip()
    except Exception:
        token = ""
    if mode != "NAI" or not token:
        return [anlas_off, usage_off]

    try:
        summary = api_verification.fetch_nai_subscription_summary(token)
    except Exception as exc:  # pragma: no cover - 네트워크/응답 오류
        print(f"[warn] NAI subscription fetch failed: {exc}")
        return [anlas_off, usage_off]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    anlas_payload = anlas_off
    if summary.get("anlas") is not None:
        anlas_payload = {
            "type": "anlas_update", "available": True,
            "anlas": int(summary["anlas"]), "fetched_at": now,
        }
    usage_payload = usage_off
    usage = summary.get("usage")
    # 사용량 배지는 **V5 를 고른 동안에만** 뜬다.
    if usage and _current_model_uses_usage_limit(context):
        usage_payload = {
            "type": "nai_usage_update", "available": True,
            "percent": int(usage.get("percent", 0)),
            "is_negative": bool(usage.get("is_negative", False)),
            "seconds_until_next_percent": int(usage.get("seconds_until_next_percent", 0)),
            "fetched_at": now,
        }
    return [anlas_payload, usage_payload]


async def broadcast_anlas_and_usage(context: Any, clients: set) -> None:
    """세션 시작 · 모델/모드 변경 시 쓰는 경로. 요청 1회로 두 배지를 갱신한다."""
    if not clients:
        return
    payloads = await asyncio.to_thread(_build_both_payloads, context)
    for payload in payloads:
        await broadcast_json(clients, payload)


async def broadcast_nai_usage(context: Any, clients: set) -> None:
    """V5 사용량 한도를 1회 조회해 브로드캐스트.

    **폴링하지 않는다** - 모델/모드가 V5 로 바뀌는 순간과 세션 시작 시 각 1회만
    부른다(사용자 지정). V5 가 아니면 네트워크를 타지 않고 available=False 만 간다.
    """
    if not clients:
        return
    payload = await asyncio.to_thread(build_nai_usage_payload, context)
    await broadcast_json(clients, payload)


def ensure_anlas_poller(context: Any, clients: set) -> None:
    """5분 주기 Anlas 폴링 태스크를 보장 (중복 생성 방지)."""
    task = getattr(context, "headless_anlas_poll_task", None)
    if task is not None and not task.done():
        return
    context.headless_anlas_poll_task = asyncio.create_task(_run_anlas_poll(context, clients))


async def _run_anlas_poll(context: Any, clients: set) -> None:
    if getattr(context, "headless_anlas_poll_active", False):
        return
    context.headless_anlas_poll_active = True
    try:
        while True:
            # 연결 시점에 1회 즉시 브로드캐스트하므로, 폴러는 sleep 후 갱신부터 시작.
            await asyncio.sleep(ANLAS_POLL_INTERVAL_SECONDS)
            await broadcast_anlas(context, clients)
    finally:
        context.headless_anlas_poll_active = False
