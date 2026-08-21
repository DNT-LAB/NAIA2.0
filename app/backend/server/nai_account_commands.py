"""NAI 다중 계정(Multi Token) 웹소켓 커맨드.

Dev0714 의 PyQt `api_management_window.py` 가 하던 일을 웹으로 옮긴 것이다.
읽기는 누구나, **쓰기는 로컬에서만** — 게이트가 둘로 갈린다:

    nai_accounts_get           게이트 없음   토큰 전문은 안 나간다(앞 7자 미리보기만)
    nai_account_add            setup_gate   자격 증명 표면
    nai_account_delete         setup_gate   토큰까지 지운다
    nai_account_set_token      setup_gate   토큰 입력
    nai_account_set_enabled    account_gate 로컬이면 터널 중에도 허용
    nai_account_set_policy     account_gate 로컬이면 터널 중에도 허용

⚠️ 토큰은 **검증에 성공해야만 저장한다**(메인 토큰과 같은 규칙). 검증 없이 넣으면
그 계정이 회전에 들어간 뒤 **N 장마다 한 번씩 생성이 실패한다** - 사용자 입장에서는
"가끔 안 된다" 라 원인을 찾기가 훨씬 어렵다.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.anlas_poller import schedule_subscription_refresh
from core import api_verification
from core.nai_account_service import MAIN_ACCOUNT_ID, NaiAccountService

AsyncRunner = Callable[..., Awaitable[Any]]

NAI_ACCOUNT_COMMAND_TYPES = {
    "nai_accounts_get",
    "nai_account_add",
    "nai_account_delete",
    "nai_account_set_token",
    "nai_account_set_enabled",
    "nai_account_set_policy",
}

# 쓰기 커맨드별 게이트. 위 표 참조.
_SETUP_GATED = {"nai_account_add", "nai_account_delete", "nai_account_set_token"}
_ACCOUNT_GATED = {"nai_account_set_enabled", "nai_account_set_policy"}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


def _snapshot_payload(context: Any) -> dict[str, Any]:
    from core.nai_account_balancer import policy_options

    snapshot = NaiAccountService(context).snapshot()
    snapshot["type"] = "nai_accounts"
    # ⚠️ 목록은 **모델 계열마다 다르다**(balancer 주석 참조). `snapshot()` 이 이미
    # 지금 계열을 판정해 뒀으니 그 값을 그대로 쓴다 - 여기서 다시 판정하면 두 값이
    # 어긋나 라디오가 목록 밖 키를 가리킬 수 있다.
    snapshot["policy_options"] = policy_options(bool(snapshot.get("uses_usage_limit", True)))
    return snapshot


def _set_token(context: Any, account_id: str, token: str) -> dict[str, Any]:
    """중복 확인 -> 검증 -> 저장 -> 켜기. 어느 단계든 실패하면 저장하지 않는다."""
    service = NaiAccountService(context)

    # ⚠️ 중복은 **검증보다 먼저** 막는다. 검증은 네트워크 왕복 10초까지 가는데,
    # 어차피 거절할 입력에 그 시간을 쓸 이유가 없다.
    #
    # 같은 토큰을 두 계정에 넣으면 계정 수만 늘고 한도는 그대로다. 사용자는 두 배로
    # 쓸 수 있다고 믿는데 아니고, 패널 합계가 같은 계정을 두 번 세어 **없는 잔량을
    # 있다고 표시한다**(실측: Anlas 19,896 인데 실제 9,948). 조용한 손해라 막는다.
    owner = service.find_token_owner(token, exclude=account_id)
    if owner:
        label = next((r["label"] for r in service.snapshot()["accounts"]
                      if r["id"] == owner), owner)
        return {"ok": False,
                "message": f"이미 {label}에 등록된 토큰입니다. 같은 계정을 두 번 넣어도 "
                           f"사용량 한도는 늘지 않습니다."}

    result = api_verification.verify_nai_token(token)
    if not result.success:
        return {"ok": False, "message": result.message}
    saved = service.set_token(account_id, result.value or token)
    if not saved.get("ok"):
        return saved
    # 토큰을 넣었다는 건 그 계정을 쓰겠다는 뜻이다. 꺼 둔 채로 두면 "넣었는데 왜
    # 안 쓰이지" 가 된다 - 계정은 토큰이 없을 때만 꺼진 채로 만든다.
    service.set_enabled(account_id, True)
    return {"ok": True, "message": result.message}


async def handle_nai_account_command(
    ws: WebSocket,
    context: Any,
    client_host: str,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
    clients: set | None = None,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in NAI_ACCOUNT_COMMAND_TYPES:
        return False

    if command_type in _SETUP_GATED:
        allowed, reason = context.setup_gate(client_host)
    elif command_type in _ACCOUNT_GATED:
        allowed, reason = context.account_gate(client_host)
    else:
        allowed, reason = True, ""
    if not allowed:
        await _send_json(ws, {"type": "nai_account_result", "command": command_type,
                              "ok": False, "message": reason})
        await _send_json(ws, _snapshot_payload(context))
        return True

    service = NaiAccountService(context)
    account_id = str(command.get("account_id") or "").strip()
    result: dict[str, Any] = {"ok": True}

    if command_type == "nai_accounts_get":
        await _send_json(ws, _snapshot_payload(context))
        return True

    if command_type == "nai_account_add":
        result = service.add_account()
    elif command_type == "nai_account_delete":
        result = service.delete_account(account_id)
    elif command_type == "nai_account_set_token":
        # 검증이 네트워크를 타므로 **스레드로 보낸다.** 여기서 await 하면 그 세션의
        # 수신 루프가 최대 10초 멈춘다(프리셋 연타 사고와 같은 뿌리).
        result = await run_in_thread(_set_token, context, account_id or MAIN_ACCOUNT_ID,
                                     str(command.get("token") or ""))
    elif command_type == "nai_account_set_enabled":
        result = service.set_enabled(account_id, bool(command.get("enabled", False)))
    elif command_type == "nai_account_set_policy":
        result = service.set_policy(str(command.get("policy") or ""))

    await _send_json(ws, {
        "type": "nai_account_result",
        "command": command_type,
        "ok": bool(result.get("ok")),
        "message": result.get("message", ""),
        # 성공했는데도 경고할 게 있는 경우가 있다 - 계정은 지웠지만 토큰이 남았다든지.
        # 그걸 조용한 info 토스트로 흘리면 자격 증명이 남은 걸 아무도 모른다.
        "level": str(result.get("level") or ""),
    })
    await _send_json(ws, _snapshot_payload(context))

    # 계정 구성이 바뀌면 배지의 평균값도 바뀐다. 캐시를 버리고 다시 받는다
    # (비차단 - 이 커맨드 핸들러는 조회를 기다리지 않는다).
    if result.get("ok") and clients:
        schedule_subscription_refresh(context, clients, force=True)
    return True
