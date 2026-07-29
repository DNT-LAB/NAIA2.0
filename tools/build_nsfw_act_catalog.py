# -*- coding: utf-8 -*-
"""성인 '행위' 도감 — wildcards/nsfw/nsfw_{act}.txt.

**이미지를 만들지 않는다.** 목록만 정리한다(기존 build_nsfw_catalog.py 와 같은 방침).

## 왜 이게 따로 필요한가

`SLOT_GROUPS` 는 여섯 그룹(Person_Body / Clothing_Wear / Expression_Action /
Composition_Meta / Location_Background / Food_Object)만 읽는다. **`NSFW` 그룹은
어느 슬롯에도 매핑돼 있지 않아** 분류 파이프라인이 한 번도 읽은 적이 없다.
그래서 `sex`(149,518) · `vaginal`(108,348) · `fellatio`(35,024) 같은 것이
어디에도 없었다. 기존 도감 245개는 SFW 그룹에 섞여 있던 것을 정규식으로 걸러낸
전혀 다른 경로의 결과물이다.

## 어디까지 담는가

  · `source == KR_tags` 만. NSFW 그룹 4,020개 중 760개다. 나머지 3,260개는
    e621 계열 어휘(`anthro penetrated` · `equine genitalia` · `gynomorph`)로,
    Danbooru 학습 모델이 제대로 그리지 못한다.
  · freq >= 149 (다른 축과 같은 절단선)
  · 기존 도감 245개와 겹치는 것은 뺀다 — 팩 키는 `<축>/<태그>` 하나뿐이라
    두 축에 같은 태그가 있으면 뒤쪽 축이 영영 안 찬다(실측 `bandages`).

## 무엇을 빼는가

  · 서브그룹 `taboo` / `gore` / `dark_content` (사용자 지시)
    - taboo   강간 · 아동 · 근친 · 구로 · 료나 · 자해 · vore
    - gore    유혈 · 신체 훼손
    - dark_content 자살 · 살인 · 고문 · 학대
  · 위 서브그룹을 피해 남은 것 중 이름으로 걸리는 11개
    (rape / shota / onee-shota / incest / sleep molestation / forced* / ryona / urine meter)
    서브그룹 분류가 완전하지 않아 이름 규칙이 한 겹 더 필요하다.
"""
import json
import re
from pathlib import Path

OUT = Path("wildcards/nsfw")
CUT = 149

# 서브그룹 단위 제외.
SKIP_SUBGROUP = {"taboo", "gore", "dark_content"}
# 서브그룹을 빠져나온 것 중 이름으로 거르는 것. 서브그룹 분류가 완전하지 않다.
# 뒤쪽 `\b` 때문에 접미가 붙은 형태를 놓쳤다 — `molest`+`ation`, `bestial`+`ity`.
# 앞 경계만 두고 뒤는 연다. 이 목록은 정확도보다 누락이 위험하다.
BLOCK_NAME = re.compile(
    r"\b(rape|shota|loli|child|kid|toddler|baby|teen|incest|cest"
    r"|noncon|non-con|forced|molest|unconscious|drugged|guro|ryona|vore"
    r"|scat|feces|urine|piss|torture|abuse|snuff|bestial|zoo|pokephilia"
    r"|chikan|harassment|mind control|hypnosis|hypnotiz)", re.I)

# 분류. 위에서부터 먼저 맞는 것을 쓴다(순서가 곧 우선순위).
# 이름 규칙만 쓴다 — 눈으로 검수하지 않으므로 근거가 이름에 있어야 한다.
CATEGORIES = (
    ("nsfw_censor", "검열 처리", re.compile(
        r"censor|mosaic|bar censor|convenient|steam\b|light censor|tape gag")),
    ("nsfw_group", "다인원", re.compile(
        r"group sex|threesome|foursome|orgy|gangbang|\bmmf\b|\bffm\b|\bmmm\b|\bfff\b"
        r"|double penetration|triple penetration|spitroast|multiple (boys|girls|penises)"
        r"|shared|netorare|cuckold|voyeur")),
    ("nsfw_position", "체위", re.compile(
        r"position|missionary|cowgirl|doggystyle|from behind|girl on top|straddling"
        r"|suspended|standing sex|reverse |sitting sex|lap\b|prone bone|piledriver"
        r"|leg lift|carrying sex|face-to-face")),
    ("nsfw_oral", "구강", re.compile(
        # `oral` 은 단어 경계가 필요하다 — 없으면 `pect-oral-s` · `clit-oral` 을 삼킨다
        # (`butt` 가 butterfly·button 을 삼켰던 것과 같은 실수, 두 번째다).
        r"fellatio|\boral\b|cunnilingus|irrumatio|deepthroat|licking|sucking|blowjob"
        r"|mouth|tongue|kiss|swallow|gokkun|throat")),
    ("nsfw_penetration", "삽입", re.compile(
        r"penetrat|vaginal|\banal\b|insertion|inside\b|\bin (pussy|vagina|ass|anus|mouth)"
        r"|impale|stuck|hilt|deep\b|cervix|womb")),
    ("nsfw_hand", "손·가슴·기타 부위", re.compile(
        r"handjob|paizuri|masturbat|fingering|footjob|thighjob|axillajob|hairjob"
        r"|grinding|frottage|tribadism|scissoring|rubbing|stroking|fingers? in"
        r"|grabbing|groping|squeez|fondl|pinching|tweaking")),
    ("nsfw_toy", "기구·도구", re.compile(
        r"sex toy|dildo|vibrator|anal beads|butt plug|onahole|fleshlight|toy\b"
        r"|rope|shibari|bound|bondage|restrain|handcuff|collar|leash|blindfold|spreader"
        r"|chastity|cock ring|strap-on|strapon|machine")),
    ("nsfw_cum", "사정·체액", re.compile(
        r"\bcum\b|cumdrip|cumshot|ejaculat|semen|precum|creampie|bukkake|facial"
        r"|pussy juice|vaginal fluid|saliva|drool|squirt|lactation|milk\b|sweat")),
    ("nsfw_pairing", "관계·장르", re.compile(
        r"hetero|\byuri\b|\byaoi\b|\bbara\b|futanari|newhalf|otokonoko|monster girl"
        r"|furry|interspecies|tentacle|size difference|age difference|dominant"
        r"|submissive|femdom|maledom|\bpov\b|imminent")),
    ("nsfw_anatomy", "해부·부위", re.compile(
        r"\bpenis|\bpussy|\banus\b|testicl|clitor|vulva|urethra|uterus|cervix|ovum"
        r"|perineum|foreskin|scrotum|hymen|labia|glans|smegma|sperm cell")),
    ("nsfw_peek", "엿보임·노출 사고", re.compile(
        r"pantyshot|pantylines|upskirt|upshorts|upshirt|downblouse|slip\b|peek\b"
        r"|clothing aside|cutout|nippleless|breast pocket|accidental|zenra|flashing"
        r"|public nudity|see-through")),
    ("nsfw_fetish", "페티시·상황", re.compile(
        r"inflation|expansion|enema|human toilet|exhibitionism|indecency|prostitut"
        r"|instant loss|defloration|impregnat|fertiliz|in heat|virgin|sex ed"
        r"|contest|pornography|docking|thigh sex|buttjob|pecjob")),
    ("nsfw_state", "상태·표정", re.compile(
        r"erection|flaccid|aroused|arousal|blush|ahegao|orgasm|climax|trembling"
        r"|spread|presenting|exposed|nude|naked|undress|strip|lifted|raised"
        r"|cameltoe|zettai ryouiki|clothed |partially|after ")),
)


# 정규식이 놓친 것의 행선지. 태그 DB 의 subgroup -> 분류.
SUBGROUP_TO = {
    "sex_acts": "nsfw_act", "sex_act": "nsfw_act", "sexual_activity": "nsfw_act",
    "simulated_sex_acts": "nsfw_act", "activity": "nsfw_act", "implied": "nsfw_act",
    "sexual_positions": "nsfw_position", "sex_position": "nsfw_position",
    "pose": "nsfw_position",
    "genitals": "nsfw_anatomy", "anatomy": "nsfw_anatomy", "body": "nsfw_anatomy",
    "body_modification": "nsfw_anatomy", "body_writing": "nsfw_anatomy",
    "nudity": "nsfw_peek", "exposure": "nsfw_peek", "pasties": "nsfw_peek",
    "sexual_attire": "nsfw_peek",
    "sex_objects": "nsfw_toy", "toys": "nsfw_toy", "object": "nsfw_toy",
    "fluids": "nsfw_cum",
    "groping": "nsfw_hand", "self_touch": "nsfw_hand",
    "censorship": "nsfw_censor", "symbol": "nsfw_censor",
    "expression": "nsfw_state", "state": "nsfw_state", "reaction": "nsfw_state",
    "anticipation": "nsfw_state", "meter": "nsfw_state",
    "fetish": "nsfw_fetish", "situation": "nsfw_fetish",
    "sexual_situation": "nsfw_fetish", "genre": "nsfw_fetish",
    "media": "nsfw_fetish", "meme": "nsfw_fetish",
    "pov": "nsfw_pairing", "focus": "nsfw_pairing", "visual": "nsfw_pairing",
    "insertion": "nsfw_penetration",
}
# `nsfw_act` 는 폴백 전용 키다 — 이름 규칙으로는 안 잡히는 '행위 일반'(sex 등).
_FALLBACK_LABEL = {"nsfw_act": "행위"}


def main() -> int:
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)      # noqa: E731
    SG = lambda t: str((raw.get(t) or {}).get("subgroup", "") or "")  # noqa: E731
    SRC = lambda t: str((raw.get(t) or {}).get("source", "") or "")   # noqa: E731

    # 기존 도감(245)과 겹치면 안 된다 — 팩 키가 하나뿐이라 뒤쪽 축이 영영 안 찬다.
    # **자기 출력 파일은 빼야 한다.** 두 번째 실행에서 직전 결과가 전부 `taken` 으로
    # 잡혀 풀이 0이 된다(실측). 이 프로젝트에서 다섯 번째로 겪는 함정이라 규칙으로 막는다.
    # **폴백 전용 키도 넣어야 한다.** `nsfw_act` 를 빠뜨렸더니 두 번째 실행에서
    # 그 101개가 `taken` 으로 잡혀 642 -> 541 이 됐다. 같은 함정 여섯 번째다 —
    # 목록을 손으로 적지 말고 출력 키 전체에서 파생시킨다.
    _own = {k for k, _l, _p in CATEGORIES} | set(_FALLBACK_LABEL) | {"nsfw_etc"}
    taken: set[str] = set()
    for p in OUT.glob("*.txt"):
        if p.stem.startswith("_") or p.stem in _own:
            continue
        taken |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}

    # 빠진 것도 따로 남긴다(사용자 지시) — 무엇이 왜 빠졌는지 안 보이면
    # 나중에 "이건 왜 없지" 를 다시 조사하게 된다.
    pool, blocked, tabooed, foreign = [], [], [], []
    for tag, d in raw.items():
        if str(d.get("group", "")) != "NSFW":
            continue
        if F(tag) < CUT:
            continue
        if SRC(tag) != "KR_tags":
            foreign.append(tag)          # e621 계열 어휘 — 모델이 못 그린다(정책 아님)
            continue
        if SG(tag) in SKIP_SUBGROUP:
            tabooed.append(tag)          # taboo / gore / dark_content
            continue
        if tag in taken:
            continue
        (blocked if BLOCK_NAME.search(tag) else pool).append(tag)

    cat: dict[str, list[str]] = {}
    unmatched: list[str] = []
    for tag in pool:
        for key, _label, pat in CATEGORIES:
            if pat.search(tag):
                cat.setdefault(key, []).append(tag)
                break
        else:
            # 정규식이 놓친 것은 **태그 DB 의 서브그룹**으로 떨어뜨린다.
            # 규칙을 계속 늘리는 대신 이미 분류돼 있는 것을 쓴다 — 안 그러면
            # 이름 규칙이 데이터를 못 따라가 기타만 커진다(실측 310/650).
            key = SUBGROUP_TO.get(SG(tag))
            (cat.setdefault(key, []) if key else unmatched).append(tag)

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for key, label, _p in CATEGORIES:
        v = sorted(cat.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:18s} {label:14s} {len(v):4d}  {', '.join(v[:5])}")
    for key, label in _FALLBACK_LABEL.items():
        v = sorted(cat.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:18s} {label:14s} {len(v):4d}  {', '.join(v[:5])}")
    if unmatched:
        v = sorted(unmatched, key=lambda t: -F(t))
        (OUT / "nsfw_etc.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {'nsfw_etc':18s} {'기타':14s} {len(v):4d}  {', '.join(v[:8])}")

    # ── 제외 목록 3종 ────────────────────────────────────────────────────
    # 파일명이 `_` 로 시작하므로 팩 빌더·생성기가 축으로 읽지 않는다.
    def _dump(name: str, items: list[str], head: str) -> None:
        if not items:
            return
        v = sorted(items, key=lambda t: -F(t))
        body = "\n".join(f"{t}\t{F(t)}\t{SG(t) or '-'}" for t in v)
        (OUT / name).write_text(f"# {head}\n# 태그\t빈도\t서브그룹\n{body}\n", encoding="utf-8")
        print(f"  {name:24s} {len(v):5d}  {head}")

    print("\n제외 목록:")
    _dump("_excluded_taboo.txt", tabooed,
          "서브그룹 taboo/gore/dark_content — 강간·아동·근친·구로·료나·자해·자살·고문·유혈")
    _dump("_excluded_byname.txt", blocked,
          "위 서브그룹을 빠져나왔지만 이름 규칙에 걸린 것 (서브그룹 분류가 완전하지 않다)")
    _dump("_excluded_foreign.txt", foreign,
          "e621 계열 어휘 — Danbooru 학습 모델이 못 그린다(정책 제외 아님)")

    (OUT / "_nsfw_act_catalog.json").write_text(json.dumps({
        "note": [
            "성인 행위 도감. 이미지를 만들지 않는다 — 목록뿐이다.",
            "NSFW 그룹은 SLOT_GROUPS 에 없어 분류 파이프라인이 읽은 적이 없었다.",
            "source=KR_tags 만 담는다(e621 계열은 Danbooru 모델이 못 그린다).",
            "제외분은 _excluded_*.txt 세 파일에 이유별로 남긴다.",
        ],
        "label": {k: l for k, l, _p in CATEGORIES} | _FALLBACK_LABEL | {"nsfw_etc": "기타"},
        "cut": CUT,
        "count": total,
        "excluded": {"taboo": len(tabooed), "byname": len(blocked), "foreign": len(foreign)},
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n총 {total}개 / {OUT}/  (이미지 생성 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
