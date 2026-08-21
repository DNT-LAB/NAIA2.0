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
POLICY_ROUND_ROBIN_80_120 = "round_robin_80_120"
POLICY_ROUND_ROBIN_400_500 = "round_robin_400_500"

# 구간형 정책의 범위(양끝 포함). 묶음마다 이 안에서 값을 하나 뽑는다.
POLICY_RANGES: dict[str, tuple[int, int]] = {
    POLICY_ROUND_ROBIN_80_120: (80, 120),
    POLICY_ROUND_ROBIN_400_500: (400, 500),
}

POLICIES: tuple[str, ...] = (
    POLICY_ROUND_ROBIN,
    POLICY_ROUND_ROBIN_10,
    POLICY_ROUND_ROBIN_80_120,
    POLICY_ROUND_ROBIN_400_500,
)

DEFAULT_POLICY = POLICY_ROUND_ROBIN

# 10장 단위 정책의 묶음 크기.
BLOCK = 10

# 동적 할당(-10)은 없앴다(사용자 지시 2026-08-21). 잔량을 보고 균등화하는 방식은
# **퍼센트가 정수라 해상도가 너무 거칠었다** - 1% 가 약 17장이라 값이 한 번 움직일
# 때까지 같은 계정만 골랐고, 그동안은 라운드 로빈과 구분되지 않았다.
# 설정에 남아 있는 옛 키(`dynamic` / `dynamic_10`)는 `POLICIES` 에 없으므로
# `normalize_policy` 가 기본값으로 눕힌다 - 따로 지울 필요가 없다.


def normalize_policy(value: Any) -> str:
    v = str(value or "").strip()
    return v if v in POLICIES else DEFAULT_POLICY


def _block_size(seed: int, index: int, low: int, high: int) -> int:
    """`index` 번째 묶음의 크기. `low..high` 안의 값 하나.

    **난수 생성기를 쓰지 않는다.** 같은 (seed, index) 는 늘 같은 값이어야 한다 -
    안 그러면 화면이 "이번 라운드는 이 계정" 을 그릴 때마다(peek) 경계가 흔들려
    실제 생성과 어긋난다. 해시로 만들면 상태 없이 같은 답이 나온다.
    """
    span = max(1, high - low + 1)
    h = (int(seed) * 2654435761 + int(index) * 40503) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return low + (h % span)


def _ranged_block_index(counter: int, seed: int, low: int, high: int) -> int:
    """`counter` 장째가 몇 번째 묶음에 드는가.

    묶음 크기가 매번 달라(80~120 등) 나눗셈으로는 못 구한다. 앞에서부터 더해 간다 -
    묶음이 최소 80장이라 한 세션에서 도는 횟수는 수십 번을 넘지 않는다.
    """
    counter = max(0, int(counter))
    index = 0
    consumed = 0
    while True:
        consumed += _block_size(seed, index, low, high)
        if counter < consumed:
            return index
        index += 1
        if index > 100000:                      # 폭주 방지(현실적으로 도달 불가)
            return index


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
    seed: int = 0,
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

    step = max(0, int(counter))

    # 구간형: 묶음 크기를 80~120(또는 400~500) 안에서 뽑고, 그 수만큼 채우면 계정을
    # 바꾸면서 **새 값을 다시 뽑는다**(사용자 지시 2026-08-21).
    span = POLICY_RANGES.get(policy)
    if span is not None:
        return pool[_ranged_block_index(step, seed, span[0], span[1]) % len(pool)]

    if policy == POLICY_ROUND_ROBIN_10:
        return pool[(step // BLOCK) % len(pool)]
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
        {"key": POLICY_ROUND_ROBIN_80_120, "label": "라운드 로빈-80~120",
         "desc": "80~120 사이에서 값을 하나 뽑아 그만큼 생성한 뒤 계정을 바꾸고, "
                 "새 값을 다시 뽑습니다. 한 토큰의 사용량을 모두 소모하면 이후에는 "
                 "남은 계정에서만 생성합니다."},
        {"key": POLICY_ROUND_ROBIN_400_500, "label": "라운드 로빈-400~500",
         "desc": "400~500 사이에서 값을 하나 뽑아 그만큼 생성한 뒤 계정을 바꾸고, "
                 "새 값을 다시 뽑습니다. 한 토큰의 사용량을 모두 소모하면 이후에는 "
                 "남은 계정에서만 생성합니다."},
    ]
