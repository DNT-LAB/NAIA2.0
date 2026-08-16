# -*- coding: utf-8 -*-
"""조합 추천에서 걷어낼 잡음 어휘.

## 색상·무늬

`black dress` 를 권하는 것은 정보가 아니다. 사용자가 `maid` 를 골랐을 때 알고
싶은 것은 **`dress` 가 따라온다**는 사실이지 그것이 검은색이라는 사실이 아니다.
색은 사용자가 정하는 것이고, 코퍼스에서 어떤 색이 흔한지는 취향의 통계일 뿐
조합의 근거가 아니다(사용자 지적 2026-08-14).

실측(2026-08-14, 8개 seed x 5줄 x 3태그 = 120칩):

    전체 칩의 21.7% 가 색상 포함
    `blue eyes` seed 는 13/15 (blue hair, blue nails, blue vest, ...)
    `garter belt+underwear` 는 9/15 (black panties, black bra, ...)

어휘 SSOT 는 `data/color.txt` 다. 다만 그 파일은 런타임 설치 자산이라
(`core/runtime_install_manager.py`) 배포판에서 없을 수 있다 - 조합 추천이 그
파일의 존재에 매달리면 안 되므로 **여기 복사해 둔다.** 원본이 바뀌면
`tools/check_tag_combo_colors.py` 가 어긋남을 잡는다.

**seed 에는 적용하지 않는다.** 사용자가 직접 넣은 `blue eyes` 는 지워지면 안 된다.
거르는 것은 **후보**뿐이다.
"""

from __future__ import annotations

import re

# data/color.txt 사본. 순수 색 + 무늬/프린트까지 - 둘 다 "표면의 선택"이라
# 조합의 근거가 못 된다는 점에서 같다.
COLOR_WORDS: frozenset[str] = frozenset({
    "grey", "beige", "aqua", "white", "brown", "blonde", "red", "pink",
    "orange", "yellow", "gold", "green", "blue", "purple", "black",
    "rainbow", "streaked", "gradient", "multicolored", "plaid",
    "strawberry", "argyle", "camouflage", "print", "striped", "checkered",
    "dark", "silver",
})

# 띄어쓰기/하이픈이 들어가 토큰 분해로는 안 잡히는 것들. 긴 것부터 본다.
COLOR_PHRASES: tuple[str, ...] = (
    "diagonal-striped", "vertical-striped", "colored inner", "split-color",
    "american flag", "light green", "polka dot", "sky blue", "two-tone",
)

# 색처럼 보이지만 색이 아닌 것 - 여기 있으면 통과시킨다.
#
# `dark` 가 특히 위험하다. `dark skin` 은 색 선택이 아니라 인물 특징이고,
# `darkness`/`dark persona` 는 분위기다. 토큰이 같다고 같이 버리면 의미 있는
# 후보가 사라진다.
NOT_COLOR: frozenset[str] = frozenset({
    "dark skin", "dark-skinned female", "dark-skinned male", "darkness",
    "dark persona", "dark aura", "dark background", "in the dark",
    "gold trim",          # 장식 디테일이지 색 지정이 아니다
})

_SPLIT = re.compile(r"[\s_\-]+")

# ---------------------------------------------------------------- 프레이밍/메타
#
# `full body` 는 그림을 **어떻게 잘랐나**지 무엇이 들었나가 아니다. 색과 같은
# 성격 - 사용자가 정하는 표현 방식이지 조합의 근거가 못 된다.
#
# 실측(2026-08-15, 자세 축 심층):
#     자세 앵커 칩 3,185개 중 프레이밍 4.1% · 아티팩트 0.3%
#     의상 앵커 칩 3,811개 중 프레이밍 1.9% · 아티팩트 0.1%   <- 자세가 2배
#     자세 앵커 518 중 1위 행이 오염된 것 49 (9.5%)
#     `full body` 는 전 어휘 후보 빈도 6위(24,728칩 중 322)
#
#     watson cross -> full body, standing   54.6%
#     standing     -> full body, transparent background / full body, tachi-e
#
# ⚠️ **축 접두사로 거르면 안 된다.** 처음엔 `("view_", "meta_")` 를 통째로 뺐는데,
# 축 이름은 필터 의미가 아니었다(Codex 게이트, 실측 확인):
#
#     meta_peek   -> upskirt · downblouse · pantyshot · navel focus · armpit focus
#     meta_screen -> genderswap · aged up · aged down · size difference · body switch
#     view_angle  -> from behind (looking back -> ass, from behind 43.4%)
#     view_layout -> multiple views (turnaround -> multiple views, reference sheet 82.7%)
#
# 앞의 둘은 **내용**이다. 그걸 빼면 "강한 nsfw/taboo 조합도 사용자 의도이며
# 프로그램이 제한할 근거가 없다" 는 이 기능의 제약을 정면으로 어긴다.
# 뒤의 둘은 자세·판 구성의 정당한 동반이라, 빼면 43.4% -> 18.7% 로 나빠진다.
#
# 그래서 **크롭만** 명시적으로 적는다. `view_shot` 축의 부분집합이고, 축과
# 어긋나면 `tools/check_tag_combo_framing.py` 가 잡는다.
CROP_TAGS: frozenset[str] = frozenset({
    "full body", "upper body", "lower body", "cowboy shot", "close-up",
    "portrait", "bust", "wide shot", "cropped legs", "cropped torso",
    "cropped arms", "cropped shoulders", "cropped head",
    "feet out of frame", "foot out of frame", "head out of frame",
    "out of frame", "letterboxed", "cropped",
})

# 축 어디에도 없는 코퍼스 아티팩트. 사용자가 UI 에서 고를 수 없는데 추천에는
# 뜬다 - 게임 스프라이트 추출물이나 업로더 관행에서 나온 것들이다.
# ⚠️ `character sheet` · `reference sheet` · `turnaround` 는 여기 있으면 안 된다.
# 처음엔 넣었는데, 그건 업로드 관행이 아니라 **의도적인 출력 형식**이다 -
# `turnaround -> multiple views, reference sheet` 가 82.7% 다(Codex 실측).
ARTIFACT_TAGS: frozenset[str] = frozenset({
    # 게임 스프라이트/공식 소재 추출물. 그림 내용과 무관하다.
    "transparent background", "tachi-e", "official art", "game cg", "sprite",
    # 업로더/사이트 관행.
    "third-party edit", "third-party watermark", "sample watermark", "scan",
    "page number", "content rating", "lowres", "highres", "absurdres",
    "bad id", "bad pixiv id", "translation request", "commentary request",
    "check translation", "paid reward available",
})


def color_hit(tag: str) -> str:
    """색/무늬 어휘를 찾으면 그 단어를, 아니면 빈 문자열을 돌려준다."""
    t = str(tag).strip().lower().replace("_", " ")
    if t in NOT_COLOR:
        return ""
    for p in COLOR_PHRASES:
        if p in t:
            return p
    for w in _SPLIT.split(t):
        if w in COLOR_WORDS:
            return w
    return ""


def is_color_tag(tag: str) -> bool:
    return bool(color_hit(tag))


_AXIS_CACHE: dict[str, set[str]] | None = None


def _axis_of(root=None) -> dict[str, set[str]]:
    """태그 -> 축 집합. 한 번만 읽는다."""
    global _AXIS_CACHE
    if _AXIS_CACHE is None:
        import json
        from pathlib import Path
        p = (Path(root) if root else Path(__file__).resolve().parents[2])
        p = p / "data" / "interactive_axis_tags.json"
        out: dict[str, set[str]] = {}
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            for axis, tags in (d.get("axes") or {}).items():
                for t in tags:
                    out.setdefault(str(t).strip().lower(), set()).add(axis)
        except (OSError, ValueError):
            pass       # 축 파일이 없어도 기능은 돌아야 한다 - 필터만 꺼진다
        _AXIS_CACHE = out
    return _AXIS_CACHE


def is_framing_tag(tag: str, root=None) -> bool:
    """**크롭·아티팩트**인가. 후보에만 쓴다 - seed 와 앵커는 건드리지 않는다.

    `full body` 를 권하는 것은 "이 자세는 전신샷으로 많이 찍힌다" 는 말이라
    통계로는 참이지만, 4행짜리 화면에서 내용 조합을 밀어낼 값어치는 없다.
    사용자는 자세를 고르지 크롭을 고르는 것이 아니다.

    ⚠️ 색과 달리 **앵커 목록에서는 빼지 않는다.** 색은 앵커에서도 빼서
    `blue eyes` 단독 조회가 기권하는데, `full body` 를 seed 로 골랐을 때는
    답이 있어야 한다(Codex 지적). 여기 걸린다고 앵커 자격이 사라지지 않는다.
    """
    t = str(tag).strip().lower().replace("_", " ")
    return t in CROP_TAGS or t in ARTIFACT_TAGS
