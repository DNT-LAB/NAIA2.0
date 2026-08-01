# -*- coding: utf-8 -*-
"""성인 축 도감 분류 — wildcards/nsfw/*.txt + _nsfw_catalog.json.

**이 스크립트는 이미지를 만들지 않는다.** 목록만 정리한다.

왜 생성하지 않는가
------------------
벤치 템플릿이 `1girl, young female` 이고 네거티브에 `adolescent, mature female` 을
넣어 **의도적으로 어려 보이는 인물**로 고정돼 있다. 그 베이스로 성적인 이미지를
만드는 것은 태그 빈도와 무관하게 하지 않는다.
사용자도 같은 이유로 GitHub 게시 불가라고 판단했다(2026-07-28).

**막는 것은 "어린 외형 + 성적 내용"의 조합이지 어린 외형 태그 자체가 아니다.**
`loli`·`shota`·`child` 는 체형 축에서 `rating:general` 베이스로 정상 생성된다 —
AI 이미지 생성에서 체형을 조절하는 범용 분류 태그이고, 실제 썸네일도 착의 상태다
(Vision 확인 2026-08-01). `oppai loli` 도 외모 서술이라 체형 축으로 이관됐고 성인
도감에는 없다. 연령 게이트의 정확한 적용 범위는 tools/thumb_age_guard.py 를 보라 —
런타임 가드는 배치 이름에 `nsfw` 가 있을 때만 돈다.

그래서 여기서는 **분류와 와일드카드까지만** 한다. 사용자가 직접 생성하거나,
와일드카드로만 쓰거나, 그대로 두거나 할 수 있게 목록을 정돈해 둔다.

출력 위치가 `wildcards/thumb/` 이 아니라 `wildcards/nsfw/` 인 것도 같은 이유다 —
thumb 도구들이 축으로 읽어 실수로 생성 대상에 넣는 일이 없어야 한다.
"""
import json
import re
from pathlib import Path

# 원본 목록도 이제 nsfw 폴더에 있다(생성 축 폴더 밖으로 옮겼다).
SRC = Path("wildcards/nsfw")
OUT = Path("wildcards/nsfw")

# 이 빌더가 만들지 않는 축. 한 파일에 writer 가 둘이면 반드시 갈라진다 —
# 이 프로젝트에서 fx_effect · loc_backdrop 로 이미 겪었다.
_OWNED_ELSEWHERE = {"nsfw_act", "nsfw_etc"}
# `meta_nsfw` 는 태그 DB 의 `Composition_Meta` 그룹에서 온 성인 태그다
# (`nude`·`hair censor`·`ass focus`). 앞의 넷은 NSFW 그룹만 훑어서 이것들을
# 통째로 놓치고 있었다 — 도감에도 와일드카드에도 없었다(2026-08-01).
# tools/thumb_meta_build.py 가 만든다.
SOURCES = ("body_nsfw", "cloth_nsfw", "pose_nsfw", "pose_nsfw_face", "meta_nsfw")

# 도감 분류. 위에서부터 먼저 맞는 것을 쓴다(순서가 곧 우선순위).
# 이름 규칙만으로 나눈다 — 이 목록은 눈으로 검수하지 않으므로 근거가 이름에 있어야 한다.
CATEGORIES = (
    ("nsfw_fluid",    "체액", re.compile(
        r"\bcum\b|precum|drinking own cum|cumshot|urine|feces|saliva trail")),
    ("nsfw_genital",  "성기", re.compile(
        # `cock ring`/`chastity belt` 은 구속 기구로 잡히지만 실제로는 성기 기구다 —
        # questionable 단계에 두면 등급이 어긋난다.
        r"penis|pussy|vagina|clitoris|labia|balls\b|testicl|anus|genital|frenulum"
        r"|cock ring|chastity"
        r"|\bslit\b|knot\b|sheath\b|flaccid|erection|bulge|crotch|groin")),
    ("nsfw_pubic",    "음모", re.compile(r"pubic|pubes")),
    ("nsfw_nipple",   "유두·유륜", re.compile(r"nipple|areola|montgomery")),
    ("nsfw_breast",   "가슴 노출·접촉", re.compile(
        r"breast|oppai|paizuri|cleavage|underboob|sideboob|framed breasts")),
    ("nsfw_butt",     "둔부", re.compile(r"\bass\b|\bbutt(s|ocks)?\b")),
    ("nsfw_bondage",  "구속·기구", re.compile(
        r"\bgag\b|gagged|harness|chastity|cock ring|leash|bound|shibari|rope")),
    ("nsfw_exposure", "노출 의상", re.compile(
        # `nude`/`completely nude` 는 `^naked ` 로 안 잡힌다(실측 explicit 73.1%).
        r"\bnude\b|^naked |topless|bottomless|no pants|micro |see-through|pasties|maebari"
        r"|crotchless|cupless|breastless|thong|slingshot|revealing|impossible "
        r"|bikini|swimsuit|leotard|bodysuit|bodystocking|lingerie|negligee|chemise"
        r"|babydoll|garter|latex|fishnet|showgirl|bunny|virgin killer|frontless"
        r"|one-piece thong|diaper|wet panties|panties|dress|shirt|sweater|apron"
        r"|towel|jacket|coat|kimono|cape|capelet|robe|scarf|necktie|skirt|ribbon"
        r"|bandage|sheet|hoodie|overalls|suspenders|tabard|labcoat|cloak|paint")),
    ("nsfw_act",      "행위", re.compile(
        r"spreading|grabbing|squeez|press|tweaking|sucking|slapping|shake|smack"
        r"|masturbat|fellatio|breastfeeding|covering")),
)


def main() -> int:
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731
    KR = lambda t: str((raw.get(t) or {}).get("kr") or "")      # noqa: E731

    pool: dict[str, str] = {}
    for name in SOURCES:
        f = SRC / f"{name}.txt"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            t = line.strip()
            if t:
                pool.setdefault(t, name)

    cat: dict[str, list[str]] = {}
    unmatched: list[str] = []
    for tag in pool:
        for key, _label, pat in CATEGORIES:
            if pat.search(tag):
                cat.setdefault(key, []).append(tag)
                break
        else:
            unmatched.append(tag)

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for key, label, _p in CATEGORIES:
        v = sorted(cat.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        # **소유권 검사.** `nsfw_act` · `nsfw_etc` 는 build_nsfw_act_catalog.py 가
        # 소유한다(행위 도감 640개). 이 레거시 빌더가 같은 파일을 다른 풀에서
        # 덮어쓰면 그쪽 결과가 조용히 사라진다(Codex 리뷰 2026-07-30 지적).
        if key in _OWNED_ELSEWHERE:
            print(f"  (건너뜀: {key} 는 build_nsfw_act_catalog.py 소유)")
            continue
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:16s} {label:12s} {len(v):4d}  {', '.join(v[:5])}")
    if unmatched:
        v = sorted(unmatched, key=lambda t: -F(t))
        if "nsfw_etc" not in _OWNED_ELSEWHERE:
            (OUT / "nsfw_etc.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        else:
            # **조용히 사라지면 안 된다.** nsfw_etc 를 다른 빌더가 소유하게 되면서,
            # 여기로 떨어진 태그는 화면에만 찍히고 파일에는 안 써졌다 — nude 를 포함한
            # 8개가 그렇게 없어진 것을 2026-08-01 에 발견했다. 갈 곳 없는 것은 남긴다.
            (OUT / "_nsfw_unrouted.txt").write_text(
                "# 어느 분류에도 안 맞아 갈 곳이 없는 태그. nsfw_etc 는 다른 빌더 소유라\n"
                "# 여기서 쓸 수 없다. CATEGORIES 에 규칙을 넣거나 원본에서 빼라.\n"
                + "\n".join(v) + "\n", encoding="utf-8")
            print(f"  !! 갈 곳 없음 {len(v)}개 -> {OUT / '_nsfw_unrouted.txt'}"
                  f"  ({', '.join(v[:8])})")
        total += len(v)
        if "nsfw_etc" not in _OWNED_ELSEWHERE:
            print(f"  {'nsfw_etc':16s} {'기타':12s} {len(v):4d}  {', '.join(v[:8])}")

    (OUT / "_nsfw_catalog.json").write_text(json.dumps({
        "note": [
            "성인 축 도감. 이미지를 만들지 않는다 — 목록과 와일드카드만이다.",
            "생성하지 않는 이유는 tools/build_nsfw_catalog.py 문서주석 참조.",
            "thumb 도구가 축으로 읽지 않도록 wildcards/thumb 밖에 둔다.",
        ],
        "label": {k: l for k, l, _p in CATEGORIES} | {"nsfw_etc": "기타"},
        "source_axes": list(SOURCES),
        "count": total,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n총 {total}개 / {OUT}/  (이미지 생성 없음)")
    kr = sum(1 for t in pool if KR(t))
    print(f"한글 설명 있음 {kr}/{len(pool)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
