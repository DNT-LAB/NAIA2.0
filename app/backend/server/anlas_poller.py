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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        print(f"⚠️ Anlas 조회 실패: {exc}", flush=True)
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
        print(f"⚠️ Use Vibe Anlas 갱신 실패: {exc}", flush=True)


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
        print(f"[warn] NAI usage-limit model check failed: {exc}", flush=True)
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
        print(f"[warn] NAI usage limit fetch failed: {exc}", flush=True)
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


# ---- 계정별 사용량 (Multi Token) --------------------------------------------
#
# 배지는 **평균**을 보여 주고(사용자 명세: "통합 (SUM -> AVG)"), 패널은 계정마다
# 막대를 그린다. 그러려면 계정 수만큼 구독 조회가 필요하다.
#
# ⚠️ 그래서 이 조회는 **활성 계정이 2개 이상이고 V5 를 고른 동안에만** 한다.
# 계정이 하나면 아래 메인 조회 한 번으로 이미 끝난 이야기다.


def _fetch_extra_account_usage(rows: list[tuple[str, str]]) -> dict[str, Any]:
    """메인을 뺀 나머지 계정의 사용량을 **동시에** 조회한다.

    순차로 돌리면 계정 수 x 5초가 그대로 지연이 된다(최대 9계정 = 45초). 어차피
    스레드에서 도는 blocking 함수라 풀 하나면 충분하다.
    """
    if not rows:
        return {}
    out: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=min(len(rows), 8)) as pool:
        futures = {pool.submit(api_verification.fetch_nai_usage_limit, tok): aid
                   for aid, tok in rows}
        for future in as_completed(futures):
            account_id = futures[future]
            try:
                usage = future.result()
            except Exception as exc:  # pragma: no cover - 네트워크/응답 오류
                print(f"[warn] account usage fetch failed for {account_id}: {exc}", flush=True)
                usage = None
            if usage:
                out[account_id] = {
                    "percent": int(usage.get("percent", 0)),
                    "is_negative": bool(usage.get("is_negative", False)),
                }
    return out


def _account_rows(context: Any, usage_by_id: dict[str, Any]) -> list[dict[str, Any]]:
    """패널이 그릴 계정 행. **토큰 전문은 넣지 않는다**(앞 7자 미리보기만)."""
    from core.nai_account_service import NaiAccountService

    service = NaiAccountService(context)
    rows = []
    for row in service.snapshot()["accounts"]:
        if not (row["enabled"] and row["has_token"]):
            continue
        usage = usage_by_id.get(row["id"])
        rows.append({
            "id": row["id"],
            "label": row["label"],
            "token_preview": row["token_preview"],
            "available": isinstance(usage, dict),
            "percent": int(usage.get("percent", 0)) if isinstance(usage, dict) else 0,
            "is_negative": bool(usage.get("is_negative")) if isinstance(usage, dict) else False,
        })
    return rows


def _cache_account_usage(context: Any, usage_by_id: dict[str, Any]) -> None:
    """생성 경로가 읽어 갈 자리에 놓는다(`core.nai_account_service` 계약).

    **빈 dict 는 캐시하지 않는다.** 그러면 '모른다' 가 '전부 100%' 로 보일 일이
    없다 - balancer 쪽에서 모르는 값은 어차피 미소진으로 처리한다.
    """
    if usage_by_id:
        context.headless_account_usage_cache = (time.monotonic(), usage_by_id)


def _build_both_payloads(context: Any) -> list[dict[str, Any]]:
    """Anlas + V5 사용량을 **구독 조회 1회**(+ 추가 계정분)로 만들어 둘 다 돌려준다."""
    anlas_off = _unavailable_payload()
    usage_off = _usage_hidden_payload()
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
        print(f"[warn] NAI subscription fetch failed: {exc}", flush=True)
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
        _attach_accounts(context, usage_payload, usage)
    return [anlas_payload, usage_payload]


def _attach_accounts(context: Any, usage_payload: dict[str, Any],
                     main_usage: dict[str, Any]) -> None:
    """다중 계정이면 계정별 사용량을 붙이고 배지 값을 **평균**으로 바꾼다.

    계정이 하나뿐이면 아무것도 하지 않는다 - 요청도 안 나가고, 배지는 지금까지와
    똑같이 그 계정의 값을 보여 준다.
    """
    from core.nai_account_balancer import average_percent
    from core.nai_account_service import MAIN_ACCOUNT_ID, NaiAccountService

    try:
        service = NaiAccountService(context)
        active = service.active_accounts()
        if len(active) < 2:
            return

        usage_by_id: dict[str, Any] = {}
        if any(account_id == MAIN_ACCOUNT_ID for account_id, _ in active):
            usage_by_id[MAIN_ACCOUNT_ID] = {
                "percent": int(main_usage.get("percent", 0)),
                "is_negative": bool(main_usage.get("is_negative", False)),
            }
        extras = [(a, t) for a, t in active if a != MAIN_ACCOUNT_ID]
        usage_by_id.update(_fetch_extra_account_usage(extras))
        _cache_account_usage(context, usage_by_id)

        snapshot = service.snapshot()
        usage_payload["accounts"] = _account_rows(context, usage_by_id)
        usage_payload["policy"] = snapshot["policy"]
        usage_payload["balancing_effective"] = snapshot["balancing_effective"]
        # 배지는 합이 아니라 **평균**이다(사용자 명세). 못 받은 계정은 평균에서 뺀다.
        avg = average_percent(usage_by_id, [a for a, _ in active])
        if avg is not None:
            usage_payload["percent"] = avg
        usage_payload["is_negative"] = all(
            bool(u.get("is_negative")) for u in usage_by_id.values()
        ) if usage_by_id else False
    except Exception as exc:  # noqa: BLE001 - 배지 하나 때문에 세션이 죽으면 안 된다
        print(f"[warn] multi-token usage attach failed: {exc}", flush=True)


async def broadcast_anlas_and_usage(context: Any, clients: set) -> None:
    """세션 시작 · 모델/모드 변경 시 쓰는 경로. 요청 1회로 두 배지를 갱신한다.

    ⚠️ **커맨드 처리 경로에서 이걸 직접 await 하지 마라.** 아래
    `schedule_subscription_refresh()` 를 써야 한다 — 이유는 그쪽 주석 참조.
    """
    if not clients:
        return
    payloads = await asyncio.to_thread(_build_both_payloads, context)
    for payload in payloads:
        await broadcast_json(clients, payload)
    _cache_pair(context, payloads)


# ---- 비차단 갱신 ------------------------------------------------------------
#
# 배지 하나 때문에 세션을 멈추면 안 된다(사용자 지적 2026-08-21).
#
# 사고 경위: `set_param(model)` 핸들러가 구독 조회를 **await** 했다. 그 await 동안
# 그 세션의 `while True: await ws.receive_text()` 루프가 다음 메시지를 못 받는다.
# 조회는 타임아웃 8초 x 재시도 2회 = 최악 **16초**. 그래서 프리셋을 연달아 바꾸면
# 백엔드가 죽은 것처럼 보이고(랜덤 버튼 무반응), 밀려 있던 프리셋 쓰기가 뒤늦게
# 도착해 **앞 프리셋 값이 뒤 프리셋에 덮어씌워졌다**.
#
# 프리셋 적용은 모델 파라미터를 건드리므로 이 경로를 그대로 탄다.

_USAGE_CACHE_TTL_SECONDS = 60


def _cache_pair(context: Any, payloads: list[dict[str, Any]]) -> None:
    """Anlas + 사용량을 **쌍으로** 캐시한다.

    ⚠️ 예전에는 사용량만 캐시했다. 그러면 캐시 적중 시 `anlas_update` 가 안 나가
    Anlas pill 이 비어 버린다 - 아래 `schedule_subscription_refresh` 주석의 사고와
    같은 뿌리다. 둘은 한 요청에서 나온 값이니 함께 보관하고 함께 내보낸다.
    """
    if len(payloads) == 2 and payloads[0].get("available"):
        context.headless_subscription_cache = (time.monotonic(), payloads[0], payloads[1])


def _cached_pair(context: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
    cached = getattr(context, "headless_subscription_cache", None)
    if not cached:
        return None
    stamped, anlas_payload, usage_payload = cached
    if time.monotonic() - stamped > _USAGE_CACHE_TTL_SECONDS:
        return None
    return anlas_payload, usage_payload


def _usage_hidden_payload() -> dict[str, Any]:
    # `accounts` 를 빈 목록으로 같이 보낸다 - 배지가 숨어도 열려 있던 패널이
    # 옛 계정 막대를 그대로 들고 있으면 안 된다.
    return {
        "type": "nai_usage_update", "available": False, "percent": 0,
        "is_negative": False, "seconds_until_next_percent": 0, "fetched_at": "",
        "accounts": [], "balancing_effective": False,
    }


def usage_badge_active(context: Any) -> bool:
    """지금 사용량 배지가 떠 있는 상태인가(= NAI 모드 + V5 모델).

    생성 완료 경로가 "이번엔 사용량도 갱신해야 하나" 를 판단할 때 쓴다.
    """
    return (
        str(context.get_api_mode() or "").upper() == "NAI"
        and _current_model_uses_usage_limit(context)
    )


def schedule_subscription_refresh(context: Any, clients: set, *, force: bool = False) -> None:
    """구독 조회를 **기다리지 않고** 예약한다. 호출자는 절대 막히지 않는다.

    ⚠️ **항상 두 장(`anlas_update` + `nai_usage_update`)을 같은 순서로 내보낸다.**
    처음엔 "V5 가 아니면 사용량 숨김만 보내고 끝" 으로 짰는데, 그러면 그 경우에
    `anlas_update` 가 **아예 안 나가** Anlas pill 이 5분(폴러 주기) 동안 비었다.
    릴리즈 웹 스모크 계약이 이걸 잡았다(기대 `...anlas_update` vs 관측
    `...nai_usage_update`). 사용량 배지만 V5 전용이지 Anlas 는 NAI 모드면 늘 필요하다.

    네트워크를 타지 않고 끝나는 경우:
      - NAI 모드가 아니거나 토큰이 없다 -> 둘 다 '없음' 으로 즉시(조회 불필요)
      - 방금 받아 둔 값이 있다          -> 캐시(60초) 쌍을 그대로 다시 보낸다
    프리셋을 바꿔도 값이 안 변하는 구간은 이 두 갈래가 네트워크 없이 흡수한다.

    실제 조회가 필요할 때만 태스크를 띄우고, **이미 떠 있으면 새로 만들지 않는다**
    (프리셋 하나가 모델 신호를 여러 번 쏴도 요청은 한 번).
    """
    if not clients:
        return

    # 생성 직후처럼 **값이 방금 변했다고 아는** 경우에는 캐시를 버린다. 안 버리면
    # 60초 캐시가 옛 값을 그대로 다시 보내, 생성해도 배지가 안 움직인다.
    if force:
        context.headless_subscription_cache = None

    try:
        token = str(context.secure_token_manager.get_token("nai_token") or "").strip()
    except Exception:
        token = ""
    if str(context.get_api_mode() or "").upper() != "NAI" or not token:
        asyncio.create_task(
            _send_pair(clients, _unavailable_payload(), _usage_hidden_payload()))
        return

    cached = _cached_pair(context)
    if cached is not None:
        # 캐시는 Anlas 기준으로 잡는다. 사용량은 모델에 따라 붙였다 뗐다 하므로
        # **지금 모델 기준으로 다시 판정**한다 - 안 그러면 V5 에서 V4.5 로 바꿔도
        # 배지가 캐시 때문에 남는다.
        usage = cached[1] if _current_model_uses_usage_limit(context) else _usage_hidden_payload()
        asyncio.create_task(_send_pair(clients, cached[0], usage))
        return

    task = getattr(context, "headless_subscription_refresh_task", None)
    if task is not None and not task.done():
        return
    new_task = asyncio.create_task(broadcast_anlas_and_usage(context, clients))
    # 예외를 회수하지 않으면 "Task exception was never retrieved" 로 로그만 더럽힌다.
    new_task.add_done_callback(_log_refresh_failure)
    context.headless_subscription_refresh_task = new_task


async def _send_pair(clients: set, anlas_payload: dict[str, Any],
                     usage_payload: dict[str, Any]) -> None:
    """순서가 계약이다 - `anlas_update` 먼저, `nai_usage_update` 다음."""
    try:
        await broadcast_json(clients, anlas_payload)
        await broadcast_json(clients, usage_payload)
    except Exception as exc:  # pragma: no cover - 배지 전송 실패가 세션을 막으면 안 됨
        print(f"[warn] subscription badge broadcast failed: {exc}", flush=True)


def _log_refresh_failure(task: "asyncio.Task[Any]") -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        print(f"[warn] NAI subscription refresh failed: {exc}", flush=True)


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
