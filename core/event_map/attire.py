# -*- coding: utf-8 -*-
"""입는 것(옷 · 장신구 · 머리 장식) 가르기.

분류는 `tools/add_default_attire.py`(캐릭터 기본 의상 빌더)가 쓰던 것을 그대로 옮겼다 - 런타임은 tools/ 를 부를 수
없다(배포에 없다). 빌더는 이제 이 모듈을 가져다 쓴다.

뽑기(게시물 하나에서 의상 · 행동 …)는 `core.event_map.post_pick` 이 한다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from core.event_map.tree import TREE_PATH


class AttireClassifier:
    """태그가 **입는 것**(옷 · 장신구 · 머리 장식)인지 - 이벤트 맵 3단 지도(Danbooru 위키 tag_groups)로 가른다.

    지도의 자리(D1 > D2 > D3)로 본다. 한 태그가 여러 자리에 있을 수 있다(`hair bow` = 머리 > Objects · 장신구 · 의상).
      · 강한 자리 = D1 `Attire and body accessories` 에서 화장(`makeup`) · 노출(`nudity`) 쪽을 뺀 곳 -> 의상
      · 약한 자리 = 몸 갈래 안의 '입는 것' 절(`WEAK`) - 머리 장식 · 귀걸이 · 양말류 · 어깨 옷 · 가슴 옷.
        노출 자리에도 있으면 의상이 아니다(`bare shoulders` · `off shoulder` · `no bra`).
      · 지도에 있는데 위 어디에도 없으면 의상이 아니다(`low ponytail` = 머리 모양 · `halo` · `animal ears` = 몸 ·
        `nail polish` = 화장 · `bare shoulders` = 노출).
      · 단, 그 자리가 몸 · 노출 · 화장이 **아닌** 딴 갈래뿐이면(무늬 · 동물 · 사물 - `heart earrings` = symbols ·
        `cat hair ornament` = cats) 아래 '앞 낱말 떼기' 를 계속한다 -> earrings · hair ornament.
        몸 · 노출 · 들고 있다 · 구도(무늬 제외) 자리는 계속하지 않는다 - `no shoes` -> shoes · `no bra` -> bra ·
        `diffraction spikes` -> spikes 로 뒤집히면 안 된다.
    지도에 없는 태그(지도는 **색 태그를 버렸다** - `white shirt` · `red bow`)는 앞 낱말을 하나씩 떼며 처음 걸리는
    자리로 본다: `white shirt` -> shirt · `plaid skirt` -> skirt · `black-framed eyewear` -> eyewear ·
    `red nails` -> nails(어디에도 없다 = 의상 아님) · `very long braid` -> long braid(머리 모양).
    지도에 없는 포괄 낱말(`UMBRELLA` - `black headwear` · `white footwear` · `gold trim`)만 손으로 둔다.
    끝까지 못 찾으면 의상이 아니다(`striped` · `animal print` - 무늬만으로는 옷이 아니다).

    **들고 다니는 것은 의상이 아니다**(사용자 결정 2026-10-22): 지도는 가방 · 우산 · 부채를 장신구(Bags · Misc)에 두지만
    몸에 걸친 것이 아니다 - `CARRIED` 로 뺀다. `unworn ` · `holding ` 으로 시작하는 태그도 의상이 아니다.
    몸에 차는 것(머리 장식 · 장신구 · 안경 · 머리에 얹은 가면/고글 · 허벅지 파우치)은 그대로 의상이다.
    """

    ATTIRE_D1 = "Attire and body accessories"
    NOT_WORN_D2 = frozenset({"tag_group:makeup", "tag_group:nudity"})
    NUDITY_D2 = "tag_group:nudity"
    WEAK = frozenset({
        ("tag_group:hair", "Objects"),
        ("tag_group:ears_tags", "Objects for the ears; or, objects with ears"),
        ("tag_group:feet", "Clothing & Accessories"),
        ("tag_group:shoulders", "Attire for shoulders"),
        ("tag_group:breasts_tags", "Clothes for breasts"),
    })
    # 지도에 없거나(포괄 태그) 엉뚱한 자리에만 있는(`jewelry` = 들고 있는 것) 포괄 낱말.
    UMBRELLA = frozenset({"headwear", "footwear", "eyewear", "legwear", "handwear", "neckwear", "sleeves", "trim",
                          "jewelry"})
    BODY_D1 = "Body"
    # 들고 다니는 것 - 지도의 장신구 > Bags · Misc · Decorations 에서 몸에 걸치지 않는 것을 골랐다.
    # 몸에 차는 thigh pouch · arm pouch · belt bag 과 몸 · 옷에 붙는 것(vision · tail ornament · ofuda on clothes ·
    # soul gem · wing ornament · core crystal · purity seal · shide)은 남긴다.
    CARRIED = frozenset({
        # Bags
        "bag", "backpack", "school bag", "handbag", "randoseru", "shopping bag", "paper bag", "plastic bag",
        "duffel bag", "animal bag", "satchel", "rolling suitcase", "grocery bag", "school briefcase", "kinchaku",
        "coin purse", "luggage", "heart-shaped bag", "tote bag", "open bag", "backpack basket", "book holster",
        "bear bag", "money bag", "transparent bag", "rabbit bag", "heart pouch", "drawstring bag",
        # Misc - 우산 · 부채 · 손에 드는 물건
        "umbrella", "oil-paper umbrella", "beach umbrella", "parasol", "closed umbrella", "transparent umbrella",
        "shared umbrella", "frilled umbrella", "leaf umbrella", "planted umbrella", "torn umbrella",
        "animal-themed umbrella",
        "hand fan", "folding fan", "paper fan", "folded fan", "uchiwa", "tuanshan", "transparent fan", "war fan",
        "leaf fan", "harisen",
        "cane", "pocket watch", "handkerchief", "pencil case", "wallet", "ritual baton", "keyring", "tucked money",
        "virtual pet (toy)", "shakujou", "omamori", "talisman", "mp3 player", "cigarette holder", "cellphone strap",
        "pop socket", "muff",
        # Decorations 중 몸에 걸치지 않는 것
        "bag charm", "keychain", "animal keychain", "cellphone charm", "frilled pillow", "frilled innertube",
        # 손에 드는 것(지도는 갑옷 · 손 장비에 둔다)
        "shield", "puppet", "hand puppet",
    })
    # 이 낱말로 시작하면 의상이 아니다 - 벗어 둔 것 · 들고 있는 것 · 옷을 만지는 동작(`lifting own clothes`).
    STOP_FIRST = frozenset({"unworn", "holding", "lifting", "adjusting", "removing"})
    # 구도 · 스타일 갈래는 무늬(symbols)만 빼고 확정이다 - `diffraction spikes`(촬영 효과)가 spikes(장식)로 넘어가면
    # 안 된다. 나머지 딴 갈래(무늬 · 동물 · 운동 · 물 …)는 앞 낱말 떼기를 계속한다(`baseball uniform` -> uniform ·
    # `wet shirt` -> shirt · `heart earrings` -> earrings).
    COMPOSITION_D1 = "Image composition and style"
    SYMBOLS_D2 = "tag_group:symbols"
    HOLDING_D2 = "tag_group:holding_tags"

    def __init__(self, tree_path: Path = TREE_PATH):
        tree = json.loads(Path(tree_path).read_text(encoding="utf-8"))
        self.place: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for d1 in tree.get("d1") or []:
            for d2 in d1.get("d2") or []:
                for d3 in d2.get("d3") or []:
                    for tag in d3.get("tags") or []:
                        self.place[str(tag)].append((str(d1.get("id")), str(d2.get("id")), str(d3.get("id"))))
        self._memo: dict[str, bool] = {}

    def _direct(self, tag: str) -> bool | None:
        """True = 의상 · False = 의상 아님(확정) · None = 모름(앞 낱말을 떼고 계속)."""
        if tag in self.CARRIED:
            return False
        if tag in self.UMBRELLA:
            return True
        hits = self.place.get(tag)
        if not hits:
            return None
        strong = any(d1 == self.ATTIRE_D1 and d2 not in self.NOT_WORN_D2 for d1, d2, _ in hits)
        weak = any((d2, d3) in self.WEAK for _, d2, d3 in hits)
        nude = any(d2 == self.NUDITY_D2 for _, d2, _ in hits)
        if strong or (weak and not nude):
            return True
        if any(d1 in (self.BODY_D1, self.ATTIRE_D1) or d2 == self.HOLDING_D2
               or (d1 == self.COMPOSITION_D1 and d2 != self.SYMBOLS_D2) for d1, d2, _ in hits):
            return False                    # 몸 · 노출 · 화장 · 들고 있다 · 촬영 효과 = 확정
        return None                         # 딴 갈래(무늬 · 동물 · 운동 · 물 …)뿐 - 더 짧은 꼬리를 본다

    def is_attire(self, tag: str) -> bool:
        tag = " ".join(str(tag or "").replace("_", " ").lower().split())
        hit = self._memo.get(tag)
        if hit is None:
            words = tag.split(" ")
            hit = False
            for i in range(0 if words[0] in self.STOP_FIRST else len(words)):
                found = self._direct(" ".join(words[i:]))
                if found is not None:
                    hit = found
                    break
            self._memo[tag] = hit
        return hit



_CLASSIFIER: AttireClassifier | None = None


def attire_classifier() -> AttireClassifier:
    global _CLASSIFIER
    if _CLASSIFIER is None:
        _CLASSIFIER = AttireClassifier()
    return _CLASSIFIER


def drop_covered(tags: list[str]) -> list[str]:
    """더 자세한 태그가 덮는 포괄 태그를 뺀다 - `white shirt` 가 있으면 `shirt` 는 군더더기다."""
    return [t for t in tags if not any(o != t and o.endswith(" " + t) for o in tags)]
