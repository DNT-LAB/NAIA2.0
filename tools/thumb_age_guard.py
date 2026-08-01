# -*- coding: utf-8 -*-
"""연령 안전 게이트의 **단일 출처**.

## 왜 따로 두는가

같은 목록이 세 곳에 손으로 복사돼 있었고, 셋 다 같은 구멍이 있었다(Codex 리뷰
2026-07-30 지적):

  · `tools/thumb_bench.py`        요청 직전 런타임 가드
  · `tools/thumb_bench_init.py`   `_bench.json` 빌드 시 assert
  · `tools/nsfw_event_anchor.py`  자동 추출한 subtag 후보 차단

구멍은 **부분 문자열 목록**이었다는 점이다. `("young female", "young male",
"adolescent", "loli", "shota", "toddlercon", "diaper")` 는 `child` · `baby` ·
`teenage` · `muscular child` · 맨 `young` 을 통과시켰다(실측). 이 프로젝트에서
"목록을 두 군데 적으면 갈라진다"를 여러 번 겪었는데, 여기서는 갈라지지도 않고
**셋이 똑같이 틀렸다** — 목록 자체가 좁았기 때문이다.

그래서 목록이 아니라 **단어 경계 정규식** 하나로 바꾸고, 세 곳이 이것을 import 한다.

## 무엇을 막는가

어린 외형을 가리키는 어휘 전부. 사용자 요구는 "어린 외형의 nsfw 이미지가 GitHub 로
배포되는 것"을 막는 것이고(한국 법), 그 마지막 방어선이 요청 직전이다.

`diaper` 도 넣는다 — 성인 기저귀 취향이 따로 있으나 성적 맥락에서는 유아화로 읽힌다.

**SFW 축은 영향받지 않는다.** 런타임 가드는 배치 이름에 `nsfw` 가 있을 때만 돈다.
체형 축의 `loli` · `child` · `muscular child` 는 `rating:general` 베이스로 계속 생성된다
(사용자와 협의된 배치 — 신체 조절용 범용 태그이고 Vision 으로 확인했다).
"""
import re

# 앞뒤 단어 경계를 둔다. 접미가 붙은 형태를 잡으려면 뒤 경계를 열어야 하는 것도 있어
# (`adolescen` + `t/ce`, `teen` + `age/ager`) 그런 것은 어간만 적는다.
DANGER_AGE_RE = re.compile(
    r"\b("
    r"loli|lolicon|lolidom"
    r"|shota|shotacon|onee-shota|onii-shota"
    r"|toddler|toddlercon"
    r"|child|children|childlike"
    r"|baby|infant|newborn"
    r"|\bkid\b|kindergarten|preschool"
    r"|teen|teens|teenage|teenager|preteen"
    r"|adolescen"          # adolescent / adolescence
    # 맨 `young` 도 막는다. Danbooru 에 단독 `young` 태그는 없지만, 성인 프롬프트에
    # 그 토큰이 들어갈 이유가 없고 Codex 리뷰가 이 구멍을 지적했다.
    r"|young"
    r"|underage|minor-aged|jailbait"
    r"|diaper"
    r")",
    re.I,
)

# 사람이 읽는 목록(오류 메시지·문서용). 판정은 정규식이 한다 — 여기 적힌 것만
# 막는다고 오해하지 않도록 이름을 분리한다.
DANGER_AGE_EXAMPLES = (
    "loli", "shota", "child", "baby", "teenage", "adolescent",
    "young female", "young male", "toddlercon", "diaper",
)


def danger_age_hits(text: str) -> list[str]:
    """`text` 안에서 걸린 어린 외형 어휘를 돌려준다(없으면 빈 리스트)."""
    return sorted({m.group(0).lower() for m in DANGER_AGE_RE.finditer(text or "")})
