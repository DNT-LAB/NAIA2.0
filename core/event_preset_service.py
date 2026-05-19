"""Server-safe Event Preset facade for Remote Web."""

from __future__ import annotations

import math
import base64
import json
import re
import threading
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd

from core.event_preset.data_manager import EventPresetDataManager
from core.event_preset.engines import (
    PERSON_PARTITION_LABELS,
    PERSON_PARTITION_ORDER,
    PERSON_TAG_MAP,
    RecommendationEngine,
    StagingEngine,
    TaxonomyEngine,
    format_count,
    parse_partition_name,
)


class EventPresetService:
    """Read-only Event Preset data service that does not import desktop widgets."""

    RATING_OPTIONS = [
        {"id": "g", "label": "G", "name": "General"},
        {"id": "s", "label": "S", "name": "Sensitive"},
        {"id": "q", "label": "Q", "name": "Question"},
        {"id": "e", "label": "E", "name": "Explicit"},
    ]
    RATING_NAMES = {item["id"]: item["name"] for item in RATING_OPTIONS}
    RATING_SUFFIX_TAGS = {
        "g": "rating:general",
        "s": "rating:sensitive",
        "q": "rating:questionable",
        "e": "rating:explicit",
    }
    PERSON_ALIASES = {
        "all": "1girl_solo",
        "solo": "1girl_solo",
        "pair": "2girls",
        "group": "multiple_girls",
    }
    SLOT_META = {
        "expression": {
            "df_key": "expression",
            "tag_col": "expression_tag",
            "group": "Expression",
            "limit": 12,
        },
        "clothing": {
            "df_key": "clothing",
            "tag_col": "clothing_tag",
            "group": "Clothing",
            "limit": 12,
        },
        "characteristic": {
            "df_key": "characteristic",
            "tag_col": "characteristic_tag",
            "group": "Characteristic",
            "limit": 12,
        },
    }

    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root)
        preferred_data_path = self.repo_root / "data" / "event_preset" / "naia_prompt_preset"
        legacy_data_path = self.repo_root / "ui" / "event_preset" / "naia_prompt_preset"
        self.data_path = preferred_data_path if preferred_data_path.exists() or not legacy_data_path.exists() else legacy_data_path
        self.translation_path = self.repo_root / "core" / "event_preset" / "event_preset_category_translations_ko.json"
        self.thumbnail_path = self.repo_root / "data" / "event_preset_thumbnail"
        self._data_manager = EventPresetDataManager(self.data_path)
        self._taxonomy: TaxonomyEngine | None = None
        self._recommendation: RecommendationEngine | None = None
        self._partition_row_counts: dict[str, Any] = {}
        self._base_ready = False
        self._base_error = ""
        self._thumbnail_lock = threading.RLock()
        self._thumbnail_index: dict[str, Any] | None = None
        self._translation_payload: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        main_state = "missing"
        message = "Event Preset data is not installed."
        partitions: set[str] = set()
        partition_counts: dict[str, Any] = {}

        if self.data_path.exists():
            try:
                if self._data_manager.is_data_available():
                    main_state = "ready"
                    message = "Main preset data is ready."
                    partitions = self._data_manager.get_available_partitions()
                    partition_counts = self._data_manager.get_partition_row_counts()
                else:
                    main_state = "error"
                    message = "Event Preset data exists but required base files are missing."
            except zipfile.BadZipFile:
                main_state = "error"
                message = "Event Preset data is not a valid ZIP archive."
            except Exception as exc:
                main_state = "error"
                message = f"Event Preset data check failed: {exc}"

        thumb_state = "ready" if self.thumbnail_path.exists() else "missing"
        if thumb_state == "missing" and main_state == "ready":
            message = "Main preset data is ready. Thumbnail data is not installed."

        return {
            "ok": True,
            "dataMode": "real" if main_state == "ready" else main_state,
            "dataAvailability": {
                "main": main_state,
                "thumbnails": thumb_state,
                "message": message,
            },
            "paths": {
                "main": str(self.data_path.relative_to(self.repo_root)),
                "thumbnails": str(self.thumbnail_path.relative_to(self.repo_root)),
            },
            "counts": {
                "partitions": len(partitions),
                "categories": len(partition_counts),
                "events": 0,
            },
            "capabilities": {
                "bootstrap": main_state == "ready",
                "select": main_state == "ready",
                "promptPreview": main_state == "ready",
                "thumbnail": thumb_state == "ready",
                "download": True,
            },
        }

    def _ensure_ready(self) -> None:
        if self._base_ready:
            return
        if self._base_error:
            raise RuntimeError(self._base_error)
        assets, missing = self._data_manager.load_base_assets()
        if assets is None:
            self._base_error = "Required Event Preset files are missing: " + ", ".join(missing)
            raise RuntimeError(self._base_error)
        self._taxonomy = TaxonomyEngine(assets)
        self._recommendation = RecommendationEngine(
            self._data_manager.get_recommendations(),
            self._data_manager.get_color_prefixes(),
        )
        self._partition_row_counts = self._data_manager.get_partition_row_counts()
        self._base_ready = True

    # ------------------------------------------------------------------
    # Bootstrap / selection
    # ------------------------------------------------------------------

    def bootstrap(
        self,
        rating_id: str = "s",
        person_id: str = "1girl_solo",
        search: str = "",
        category_id: str = "",
        subcategory_id: str = "",
        event_id: str = "",
        limit: int | None = None,
    ) -> dict[str, Any]:
        status = self.status()
        if status["dataAvailability"]["main"] != "ready":
            return {
                "ok": True,
                "dataMode": status["dataMode"],
                "dataAvailability": status["dataAvailability"],
                "ratings": self.RATING_OPTIONS,
                "persons": [],
                "selected": {
                    "ratingId": self._normalize_rating(rating_id),
                    "personId": self._normalize_person(person_id),
                    "categoryId": "",
                    "subcategoryId": "",
                    "eventId": "",
                    "comboId": "",
                    "recommendedTagIds": [],
                    "search": str(search or ""),
                },
                "categories": [],
            }

        self._ensure_ready()
        rating = self._normalize_rating(rating_id)
        person = self._normalize_person(person_id)
        partition = self._resolve_partition(rating, person)
        rating, person = parse_partition_name(partition)
        partition_data = self._load_projected_partition(partition)
        persons = self._person_options(rating)
        categories = self._build_categories(search, partition_data, limit=limit)
        selected = self._resolve_selected(categories, {
            "ratingId": rating,
            "personId": person,
            "categoryId": category_id,
            "subcategoryId": subcategory_id,
            "eventId": event_id,
            "comboId": "",
            "recommendedTagIds": [],
            "search": str(search or ""),
        })

        return {
            "ok": True,
            "dataMode": "real",
            "dataAvailability": status["dataAvailability"],
            "ratings": self.RATING_OPTIONS,
            "persons": persons,
            "selected": selected,
            "categories": categories,
        }

    def select(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        status = self.status()
        if status["dataAvailability"]["main"] != "ready":
            return {
                "ok": True,
                "dataMode": status["dataMode"],
                "dataAvailability": status["dataAvailability"],
                "selected": {},
                "event": None,
                "promptPreview": "",
            }

        self._ensure_ready()
        rating = self._normalize_rating(str(payload.get("ratingId") or "s"))
        person = self._normalize_person(str(payload.get("personId") or "1girl_solo"))
        partition = self._resolve_partition(rating, person)
        rating, person = parse_partition_name(partition)
        partition_data = self._load_projected_partition(partition)
        event_tag = str(payload.get("eventId") or payload.get("eventTag") or "").strip()
        if not event_tag:
            categories = self._build_categories(str(payload.get("search") or ""), partition_data, limit=2000)
            selected = self._resolve_selected(categories, {
                "ratingId": rating,
                "personId": person,
                "categoryId": str(payload.get("categoryId") or ""),
                "subcategoryId": str(payload.get("subcategoryId") or ""),
                "eventId": "",
                "comboId": "",
                "recommendedTagIds": [],
                "search": str(payload.get("search") or ""),
            })
            event_tag = selected.get("eventId", "")
        if not event_tag:
            return {
                "ok": True,
                "dataMode": "real",
                "dataAvailability": status["dataAvailability"],
                "selected": {
                    "ratingId": rating,
                    "personId": person,
                    "categoryId": str(payload.get("categoryId") or ""),
                    "subcategoryId": str(payload.get("subcategoryId") or ""),
                    "eventId": "",
                    "comboId": "",
                    "recommendedTagIds": [],
                    "search": str(payload.get("search") or ""),
                },
                "event": None,
                "promptPreview": "",
            }

        event = self._event_detail(event_tag, partition_data, rating, person)
        combo_id = str(payload.get("comboId") or "") or event["observedCombos"][0]["id"] if event["observedCombos"] else ""
        if combo_id and not any(combo["id"] == combo_id for combo in event["observedCombos"]):
            combo_id = event["observedCombos"][0]["id"] if event["observedCombos"] else ""
        recommended_ids = [
            str(item)
            for item in payload.get("recommendedTagIds", [])
            if isinstance(item, (str, int, float))
        ]
        prompt_preview = self._build_preview_from_event(
            event,
            combo_id,
            recommended_ids,
            rating=rating,
            person=person,
        )

        selected = {
            "ratingId": rating,
            "personId": person,
            "categoryId": str(payload.get("categoryId") or ""),
            "subcategoryId": str(payload.get("subcategoryId") or ""),
            "eventId": event_tag,
            "comboId": combo_id,
            "recommendedTagIds": recommended_ids,
            "search": str(payload.get("search") or ""),
        }
        return {
            "ok": True,
            "requestId": str(payload.get("requestId") or ""),
            "dataMode": "real",
            "dataAvailability": status["dataAvailability"],
            "selected": selected,
            "event": event,
            "promptPreview": prompt_preview,
        }

    def observed_combos(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Fast event-combo lookup for generation-time preset expansion."""
        payload = payload if isinstance(payload, dict) else {}
        status = self.status()
        if status["dataAvailability"]["main"] != "ready":
            return {
                "ok": True,
                "dataMode": status["dataMode"],
                "dataAvailability": status["dataAvailability"],
                "selected": {},
                "event": None,
            }

        self._ensure_ready()
        rating = self._normalize_rating(str(payload.get("ratingId") or "s"))
        person = self._normalize_person(str(payload.get("personId") or "1girl_solo"))
        partition = self._resolve_partition(rating, person)
        rating, person = parse_partition_name(partition)
        partition_data = self._load_projected_partition(partition)
        event_tag = str(payload.get("eventId") or payload.get("eventTag") or "").strip()
        if not event_tag:
            return {
                "ok": True,
                "dataMode": "real",
                "dataAvailability": status["dataAvailability"],
                "selected": {
                    "ratingId": rating,
                    "personId": person,
                    "categoryId": str(payload.get("categoryId") or ""),
                    "subcategoryId": str(payload.get("subcategoryId") or ""),
                    "eventId": "",
                },
                "event": None,
            }

        event = {
            "id": event_tag,
            "tag": event_tag,
            "label": event_tag,
            "ratings": [rating],
            "persons": [person],
            "promptAtoms": [event_tag],
            "observedCombos": self._observed_combos(event_tag, partition_data),
        }
        return {
            "ok": True,
            "dataMode": "real",
            "dataAvailability": status["dataAvailability"],
            "selected": {
                "ratingId": rating,
                "personId": person,
                "categoryId": str(payload.get("categoryId") or ""),
                "subcategoryId": str(payload.get("subcategoryId") or ""),
                "eventId": event_tag,
            },
            "event": event,
        }

    def prompt_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        rating = self._normalize_rating(str(payload.get("ratingId") or "s"))
        person = self._normalize_person(str(payload.get("personId") or "1girl_solo"))
        combo_tags = self._split_csv(payload.get("comboPrompt") or payload.get("prompt") or "")
        event_names = [
            str(item).strip()
            for item in payload.get("eventIds", [])
            if str(item).strip()
        ]
        recommended = [
            str(item).strip()
            for item in payload.get("recommendedTags", [])
            if str(item).strip()
        ]
        atoms = self._unique(combo_tags or event_names)
        prompt = ", ".join(self._prompt_atoms_with_identity(atoms, recommended, rating, person))
        return {"ok": True, "prompt": prompt, "atoms": self._split_csv(prompt)}

    def generation_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        selection = self.select(payload)
        event = selection.get("event")
        selected = selection.get("selected") or {}
        if not event:
            raise ValueError("Event Preset selection is empty.")
        rating = self._normalize_rating(str(selected.get("ratingId") or payload.get("ratingId") or "s"))
        person = self._normalize_person(str(selected.get("personId") or payload.get("personId") or "1girl_solo"))
        combo_id = str(selected.get("comboId") or "")
        recommended_ids = [
            str(item)
            for item in selected.get("recommendedTagIds", [])
            if isinstance(item, (str, int, float))
        ]
        prompt = self._build_preview_from_event(
            event,
            combo_id,
            recommended_ids,
            rating=rating,
            person=person,
        )
        prompt_override = str(payload.get("promptOverride") or "").strip()
        if prompt_override:
            prompt = prompt_override
        if not prompt:
            raise ValueError("Event Preset prompt is empty.")
        source_row = {
            "general": prompt,
            "rating": rating,
            "character": None,
            "copyright": None,
            "artist": None,
            "meta": None,
            "event_preset_event": str(event.get("tag") or event.get("id") or ""),
            "event_preset_combo_id": combo_id,
            "event_preset_person": person,
        }
        return {
            "ok": True,
            "requestId": str(payload.get("requestId") or ""),
            "selected": selected,
            "promptPreview": prompt,
            "sourceRow": source_row,
            "event": {
                "id": str(event.get("id") or ""),
                "tag": str(event.get("tag") or event.get("id") or ""),
                "label": str(event.get("label") or event.get("tag") or event.get("id") or ""),
            },
        }

    def thumbnail_payload(
        self,
        event_id: str = "",
        tag: str = "",
        size: str = "",
    ) -> tuple[bytes, str]:
        key = str(event_id or tag or "").strip()
        if not key:
            raise ValueError("eventId or tag is required.")
        index = self._load_thumbnail_index()
        value = index.get(key)
        if value is None:
            raise KeyError(f"Thumbnail not found: {key}")
        if isinstance(value, list):
            value = value[0] if value else ""
        if isinstance(value, dict):
            value = value.get("data") or value.get("image") or value.get("base64") or ""
        if not isinstance(value, str) or not value.strip():
            raise KeyError(f"Thumbnail not found: {key}")
        encoded = value.strip()
        if "," in encoded and encoded[:64].lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        raw = base64.b64decode(encoded)
        if raw.startswith(b"\xff\xd8"):
            media_type = "image/jpeg"
        elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
            media_type = "image/png"
        elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            media_type = "image/webp"
        else:
            media_type = "application/octet-stream"
        return raw, media_type

    # ------------------------------------------------------------------
    # Data shaping
    # ------------------------------------------------------------------

    def _load_projected_partition(self, partition: str) -> dict[str, Any]:
        assert self._taxonomy is not None
        data = self._data_manager.load_partition_data(partition)
        catalog = data.get("catalog", pd.DataFrame())
        if isinstance(catalog, pd.DataFrame) and not catalog.empty:
            event_count_map = {
                str(row.event_tag): int(row.post_count)
                for row in catalog[["event_tag", "post_count"]].itertuples(index=False)
            }
            self._taxonomy.apply_partition_projection(event_count_map)
        else:
            self._taxonomy.reset_to_base()
        return data

    def _build_categories(
        self,
        search: str,
        partition_data: dict[str, Any],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        assert self._taxonomy is not None
        visible_events = self._visible_events(partition_data)
        search_text = str(search or "").strip()
        if search_text:
            visible_events &= set(self._taxonomy.filter_events(search_text))
        max_events = None if limit is None else max(1, min(int(limit), 8000))

        categories: list[dict[str, Any]] = []
        emitted = 0
        for subgroup in self._taxonomy.get_subgroups_sorted():
            events = self._taxonomy.get_events_for_subgroup(subgroup["group"], subgroup["subgroup"])
            events = [event for event in events if event["event_tag"] in visible_events]
            if not events:
                continue
            remaining = len(events) if max_events is None else max_events - emitted
            subcategories = self._group_events_by_subcategory(subgroup, events, remaining)
            if not subcategories:
                continue
            total_count = sum(int(event.get("post_count", 0) or 0) for event in events)
            category_id = self._category_id(subgroup["group"], subgroup["subgroup"])
            category = {
                "id": category_id,
                "groupId": str(subgroup["group"]),
                "subgroupId": str(subgroup["subgroup"]),
                "group": str(subgroup.get("group_display") or subgroup["group"]),
                "label": str(subgroup.get("subgroup_display") or subgroup["subgroup"]),
                "count": total_count,
                "displayCount": format_count(total_count),
                "subcategories": subcategories,
            }
            self._apply_translation(category, "subgroups", category_id)
            self._apply_translation(category, "groups", str(subgroup["group"]), prefix="group")
            categories.append(category)
            emitted += sum(len(subcategory["events"]) for subcategory in subcategories)
            if max_events is not None and emitted >= max_events:
                break
        return categories

    def _group_events_by_subcategory(
        self,
        subgroup: dict[str, Any],
        events: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        category_id = self._category_id(subgroup["group"], subgroup["subgroup"])
        for event in events[:max(0, int(limit or 0))]:
            raw_subcat = str(event.get("subcategory") or "general")
            subcat_id = self._subcategory_id(category_id, raw_subcat)
            item = grouped.setdefault(subcat_id, {
                "id": subcat_id,
                "categoryId": category_id,
                "subcategoryId": raw_subcat,
                "label": str(event.get("subcategory_display") or raw_subcat.replace("_", " ").title()),
                "count": 0,
                "events": [],
            })
            self._apply_translation(item, "subcategories", subcat_id)
            count = int(event.get("post_count", 0) or 0)
            item["count"] += count
            tag = str(event["event_tag"])
            event_item = {
                "id": tag,
                "tag": tag,
                "label": tag,
                "count": count,
                "ratings": [key for key in self.RATING_NAMES],
                "persons": list(PERSON_PARTITION_ORDER),
                "promptAtoms": [tag],
            }
            self._apply_translation(event_item, "events", tag)
            item["events"].append(event_item)
        return list(grouped.values())

    def _event_detail(
        self,
        event_tag: str,
        partition_data: dict[str, Any],
        rating: str,
        person: str,
    ) -> dict[str, Any]:
        catalog = partition_data.get("catalog", pd.DataFrame())
        count = 0
        if isinstance(catalog, pd.DataFrame) and not catalog.empty:
            rows = catalog[catalog["event_tag"] == event_tag]
            if not rows.empty:
                count = int(rows.iloc[0].get("post_count", 0) or 0)
        combos = self._observed_combos(event_tag, partition_data)
        slots = self._slots(event_tag, partition_data)
        recommended = self._recommended_tags(event_tag, slots)
        direct_recommended = self._direct_recommended_tags(event_tag, slots)
        thumbnail_ready = self.thumbnail_path.exists()
        event = {
            "id": event_tag,
            "tag": event_tag,
            "label": event_tag,
            "count": count,
            "ratings": [rating],
            "persons": [person],
            "promptAtoms": [event_tag],
            "observedCombos": combos,
            "slots": slots,
            "recommendedTags": recommended,
            "directRecommendedTags": direct_recommended,
            "thumbnail": {
                "status": "ready" if thumbnail_ready else "missing",
                "label": f"{event_tag} preview",
                "aspectRatio": "3:4",
                "source": "server" if thumbnail_ready else "metadata",
                "url": f"/api/event-preset/thumbnail?eventId={quote(event_tag, safe='')}" if thumbnail_ready else "",
            },
        }
        self._apply_translation(event, "events", event_tag)
        return event

    def _observed_combos(
        self,
        event_tag: str,
        partition_data: dict[str, Any],
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        combo_df = partition_data.get("combo", pd.DataFrame())
        if not isinstance(combo_df, pd.DataFrame) or combo_df.empty:
            return []
        combos = StagingEngine().get_single_event_combos(event_tag, combo_df, limit=limit)
        result: list[dict[str, Any]] = []
        for index, (prompt, count) in enumerate(combos):
            tags = self._split_csv(prompt)
            combo = {
                "id": f"combo-{index}",
                "label": self._combo_label(tags, event_tag),
                "prompt": prompt,
                "tags": tags,
                "count": int(count) if not isinstance(count, float) or math.isfinite(count) else 0,
            }
            translated_tags = self._translated_tag_labels(tags)
            if translated_tags:
                combo["labelKo"] = ", ".join(translated_tags[:4])
                combo["krDesc"] = ", ".join(translated_tags)
            result.append(combo)
        return result

    def _slots(self, event_tag: str, partition_data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        return {
            key: self._slot_items(event_tag, partition_data, **meta)
            for key, meta in self.SLOT_META.items()
        }

    def _slot_items(
        self,
        event_tag: str,
        partition_data: dict[str, Any],
        df_key: str,
        tag_col: str,
        group: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        df = partition_data.get(df_key, pd.DataFrame())
        if not isinstance(df, pd.DataFrame) or df.empty or tag_col not in df.columns:
            return []
        sub = df[df["event_tag"] == event_tag]
        if sub.empty:
            return []
        sub = sub.sort_values("confidence", ascending=False).head(limit)
        items: list[dict[str, Any]] = []
        for row in sub.itertuples(index=False):
            tag = str(getattr(row, tag_col))
            confidence = float(getattr(row, "confidence", 0.0) or 0.0)
            count = int(getattr(row, "count", 0) or 0)
            items.append({
                "id": tag,
                "tag": tag,
                "count": count,
                "confidence": confidence,
                "group": group,
            })
        return items

    def _recommended_tags(self, event_tag: str, slots: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        assert self._recommendation is not None
        recommended: list[dict[str, Any]] = []
        seen: set[str] = set()

        def push(tag: str, count: int = 0, group: str = "Auto", confidence: float | None = None) -> None:
            key = tag.strip().lower()
            if not key or key in seen or key == event_tag.lower():
                return
            seen.add(key)
            item: dict[str, Any] = {"id": tag, "tag": tag, "count": int(count), "group": group}
            if confidence is not None:
                item["confidence"] = float(confidence)
            recommended.append(item)

        for tag in self._recommendation.collect_auto_deps([event_tag]):
            push(str(tag), group="Auto")
        for slot_key, group in [
            ("expression", "Expression"),
            ("clothing", "Clothing"),
            ("characteristic", "Characteristic"),
        ]:
            for item in slots.get(slot_key, [])[:8]:
                push(
                    str(item.get("tag") or ""),
                    int(item.get("count", 0) or 0),
                    group,
                    item.get("confidence"),
                )
        return recommended

    def _direct_recommended_tags(
        self,
        event_tag: str,
        slots: dict[str, list[dict[str, Any]]],
        per_group_limit: int = 8,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = {event_tag.strip().lower()}
        for slot_key in ["expression", "clothing", "characteristic"]:
            items = sorted(
                slots.get(slot_key, []),
                key=lambda item: (
                    float(item.get("confidence", 0.0) or 0.0),
                    int(item.get("count", 0) or 0),
                ),
                reverse=True,
            )
            for item in items[:per_group_limit]:
                tag = str(item.get("tag") or item.get("id") or "").strip()
                key = tag.lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                result.append(dict(item))
        return result

    def _build_preview_from_event(
        self,
        event: dict[str, Any],
        combo_id: str,
        recommended_ids: list[str],
        rating: str = "",
        person: str = "",
    ) -> str:
        combo = next(
            (item for item in event.get("observedCombos", []) if item.get("id") == combo_id),
            None,
        )
        base = self._split_csv(combo.get("prompt", "")) if combo else list(event.get("promptAtoms", []))
        base = self._base_tags_with_event(event, base)
        rec_lookup = self._recommendation_lookup(event)
        rec_tags = [rec_lookup[item] for item in recommended_ids if item in rec_lookup]
        return ", ".join(self._prompt_atoms_with_identity(base, rec_tags, rating, person))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_translations(self) -> dict[str, Any]:
        if self._translation_payload is not None:
            return self._translation_payload
        try:
            with self.translation_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            data = {}
        except Exception:
            data = {}
        self._translation_payload = data if isinstance(data, dict) else {}
        return self._translation_payload

    def _translation_item(self, section: str, key: Any) -> dict[str, Any]:
        clean_key = str(key or "").strip()
        if not clean_key:
            return {}
        section_data = self._load_translations().get(section)
        if not isinstance(section_data, dict):
            return {}
        item = section_data.get(clean_key)
        if item is None and section == "events":
            item = section_data.get(clean_key.lower())
        return item if isinstance(item, dict) else {}

    def _apply_translation(
        self,
        target: dict[str, Any],
        section: str,
        key: Any,
        *,
        prefix: str = "",
    ) -> None:
        info = self._translation_item(section, key)
        if not info:
            return
        field_prefix = prefix.strip()

        def name(field: str) -> str:
            return f"{field_prefix}{field[:1].upper()}{field[1:]}" if field_prefix else field

        for src, dst in [
            ("labelKo", "labelKo"),
            ("labelEn", "labelEn"),
            ("krDesc", "krDesc"),
            ("krCategory", "krCategory"),
        ]:
            value = str(info.get(src) or "").strip()
            if value:
                target[name(dst)] = value
        candidates = info.get("labelKoCandidates")
        if isinstance(candidates, list) and candidates:
            target[name("labelKoCandidates")] = [
                str(item).strip()
                for item in candidates
                if str(item or "").strip()
            ]
        source = info.get("source")
        if isinstance(source, dict):
            target[name("translationSource")] = dict(source)

    def _translated_tag_labels(self, tags: list[str]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            info = self._translation_item("events", tag)
            label = str(info.get("labelKo") or "").strip()
            if not label:
                continue
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            labels.append(label)
        return labels

    def _load_thumbnail_index(self) -> dict[str, Any]:
        if not self.thumbnail_path.exists():
            raise FileNotFoundError("Event Preset thumbnail data is not installed.")
        with self._thumbnail_lock:
            if self._thumbnail_index is not None:
                return self._thumbnail_index
            with self.thumbnail_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("Event Preset thumbnail data must be a JSON object.")
            self._thumbnail_index = data
            return data

    def _prompt_atoms_with_identity(
        self,
        base_tags: list[str],
        rec_tags: list[str],
        rating: str,
        person: str,
    ) -> list[str]:
        person_tags = PERSON_TAG_MAP.get(person, [])
        rating_tag = self.RATING_SUFFIX_TAGS.get(rating, "")
        return self._unique(
            list(person_tags)
            + list(base_tags)
            + list(rec_tags)
            + ([rating_tag] if rating_tag else [])
        )

    def _recommendation_lookup(self, event: dict[str, Any]) -> dict[str, str]:
        lookup: dict[str, str] = {}

        def push(item: dict[str, Any]) -> None:
            item_id = str(item.get("id") or item.get("tag") or "")
            tag = str(item.get("tag") or item.get("id") or "")
            if item_id and tag:
                lookup[item_id] = tag

        for item in event.get("recommendedTags", []):
            if isinstance(item, dict):
                push(item)
        for item in event.get("directRecommendedTags", []):
            if isinstance(item, dict):
                push(item)
        for values in (event.get("slots") or {}).values():
            for item in values or []:
                if isinstance(item, dict):
                    push(item)
        return lookup

    def _base_tags_with_event(self, event: dict[str, Any], base_tags: list[str]) -> list[str]:
        base = self._unique(base_tags)
        base_keys = {self._prompt_key(tag) for tag in base if self._prompt_key(tag)}
        missing = [
            tag for tag in self._event_prompt_atoms(event)
            if self._prompt_key(tag) not in base_keys
        ]
        return self._unique([*missing, *base])

    @staticmethod
    def _event_prompt_atoms(event: dict[str, Any]) -> list[str]:
        atoms = event.get("promptAtoms")
        if isinstance(atoms, (list, tuple, set)):
            clean = [EventPresetService._prompt_atom(item) for item in atoms if EventPresetService._prompt_atom(item)]
            if clean:
                return clean
        for key in ("tag", "id", "label"):
            value = EventPresetService._prompt_atom(event.get(key))
            if value:
                return [value]
        return []

    @staticmethod
    def _prompt_key(value: Any) -> str:
        return " ".join(
            EventPresetService._prompt_atom(value)
            .lower()
            .replace("_", " ")
            .replace("-", " ")
            .split()
        )

    def _person_options(self, rating: str) -> list[dict[str, Any]]:
        available = self._data_manager.get_available_partitions()
        rating_label = self.RATING_NAMES.get(rating, "General")
        counts = self._partition_row_counts.get(rating_label, {})
        persons: list[dict[str, Any]] = []
        for person in PERSON_PARTITION_ORDER:
            partition = f"{rating}_{person}"
            if partition not in available:
                continue
            count = int(counts.get(person, 0) or 0)
            persons.append({
                "id": person,
                "label": PERSON_PARTITION_LABELS.get(person, person),
                "count": count,
                "displayCount": format_count(count),
            })
        return persons

    def _visible_events(self, partition_data: dict[str, Any]) -> set[str]:
        catalog = partition_data.get("catalog", pd.DataFrame())
        if not isinstance(catalog, pd.DataFrame) or catalog.empty:
            return set()
        return set(catalog["event_tag"].fillna("").astype(str).tolist())

    def _resolve_partition(self, rating: str, person: str) -> str:
        available = self._data_manager.get_available_partitions()
        partition = f"{rating}_{person}"
        if partition in available:
            return partition
        for candidate_person in PERSON_PARTITION_ORDER:
            candidate = f"{rating}_{candidate_person}"
            if candidate in available:
                return candidate
        if available:
            return sorted(available)[0]
        raise RuntimeError("No Event Preset partitions are available.")

    def _resolve_selected(
        self,
        categories: list[dict[str, Any]],
        requested: dict[str, Any],
    ) -> dict[str, Any]:
        selected = dict(requested)
        requested_event = str(requested.get("eventId") or "")
        requested_category = str(requested.get("categoryId") or "")
        requested_subcategory = str(requested.get("subcategoryId") or "")

        first_context: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None
        requested_context: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None
        for category in categories:
            for subcategory in category.get("subcategories", []):
                for event in subcategory.get("events", []):
                    context = (category, subcategory, event)
                    if first_context is None:
                        first_context = context
                    if requested_event and event.get("id") == requested_event:
                        requested_context = context
                        break
                    if (
                        requested_category
                        and category.get("id") == requested_category
                        and (not requested_subcategory or subcategory.get("id") == requested_subcategory)
                    ):
                        requested_context = context
                        break
                if requested_context:
                    break
            if requested_context:
                break

        context = requested_context or first_context
        if context:
            category, subcategory, event = context
            selected["categoryId"] = category.get("id", "")
            selected["subcategoryId"] = subcategory.get("id", "")
            selected["eventId"] = event.get("id", "")
        else:
            selected["categoryId"] = ""
            selected["subcategoryId"] = ""
            selected["eventId"] = ""
        return selected

    def _normalize_rating(self, value: str) -> str:
        raw = str(value or "").strip().lower()
        if raw in self.RATING_NAMES:
            return raw
        for key, name in self.RATING_NAMES.items():
            if raw == name.lower():
                return key
        return "s"

    def _normalize_person(self, value: str) -> str:
        raw = str(value or "").strip()
        raw = self.PERSON_ALIASES.get(raw, raw)
        return raw if raw in PERSON_PARTITION_ORDER else "1girl_solo"

    @staticmethod
    def _category_id(group: str, subgroup: str) -> str:
        return f"{group}::{subgroup}"

    @staticmethod
    def _subcategory_id(category_id: str, subcategory: str) -> str:
        return f"{category_id}::{subcategory or 'general'}"

    @staticmethod
    def _split_csv(text: Any) -> list[str]:
        if not isinstance(text, str):
            return []
        return [
            EventPresetService._prompt_atom(part)
            for part in text.split(",")
            if EventPresetService._prompt_atom(part)
        ]

    @staticmethod
    def _unique(tags: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for tag in tags:
            clean = EventPresetService._prompt_atom(tag)
            key = clean.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(clean)
        return result

    @staticmethod
    def _prompt_atom(value: Any) -> str:
        text = str(value or "").strip()
        while len(text) >= 2 and text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        return text

    @staticmethod
    def _combo_label(tags: list[str], event_tag: str) -> str:
        companions = [tag for tag in tags if tag.lower() != event_tag.lower()]
        label = ", ".join(companions[:3] or tags[:3])
        return label or event_tag
