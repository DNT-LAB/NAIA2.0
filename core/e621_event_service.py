"""PyQt-free E621 Event module state for the Remote Web headless runtime."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from core.e621_tag_repository import E621TagRepository
from core.e621_relation_repository import E621RelationRepository
from core.e621_research_index import E621ResearchIndex, search_key
from core.prompt_generation_service import PromptGenerationService
from core.e621_prompt_composer import (WEIGHT_LIMITS, display_tag, validate_weight,
    prepare_template, restore_literals)


DEFAULT_TESTBENCH = "{{selected_tags}}"

# ── 관련 태그 자동 조립(사용자 지정 2026-10-03: "진짜 코어만 · 6개 이내", "종은 가급적 숨김") ──
# 코어 = 고른 태그가 붙은 게시물의 AUTO_RELATED_MIN_SHARE 이상에 함께 붙는 태그(팩이 이미 우연의 2배 이상만 담는다).
# 0.25 로 재 보면 feet 에 4_toes, kissing 에 male/male 과 male/female 이 함께 올라온다 - 서로 다른 변종이 섞인다.
AUTO_RELATED_DEFAULT_LIMIT = 6
AUTO_RELATED_MAX_LIMIT = 12
AUTO_RELATED_MIN_SHARE = 0.4
# 자동을 끄고 손으로 고를 때의 '함께' 추천은 더 넓게 보인다.
SUGGEST_MIN_SHARE = 0.1
SUGGEST_LIMIT = 16
# 게시물이 너무 적은 태그는 관측이 흔들린다.
RELATED_MIN_POSTS = 1000
# 종(Species 분류 - anthro · feral · humanoid 같은 체형도 여기 든다)은 숨긴다. 고른 태그가 그 종에서만 주로
# 나올 때(fox_tail → fox, beak → bird)만 가장 구체적인 종 하나를 담는다.
SPECIES_DEPENDENT_SHARE = 0.6
AUTO_RELATED_EXCLUDED_MAX = 200

# 미리보기에 그대로 보이는 조립 오류 - 화면 문구로 바꾼다([생성] 의 알림은 원문 그대로 둔다).
PREVIEW_ERRORS = {
    "Use {{selected_tags}} at most once": "{{selected_tags}} 는 한 번만 쓸 수 있습니다",
    "{{selected_tags}} must be a standalone tag without a weight wrapper":
        "{{selected_tags}} 는 가중치로 감싸지 말고 쉼표 사이에 따로 적어 주세요",
    "Unbalanced or unsupported numeric weight in E621 template": "템플릿의 가중치(숫자::태그 ::) 짝이 맞지 않습니다",
    "weight must be a finite number between 0 and 2": "가중치는 0 ~ 2 사이 숫자여야 합니다",
}


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
        self.save_dir = save_root / "e621_event"
        self.settings_path = save_root / "e621_module_v2_settings.json"
        self.starred_path = save_root / "e621_starred_v2.json"
        self.deleted_path = save_root / "e621_deleted_v2.json"
        self.selected_tags_path = save_root / "e621_selected_tags_v1.json"
        self.selected_tags: list[dict[str, Any]] = []
        self.use_main_pipeline = True
        self.auto_related_enabled = True
        self.auto_related_limit = AUTO_RELATED_DEFAULT_LIMIT
        self.auto_related_excluded: list[str] = []
        self._species_tags: set[str] | None = None
        self._related_cache: tuple[Any, list[dict[str, Any]]] | None = None
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
        self.disable_translation = False
        self.disable_wiki_search = False
        self.starred_keys: set[str] = set()
        self.deleted_keys: set[str] = set()
        self._settings_loaded = False
        self._search_index: E621ResearchIndex | None = None
        self._index_source = None

    def state(self) -> dict[str, Any]:
        loaded = self._ensure_loaded()
        visible_tags = self._visible_tags() if loaded else []
        selected = self._find_tag(self.selected_tag) if loaded else None
        matches = self._search_index.matches(self.search_text, self.disable_wiki_search) if loaded else None
        selected_match = (matches.get(self.selected_tag) if matches is not None and
            any(row["tag"] == self.selected_tag for row in visible_tags) else None)
        tag_limit = 300
        self.tag_offset = min(self.tag_offset, max(0, (len(visible_tags) - 1) // tag_limit * tag_limit))
        selected_payload = self._tag_payload(selected, selected_match) if selected else None
        if selected_payload is not None:
            selected_payload["research"] = self.research_metadata.for_tag(selected_payload["tag"])
            selected_payload["relations"] = self._relations_payload(selected_payload["tag"])
        return {
            "type": "module_state",
            "module_id": "e621_event",
            "available": True,
            "runtime": "web",
            "data_loaded": loaded,
            "data_path": str(self.data_path),
            "search_text": self.search_text,
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
            "selected_tags": [dict(row) for row in self.selected_tags],
            "auto_related": self._auto_related_payload() if loaded else None,
            # 자동이 켜져 있으면 화면은 추천 줄을 안 그린다 - 그때는 만들지 않는다.
            "selection_suggestions": self._suggestions_payload() if loaded and not self.auto_related_enabled else None,
            "selection_preview": self._preview_payload() if loaded else None,
            "use_main_pipeline": self.use_main_pipeline,
            "weight_limits": {mode: dict(limits) for mode, limits in WEIGHT_LIMITS.items()},
        }

    # ── 관계 팩 → 화면 ────────────────────────────────────────────────────────
    # 응답 계약 = docs/e621_relations_contract.ko.md. 여기서는 화면이 그릴 만큼만 줄인다.
    # 관계가 프롬프트에 스스로 들어가는 길은 하나뿐이다: 자동 조립이 켜져 있고, 그 태그가 트레이에 칩으로 보일 때.
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
        # '함께' = 팩에 든 순서 그대로(함께 붙은 수 × 특이도). 종은 의존할 때만 보인다(자동 조립과 같은 규칙).
        species = self._species()
        anchor_is_species = exact_tag in species
        cooccurrences = []
        for target, pair, share, lift, _count in self.relations.cooccurring(exact_tag):
            if target in self.deleted_keys:
                continue
            if target in species and (anchor_is_species or share < SPECIES_DEPENDENT_SHARE):
                continue
            cooccurrences.append({**self._tag_brief(target, selected), "pair_count": int(pair),
                                  "share": round(share, 3), "lift": round(lift, 2)})
        return {
            "status": related.get("status"),
            "snapshot": (related.get("observations") or {}).get("snapshot"),
            "broader": ranked(broader), "broader_total": len(set(broader)),
            "narrower": ranked(narrower), "narrower_total": len(set(narrower)),
            "aliases": [{"from": row["source"]["exact_tag"], "to": row["target"]["exact_tag"]}
                        for row in groups.get("aliases") or []],
            "cooccurrences": cooccurrences,
        }

    def _related_rows(self) -> list[dict[str, Any]]:
        """고른 태그들과 함께 붙는 태그 - 숨김 · 제외 · 문턱을 걸기 전의 전체. 고른 태그가 그대로면 다시 안 만든다."""
        anchors = tuple(row["exact_tag"] for row in self.selected_tags)
        if self._related_cache is not None and self._related_cache[0] == anchors:
            return self._related_cache[1]
        selected = set(anchors)
        species = self._species()
        # 고른 태그가 이미 뜻하는 상위 태그(soles → feet, kimono → clothing)는 붙이지 않는다 - 자리만 차지한다.
        implied: set[str] = set()
        for anchor in anchors:
            implied |= self.relations.implied(anchor)
        merged: dict[str, dict[str, Any]] = {}
        for anchor in anchors[:64]:
            anchor_is_species = anchor in species
            for target, pair, share, lift, count in self.relations.cooccurring(anchor):
                if target in selected or target in implied or count < RELATED_MIN_POSTS:
                    continue
                is_species = target in species
                # 종을 직접 골랐으면 종을 더 붙이지 않는다(fox → red_fox 는 원하는 것이 아니다).
                if is_species and (anchor_is_species or share < SPECIES_DEPENDENT_SHARE):
                    continue
                entry = merged.setdefault(target, {"tag": target, "species": is_species, "edges": []})
                entry["edges"].append((anchor, share, share * math.log2(lift), int(pair)))
        # 종은 가장 구체적인 것만: fox 가 있으면 그것이 뜻하는 canine · canid 는 뺀다.
        covered: set[str] = set()
        for entry in merged.values():
            if entry["species"]:
                covered |= self.relations.implied(entry["tag"])
        rows = [entry for tag, entry in merged.items() if tag not in covered]
        self._related_cache = (anchors, rows)
        return rows

    def _related_candidates(self, *, min_share: float, limit: int, excluded: set[str]) -> list[dict[str, Any]]:
        """코어 순: 여러 태그에 걸친 것 먼저, 그다음 '함께 붙는 비율 × 특이도'. 종은 하나만, 맨 뒤에."""
        if limit <= 0 or not self.selected_tags:
            return []
        selected = {row["exact_tag"] for row in self.selected_tags}
        ranked = []
        for entry in self._related_rows():
            tag = entry["tag"]
            if tag in self.deleted_keys or tag in excluded:
                continue
            # 종은 이미 의존 문턱을 넘은 것만 남아 있다.
            edges = entry["edges"] if entry["species"] else [edge for edge in entry["edges"] if edge[1] >= min_share]
            if not edges:
                continue
            ranked.append({**self._tag_brief(tag, selected), "species": entry["species"],
                           "anchors": [edge[0] for edge in edges],
                           "matched_anchor_count": len(edges),
                           "share": round(max(edge[1] for edge in edges), 3),
                           "pair_count": max(edge[3] for edge in edges),
                           "_score": sum(edge[2] for edge in edges)})
        ranked.sort(key=lambda row: (-row["matched_anchor_count"], -row["_score"], row["tag"]))
        species = [row for row in ranked if row["species"]][:1]
        chosen = [row for row in ranked if not row["species"]][:max(0, limit - len(species))] + species
        for row in chosen:
            row.pop("_score")
        return chosen

    def _auto_tags(self) -> list[dict[str, Any]]:
        if not self.auto_related_enabled:
            return []
        return self._related_candidates(min_share=AUTO_RELATED_MIN_SHARE, limit=self.auto_related_limit,
                                        excluded=set(self.auto_related_excluded))

    def _auto_related_payload(self) -> dict[str, Any]:
        return {"enabled": self.auto_related_enabled, "limit": self.auto_related_limit,
                "limit_max": AUTO_RELATED_MAX_LIMIT, "min_share": AUTO_RELATED_MIN_SHARE,
                # 고른 태그가 없으면 팩을 읽지 않는다 - 읽는 데 0.3초쯤 걸리고, 그때는 쓸 일도 없다.
                "available": bool(self.relations.load()) if self.selected_tags else None,
                "tags": self._auto_tags(), "excluded": list(self.auto_related_excluded)}

    def _suggestions_payload(self) -> dict[str, Any] | None:
        if not self.selected_tags:
            return None
        # 쌍 관측의 합이라 근사다(여러 태그 전체의 교집합 수가 아니다).
        return {"status": "available" if self.relations.load() else "missing", "approximate": True,
                "candidates": self._related_candidates(min_share=SUGGEST_MIN_SHARE, limit=SUGGEST_LIMIT, excluded=set())}

    def _assembly_rows(self) -> tuple[list[dict[str, Any]], int]:
        """[생성] 과 미리보기가 함께 쓰는 조립 순서: 고른 태그(사용자 순서) → 자동(코어 순, 가중치 1)."""
        manual = [dict(row) for row in self.selected_tags]
        auto = [{"exact_tag": row["tag"], "weight": 1.0} for row in self._auto_tags()]
        return manual + auto, len(manual)

    def _preview_payload(self) -> dict[str, Any]:
        """[생성] 이 보낼 글을 조각으로. 와일드카드는 철자 그대로 두고 메인 파이프라인은 타지 않는다."""
        # 상태 조회는 모드를 못 읽는 환경에서도 죽지 않아야 한다([생성] 은 모드가 꼭 있어야 한다 - 그쪽은 그대로).
        get_api_mode = getattr(self.app_context, "get_api_mode", None)
        api_mode = get_api_mode() if callable(get_api_mode) else "NAI"
        rows, manual_count = self._assembly_rows()
        try:
            tags, protected = prepare_template(self.testbench, rows, api_mode, expand=None)
        except ValueError as exc:
            return {"api_mode": api_mode, "segments": [], "error": PREVIEW_ERRORS.get(str(exc), str(exc))}
        order = {token: index for index, token in enumerate(protected)}
        segments = []
        for token in tags:
            index = order.get(token)
            if index is not None and index < len(rows):
                # prepare_template 은 조립 태그를 맨 먼저, 넘긴 순서대로 보호한다.
                segments.append({"text": protected[token], "source": "manual" if index < manual_count else "auto",
                                 "exact_tag": rows[index]["exact_tag"]})
            else:
                segments.append({"text": protected.get(token, token), "source": "template"})
        return {"api_mode": api_mode, "segments": segments, "error": None}

    def set_param(self, key: str, value: Any) -> dict[str, Any] | list[dict[str, Any]]:
        self._ensure_loaded()
        raw = str(value or "")
        if key == "search":
            self.search_text = raw.strip().lower()
            self.current_category = None
            self.current_level2 = None
            self.selected_tag = None
            self.tag_offset = 0
        elif key == "reset":
            self.search_text = ""
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
        elif key.startswith("auto_related_"):
            try:
                self._edit_auto_related(key, value)
            except (ValueError, OSError) as exc:
                return self._toast(str(exc), level="error")
        elif key == "use_main_pipeline":
            self.use_main_pipeline = self._coerce_bool(value)
            self._save_settings()
        elif key == "testbench":
            self.testbench = raw
            self._save_settings()
        elif key == "generate":
            template = raw if raw.strip() else self.testbench
            try:
                from core.headless_random_prompt_service import pipeline_swap_lock
                with pipeline_swap_lock(self.app_context):
                    expand, template_context = self._template_expander() if self.use_main_pipeline else (None, None)
                    tags, protected = prepare_template(template, self._assembly_rows()[0], self.app_context.get_api_mode(),
                        expand=expand)
                    if not tags:
                        return self._toast("E621 testbench is empty", level="error")
                    generated = self._generate_prompt(tags) if self.use_main_pipeline else ", ".join(tags)
                    generated = restore_literals(generated, protected)
                    if not generated:
                        raise ValueError("E621 generated prompt is empty")
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
                return self._toast(str(exc), level="error")
            self.testbench = template
            self._save_settings()
            self.app_context.prompt_text = generated
            save_remote_ui_state = getattr(self.app_context, "save_remote_ui_state", None)
            if callable(save_remote_ui_state):
                save_remote_ui_state()
            return [
                {
                    "type": "prompt_generated",
                    "source": "e621_event",
                    "use_main_pipeline": self.use_main_pipeline,
                    "prompt": generated,
                    "remaining": self.app_context.search_results.get_count()
                    if getattr(self.app_context, "search_results", None) is not None
                    else 0,
                    "rating_counts": self.app_context.search_state_payload().get("rating_counts", {}),
                },
                self._toast(f"E621 prompt prepared ({len(tags)} tags)", level="success"),
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
            self.use_main_pipeline = self._coerce_bool(settings.get("use_main_pipeline", True))
            self.testbench = str(settings.get("testbench", DEFAULT_TESTBENCH))
            self.auto_related_enabled = self._coerce_bool(settings.get("auto_related_enabled", True))
            try:
                limit = int(settings.get("auto_related_limit", AUTO_RELATED_DEFAULT_LIMIT))
            except (TypeError, ValueError):
                limit = AUTO_RELATED_DEFAULT_LIMIT
            self.auto_related_limit = min(AUTO_RELATED_MAX_LIMIT, max(0, limit))
            excluded = settings.get("auto_related_excluded", [])
            self.auto_related_excluded = list(dict.fromkeys(
                tag for tag in (excluded if isinstance(excluded, list) else []) if isinstance(tag, str) and tag
            ))[:AUTO_RELATED_EXCLUDED_MAX]
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
                    "use_main_pipeline": self.use_main_pipeline,
                    "testbench": self.testbench,
                    "auto_related_enabled": self.auto_related_enabled,
                    "auto_related_limit": self.auto_related_limit,
                    "auto_related_excluded": self.auto_related_excluded,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _edit_auto_related(self, key: str, value: Any) -> None:
        if key == "auto_related_enabled":
            self.auto_related_enabled = self._coerce_bool(value)
        elif key == "auto_related_limit":
            if isinstance(value, bool):
                raise ValueError("auto_related_limit must be an integer")
            try:
                limit = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("auto_related_limit must be an integer") from exc
            self.auto_related_limit = min(AUTO_RELATED_MAX_LIMIT, max(0, limit))
        elif key in {"auto_related_exclude", "auto_related_include"}:
            exact = value.get("exact_tag") if isinstance(value, dict) else value
            if not isinstance(exact, str) or self._find_tag(exact) is None:
                raise ValueError("Unknown exact_tag in E621 dictionary")
            kept = [tag for tag in self.auto_related_excluded if tag != exact]
            if key == "auto_related_exclude":
                # 새로 뺀 것을 남기고 가장 오래된 것부터 밀어낸다.
                kept = (kept + [exact])[-AUTO_RELATED_EXCLUDED_MAX:]
            self.auto_related_excluded = kept
        elif key == "auto_related_reset":
            self.auto_related_excluded = []
        else:
            raise ValueError(f"Unknown E621 auto-related command: {key}")
        self._save_settings()

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
        matches = index.matches(self.search_text, self.disable_wiki_search)
        categories = []
        for section, name, folder_count in sorted(index.categories):
            rows = index.category_rows[(section, name)]
            visible = rows if self.content_filter == "all" and not self.deleted_keys else index.filter_rows(
                rows, content_filter=self.content_filter, hidden=self.deleted_keys,
                starred=self.starred_keys, starred_only=False, matches=None)
            categories.append({
                "name": name, "section": section, "folder_count": folder_count,
                "tag_count": len(visible),
                "starred_count": sum(row["tag"] in self.starred_keys for row in visible) if self.starred_keys else 0,
                "matched": bool(self.search_text and any(row["tag"] in matches and
                    (self.view_mode != "starred" or row["tag"] in self.starred_keys) for row in visible)),
                "selected": name == self.current_category,
            })
        return categories

    def _folders(self) -> list[dict[str, Any]]:
        if not self.current_category:
            return []
        index = self._search_index
        section, node = self._category_data(self.current_category)
        if not isinstance(node, dict):
            return []
        matches = index.matches(self.search_text, self.disable_wiki_search)
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
            matches=index.matches(self.search_text, self.disable_wiki_search))

    @staticmethod
    def _search_key(value: Any) -> str:
        """Keep the established underscore/space search projection."""
        return search_key(value)

    def _filter_tags(self, tags: list[dict[str, Any]], *, include_search: bool = True) -> list[dict[str, Any]]:
        index = self._search_index
        matches = index.matches(self.search_text, self.disable_wiki_search) if include_search else None
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
        research = self.research_metadata.for_tag(tag_name) if self.research_metadata else {}
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
