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
    # ⚠️ 계정이 둘 이상이면 **합계**를 보여야 하므로 계정별 Anlas 가 필요하다. 그래서
    # `fetch_nai_anlas`(Anlas 만) 대신 summary 를 쓴다 - 같은 엔드포인트 한 번이고
    # 메인 응답을 계정 풀에 그대로 재사용할 수 있다.
    #
    # 이 경로는 **V5 가 아닌 생성 직후**에도 쓰인다. 메시지를 정확히 **1장**
    # (`anlas_update`)만 내보내야 릴리즈 웹 스모크의 생성 커맨드 계약이 안 어긋난다 -
    # 그래서 여기서 사용량 배지를 같이 보내지 않는다.
    try:
        summary = api_verification.fetch_nai_subscription_summary(token)
    except Exception as exc:  # pragma: no cover - 네트워크/응답 오류
        print(f"⚠️ Anlas 조회 실패: {exc}", flush=True)
        summary = {}
    value = (summary or {}).get("anlas")
    if value is None:
        return _unavailable_payload()
    payload = {
        "type": "anlas_update",
        "available": True,
        "anlas": int(value),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    combine_anlas(payload, refresh_account_pool(context, summary))
    return payload


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

    판정은 모델 계약이 SSOT 다 - 정책 목록과 무료 집계도 같은 함수를 본다.
    """
    from core.nai_model_contract import context_uses_opus_usage_limit

    return context_uses_opus_usage_limit(context)


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
    """메인을 뺀 나머지 계정의 **Anlas + 사용량**을 동시에 조회한다.

    순차로 돌리면 계정 수 x 8초가 그대로 지연이 된다(최대 9계정). 어차피 스레드에서
    도는 blocking 함수라 풀 하나면 충분하다.

    `fetch_nai_usage_limit` 이 아니라 `fetch_nai_subscription_summary` 를 쓴다 -
    같은 엔드포인트 한 번으로 Anlas 까지 같이 온다. 패널이 계정마다 잔여 Anlas 를
    보여 주므로 어차피 둘 다 필요하다.
    """
    if not rows:
        return {}
    out: dict[str, Any] = {}
    # ⚠️ 동시 4개까지만. 계정 상한이 9라 그냥 두면 한 번에 8~9개 요청이 같은
    # 엔드포인트로 몰린다. 429 를 맞으면 그 계정이 `usage_by_id` 에서 빠지고,
    # 동적 할당은 **모르는 계정을 100% 로 본다** - 실제로는 소진된 계정에 생성을
    # 보내 Anlas 를 태울 수 있다. 화면만 비는 게 아니라 돈이 걸린 문제라 아낀다.
    # 9계정이어도 3파도면 끝나므로 체감 지연은 없다.
    with ThreadPoolExecutor(max_workers=min(len(rows), 4)) as pool:
        futures = {pool.submit(api_verification.fetch_nai_subscription_summary, tok): aid
                   for aid, tok in rows}
        for future in as_completed(futures):
            account_id = futures[future]
            try:
                summary = future.result() or {}
            except Exception as exc:  # pragma: no cover - 네트워크/응답 오류
                print(f"[warn] account usage fetch failed for {account_id}: {exc}", flush=True)
                summary = {}
            usage = summary.get("usage")
            if usage:
                out[account_id] = {
                    "percent": int(usage.get("percent", 0)),
                    "is_negative": bool(usage.get("is_negative", False)),
                    "anlas": summary.get("anlas"),
                }
    return out


# 좁혀 묻기를 멈추고 전 계정을 다시 훑는 주기. 생성하지 않은 계정도 시간당 0.46%씩
# 회복되므로, 오래 안 물으면 캐시가 실제보다 **낮게** 남아 동적 할당이 그 계정을
# 계속 뒤로 미룬다. 이 주기가 그 편차의 상한이다.
ACCOUNT_USAGE_FULL_REFRESH_SECONDS = 300


def _narrow_targets(context: Any, extras: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """이번에 실제로 물어볼 계정만 골라 준다.

    생성 직후에는 **방금 생성한 계정 하나**로 좁힌다. 이번 생성으로 값이 변할 수
    있는 계정은 그것뿐이고, 나머지를 매번 같이 묻는 것은 계정 수만큼 요청이 늘 뿐이다
    (사용자 지적 2026-08-21: "동적 할당에서 매 생성마다 두 계정이 동시에 조회").

    좁히지 않는 경우:
      - 생성 맥락이 아니다(접속 / 모델 변경 / 계정 추가·삭제) -> 전부
      - 캐시가 없거나 빠진 계정이 있다                        -> 전부
      - 캐시가 5분 넘게 묵었다                                -> 전부(회복분 반영)
    """
    from core.nai_account_service import (
        LAST_GENERATION_ACCOUNT_ATTR,
        account_usage_cache_age,
        cached_account_usage,
    )

    # **한 번 쓰고 지운다.** 안 지우면 생성 이후의 모든 갱신(모델 변경 · 계정 추가 ·
    # 재접속)이 계속 그 계정 하나만 물어, 나머지가 영영 안 새로워진다.
    target = str(getattr(context, LAST_GENERATION_ACCOUNT_ATTR, "") or "")
    if target:
        setattr(context, LAST_GENERATION_ACCOUNT_ATTR, "")
    if not target:
        return extras
    cached = cached_account_usage(context)
    if not cached or any(account_id not in cached for account_id, _ in extras):
        return extras
    if account_usage_cache_age(context) >= ACCOUNT_USAGE_FULL_REFRESH_SECONDS:
        return extras
    # 메인이 생성했으면 추가 계정은 하나도 안 묻는다 - 메인 구독은 위에서 이미 받았다.
    return [(a, t) for a, t in extras if a == target]


def _account_rows(context: Any, usage_by_id: dict[str, Any],
                  next_account_id: str) -> list[dict[str, Any]]:
    """패널이 그릴 계정 행. **토큰 전문은 넣지 않는다**(앞 7자 미리보기만)."""
    from core.nai_account_service import NaiAccountService, account_session_tally

    service = NaiAccountService(context)
    tally = account_session_tally(context)
    rows = []
    for row in service.snapshot()["accounts"]:
        if not (row["enabled"] and row["has_token"]):
            continue
        usage = usage_by_id.get(row["id"])
        known = isinstance(usage, dict)
        anlas = usage.get("anlas") if known else None
        rows.append({
            "id": row["id"],
            "label": row["label"],
            "token_preview": row["token_preview"],
            "available": known,
            "percent": int(usage.get("percent", 0)) if known else 0,
            "is_negative": bool(usage.get("is_negative")) if known else False,
            "anlas": int(anlas) if isinstance(anlas, int) else None,
            # 이번 라운드에 생성할 계정. 화면이 여기를 강조한다.
            "is_next": row["id"] == next_account_id,
            # 이번 세션에 이 계정으로 나간 장수(사용자 요청 2026-08-21: "총 ****장").
            "session_count": int(tally.get(row["id"], 0)),
        })
    return rows


def refresh_account_pool(context: Any, main_summary: dict[str, Any] | None) -> dict[str, Any]:
    """활성 계정 전체의 `{id: {percent, is_negative, anlas}}` 를 만들어 캐시한다.

    **V5 와 무관하다.** 예전에는 이 조회가 사용량 배지(V5 전용) 안에만 있어서,
    V4.5 에서는 계정이 둘이어도 Anlas 가 메인 것만 나왔다 - 모델을 바꾸면 좌상단
    숫자가 튀었다(사용자 지시 2026-08-21: "1개일 땐 Mute, 2개 이상이면 Show" 정책을
    NAID5 이외 버전에도 전파).

    `main_summary` 는 호출자가 이미 받아 둔 메인 계정 구독 응답(있으면 재사용해서
    같은 걸 두 번 묻지 않는다). 활성 계정이 하나도 없을 때만 빈 dict 를 돌려준다.
    """
    from core.nai_account_service import (
        MAIN_ACCOUNT_ID,
        NaiAccountService,
        cached_account_usage,
    )

    try:
        active = NaiAccountService(context).active_accounts()
        # ⚠️ 예전에는 `< 2` 였다. 계정이 하나면 배지가 어차피 그 계정의 값을 그대로
        #    보여 주니 캐시가 필요 없다고 봤는데, **생성 경로는 이 캐시만 본다** -
        #    그래서 '0% 도달 시 Auto Gen 해제' 가 계정 하나인 설치에서 통째로 안
        #    걸렸다(Codex BLOCK 2026-08-25). 빈 캐시는 '모른다' 로 읽혀 영영 안 멈춘다.
        #
        #    배지는 그대로다 - `_attach_accounts` 에 자기 `< 2` 가드가 따로 있어
        #    평균/계정 줄을 붙이지 않는다(실측 확인).
        #    요청도 안 는다 - 활성이 메인 하나면 `main_summary` 로 채우고 extras 가
        #    비어 조회가 아예 없다. 메인을 끄고 추가 계정 하나만 쓰는 드문 구성에서만
        #    조회 하나가 는다.
        if not active:
            return {}

        usage_by_id: dict[str, Any] = {}
        if main_summary is not None and any(a == MAIN_ACCOUNT_ID for a, _ in active):
            main_usage = main_summary.get("usage") or {}
            usage_by_id[MAIN_ACCOUNT_ID] = {
                "percent": int(main_usage.get("percent", 0)),
                "is_negative": bool(main_usage.get("is_negative", False)),
                "anlas": main_summary.get("anlas"),
            }
        extras = [(a, t) for a, t in active if a != MAIN_ACCOUNT_ID]
        usage_by_id.update(_fetch_extra_account_usage(_narrow_targets(context, extras)))
        # 좁혀 물었으면 안 물어본 계정은 캐시 값을 그대로 이어 쓴다.
        #
        # ⚠️ **지금 활성인 계정만** 이어 쓴다. 예전에는 캐시에 있는 것을 전부 합쳐서,
        # 지우거나 꺼 버린 계정의 Anlas 가 통합값에 계속 더해졌다(Codex 리뷰
        # 2026-08-21). 사용자는 없는 돈을 있다고 읽게 된다.
        active_ids = {account_id for account_id, _ in active}
        for account_id, cached in cached_account_usage(context).items():
            if account_id in active_ids:
                usage_by_id.setdefault(account_id, cached)
        _cache_account_usage(context, usage_by_id)
        return usage_by_id
    except Exception as exc:  # noqa: BLE001 - 배지 하나 때문에 세션이 죽으면 안 된다
        print(f"[warn] account pool refresh failed: {exc}", flush=True)
        return {}


def combine_anlas(anlas_payload: dict[str, Any], usage_by_id: dict[str, Any]) -> None:
    """계정이 둘 이상이면 Anlas pill 값을 **합계**로 바꾼다(제자리 수정)."""
    if not anlas_payload.get("available"):
        return
    known = [u.get("anlas") for u in usage_by_id.values()]
    known = [a for a in known if isinstance(a, int)]
    if len(known) >= 2:
        anlas_payload["anlas"] = sum(known)
        anlas_payload["account_count"] = len(known)


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
    # 계정 조회는 **모델과 무관하다.** V4.5 에서도 계정이 둘이면 Anlas 를 합쳐 준다
    # (사용자 지시 2026-08-21). 하나뿐이면 메인 구독 응답만으로 채운다(추가 요청 없음).
    usage_by_id = refresh_account_pool(context, summary)
    combine_anlas(anlas_payload, usage_by_id)

    # 배지는 **NAI 모드면 늘 뜬다**(사용자 지시 2026-08-21). 모델을 V5 <-> V4.5 로
    # 오갈 때마다 사라졌다 나타나면 자리도 흔들리고, 배지가 보여 주는 값이 이제
    # 퍼센트가 아니라 **이번 세션 무료 생성 수**라 모델과 무관하게 의미가 있다.
    #
    # `uses_usage_limit` 는 "지금 모델이 V5 인가" 다 - 퍼센트/잔량 숫자는 V5 에서만
    # 뜻이 있으므로 화면이 이 값을 보고 그 부분만 흐리거나 감춘다.
    from core.nai_free_usage import session_payload

    usage = summary.get("usage") or {}
    usage_payload = {
        "type": "nai_usage_update",
        "available": True,
        "uses_usage_limit": _current_model_uses_usage_limit(context),
        "percent": int(usage.get("percent", 0)),
        "is_negative": bool(usage.get("is_negative", False)),
        "seconds_until_next_percent": int(usage.get("seconds_until_next_percent", 0)),
        "fetched_at": now,
        **session_payload(context),
    }
    _attach_accounts(context, usage_payload)
    _attach_policy(context, usage_payload)
    return [anlas_payload, usage_payload]


def _attach_accounts(context: Any, usage_payload: dict[str, Any]) -> None:
    """다중 계정이면 계정별 사용량을 붙이고 배지 값을 **평균**으로 바꾼다.

    계정이 하나뿐이면 아무것도 하지 않는다 - 요청도 안 나가고, 배지는 지금까지와
    똑같이 그 계정의 값을 보여 준다.
    """
    from core.nai_account_balancer import average_percent, select_account
    from core.nai_account_service import (
        MAIN_ACCOUNT_ID,
        NaiAccountService,
        cached_account_usage,
        peek_rotation_counter,
        rotation_seed,
    )

    try:
        service = NaiAccountService(context)
        active = service.active_accounts()
        if len(active) < 2:
            return
        # 조회·캐시는 공용 함수가 한다(V5 밖에서도 같은 걸 쓴다). 이미 받아 둔
        # 계정별 값을 그대로 읽는다 - 여기서 다시 물으면 요청이 두 배가 된다.
        usage_by_id = dict(cached_account_usage(context))
        if not usage_by_id:
            return

        snapshot = service.snapshot()
        # 이번 라운드에 생성할 계정. ⚠️ **peek 이다** - 여기서 카운터를 올리면
        # 화면을 그릴 때마다 회전이 어긋나 실제 생성이 계정을 건너뛴다.
        next_account_id = select_account(
            [a for a, _ in active],
            policy=snapshot["policy"],
            counter=peek_rotation_counter(context),
            usage_by_id=usage_by_id,
            seed=rotation_seed(context),
            # 생성 경로(`api_service`)와 **같은 값**을 넣는다. 스냅샷의 값은 이미
            # '지금 쓸 수 있는지' 로 걸러져 있다.
            forced=str(snapshot.get("forced_account_id") or ""),
        )
        usage_payload["accounts"] = _account_rows(context, usage_by_id, next_account_id)
        usage_payload["next_account_id"] = next_account_id
        # 배지는 합이 아니라 **평균**이다(사용자 명세). 못 받은 계정은 평균에서 뺀다.
        avg = average_percent(usage_by_id, [a for a, _ in active])
        if avg is not None:
            usage_payload["percent"] = avg
        usage_payload["is_negative"] = all(
            bool(u.get("is_negative")) for u in usage_by_id.values()
        ) if usage_by_id else False
    except Exception as exc:  # noqa: BLE001 - 배지 하나 때문에 세션이 죽으면 안 된다
        print(f"[warn] multi-token usage attach failed: {exc}", flush=True)


def _attach_policy(context: Any, usage_payload: dict[str, Any]) -> None:
    """부하 분산 정책과 지금 묶음의 진행도를 붙인다.

    ⚠️ **모델에 딸린 값이다.** 정책 목록이 V5 와 비V5 로 갈려 있어(balancer 참조)
    모델이 바뀌면 목록도 선택도 바뀐다. 캐시된 페이로드를 다시 보내는 경로에서도
    반드시 이걸 다시 돌려야 한다 - 안 그러면 4.5 로 갔는데 V5 목록이 그대로 남는다.
    """
    from core.nai_account_balancer import policy_options, rotation_block
    from core.nai_account_service import (
        NaiAccountService,
        peek_rotation_counter,
        rotation_seed,
    )

    try:
        on_v5 = _current_model_uses_usage_limit(context)
        snapshot = NaiAccountService(context).snapshot()
        policy = snapshot["policy"]
        current, target = rotation_block(
            policy, peek_rotation_counter(context), rotation_seed(context))
        usage_payload["policy"] = policy
        usage_payload["policy_options"] = policy_options(on_v5)
        usage_payload["balancing_effective"] = snapshot["balancing_effective"]
        # "목표 100장 · 현재 37장" 과 게이지. 1장짜리 정책(라운드 로빈/동적 할당)은
        # target 이 1 이라 화면이 게이지를 안 그린다.
        usage_payload["rotation_current"] = current
        usage_payload["rotation_target"] = target
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] multi-token policy attach failed: {exc}", flush=True)


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
    # 옛 계정 행을 그대로 들고 있으면 안 된다.
    # (NAI 모드가 아니거나 토큰이 없을 때만 쓰인다 - 모델 때문에 숨지는 않는다.)
    return {
        "type": "nai_usage_update", "available": False, "percent": 0,
        "is_negative": False, "seconds_until_next_percent": 0, "fetched_at": "",
        "accounts": [], "balancing_effective": False, "uses_usage_limit": False,
        "free_generations": 0, "session_generations": 0, "elapsed_seconds": 0,
        "rotation_current": 0, "rotation_target": 1,
    }


# 배지를 마지막으로 그렸을 때의 모델 키.
#
# ⚠️ **모델을 바꾸는 길이 하나가 아니다.** `set_param(model)` 커맨드만 갱신을 걸어
# 뒀는데, 프리셋 적용은 `_apply_main_settings` 가 `context.set_param()` 을 **직접**
# 불러 그 핸들러를 안 거친다. 그래서 프리셋으로 NAID5 -> NAID4.5 로 가면 드롭다운은
# 바뀌는데 배지/정책 목록은 V5 인 채였다(사용자 지적 2026-08-21).
#
# 호출처를 하나하나 쫓는 대신 **결과(모델 키)가 변했는가**를 본다. 새 경로가
# 생겨도 자동으로 걸린다.
_BADGE_MODEL_ATTR = "headless_usage_badge_model_key"


def _current_model_key(context: Any) -> str:
    try:
        return str(context._current_model_key() or "")
    except Exception:
        return ""


def note_usage_badge_model(context: Any) -> None:
    """지금 모델을 '배지가 아는 모델' 로 기록한다(갱신을 직접 건 직후에 쓴다)."""
    setattr(context, _BADGE_MODEL_ATTR, _current_model_key(context))


def refresh_usage_if_model_changed(context: Any, clients: set) -> bool:
    """마지막으로 그린 뒤 모델이 바뀌었으면 배지를 갱신한다.

    커맨드 처리 **직후**에 부른다. 안 바뀌었으면 아무 일도 하지 않으므로 수신
    루프에 얹어도 비용은 dict 조회 한 번이다.
    """
    key = _current_model_key(context)
    if key == getattr(context, _BADGE_MODEL_ATTR, None):
        return False
    setattr(context, _BADGE_MODEL_ATTR, key)
    schedule_subscription_refresh(context, clients)
    return True


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
        # 배지는 이제 모델과 무관하게 뜨므로 캐시를 그대로 쓴다. 다만 **모델에 딸린
        # 값들은 지금 기준으로 다시 채운다** - 캐시는 V5 일 때 잡혔을 수 있고,
        # 세션 카운터는 그 사이에 늘었을 수 있다.
        from core.nai_free_usage import session_payload

        usage = dict(cached[1])
        if usage.get("available"):
            usage["uses_usage_limit"] = _current_model_uses_usage_limit(context)
            usage.update(session_payload(context))
            # 정책 목록/선택도 모델에 딸려 있다 - 캐시가 V5 때 잡혔으면 4.5 로 와도
            # V5 목록이 그대로 남는다. 여기서 다시 채운다.
            _attach_policy(context, usage)
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
            # V5 를 고른 동안에는 **사용량도 같이** 갱신한다. 예전에는 Anlas 만 돌아서,
            # 생성 없이 놀고 있으면 회복분(시간당 0.46%)이 배지에 영영 안 나타났다 -
            # 모델을 다시 만지기 전까지 숫자가 굳어 있었다.
            #
            # 이 경로는 접속 후 5분이 지나야 처음 도므로 릴리즈 웹 스모크의 메시지
            # 개수 계약과 무관하다(스모크는 그 전에 끝난다).
            if usage_badge_active(context):
                await broadcast_anlas_and_usage(context, clients)
            else:
                await broadcast_anlas(context, clients)
    finally:
        context.headless_anlas_poll_active = False
