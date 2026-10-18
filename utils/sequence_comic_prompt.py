"""Sequence 만화 한 장 프롬프트(사용자 2026-10-17 - Sequence 리메이크).

이야기(이벤트 그룹)의 컷들을 **한 장** 에 장면 칸으로 그린다(해상도는 사용자 설정 - 10-17 해제) - 인페인트 연쇄 없이 t2i 한 번.
시험 기록 = docs/REFERENCE_COMIC_DESIGN_2026_10_17.md · docs/comic_panel_lab_20261017/run_story_one_image.py

    <PE prefix>                                 (맨 앞의 `{n}koma, {n} panel comic, sequential` 은 회수 - 사용자 2026-10-17)
    character clothing: <scene 1 의 옷>,        <- 본문(build_comic_body)
    scene 1: (layout:top panel), sequential, <태그>, rating:x,
    scene 2: (layout:bottom panel), sequential, <직전 장면에서 바뀐 태그만>, rating:y,
    ...
    <PE postfix>

규칙
- 장면 태그에서 캐릭터 특징(data/characteristic_list.txt) · 메타 태그(data/taglist/meta_tags.json)를 뺀다.
  인물은 캐릭터 프롬프트가 정한다(이 기능은 캐릭터 프롬프트를 전제로 한다 - 사용자).
- 직전 장면에서 바뀐 태그가 하나도 없는 컷만 건너뛴다 · 최대 MAX_SCENES 장면.
- 의상: scene 1 의 의상 사전(data/clothes_list.txt) 태그를 `character clothing:` 한 줄로 올리고 scene 1 에서 뺀다.
  이후 장면은 그 의상과 겹치는 것만 뺀다(새 옷은 남는다). 노출 · 상태 태그(nude, open clothes …)는 장면에 남긴다.
- scene 2 부터는 직전 장면에서 **바뀐 태그만** 싣는다(공통 태그를 되풀이하면 장면이 평균으로 뭉개졌다).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

# 5 · 6장면은 모델이 받는지 검증되지 않았다(사용자 2026-10-17) - 앞 4장면까지만.
MAX_SCENES = 4
# 장면 수별 고정 사양(사용자 2026-10-17). koma = `2::{koma} ::` 를 인원 태그 앞에 · 해상도는 이 크기로 고정.
# 3장면은 768x1344(사용자 2026-10-18 - 832x1216 에서 바꿈 · 1,032,192px 라 1MP 안).
# 4장면은 1088x960(사용자 2026-10-18 - 1024x1024 정사각에서는 특히 Q 에서 칸이 6 · 8개로 쪼개졌다 · 1,044,480px 라 1MP 안).
# large = 패널 [라지 (유료)] 의 크기(사용자 2026-10-18) - 셋 다 1MP 를 넘어 Anlas 를 쓴다.
COMIC_SPECS: dict[int, dict[str, Any]] = {
    4: {"size": (1088, 960), "large": (1280, 1280), "koma": "4koma"},
    3: {"size": (768, 1344), "large": (1024, 1792), "koma": "3koma"},
    2: {"size": (896, 1152), "large": (1152, 1472), "koma": "2koma"},
}
# 인원 태그(1girl · 2girls · 1boy · 6+boys · 1other …). koma 는 이 중 **맨 앞 것** 앞에 간다 - 예전엔 첫 `1girl` 앞만 찾아
# `1boy, 1girl` 이면 `1boy, 2::2koma ::, 1girl` 로 둘 사이에 끼었다(사용자 제보 2026-10-18).
# 가중치가 붙은 것(`0.8::1girl ::` · `-0.8::` · `.8::`)은 가중치째 그 앞에 넣는다 - 부호 · 소수점 가운데서 다시 맞추면
# `-2::2koma ::, 0.8::1girl` 처럼 부호가 koma 로 넘어갔다(Codex 리뷰). `artist:2girls` 처럼 `:` 뒤에 붙은 글자는 인원 태그가 아니다.
_PERSON_TAG = r"(?<![\w:+.\-])(?:-?(?:\d+(?:\.\d*)?|\.\d+)::\s*)?\d+\+?(?:girl|boy|other)s?(?![\w])"
# 장면마다 칸의 자리(사용자 2026-10-18): `scene k: (layout:<자리>), sequential, …`. 장면 수(합친 뒤의 수)로 고른다.
# 3장면 가운데 = `middle tier`(사용자 지정) · 4장면 = 2x2(왼쪽 위부터 Z 차례). 표에 없는 수(1)는 자리를 안 붙인다.
SCENE_LAYOUTS: dict[int, tuple[str, ...]] = {
    2: ("top panel", "bottom panel"),
    3: ("top panel", "middle tier", "bottom panel"),
    4: ("top-left panel", "top-right panel", "bottom-left panel", "bottom-right panel"),
}
COMIC_SENTENCE = ("A {n}-panel comic strip separated by thick, bold black borders. The panels are arranged "
                  "sequentially from {order} to show a continuous progression of events with the same, "
                  "sequential, silent comic")
# 고정 문장의 칸 차례. 4장면은 2x2 라 위 줄 왼쪽 -> 오른쪽, 아래 줄 왼쪽 -> 오른쪽(사용자 2026-10-18 · SCENE_LAYOUTS 와 같은 차례).
COMIC_ORDER_DEFAULT = "top to bottom"
COMIC_ORDER: dict[int, str] = {
    4: "top-left to top-right, and bottom-left to bottom-right",
}
RATING_TAGS = {
    "g": "rating:general",
    "s": "rating:sensitive",
    "q": "rating:questionable",
    "e": "rating:explicit",
}
# 의상 사전에 있어도 '입은 옷' 이 아닌 상태 - 의상 줄로 올리면 모든 칸에 걸린다.
CLOTHING_STATE_TAGS = frozenset({
    "nude", "completely nude", "topless", "bottomless", "undressing", "clothes lift", "skirt lift", "shirt lift",
    "panty pull", "clothing aside", "nipples", "areola slip", "nipple slip", "breasts out", "naked belt",
    "naked shirt", "open clothes", "unzipping", "clothes pull", "cleavage", "underboob", "sideboob", "no bra",
    "no panties", "covered nipples", "wet clothes", "torn clothes", "see-through", "partially undressed",
    # 장면마다 바뀌는 입은 모양 · 보이는 방식(2026-10-17 의상 줄 정리)
    "off shoulder", "open shirt", "open jacket", "open coat", "open kimono", "no shoes", "no pants",
    "underwear only", "upskirt", "bikini top only", "bikini bottom only", "pantyshot", "towel", "naked towel",
})
# 의상 사전에 있지만 **입은 옷이 아닌** 것(사용자 2026-10-17 "의상 줄 정리"): 살 · 몸 · 화장, 옷 이름 없이 꾸밈 · 맞음새만
# 말하는 것, 메타. 의상 줄로 올리지 않고 장면에 남긴다. story_v1 의 의상 줄 빈도 상위 220개에서 골랐다
# (예: bare shoulders 2,681 · midriff 671 · frills 678 · skindentation 574 · alternate costume 576).
# 장신구(hairclip · earrings · glasses …)는 인물의 모습이라 의상 줄에 둔다.
CLOTHING_DESCRIPTOR_TAGS = frozenset({
    # 살 · 몸 · 화장
    "midriff", "covered navel", "skindentation", "zettai ryouiki", "tanlines", "tan", "nail polish",
    "fingernails", "toenails", "toenail polish", "black nails", "pink nails", "red nails", "blue nails", "lipstick",
    "makeup", "piercing", "navel piercing", "ear piercing", "cameltoe", "thigh gap",
    # 옷 이름 없는 꾸밈 · 맞음새 · 무늬
    "frills", "lace", "lace trim", "fur trim", "buttons", "o-ring", "shiny clothes", "skin tight", "tight clothes",
    "taut clothes", "impossible clothes", "revealing clothes", "clothing cutout", "cleavage cutout", "side slit",
    "striped clothes", "plaid clothes", "animal print", "floral print", "polka dot", "print", "see-through clothes",
    "sleeveless", "strapless", "highleg", "backless outfit", "multicolored clothes", "two-tone clothes",
    # 메타
    "alternate costume", "official alternate costume", "cosplay", "costume", "uniform", "casual",
})


def _not_worn(key: str) -> bool:
    """의상 줄로 올리지 않을 태그 - 상태 · 묘사 · `bare …`(bare shoulders/legs …) · `open …`(open shirt/dress/jacket …)."""
    return (key in CLOTHING_STATE_TAGS or key in CLOTHING_DESCRIPTOR_TAGS
            or key.startswith("bare ") or key.startswith("open "))

_DATA = Path(__file__).resolve().parents[1] / "data"


def _norm(tag: Any) -> str:
    return str(tag or "").replace("_", " ").strip()


@lru_cache(maxsize=None)
def _txt_vocab(name: str) -> frozenset[str]:
    try:
        lines = (_DATA / name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(_norm(x).lower() for x in lines if x.strip())


@lru_cache(maxsize=1)
def _meta_vocab() -> frozenset[str]:
    try:
        data = json.loads((_DATA / "taglist" / "meta_tags.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    tags = data.get("tags") if isinstance(data, dict) else data
    if isinstance(tags, dict):
        tags = [t for v in tags.values() for t in (v if isinstance(v, list) else [v])]
    return frozenset(_norm(t).lower() for t in (tags or []) if isinstance(t, str) and t.strip())


def scene_tags(raw_tags: Iterable[Any]) -> list[str]:
    """한 컷의 태그 - 공백형 · 중복 제거 · 캐릭터 특징 / 메타 / rating 태그 제외."""
    features = _txt_vocab("characteristic_list.txt")
    meta = _meta_vocab()
    out: list[str] = []
    for raw in raw_tags:
        tag = _norm(raw)
        key = tag.lower()
        if not tag or tag in out or key in features or key in meta or key.startswith("rating:"):
            continue
        out.append(tag)
    return out


# 이웃 컷이 비슷한 이야기 = 버린다(사용자 2026-10-17 "방식은 버림" - 이야기 통째로).
# 이웃 쌍 하나라도 겹침 ≥ SIMILAR_JACCARD 이거나 새 태그 < SIMILAR_MIN_NEW 이면 비슷하다.
# events_v1 133,358 -> 105,466(3컷 12,932 · 4컷 3,358). 만화 한 장으로 묶었을 때 칸이 같은 그림을 되풀이하던 이야기다.
# 규칙을 바꾸면 SIMILAR_RULE_VERSION 을 올린다 - 로드 캐시(core/sequence_preset_service)가 다시 만든다.
SIMILAR_JACCARD = 0.85
SIMILAR_MIN_NEW = 3
# 눈에 띄는 변화(사용자 2026-10-18 "Q 는 죄다 옷 벗기는 것 밖에 없다"): 이웃 쌍마다 새로 생긴 태그 중 옷 · 노출 · 상태 ·
# 표정 · 시선 · 배경색 · 땀을 뺀 것(= 자세 · 행동 · 구도 · 인물 · 장소 · 사물)이 이만큼은 있어야 한다. 실측(표본 3,000):
# 쌍마다 3개 이상 = Q 39% · E 79% / 어느 한 쌍이라도 0개 = Q 24% · E 7%(옷만 벗거나 아무것도 안 바뀜).
STRONG_MIN_NEW = 3
SIMILAR_RULE_VERSION = 2
# 바뀌어도 그림이 거의 안 바뀌는 노출 · 몸 태그(의상 사전 · 상태 태그와 함께 '눈에 띄는 변화' 에서 뺀다).
EXPOSURE_TAGS = frozenset({
    "nipples", "pussy", "areolae", "nude", "completely nude", "topless", "bottomless", "breasts out", "ass", "navel",
    "cleft of venus", "anus", "censored", "mosaic censoring", "uncensored", "pubic hair", "cameltoe", "panties",
    "underwear", "bra", "lingerie", "underwear only", "no bra", "no panties", "breasts", "collarbone", "stomach",
    "groin", "thighs", "bare shoulders", "cleavage", "medium breasts", "large breasts", "small breasts",
    "topless female", "barefoot",
})
# 표정 사전(data/taglist/expression_tags.json)에 더해 시선 · 배경색 · 땀 · 효과처럼 구도를 안 바꾸는 것.
WEAK_EXTRA_TAGS = frozenset({
    "looking at viewer", "looking away", "looking to the side", "looking down", "looking up", "looking back",
    "simple background", "white background", "grey background", "gradient background", "blurry background",
    "sweat", "sweatdrop", "heart", "spoken heart", "motion lines", "trembling", "steam", "convenient censoring",
    "solo", "solo focus", "english text", "speech bubble", "blank censor",
})


@lru_cache(maxsize=1)
def _weak_vocab() -> frozenset[str]:
    try:
        data = json.loads((_DATA / "taglist" / "expression_tags.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    tags: list[Any] = list(data.get("tags") or []) if isinstance(data, dict) else []
    for key in ("groups", "modifiers"):
        block = data.get(key) if isinstance(data, dict) else None
        if isinstance(block, dict):
            tags += [t for v in block.values() for t in (v if isinstance(v, list) else [])]
    return frozenset(_norm(t).lower() for t in tags if isinstance(t, str)) | WEAK_EXTRA_TAGS


def _is_visible_change(tag: str) -> bool:
    key = tag.lower()
    if key in EXPOSURE_TAGS or key in CLOTHING_STATE_TAGS or key in _weak_vocab():
        return False
    if key.startswith(("bare ", "open ")) or "lift" in key or "pull" in key or "aside" in key:
        return False
    return key not in _txt_vocab("clothes_list.txt")


def has_similar_neighbors(frames: list[dict[str, Any]]) -> bool:
    """이웃 컷 쌍 중 하나라도 비슷하면 True(장면 태그 = 캐릭터 특징 · 메타 · rating 을 뺀 것).
    비슷함 = 겹침이 크거나 새 태그가 적거나, **눈에 띄는 변화**(_is_visible_change)가 STRONG_MIN_NEW 개 미만."""
    tag_sets = [set(scene_tags(f.get("tags") or [])) for f in frames]
    for prev, cur in zip(tag_sets, tag_sets[1:]):
        jac = len(prev & cur) / max(1, len(prev | cur))
        new = cur - prev
        if jac >= SIMILAR_JACCARD or len(new) < SIMILAR_MIN_NEW:
            return True
        if sum(1 for t in new if _is_visible_change(t)) < STRONG_MIN_NEW:
            return True
    return False


def plan_comic(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """frames = [{"tags": [...], "rating": "q"}, ...] -> {"clothing": [...], "scenes": [...]}.

    scenes[k] = {"tags": 그 컷의 장면 태그 전체, "shown": 실을 태그, "rating", "removed": 직전 장면에서 빠진 태그}.
    실을 태그 = 의상 줄로 올라간 것을 빼고, scene 2 부터는 직전 컷에서 새로 생긴 것만(= 미리보기의 add).
    removed 는 미리보기에만 쓴다(프롬프트에는 안 실린다) - 옷은 빼고 보여 준다(사용자 2026-10-18 "옷은 보여주지 맙시다").
    """
    clothes = _txt_vocab("clothes_list.txt")
    usable = [(scene_tags(f.get("tags") or []), str(f.get("rating") or "")) for f in frames]
    usable = [(tags, rating) for tags, rating in usable if tags]
    if not usable:
        return {"clothing": [], "scenes": []}
    worn = [t for t in usable[0][0] if t.lower() in clothes and not _not_worn(t.lower())]
    worn_keys = {t.lower() for t in worn}
    scenes: list[dict[str, Any]] = []
    for tags, rating in usable:
        shown = [t for t in tags if t.lower() not in worn_keys]
        removed: list[str] = []
        if scenes:
            prev_tags = scenes[-1]["tags"]
            prev = set(prev_tags)
            shown = [t for t in shown if t not in prev]
            # ⚠️ 실을 태그가 **하나도 없을 때만** 합친다(사용자 2026-10-17 제보: 3 · 4컷이 전부 scene 2 까지만 나왔다).
            #    처음엔 '겹침 ≥ 0.85 · 새 태그 < 3' 이면 합쳤는데, Sequence 데이터(events_v1)는 이웃 컷이 태그 한두 개
            #    차이인 경우가 많아 3컷 이야기의 44% · 5~6컷의 72~75% 가 장면을 잃었다. 새 태그 0 기준이면 13% · 30%.
            #    새 태그가 의상 줄에 이미 있는 것뿐이면(예: short shorts) 그 장면은 rating 만 남으므로 역시 합친다.
            if not shown:
                continue
            cur = set(tags)
            removed = [t for t in prev_tags if t not in cur
                       and not (t.lower() in clothes and not _not_worn(t.lower()))]
        scenes.append({"tags": tags, "shown": shown, "rating": rating, "removed": removed})
        if len(scenes) >= MAX_SCENES:
            break
    return {"clothing": worn, "scenes": scenes}


def build_comic_body(frames: list[dict[str, Any]]) -> tuple[int, str]:
    """frames = [{"tags": [...], "rating": "q"}, ...] -> (장면 수, 본문). 장면이 없으면 (0, "")."""
    plan = plan_comic(frames)
    scenes = plan["scenes"]
    if not scenes:
        return 0, ""
    lines: list[str] = []
    if plan["clothing"]:
        lines.append(f"character clothing: {', '.join(plan['clothing'])}")
    layouts = SCENE_LAYOUTS.get(len(scenes), ())
    for k, scene in enumerate(scenes, start=1):
        rating_tag = RATING_TAGS.get(scene["rating"].lower()[:1], "")
        head = [f"(layout:{layouts[k - 1]})", "sequential"] if layouts else []
        lines.append(f"scene {k}: {', '.join(head + scene['shown'] + ([rating_tag] if rating_tag else []))}")
    return len(scenes), ",\n\n".join(lines)


def comic_preview(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Sequence [미리보기] 툴팁 데이터(사용자 2026-10-18): 의상 상자 · scene 1 = 실을 태그 · scene 2~ = add / rem."""
    plan = plan_comic(frames)
    out = []
    for k, scene in enumerate(plan["scenes"], start=1):
        item = {"index": k, "rating": scene["rating"]}
        if k == 1:
            item["tags"] = scene["shown"]
        else:
            item["add"] = scene["shown"]
            item["rem"] = scene["removed"]
        out.append(item)
    return {"clothing": plan["clothing"], "scenes": out}


def panel_tags(n: int) -> str:
    return f"{n}koma, {n} panel comic, sequential"


def comic_spec(n: int) -> dict[str, Any] | None:
    """장면 수 n 의 고정 사양(해상도 · koma). 사양이 없는 수(1)면 None - 그때는 사용자 해상도 · 만화 문구 없음."""
    return COMIC_SPECS.get(int(n or 0))


def comic_size(spec: dict[str, Any], large: bool = False) -> tuple[int, int]:
    """사양의 해상도 - 라지면 large(없으면 노말)."""
    return tuple(spec.get("large") or spec["size"]) if large else tuple(spec["size"])


def build_comic_prompt(assembled: str, n: int, body: str) -> str:
    """조립된 프롬프트(PE prefix + 본문 + postfix)의 **본문 자리**를 만화 본문으로 바꾼다.

    본문 자리 = 본문 표식(`#랜덤프롬프트` 또는 카테고리 표식)부터 다음 빈 줄(`\\n\\n`)까지. 표식 줄은 나갈 때
    주석으로 지워지므로 표식 다음 줄은 쉼표로 시작해야 첫 장면이 함께 지워지지 않는다.
    PE 파이프라인을 장면 줄에 통과시키지 않는 이유: 본문 태그를 정렬 · 중복 제거 · 숨김 처리해 `scene k:` 구조가 깨진다.

    장면 수 사양이 있으면(2~4, 사용자 2026-10-17):
    - `2::{k}koma ::` 를 맨 앞 인원 태그(`1boy` · `1girl` · `2girls` …) 앞에(없으면 맨 앞),
    - 고정 문장(COMIC_SENTENCE)을 **선행 고정 프롬프트(PE prefix) 뒤** = 본문 표식 바로 앞에 붙인다.
    ⚠️ 맨 앞의 `{n}koma, {n} panel comic, sequential` 은 회수했다(사용자: "묻어나온다").
    """
    import re

    from core.prompt_category_annotation import LEGACY_MAIN_MARKER, find_main_block_start

    text = assembled or ""
    spec = comic_spec(n)
    at = find_main_block_start(text)
    end = text.find("\n\n", at) if at >= 0 else -1
    if at < 0 or end < 0:
        prefix, tail = text, ""
    else:
        prefix, tail = text[:at], text[end:]
    if spec:
        koma = f"2::{spec['koma']} ::"
        hit = re.search(_PERSON_TAG, prefix)
        prefix = f"{prefix[:hit.start()]}{koma}, {prefix[hit.start():]}" if hit else f"{koma}, {prefix}"
        sentence = COMIC_SENTENCE.format(n=n, order=COMIC_ORDER.get(int(n or 0), COMIC_ORDER_DEFAULT))
        stripped = prefix.rstrip()
        trail = prefix[len(stripped):]
        core_prefix = stripped.rstrip(",").rstrip()
        prefix = f"{core_prefix}, {sentence},{trail}" if core_prefix else f"{sentence},{trail}"
    if at < 0 or end < 0:
        return f"{prefix},\n\n{body},\n\n" if prefix else body
    return f"{prefix}{LEGACY_MAIN_MARKER}\n, {body}{tail}"
