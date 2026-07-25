"""Interactive 모드 계층 브라우징 인덱스.

Depth1(subgroup) -> Depth2(subgroup 내 태그) -> Depth3(태그의 children) 3단 탐색.
타이핑 없이 카테고리를 훑어 내려가는 용도(Dev0714 TagViewer 3단 구조).

데이터 출처는 자동완성/관계와 동일한 interactive_tags.json 의 병합 레코드(kr_tag_loader).
group/subgroup/freq/relations.children 를 쓴다. group 이 채워진 16,698 태그만 계층에
들어가고, KR 병합분(group 없음)은 브라우징 대상이 아니다(타이핑 자동완성으로만 접근).

세션당 한 번 빌드한다(~60ms). 자동완성처럼 매 요청 순회하지 않는다.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# 슬롯 <-> group. autocomplete_commands.INTERACTIVE_SLOT_GROUPS 와 같은 스킴을 쓴다.
# (여기 두는 이유: 브라우즈는 자동완성과 독립적으로 임포트될 수 있어야 한다.)
SLOT_GROUPS: dict[str, tuple[str, ...]] = {
    "characteristic": ("Person_Body", "Creatures"),
    "clothing": ("Clothing_Wear",),
    "pose_action": ("Expression_Action",),
    "expression": ("Expression_Action",),
    "meta": ("Composition_Meta",),
    "location": ("Location_Background",),
    "object": ("Food_Object",),
}

# 오분류 교정: 원본 taxonomy 가 의상/특징/액션성 태그를 Composition_Meta 에 몰아넣었다
# (Codex 감사 + 실측 검증, 2026-07-24). _build 에서 tag 의 group 을 교체한다.
#
# ⚠️ 키에 반드시 **원본 group** 을 포함한다. subgroup 이름만으로 매칭하면 동명 subgroup
# (예: NSFW/pose 6개)까지 옮겨져 NSFW 가 일반 슬롯으로 누출된다(Codex BLOCKER, 실측 확인).
#
# 동질(homogeneous) subgroup 은 (group, subgroup) 단위로 통째 이동:
SOURCE_SUBGROUP_GROUP_OVERRIDE: dict[tuple[str, str], str] = {
    ("Composition_Meta", "clothing_state"): "Clothing_Wear",   # nude/topless/bottomless -> 의상
    ("Composition_Meta", "pose"): "Expression_Action",         # flower over mouth (Composition_Meta 만)
    ("Composition_Meta", "surreal"): "Person_Body",   # headless/object head 등 6개(Codex 2차)
}

# 혼재(mixed) subgroup(alternate/focus_tags/face_meta)은 **태그 단위**로만 이동한다.
_TAG_OVERRIDE_CLOTHING = [   # alternate* 착의류 -> 의상
    "alternate costume", "costume switch", "alternate legwear", "alternate headwear",
    "alternate hair ornament", "alternate footwear", "alternate neckwear",
]
_TAG_OVERRIDE_PERSON = [     # alternate 헤어/신체 + focus_tags 캐릭터 + face_meta 얼굴 -> 특징
    "alternate hairstyle", "official alternate hairstyle", "alternate hair length",
    "official alternate hair length", "alternate wings", "alternate tail",
    "otoko no ko", "alternate breast size", "faceless", "mature male", "faceless male",
    "mature female", "mini person", "minigirl", "bishounen", "girly boy",
    "forehead mark", "whisker markings", "faceless female", "teardrop facial mark",
    "crescent facial mark", "extra faces", "extra mouth", "hidden face", "glowing mouth",
    "snow on head", "screw in head", "marking on cheek", "heart on cheek", "ink on face",
    "mob face", "bad face", "nose shade", "partially shaded face", "heart cheeks",
]
# Codex 2차 감사(2026-07-24) 고신뢰 213건 — hands/body_parts 포즈->액션, 로봇/나비->특징/Creatures 등.
_HIGH_CONF2_OVERRIDE: dict[tuple[str, str], str] = {
    # Composition_Meta -> Person_Body (14)
    ("Composition_Meta", "disembodied limb"): "Person_Body",
    ("Composition_Meta", "extra arms"): "Person_Body",
    ("Composition_Meta", "disembodied head"): "Person_Body",
    ("Composition_Meta", "multiple heads"): "Person_Body",
    ("Composition_Meta", "extra legs"): "Person_Body",
    ("Composition_Meta", "detached arm"): "Person_Body",
    ("Composition_Meta", "detached legs"): "Person_Body",
    ("Composition_Meta", "extra horns"): "Person_Body",
    ("Composition_Meta", "disembodied torso"): "Person_Body",
    ("Composition_Meta", "fewer digits"): "Person_Body",
    ("Composition_Meta", "extra digits"): "Person_Body",
    ("Composition_Meta", "missing finger"): "Person_Body",
    ("Composition_Meta", "alternate eye color"): "Person_Body",
    ("Composition_Meta", "official alternate eye color"): "Person_Body",
    # Composition_Meta -> Creatures (3)
    ("Composition_Meta", "horse head"): "Creatures",
    ("Composition_Meta", "fish head"): "Creatures",
    ("Composition_Meta", "eldritch abomination"): "Creatures",
    # Composition_Meta -> Location_Background (4)
    ("Composition_Meta", "pink fire"): "Location_Background",
    ("Composition_Meta", "black fire"): "Location_Background",
    ("Composition_Meta", "red fire"): "Location_Background",
    ("Composition_Meta", "white fire"): "Location_Background",
    # Person_Body -> Expression_Action (102)
    ("Person_Body", "hands in pockets"): "Expression_Action",
    ("Person_Body", "heart hands"): "Expression_Action",
    ("Person_Body", "hands on own chest"): "Expression_Action",
    ("Person_Body", "hands on own face"): "Expression_Action",
    ("Person_Body", "own hands clasped"): "Expression_Action",
    ("Person_Body", "hands on own cheeks"): "Expression_Action",
    ("Person_Body", "open hands"): "Expression_Action",
    ("Person_Body", "hands in hair"): "Expression_Action",
    ("Person_Body", "hands on own knees"): "Expression_Action",
    ("Person_Body", "steepled fingers"): "Expression_Action",
    ("Person_Body", "fingers together"): "Expression_Action",
    ("Person_Body", "hands on another's shoulders"): "Expression_Action",
    ("Person_Body", "hands on another's face"): "Expression_Action",
    ("Person_Body", "spread fingers"): "Expression_Action",
    ("Person_Body", "hands on own head"): "Expression_Action",
    ("Person_Body", "hands on own thighs"): "Expression_Action",
    ("Person_Body", "hands on lap"): "Expression_Action",
    ("Person_Body", "hands on headwear"): "Expression_Action",
    ("Person_Body", "hands on another's head"): "Expression_Action",
    ("Person_Body", "heart hands duo"): "Expression_Action",
    ("Person_Body", "index fingers together"): "Expression_Action",
    ("Person_Body", "hands on another's cheeks"): "Expression_Action",
    ("Person_Body", "cupping hands"): "Expression_Action",
    ("Person_Body", "hands on feet"): "Expression_Action",
    ("Person_Body", "hands on own stomach"): "Expression_Action",
    ("Person_Body", "hands on ground"): "Expression_Action",
    ("Person_Body", "hands on another's hips"): "Expression_Action",
    ("Person_Body", "hands on another's thighs"): "Expression_Action",
    ("Person_Body", "index fingers raised"): "Expression_Action",
    ("Person_Body", "hands on another's chest"): "Expression_Action",
    ("Person_Body", "hands on hilt"): "Expression_Action",
    ("Person_Body", "knives between fingers"): "Expression_Action",
    ("Person_Body", "fingersmile"): "Expression_Action",
    ("Person_Body", "fingers to cheeks"): "Expression_Action",
    ("Person_Body", "handshake"): "Expression_Action",
    ("Person_Body", "hands in pocket"): "Expression_Action",
    ("Person_Body", "x fingers"): "Expression_Action",
    ("Person_Body", "fingers to mouth"): "Expression_Action",
    ("Person_Body", "hands on own legs"): "Expression_Action",
    ("Person_Body", "hands on floor"): "Expression_Action",
    ("Person_Body", "peeking through fingers"): "Expression_Action",
    ("Person_Body", "hands on another's back"): "Expression_Action",
    ("Person_Body", "hands on own chin"): "Expression_Action",
    ("Person_Body", "hands on another's stomach"): "Expression_Action",
    ("Person_Body", "hands on another's waist"): "Expression_Action",
    ("Person_Body", "heart hands failure"): "Expression_Action",
    ("Person_Body", "hands on headphones"): "Expression_Action",
    ("Person_Body", "hands on own knee"): "Expression_Action",
    ("Person_Body", "ofuda between fingers"): "Expression_Action",
    ("Person_Body", "hands on thighs"): "Expression_Action",
    ("Person_Body", "snapping fingers"): "Expression_Action",
    ("Person_Body", "hands on legs"): "Expression_Action",
    ("Person_Body", "breathing on hands"): "Expression_Action",
    ("Person_Body", "hands on another's neck"): "Expression_Action",
    ("Person_Body", "hands on another's shoulder"): "Expression_Action",
    ("Person_Body", "hands on another's arms"): "Expression_Action",
    ("Person_Body", "painting nails"): "Expression_Action",
    ("Person_Body", "hands over own mouth"): "Expression_Action",
    ("Person_Body", "looking at hands"): "Expression_Action",
    ("Person_Body", "hands on shoulders"): "Expression_Action",
    ("Person_Body", "hands on another's knees"): "Expression_Action",
    ("Person_Body", "crossed fingers"): "Expression_Action",
    ("Person_Body", "hands on eyewear"): "Expression_Action",
    ("Person_Body", "hands on another's leg"): "Expression_Action",
    ("Person_Body", "warming hands"): "Expression_Action",
    ("Person_Body", "hands on own neck"): "Expression_Action",
    ("Person_Body", "hands on stomach"): "Expression_Action",
    ("Person_Body", "hands under legs"): "Expression_Action",
    ("Person_Body", "washing hands"): "Expression_Action",
    ("Person_Body", "hands on another's arm"): "Expression_Action",
    ("Person_Body", "hands on own shoulders"): "Expression_Action",
    ("Person_Body", "twiddling fingers"): "Expression_Action",
    ("Person_Body", "card between fingers"): "Expression_Action",
    ("Person_Body", "face in hands"): "Expression_Action",
    ("Person_Body", "bugles on fingers"): "Expression_Action",
    ("Person_Body", "hands on another's wrists"): "Expression_Action",
    ("Person_Body", "fingers to cheek"): "Expression_Action",
    ("Person_Body", "clipping nails"): "Expression_Action",
    ("Person_Body", "holding with feet"): "Expression_Action",
    ("Person_Body", "tiptoes"): "Expression_Action",
    ("Person_Body", "soaking feet"): "Expression_Action",
    ("Person_Body", "head back"): "Expression_Action",
    ("Person_Body", "dorsiflexion"): "Expression_Action",
    ("Person_Body", "stomach growling"): "Expression_Action",
    ("Person_Body", "bound thighs"): "Expression_Action",
    ("Person_Body", "outstretched legs"): "Expression_Action",
    ("Person_Body", "hanging legs"): "Expression_Action",
    ("Person_Body", "wiggling toes"): "Expression_Action",
    ("Person_Body", "standing on three legs"): "Expression_Action",
    ("Person_Body", "head on knees"): "Expression_Action",
    ("Person_Body", "bound toes"): "Expression_Action",
    ("Person_Body", "bound feet"): "Expression_Action",
    ("Person_Body", "head on knee"): "Expression_Action",
    ("Person_Body", "licking lips"): "Expression_Action",
    ("Person_Body", "cheek pinching"): "Expression_Action",
    ("Person_Body", "brushing teeth"): "Expression_Action",
    ("Person_Body", "noses touching"): "Expression_Action",
    ("Person_Body", "teeth hold"): "Expression_Action",
    ("Person_Body", "toothbrush in mouth"): "Expression_Action",
    ("Person_Body", "jaw drop"): "Expression_Action",
    ("Person_Body", "biting tongue"): "Expression_Action",
    ("Person_Body", "pill on tongue"): "Expression_Action",
    # Person_Body -> Composition_Meta (1)
    ("Person_Body", "pov hands"): "Composition_Meta",
    # Creatures -> Clothing_Wear (5)
    ("Creatures", "animal around neck"): "Clothing_Wear",
    ("Creatures", "cat hood"): "Clothing_Wear",
    ("Creatures", "rabbit hood"): "Clothing_Wear",
    ("Creatures", "reindeer hood"): "Clothing_Wear",
    ("Creatures", "rabbit earmuffs"): "Clothing_Wear",
    # Creatures -> Expression_Action (17)
    ("Creatures", "bird on hand"): "Expression_Action",
    ("Creatures", "bird on arm"): "Expression_Action",
    ("Creatures", "cat on lap"): "Expression_Action",
    ("Creatures", "pokemon on lap"): "Expression_Action",
    ("Creatures", "pokemon on arm"): "Expression_Action",
    ("Creatures", "animal on head"): "Expression_Action",
    ("Creatures", "animal on shoulder"): "Expression_Action",
    ("Creatures", "animal on back"): "Expression_Action",
    ("Creatures", "bird on head"): "Expression_Action",
    ("Creatures", "bird on shoulder"): "Expression_Action",
    ("Creatures", "cat on head"): "Expression_Action",
    ("Creatures", "cat on shoulder"): "Expression_Action",
    ("Creatures", "crab on head"): "Expression_Action",
    ("Creatures", "dog on head"): "Expression_Action",
    ("Creatures", "crab on shoulder"): "Expression_Action",
    ("Creatures", "tentacle around neck"): "Expression_Action",
    ("Creatures", "snake bite"): "Expression_Action",
    # Creatures -> Food_Object (9)
    ("Creatures", "stuffed cat"): "Food_Object",
    ("Creatures", "stuffed fish"): "Food_Object",
    ("Creatures", "fish skeleton"): "Food_Object",
    ("Creatures", "animal skeleton"): "Food_Object",
    ("Creatures", "insect collection"): "Food_Object",
    ("Creatures", "nest"): "Food_Object",
    ("Creatures", "bird nest"): "Food_Object",
    ("Creatures", "spider web"): "Food_Object",
    ("Creatures", "caterpillar tracks"): "Food_Object",
    # Creatures -> Composition_Meta (2)
    ("Creatures", "too many cats"): "Composition_Meta",
    ("Creatures", "too many birds"): "Composition_Meta",
    # Clothing_Wear -> Person_Body (7)
    ("Clothing_Wear", "black wings"): "Person_Body",
    ("Clothing_Wear", "bodypaint"): "Person_Body",
    ("Clothing_Wear", "facial tattoo"): "Person_Body",
    ("Clothing_Wear", "nose piercing"): "Person_Body",
    ("Clothing_Wear", "nose ring"): "Person_Body",
    ("Clothing_Wear", "mouth piercing"): "Person_Body",
    ("Clothing_Wear", "cheek piercing"): "Person_Body",
    # Clothing_Wear -> Food_Object (2)
    ("Clothing_Wear", "camping chair"): "Food_Object",
    ("Clothing_Wear", "standard manufacturing dp-12"): "Food_Object",
    # Expression_Action -> Person_Body (5)
    ("Expression_Action", "fingerprint"): "Person_Body",
    ("Expression_Action", "finger marks"): "Person_Body",
    ("Expression_Action", "left-handed"): "Person_Body",
    ("Expression_Action", "hand tattoo"): "Person_Body",
    ("Expression_Action", "scar on hand"): "Person_Body",
    # Expression_Action -> Food_Object (2)
    ("Expression_Action", "main battle tank"): "Food_Object",
    ("Expression_Action", "battle standard"): "Food_Object",
    # Location_Background -> Clothing_Wear (1)
    ("Location_Background", "snow on headwear"): "Clothing_Wear",
    # Food_Object -> Person_Body (8)
    ("Food_Object", "android"): "Person_Body",
    ("Food_Object", "single mechanical arm"): "Person_Body",
    ("Food_Object", "cyborg"): "Person_Body",
    ("Food_Object", "robot joints"): "Person_Body",
    ("Food_Object", "mechanical eye"): "Person_Body",
    ("Food_Object", "robot girl"): "Person_Body",
    ("Food_Object", "single mechanical hand"): "Person_Body",
    ("Food_Object", "single mechanical leg"): "Person_Body",
    # Food_Object -> Creatures (16)
    ("Food_Object", "robot"): "Creatures",
    ("Food_Object", "non-humanoid robot"): "Creatures",
    ("Food_Object", "humanoid robot"): "Creatures",
    ("Food_Object", "robot animal"): "Creatures",
    ("Food_Object", "clothed robot"): "Creatures",
    ("Food_Object", "robot dog"): "Creatures",
    ("Food_Object", "robot fish"): "Creatures",
    ("Food_Object", "orange butterfly"): "Creatures",
    ("Food_Object", "transparent butterfly"): "Creatures",
    ("Food_Object", "monarch butterfly"): "Creatures",
    ("Food_Object", "blue butterfly"): "Creatures",
    ("Food_Object", "glowing butterfly"): "Creatures",
    ("Food_Object", "yellow butterfly"): "Creatures",
    ("Food_Object", "purple butterfly"): "Creatures",
    ("Food_Object", "butterflyfish"): "Creatures",
    ("Food_Object", "red butterfly"): "Creatures",
    # Food_Object -> Expression_Action (13)
    ("Food_Object", "knife in head"): "Expression_Action",
    ("Food_Object", "sword between breasts"): "Expression_Action",
    ("Food_Object", "sword in head"): "Expression_Action",
    ("Food_Object", "weapon on back"): "Expression_Action",
    ("Food_Object", "weapon over shoulder"): "Expression_Action",
    ("Food_Object", "sword over shoulder"): "Expression_Action",
    ("Food_Object", "sword on back"): "Expression_Action",
    ("Food_Object", "gun on back"): "Expression_Action",
    ("Food_Object", "gun to head"): "Expression_Action",
    ("Food_Object", "cream on body"): "Expression_Action",
    ("Food_Object", "butterfly on head"): "Expression_Action",
    ("Food_Object", "butterfly on nose"): "Expression_Action",
    ("Food_Object", "butterfly sitting"): "Expression_Action",
    # Food_Object -> Clothing_Wear (2)
    ("Food_Object", "sign around neck"): "Clothing_Wear",
    ("Food_Object", "head flag"): "Clothing_Wear",
}

TAG_GROUP_OVERRIDE: dict[tuple[str, str], str] = {
    **{("Composition_Meta", t): "Clothing_Wear" for t in _TAG_OVERRIDE_CLOTHING},
    **{("Composition_Meta", t): "Person_Body" for t in _TAG_OVERRIDE_PERSON},    **_HIGH_CONF2_OVERRIDE,
}

# subgroup 영문 -> 한글 라벨. 데이터에 한글 subgroup 이 없어 자주 쓰는 것만 손으로 붙인다.
# 없는 subgroup 은 영문 그대로 노출된다(치명적이지 않음).
SUBGROUP_LABELS_KO: dict[str, str] = {
    "attire": "의상", "accessories": "액세서리", "headwear": "모자/머리장식",
    "legwear": "다리", "footwear": "신발", "handwear": "손", "armor": "갑옷",
    "neck_and_neckwear": "목/넥웨어", "hair_accessories": "머리장식",
    "eyewear": "안경/눈", "bra": "브라", "panties": "팬티", "swimwear": "수영복",
    "expression": "표정", "emotion": "감정", "pose": "포즈", "posture": "자세",
    "activity": "활동", "gesture": "제스처", "combat_actions": "전투",
    "interaction": "상호작용", "dances": "춤",
    "hair": "머리카락", "hair_color": "머리색", "hair_styles": "헤어스타일",
    "eyes": "눈", "eyes_tags": "눈", "face": "얼굴", "face_tags": "얼굴",
    "body_type": "체형", "breasts_tags": "가슴", "skin_color": "피부색",
    "ears_tags": "귀", "tail": "꼬리", "wings": "날개", "body_parts": "신체부위",
    "backgrounds": "배경", "locations": "장소", "nature": "자연",
    "time": "시간", "weather": "날씨", "landmark": "랜드마크",
    "composition": "구도", "focus": "포커스", "lighting": "조명",
    "colors": "색상", "count": "인원", "art_style": "화풍",
    "food_tags": "음식", "furniture": "가구", "weapons": "무기",
    "instruments": "악기", "vehicles": "탈것", "tools": "도구", "containers": "용기",
    # --- Codex 조사(2026-07-24)로 확인된 미매핑 subgroup 한글화 ---
    # 구도(Composition_Meta): 실제 구도 태그는 image_composition 에 있고 composition 은 16개뿐 —
    # 라벨은 한글화하되 '구도 승격/재분류'는 [2] 설계에서 별도 처리.
    "image_composition": "화면 구성", "composition": "구도", "framing": "프레이밍",
    "metatags": "메타 태그", "meta": "메타", "symbols": "기호", "effects": "효과",
    "text": "텍스트", "scan": "매체/기법", "focus_tags": "초점 대상",
    "body_meta": "신체 메타", "face_meta": "얼굴 메타", "year_tags": "연도",
    "subjective": "주관적", "alternate": "대체 버전", "clothing_state": "착의 상태",
    "surreal": "초현실", "censoring": "검열", "quality": "품질",
    # 배경(Location_Background)
    "real_world_locations": "실제 장소", "water": "물/수역", "fire": "불/화염", "etc": "기타",
    # 기타/사물(Food_Object)
    "technology": "전자기기", "cards": "카드", "board_games": "보드게임",
    "art_objects": "미술품", "objects": "오브젝트", "medical_equipment": "의료기기",
}


def subgroup_label(subgroup: str) -> str:
    return SUBGROUP_LABELS_KO.get(subgroup, subgroup.replace("_", " "))


class InteractiveBrowseIndex:
    """group -> subgroup -> [tag] 계층 + 태그별 children."""

    def __init__(self, raw: Mapping[str, Any]):
        # group -> subgroup -> list[tag]  (freq 내림차순 정렬 완료)
        self._tree: dict[str, dict[str, list[str]]] = {}
        # tag -> {freq, desc, group, subgroup, children:list}  (슬롯 group 태그만)
        self._meta: dict[str, dict[str, Any]] = {}
        # tag -> group  (**모든** group 보유 태그. slot 밖 group(NSFW 등)도 담아,
        # children 슬롯 필터가 huge dildo(NSFW) 같은 자식을 정확히 판정하게 한다.)
        self._group_lookup: dict[str, str] = {}
        self._build(raw)

    def _build(self, raw: Mapping[str, Any]) -> None:
        wanted: set[str] = set()
        for groups in SLOT_GROUPS.values():
            wanted.update(groups)

        tmp: dict[str, dict[str, list[tuple[int, str]]]] = {}
        for tag, info in raw.items():
            if not isinstance(info, dict):
                continue
            source_group = str(info.get("group", "") or "")
            subgroup = str(info.get("subgroup", "") or "")
            # 오분류 교정 우선순위: 태그 단위 > (원본group, subgroup) 단위 > 원본 group.
            # 원본 group 을 키에 포함해 동명 subgroup(NSFW/pose 등) 오염을 막는다.
            group = TAG_GROUP_OVERRIDE.get(
                (source_group, str(tag).strip().lower()),
                SOURCE_SUBGROUP_GROUP_OVERRIDE.get(
                    (source_group, subgroup.strip().lower()),
                    source_group,
                ),
            )
            if group:
                self._group_lookup[tag] = group   # slot 밖 group 포함
            if group not in wanted or not subgroup:
                continue
            freq = int(info.get("freq", 0) or 0)
            children = _as_list((info.get("relations") or {}).get("children"))
            self._meta[tag] = {
                "freq": freq,
                "desc": str(info.get("description", "") or ""),
                "group": group,
                "subgroup": subgroup,
                "children": children,
            }
            tmp.setdefault(group, {}).setdefault(subgroup, []).append((freq, tag))

        for group, subs in tmp.items():
            self._tree[group] = {}
            for subgroup, entries in subs.items():
                entries.sort(key=lambda item: (-item[0], item[1]))
                self._tree[group][subgroup] = [tag for _, tag in entries]

    # ------------------------------------------------------------------
    # Depth1: subgroup 목록
    # ------------------------------------------------------------------

    def subgroups(
        self,
        slot: str,
        include: Any = None,
        exclude: Any = None,
    ) -> list[dict[str, Any]]:
        """slot 의 subgroup 목록. include/exclude 로 섹션 스코프(구도 vs 효과)를 건다.
        include 가 주어지면 그 집합만, exclude 는 그 집합을 뺀다(둘 다 소문자 비교)."""
        groups = SLOT_GROUPS.get(str(slot or "").strip().lower())
        if not groups:
            return []
        inc = {str(s).strip().lower() for s in include} if include else None
        exc = {str(s).strip().lower() for s in exclude} if exclude else set()
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in groups:
            for subgroup, tags in self._tree.get(group, {}).items():
                if subgroup in seen:
                    continue
                key = str(subgroup).strip().lower()
                if inc is not None and key not in inc:
                    continue
                if key in exc:
                    continue
                seen.add(subgroup)
                rows.append({
                    "id": subgroup,
                    "label": subgroup_label(subgroup),
                    "count": len(tags),
                    "group": group,
                })
        # 태그 많은 subgroup 을 위로(대표 카테고리 우선)
        rows.sort(key=lambda r: (-r["count"], r["id"]))
        return rows

    # ------------------------------------------------------------------
    # Depth2: subgroup 내 태그
    # ------------------------------------------------------------------

    def tags_in(self, slot: str, subgroup: str, offset: int = 0, limit: int = 60) -> dict[str, Any]:
        groups = SLOT_GROUPS.get(str(slot or "").strip().lower()) or ()
        tags: list[str] = []
        for group in groups:
            tags = self._tree.get(group, {}).get(subgroup, [])
            if tags:
                break
        page = tags[offset:offset + limit]
        return {
            "items": [self._row(tag) for tag in page],
            "total": len(tags),
            "hasMore": offset + len(page) < len(tags),
        }

    # ------------------------------------------------------------------
    # Depth3: 태그의 children
    # ------------------------------------------------------------------

    def children_of(self, tag: str, slot: str = "", limit: int = 60) -> dict[str, Any]:
        meta = self._meta.get(tag)
        children = list(meta.get("children") or []) if meta else []

        # 슬롯 스코프. children 은 관계 그래프라 다른 group 이 섞인다 — 예: "hug" 의 children 에
        # "huge ass"(Person_Body), "huge weapon"(Food_Object) 이 들어 있어, expression 슬롯에서
        # 펼치면 엉뚱한 태그가 나온다(Codex BLOCKER). group 이 명시적으로 다른 자식은 버린다.
        # group 을 못 찾는 자식(KR 병합분)은 부모가 이 슬롯이라 통과시킨다.
        groups = set(SLOT_GROUPS.get(str(slot or "").strip().lower(), ()))
        if groups:
            children = [
                t for t in children
                if self._group_lookup.get(t, "") in ("", *groups)
            ]

        children.sort(key=lambda t: (-int((self._meta.get(t) or {}).get("freq", 0) or 0), t))
        page = children[:limit]
        return {
            "items": [self._row(t) for t in page],
            "total": len(children),
            "hasMore": len(children) > limit,
        }

    # ------------------------------------------------------------------

    def _row(self, tag: str) -> dict[str, Any]:
        meta = self._meta.get(tag) or {}
        return {
            "tag": tag,
            "count": int(meta.get("freq", 0) or 0),
            "desc": str(meta.get("desc", "") or ""),
            "hasChildren": bool(meta.get("children")),
        }


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        return [value]
    return []
