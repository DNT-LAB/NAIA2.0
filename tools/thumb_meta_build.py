# -*- coding: utf-8 -*-
"""기타·텍스트 축 빌더 — meta 그룹에서 **그림으로 구분되는 것**만 골라 축으로 세운다.

## 왜 신설하는가

`composition_fx`('기타·텍스트') 슬롯은 "썸네일이 없는 meta 태그만 담는 트리"로 만들었다.
그런데 사용자가 "의외로 다 구분이 가능하다"고 지적했다(2026-08-01). 맞다 —
`4koma`·`speech bubble`·`border`·`midriff peek`·`genderswap` 은 그림이 확실히 달라진다.
탐색기로 남겨 둘 이유가 없다.

## 다만 전부는 아니다

대상은 933개(freq>=300 이면 390개)인데, 그 안에는 그림으로 구분이 **안 되는** 것이
섞여 있다. 골라내지 않고 통째로 돌리면 팩에 쓰레기가 들어간다:

    weibo username · pixiv id · rhodes island logo · takeuchi takashi (style)
        -> 고유명·계정·화풍. 그려도 서로 구분이 안 된다.
    bad anatomy · manly · hot · pun · truth · yes · death
        -> 주관·품질 판정. 그림이 아니다.
           (`yandere` 는 여기 넣지 마라 — `persona` 축이 이미 그림을 가지고 있다.
            `taken` 에서 먼저 걸러지므로 제외 목록에도 안 나온다.)
    alternate costume · official alternate hairstyle · costume switch
        -> **관계형 메타**. "원작과 다르다"는 뜻이라 그 자체로는 그릴 것이 없다.
           성인 축에서 `_relational_meta.txt` 로 겪은 것과 같은 유형이다.
    nude · completely nude · hair censor · text censor
        -> 성인. **`_meta_adult.txt` 로 따로 뺀다.** 나머지 제외 태그와 취급이 다르다 —
           저것들은 "안 그린다"이고 이쪽은 "도감 분류와 와일드카드는 만들되 그림은
           만들지 않는다"이다(사용자 정책). 한 파일에 섞으면 그 구분이 사라진다.
    bad feet · bad leg · bad perspective · deformed
        -> 결함 태그. 네거티브에 이미 들어 있어 찍히지도 않는다.

그래서 **축별로 목록을 직접 고른다.** 규칙으로는 `weibo username`(계정)과
`body writing`(그림)을 가를 수 없다. 고른 근거는 각 축 주석에 남기고, 버린 것은
`_meta_dropped.txt` 에 전부 적어 나중에 뒤집을 수 있게 한다.

## 다른 축과 겹치면 안 된다

팩 키가 `<축>/<태그>` 하나뿐이라 두 축에 같은 태그가 있으면 뒤쪽이 영영 안 찬다.
`fx_symbol` 이 이미 말풍선 19개를, `fx_light` 가 조명 10개를 가져갔다(실측).
`wildcards/thumb` + `wildcards/nsfw` 의 모든 .txt 를 읽어 겹치는 것은 뺀다.

사용: python tools/thumb_meta_build.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.kr_tag_loader import load_kr_tag_records  # noqa: E402

OUT = Path("wildcards/thumb")
CUT = 300
GROUP = "Composition_Meta"

# 성인 — 그림을 만들지 않는다(사용자 정책).
#
# **이름으로 추정하지 않는다.** 전에는 서브그룹(`clothing_state`/`censoring`)과 이름
# 규칙으로 갈랐는데, 그러면 `hip focus`(sensitive 64.5%)·`pectoral focus`(63.6%)·
# `breast focus`(49.6%)처럼 실제로는 `bikini`(sensitive 73.2%)와 같은 구간인 태그가
# 성인으로 잡힌다. 사용자 지적: **"모든 기준은 Danbooru를 중심으로 해야 한다"**
# (2026-08-01). Danbooru 판정이 게시물마다 붙어 있으니 그걸 쓴다.
#
# 기준은 `explicit >= 70%` (사용자 확정 2026-08-01, `nude` 73.1% 를 기준점으로).
# 이 값이면 `nude`·`completely nude` 만 성인이고 `topless`(32.2%)·`bottomless`(68.5%)·
# 검열 3종·`ass focus`(39.1%)는 일반 축으로 간다.
# rating 표본에 없어 실측으로 판정할 수 없는데 성인인 것. 근거를 반드시 적는다 —
# 이런 예외가 늘면 실측 게이트가 무의미해진다.
#   from front position  설명이 "정면 삽입 체위". 서브그룹만 구도로 잡혀 있다.
ADULT_FORCE = {"from front position"}

RATING = Path("data/tag_rating.json")
ADULT_EXPLICIT_PCT = 70.0
RATING_MIN_N = 20   # 표본이 적으면 비율이 튄다(`pectoral focus` 는 22건뿐)
# NSFW 원본 목록. 성인 도감 빌더(tools/build_nsfw_catalog.py)가 SOURCES 로 읽는다.
NSFW_SRC = Path("wildcards/nsfw/meta_nsfw.txt")

# 축 라벨 + 프레이밍. 프레이밍 키는 `_manifest.json` 의 `framing_base` 와 같은 것을 쓴다.
LABEL = {
    "meta_text": "글자·컷",
    "meta_frame": "액자·판형",
    "meta_peek": "살짝 보임·부분",
    "meta_screen": "화면·연출",
}
FRAMING = {
    # 글자와 액자는 화면 전체가 대상이라 인물을 조여 잡으면 안 보인다.
    "meta_text": "free",
    "meta_frame": "free",
    # '살짝 보임'은 겨드랑이·배꼽·발처럼 부위가 대상이라 상반신으로 잡는다.
    "meta_peek": "upper",
    "meta_screen": "free",
}

# ── 축별 목록 (직접 고른 것) ────────────────────────────────────────────────
# 규칙으로 못 가른다. 고른 기준은 "이 태그만 바꿔 두 장을 찍었을 때 눈으로 달라지는가".
PICK = {
    # 글자가 화면에 실제로 그려지는 것 + 컷 나눔. 언어별 텍스트는 글자 모양이 달라
    # 서로 구분된다. `thank you`·`profanity`·`math` 같은 '내용' 태그는 뺐다.
    "meta_text": [
        "4koma", "2koma", "3koma", "1koma", "5koma", "multiple 4koma", "segmented comic",
        "vertical comic", "silent comic", "right-to-left comic", "left-to-right manga",
        "dialogue box", "chat log", "text messaging", "narration",
        "subtitled", "text background", "text-only page", "colored text", "title",
        "artist name", "signature", "alpha signature", "watermark", "dated",
        "character name", "copyright name", "copyright notice", "company name",
        "twitter username", "patreon username", "facebook username", "web address",
        "hashtag", "page number", "episode number", "character profile", "stats",
        "body writing", "graffiti", "license plate", "price tag", "wanted", "keep out",
        "kanji", "furigana", "romaji text", "runes", "hieroglyphics", "cursive",
        "russian text", "german text", "french text", "italian text", "spanish text",
        "simplified chinese text", "traditional chinese text", "mixed-language text",
        "bilingual", "cyrillic", "lyrics", "song name", "circle name", "squiggle",
        "+++", "!!", "??", "acronym", "number pun",
    ],
    # 그림을 둘러싸거나 판형을 바꾸는 것. 색 테두리는 서로 색으로 구분된다.
    "meta_frame": [
        "border", "white border", "black border", "grey border", "pink border",
        "blue border", "red border", "yellow border", "green border", "purple border",
        "orange border", "brown border", "outside border", "picture frame",
        "comic", "comic cover", "cover", "cover page", "cover image", "doujin cover",
        "manga cover", "magazine cover", "fake magazine cover", "fake cover",
        "novel cover", "album cover", "movie poster", "poster (object)", "poster (medium)",
        "box art", "reference sheet", "reference inset", "color guide", "expressions",
        "height chart", "chart", "before and after", "variations", "minimap",
        "dual persona", "multiple persona", "circle cut", "oekaki",
    ],
    # 몸의 일부만 보이거나, 화면 밖으로 잘려 나간 것. 프레이밍이 곧 그림이다.
    "meta_peek": [
        "midriff peek", "armpit peek", "armpit hair peek", "back focus", "armpit focus",
        "navel focus", "head only", "feet only", "cropped arms",
        "disembodied limb", "disembodied head", "snow on head",
        # 얼굴 표식(forehead mark 등)과 extra arms/faces 는 face·body_nonhuman 축이
        # 이미 가지고 있다. 여기 적으면 빌더가 중복으로 막는다.
    ],
    # 화면 자체를 다르게 연출하는 것. 인물이 아니라 '어떻게 보여주는가'가 바뀐다.
    "meta_screen": [
        "user interface", "heads-up display", "holographic interface",
        "gameplay mechanics", "fake screenshot", "fake phone screenshot",
        "cellphone photo", "fake video", "flashback", "fourth wall", "abstract",
        "genderswap", "genderswap (mtf)", "genderswap (ftm)", "genderswap (otf)",
        "aged down", "aged up", "age regression", "size difference",
        "humanization", "crossover", "multiple crossover", "real life insert",
        "unconventional media", "nihonga", "color trace", "personality switch",
        "body switch", "when you see it", "too many",
    ],
}


def main() -> int:
    raw = load_kr_tag_records().raw
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)  # noqa: E731

    # 다른 축(성인 포함)이 이미 가진 태그. 자기 출력은 빼야 두 번째 실행에서 축이 0이 되지 않는다.
    # **자기 출력을 빼야 한다.** 두 번째 실행에서 직전 결과가 전부 `taken` 으로 잡혀
    # 축이 비어 버린다 — 이 리포에서 여러 번 겪은 함정이다. 축 .txt 뿐 아니라
    # NSFW 원본(`meta_nsfw.txt`)도 이 빌더가 쓰므로 같이 뺀다(실측: 안 빼면 nude 가 사라진다).
    # **자기 출력을 빼야 한다.** 그리고 `meta_nsfw` 는 성인 도감의 *소스*라,
    # 도감 출력(nsfw_*.txt)까지 taken 으로 보면 순환이 생긴다 — 소스에서 빼면
    # 출력이 사라지고, 출력이 사라지면 다시 소스에 넣어야 한다. 실측으로
    # `nude`(269,994)·`completely nude`(109,029)가 이 순환에서 통째로 증발했다.
    _catalog_out = {p.stem for p in Path("wildcards/nsfw").glob("nsfw_*.txt")}
    own = set(LABEL) | {NSFW_SRC.stem} | _catalog_out
    taken: dict[str, str] = {}
    for p in list(OUT.glob("*.txt")) + list(Path("wildcards/nsfw").glob("*.txt")):
        if p.stem.startswith("_") or p.stem in own:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                taken.setdefault(line.strip(), p.stem)

    pool = {t for t, d in raw.items()
            if str(d.get("group") or "") == GROUP and F(t) >= CUT}

    axes: dict[str, list[str]] = {}
    picked: set[str] = set()
    problems: list[str] = []
    for key, tags in PICK.items():
        keep = []
        for t in tags:
            if t not in raw:
                problems.append(f"{key}: 태그 DB 에 없다 -> {t!r}")
                continue
            if F(t) < CUT:
                problems.append(f"{key}: freq<{CUT} -> {t!r} ({F(t)})")
                continue
            if t in taken:
                problems.append(f"{key}: {taken[t]} 축이 이미 가짐 -> {t!r}")
                continue
            if t in picked:
                problems.append(f"{key}: 이 파일 안에서 중복 -> {t!r}")
                continue
            picked.add(t)
            keep.append(t)
        keep.sort(key=lambda x: -F(x))
        axes[key] = keep

    if problems:
        # 조용히 넘기면 목록이 갈라진다. 고치기 전에는 쓰지 않는다.
        print("!! 목록 문제 %d건" % len(problems))
        for line in problems[:40]:
            print("   " + line)
        return 1

    for key, tags in axes.items():
        (OUT / f"{key}.txt").write_text("\n".join(tags) + "\n", encoding="utf-8")
        print(f"  {key:12s} {LABEL[key]:12s} {len(tags):4d}개")

    (OUT / "_meta_axes.json").write_text(json.dumps({
        "note": ["기타·텍스트 축. tools/thumb_meta_build.py 가 만든다.",
                 "meta 그룹에서 '그림으로 구분되는 것'만 직접 골랐다 —",
                 "고유명/계정/화풍/주관판정/관계형메타/성인/결함 태그는 뺐다(_meta_dropped.txt)."],
        "label": LABEL, "framing": FRAMING,
    }, ensure_ascii=False), encoding="utf-8")

    rest = pool - picked - set(taken)
    if not RATING.exists():
        raise SystemExit(f"{RATING} 가 없다. tools/build_tag_rating.py 를 먼저 돌려라 "
                         f"— 성인 판정은 실측 rating 으로만 한다.")
    rating = json.loads(RATING.read_text(encoding="utf-8"))["tags"]

    def is_adult(tag: str) -> bool:
        if tag in ADULT_FORCE:
            return True
        r = rating.get(tag)
        if not r or r["n"] < RATING_MIN_N:
            return False        # 근거가 없으면 성인으로 몰지 않는다(과잉 분류가 이번 문제였다)
        return r["e"] >= ADULT_EXPLICIT_PCT

    adult = sorted((t for t in rest if is_adult(t)), key=lambda x: -F(x))
    dropped = sorted((t for t in rest if not is_adult(t)), key=lambda x: -F(x))
    # 판정 근거가 없는 것은 조용히 넘어가면 안 된다 — 표본 밖이라 '아니다'가 아니라 '모른다'다.
    unrated = [t for t in rest if t not in rating]
    if unrated:
        print(f"  (rating 표본에 없어 성인 판정을 못 한 태그 {len(unrated)}개"
              f" — 예: {', '.join(sorted(unrated, key=lambda x: -F(x))[:5])})")

    (OUT / "_meta_dropped.txt").write_text(
        "# freq>=%d 인 meta 태그 중 축에 넣지 않은 것. 되살리려면 PICK 에 옮겨 적는다.\n" % CUT
        + "# 성인은 여기 없다 -> _meta_adult.txt\n"
        + "\n".join(f"{t}\t{F(t)}" for t in dropped) + "\n", encoding="utf-8")
    (OUT / "_meta_adult.txt").write_text(
        "# 성인 meta 태그. **그림을 만들지 않는다**(사용자 정책) — 도감 분류와\n"
        "# 와일드카드까지만이다. 축에 넣지 말 것.\n"
        f"# 판정: Danbooru rating 실측 explicit >= {ADULT_EXPLICIT_PCT:.0f}% "
        f"(data/tag_rating.json). 이름으로 추정하지 않는다.\n"
        "# 열: 태그 / 빈도 / explicit%\n"
        + "\n".join(f"{t}\t{F(t)}\t{rating[t]['e']}" for t in adult) + "\n", encoding="utf-8")
    # 성인 도감이 읽을 원본 목록(빈도순 평문). 여기 것은 `taken` 을 이미 통과했으므로
    # 다른 NSFW 원본과 겹치지 않는다 — 한 태그에 writer 가 둘이면 반드시 갈라진다.
    NSFW_SRC.parent.mkdir(parents=True, exist_ok=True)
    NSFW_SRC.write_text("\n".join(adult) + "\n", encoding="utf-8")
    print(f"\n채택 {len(picked)} / 다른 축 보유 {len(pool & set(taken))}"
          f" / 제외 {len(dropped)} / 성인 {len(adult)}(그림 안 만듦)")
    print(f"  제외 목록: {OUT / '_meta_dropped.txt'}")
    print(f"  성인 목록: {OUT / '_meta_adult.txt'}  (도감 원본: {NSFW_SRC})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
