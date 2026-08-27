"""NAI 다중 계정(Multi Token) 저장소.

배경
----
생성 경로의 다중 계정 지원은 **한 번도 사라진 적이 없다** —
`APIService._get_active_nai_token()` 이 지금도 `save/nai_accounts.json` 을 읽어
라운드 로빈으로 토큰을 고른다. 사라진 것은 그 파일을 **사람이 편집할 UI** 뿐이다
(PyQt `legacy_desktop/tabs/api_management_window.py`, 커밋 `cf6f8dc9` 에서 제거).

이 모듈은 그 UI 가 쓰던 것과 **똑같은 스키마**를 다룬다. 다르게 쓰면 생성 경로가
읽지 못한다.

    {
      "accounts": [
        {"id": "nai_token_1", "label": "계정2", "enabled": false, "last_verified": null}
      ],
      "round_robin_enabled": false,
      "main_account_enabled": true,
      "load_balancing_policy": "round_robin"     // 신규 (아래 참조)
    }

토큰 값 자체는 이 파일에 넣지 않는다. `secure_token_manager` 에 **계정 id 를 키로**
암호화 저장한다(메인 계정 키는 `nai_token`). 파일에는 앞 7자 미리보기만 만들어 준다.

`round_robin_enabled` 는 이제 **파생값**이다
--------------------------------------------
레거시 UI 에서는 이게 "번갈아 쓸까 말까" 토글이었다. 새 명세(2026-08-21)의 라디오는
정책 4종뿐이고 '끄기' 가 없다 - 한 계정만 쓰고 싶으면 나머지를 **비활성**하면 된다.
그래서 이 키는 `저장할 때마다 활성 계정 2개 이상인가` 로 다시 계산해 써 둔다.
사람이 고르는 값이 아니라, 이 파일을 읽는 옛 코드가 오해하지 않게 두는 흔적이다.

⚠️ 파일 경로는 반드시 `runtime_paths.save_dir` 를 쓴다. `APIService._save_file_path`
와 같은 자리를 가리켜야 하며, 저장소 트리에 쓰면 안 된다(런타임 쓰기 정책).
"""

from __future__ import annotations

import functools
import json
import random
import threading
import time
from pathlib import Path
from typing import Any

from core.nai_account_balancer import DEFAULT_POLICY, normalize_policy

ACCOUNTS_FILENAME = "nai_accounts.json"
MAIN_ACCOUNT_ID = "nai_token"
MAIN_ACCOUNT_LABEL = "메인 계정"

# 정책은 **모델 계열마다 따로 기억한다.** 목록이 갈렸기 때문이다(balancer 주석 참조).
# 한 칸에 몰아 두면 V5 에서 '동적 할당' 을 고른 뒤 4.5 로 갔다 오기만 해도 그 선택이
# 폴백값으로 덮여 사라진다.
#
# `load_balancing_policy` 는 **옛 키 그대로** V5 쪽에 쓴다 - 기존 파일이 그대로
# 읽힌다. 비V5 칸은 새 키이며, 없으면 옛 키에서 물려받는다(구간형 정책을 고른
# 사용자가 이번 판올림에서 그 선택을 잃지 않도록).
POLICY_KEY_USAGE = "load_balancing_policy"
POLICY_KEY_ANLAS = "load_balancing_policy_anlas"

# 활성 계정이 **전부** 무료 사용량 0% 에 닿으면 Auto Gen 을 스스로 끈다(사용자 지정).
# 계열마다 갈리지 않는 하나의 스위치다 - 무료 풀은 V5 에만 있으므로 판정 자체가
# V5 에서만 뜻을 가진다(`generation_quota_exhausted` 참조).
STOP_ON_EXHAUSTED_KEY = "stop_auto_gen_on_exhausted"

# 사용자가 **직접 고른 계정**(사용자 지정 2026-08-27). 비어 있으면 부하 분산 정책을
# 쓴다. 계열을 나누지 않는다 - "이 계정으로 뽑겠다" 는 뜻이 모델에 따라 달라질 이유가
# 없다. 고른 계정이 꺼지거나 지워지면 스냅샷이 빈 값으로 보고하고 선택은 정책으로
# 되돌아간다(`nai_account_balancer.select_account` 주석 참조).
FORCED_ACCOUNT_KEY = "forced_account_id"

# 계정을 무한정 늘릴 이유가 없다. 라운드 로빈은 카운터 % N 이라 N 이 커질수록
# 한 계정이 다시 쓰이기까지의 간격만 늘어난다.
MAX_ACCOUNTS = 9


def _default_data() -> dict[str, Any]:
    return {
        "accounts": [],
        "round_robin_enabled": False,
        "main_account_enabled": True,
        POLICY_KEY_USAGE: DEFAULT_POLICY,
        POLICY_KEY_ANLAS: DEFAULT_POLICY,
        STOP_ON_EXHAUSTED_KEY: False,
        FORCED_ACCOUNT_KEY: "",
    }


def account_label(account_id: str) -> str:
    """`nai_token_1` -> `계정2`. 메인은 `메인 계정`.

    레거시 UI 의 규칙 그대로다 - 인덱스에 1 을 더해 사람이 세는 번호로 만든다
    (메인이 1번이므로 첫 추가 계정이 2번).
    """
    if account_id == MAIN_ACCOUNT_ID:
        return MAIN_ACCOUNT_LABEL
    try:
        return f"계정{int(str(account_id).split('_')[-1]) + 1}"
    except (ValueError, TypeError):
        return str(account_id)


def token_preview(token: str | None) -> str:
    """앞 7자만. 토큰 전문은 어떤 경로로도 프런트에 보내지 않는다."""
    t = str(token or "")
    return t[:7] if t else ""


# 계정별 V5 사용량 캐시가 앉는 자리. 채우는 쪽은 서버의 구독 폴러이고,
# 읽는 쪽은 **생성 경로**다.
#
# ⚠️ 생성 경로는 계정을 고르려고 네트워크를 타면 안 된다 - 매 장마다 구독 API 를
# 때리게 되고, 그 조회는 실측 8초까지 걸린다. 그래서 "있으면 쓰고 없으면 모른다"
# 로 둔다. 모르면 balancer 가 전부 미소진·동률로 보고 라운드 로빈으로 눕는다.
ACCOUNT_USAGE_CACHE_ATTR = "headless_account_usage_cache"

# 직전 생성이 어느 계정으로 나갔는지. 생성 직후 재조회가 **그 계정만** 묻기 위해
# 쓴다 - 나머지 계정은 이번 생성으로 값이 변할 수가 없다.
LAST_GENERATION_ACCOUNT_ATTR = "nai_last_generation_account"


def account_usage_cache_age(context: Any) -> float:
    """계정별 사용량 캐시가 얼마나 묵었는가(초). 없으면 무한대."""
    cached = getattr(context, ACCOUNT_USAGE_CACHE_ATTR, None)
    if isinstance(cached, tuple) and len(cached) == 2:
        try:
            return max(0.0, time.monotonic() - float(cached[0]))
        except (TypeError, ValueError):
            return float("inf")
    return float("inf")


def cached_account_usage(context: Any) -> dict[str, Any]:
    """폴러가 채워 둔 `{계정 id: {"percent":int,"is_negative":bool}}`. 없으면 `{}`."""
    cached = getattr(context, ACCOUNT_USAGE_CACHE_ATTR, None)
    if isinstance(cached, tuple) and len(cached) == 2 and isinstance(cached[1], dict):
        return cached[1]
    return {}


def generation_quota_exhausted(context: Any) -> bool:
    """**이번 생성이 쓸 계정들**이 전부 무료 사용량 0% 에 닿았는가.

    ⚠️ '완전히 0' 이 아니다(사용자 정정). Anlas 는 남아 있어도 이 풀이 마르면 그
       다음 장부터 유료다 - 밤새 도는 Auto Gen 이 그 선을 조용히 넘는 것을 막자는
       판정이다. **하나라도 남아 있으면 False** 다(부하 분산이 남은 계정으로 옮겨
       계속 무료로 생성한다).

    ⚠️ **계정을 하나 지목했으면 그 계정만 본다**(사용자 지정 2026-08-27). 지목하면
       생성은 그 계정으로만 나가므로, '모든 계정' 을 기다리면 지목한 계정이 마른
       뒤에도 안전장치가 안 걸려 **Anlas 로 계속 태운다** - 다른 계정에 남은 잔량은
       이번 생성에 쓰이지 않는데도 판정을 붙잡고 있는 셈이다.
       화면의 스위치 설명도 이때 '선택 계정 사용량 0% 기준' 으로 바뀐다 - 판정과
       설명은 같은 것을 말해야 한다.

    ⚠️ **모르면 False 다.** 캐시가 비었거나(폴러가 아직 못 채웠거나 조회가 실패했거나)
       보는 계정 중 하나라도 값을 모르면 판단하지 않는다 - 모르는 것을 소진으로 읽으면
       멀쩡한 루프가 이유 없이 죽는다.
    """
    if not context_uses_usage_limit(context):
        return False        # 무료 풀이 없는 계열에서는 퍼센트에 뜻이 없다
    usage = cached_account_usage(context)
    if not usage:
        return False
    try:
        service = NaiAccountService(context)
        active = [account_id for account_id, _ in service.active_accounts()]
        # 지목한 계정이 있으면 그 하나가 곧 '이번 생성이 쓸 계정' 이다.
        # `forced_account()` 는 못 쓰는 값이면 빈 문자열을 돌려주므로 자연히 전체로 돌아간다.
        forced = service.forced_account()
        if forced:
            active = [forced]
    except Exception:       # noqa: BLE001 - 판정 하나 때문에 생성 루프가 죽으면 안 된다
        return False
    if not active:
        return False
    for account_id in active:
        row = usage.get(account_id)
        if not isinstance(row, dict):
            return False                        # 값을 모르는 계정이 있다
        if row.get("is_negative"):
            continue                            # 음수 = 이미 넘겨 썼다
        percent = row.get("percent")
        if not isinstance(percent, (int, float)) or isinstance(percent, bool):
            return False
        if percent > 0:
            return False                        # 아직 남은 계정이 있다
    return True


# 계정 회전용 카운터.
#
# ⚠️⚠️ **여기가 다중 계정을 조용히 죽여 온 자리다.** 옛 구현과 내 첫 구현 모두
# `app_context.image_crud_controller.get_counter()` 를 썼는데, 헤드리스 컨텍스트
# (`WebSessionContext`)에는 **그 컨트롤러가 아예 없다.** 그래서 계정 선택이 매번
# AttributeError 를 냈고, 넓은 `except` 가 그걸 삼켜 **항상 메인 토큰**이 나갔다.
# 실측(2026-08-21): 라운드 로빈으로 4장을 생성했는데 4장 전부 메인 계정.
# 오류도 안 보이고 그림도 잘 나오니 "되는 줄 알았다".
#
# 그래서 회전은 **자기 카운터**로 센다. 남의 카운터에 얹으면 그 카운터가 어느 날
# 사라져도 이렇게 조용히 꺼진다.
_ROTATION_ATTR = "nai_account_rotation_counter"
_ROTATION_LOCK = threading.Lock()

# ⚠️ 이 파일은 **읽고 -> 고치고 -> 쓴다.** 그 셋이 한 덩어리가 아니면 서로를 지운다:
# 토큰 검증은 워커 스레드에서 끝나며 `set_enabled` 를 부르고, 그 사이 다른 브라우저가
# 이벤트 루프에서 `set_stop_on_exhausted` 를 부를 수 있다. 둘 다 옛 문서를 읽으면
# 나중에 저장한 쪽이 상대의 변경을 되돌린다 - 화면은 이미 "켜짐" 이라 말했는데 다음
# 묶음이 보호 없이 돈다(Codex BLOCK 2026-08-25).
#
# RLock 이다 - 잠근 메서드가 다른 잠근 메서드를 부를 수 있다(같은 스레드 재진입).
_DATA_LOCK = threading.RLock()


def _locked(method):
    """`load -> 고치기 -> save` 한 덩어리를 통째로 잠근다."""

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        with _DATA_LOCK:
            return method(*args, **kwargs)

    return wrapper


def reset_rotation_counter(context: Any) -> None:
    """회전 카운터를 0 으로 되돌린다. **정책을 바꿀 때** 부른다.

    ⚠️ 안 되돌리면 새 정책이 옛 카운터를 자기 방식으로 다시 해석한다. 80~120 으로
    37장 뽑고 400~500 으로 바꾸면 화면이 `37/478` 이 되고(0 부터가 아니다), 라운드
    로빈으로 바꾸면 `37 % 2 = 1` 이라 **계정이 즉시 상대편으로 넘어간다**. 사용자에게
    "정책을 골랐더니 왜 갑자기 계정이 바뀌지" 로 보인다(사용자 지시 2026-08-21:
    "리셋으로 바꿔주세요").

    씨앗은 건드리지 않는다 - 세션 안에서 묶음 크기가 흔들리면 화면이 그릴 때마다
    (peek) 경계가 달라져 실제 생성과 어긋난다.
    """
    with _ROTATION_LOCK:
        setattr(context, _ROTATION_ATTR, 0)


def next_rotation_counter(context: Any) -> int:
    """이번 생성에 쓸 회전 번호. 부를 때마다 1 증가한다(스레드 안전).

    프로세스 수명 동안만 센다 - 재시작하면 0 부터다. 회전에서 중요한 건 절대값이
    아니라 **연속 호출이 서로 다른 값을 받는 것**이라 그걸로 충분하다.
    """
    with _ROTATION_LOCK:
        current = _read_rotation(context)
        setattr(context, _ROTATION_ATTR, current + 1)
        return current


_ROTATION_SEED_ATTR = "nai_account_rotation_seed"


def rotation_seed(context: Any) -> int:
    """구간형 정책(80~120 등)이 묶음 크기를 뽑을 때 쓰는 **세션 씨앗**.

    세션마다 다르되 세션 안에서는 고정이어야 한다 - 고정이 아니면 화면이 "이번
    라운드는 이 계정" 을 그릴 때마다 묶음 경계가 달라져 실제 생성과 어긋난다.
    """
    seed = getattr(context, _ROTATION_SEED_ATTR, None)
    if not isinstance(seed, int):
        seed = random.getrandbits(31) or 1
        setattr(context, _ROTATION_SEED_ATTR, seed)
    return seed


def context_uses_usage_limit(context: Any) -> bool:
    """지금 고른 모델이 V5 계열인가. 판정은 모델 계약이 SSOT 다."""
    from core.nai_model_contract import context_uses_opus_usage_limit

    return context_uses_opus_usage_limit(context)


# 계정별 **이번 세션 생성 장수**. 팝오버가 "총 1,024장" 을 그리는 데 쓴다
# (사용자 요청 2026-08-21).
#
# ⚠️ 회전 카운터에서 나눗셈으로 계산하지 않는다. 소진된 계정은 후보에서 빠지므로
# 실제 배분은 균등하지 않고, 계산값과 실제가 어긋나면 사용자가 보는 숫자가 거짓말이
# 된다. **실제로 고른 순간에만** 센다.
_SESSION_TALLY_ATTR = "nai_account_session_tally"


def note_account_used(context: Any, account_id: str) -> int:
    """이 계정으로 1장 나갔다고 기록하고 누적값을 돌려준다."""
    if not account_id:
        return 0
    with _ROTATION_LOCK:
        tally = account_session_tally(context)
        total = tally.get(account_id, 0) + 1
        tally[account_id] = total
        setattr(context, _SESSION_TALLY_ATTR, tally)
        return total


def account_session_tally(context: Any) -> dict[str, int]:
    """`{계정 id: 이번 세션 생성 장수}`. 프로세스 수명 동안만 센다."""
    tally = getattr(context, _SESSION_TALLY_ATTR, None)
    return tally if isinstance(tally, dict) else {}


def peek_rotation_counter(context: Any) -> int:
    """**소비하지 않고** 다음 회전 번호만 본다.

    화면이 "이번 라운드는 이 계정" 을 표시할 때 쓴다. 여기서 카운터를 올리면
    화면을 그릴 때마다 회전이 어긋나 실제 생성이 계정을 건너뛴다.
    """
    with _ROTATION_LOCK:
        return _read_rotation(context)


def _read_rotation(context: Any) -> int:
    current = getattr(context, _ROTATION_ATTR, 0)
    try:
        return int(current)
    except (TypeError, ValueError):
        return 0


class NaiAccountService:
    """`nai_accounts.json` 읽기/쓰기와 토큰 저장소 연동."""

    def __init__(self, context: Any):
        self.context = context

    # ---- 파일 ----------------------------------------------------------

    def _path(self) -> Path:
        runtime_paths = getattr(self.context, "runtime_paths", None)
        if runtime_paths is not None:
            return Path(runtime_paths.save_dir) / ACCOUNTS_FILENAME
        return Path("save") / ACCOUNTS_FILENAME

    def load(self) -> dict[str, Any]:
        path = self._path()
        if not path.is_file():
            return _default_data()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001 - 깨진 파일이 앱을 막으면 안 된다
            print(f"[warn] nai_accounts.json read failed: {exc}", flush=True)
            return _default_data()
        base = _default_data()
        accounts = data.get("accounts")
        base["accounts"] = [a for a in accounts if isinstance(a, dict) and a.get("id")] \
            if isinstance(accounts, list) else []
        base["round_robin_enabled"] = bool(data.get("round_robin_enabled", False))
        # 옛 파일에는 이 키가 없다. 없으면 메인을 켜 둔 것으로 본다 - 끄면 토큰이
        # 하나도 안 남아 생성이 통째로 막힌다.
        base["main_account_enabled"] = bool(data.get("main_account_enabled", True))
        legacy = data.get(POLICY_KEY_USAGE)
        base[POLICY_KEY_USAGE] = normalize_policy(legacy, True)
        # 비V5 칸이 없는 옛 파일은 옛 키에서 물려받는다.
        base[POLICY_KEY_ANLAS] = normalize_policy(
            data.get(POLICY_KEY_ANLAS, legacy), False)
        # 옛 파일에는 없다. 없으면 꺼진 것으로 본다 - 켜져 있다고 오해하면 사용자가
        # 켠 적 없는 이유로 Auto Gen 이 멈춘다.
        base[STOP_ON_EXHAUSTED_KEY] = bool(data.get(STOP_ON_EXHAUSTED_KEY, False))
        base[FORCED_ACCOUNT_KEY] = str(data.get(FORCED_ACCOUNT_KEY) or "")
        return base

    def save(self, data: dict[str, Any]) -> None:
        # 레거시 파생값을 여기서 한 번에 맞춘다 - 각 변경 메서드가 따로 챙기면
        # 언젠가 한 곳이 빠진다.
        data["round_robin_enabled"] = len(self._active_rows(data)) >= 2
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ---- 토큰 ----------------------------------------------------------

    def _get_token(self, account_id: str) -> str:
        try:
            return str(self.context.secure_token_manager.get_token(account_id) or "").strip()
        except Exception:
            return ""

    def _set_token(self, account_id: str, token: str) -> None:
        self.context.secure_token_manager.save_token(account_id, token)

    def _delete_token(self, account_id: str) -> bool:
        """자격 증명을 지웠는가. **예외도 `False` 도 실패다.**

        저장소 구현이 `False` 를 돌려주는 경우(키 없음/권한)가 있어 반환값도 본다 -
        예외만 보면 그 실패가 조용히 성공으로 보고된다.
        """
        try:
            result = self.context.secure_token_manager.delete_token(account_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] token delete failed for {account_id}: {exc}", flush=True)
            return False
        # 옛 저장소는 `None` 을 돌려주고 성공이다 - 명시적 `False` 만 실패로 본다.
        if result is False:
            print(f"[warn] token delete returned false for {account_id}", flush=True)
            return False
        return True

    # ---- 조회 ----------------------------------------------------------

    def _active_rows(self, data: dict[str, Any]) -> list[tuple[str, str]]:
        """생성에 실제로 쓸 수 있는 `(계정 id, 토큰)` 목록.

        **순서가 계약이다** - 메인 먼저, 그 다음 파일에 적힌 순서. 레거시 리더가
        쓰던 순서 그대로여야 라운드 로빈이 사용자가 보던 것과 같이 돈다.
        """
        rows: list[tuple[str, str]] = []
        main_token = self._get_token(MAIN_ACCOUNT_ID)
        if main_token and data.get("main_account_enabled", True):
            rows.append((MAIN_ACCOUNT_ID, main_token))
        for acc in data.get("accounts", []):
            if not acc.get("enabled"):
                continue
            account_id = str(acc.get("id") or "")
            token = self._get_token(account_id)
            if account_id and token:
                rows.append((account_id, token))
        return rows

    def active_accounts(self) -> list[tuple[str, str]]:
        """생성 경로와 사용량 조회가 함께 쓰는 활성 계정 목록."""
        return self._active_rows(self.load())

    def policy(self, uses_usage_limit: bool | None = None) -> str:
        """이 모델 계열에서 지금 걸린 정책. 안 주면 컨텍스트에서 판정한다."""
        if uses_usage_limit is None:
            uses_usage_limit = context_uses_usage_limit(self.context)
        key = POLICY_KEY_USAGE if uses_usage_limit else POLICY_KEY_ANLAS
        return normalize_policy(self.load().get(key), uses_usage_limit)

    def all_account_ids(self, data: dict[str, Any] | None = None) -> list[str]:
        data = data if data is not None else self.load()
        return [MAIN_ACCOUNT_ID] + [str(a.get("id")) for a in data.get("accounts", [])
                                    if a.get("id")]

    def find_token_owner(self, token: str, *, exclude: str = "") -> str:
        """이 토큰을 **이미** 갖고 있는 계정 id. 없으면 빈 문자열.

        같은 토큰을 두 계정에 넣으면 계정 수만 늘고 한도는 그대로다 - 사용자는
        두 배로 쓸 수 있다고 믿는데 실제로는 아니다. 게다가 패널 합계가 같은
        계정을 두 번 세어 **없는 잔량을 있다고 표시한다**(실측: Anlas 19,896 인데
        실제 9,948). 조용히 손해 보는 구성이라 입력 단계에서 걸러야 한다.
        """
        token = str(token or "").strip()
        if not token:
            return ""
        for account_id in self.all_account_ids():
            if account_id == exclude:
                continue
            if self._get_token(account_id) == token:
                return account_id
        return ""

    def snapshot(self) -> dict[str, Any]:
        """프런트가 그릴 수 있는 형태. **토큰 전문은 절대 넣지 않는다.**"""
        data = self.load()
        main_token = self._get_token(MAIN_ACCOUNT_ID)
        rows = [{
            "id": MAIN_ACCOUNT_ID,
            "label": MAIN_ACCOUNT_LABEL,
            "enabled": bool(data["main_account_enabled"]),
            "has_token": bool(main_token),
            "token_preview": token_preview(main_token),
            "is_main": True,
        }]
        for acc in data["accounts"]:
            token = self._get_token(str(acc["id"]))
            rows.append({
                "id": str(acc["id"]),
                "label": str(acc.get("label") or account_label(str(acc["id"]))),
                "enabled": bool(acc.get("enabled", False)),
                "has_token": bool(token),
                "token_preview": token_preview(token),
                "is_main": False,
            })
        # 중복 표시. 입력 단계에서 막지만, **메인 토큰은 위쪽 '영구 토큰' 칸으로도
        # 바뀌므로**(이 서비스를 안 거친다) 이미 겹쳐 있는 상태가 생길 수 있다.
        # 그때는 막을 수 없으니 최소한 화면이 말해 줘야 한다.
        seen: dict[str, str] = {}
        for row in rows:
            token = self._get_token(row["id"])
            row["duplicate_of"] = seen.get(token, "") if token else ""
            if token and token not in seen:
                seen[token] = row["label"]
        active = [r for r in rows if r["enabled"] and r["has_token"]]
        on_v5 = context_uses_usage_limit(self.context)
        policy_key = POLICY_KEY_USAGE if on_v5 else POLICY_KEY_ANLAS
        return {
            "accounts": rows,
            # ⚠️ 지금 **모델 계열의** 정책이다. 계열마다 목록이 다르므로 이걸 틀리면
            # 화면에 없는 라디오가 켜져 있거나, 아무것도 안 켜져 보인다.
            "policy": normalize_policy(data.get(policy_key), on_v5),
            "uses_usage_limit": on_v5,
            "active_count": len(active),
            # 활성 계정이 2개 미만이면 정책이 아무 일도 안 한다. 프런트가 라디오를
            # 흐리게 만들어 "골랐는데 안 바뀐다" 를 없앤다.
            "balancing_effective": len(active) >= 2,
            "can_add": len(data["accounts"]) < MAX_ACCOUNTS,
            "max_accounts": MAX_ACCOUNTS,
            STOP_ON_EXHAUSTED_KEY: bool(data.get(STOP_ON_EXHAUSTED_KEY, False)),
            # ⚠️ **지금 쓸 수 있는 값만 보고한다.** 고른 계정을 나중에 끄거나 지우면
            #    저장된 값은 남는데 선택은 정책으로 되돌아간다 - 그대로 보고하면
            #    화면은 "이 계정만 사용" 이라 말하는데 실제로는 돌아가고 있게 된다.
            FORCED_ACCOUNT_KEY: self._effective_forced(data, active),
        }

    # ---- 변경 ----------------------------------------------------------

    def next_account_id(self, data: dict[str, Any]) -> str:
        existing = {str(a.get("id")) for a in data["accounts"]}
        index = 1
        while f"{MAIN_ACCOUNT_ID}_{index}" in existing:
            index += 1
        return f"{MAIN_ACCOUNT_ID}_{index}"

    @_locked
    def add_account(self) -> dict[str, Any]:
        data = self.load()
        if len(data["accounts"]) >= MAX_ACCOUNTS:
            return {"ok": False, "message": f"계정은 최대 {MAX_ACCOUNTS}개까지 추가할 수 있습니다."}
        account_id = self.next_account_id(data)
        data["accounts"].append({
            "id": account_id,
            "label": account_label(account_id),
            # 토큰이 없는 채로 켜 두면 라운드 로빈이 빈 계정을 세지는 않지만
            # 사용자에게는 "켰는데 안 쓰인다" 로 보인다. 꺼진 채로 만든다.
            "enabled": False,
            "last_verified": None,
        })
        self.save(data)
        return {"ok": True, "account_id": account_id}

    @_locked
    def delete_account(self, account_id: str) -> dict[str, Any]:
        if account_id == MAIN_ACCOUNT_ID:
            return {"ok": False, "message": "메인 계정은 삭제할 수 없습니다."}
        data = self.load()
        before = len(data["accounts"])
        data["accounts"] = [a for a in data["accounts"] if str(a.get("id")) != account_id]
        if len(data["accounts"]) == before:
            return {"ok": False, "message": "계정을 찾을 수 없습니다."}
        # 지운 계정의 id 는 나중에 재사용된다 - 지목을 남기면 **남의 자리**로 간다.
        self._drop_forced_if_unusable(data, {a for a, _ in self._active_rows(data)})
        self.save(data)
        # ⚠️ 토큰 삭제 실패를 삼키면 **지운 계정의 자격 증명이 저장소에 남는다.**
        # 명부에서 빠져 회전에는 안 들어가므로 생성은 멀쩡하지만, 사용자는 "지웠다"
        # 고 믿는데 토큰은 그대로다. 목록에서 사라지는 것과 자격 증명이 사라지는 것은
        # 다른 이야기라, 후자가 실패하면 반드시 말해 준다(Codex 리뷰 2026-08-21).
        if not self._delete_token(account_id):
            return {"ok": True, "level": "warning",
                    "message": "계정은 삭제했지만 저장된 토큰을 지우지 못했습니다. "
                               "자격 증명이 남아 있으니 확인해 주세요."}
        return {"ok": True}

    @_locked
    def set_enabled(self, account_id: str, enabled: bool) -> dict[str, Any]:
        data = self.load()
        if account_id == MAIN_ACCOUNT_ID:
            data["main_account_enabled"] = bool(enabled)
        else:
            found = False
            for acc in data["accounts"]:
                if str(acc.get("id")) == account_id:
                    acc["enabled"] = bool(enabled)
                    found = True
                    break
            if not found:
                return {"ok": False, "message": "계정을 찾을 수 없습니다."}
        # 끈 계정이 지목돼 있었으면 그 지목도 함께 버린다(위 주석 참조).
        self._drop_forced_if_unusable(data, {a for a, _ in self._active_rows(data)})
        self.save(data)
        return {"ok": True}

    def set_token(self, account_id: str, token: str) -> dict[str, Any]:
        """사용자가 입력한 토큰을 저장한다. 메인 계정도 이 경로를 쓸 수 있다."""
        token = str(token or "").strip()
        if not token:
            return {"ok": False, "message": "토큰이 비어 있습니다."}
        if account_id != MAIN_ACCOUNT_ID:
            data = self.load()
            if not any(str(a.get("id")) == account_id for a in data["accounts"]):
                return {"ok": False, "message": "계정을 찾을 수 없습니다."}
        self._set_token(account_id, token)
        return {"ok": True, "token_preview": token_preview(token)}

    @_locked
    def set_policy(self, policy: str, uses_usage_limit: bool | None = None) -> dict[str, Any]:
        """부하 분산 정책 선택. 모르는 값은 기본(라운드 로빈)으로 눕힌다.

        **지금 모델 계열의 칸에만 쓴다** - 다른 계열의 선택은 건드리지 않는다.

        ⚠️ **지목 해제도 여기서 함께 한다**(Codex 리뷰 2026-08-27). 화면에서 두
           커맨드(`set_forced('')` + `set_policy`)로 나눠 보냈더니 그 사이가 원자적이
           아니었다 - 그 틈에 Auto Gen 이 토큰을 고르면 화면은 새 정책인데 실제
           이미지는 옛 지목 계정으로 나간다. 한 잠금 안에서 같이 쓴다.
        """
        if uses_usage_limit is None:
            uses_usage_limit = context_uses_usage_limit(self.context)
        key = POLICY_KEY_USAGE if uses_usage_limit else POLICY_KEY_ANLAS
        data = self.load()
        previous = normalize_policy(data.get(key), uses_usage_limit)
        data[key] = normalize_policy(policy, uses_usage_limit)
        # 정책을 고르는 것은 "다시 나눠 써라" 는 뜻이다 - 지목은 그 자리에서 풀린다.
        forced_cleared = bool(data.get(FORCED_ACCOUNT_KEY))
        data[FORCED_ACCOUNT_KEY] = ""
        self.save(data)
        # 정책이 실제로 바뀌었으면 회전을 **처음부터** 다시 센다(사용자 지시
        # 2026-08-21). 이유는 `reset_rotation_counter` 주석 참조.
        if data[key] != previous or forced_cleared:
            reset_rotation_counter(self.context)
        return {"ok": True, "policy": data[key], FORCED_ACCOUNT_KEY: ""}

    @staticmethod
    def _drop_forced_if_unusable(data: dict[str, Any], usable: set[str]) -> bool:
        """못 쓰게 된 지목을 **파일에서 지운다**. 지웠으면 True.

        ⚠️ 숨기기만 하면 유령이 남는다(Codex 리뷰 2026-08-27). 스냅샷은 빈 값을
           보내므로 화면도 지목을 모르고, 따라서 해제 커맨드도 안 나간다 - 그런데
           파일에는 값이 남아 있어서 그 계정을 **다시 켜는 순간** 사용자가 고르지도
           않은 단일 계정 모드로 돌아간다. 더 나쁜 경우: 지운 계정의 id 는
           `next_account_id()` 가 다시 내주므로(`nai_token_1`), **다른 계정**이
           그 지목을 물려받는다.
        """
        forced = str(data.get(FORCED_ACCOUNT_KEY) or "")
        if forced and forced not in usable:
            data[FORCED_ACCOUNT_KEY] = ""
            return True
        return False

    @staticmethod
    def _effective_forced(data: dict[str, Any], active_rows: list[dict[str, Any]]) -> str:
        """저장된 '고른 계정' 중 **지금 실제로 쓸 수 있는** 것만 돌려준다."""
        forced = str(data.get(FORCED_ACCOUNT_KEY) or "")
        if not forced:
            return ""
        return forced if any(row["id"] == forced for row in active_rows) else ""

    def forced_account(self) -> str:
        """생성 경로가 읽는 값. 못 쓰는 값이면 빈 문자열(= 정책으로)."""
        data = self.load()
        forced = str(data.get(FORCED_ACCOUNT_KEY) or "")
        if not forced:
            return ""
        # ⚠️ **같은 판**으로 판정한다. `active_accounts()` 를 부르면 파일을 다시
        #    읽어, 그 사이에 바뀐 명부와 이 값이 어긋날 수 있다.
        return forced if any(a == forced for a, _ in self._active_rows(data)) else ""

    @_locked
    def set_forced_account(self, account_id: str) -> dict[str, Any]:
        """계정 하나를 지목한다. 빈 값이면 해제하고 부하 분산으로 돌아간다.

        ⚠️ **활성 계정만** 지목할 수 있다. 꺼져 있거나 토큰이 없는 계정을 가리키면
           생성은 정책으로 돌아가는데 화면만 지목됐다고 말해 어긋난다.
        """
        account_id = str(account_id or "")
        data = self.load()
        if account_id:
            usable = {a for a, _ in self._active_rows(data)}
            if account_id not in usable:
                return {"ok": False, "message": "활성 계정만 선택할 수 있습니다."}
        previous = str(data.get(FORCED_ACCOUNT_KEY) or "")
        data[FORCED_ACCOUNT_KEY] = account_id
        self.save(data)
        # 지목을 걸거나 풀면 회전을 처음부터 다시 센다 - 정책을 바꿀 때와 같은 이유다
        # (묶음 중간에서 이어받으면 화면의 진행 게이지가 거짓말을 한다).
        if account_id != previous:
            reset_rotation_counter(self.context)
        return {"ok": True, FORCED_ACCOUNT_KEY: account_id}

    @_locked
    def set_stop_on_exhausted(self, enabled: bool) -> dict[str, Any]:
        """모든 계정이 0% 에 닿으면 Auto Gen 을 끌 것인가(사용자 지정).

        계열을 나누지 않는다 - 무료 풀은 V5 에만 있으므로 비V5 에서는 판정이 애초에
        서지 않는다(`generation_quota_exhausted`).
        """
        data = self.load()
        data[STOP_ON_EXHAUSTED_KEY] = bool(enabled)
        self.save(data)
        return {"ok": True, STOP_ON_EXHAUSTED_KEY: data[STOP_ON_EXHAUSTED_KEY]}
