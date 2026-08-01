# -*- coding: utf-8 -*-
"""남성 인물이 그려지는 태그의 **단일 출처**.

## 왜 한 파일인가

이 목록은 두 곳이 쓴다.

- `thumb_axes_build.py` — 생성 배치를 가른다. `1girl` 베이스로는 렌더되지 않아
  남성 베이스로 따로 돌려야 한다.
- `thumb_axes_emit.py` — UI 를 가른다. 여성 위주로 쓰는 사용자에게 그리드 한복판에서
  중년 남성 나체가 튀어나오면 그건 기능이 아니라 사고다. 탭 안의 별도 섹션으로 격리한다.

같은 목록을 두 군데 손으로 적어 갈라진 사고가 이 프로젝트에서 이미 다섯 번 났다
(신설 축이 통째로 스킵되고, 다인원 439개가 UI 에 도달하지 않았다). 그래서 파일로 뽑는다.

## 판정 기준은 이름이 아니라 **실제 렌더된 그림**이다

2026-07-30 팩에서 꺼내 눈으로 확인했다. 이름으로 골랐다면 절반이 틀렸다:

| 태그 | 실제 그림 | 판정 |
|---|---|---|
| `beard` · `full beard` 외 수염 13 | 중년 남성 나체 상반신 | **남성** |
| `pectorals` · `large/huge pectorals` | 남성 상반신(`pectorals` 는 남성기까지) | **남성** |
| `muscular male` `toned male` `old man` `fat man` `ugly man` `giant male` | 남성 | **남성** |
| `fake mustache` · `fake beard` | 가짜 수염을 붙인 여성(코스튬) | 여성 — 그대로 |
| `male swimwear` · `male underwear` · `male maid` | 남성 옷을 입은 여성 | 여성 — 그대로 |
| `pectoral cleavage` | V넥을 입은 여성 | 여성 — 그대로 |
| `strongman waist` | (옛 그림) 여성 하반신 -> (최신) 근육질 남성 전신 | **남성** — 아래 주석 |
| `grabbing own pectoral` | 교복 여학생 | 여성 — 그대로 |
| `miniboy` | 여성 캐릭터(생성 실패로 보인다) | 여성 — 그대로 |

즉 `male`/`man` 이 이름에 있다는 것만으로는 아무것도 알 수 없다. **`male underwear` 는
여성이 입고, `beard` 는 남성이 난다.** 새 태그를 넣을 때도 그림을 먼저 봐라.

`species_male`(`cat boy` 등 38)은 이미 축 자체가 갈려 있어 여기 없다.
"""

# 그림에서 남성 인물이 나오는 태그. 축 이름은 주석으로만 적는다 — 실제 축 배정은
# 각 축 .txt 파일이 SSOT 이고, 여기 적힌 태그가 어느 축에 있든 그 축에서 갈린다.
MALE_ONLY = {
    # body_type — 남성 체형
    "muscular male", "toned male", "old man", "fat man", "ugly man", "giant male",
    # `strongman waist` — 처음에 여성으로 판정했는데 그건 **옛 그림**을 본 것이었다.
    # 팩을 mtime 최신 우선으로 확정하자 근육질 남성 전신으로 바뀌었다. 태그 뜻(씨름꾼
    # 허리)도 남성이다. 판정 근거가 어느 시점의 그림인지까지 봐야 한다는 교훈.
    "strongman waist",
    # body_type — 흉근. 여성 가슴이 아니라 남성 상반신으로 렌더된다.
    "pectorals", "large pectorals", "huge pectorals",
    # body_type — 이름 그대로 남성이다. 그림 판정과 다르게 취급하는 두 개:
    #   `shota`  — 썸네일이 아직 없다(`loli` 의 남성 짝. 여성 쪽이 body_type 에 있어 짝을 맞춘다).
    #   `miniboy` — 지금 팩의 그림은 여성인데 그게 **생성 실패**다(여성 베이스로 돌았다).
    #              태그 뜻이 '작은 소년' 이라 남성 베이스로 다시 돌려야 맞다.
    # 둘 다 재생성하면 남성이 되므로 지금부터 격리해 둔다.
    "shota", "miniboy",
    # face — 수염. 13개 전부 중년 남성 나체 상반신으로 렌더됐다.
    # `fake mustache` / `fake beard` 는 여성 코스튬이라 **넣지 않는다**.
    "beard", "mustache", "beard stubble", "mustache stubble",
    "long beard", "long mustache", "thick beard", "thick mustache",
    "full beard", "braided beard", "chinstrap beard", "tied beard",
    "pencil mustache",
}

# 남성기가 그려져 있어 일반 축에 그냥 둘 수 없는 것. 격리만으로는 부족해 블러까지 건다.
# 재생성으로 해결되면 이 집합에서 빼라 — 블러는 임시 조치다.
MALE_EXPLICIT = {
    "pectorals",
}

# **이름은 남성인데 그림은 여성인 것.** 정규식으로 남성을 찾는 코드가 이것들을 1boy 배치로
# 보내면 잘 나온 여성 썸네일을 남성으로 갈아버린다. 위 표의 실측이 근거다.
# `male underwear` 는 여성이 입는 것이 이 태그의 용도다 — 이름을 믿으면 안 된다.
FEMALE_RENDER = {
    "male swimwear", "male underwear", "male underwear peek",
    "no male underwear", "wet male underwear",
    "male underwear pull", "male underwear aside",
    "male maid", "male playboy bunny",
    "pectoral cleavage", "grabbing own pectoral",
    # 여성이 붙이는 가짜 수염(코스튬).
    "fake mustache", "fake beard",
    # 인물이 아니라 카메라·구도·기호를 말한다.
    "male pov", "male hand", "male-female symbol",
}
assert not (MALE_ONLY & FEMALE_RENDER), "한 태그가 남성이면서 여성일 수는 없다"


def is_male_render(tag: str) -> bool | None:
    """실측이 있으면 True/False, 없으면 None(호출자가 추정해도 된다)."""
    t = (tag or "").strip().lower()
    if t in MALE_ONLY:
        return True
    if t in FEMALE_RENDER:
        return False
    return None
