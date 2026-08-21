"""다중 계정 부하 분산 정책 (Multi Token).

사용자 명세(2026-08-21):

    [v] 라운드 로빈      1장씩 번갈아 생성. 한 토큰의 사용량을 다 쓰면 이후에는
                         남은 계정에서만 생성한다.
    [ ] 라운드 로빈-10   10장씩 번갈아. 소진 규칙은 같다.
    [ ] 동적 할당        각 계정의 Usage 를 **균일하게 맞춰 가며** 생성한다.
                         전부 같아지면 그때부터 라운드 로빈처럼 돈다.
    [ ] 동적 할당-10     동적 할당인데 10장 단위로 고정. 같아지면 라운드 로빈-10.

여기는 **순수 함수만** 둔다. 네트워크도 파일도 만지지 않는다 - 계정 선택은 유료
생성 경로가 매번 지나가는 자리라, 값만 넣으면 결과가 정해지는 형태여야 테스트로
못 박을 수 있다.

⚠️ 소진 판정을 잘못하면 **돈이 샌다.** V5 무료 사용량이 남은 계정을 두고 소진된
계정을 고르면 그 장은 Anlas 로 청구된다. 그래서 "모르면 소진이 아니다" 로 둔다 -
usage 를 못 받은 계정(None)은 후보에 남긴다. 반대로 하면 조회 한 번 실패에
멀쩡한 계정이 통째로 빠진다.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

# 파일에 저장되는 정책 키. 프런트 라디오와 1:1 이다.
POLICY_ROUND_ROBIN = "round_robin"
POLICY_ROUND_ROBIN_10 = "round_robin_10"
POLICY_DYNAMIC = "dynamic"
POLICY_DYNAMIC_10 = "dynamic_10"

POLICIES: tuple[str, ...] = (
    POLICY_ROUND_ROBIN,
    POLICY_ROUND_ROBIN_10,
    POLICY_DYNAMIC,
    POLICY_DYNAMIC_10,
)

DEFAULT_POLICY = POLICY_ROUND_ROBIN

# 10장 단위 정책의 묶음 크기.
BLOCK = 10


def normalize_policy(value: Any) -> str:
    v = str(value or "").strip()
    return v if v in POLICIES else DEFAULT_POLICY


def is_exhausted(usage: Any) -> bool:
    """이 계정의 V5 무료 사용량이 바닥났는가.

    `usage` 는 `{"percent": int, "is_negative": bool}` 또는 None(모름).
    **모르면 False** - 위 주석의 이유로, 조회 실패가 계정을 빼앗으면 안 된다.
    """
    if not isinstance(usage, dict):
        return False
    if usage.get("is_negative"):
        return True
    percent = usage.get("percent")
    if percent is None:
        # ⚠️ 기본값을 0 으로 두면 **빈 dict 가 소진으로 판정된다**(내 첫 구현의 버그,
        # 테스트가 잡았다). `{}` 는 "모른다" 이지 "다 썼다" 가 아니다.
        return False
    try:
        return int(percent) <= 0
    except (TypeError, ValueError):
        return False


def _percent(usage: Any) -> int:
    """정렬용 잔량. 모르는 계정은 100 으로 봐서 우선 후보가 되게 한다."""
    if not isinstance(usage, dict):
        return 100
    try:
        return int(usage.get("percent", 100))
    except (TypeError, ValueError):
        return 100


def average_percent(usage_by_id: dict[str, Any], account_ids: Iterable[str]) -> int | None:
    """배지에 찍을 **통합값**. 명세대로 합이 아니라 평균이다.

    usage 를 하나도 못 받았으면 None(= 배지를 띄우지 않는다).
    """
    known = [_percent(usage_by_id.get(a)) for a in account_ids
             if isinstance(usage_by_id.get(a), dict)]
    if not known:
        return None
    return round(sum(known) / len(known))


def select_account(
    account_ids: Sequence[str],
    *,
    policy: str = DEFAULT_POLICY,
    counter: int = 0,
    usage_by_id: dict[str, Any] | None = None,
) -> str:
    """이번 생성에 쓸 계정 id 하나.

    `counter` 는 기존 구현과 같은 이미지 카운터다(단조 증가). 이것만으로 결정되므로
    같은 입력이면 같은 결과가 나온다.
    """
    ids = [a for a in account_ids if a]
    if not ids:
        return ""
    if len(ids) == 1:
        return ids[0]

    usage_by_id = usage_by_id or {}
    policy = normalize_policy(policy)

    # 1) 소진된 계정을 뺀다. 다 소진됐으면 **아무도 빼지 않는다** - 그때는 Anlas 로
    #    계속 생성할 수 있으므로, 후보를 비워 생성을 막는 편이 더 나쁘다.
    live = [a for a in ids if not is_exhausted(usage_by_id.get(a))]
    pool = live if live else ids

    if len(pool) == 1:
        return pool[0]

    block = max(0, int(counter)) // BLOCK
    step = max(0, int(counter))

    if policy in (POLICY_DYNAMIC, POLICY_DYNAMIC_10):
        top = max(_percent(usage_by_id.get(a)) for a in pool)
        leaders = [a for a in pool if _percent(usage_by_id.get(a)) == top]
        if len(leaders) < len(pool):
            # 아직 균일하지 않다 - 가장 많이 남은 쪽을 쓴다. 선두가 여럿이면
            # 그 안에서만 돌려 한 계정에 몰리지 않게 한다.
            idx = (block if policy == POLICY_DYNAMIC_10 else step) % len(leaders)
            return leaders[idx]
        # 전부 같아졌다 -> 명세대로 라운드 로빈 정책으로 넘어간다.
        policy = POLICY_ROUND_ROBIN_10 if policy == POLICY_DYNAMIC_10 else POLICY_ROUND_ROBIN

    if policy == POLICY_ROUND_ROBIN_10:
        return pool[block % len(pool)]
    return pool[step % len(pool)]


def policy_options() -> list[dict[str, str]]:
    """프런트가 라디오를 그릴 때 쓰는 목록. 문구는 사용자 명세 그대로."""
    return [
        {"key": POLICY_ROUND_ROBIN, "label": "라운드 로빈",
         "desc": "1장씩 번갈아가며 생성합니다. 한 토큰의 사용량을 모두 소모하면 "
                 "이후에는 남은 계정에서만 생성합니다."},
        {"key": POLICY_ROUND_ROBIN_10, "label": "라운드 로빈-10",
         "desc": "10장씩 번갈아가며 생성합니다. 한 토큰의 사용량을 모두 소모하면 "
                 "이후에는 남은 계정에서만 생성합니다."},
        {"key": POLICY_DYNAMIC, "label": "동적 할당",
         "desc": "각 계정의 Usage를 균일하게 맞춰가며 생성합니다. Usage가 전부 "
                 "같아지면 이후에는 라운드 로빈 정책이 적용됩니다."},
        {"key": POLICY_DYNAMIC_10, "label": "동적 할당-10",
         "desc": "각 계정의 Usage를 균일하게 맞춰가며 생성하되 10장 단위로 "
                 "고정됩니다. 같아지면 라운드 로빈-10 정책이 적용됩니다."},
    ]
