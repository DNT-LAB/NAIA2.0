"""In-memory research-only index, built on the first E621 module request.

No shared autocomplete imports, persistence, provider state or corpus I/O.
Exact identities are retained; normalization is only a search projection.
"""
from __future__ import annotations

import re
import heapq
from typing import Any

from core.site_tag_repository import collect_legacy_tags

TAG_NAME, KOREAN_NAME, KOREAN_KEYWORDS, KOREAN_DESCRIPTION, STORED_BODY, TRANSLATED_QUERY = 1, 2, 4, 8, 16, 32
MATCH_FIELDS = ((TAG_NAME, "tag_name"), (KOREAN_NAME, "korean_name"),
                (KOREAN_KEYWORDS, "korean_keywords"), (KOREAN_DESCRIPTION, "korean_description"),
                (STORED_BODY, "stored_body"), (TRANSLATED_QUERY, "translated_query"))
HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")

# ── 색 변형 태그 ──────────────────────────────────────────────────────────────
# '일반 미분류' 를 게시물 수 순으로 보면 상위 300개 중 286개가 pink_nipples · black_penis · white_shirt 같은
# '색 + 부위 · 옷' 이었다(사용자 제보 2026-10-03 "노이즈 같아요"). 그 분류의 목록에서만 치운다 - 검색과 전체 목록에는 남는다.
#
# 색 낱말로 시작한다고 다 색 변형이 아니다(tan_line · golden_shower · black_eye_(injury) · orange_juice · white_house).
# 그래서 **나머지가 같은 태그가 여러 색으로 있을 때만** 색 변형으로 본다:
#   · 색 낱말(들) + 나머지: 그 나머지에 색이 COLOR_FAMILY_MIN 가지 이상(3~4가지면 orange_juice · green_room 이 걸린다).
#   · 명암만 붙은 것(dark_skin · light_fur · pale_body): 그 나머지에 색이 TONE_FAMILY_MIN 가지 이상
#     (light_beam · dark_room · light_truck · dark_magic 은 남는다).
#   · 괄호로 시작하는 나머지(gold_(metal) · lavender_(flower))와 낱말 하나짜리(rainbow · bronze)는 건드리지 않는다.
UNCLASSIFIED_GENERAL = "일반 미분류"
COLOR_FAMILY_MIN = 5
TONE_FAMILY_MIN = 12
COLOR_WORDS = frozenset({
    "black", "white", "grey", "gray", "red", "blue", "green", "yellow", "orange", "purple", "pink", "brown", "tan",
    "teal", "cyan", "magenta", "gold", "golden", "silver", "blonde", "beige", "cream", "turquoise", "violet",
    "lavender", "maroon", "crimson", "indigo", "aqua", "navy", "lime", "amber", "bronze", "copper", "rainbow",
    "multicolored", "monotone", "colored", "ginger", "platinum", "auburn", "scarlet", "olive", "peach", "ivory"})
# 색 앞에 붙는 꾸밈말(light_blue_eyes · glowing_red_eyes). 색 낱말이 뒤따를 때만 색의 일부로 본다.
_COLOR_MODIFIERS = frozenset({"light", "dark", "pale", "bright", "pastel", "neon", "deep", "glowing"})
# 색 없이 명암만으로도 색 변형이 되는 낱말.
_TONE_WORDS = frozenset({"dark", "light", "pale"})
_COLOR_PHRASES = frozenset({("two", "tone"), ("multi", "tone"), ("three", "tone")})
_COLOR_HEADS = COLOR_WORDS | _COLOR_MODIFIERS | {"two", "multi", "three"}


def _split_color(tag: str) -> tuple[str, str, bool] | None:
    """(색 부분, 나머지, 명암만인가). 색으로 시작하지 않으면 None."""
    tokens = tag.split("_")
    index = 0
    while index < len(tokens) and tokens[index] in _COLOR_MODIFIERS:
        index += 1
    start = index
    while index < len(tokens):
        if tokens[index] in COLOR_WORDS:
            index += 1
        elif tuple(tokens[index:index + 2]) in _COLOR_PHRASES:
            index += 2
        elif (tokens[index] == "and" and index > start and index + 1 < len(tokens)
              and tokens[index + 1] in COLOR_WORDS):
            index += 1
        else:
            break
    if index > start:
        return "_".join(tokens[:index]), "_".join(tokens[index:]), False
    if tokens[0] in _TONE_WORDS and len(tokens) > 1:
        return tokens[0], "_".join(tokens[1:]), True
    return None


def color_variant_tags(names) -> set[str]:
    """색만 다른 변형 태그(white_fur · blue_eyes · dark_skin …). 규칙은 위 주석."""
    families: dict[str, dict[str, list[str]]] = {}
    tones: dict[str, list[str]] = {}
    for tag in names:
        if tag.split("_", 1)[0] not in _COLOR_HEADS:
            continue  # 17만 개 중 색 · 명암 낱말로 시작하는 것만 자세히 본다
        parts = _split_color(tag)
        if parts is None:
            continue
        color, rest, tone_only = parts
        if rest.startswith("(") or (not rest and "_" not in tag):
            continue
        if tone_only:
            tones.setdefault(rest, []).append(tag)
        else:
            families.setdefault(rest, {}).setdefault(color, []).append(tag)
    found: set[str] = set()
    for rest, by_color in families.items():
        if len(by_color) >= COLOR_FAMILY_MIN:
            for tags in by_color.values():
                found.update(tags)
    for rest, tags in tones.items():
        if len(families.get(rest, ())) >= TONE_FAMILY_MIN:
            found.update(tags)
    return found


def search_key(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").lower().split())


class E621ResearchIndex:
    def __init__(self, tree: dict, metadata: Any):
        self.metadata = metadata
        self.categories = []
        self.category_rows = {}
        self.folder_rows = {}
        # 색 묶음은 사전 전체에서 센다(분류된 white_fur 도 'fur' 묶음의 한 색이다). 치우는 곳은 '일반 미분류' 뿐이다.
        self.color_variants = color_variant_tags(metadata._native) if UNCLASSIFIED_GENERAL in (tree.get("General") or {}) else set()
        for section in ("General", "Species"):
            section_data = tree.get(section, {})
            if not isinstance(section_data, dict):
                continue
            # Traversal order preserves the first native occurrence on dedup.
            for name, node in section_data.items():
                self.categories.append((section, name, len(node) if isinstance(node, dict) else 0))
                if isinstance(node, dict):
                    rows = []
                    for folder, child in node.items():
                        values = collect_legacy_tags(child)
                        if section == "General" and name == UNCLASSIFIED_GENERAL and self.color_variants:
                            values = [row for row in values if row["tag"] not in self.color_variants]
                        self.folder_rows[(section, name, folder)] = values
                        rows.extend(values)
                else:
                    rows = collect_legacy_tags(node)
                self.category_rows[(section, name)] = rows
        # Metadata already owns the first native row for each exact identity.
        self.by_tag = metadata._native
        if set(tree) <= {"General", "Species"}:
            self.all_rows = list(self.by_tag.values())
        else:
            visible = {}
            for rows in self.category_rows.values():
                for row in rows:
                    visible.setdefault(row["tag"], row)
            self.all_rows = list(visible.values())
        # The first response needs 300 ranks, not a full sorted copy of 172k
        # rows. Later pages use the identical total ordering over this snapshot.
        self.first_page = heapq.nsmallest(300, self.all_rows, key=self.sort_key)
        # 정렬한 목록은 처음 필요할 때 한 번 만들어 둔다 - 이 색인은 스냅숏이라 줄이 바뀌지 않는다.
        # (쪽을 이어 붙이는 화면은 뒤쪽을 자주 청한다. 예전에는 상태가 올 때마다 17만 줄을 다시 정렬했다.)
        self._all_sorted = None
        self._category_sorted = {}
        # The exact-key dictionary is also the name index. Query the retained
        # names directly instead of allocating 172k normalized name copies.
        # Keep references to bodies, not another normalized corpus in memory.
        # Korean fields are small and prepared below; body case conversion is
        # done during a query so opening the module need not copy every wiki.
        self.bodies = {tag: str(self.by_tag[tag].get("wiki_body") or self.by_tag[tag].get("wiki_preview"))
                       for tag in metadata._body_tags if tag in self.by_tag}
        # 한국어 검색 필드는 첫 검색 때 준비한다(_korean_fields). 모듈을 여는 데는 쓰이지 않는데, 이름을 붙인 태그가
        # 6천 → 2만 1천 개로 늘면서 여기서만 첫 열기가 0.55 → 0.70초가 됐다(실측 2026-10-05).
        self._korean = None
        self._query_key = None
        self._matches = None

    def matches(self, query: str, disable_wiki: bool, translated: str = "") -> dict[str, tuple[int, int, int]] | None:
        """Return (field bits, compact-only bits, grade); cache one query only.

        `translated` = the query translated to English. Its matches are only *added*: tags the
        original query already found keep their entry, new ones get TRANSLATED_QUERY and rank
        after every original match (grade + 2). A Korean query that finds nothing falls back to them.
        """
        key = (query, disable_wiki, translated)
        if key == self._query_key:
            return self._matches
        if not query:
            self._query_key, self._matches = key, None
            return None
        matches = self._scan(query, disable_wiki)
        if translated:
            for tag, (bits, compact, grade) in self._scan(translated, disable_wiki).items():
                if tag not in matches:
                    matches[tag] = (bits | TRANSLATED_QUERY, compact, grade + 2)
        self._query_key, self._matches = key, matches
        return matches

    def _scan(self, query: str, disable_wiki: bool) -> dict[str, tuple[int, int, int]]:
        needle = search_key(query)
        compact = needle.replace(" ", "") if HANGUL.search(needle) else None
        pattern = re.compile(re.escape(needle).replace(r"\ ", r"[\s_]+")) if " " in needle else None
        matches = {tag: (TAG_NAME, 0, 0 if needle and needle == search_key(tag) else 1)
                   for tag in self.by_tag if (pattern.search(tag.lower()) if pattern else needle in tag.lower())}
        for tag, fields in self._korean_fields().items():
            bits, compact_bits, direct_bits = 0, 0, 0
            for position, bit in ((0, KOREAN_NAME), (1, KOREAN_NAME), (2, KOREAN_DESCRIPTION), (3, KOREAN_KEYWORDS)):
                if fields[position] and needle in fields[position]:
                    bits |= bit
                    direct_bits |= bit
                elif compact is not None and fields[position + 4] and compact in fields[position + 4]:
                    bits |= bit
                    compact_bits |= bit
            if bits:
                previous = matches.get(tag, (0, 0, 1))
                matches[tag] = (previous[0] | bits, compact_bits & ~direct_bits, previous[2])
        if not disable_wiki:
            # Query whitespace matches runs of native whitespace/underscores.
            # This is equivalent to search_key(body) substring matching, without
            # copying/splitting every long body during module initialization.
            for tag, body in self.bodies.items():
                body = body.lower()
                if (pattern.search(body) if pattern else needle in body):
                    previous = matches.get(tag, (0, 0, 1))
                    matches[tag] = (previous[0] | STORED_BODY, previous[1], previous[2])
        return matches

    def _korean_fields(self):
        if self._korean is None:
            prepared = {}
            for tag in self.metadata.search_field_tags:
                if tag in self.by_tag:
                    normal = tuple(search_key(value) for value in self.metadata.search_fields(tag))
                    prepared[tag] = (*normal, *(value.replace(" ", "") for value in normal))
            self._korean = prepared
        return self._korean

    def filter_rows(self, rows, *, content_filter, hidden, starred, starred_only, matches):
        allowed = self.metadata.content_tags(content_filter)
        without = content_filter == "without_description"
        body, described = self.metadata._body_tags, self.metadata._described
        return [row for row in rows
                if row["tag"] not in hidden
                and (not starred_only or row["tag"] in starred)
                and (allowed is None or row["tag"] in allowed)
                and (not without or (row["tag"] not in body and row["tag"] not in described))
                and (matches is None or row["tag"] in matches)]

    def visible(self, *, category, folder, content_filter, hidden, starred, starred_only, matches):
        if category:
            section = next((section for section in ("General", "Species") if (section, category) in self.category_rows), None)
            key = (section, category, folder or None)
            rows = self._category_sorted.get(key)
            if rows is None:
                rows = (self.folder_rows.get((section, category, folder), []) if folder
                        else self.category_rows.get((section, category), []))
                # Dedup precedes pagination; preserve the first native membership.
                rows = sorted({row["tag"]: row for row in reversed(rows)}.values(), key=self.sort_key)
                self._category_sorted[key] = rows
        elif matches is None and content_filter == "all" and not hidden and not starred_only:
            return self.all_rows
        else:
            rows = self._sorted_all()
        # 거르기는 순서를 지킨다(늘 새 목록을 돌려준다 - 위의 정렬해 둔 목록은 건드리지 않는다).
        rows = self.filter_rows(rows, content_filter=content_filter, hidden=hidden,
                                starred=starred, starred_only=starred_only, matches=matches)
        if matches is not None:
            # 이미 (게시물 수, 이름) 순이다 - 안정 정렬이라 일치 등급만으로 다시 세우면 된다.
            rows.sort(key=lambda row: matches[row["tag"]][2])
        return rows

    @staticmethod
    def sort_key(row):
        return -int(row.get("count") or 0), row["tag"]

    def _sorted_all(self):
        if self._all_sorted is None:
            self._all_sorted = sorted(self.all_rows, key=self.sort_key)
        return self._all_sorted

    def page(self, rows, offset, limit=300):
        if rows is self.all_rows:
            if offset == 0 and limit == 300:
                return self.first_page
            return self._sorted_all()[offset:offset + limit]
        return rows[offset:offset + limit]

    @staticmethod
    def is_translated_match(match) -> bool:
        return bool(match and match[0] & TRANSLATED_QUERY)

    @staticmethod
    def match_payload(match):
        bits, compact, grade = match or (0, 0, None)
        korean = bits & (KOREAN_NAME | KOREAN_KEYWORDS | KOREAN_DESCRIPTION)
        return {"match_grade": grade,
                "match_fields": [name for bit, name in MATCH_FIELDS if bits & bit],
                "match_compact_fields": [name for bit, name in MATCH_FIELDS if compact & bit],
                "matched_in_korean": bool(not bits & TAG_NAME and korean),
                "matched_in_wiki": bool(not bits & TAG_NAME and not korean and bits & STORED_BODY)}
