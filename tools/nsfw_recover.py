# -*- coding: utf-8 -*-
"""일반 축에 섞여 배포 중인 성인 태그를 성인 도감으로 회수한다.

## 무엇이 문제였나

성인 판정을 rating 실측으로 바꾸면서 **반대 방향의 누수**가 드러났다. 일반 축에
`explicit >= 70%` 인 태그가 79개 있었고, 전부 썸네일이 만들어져 팩에 들어가
있었다 — 블러 없이 배포 중이었다.

    cum on floor(100%) · thong aside(100%) · panties aside(99.1%) ·
    glory hole(88.9%) · leotard aside(96.9%) · bikini bottom aside(98.7%)

이름 규칙으로 분류하던 시절 `pose_clothing`(옷을 당기는 자세)·`loc_indoor`(실내)
같은 축이 성인 태그를 자기 규칙으로 주워 갔다.

## 어떻게 회수하나

**목록 하나**(`_recovered_to_nsfw.txt`)를 만들고 일반 축 빌더들이 그것을 뺀다.
성인 도감은 그 목록을 소스로 읽는다. `_moved_to_sfw.txt` 와 정확히 대칭이다.

블러는 축 단위라 성인 축으로 가면 자동으로 걸린다.

## 경계에 있는 것

`leg grab`(88.2%)·`straddling`(86.5%)·`hand around waist`(85.7%) 처럼 **자세
자체는 성적이지 않은데 그런 게시물에 많이 붙은** 태그가 섞여 있다. rating 은
"Danbooru 게시물에서 어떻게 쓰였나"지 "우리 썸네일이 무엇인가"가 아니다
(`loli`/`shota` 에서 같은 함정을 겪었다). 목록에 남겨 두되 이 문단으로 표시해
둔다 — 되돌리려면 `_recovered_to_nsfw.txt` 에서 그 줄만 지우면 된다.

사용: python tools/nsfw_recover.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.nsfw_explicit_vocab import is_explicit_vocab  # noqa: E402

TH = Path("wildcards/thumb")
NS = Path("wildcards/nsfw")
PACK = Path("data/interactive_thumbnails.json")
RATING = Path("data/tag_rating.json")
OUT = NS / "_recovered_to_nsfw.txt"

# rating 이 "우리 썸네일"이 아니라 "게시물 사용례"를 재는 축. 체형·표정처럼
# `rating:general` 베이스로 찍는 축은 게시물 통계와 무관하다(loli/shota 교훈).
EXEMPT_AXES = {"body_type", "body_feature", "persona", "face", "expression"}
CUT = 70.0


def main() -> int:
    rating = json.loads(RATING.read_text(encoding="utf-8"))["tags"]
    pack = json.loads(PACK.read_text(encoding="utf-8"))

    rows = []
    for key in pack:
        axis, _, tag = key.partition("/")
        if not tag or axis.startswith("nsfw_") or axis in EXEMPT_AXES:
            continue
        r = rating.get(tag)
        if r and r["n"] >= 20 and r["e"] >= CUT:
            rows.append((r["e"], tag, axis))
    rows.sort(reverse=True)

    vocab = [t for _e, t, _a in rows if is_explicit_vocab(t)]
    plain = [t for _e, t, _a in rows if not is_explicit_vocab(t)]
    tags = sorted({t for _e, t, _a in rows})

    OUT.write_text(
        "# 일반 축에서 성인 도감으로 회수한 태그. 일반 축 빌더들이 이 목록을 뺀다.\n"
        "# tools/nsfw_recover.py 가 만든다. 되돌리려면 해당 줄을 지우고 빌더를 다시 돌려라.\n"
        f"# 판정: explicit >= {CUT:.0f}% (체형·표정 등 rating:general 베이스 축은 제외).\n"
        "# 경계: 자세 자체는 성적이지 않은데 그런 게시물에 많이 붙은 것이 섞여 있다\n"
        "#       (leg grab · straddling · hand around waist). 문단은 문서주석 참조.\n"
        + "\n".join(tags) + "\n", encoding="utf-8")

    print(f"회수 {len(tags)}개  (성인 어휘 {len(vocab)} / 그 외 {len(plain)})")
    print("  성인 어휘:", ", ".join(vocab[:8]))
    print("  그 외    :", ", ".join(plain[:8]))
    print(f"\n목록: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
