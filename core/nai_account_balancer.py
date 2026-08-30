"""다중 계정 부하 분산 정책 (Multi Token).

사용자 명세(2026-08-21). **정책 목록은 모델 계열마다 다르다**:

    V5 계열(무료 사용량 % 가 있다)
        [v] 라운드 로빈      1장씩 번갈아 생성. 한 토큰의 사용량을 다 쓰면 이후에는
                             남은 계정에서만 생성한다.
        [ ] 라운드 로빈-10   10장씩 번갈아. 소진 규칙은 같다.
        [ ] 동적 할당        각 계정의 Usage 를 **균일하게 맞춰 가며** 생성한다.
                             전부 같아지면 그때부터 라운드 로빈처럼 돈다.
        [ ] 동적 할당-10     동적 할당인데 10장 단위로 고정. 같아지면 라운드 로빈-10.

    V5 가 아닌 계열(Anlas 로만 청구된다)
        [v] 라운드 로빈 / 라운드 로빈-10   위와 같다.
        [ ] 라운드 로빈-80~120   80~120 중 하나를 뽑아 그만큼 생성한 뒤 교체하고
                                 새 값을 다시 뽑는다.
        [ ] 라운드 로빈-400~500  같은 방식, 범위만 다르다.

⚠️ **동적 할당을 비V5 에 두면 안 된다.** 그것이 균등화하는 값은 V5 무료 사용량 %
인데, V4.5 생성은 그 %를 건드리지 않는다 - 아무리 생성해도 값이 안 움직여서 정책이
라운드 로빈과 구분되지 않는다. 반대로 구간형(80~120 / 400~500)을 V5 에 두면 사용자가
잔량을 보고 고르던 방식을 잃는다. 그래서 목록을 갈랐다(사용자 지적 2026-08-21:
"NAID5 에서 NAID4.5 사양의 로드 밸런싱 정책이 나타납니다").

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
POLICY_ROUND_ROBIN_80_120 = "round_robin_80_120"
POLICY_ROUND_ROBIN_400_500 = "round_robin_400_500"

# 구간형 정책의 범위(양끝 포함). 묶음마다 이 안에서 값을 하나 뽑는다.
POLICY_RANGES: dict[str, tuple[int, int]] = {
    POLICY_ROUND_ROBIN_80_120: (80, 120),
    POLICY_ROUND_ROBIN_400_500: (400, 500),
}

# 모델 계열별 목록(화면 순서 그대로).
USAGE_POLICIES: tuple[str, ...] = (
    POLICY_ROUND_ROBIN,
    POLICY_ROUND_ROBIN_10,
    POLICY_DYNAMIC,
    POLICY_DYNAMIC_10,
)
ANLAS_POLICIES: tuple[str, ...] = (
    POLICY_ROUND_ROBIN,
    POLICY_ROUND_ROBIN_10,
    POLICY_ROUND_ROBIN_80_120,
    POLICY_ROUND_ROBIN_400_500,
)

# 저장을 허용하는 전체 집합(두 계열의 합집합, 순서 유지).
POLICIES: tuple[str, ...] = tuple(dict.fromkeys(USAGE_POLICIES + ANLAS_POLICIES))

DEFAULT_POLICY = POLICY_ROUND_ROBIN

# 10장 단위 정책의 묶음 크기.
BLOCK = 10

# 계열이 다른 정책으로 넘어갈 때의 착지점. 뜻이 가장 가까운 쪽으로 눕힌다.
# ⚠️ 저장은 계열마다 따로 하므로(`nai_account_service`) 이 폴백은 옛 파일을 읽을 때와
# 방어용일 뿐이다 - 모델을 오갔다고 사용자가 고른 값이 서로를 덮지 않는다.
_FAMILY_FALLBACK: dict[str, str] = {
    POLICY_DYNAMIC: POLICY_ROUND_ROBIN,
    POLICY_DYNAMIC_10: POLICY_ROUND_ROBIN_10,
    POLICY_ROUND_ROBIN_80_120: POLICY_ROUND_ROBIN,
    POLICY_ROUND_ROBIN_400_500: POLICY_ROUND_ROBIN,
}


def family_policies(uses_usage_limit: bool) -> tuple[str, ...]:
    """이 모델 계열에서 고를 수 있는 정책 키들."""
    return USAGE_POLICIES if uses_usage_limit else ANLAS_POLICIES


def normalize_policy(value: Any, uses_usage_limit: bool | None = None) -> str:
    """저장/사용 전에 정책 키를 다듬는다.

    `uses_usage_limit` 를 주면 **그 계열 안으로** 눕힌다(화면에 없는 라디오가 켜져
    보이는 일을 막는다). 안 주면 저장 가능한 전체 집합만 본다.
    """
    v = str(value or "").strip()
    if uses_usage_limit is None:
        return v if v in POLICIES else DEFAULT_POLICY
    allowed = family_policies(bool(uses_usage_limit))
    if v in allowed:
        return v
    fallback = _FAMILY_FALLBACK.get(v, DEFAULT_POLICY)
    return fallback if fallback in allowed else DEFAULT_POLICY


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


def _ranged_block(counter: int, seed: int, low: int, high: int) -> tuple[int, int, int]:
    """`counter` 장째가 든 묶음의 `(번호, 그 묶음에서 몇 장째, 묶음 크기)`.

    묶음 크기가 매번 달라(80~120 등) 나눗셈으로는 못 구한다. 앞에서부터 더해 간다 -
    묶음이 최소 80장이라 한 세션에서 도는 횟수는 수십 번을 넘지 않는다.
    """
    counter = max(0, int(counter))
    index = 0
    consumed = 0
    while True:
        size = _block_size(seed, index, low, high)
        if counter < consumed + size:
            return index, counter - consumed, size
        consumed += size
        index += 1
        if index > 100000:                      # 폭주 방지(현실적으로 도달 불가)
            return index, 0, size


def _ranged_block_index(counter: int, seed: int, low: int, high: int) -> int:
    return _ranged_block(counter, seed, low, high)[0]


def rotation_block(policy: str, counter: int, seed: int = 0) -> tuple[int, int]:
    """지금 묶음의 `(진행 장수, 목표 장수)`.

    화면이 "목표 100장 · 현재 37장" 과 게이지를 그리는 데 쓴다(사용자 요청
    2026-08-21). `counter` 는 **다음에 쓸 값**(peek)이므로 그대로 '이미 생성한 장수'
    가 된다 - 첫 장이 counter 0 을 소비하기 때문이다.
    """
    policy = normalize_policy(policy)
    counter = max(0, int(counter))
    span = POLICY_RANGES.get(policy)
    if span is not None:
        _index, current, size = _ranged_block(counter, seed, span[0], span[1])
        return current, size
    if policy in (POLICY_ROUND_ROBIN_10, POLICY_DYNAMIC_10):
        return counter % BLOCK, BLOCK
    return 0, 1


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


def _anlas(usage: Any) -> int:
    """정렬용 Anlas 잔량. **모르는 계정은 -1** 이다.

    ⚠️ `_percent` 는 모르는 계정을 100 으로 봐서 우선 후보로 올리는데, 여기서 같은
       손버릇을 쓰면 **잔량을 모르는 계정에 돈이 몰린다**. 모르면 뒤로 미룬다 -
       전부 모르면 서로 같아져 라운드 로빈으로 넘어간다.
    """
    if not isinstance(usage, dict):
        return -1
    value = usage.get("anlas")
    if not isinstance(value, int):
        return -1
    return value


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
    forced: str = "",
    prefer_anlas: bool = False,
) -> str:
    """이번 생성에 쓸 계정 id 하나.

    `counter` 는 기존 구현과 같은 이미지 카운터다(단조 증가). 이것만으로 결정되므로
    같은 입력이면 같은 결과가 나온다.

    `forced` 는 사용자가 **직접 고른 계정**이다(사용자 지정 2026-08-27). 있으면
    정책보다 먼저다 - 부하 분산은 "알아서 나눠 달라" 는 뜻이고, 계정을 지목한
    것은 그 반대의 뜻이기 때문이다.

    ⚠️ **소진돼도 그 계정을 쓴다.** 정책 경로는 0% 인 계정을 후보에서 빼지만,
       지목은 명시적인 선택이라 말없이 다른 계정으로 옮기면 안 된다(그러면 이
       기능이 있으나 마나다). 무료 풀이 마르면 Anlas 로 계속 생성된다 - 그것을
       원치 않으면 'Safety' 스위치가 Auto Gen 을 끈다.
    ⚠️ 목록에 없는 id(계정을 끄거나 지운 뒤 남은 값)면 **정책으로 되돌아간다.**
       고를 수 없는 것을 가리킨 채 생성을 막는 쪽이 더 나쁘다.
    """
    ids = [a for a in account_ids if a]
    if not ids:
        return ""
    if forced and forced in ids:
        return forced
    if len(ids) == 1:
        return ids[0]

    usage_by_id = usage_by_id or {}
    policy = normalize_policy(policy)

    # 1) 소진된 계정을 뺀다. 다 소진됐으면 **아무도 빼지 않는다** - 그때는 Anlas 로
    #    계속 생성할 수 있으므로, 후보를 비워 생성을 막는 편이 더 나쁘다.
    #
    # ⚠️ **유료 모드에서는 걸러 내지 않는다.** 이 판정은 V5 **무료 사용량**이 말랐는가를
    #    보는 것인데, 지금 나가는 돈은 Anlas 다 - 사용량이 0% 인 계정도 Anlas 가 있으면
    #    멀쩡하게 쓴다. 여기서 빼면 버리는 후보가 생긴다(사용자 지정 2026-08-30).
    if prefer_anlas:
        pool = list(ids)
    else:
        live = [a for a in ids if not is_exhausted(usage_by_id.get(a))]
        pool = live if live else ids

    if len(pool) == 1:
        return pool[0]

    step = max(0, int(counter))
    block = step // BLOCK

    # 동적 할당: 잔량이 가장 많은 쪽을 쓴다. 전부 같아지면 라운드 로빈으로 넘어간다.
    if policy in (POLICY_DYNAMIC, POLICY_DYNAMIC_10):
        # ⚠️ **재는 자를 지금 깎이는 것에 맞춘다**(사용자 지정 2026-08-30).
        #    동적 할당은 "각 계정을 균일하게 맞춰 간다" 는 약속인데, 유료 모드에서
        #    V5 무료 사용량 % 를 보면 **그 값이 안 움직인다** - 깎이는 것은 Anlas 다.
        #    그러면 선두가 영영 그대로여서 한 계정만 계속 쓰게 된다
        #    (사용자 제보: "유료 모드에서 Load Balancing 정책이 적용되지 않는다").
        metric = _anlas if prefer_anlas else _percent
        top = max(metric(usage_by_id.get(a)) for a in pool)
        leaders = [a for a in pool if metric(usage_by_id.get(a)) == top]
        if len(leaders) < len(pool):
            # 아직 균일하지 않다 - 선두가 여럿이면 그 안에서만 돌려 한 계정에
            # 몰리지 않게 한다.
            idx = (block if policy == POLICY_DYNAMIC_10 else step) % len(leaders)
            return leaders[idx]
        policy = POLICY_ROUND_ROBIN_10 if policy == POLICY_DYNAMIC_10 else POLICY_ROUND_ROBIN

    # 구간형: 묶음 크기를 80~120(또는 400~500) 안에서 뽑고, 그 수만큼 채우면 계정을
    # 바꾸면서 **새 값을 다시 뽑는다**(사용자 지시 2026-08-21).
    span = POLICY_RANGES.get(policy)
    if span is not None:
        return pool[_ranged_block_index(step, seed, span[0], span[1]) % len(pool)]

    if policy == POLICY_ROUND_ROBIN_10:
        return pool[block % len(pool)]
    return pool[step % len(pool)]


_POLICY_TEXT: dict[str, tuple[str, str]] = {
    POLICY_ROUND_ROBIN: (
        "라운드 로빈",
        "1장씩 번갈아가며 생성합니다. 한 토큰의 사용량을 모두 소모하면 "
        "이후에는 남은 계정에서만 생성합니다."),
    POLICY_ROUND_ROBIN_10: (
        "라운드 로빈-10",
        "10장씩 번갈아가며 생성합니다. 한 토큰의 사용량을 모두 소모하면 "
        "이후에는 남은 계정에서만 생성합니다."),
    POLICY_DYNAMIC: (
        "동적 할당",
        "각 계정의 Usage를 균일하게 맞춰가며 생성합니다. Usage가 전부 같아지면 "
        "이후에는 라운드 로빈 정책이 적용됩니다."),
    POLICY_DYNAMIC_10: (
        "동적 할당-10",
        "각 계정의 Usage를 균일하게 맞춰가며 생성하되 10장 단위로 고정됩니다. "
        "같아지면 라운드 로빈-10 정책이 적용됩니다."),
    POLICY_ROUND_ROBIN_80_120: (
        "라운드 로빈-80~120",
        "80~120 사이에서 값을 하나 뽑아 그만큼 생성한 뒤 계정을 바꾸고, "
        "새 값을 다시 뽑습니다. 한 토큰의 사용량을 모두 소모하면 이후에는 "
        "남은 계정에서만 생성합니다."),
    POLICY_ROUND_ROBIN_400_500: (
        "라운드 로빈-400~500",
        "400~500 사이에서 값을 하나 뽑아 그만큼 생성한 뒤 계정을 바꾸고, "
        "새 값을 다시 뽑습니다. 한 토큰의 사용량을 모두 소모하면 이후에는 "
        "남은 계정에서만 생성합니다."),
}


def policy_options(uses_usage_limit: bool = True) -> list[dict[str, str]]:
    """프런트가 라디오를 그릴 때 쓰는 목록. 문구는 사용자 명세 그대로.

    **모델 계열마다 다르다** - 위 모듈 주석 참조.
    """
    return [
        {"key": key, "label": _POLICY_TEXT[key][0], "desc": _POLICY_TEXT[key][1]}
        for key in family_policies(bool(uses_usage_limit))
    ]
