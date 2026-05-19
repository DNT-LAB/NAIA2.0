"""PyQt-free E621 Event module state for the Remote Web headless runtime."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.prompt_generation_service import PromptGenerationService
from core.wildcard_processor import split_tags_smart


DEFAULT_TESTBENCH = "1girl, 1boy, 2:: e621태그는_강조하여_입력하세요 ::, duo, male/female, nsfw, rating:explicit"


class E621EventService:
    def __init__(self, app_context: Any):
        self.app_context = app_context
        self.root = Path(getattr(app_context, "repo_root", Path.cwd()))
        self.data_path = self.root / "data" / "e621_data"
        self.save_dir = self.root / "save" / "e621_event"
        self.settings_path = self.root / "save" / "e621_module_v2_settings.json"
        self.starred_path = self.root / "save" / "e621_starred_v2.json"
        self.deleted_path = self.root / "save" / "e621_deleted_v2.json"
        self.data: dict[str, Any] | None = None
        self.search_text = ""
        self.view_mode = "default"
        self.current_category: str | None = None
        self.current_level2: str | None = None
        self.selected_tag: str | None = None
        self.testbench = DEFAULT_TESTBENCH
        self.disable_translation = False
        self.disable_wiki_search = False
        self.starred_keys: set[str] = set()
        self.deleted_keys: set[str] = set()
        self._settings_loaded = False

    def state(self) -> dict[str, Any]:
        loaded = self._ensure_loaded()
        selected = self._find_tag(self.selected_tag) if loaded else None
        visible_tags = self._visible_tags() if loaded else []
        tag_limit = 300
        return {
            "type": "module_state",
            "module_id": "e621_event",
            "available": True,
            "headless": True,
            "data_loaded": loaded,
            "data_path": str(self.data_path),
            "search_text": self.search_text,
            "view_mode": self.view_mode,
            "disable_translation": self.disable_translation,
            "disable_wiki_search": self.disable_wiki_search,
            "prompt_testbench_visible": True,
            "translation_control_visible": True,
            "wiki_search_control_visible": True,
            "current_category": self.current_category,
            "current_level2": self.current_level2,
            "categories": self._categories() if loaded else [],
            "folders": self._folders() if loaded else [],
            "tags": [self._tag_payload(item) for item in visible_tags[:tag_limit]],
            "tag_total": len(visible_tags),
            "tag_limit": tag_limit,
            "starred_total": len(self.starred_keys),
            "hidden_total": len(self.deleted_keys),
            "hidden_items": sorted(self.deleted_keys)[:120],
            "selected": self._tag_payload(selected) if selected else None,
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
        elif key == "reset":
            self.search_text = ""
            self.current_category = None
            self.current_level2 = None
            self.selected_tag = None
            self.view_mode = "default"
        elif key == "view_mode":
            self.view_mode = "starred" if raw == "starred" else "default"
        elif key == "category":
            self.current_category = raw or None
            self.current_level2 = None
            self.selected_tag = None
        elif key == "level2":
            self.current_level2 = raw or None
            self.selected_tag = None
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
            return self._toast(f"E621 action is not supported in headless: {key}", level="info")
        return self.state()

    def _ensure_loaded(self) -> bool:
        if not self._settings_loaded:
            self._load_settings()
        if self.data is not None:
            return True
        if not self.data_path.exists():
            return False
        try:
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        self.data = payload
        return True

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
        categories = []
        data = self.data or {}
        for section in ("General", "Species"):
            section_data = data.get(section, {})
            if not isinstance(section_data, dict):
                continue
            for name in sorted(section_data.keys()):
                tags = self._collect_tags(section_data.get(name))
                visible = [tag for tag in tags if tag.get("tag", "") not in self.deleted_keys]
                categories.append({
                    "name": name,
                    "section": section,
                    "folder_count": len(section_data.get(name, {})) if isinstance(section_data.get(name), dict) else 0,
                    "tag_count": len(visible),
                    "starred_count": sum(1 for tag in visible if tag.get("tag", "") in self.starred_keys),
                    "matched": bool(self.search_text and self._filter_tags(visible, include_search=True)),
                    "selected": name == self.current_category,
                })
        return categories

    def _folders(self) -> list[dict[str, Any]]:
        if not self.current_category:
            return []
        _, category_data = self._category_data(self.current_category)
        if not isinstance(category_data, dict):
            return []
        folders = []
        for name in sorted(category_data.keys()):
            tags = self._filter_tags(self._collect_tags(category_data.get(name)))
            if not tags:
                continue
            folders.append({
                "name": name,
                "display": name.replace("_", " "),
                "tag_count": len(tags),
                "selected": name == self.current_level2,
            })
        return folders

    def _visible_tags(self) -> list[dict[str, Any]]:
        if self.current_category:
            _, category_data = self._category_data(self.current_category)
            if isinstance(category_data, dict) and self.current_level2:
                tags = self._collect_tags(category_data.get(self.current_level2))
            else:
                tags = self._collect_tags(category_data)
        else:
            tags = []
            data = self.data or {}
            for section in ("General", "Species"):
                for category_data in (data.get(section, {}) or {}).values():
                    tags.extend(self._collect_tags(category_data))
        tags = self._filter_tags(tags, include_search=True)
        tags.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
        return tags

    def _filter_tags(self, tags: list[dict[str, Any]], *, include_search: bool = True) -> list[dict[str, Any]]:
        result = [tag for tag in tags if tag.get("tag", "") not in self.deleted_keys]
        if self.view_mode == "starred":
            result = [tag for tag in result if tag.get("tag", "") in self.starred_keys]
        if include_search and self.search_text:
            needle = self.search_text.lower()
            filtered = []
            for tag in result:
                name = str(tag.get("tag") or "").lower()
                wiki = "" if self.disable_wiki_search else str(tag.get("wiki_body") or tag.get("wiki_preview") or "").lower()
                if needle in name or needle in wiki:
                    copied = dict(tag)
                    copied["matched_in_wiki"] = needle not in name and needle in wiki
                    filtered.append(copied)
            result = filtered
        return result

    def _category_data(self, category: str) -> tuple[str | None, Any]:
        data = self.data or {}
        for section in ("General", "Species"):
            section_data = data.get(section, {})
            if isinstance(section_data, dict) and category in section_data:
                return section, section_data.get(category)
        return None, None

    def _find_tag(self, tag_name: str | None) -> dict[str, Any] | None:
        if not tag_name:
            return None
        for tag in self._visible_tags():
            if tag.get("tag") == tag_name:
                return tag
        for section in ("General", "Species"):
            for category_data in (self.data or {}).get(section, {}).values():
                for tag in self._collect_tags(category_data):
                    if tag.get("tag") == tag_name:
                        return tag
        return None

    def _tag_payload(self, tag_data: dict[str, Any]) -> dict[str, Any]:
        tag_name = str(tag_data.get("tag") or "")
        count = int(tag_data.get("count") or 0)
        return {
            "tag": tag_name,
            "display": tag_name.replace("_", " "),
            "kor": tag_data.get("kor", ""),
            "count": count,
            "count_label": self._format_count(count),
            "starred": tag_name in self.starred_keys,
            "hidden": tag_name in self.deleted_keys,
            "matched_in_wiki": bool(tag_data.get("matched_in_wiki", False)),
        }

    def _wiki_payload(self, tag_data: dict[str, Any] | None) -> dict[str, Any]:
        if not tag_data:
            return {"tag": "", "text": "", "translated": False}
        tag_name = str(tag_data.get("tag") or "")
        body = str(tag_data.get("wiki_body") or tag_data.get("wiki_preview") or "위키 정보 없음")
        body = self._clean_wiki_text(body)
        return {
            "tag": tag_name,
            "text": f"Tag: {tag_name.replace('_', ' ')}\nCount: {self._format_count(tag_data.get('count'))}\n\n{'=' * 50}\n\n{body}",
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
        return {"type": "toast", "message": message, "level": level, "headless": True}

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
