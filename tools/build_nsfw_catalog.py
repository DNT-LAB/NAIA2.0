# -*- coding: utf-8 -*-
"""성인 축 도감 분류 — wildcards/nsfw/*.txt + _nsfw_catalog.json.

**이 스크립트는 이미지를 만들지 않는다.** 목록만 정리한다.

왜 생성하지 않는가
------------------
벤치 템플릿이 `1girl, young female` 이고 네거티브에 `adolescent, mature female` 을
넣어 **의도적으로 어려 보이는 인물**로 고정돼 있다. 그 베이스로 성적인 이미지를
만드는 것은 태그 빈도와 무관하게 하지 않는다. `body_nsfw` 에 `oppai loli` 가 들어
있다는 사실 자체가 이 위험이 가정이 아님을 보여준다.
사용자도 같은 이유로 GitHub 게시 불가라고 판단했다(2026-07-28).

그래서 여기서는 **분류와 와일드카드까지만** 한다. 사용자가 직접 생성하거나,
와일드카드로만 쓰거나, 그대로 두거나 할 수 있게 목록을 정돈해 둔다.

출력 위치가 `wildcards/thumb/` 이 아니라 `wildcards/nsfw/` 인 것도 같은 이유다 —
thumb 도구들이 축으로 읽어 실수로 생성 대상에 넣는 일이 없어야 한다.
"""
import json
import re
from pathlib import Path

SRC = Path("wildcards/thumb")
OUT = Path("wildcards/nsfw")
SOURCES = ("body_nsfw", "cloth_nsfw", "pose_nsfw", "pose_nsfw_face")

# 도감 분류. 위에서부터 먼저 맞는 것을 쓴다(순서가 곧 우선순위).
# 이름 규칙만으로 나눈다 — 이 목록은 눈으로 검수하지 않으므로 근거가 이름에 있어야 한다.
CATEGORIES = (
    ("nsfw_fluid",    "체액", re.compile(
        r"\bcum\b|precum|drinking own cum|cumshot|urine|feces|saliva trail")),
    ("nsfw_genital",  "성기", re.compile(
        r"penis|pussy|vagina|clitoris|labia|balls\b|testicl|anus|genital|frenulum"
        r"|\bslit\b|knot\b|sheath\b|flaccid|erection|bulge|crotch|groin")),
    ("nsfw_pubic",    "음모", re.compile(r"pubic|pubes")),
    ("nsfw_nipple",   "유두·유륜", re.compile(r"nipple|areola|montgomery")),
    ("nsfw_breast",   "가슴 노출·접촉", re.compile(
        r"breast|oppai|paizuri|cleavage|underboob|sideboob|framed breasts")),
    ("nsfw_butt",     "둔부", re.compile(r"\bass\b|\bbutt(s|ocks)?\b")),
    ("nsfw_bondage",  "구속·기구", re.compile(
        r"\bgag\b|gagged|harness|chastity|cock ring|leash|bound|shibari|rope")),
    ("nsfw_exposure", "노출 의상", re.compile(
        r"^naked |topless|bottomless|no pants|micro |see-through|pasties|maebari"
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
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:16s} {label:12s} {len(v):4d}  {', '.join(v[:5])}")
    if unmatched:
        v = sorted(unmatched, key=lambda t: -F(t))
        (OUT / "nsfw_etc.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
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
