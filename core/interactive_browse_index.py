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
            group = str(info.get("group", "") or "")
            subgroup = str(info.get("subgroup", "") or "")
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

    def subgroups(self, slot: str) -> list[dict[str, Any]]:
        groups = SLOT_GROUPS.get(str(slot or "").strip().lower())
        if not groups:
            return []
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in groups:
            for subgroup, tags in self._tree.get(group, {}).items():
                if subgroup in seen:
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
