"""PyQt-free E621 Event module state for the Remote Web headless runtime."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.e621_tag_repository import E621TagRepository
from core.e621_research_index import E621ResearchIndex, search_key
from core.prompt_generation_service import PromptGenerationService
from core.wildcard_processor import split_tags_smart


DEFAULT_TESTBENCH = "1girl, 1boy, 2:: e621태그는_강조하여_입력하세요 ::, duo, male/female, nsfw, rating:explicit"


class E621EventService:
    def __init__(self, app_context: Any):
        self.app_context = app_context
        self.root = Path(getattr(app_context, "repo_root", Path.cwd()))
        runtime_paths = getattr(app_context, "runtime_paths", None)
        save_root = runtime_paths.save_dir if runtime_paths is not None else self.root / "save"
        self.data_path = self.root / "data" / "e621_data"
        data_dir = getattr(runtime_paths, "data_dir", None)
        self.repository = E621TagRepository(self.root, data_roots=[data_dir] if data_dir is not None else None)
        self.save_dir = save_root / "e621_event"
        self.settings_path = save_root / "e621_module_v2_settings.json"
        self.starred_path = save_root / "e621_starred_v2.json"
        self.deleted_path = save_root / "e621_deleted_v2.json"
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
        }

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
        elif key == "testbench":
            self.testbench = raw
        elif key == "generate":
            prompt = raw.strip() or self.testbench
            tags = [tag.strip() for tag in split_tags_smart(prompt) if tag.strip()]
            if not tags:
                return self._toast("E621 testbench is empty", level="error")
            self.testbench = ", ".join(tags)
            generated = self._generate_prompt(tags)
            self.app_context.prompt_text = generated
            save_remote_ui_state = getattr(self.app_context, "save_remote_ui_state", None)
            if callable(save_remote_ui_state):
                save_remote_ui_state()
            return [
                {
                    "type": "prompt_generated",
                    "source": "e621_event",
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

    def _save_settings(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(
                {
                    "disable_translation": self.disable_translation,
                    "disable_wiki_search": self.disable_wiki_search,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

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
        }
        try:
            service = getattr(self.app_context, "prompt_generation_service", None)
            if service is None:
                service = PromptGenerationService(self.app_context)
                self.app_context.prompt_generation_service = service
            return service.generate_instant_source_silent(source, settings) or ", ".join(tags)
        except Exception:
            return ", ".join(tags)

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
