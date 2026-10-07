"""PyQt-free E621 Event module state for the Remote Web headless runtime."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from core.e621_count_profile import COUNT_TAGS, E621CountProfile
from core.e621_tag_repository import E621TagRepository
from core.e621_relation_repository import E621RelationRepository
from core.e621_research_index import E621ResearchIndex, HANGUL, search_key
from core.prompt_generation_service import PromptGenerationService
from core.e621_prompt_composer import (WEIGHT_LIMITS, display_tag, editable_tag, validate_weight,
    prepare_template, restore_literals)


# 예전 화면의 틀. 지금 화면은 틀을 보이지 않는다 - 상태 · 설정의 자리만 남아 있다.
DEFAULT_TESTBENCH = "{{selected_tags}}"

# ── 테스트 생성의 자동 조립 ──────────────────────────────────────────────────
# 고른 태그 하나로 프롬프트를 조립한다: 주체 → 인원 태그 → 고른 태그 → 관련 태그.
#   · 주체는 1girl - 남성모드를 켜면 1boy(사용자 지정 2026-10-05). 인원 태그는 혼자서는 거의 안 나오는 태그에만
#     붙는다(같은 날: "특이점이 없는 경우에는 1girl 만 넣고 인원 태그를 사용하지 않습니다" - 기준은 core/e621_count_profile.py).
#   · 관련 태그 = 진짜 코어만, 6개 이내(사용자 지정 2026-10-03 · 다시 확인 2026-10-05). 코어 = 고른 태그가 붙은 게시물의
#     40% 이상에 함께 붙는 태그(팩이 이미 우연의 2배 이상만 담는다). 0.25 로 재 보면 feet 에 4_toes, kissing 에
#     male/male 과 male/female 이 함께 올라온다 - 서로 다른 변종이 섞인다. 게시물이 너무 적은 태그는 관측이 흔들린다.
BENCH_SUBJECT = "1girl"
BENCH_SUBJECT_MALE = "1boy"
# 자동 조립의 끝에 늘 붙는 것(사용자 지정 2026-10-07: "e621 특성이므로"). 고른 태그 · 관련 태그와 겹치면 다시 붙이지 않는다.
BENCH_TAIL = ("full_body", "nsfw")
# [퍼리 싫어](사용자 지정 2026-10-07): 생성할 때 네거티브에 2 를, 조립된 프롬프트의 맨 뒤에 -1 을 붙인다.
NO_FURRY_TAGS = "furry, furry female"


def no_furry_pieces(api_mode: str) -> tuple[str, str]:
    """(프롬프트 맨 뒤에 붙일 글, 네거티브에 붙일 글). 가중치는 그 모드의 표기로."""
    if api_mode == "NAI":
        return f"-1::{NO_FURRY_TAGS} ::", f"2::{NO_FURRY_TAGS} ::"
    return f"({NO_FURRY_TAGS}:-1)", f"({NO_FURRY_TAGS}:2)"
AUTO_RELATED_LIMIT = 6
AUTO_RELATED_MIN_SHARE = 0.4
RELATED_MIN_POSTS = 1000
BENCH_PROMPT_LIMIT = 4000
BENCH_ERRORS = {
    "Unbalanced or unsupported numeric weight in E621 template": "가중치 표기(숫자::태그 ::)가 닫히지 않았습니다",
}

# 선택한 태그의 '함께' 줄에서 종(Species 분류 - anthro · feral · humanoid 같은 체형도 여기 든다)은 숨긴다
# (사용자 지정 2026-10-03: 주 대상이 인간이라 종은 가급적 숨김). 그 태그가 그 종에서만 주로 나올 때만 보인다
# (fox_tail → fox, beak → bird).
SPECIES_DEPENDENT_SHARE = 0.6


class E621EventService:
    def __init__(self, app_context: Any):
        self.app_context = app_context
        self.root = Path(getattr(app_context, "repo_root", Path.cwd()))
        runtime_paths = getattr(app_context, "runtime_paths", None)
        save_root = runtime_paths.save_dir if runtime_paths is not None else self.root / "save"
        self.data_path = self.root / "data" / "e621_data"
        data_dir = getattr(runtime_paths, "data_dir", None)
        self.repository = E621TagRepository(self.root, data_roots=[data_dir] if data_dir is not None else None)
        # 관계 팩(별칭 · 포함 · 공동 출현). 만들 때는 안 읽는다 - 처음 태그를 고르거나 고른 태그가 있는 상태를
        # 처음 만들 때 한 번 읽는다(약 0.3초).
        self.relations = E621RelationRepository(self.root, data_roots=[data_dir] if data_dir is not None else None)
        # 태그의 인원 분포(테스트 생성이 인원 태그를 고르는 근거). 이것도 처음 태그를 고를 때 한 번 읽는다.
        self.count_profile = E621CountProfile(self.root, data_roots=[data_dir] if data_dir is not None else None)
        self.save_dir = save_root / "e621_event"
        self.settings_path = save_root / "e621_module_v2_settings.json"
        self.starred_path = save_root / "e621_starred_v2.json"
        self.deleted_path = save_root / "e621_deleted_v2.json"
        self.selected_tags_path = save_root / "e621_selected_tags_v1.json"
        self.selected_tags: list[dict[str, Any]] = []
        # 테스트 생성은 늘 메인 설정(선행 · 후행 프롬프트 · 전처리)을 탄다. 화면의 [메인 설정] 체크는 걷어 냈다
        # (사용자 지정 2026-10-05) - 끄는 길은 명령으로만 남아 있고, 그 값은 저장하지도 되살리지도 않는다
        # (예전 화면이 저장해 둔 '끔' 이 보이지 않는 채로 남아 있으면 안 된다).
        self.use_main_pipeline = True
        # 남성모드: 조립의 주체를 1girl 대신 1boy 로(설정에 저장한다).
        self.male_mode = False
        # 퍼리 싫어: 생성할 때 furry 를 네거티브(2)와 프롬프트 끝(-1)에 붙인다(설정에 저장한다).
        self.no_furry = False
        self._species_tags: set[str] | None = None
        # (검색어, 영어로 번역한 검색어). 한국어 검색어를 번역한 결과로 한 번 더 찾는다 - set_param("search_translation").
        self.search_translation: tuple[str, str] | None = None
        self.data: dict[str, Any] | None = None
        self.research_metadata: Any | None = None
        self.search_text = ""
        self.view_mode = "default"
        self.content_filter = "all"
        self.tag_offset = 0
        self.current_category: str | None = None
        self.current_level2: str | None = None
        self.selected_tag: str | None = None
        self.testbench = DEFAULT_TESTBENCH
        # 고른 태그에 거는 가중치. 태그를 바꿔도 남는다(사용자 지정 2026-10-05) - 켜 있는 동안만이고 저장하지는 않는다.
        self.test_weight = 1.0
        self.disable_translation = False
        self.disable_wiki_search = False
        self.starred_keys: set[str] = set()
        self.deleted_keys: set[str] = set()
        self._settings_loaded = False
        self._search_index: E621ResearchIndex | None = None
        self._index_source = None
        # (무엇으로 셌나, 분류 → 맞은 태그 수). 검색이 걸린 동안 태그를 누를 때마다 17만 줄을 다시 세지 않게 적어 둔다.
        self._category_hits: tuple[Any, dict[tuple[str, str], int]] | None = None

    def state(self) -> dict[str, Any]:
        loaded = self._ensure_loaded()
        visible_tags = self._visible_tags() if loaded else []
        selected = self._find_tag(self.selected_tag) if loaded else None
        matches = self._matches() if loaded else None
        selected_match = (matches.get(self.selected_tag) if matches is not None and
            any(row["tag"] == self.selected_tag for row in visible_tags) else None)
        tag_limit = 300
        self.tag_offset = min(self.tag_offset, max(0, (len(visible_tags) - 1) // tag_limit * tag_limit))
        selected_payload = self._tag_payload(selected, selected_match) if selected else None
        if selected_payload is not None:
            research = self.research_metadata.for_tag(selected_payload["tag"])
            if research.get("korean_body"):
                # 번역 본문도 영어 본문과 같은 방식으로 다듬어 보인다(thumb 번호 · [[링크]] · [b] 표식).
                research["korean_body"] = self._clean_wiki_text(research["korean_body"])
            selected_payload["research"] = research
            selected_payload["relations"] = self._relations_payload(selected_payload["tag"])
        return {
            "type": "module_state",
            "module_id": "e621_event",
            "available": True,
            "runtime": "web",
            "data_loaded": loaded,
            "data_path": str(self.data_path),
            "search_text": self.search_text,
            "search_translation": self._search_translation_payload() if loaded else None,
            "view_mode": self.view_mode,
            "content_filter": self.content_filter,
            "research_summary": self.research_metadata.summary() if loaded else {},
            "disable_translation": self.disable_translation,
            "disable_wiki_search": self.disable_wiki_search,
            "prompt_testbench_visible": True,
            "translation_control_visible": True,
            "wiki_search_control_visible": True,
            "current_category": self.current_category,
            "current_level2": self.current_level2,
            "categories": self._categories() if loaded else [],
            "folders": self._folders() if loaded else [],
            "tags": [self._tag_payload(item, matches.get(item["tag"]) if matches is not None else None)
                     for item in (self._search_index.page(visible_tags, self.tag_offset, tag_limit) if loaded else [])],
            "tag_total": len(visible_tags),
            "tag_limit": tag_limit,
            "tag_offset": self.tag_offset,
            "tag_page_size": tag_limit,
            "has_previous": self.tag_offset > 0,
            "has_next": self.tag_offset + tag_limit < len(visible_tags),
            "starred_total": len(self.starred_keys),
            "hidden_total": len(self.deleted_keys),
            "hidden_items": sorted(self.deleted_keys)[:120],
            "selected": selected_payload,
            "wiki": self._wiki_payload(selected),
            "testbench": self.testbench,
            "bench": self._bench_payload(selected_payload["tag"]) if selected_payload else None,
            "selected_tags": [dict(row) for row in self.selected_tags],
            "use_main_pipeline": self.use_main_pipeline,
            "weight_limits": {mode: dict(limits) for mode, limits in WEIGHT_LIMITS.items()},
        }

    def autocomplete(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        """E621 사전에서만 찾는 자동완성 - 연구모듈의 **검색칸**이 쓴다(사용자 지정 2026-10-05).

        보낼 프롬프트의 자동완성은 공용 사전(메인 프롬프트와 같은 것)이다 - 거기에는 Danbooru 태그도 붙인다.
        줄 모양은 공용 자동완성(autocomplete_result)과 같다: tag = 사람이 읽는 이름 · group = 한국어 이름 · count = E621 게시물 수.
        """
        if not self._ensure_loaded():
            return []
        native = self.research_metadata._native if self.research_metadata else {}
        return [{"tag": display_tag(row["tag"]), "count": int(row.get("count") or 0), "desc": "",
                 "group": "" if self.disable_translation else str((native.get(row["tag"]) or {}).get("kor") or ""),
                 "cat": "e621", "axis": ""}
                for row in self._search_index.suggest(query, limit, self.deleted_keys)]

    # ── 테스트 생성 ───────────────────────────────────────────────────────────
    # 고른 태그 **하나**로 프롬프트를 조립해 보이고, 그 글을 메인 생성으로 보낸다. 태그를 여럿 골라 모으는 조립은 없다
    # (사용자 지정 2026-10-03). 화면에는 조립된 프롬프트만 보인다 - 사용자는 그 글을 직접 고친다(사용자 지정 2026-10-05:
    # "어떤 프롬프트가 자동으로 조립되는지 보여줘야 합니다 · 프롬프트는 사용자가 수정 가능하게" · 틀은 보이지 않는다).
    def _auto_related(self, anchor: str) -> list[str]:
        """고른 태그에 자동으로 붙이는 관련 태그(코어 순 · 6개 이내). 종은 그 종에서만 주로 나올 때 하나만, 맨 뒤에."""
        implied = self.relations.implied(anchor)
        species = self._species()
        anchor_is_species = anchor in species
        rows = []
        for target, _pair, share, lift, count in self.relations.cooccurring(anchor):
            # 고른 태그가 이미 뜻하는 상위 태그(soles → feet)는 자리만 차지한다. 인원 태그는 제 자리가 따로 있다.
            if target in implied or target in COUNT_TAGS or count < RELATED_MIN_POSTS or target in self.deleted_keys:
                continue
            is_species = target in species
            # 종을 직접 골랐으면 종을 더 붙이지 않는다(fox → red_fox 는 원하는 것이 아니다).
            if is_species and (anchor_is_species or share < SPECIES_DEPENDENT_SHARE):
                continue
            if not is_species and share < AUTO_RELATED_MIN_SHARE:
                continue
            rows.append((target, is_species, share * math.log2(lift)))
        # 종은 가장 구체적인 것만: fox 가 있으면 그것이 뜻하는 canine · canid 는 뺀다.
        covered: set[str] = set()
        for target, is_species, _score in rows:
            if is_species:
                covered |= self.relations.implied(target)
        rows = sorted((row for row in rows if row[0] not in covered), key=lambda row: (-row[2], row[0]))
        kind = [row[0] for row in rows if row[1]][:1]
        return [row[0] for row in rows if not row[1]][:AUTO_RELATED_LIMIT - len(kind)] + kind

    def _bench_payload(self, exact_tag: str) -> dict[str, Any]:
        """조립 순서: 주체 → 인원 태그(있을 때만) → 고른 태그(가중치) → 관련 태그 → 늘 붙는 끝(full body, nsfw)."""
        info = self.count_profile.describe(exact_tag)
        count_tag = info["tag"] if info else ""
        related = self._auto_related(exact_tag)
        api_mode = self.app_context.get_api_mode()
        subject = BENCH_SUBJECT_MALE if self.male_mode else BENCH_SUBJECT
        pieces = [(subject, 1.0), *([(count_tag, 1.0)] if count_tag else []), (exact_tag, self.test_weight),
                  *((tag, 1.0) for tag in related)]
        used = {exact_tag, *related}
        pieces += [(tag, 1.0) for tag in BENCH_TAIL if tag not in used]
        return {
            # 화면의 글상자에 들어가는 글이다. 사용자가 고치고, [생성] 은 그 글을 그대로 돌려보낸다.
            "prompt": ", ".join(editable_tag(tag, weight, api_mode) for tag, weight in pieces),
            "weight": self.test_weight, "male": self.male_mode, "no_furry": self.no_furry,
            # count_tag = 붙인 인원 태그('' = 붙이지 않았다) · count_shares = 근거(None = 표에 없는 태그) · related = 붙인 관련 태그.
            "count_tag": count_tag, "count_shares": info["shares"] if info else None, "related": related,
        }

    def _bench_prompt(self) -> str:
        tag = self.selected_tag
        return self._bench_payload(tag)["prompt"] if tag and self._find_tag(tag) is not None else ""

    # ── 관계 팩 → 화면 ────────────────────────────────────────────────────────
    # 응답 계약 = docs/e621_relations_contract.ko.md. 여기서는 화면이 그릴 만큼만 줄인다.
    # 어떤 관계도 프롬프트를 스스로 바꾸지 않는다 - 연구모듈은 고른 태그 하나를 보여 줄 뿐이다
    # (사용자 지정 2026-10-03: 프롬프트 조립은 지원하지 않는다).
    RELATION_LIST_LIMIT = 12

    def _tag_brief(self, exact_tag: str, selected: set[str]) -> dict[str, Any]:
        native = (self.research_metadata._native.get(exact_tag) if self.research_metadata else None) or {}
        return {"tag": exact_tag, "display": display_tag(exact_tag), "kor": str(native.get("kor") or ""),
                "count": int(native.get("count") or 0), "in_selection": exact_tag in selected}

    def _species(self) -> set[str]:
        if self._species_tags is None:
            index = self._search_index
            self._species_tags = {row["tag"] for (section, _name), rows in index.category_rows.items()
                                  if section == "Species" for row in rows} if index is not None else set()
        return self._species_tags

    def _relations_payload(self, exact_tag: str) -> dict[str, Any]:
        try:
            related = self.relations.related(exact_tag)
        except ValueError:
            return {"status": "invalid"}
        groups = related.get("groups") or {}
        selected = {row["exact_tag"] for row in self.selected_tags}

        def other(row: dict[str, Any]) -> str:
            # 계약상 incoming 이어도 source/target 은 원래 방향 그대로다 - 질의 태그가 아닌 쪽을 고른다.
            source, target = row["source"]["exact_tag"], row["target"]["exact_tag"]
            return target if source == exact_tag else source

        def ranked(tags: list[str]) -> list[dict[str, Any]]:
            # 하위(이 태그를 포함하는 태그)는 수천 개일 수 있다 - 게시물 수 순으로 앞만 싣고 전체 수는 따로 준다.
            briefs = [self._tag_brief(tag, selected) for tag in dict.fromkeys(tags) if tag not in self.deleted_keys]
            briefs.sort(key=lambda row: (-row["count"], row["tag"]))
            return briefs[:self.RELATION_LIST_LIMIT]

        implications = groups.get("implications") or []
        broader = [other(row) for row in implications if row.get("direction") == "outgoing"]
        narrower = [other(row) for row in implications if row.get("direction") == "incoming"]
        # '함께' = 팩에 든 순서 그대로(함께 붙은 수 × 특이도). 종은 의존할 때만 보인다.
        species = self._species()
        anchor_is_species = exact_tag in species
        cooccurrences = []
        shown_species = []
        for target, pair, share, lift, _count in self.relations.cooccurring(exact_tag):
            if target in self.deleted_keys:
                continue
            if target in species:
                if anchor_is_species or share < SPECIES_DEPENDENT_SHARE:
                    continue
                shown_species.append(target)
            cooccurrences.append({**self._tag_brief(target, selected), "pair_count": int(pair),
                                  "share": round(share, 3), "lift": round(lift, 2)})
        if len(shown_species) > 1:
            # 종은 가장 구체적인 것만: fox 가 보이면 그것이 뜻하는 canine · canid 는 같은 말의 되풀이다.
            covered = set().union(*(self.relations.implied(tag) for tag in shown_species))
            cooccurrences = [row for row in cooccurrences if row["tag"] not in covered]
        return {
            "status": related.get("status"),
            "snapshot": (related.get("observations") or {}).get("snapshot"),
            "broader": ranked(broader), "broader_total": len(set(broader)),
            "narrower": ranked(narrower), "narrower_total": len(set(narrower)),
            "aliases": [{"from": row["source"]["exact_tag"], "to": row["target"]["exact_tag"]}
                        for row in groups.get("aliases") or []],
            "cooccurrences": cooccurrences,
        }

    # ── 번역한 검색어 ─────────────────────────────────────────────────────────
    # 한국어 이름 · 검색어가 달린 태그는 17만 개 중 6,700개쯤이다 - 한국어로 치면 못 찾는 일이 많다.
    # 그래서 검색어를 영어로 번역해 한 번 더 찾고, 그 결과를 원래 결과 **뒤에** 보탠다(사용자 지정 2026-10-03).
    # 번역은 네트워크라 이 서비스가 하지 않는다 - 화면이 search_translate 로 청하면 명령 처리부(module_commands)가
    # 뒤에서 번역해 search_translation 으로 넣는다.
    def _translated_query(self) -> str:
        pending = self.search_translation
        return pending[1] if pending and pending[0] == self.search_text else ""

    def _matches(self):
        return self._search_index.matches(self.search_text, self.disable_wiki_search, self._translated_query())

    def _search_translation_payload(self) -> dict[str, Any] | None:
        translated = self._translated_query()
        if not translated:
            return None
        matches = self._matches() or {}
        return {"query": self.search_text, "translated": translated,
                "added": sum(1 for tag in matches if E621ResearchIndex.is_translated_match(matches[tag]))}

    def set_param(self, key: str, value: Any) -> dict[str, Any] | list[dict[str, Any]]:
        self._ensure_loaded()
        raw = str(value or "")
        if key == "search":
            self.search_text = raw.strip().lower()
            self.search_translation = None
            self.current_category = None
            self.current_level2 = None
            self.selected_tag = None
            self.tag_offset = 0
        elif key == "search_cancel":
            # 검색만 푼다 - 고른 분류 · 폴더 · 보기 · 필터는 그대로 둔다(전부 되돌리는 것은 reset).
            self.search_text = ""
            self.search_translation = None
            self.tag_offset = 0
        elif key == "search_translation":
            # 그사이 검색어가 바뀌었으면 버린다. 번역이 원문과 같거나 한글이 남아 있으면 쓸 값이 아니다.
            payload = value if isinstance(value, dict) else {}
            query = str(payload.get("query") or "").strip().lower()
            translated = search_key(payload.get("translated"))
            if (query and query == self.search_text and translated and translated != search_key(query)
                    and not HANGUL.search(translated)):
                self.search_translation = (query, translated)
                self.tag_offset = 0
        elif key == "reset":
            self.search_text = ""
            self.search_translation = None
            self.current_category = None
            self.current_level2 = None
            self.selected_tag = None
            self.view_mode = "default"
            self.content_filter = "all"
            self.tag_offset = 0
        elif key == "view_mode":
            self.view_mode = "starred" if raw == "starred" else "default"
            self.tag_offset = 0
        elif key == "content_filter":
            self.content_filter = raw if raw in {"with_body", "with_korean", "with_korean_search", "without_description"} else "all"
            self.selected_tag = None
            self.tag_offset = 0
        elif key == "tag_offset":
            try:
                self.tag_offset = max(0, int(raw)) // 300 * 300
            except (TypeError, ValueError):
                self.tag_offset = 0
        elif key == "category":
            self.current_category = raw or None
            self.current_level2 = None
            self.selected_tag = None
            self.tag_offset = 0
        elif key == "level2":
            self.current_level2 = raw or None
            self.selected_tag = None
            self.tag_offset = 0
        elif key == "selected_tag":
            self.selected_tag = raw or None
        elif key == "toggle_star":
            tag = raw.strip()
            if tag:
                if tag in self.starred_keys:
                    self.starred_keys.discard(tag)
                else:
                    self.starred_keys.add(tag)
                self.selected_tag = tag
                self._save_set(self.starred_path, self.starred_keys)
        elif key == "hide":
            tag = raw.strip()
            if tag:
                self.deleted_keys.add(tag)
                self.selected_tag = None
                self._save_set(self.deleted_path, self.deleted_keys)
        elif key == "restore":
            tag = raw.strip()
            if tag:
                self.deleted_keys.discard(tag)
                self._save_set(self.deleted_path, self.deleted_keys)
        elif key == "disable_translation":
            self.disable_translation = self._coerce_bool(raw)
            self._save_settings()
        elif key == "disable_wiki_search":
            self.disable_wiki_search = self._coerce_bool(raw)
            self.tag_offset = 0
            self._save_settings()
        elif key.startswith("selected_tags_"):
            try:
                self._edit_selected_tags(key, value)
            except (ValueError, OSError) as exc:
                return self._toast(str(exc), level="error")
        elif key == "use_main_pipeline":
            self.use_main_pipeline = self._coerce_bool(value)
        elif key == "male_mode":
            self.male_mode = self._coerce_bool(value)
            self._save_settings()
        elif key == "no_furry":
            self.no_furry = self._coerce_bool(value)
            self._save_settings()
        elif key == "testbench":
            self.testbench = raw
            self._save_settings()
        elif key == "test_weight":
            try:
                self.test_weight = validate_weight(value, self.app_context.get_api_mode())
            except ValueError as exc:
                return self._toast(str(exc), level="error")
        elif key == "generate":
            # 화면의 글상자에 있는 글을 그대로 보낸다(사용자가 고쳤을 수 있다). 비어 있으면 지금 고른 태그의 자동 조립.
            # 고른 태그는 그 글 안에 이미 있다 - 조립기에 따로 얹지 않는다. 화면에서 걷어 낸 예전의 여러 태그 모음
            # (selected_tags)의 저장분도 얹지 않는다 - 보이지 않는 채로 프롬프트에 섞이면 안 된다.
            # (태그 이름이 와일드카드 · 가중치 표기와 겹치는 것은 사전 17만 개 중 15개다 - $ · <:3 · ::3 따위.)
            template = (raw if raw.strip() else self._bench_prompt())[:BENCH_PROMPT_LIMIT]
            try:
                from core.headless_random_prompt_service import pipeline_swap_lock
                with pipeline_swap_lock(self.app_context):
                    expand, template_context = self._template_expander() if self.use_main_pipeline else (None, None)
                    tags, protected = prepare_template(template, [], self.app_context.get_api_mode(), expand=expand)
                    if not tags:
                        return self._toast("보낼 프롬프트가 비어 있습니다", level="error")
                    generated = self._generate_prompt(tags) if self.use_main_pipeline else ", ".join(tags)
                    generated = restore_literals(generated, protected)
                    if not generated:
                        raise ValueError("E621 generated prompt is empty")
                    # [퍼리 싫어]: 다 만들어진 프롬프트의 맨 뒤에 붙인다(고친 글 · 메인 설정의 접미 뒤). 네거티브 쪽은 아래 메시지로 간다.
                    furry_prompt, furry_negative = no_furry_pieces(self.app_context.get_api_mode()) if self.no_furry else ("", "")
                    if furry_prompt:
                        generated = f"{generated}, {furry_prompt}"
                    if template_context is not None and template_context.wildcard_history:
                        # Template rolls are frozen when the E621 prompt is prepared.
                        # Commit only after successful composition, under the same
                        # pipeline lock. Preserve the live source and unrelated state.
                        current = getattr(self.app_context, "current_prompt_context", None)
                        if current is None:
                            self.app_context.current_prompt_context = template_context
                        else:
                            current.sequential_counters.update(template_context.sequential_counters)
                            current.wildcard_state.update(template_context.wildcard_state)
                            for name, history in template_context.wildcard_history.items():
                                current.wildcard_history.setdefault(name, []).extend(history)
                            current.wildcard_rolls.extend(template_context.wildcard_rolls)
            except ValueError as exc:
                return self._toast(BENCH_ERRORS.get(str(exc), str(exc)), level="error")
            # ⚠️ 메인 프롬프트(app_context.prompt_text)는 건드리지 않는다. 예전에는 여기서 만든 프롬프트로 덮어썼는데,
            #    화면은 이 출처의 프롬프트를 메인 칸에 받지 않아서 서버와 화면이 갈라졌다 - 새로고침하면 쓰던 메인
            #    프롬프트가 테스트 프롬프트로 바뀌어 있었다(실측 2026-10-05). 생성에는 아래 메시지의 prompt 가 그대로 간다.
            return [
                {
                    "type": "prompt_generated",
                    "source": "e621_event",
                    "use_main_pipeline": self.use_main_pipeline,
                    "prompt": generated,
                    # 이 생성에만 네거티브 뒤에 덧붙일 글('' = 없음). 메인 네거티브는 건드리지 않는다.
                    "negative_append": furry_negative,
                    "remaining": self.app_context.search_results.get_count()
                    if getattr(self.app_context, "search_results", None) is not None
                    else 0,
                    "rating_counts": self.app_context.search_state_payload().get("rating_counts", {}),
                },
                self._toast("테스트 생성을 넣었습니다", level="success"),
                self.state(),
            ]
        else:
            return self._toast(f"E621 action is not supported in this runtime: {key}", level="info")
        return self.state()

    def _ensure_loaded(self) -> bool:
        if not self._settings_loaded:
            self._load_settings()
        if self.data is None:
            if not self.repository.load():
                return False
            self.data = self.repository.dictionary.legacy_tree
            self.data_path = self.repository.source_path
            self.research_metadata = self.repository.translations.legacy_metadata
        if self.research_metadata is None:
            self._load_research_metadata()
        if self._search_index is None or self._index_source is not self.data:
            self._search_index = E621ResearchIndex(self.data, self.research_metadata)
            self._index_source = self.data
        return True

    def _load_research_metadata(self) -> None:
        from core.e621_research_metadata import E621ResearchMetadata

        runtime_paths = getattr(self.app_context, "runtime_paths", None)
        data_dir = getattr(runtime_paths, "data_dir", None)
        self.research_metadata = E621ResearchMetadata(
            self.root, self._collect_tags(self.data), data_roots=[data_dir] if data_dir is not None else None,
        )

    def _load_settings(self) -> None:
        self._settings_loaded = True
        self.starred_keys = self._load_set(self.starred_path, self.save_dir / "starred.json")
        self.deleted_keys = self._load_set(self.deleted_path, self.save_dir / "deleted.json")
        try:
            settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}
        if isinstance(settings, dict):
            self.disable_translation = self._coerce_bool(settings.get("disable_translation", False))
            self.disable_wiki_search = self._coerce_bool(settings.get("disable_wiki_search", False))
            self.male_mode = self._coerce_bool(settings.get("male_mode", False))
            self.no_furry = self._coerce_bool(settings.get("no_furry", False))
            self.testbench = str(settings.get("testbench", DEFAULT_TESTBENCH))
        try:
            saved = json.loads(self.selected_tags_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = []
        seen = set()
        for row in saved if isinstance(saved, list) else []:
            if not isinstance(row, dict) or row.get("site") != "e621":
                continue
            exact = row.get("exact_tag")
            if not isinstance(exact, str) or not exact or exact in seen:
                continue
            try:
                weight = validate_weight(row.get("weight", 1.0))
            except ValueError:
                continue
            self.selected_tags.append({"site": "e621", "exact_tag": exact,
                "display": display_tag(exact), "kor": str(row.get("kor") or ""), "weight": weight})
            seen.add(exact)

    def _save_settings(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(
                {
                    "disable_translation": self.disable_translation,
                    "disable_wiki_search": self.disable_wiki_search,
                    "male_mode": self.male_mode,
                    "no_furry": self.no_furry,
                    "testbench": self.testbench,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _edit_selected_tags(self, key: str, value: Any) -> None:
        rows = [dict(row) for row in self.selected_tags]
        payload = value if isinstance(value, dict) else {"exact_tag": value}
        if payload.get("site", "e621") != "e621":
            raise ValueError("site must be e621")
        exact = payload.get("exact_tag")
        index = next((i for i, row in enumerate(rows) if row["exact_tag"] == exact), None)
        if key == "selected_tags_clear":
            rows = []
        elif key == "selected_tags_add":
            if not isinstance(exact, str) or self._find_tag(exact) is None:
                raise ValueError("Unknown exact_tag in E621 dictionary")
            if index is None:
                row = self._tag_payload(self._find_tag(exact))
                rows.append({"site": "e621", "exact_tag": exact, "display": display_tag(exact),
                    "kor": row["kor"], "weight": validate_weight(payload.get("weight", 1.0), self.app_context.get_api_mode())})
        elif key == "selected_tags_remove":
            if index is not None:
                rows.pop(index)
        elif key in {"selected_tags_weight", "selected_tags_move"}:
            if index is None:
                raise ValueError("exact_tag is not selected")
            if key == "selected_tags_weight":
                rows[index]["weight"] = validate_weight(payload.get("weight"), self.app_context.get_api_mode())
            else:
                target = payload.get("index")
                if isinstance(target, bool) or not isinstance(target, int) or not 0 <= target < len(rows):
                    raise ValueError("index must be a zero-based selected tag position")
                rows.insert(target, rows.pop(index))
        else:
            raise ValueError(f"Unknown E621 selection command: {key}")
        self.selected_tags_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.selected_tags_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.selected_tags_path)
        self.selected_tags = rows

    def _categories(self) -> list[dict[str, Any]]:
        index = self._search_index
        matches = self._matches() if self.search_text else None
        # 검색 중에는 분류마다 맞은 태그 수를 센다(화면이 그 줄을 밝히고 수를 적는다 - 사용자 지정 2026-10-05).
        # 같은 검색 · 같은 거름 조건이면 한 번만 센다.
        hits_key = None if matches is None else (
            index._query_key, self.content_filter, self.view_mode, frozenset(self.deleted_keys),
            frozenset(self.starred_keys) if self.view_mode == "starred" else None)
        cached = self._category_hits[1] if self._category_hits and self._category_hits[0] == hits_key else None
        hits: dict[tuple[str, str], int] = {}
        categories = []
        for section, name, folder_count in sorted(index.categories):
            rows = index.category_rows[(section, name)]
            visible = rows if self.content_filter == "all" and not self.deleted_keys else index.filter_rows(
                rows, content_filter=self.content_filter, hidden=self.deleted_keys,
                starred=self.starred_keys, starred_only=False, matches=None)
            if matches is None:
                match_count = 0
            elif cached is not None:
                match_count = cached[(section, name)]
            else:
                # 한 태그가 그 분류의 여러 폴더에 들 수 있다 - 목록처럼 태그 하나로 센다.
                match_count = len({row["tag"] for row in visible if row["tag"] in matches and
                                   (self.view_mode != "starred" or row["tag"] in self.starred_keys)})
            hits[(section, name)] = match_count
            categories.append({
                "name": name, "section": section, "folder_count": folder_count,
                "tag_count": len(visible),
                "starred_count": sum(row["tag"] in self.starred_keys for row in visible) if self.starred_keys else 0,
                "matched": bool(match_count), "match_count": match_count,
                "selected": name == self.current_category,
            })
        self._category_hits = (hits_key, hits) if matches is not None else None
        return categories

    def _folders(self) -> list[dict[str, Any]]:
        if not self.current_category:
            return []
        index = self._search_index
        section, node = self._category_data(self.current_category)
        if not isinstance(node, dict):
            return []
        matches = self._matches()
        folders = []
        for name in sorted(node):
            rows = index.filter_rows(index.folder_rows.get((section, self.current_category, name), []),
                content_filter=self.content_filter, hidden=self.deleted_keys,
                starred=self.starred_keys, starred_only=self.view_mode == "starred", matches=matches)
            if rows:
                folders.append({"name": name, "display": name.replace("_", " "),
                                "tag_count": len(rows), "selected": name == self.current_level2})
        return folders

    def _visible_tags(self) -> list[dict[str, Any]]:
        index = self._search_index
        return index.visible(category=self.current_category, folder=self.current_level2,
            content_filter=self.content_filter, hidden=self.deleted_keys,
            starred=self.starred_keys, starred_only=self.view_mode == "starred",
            matches=self._matches())

    @staticmethod
    def _search_key(value: Any) -> str:
        """Keep the established underscore/space search projection."""
        return search_key(value)

    def _filter_tags(self, tags: list[dict[str, Any]], *, include_search: bool = True) -> list[dict[str, Any]]:
        index = self._search_index
        matches = self._matches() if include_search else None
        rows = index.filter_rows(tags, content_filter=self.content_filter, hidden=self.deleted_keys,
                                 starred=self.starred_keys, starred_only=self.view_mode == "starred", matches=matches)
        if matches is not None:
            return [dict(row, **index.match_payload(matches[row["tag"]])) for row in rows]
        return rows

    def _matches_content_filter(self, tag: dict[str, Any]) -> bool:
        if self.content_filter == "all":
            return True
        metadata = self.research_metadata
        name = str(tag.get("tag") or "")
        allowed = metadata.content_tags(self.content_filter)
        if allowed is not None:
            return name in allowed
        return name not in metadata._body_tags and name not in metadata._described

    def _category_data(self, category: str) -> tuple[str | None, Any]:
        data = self.data or {}
        for section in ("General", "Species"):
            section_data = data.get(section, {})
            if isinstance(section_data, dict) and category in section_data:
                return section, section_data.get(category)
        return None, None

    def _find_tag(self, tag_name: str | None) -> dict[str, Any] | None:
        return self._search_index.by_tag.get(tag_name) if tag_name and self._search_index is not None else None

    def _tag_payload(self, tag_data: dict[str, Any], match=None) -> dict[str, Any]:
        tag_name = str(tag_data.get("tag") or "")
        count = int(tag_data.get("count") or 0)
        research = self.research_metadata.for_tag(tag_name, include_body=False) if self.research_metadata else {}
        return {
            "tag": tag_name,
            "display": tag_name.replace("_", " "),
            "kor": tag_data.get("kor") or research.get("korean_label", ""),
            "count": count,
            "count_label": self._format_count(count),
            "starred": tag_name in self.starred_keys,
            "hidden": tag_name in self.deleted_keys,
            **E621ResearchIndex.match_payload(match),
            "has_body": bool(research.get("has_body")),
            "has_korean_description": bool(research.get("has_korean_description")),
            "has_korean_body": bool(research.get("has_korean_body")),
            "has_korean_search": bool(research.get("has_korean_search")),
            "review_status": research.get("review_status", "unreviewed"),
            "review_label": research.get("review_label", "미검토"),
        }

    def _wiki_payload(self, tag_data: dict[str, Any] | None) -> dict[str, Any]:
        if not tag_data:
            return {"tag": "", "text": "", "body": "", "translated": False}
        tag_name = str(tag_data.get("tag") or "")
        body = str(tag_data.get("wiki_body") or tag_data.get("wiki_preview") or "")
        body = self._clean_wiki_text(body)
        return {
            "tag": tag_name,
            "text": f"Tag: {tag_name.replace('_', ' ')}\nCount: {self._format_count(tag_data.get('count'))}\n\n{'=' * 50}\n\n{body or '위키 정보 없음'}",
            "body": body,
            "source_label": "저장된 위키 본문",
            "translated": False,
        }

    def _generate_prompt(self, tags: list[str]) -> str:
        source = {
            "id": 10000000,
            "artist": [],
            "copyright": [],
            "character": [],
            "general": tags,
            "meta": [],
        }
        settings = {
            "api_mode": self.app_context.get_api_mode(),
            "auto_generate": False,
            "prompt_fixed": False,
            "wildcard_standalone": False,
            "random_prompt_weight": 1.0,
            "e621_explicit_tags": True,
        }
        from core.headless_random_prompt_service import pipeline_swap_lock

        service = getattr(self.app_context, "prompt_generation_service", None)
        if service is None:
            service = PromptGenerationService(self.app_context)
            self.app_context.prompt_generation_service = service
        with pipeline_swap_lock(self.app_context):
            result = service.generate_instant_source_result_silent(source, settings)
        if result.error or not result.final_prompt:
            raise ValueError(result.error or "E621 main prompt pipeline failed")
        return result.final_prompt

    def _template_expander(self):
        """Use the existing wildcard/preset engines before wrapping explicit weights."""
        import copy
        import pandas as pd
        from core.prompt_context import PromptContext
        from core.wildcard_processor import WildcardProcessor, split_tags_smart
        from core.wildcard_runtime import ensure_wildcard_manager

        context = PromptContext(source_row=pd.Series(dtype=object), settings={"api_mode": self.app_context.get_api_mode()})
        current = getattr(self.app_context, "current_prompt_context", None)
        if current is not None:
            context.sequential_counters = copy.deepcopy(current.sequential_counters)
            context.wildcard_state = copy.deepcopy(current.wildcard_state)
        processor = WildcardProcessor(ensure_wildcard_manager(self.app_context))

        def expand(tag):
            tags = processor.expand_tags([tag], context, location="main")
            if any(str(item).lower().startswith("preset:") for item in tags):
                service = getattr(self.app_context, "prompt_generation_service", None)
                if service is None:
                    service = PromptGenerationService(self.app_context)
                    self.app_context.prompt_generation_service = service
                tags = service.processor.expand_preset_tokens(tags, context)
            tags.extend(context.global_append_tags)
            context.global_append_tags.clear()
            result = [piece.strip() for item in tags for piece in split_tags_smart(item) if piece.strip()]
            if any("__" in piece for piece in result):
                raise ValueError("An E621 template wildcard could not be resolved")
            return result
        return expand, context

    def _collect_tags(self, data: Any) -> list[dict[str, Any]]:
        tags: list[dict[str, Any]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("tag"):
                    tags.append(item)
                elif isinstance(item, (list, dict)):
                    tags.extend(self._collect_tags(item))
        elif isinstance(data, dict):
            if data.get("tag"):
                tags.append(data)
            else:
                for value in data.values():
                    tags.extend(self._collect_tags(value))
        return tags

    def _toast(self, message: str, *, level: str = "info") -> dict[str, Any]:
        return {"type": "toast", "message": message, "level": level, "runtime": "web"}

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _format_count(value: Any) -> str:
        try:
            number = int(value or 0)
        except Exception:
            number = 0
        if number >= 1_000_000:
            return f"{number / 1_000_000:.1f}M"
        if number >= 1_000:
            return f"{number / 1_000:.1f}K"
        return str(number)

    @staticmethod
    def _clean_wiki_text(text: str) -> str:
        cleaned = re.sub(r"thumb\s+#\d+", "", str(text or ""))
        cleaned = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", cleaned)
        cleaned = re.sub(r"\[\[([^\]]+)\]\]", r"\1", cleaned)
        cleaned = re.sub(r"\[/?[a-z0-9]+\]", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    @staticmethod
    def _load_set(*paths: Path) -> set[str]:
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, list):
                return {str(item) for item in payload if str(item)}
            if isinstance(payload, dict):
                values = (
                    payload.get("starred_keys")
                    or payload.get("deleted_keys")
                    or payload.get("items")
                    or payload.get("tags")
                    or payload.get("values")
                )
                if isinstance(values, list):
                    return {str(item) for item in values if str(item)}
                return {str(key) for key, enabled in payload.items() if enabled}
        return set()

    @staticmethod
    def _save_set(path: Path, values: set[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if "starred" in path.name:
            payload: Any = {"starred_keys": sorted(values)}
        elif "deleted" in path.name:
            payload = {"deleted_keys": sorted(values)}
        else:
            payload = sorted(values)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
