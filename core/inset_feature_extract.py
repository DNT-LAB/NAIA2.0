"""레퍼런스 인셋의 [특징 추출] - WD 태거 결과에서 **캐릭터 특징만** 고른다(사용자 결정 2026-10-18).

외부 캐릭터 그림을 칸에 붙여넣고 태거를 부르면, 그 그림의 표정 · 자세 · 배경 · 옷까지 태그로 나온다. 가상 캐릭터
프롬프트에 들어갈 것은 **그 인물 자신**(머리 · 눈 · 몸 · 종족 · 장신구 · 이름)뿐이다.

⚠️ 의상 필터(`core/character_outfit_filter.strip_outfit_tags`)와 방향이 반대다. 그쪽은 사람이 쓴 캐릭터 프롬프트에서
   "의상으로 확인된 것만 뺀다"(모르는 것은 남긴다). 여기는 태거가 뱉은 것이라 `solo` · `smile` · `looking at viewer`
   같은 것이 섞여 있다 - **남길 것으로 확인된 것만 남기고**, 어디에도 없는 것은 버리지 않고 `unknown` 으로 돌려 사람이
   켜게 한다(의상 필터에서 체형 · 종족이 사전에 없어 빠졌던 사고를 되풀이하지 않는다).

판정 차례(`split_character_features`):
  1. 태거의 캐릭터 태그(이름 · `sayuri (blue archive)`)          → 남긴다
  2. 인물 태그 `1girl` · `1boy` · `1other`                       → `girl` · `boy` · `other` 로 남긴다(캐릭터 프롬프트 관례)
     여럿(`2girls` · `multiple girls`) · `solo` 류                → 뺀다(메타)
  3. 부품 카탈로그: 머리 · 눈 · 얼굴 · 신체 · 종족 · 장신구       → 남긴다 / 의상 · 소지품 → 뺀다(의상)
  4. 특징 사전 · 장신구 낱말                                      → 남긴다
  5. 프롬프트 주석 분류(`#특징:` · `#의상:` · `#표정:` …)          → 특징이면 남기고, 나머지는 그 이름으로 뺀다
  6. 어디에도 없다                                                → `unknown`
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

PERSON_RENAME = {"1girl": "girl", "1boy": "boy", "1other": "other"}
# 그림 한 장의 사정이지 그 인물의 특징이 아닌 것 - 사전에 없을 수 있어 여기서 먼저 뺀다.
META_TAGS = frozenset({
    "solo", "solo focus", "multiple girls", "multiple boys", "multiple others", "2girls", "2boys", "2others",
    "3girls", "3boys", "multiple views", "looking at viewer", "simple background", "white background",
    "transparent background", "grey background", "black background", "gradient background", "blurry",
    "blurry background", "depth of field", "upper body", "full body", "cowboy shot", "portrait", "close-up",
    "official art", "game cg", "signature", "watermark", "english text", "text", "artist name", "dated",
})
DROP_LABELS = {
    "clothes": "의상", "clothing_event": "의상", "expression": "표정", "pose_action": "포즈",
    "object": "사물", "location": "배경", "meta": "메타",
}


def _clean(tag: Any) -> str:
    return str(tag or "").replace("_", " ").strip().lower()


def split_character_features(
    character_tags: Iterable[Any],
    general_tags: Iterable[Any],
    filter_manager: Any = None,
    repo_root: str | Path | None = None,
) -> dict[str, list]:
    """`{keep: [태그], unknown: [태그], dropped: [{tag, group}]}` - 차례는 태거의 순서(인물 태그는 맨 앞)."""
    from core.character_outfit_filter import (
        _catalog_entry,
        _catalog_verdict,
        _vocabulary,
        is_accessory_or_headwear,
    )

    vocabulary = _vocabulary(repo_root)
    sets: dict = {}
    if filter_manager is not None:
        try:
            from core.prompt_category_annotation import _category_sets

            sets = _category_sets(filter_manager) or {}
        except Exception:      # noqa: BLE001 - 분류 사전이 없으면 5번을 건너뛴다(모르는 것으로 남는다)
            sets = {}
    person: list[str] = []
    keep: list[str] = []
    unknown: list[str] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()

    def once(tag: str) -> bool:
        if not tag or tag in seen:
            return False
        seen.add(tag)
        return True

    for raw in character_tags:
        tag = _clean(raw)
        if once(tag):
            keep.append(tag)
    for raw in general_tags:
        tag = _clean(raw)
        if not once(tag):
            continue
        if tag in PERSON_RENAME:
            renamed = PERSON_RENAME[tag]
            if renamed not in person:
                person.append(renamed)
            continue
        if tag in META_TAGS:
            dropped.append({"tag": tag, "group": "메타"})
            continue
        entry = _catalog_entry(tag, vocabulary["catalog"])
        if entry is not None:
            if _catalog_verdict(tag, entry):
                keep.append(tag)
            else:
                dropped.append({"tag": tag, "group": "의상"})
            continue
        if tag in vocabulary["traits"] or is_accessory_or_headwear(tag, repo_root):
            keep.append(tag)
            continue
        category = "extra"
        if sets:
            from core.prompt_category_annotation import classify

            category = classify(tag, sets)
        if category == "features":
            keep.append(tag)
        elif category in DROP_LABELS:
            dropped.append({"tag": tag, "group": DROP_LABELS[category]})
        else:
            unknown.append(tag)
    return {"keep": person + keep, "unknown": unknown, "dropped": dropped}
