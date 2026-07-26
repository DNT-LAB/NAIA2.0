# -*- coding: utf-8 -*-
"""태그 하나를 골랐을 때 보여줄 '전제조건(dependencies)'과 '추천(recommend)'.

## 문제

초보자가 `hugging tail`(꼬리 껴안기)을 고르면 꼬리가 없는 캐릭터가 나온다.
태그 자체는 유효하지만 **그 태그가 전제하는 다른 태그**를 같이 넣어야 그림이 된다.
`skirt lift` 는 치마가, `adjusting eyewear` 는 안경이 있어야 한다.

## 데이터 근거

태그 DB 의 `relations` 가 이미 상당 부분을 갖고 있다(실측):

    parent      12,363개 보유   -> 전제조건의 1차 후보
    children     2,277개 보유   -> "더 구체적으로" 추천
    siblings    11,384개 보유   -> "비슷한 것" 추천
    word_match  11,792개 보유   -> 이름이 겹칠 뿐이라 쓰지 않는다

## 함정 두 가지 (실측으로 확인)

**(1) parent 는 부분적으로 문자열 파생이다.**
    undressing        -> dress   ("undressing" 안에 "dress")
    crossdressing     -> dress
    spoken ellipsis   -> lips    ("ellipsis" 안에 "lips")
한글 설명에 그 단어의 대응이 없으면 걸러낸다.

**(2) 참인 parent 라도 전제조건이 아닐 수 있다.**
    arms behind back  -> back    누구나 등이 있다
    crossed legs      -> legs
    between breasts   -> breasts
전제조건은 **모두가 갖고 있지는 않은 것**이어야 의미가 있다. 그래서 보편 신체 축
(body_expose/body_feature/face/hair ...)의 부모는 전제로 세지 않는다.
실측: parent 가 축 안에 있는 359개 중 112개가 이 경우였다.

## 구성

    후보 = parent 소스 U 설명 어휘 소스
    - parent 소스: parent 가 '비보편 축'의 태그일 때 (실측 247개)
    - 설명 소스  : 한글 설명에 축의 대표 어휘가 나올 때 (실측 230개)
    두 소스의 합집합에서 CONFIRMED/DENIED 큐레이션을 적용한다.

큐레이션 목록은 Codex 검증 결과로 채운다. 검증 전에는 `strict=True` 로 두 소스가
**모두 동의하는 것만** 내보낸다(정밀도 우선) — 잘못된 전제 안내는 없느니만 못하다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

_ROOT = Path(__file__).resolve().parent.parent
AXIS_DIR = _ROOT / "wildcards" / "thumb"

# 누구나 갖고 있어서 전제조건이 될 수 없는 축.
UNIVERSAL_AXES = {
    "body_expose", "body_feature", "body_type", "body_condition",
    "face", "face_shape", "hair_style", "bangs", "hair_pattern",
    "skin", "eye_pattern", "marking",
    "expression", "expression_state", "expression_symbol",
}

# 축 -> (표시 이름, 한글 설명에서 그 축을 가리키는 어휘)
# 보편 축은 넣지 않는다. 어휘는 좁게 잡는다 — 넓히면 은유까지 걸린다
# (`\\m/` 설명의 "악마의 뿔"은 손동작이지 뿔이 아니다).
AXIS_TRIGGERS: dict[str, tuple[str, str]] = {
    "tail": ("꼬리", r"꼬리"),
    "wings": ("날개", r"날개"),
    "horns": ("뿔", r"뿔(?!테)"),
    "ears": ("귀", r"(동물|짐승|고양이|여우|토끼|늑대|말)\s?귀"),
    "species": ("종족", r"(수인|케모노|엘프|악마|천사|인어)"),
    "body_nonhuman": ("이형 부위", r"(아가미|물갈퀴|발굽|촉수)"),
    "cloth_eyewear": ("안경·마스크", r"(안경|고글|안대|가면|마스크|선글라스)"),
    "cloth_headwear": ("모자", r"(모자|후드|헬멧|두건)"),
    "cloth_bottom": ("하의", r"(치마|스커트|바지|반바지)"),
    "cloth_top": ("상의", r"(셔츠|재킷|코트|스웨터|블라우스|가디건)"),
    "cloth_under": ("속옷", r"(팬티|브래지어|속옷)"),
    "cloth_swim": ("수영복", r"(수영복|비키니)"),
    "cloth_dress": ("원피스·한벌", r"(드레스|원피스|레오타드)"),
    "cloth_legwear": ("다리", r"(스타킹|양말|타이츠|니삭스)"),
    "cloth_handwear": ("손", r"장갑"),
    "cloth_neck": ("목", r"(넥타이|목도리|스카프|초커)"),
    "cloth_footwear": ("신발", r"(신발|구두|부츠|샌들)"),
    "cloth_outer": ("겉옷", r"(망토|케이프|앞치마)"),
    "cloth_traditional": ("전통 의상", r"(기모노|하카마|치파오|한복)"),
    "cloth_uniform": ("제복·코스튬", r"(교복|제복|메이드복|간호사복)"),
}

# ── 1차 근거: Danbooru 공식 tag implications ────────────────────────────────
# `data/interactive_preset_facts.json` 의 implications (tools/build_preset_facts.py).
# 이벤트 프리셋 아카이브의 `base/dependency_rules.parquet` 에서 왔고, 6,679건이
# Danbooru wiki 의 tag_implications(confidence 1.0)다. 아래 문자열 휴리스틱보다
# 압도적으로 정확하다 — `undressing -> dress` 같은 어간 우연이 애초에 없다.
#
# 휴리스틱은 공식 규칙에 **없는 것만** 보완한다(`adjusting eyewear` 등).
FACTS_PATH = _ROOT / "data" / "interactive_preset_facts.json"

# Codex 검증(334 후보)으로 채운 큐레이션.
#   CONFIRMED: 한 소스만 걸려도 참인 전제 (YES 193건)
#   WEAK     : 있으면 좋지만 필수는 아님 (12건) — 힌트 문구를 낮춘다
#   DENIED   : 두 소스가 동의해도 전제가 아닌 것 (117건, 은유·선택 소품·철자 우연)
CONFIRMED: dict[str, str] = {
    'adjusting bow': 'cloth_accessory', 'adjusting bra': 'cloth_under',
    'adjusting eyewear': 'cloth_eyewear', 'adjusting footwear': 'cloth_footwear',
    'adjusting gloves': 'cloth_handwear', 'adjusting goggles': 'cloth_eyewear',
    'adjusting headphones': 'cloth_accessory', 'adjusting headwear': 'cloth_headwear',
    'adjusting hood': 'cloth_headwear', 'adjusting legwear': 'cloth_legwear',
    'adjusting leotard': 'cloth_dress', 'adjusting necktie': 'cloth_neck',
    'adjusting panties': 'cloth_under', 'adjusting scarf': 'cloth_neck',
    'adjusting shoe': 'cloth_footwear', 'adjusting swimsuit': 'cloth_swim',
    'apron hold': 'cloth_outer', 'apron lift': 'cloth_outer', 'apron pull': 'cloth_outer',
    'apron tug': 'cloth_outer', 'bike shorts pull': 'cloth_bottom',
    'bikini bottom aside': 'cloth_swim', 'bikini bottom pull': 'cloth_swim',
    'bikini pull': 'cloth_swim', 'bikini top aside': 'cloth_swim',
    'bikini top lift': 'cloth_swim', 'bikini top pull': 'cloth_swim',
    'bikini tug': 'cloth_swim', 'blindfold lift': 'cloth_eyewear',
    'bra lift': 'cloth_under', 'bra pull': 'cloth_under', 'buruma aside': 'cloth_swim',
    'cape hold': 'cloth_outer', 'cape lift': 'cloth_outer', 'coat lift': 'cloth_top',
    'collar grab': 'cloth_top', 'dress aside': 'cloth_dress', 'dress flip': 'cloth_dress',
    'dress grab': 'cloth_dress', 'dress lift': 'cloth_dress', 'dress pull': 'cloth_dress',
    'dress tug': 'cloth_dress', 'expressive tail': 'tail', 'eyepatch lift': 'cloth_eyewear',
    'eyewear lift': 'cloth_eyewear', 'flapping': 'wings', 'glove biting': 'cloth_handwear',
    'glove pull': 'cloth_handwear', 'hadanugi dousa': 'cloth_traditional',
    'hakama lift': 'cloth_traditional', 'hand in bikini': 'cloth_swim',
    'hand in pocket': 'cloth_detail', 'hand on eyewear': 'cloth_eyewear',
    'hand on goggles': 'cloth_eyewear', 'hand on headphones': 'cloth_accessory',
    'hand on headwear': 'cloth_headwear', 'hand under shirt': 'cloth_top',
    'hands in pocket': 'cloth_detail', 'hands in pockets': 'cloth_detail',
    'hands on eyewear': 'cloth_eyewear', 'hands on headphones': 'cloth_accessory',
    'hands on headwear': 'cloth_headwear', 'hat loss': 'cloth_headwear',
    'hat tip': 'cloth_headwear', 'hat tug': 'cloth_headwear', 'heart tail duo': 'tail',
    'heel pop': 'cloth_footwear', "holding another's tail": 'tail',
    'holding own tail': 'tail', 'holding with tail': 'tail', 'horn grab': 'horns',
    "hugging another's tail": 'tail', 'hugging own tail': 'tail', 'hugging tail': 'tail',
    'intertwined tails': 'tail', 'jacket grab': 'cloth_top', 'jacket lift': 'cloth_top',
    'jacket on shoulders': 'cloth_top', 'jacket over shoulder': 'cloth_top',
    'jacket partially removed': 'cloth_top', 'jacket pull': 'cloth_top',
    'jacket tug': 'cloth_top', 'kimono lift': 'cloth_traditional',
    'kimono pull': 'cloth_traditional', 'leotard aside': 'cloth_dress',
    'leotard lift': 'cloth_dress', 'leotard pull': 'cloth_dress', 'lifted by tail': 'tail',
    'looking over eyewear': 'cloth_eyewear', 'male underwear aside': 'cloth_under',
    'male underwear pull': 'cloth_under', 'mask lift': 'cloth_eyewear',
    'mask pull': 'cloth_eyewear', 'neckerchief between breasts': 'cloth_neck',
    'necktie grab': 'cloth_neck', 'necktie in mouth': 'cloth_neck',
    'nipples pressed together': 'body_nsfw', 'object in swimsuit': 'cloth_swim',
    'one-piece swimsuit pull': 'cloth_swim', 'open bikini': 'cloth_swim',
    'open fly': 'cloth_bottom', 'pajamas pull': 'cloth_style',
    'panties around ankles': 'cloth_under', 'panties around one ankle': 'cloth_under',
    'panties around one leg': 'cloth_under', 'panties aside': 'cloth_under',
    'panties on head': 'cloth_under', 'pants around one leg': 'cloth_bottom',
    'pants lift': 'cloth_bottom', 'pants pull': 'cloth_bottom', 'panty lift': 'cloth_under',
    'panty pull': 'cloth_under', 'panty tug': 'cloth_under',
    'pantyhose pull': 'cloth_legwear', 'partially unbuttoned': 'cloth_top',
    'pelvic curtain aside': 'cloth_detail', 'pelvic curtain lift': 'cloth_detail',
    'putting on gloves': 'cloth_handwear', 'putting on headwear': 'cloth_headwear',
    'putting on jewelry': 'cloth_accessory', 'putting on legwear': 'cloth_legwear',
    'putting on shoes': 'cloth_footwear', 'removing bra': 'cloth_under',
    'removing eyewear': 'cloth_eyewear', 'removing glove': 'cloth_handwear',
    'removing jacket': 'cloth_top', 'removing legwear': 'cloth_legwear',
    'removing mask': 'cloth_eyewear', 'removing pasties': 'cloth_nsfw',
    'removing shoes': 'cloth_footwear', 'ribbon in mouth': 'cloth_accessory',
    'sailor collar lift': 'cloth_detail', 'scarf pull': 'cloth_neck',
    'self wedgie': 'cloth_under', 'shared earphones': 'cloth_accessory',
    'shared scarf': 'cloth_neck', 'shirt around waist': 'cloth_top',
    'shirt behind neck': 'cloth_top', 'shirt down': 'cloth_top', 'shirt grab': 'cloth_top',
    'shirt hold': 'cloth_top', 'shirt in mouth': 'cloth_top', 'shirt lift': 'cloth_top',
    'shirt on shoulders': 'cloth_top', 'shirt partially removed': 'cloth_top',
    'shirt pull': 'cloth_top', 'shirt slip': 'cloth_top', 'shirt tucked in': 'cloth_top',
    'shirt tug': 'cloth_top', 'shoe dangle': 'cloth_footwear',
    'shoe loss': 'cloth_footwear', 'shorts around one leg': 'cloth_bottom',
    'shorts pull': 'cloth_bottom', 'skirt around ankles': 'cloth_bottom',
    'skirt around one leg': 'cloth_bottom', 'skirt flip': 'cloth_bottom',
    'skirt grab': 'cloth_bottom', 'skirt hold': 'cloth_bottom',
    'skirt lift': 'cloth_bottom', 'skirt pull': 'cloth_bottom',
    'skirt rolled up': 'cloth_bottom', 'skirt tug': 'cloth_bottom',
    'sock pull': 'cloth_legwear', 'spread wings': 'wings', 'stiff tail': 'tail',
    'strap break': 'cloth_detail', 'strap lift': 'cloth_detail',
    'strap pull': 'cloth_detail', 'suspenders hanging': 'cloth_accessory',
    'suspenders pull': 'cloth_accessory', 'sweater around neck': 'cloth_top',
    'sweater around waist': 'cloth_top', 'sweater lift': 'cloth_top',
    'sweater pull': 'cloth_top', 'sweater tug': 'cloth_top',
    'sweater vest lift': 'cloth_top', 'swimsuit aside': 'cloth_swim',
    'swimsuit lift': 'cloth_swim', 'swimsuit tug': 'cloth_swim',
    'tail around own leg': 'tail', 'tail between legs': 'tail', 'tail biting': 'tail',
    'tail grab': 'tail', 'tail pull': 'tail', 'tail raised': 'tail', 'tail wagging': 'tail',
    'tail wrap': 'tail', 'thong aside': 'cloth_under', 'thumb in pocket': 'cloth_detail',
    'tying apron': 'cloth_outer', 'tying footwear': 'cloth_footwear',
    'undone bikini': 'cloth_swim', 'wringing skirt': 'cloth_bottom',
}

WEAK: dict[str, str] = {
    'clothes between thighs': 'cloth_dress', 'convenient skirt': 'cloth_dress',
    'flying': 'wings', 'hand in pants': 'cloth_under', 'hands in pocket': 'cloth_top',
    'lifted by self': 'cloth_under', 'lifted by tail': 'cloth_dress',
    'pulled by self': 'cloth_under', 'skirt basket': 'cloth_dress',
    'skirt caught on object': 'cloth_dress', 'strap break': 'cloth_swim',
    'strap pull': 'cloth_under',
}

DENIED_PAIRS: set[tuple[str, str]] = {
    ('\\m/', 'horns'), ('\\m/', 'species'), ('ahoge wag', 'tail'),
    ('animal on head', 'cloth_headwear'), ('apron hold', 'cloth_bottom'),
    ('apron lift', 'cloth_bottom'), ('apron pull', 'cloth_bottom'),
    ('apron tug', 'cloth_bottom'), ('apron tug', 'cloth_under'),
    ('babywearing', 'cloth_accessory'), ('battleship', 'cloth_handwear'),
    ('bikini around one leg', 'cloth_swim'), ('bikini bottom pull', 'cloth_under'),
    ('bikini in mouth', 'cloth_swim'), ('bird on head', 'cloth_headwear'),
    ('blindfold slip', 'cloth_eyewear'), ('bloody wings', 'wings'),
    ('bowing', 'cloth_accessory'), ('bra slip', 'cloth_under'), ('bulge lift', 'body_nsfw'),
    ('bunny ears prank', 'ears'), ('buruma aside', 'cloth_under'),
    ('butterfly on head', 'cloth_headwear'), ('cardigan around waist', 'cloth_top'),
    ('cheering', 'cloth_accessory'), ('coat partially removed', 'cloth_top'),
    ('covering nipples', 'body_nsfw'), ('cowering', 'cloth_accessory'),
    ('crotch kick', 'body_nsfw'), ('decantering', 'cloth_accessory'),
    ('dress lift', 'cloth_under'), ('elbow on knee', 'cloth_accessory'),
    ('elbow rest', 'cloth_accessory'), ('eyewear hang', 'cloth_eyewear'),
    ('eyewear in mouth', 'cloth_eyewear'), ('fingersmile', 'tail'),
    ('firing', 'cloth_accessory'), ('glaring', 'cloth_accessory'),
    ('glove in mouth', 'cloth_handwear'), ('goggles around breasts', 'cloth_eyewear'),
    ('gyaru v', 'cloth_style'), ('hair tie in mouth', 'cloth_hairacc'),
    ('hakama lift', 'cloth_bottom'), ('hand on own elbow', 'cloth_accessory'),
    ('hands in pocket', 'cloth_headwear'), ('headphones removed', 'cloth_accessory'),
    ('henshin pose', 'cloth_eyewear'), ('holding binoculars', 'cloth_eyewear'),
    ('holding boots', 'cloth_footwear'), ('holding bow (ornament)', 'cloth_accessory'),
    ('holding bra', 'cloth_under'), ('holding cape', 'cloth_outer'),
    ('holding dress', 'cloth_dress'), ('holding dress', 'cloth_under'),
    ('holding earphones', 'cloth_accessory'), ('holding footwear', 'cloth_footwear'),
    ('holding gloves', 'cloth_handwear'), ('holding goggles', 'cloth_eyewear'),
    ('holding hair ornament', 'cloth_hairacc'), ('holding hat', 'cloth_headwear'),
    ('holding helmet', 'cloth_headwear'), ('holding jacket', 'cloth_top'),
    ('holding jewelry', 'cloth_accessory'), ('holding legwear', 'cloth_legwear'),
    ('holding mask', 'cloth_eyewear'), ('holding necktie', 'cloth_neck'),
    ('holding panties', 'cloth_under'), ('holding pocket watch', 'cloth_accessory'),
    ('holding removed eyewear', 'cloth_eyewear'), ('holding scarf', 'cloth_neck'),
    ('holding shirt', 'cloth_top'), ('holding shoes', 'cloth_footwear'),
    ('holding skirt', 'cloth_bottom'), ('holding suitcase', 'cloth_accessory'),
    ('holding swimsuit', 'cloth_swim'), ('holding underwear', 'cloth_under'),
    ('holding up', 'cloth_bottom'), ('hood down', 'cloth_headwear'),
    ('hoodie lift', 'cloth_headwear'), ('horns pose', 'horns'), ('impaled', 'horns'),
    ('in bag', 'cloth_accessory'), ('jacket around waist', 'cloth_top'),
    ('kimono lift', 'cloth_under'), ('measuring', 'cloth_accessory'),
    ('one-piece swimsuit pull', 'cloth_dress'), ('panties on head', 'cloth_eyewear'),
    ('panties on head', 'cloth_headwear'), ('pantyhose pull', 'cloth_under'),
    ('pot on head', 'cloth_headwear'), ('pouring', 'cloth_accessory'),
    ('powering up', 'cloth_accessory'), ('putting on headwear', 'cloth_dress'),
    ('rearing', 'cloth_accessory'), ('remembering', 'cloth_accessory'),
    ('removing legwear', 'cloth_under'), ('repairing', 'cloth_accessory'),
    ('roaring', 'cloth_accessory'), ('sharing food', 'cloth_accessory'),
    ('shirt tug', 'cloth_under'), ('showering', 'cloth_accessory'),
    ('skirt caught on object', 'cloth_under'), ('skirt lift', 'cloth_under'),
    ('skull on head', 'cloth_headwear'), ('snoring', 'cloth_accessory'),
    ('staring', 'cloth_accessory'), ('stirring', 'cloth_accessory'),
    ("stroking another's chin", 'ears'), ('sumo', 'species'),
    ('sweater vest lift', 'cloth_under'), ('swimsuit aside', 'cloth_under'),
    ('threat', 'cloth_footwear'), ('triple wielding', 'cloth_dress'),
    ('tying apron', 'cloth_bottom'), ('watching', 'cloth_accessory'),
    ('whispering', 'cloth_accessory'), ('wringing skirt', 'cloth_dress'),
}

DENIED: set[str] = {t for t, _ in DENIED_PAIRS}



@lru_cache(maxsize=1)
def _facts() -> dict:
    try:
        return json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"person": {}, "implications": {}}


@dataclass(frozen=True)
class Requirement:
    axis: str
    label: str
    tag: str = ""          # 구체 태그를 알면 채운다
    sources: tuple[str, ...] = ()
    confidence: float = 0.0

    @property
    def strong(self) -> bool:
        """공식 규칙 또는 사람이 확인한 것이면 강하다. 아니면 두 소스 합의를 본다.

        `adjusting eyewear` 는 공식 규칙에 없고 설명에만 걸리지만 Codex 검증에서
        YES 였다 — 안경 없이 '안경 고쳐쓰기'는 성립하지 않는다. 큐레이션을 소스로
        인정하지 않으면 이런 것이 전부 약한 힌트로 떨어진다.
        """
        return ("official" in self.sources or "confirmed" in self.sources
                or len(self.sources) > 1)


@dataclass
class Advice:
    tag: str
    requires: list[Requirement] = field(default_factory=list)
    specialize: list[str] = field(default_factory=list)   # children
    similar: list[str] = field(default_factory=list)      # siblings

    @property
    def hint_ko(self) -> str:
        if not self.requires:
            return ""
        hard = [r for r in self.requires if r.strong]
        soft = [r for r in self.requires if not r.strong]
        out = []
        if hard:
            out.append(f"이 태그는 {' · '.join(r.label for r in hard)} 이(가) "
                       f"있어야 제대로 나옵니다.")
        if soft:
            out.append(f"{' · '.join(r.label for r in soft)} 을(를) 함께 고르면 "
                       f"더 잘 나옵니다.")
        return " ".join(out)


class TagDependencyIndex:
    def __init__(self, raw: dict, axis_dir: Path | None = None, strict: bool = True):
        self._raw = raw
        self.strict = strict
        self._axis_of: dict[str, str] = {}
        for p in (axis_dir or AXIS_DIR).glob("*.txt"):
            for line in p.read_text(encoding="utf-8").splitlines():
                t = line.strip()
                if t:
                    self._axis_of.setdefault(t, p.stem)
        self._trig = {ax: re.compile(pat) for ax, (_, pat) in AXIS_TRIGGERS.items()}

    # ── 내부 ────────────────────────────────────────────────────────────
    def _meta(self, tag: str) -> dict:
        m = self._raw.get(tag)
        return m if isinstance(m, dict) else {}

    def _rel(self, tag: str, key: str) -> list[str]:
        v = (self._meta(tag).get("relations") or {}).get(key) or []
        return [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)]

    def _desc(self, tag: str) -> str:
        return str(self._meta(tag).get("description") or "")

    def _freq(self, tag: str) -> int:
        return int(self._meta(tag).get("freq", 0) or 0)

    def _from_official(self, tag: str) -> dict[str, tuple[str, float]]:
        """Danbooru tag implications. 부모가 '비보편 축'에 있을 때만 전제로 센다."""
        out: dict[str, tuple[str, float]] = {}
        for r in _facts().get("implications", {}).get(str(tag).strip().lower(), []):
            par = str(r.get("parent", ""))
            ax = self._axis_of.get(par)
            if not ax or ax in UNIVERSAL_AXES:
                continue
            out.setdefault(ax, (par, float(r.get("conf", 0.0))))
        return out

    def _from_parent(self, tag: str) -> dict[str, str]:
        """parent 가 비보편 축의 태그일 때만. 어간 우연은 설명으로 거른다."""
        out: dict[str, str] = {}
        desc = self._desc(tag)
        for p in self._rel(tag, "parent"):
            ax = self._axis_of.get(p)
            if not ax or ax in UNIVERSAL_AXES:
                continue
            pat = self._trig.get(ax)
            # 축 어휘를 아는데 설명에 그 말이 없으면 문자열 우연으로 본다.
            # (undressing -> dress: 설명이 "옷을 벗고 있는 중임" 이라 '드레스'가 없다)
            if pat is not None and not pat.search(desc):
                continue
            out.setdefault(ax, p)
        return out

    def _from_desc(self, tag: str) -> set[str]:
        desc = self._desc(tag)
        return {ax for ax, pat in self._trig.items() if pat.search(desc)}

    # ── 공개 API ────────────────────────────────────────────────────────
    def advise(self, tag: str, limit: int = 8) -> Advice:
        adv = Advice(tag=tag)
        official = self._from_official(tag)
        if tag in DENIED and not official:
            by_parent, by_desc = {}, set()
        else:
            by_parent, by_desc = self._from_parent(tag), self._from_desc(tag)
        forced, weak = CONFIRMED.get(tag), WEAK.get(tag)
        for ax in sorted(set(official) | set(by_parent) | by_desc):
            if (tag, ax) in DENIED_PAIRS and ax not in official:
                continue                       # Codex 가 부정한 쌍 — 공식 규칙만 이긴다
            src = tuple(s for s, ok in (("official", ax in official),
                                        ("confirmed", forced == ax),
                                        ("parent", ax in by_parent),
                                        ("desc", ax in by_desc)) if ok)
            if self.strict and "official" not in src and len(src) < 2                     and forced != ax and weak != ax:
                continue
            label = AXIS_TRIGGERS.get(ax, (ax, ""))[0]
            adv.requires.append(Requirement(
                axis=ax, label=label,
                tag=official.get(ax, ("", 0.0))[0] or by_parent.get(ax, ""),
                sources=src, confidence=official.get(ax, ("", 0.0))[1]))
        # 추천도 문자열 오염이 있다 — `tail` 의 children 에 `ponytail`/`low twintails`
        # (머리 모양)가 들어 있다. 고른 태그가 어떤 축에 속하면 **같은 축**의 것만 낸다.
        own_axis = self._axis_of.get(tag)

        def rank(ts: Iterable[str]) -> list[str]:
            cand = {t for t in ts if t in self._raw and t != tag}
            if own_axis:
                same = {t for t in cand if self._axis_of.get(t) == own_axis}
                cand = same or cand
            return sorted(cand, key=lambda t: -self._freq(t))[:limit]

        adv.specialize = rank(self._rel(tag, "children"))
        adv.similar = rank(self._rel(tag, "siblings"))
        return adv

    def candidates(self, tags: Iterable[str]) -> list[dict]:
        """검증용 후보 목록 — strict 를 무시하고 한 소스라도 걸리면 낸다."""
        rows = []
        for t in tags:
            bp, bd = self._from_parent(t), self._from_desc(t)
            for ax in sorted(set(bp) | bd):
                rows.append({
                    "tag": t, "axis": ax, "label": AXIS_TRIGGERS.get(ax, (ax, ""))[0],
                    "parent_tag": bp.get(ax, ""),
                    "sources": "+".join(s for s, ok in
                                        (("parent", ax in bp), ("desc", ax in bd)) if ok),
                    "freq": self._freq(t), "desc": self._desc(t)[:110],
                })
        return rows


@lru_cache(maxsize=1)
def get_dependency_index() -> TagDependencyIndex:
    from core.kr_tag_loader import load_kr_tag_records
    return TagDependencyIndex(load_kr_tag_records().raw)


def _main(argv: list[str]) -> int:
    import argparse
    import core.interactive_browse_index as ib
    ap = argparse.ArgumentParser(description="태그 전제조건/추천")
    ap.add_argument("--tag", action="append", default=[])
    ap.add_argument("--emit-candidates", metavar="TSV",
                    help="자세 슬롯 후보를 TSV 로 뽑는다(검증용)")
    ap.add_argument("--min-freq", type=int, default=100)
    a = ap.parse_args(argv)

    idx = get_dependency_index()
    for t in a.tag:
        adv = idx.advise(t)
        print(f"[{t}]")
        print(f"  전제: {[(r.label, r.tag, '+'.join(r.sources)) for r in adv.requires] or '없음'}")
        if adv.hint_ko:
            print(f"  힌트: {adv.hint_ko}")
        print(f"  구체화: {adv.specialize[:6]}")
        print(f"  비슷한: {adv.similar[:6]}")
    if a.emit_candidates:
        from core.kr_tag_loader import load_kr_tag_records
        raw = load_kr_tag_records().raw
        bi = ib.InteractiveBrowseIndex(raw)
        pool = set()
        for s in bi.subgroups("pose_action"):
            for it in bi.tags_in("pose_action", s["id"], 0, 5000)["items"]:
                if it["count"] >= a.min_freq:
                    pool.add(it["tag"])
        pool -= set(idx._axis_of)
        rows = idx.candidates(sorted(pool))
        out = Path(a.emit_candidates)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(
            f"{r['tag']}\t{r['axis']}\t{r['label']}\t{r['parent_tag']}\t"
            f"{r['sources']}\t{r['freq']}\t{r['desc']}" for r in rows) + "\n",
            encoding="utf-8")
        both = sum(1 for r in rows if "+" in r["sources"])
        print(f"후보 {len(rows)}행 (두 소스 동의 {both}) -> {out}")
    if not (a.tag or a.emit_candidates):
        ap.print_help()
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
