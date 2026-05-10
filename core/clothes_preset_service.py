"""Server-safe Clothes Preset service for Remote Web."""

from __future__ import annotations

import hashlib
import io
import importlib.util
import json
import random
import sys
import threading
import types
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKAGE_FILE_NAME = "naia_clothes_preset"
CACHE_FILE_NAME = "viewer_clothes_cache_step34.pkl"
_RUNTIME_PACKAGE = "_naia_clothes_preset_runtime"
_RUNTIME_LOCK = threading.RLock()
DEFAULT_BROWSER_SLOT = "UPPER_BODY"


@dataclass(frozen=True)
class _RuntimeModules:
    data_manager: Any
    engines: Any


def _load_runtime_modules(source_dir: Path) -> _RuntimeModules:
    """Load Clothes Preset data/engine modules without importing its PyQt package."""
    source_dir = source_dir.resolve()
    with _RUNTIME_LOCK:
        package = sys.modules.get(_RUNTIME_PACKAGE)
        if package is None:
            package = types.ModuleType(_RUNTIME_PACKAGE)
            package.__file__ = str(source_dir / "__init__.py")
            package.__path__ = [str(source_dir)]
            package.__package__ = _RUNTIME_PACKAGE
            sys.modules[_RUNTIME_PACKAGE] = package

        data_name = f"{_RUNTIME_PACKAGE}.data_manager"
        engines_name = f"{_RUNTIME_PACKAGE}.engines"
        data_module = sys.modules.get(data_name)
        if data_module is None:
            data_module = _load_module(data_name, source_dir / "data_manager.py")
        engines_module = sys.modules.get(engines_name)
        if engines_module is None:
            engines_module = _load_module(engines_name, source_dir / "engines.py")
        return _RuntimeModules(data_module, engines_module)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Clothes Preset module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ClothesPresetService:
    """Read-only Clothes Preset data service that does not import desktop widgets."""

    SOURCE_TYPES = {"combo", "direct", "recommendation", "manual"}

    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root)
        self.data_path = self.repo_root / "ui" / "clothes_preset"
        self.translation_path = self.data_path / "clothes_preset_translations_ko.json"
        self.kr_tags_path = self.repo_root / "data" / "KR_tags.parquet"
        self._lock = threading.RLock()
        self._modules: _RuntimeModules | None = None
        self._data_manager: Any | None = None
        self._data_ready = False
        self._data_error = ""
        self._cache_status = ""

        self._combo_summaries: list[Any] = []
        self._combo_summaries_ge2: list[Any] = []
        self._combo_tag_to_ids: dict[str, set[int]] = {}
        self._combo_id_lookup: dict[str, Any] = {}
        self._combo_text_lookup: dict[str, Any] = {}

        self._region_tags: list[Any] = []
        self._tag_to_region: dict[str, str] = {}
        self._assigned_slot_by_tag: dict[str, str] = {}
        self._assigned_group_by_tag: dict[str, str] = {}
        self._assigned_row_by_tag: dict[str, Any] = {}
        self._slot_rows_cache: dict[str, list[Any]] = {}

        self._reco_by_seed: dict[str, list[dict[str, Any]]] = {}
        self._avoid_by_seed: dict[str, list[dict[str, Any]]] = {}
        self._pair_by_seed: dict[str, list[dict[str, Any]]] = {}
        self._conflict_pairs: set[tuple[str, str]] = set()
        self._conflict_exclusion_score: dict[tuple[str, str], float] = {}
        self._translation_payload: dict[str, Any] | None = None
        self._kr_tag_payload: dict[str, dict[str, str]] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        package_path = self.data_path / PACKAGE_FILE_NAME
        main_state = "missing"
        message = "Clothes Preset data is not installed."

        if package_path.exists():
            try:
                with zipfile.ZipFile(package_path, "r") as zf:
                    has_data = any(name.endswith(".parquet") or name.endswith(".pkl") for name in zf.namelist())
                if has_data:
                    main_state = "ready"
                    message = "Clothes Preset data is ready."
                else:
                    main_state = "error"
                    message = "Clothes Preset archive exists but contains no supported data files."
            except zipfile.BadZipFile:
                main_state = "error"
                message = "Clothes Preset data is not a valid ZIP archive."
            except Exception as exc:
                main_state = "error"
                message = f"Clothes Preset data check failed: {exc}"
        elif any((self.data_path / name).exists() for name in self._required_data_files()):
            main_state = "ready"
            message = "Clothes Preset loose parquet data is ready."

        counts: dict[str, Any] = {"combos": 0, "comboIdeas": 0, "items": 0, "slots": 0}
        if self._data_ready:
            counts = {
                "combos": len(self._combo_summaries),
                "comboIdeas": len(self._combo_summaries_ge2),
                "items": len(self._assigned_slot_by_tag),
                "slots": len(self._display_slots()),
                "cacheStatus": self._cache_status,
            }

        return {
            "ok": True,
            "dataMode": "real" if main_state == "ready" else main_state,
            "dataAvailability": {
                "main": main_state,
                "message": message if not self._data_error else self._data_error,
            },
            "paths": {
                "main": str(self.data_path.relative_to(self.repo_root)),
                "package": str((self.data_path / PACKAGE_FILE_NAME).relative_to(self.repo_root)),
            },
            "counts": counts,
            "capabilities": self._capabilities(main_state == "ready"),
        }

    def bootstrap(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = self._coerce_payload(payload, kwargs)
        status = self.status()
        if status["dataAvailability"]["main"] != "ready":
            return {
                "ok": True,
                "dataMode": status["dataMode"],
                "dataAvailability": status["dataAvailability"],
                "capabilities": status["capabilities"],
                "pairModes": [],
                "selected": self._empty_selected(request),
                "comboRows": self._empty_combo_rows(),
                "browser": self._empty_browser(),
                "staged": self._empty_staged(),
                "promptFragment": self._empty_fragment(),
                "rules": self._empty_rules("Balanced"),
            }

        self._ensure_ready()
        normalized = self._normalize_selection(request)
        combo_rows = self._combo_rows_for_selection(request, normalized)
        browser = self._browser_for_selection(request, normalized)
        selected = dict(normalized["selected"], **browser.get("selected", {}))
        fragment = self._fragment_for_selection(normalized)
        return {
            "ok": True,
            "dataMode": "real",
            "dataAvailability": status["dataAvailability"],
            "capabilities": self._capabilities(True),
            "pairModes": self._pair_modes(),
            "selected": selected,
            "comboRows": combo_rows,
            "browser": browser,
            "staged": normalized["staged"],
            "promptFragment": fragment,
            "rules": self._rules_payload(normalized),
        }

    def select(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = self._coerce_payload(payload, kwargs)
        status = self.status()
        if status["dataAvailability"]["main"] != "ready":
            return {
                "ok": True,
                "dataMode": status["dataMode"],
                "dataAvailability": status["dataAvailability"],
                "selected": self._empty_selected(request),
                "combo": None,
                "comboRows": self._empty_combo_rows(),
                "browser": self._empty_browser(),
                "staged": self._empty_staged(),
                "promptFragment": self._empty_fragment(),
                "rules": self._empty_rules(self._normalize_pair_mode(request.get("pairMode"))),
            }

        self._ensure_ready()
        normalized = self._normalize_selection(request)
        combo = self._combo_detail(normalized["selected"].get("comboId", ""))
        browser = self._browser_for_selection(request, normalized)
        selected = dict(normalized["selected"], **browser.get("selected", {}))
        return {
            "ok": True,
            "requestId": str(request.get("requestId") or ""),
            "dataMode": "real",
            "dataAvailability": status["dataAvailability"],
            "selected": selected,
            "combo": combo,
            "comboRows": self._combo_rows_for_selection(request, normalized),
            "browser": browser,
            "staged": normalized["staged"],
            "promptFragment": self._fragment_for_selection(normalized),
            "rules": self._rules_payload(normalized),
        }

    def lucky(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """Return one rich random combo for Web Lucky focus without mutating staging."""
        request = self._coerce_payload(payload, kwargs)
        status = self.status()
        if status["dataAvailability"]["main"] != "ready":
            return {
                "ok": True,
                "dataMode": status["dataMode"],
                "dataAvailability": status["dataAvailability"],
                "selected": self._empty_selected(request),
                "combo": None,
                "comboRows": self._empty_combo_rows(),
                "browser": self._empty_browser(),
                "staged": self._empty_staged(),
                "promptFragment": self._empty_fragment(),
                "rules": self._empty_rules(self._normalize_pair_mode(request.get("pairMode"))),
            }

        self._ensure_ready()
        normalized = self._normalize_selection(request)
        seed_tags = self._lucky_seed_tags(normalized)
        candidates = self._lucky_candidates(seed_tags)
        if not candidates:
            if seed_tags:
                raise ValueError("No Clothes Preset lucky combo is available for staged items.")
            raise ValueError("No Clothes Preset lucky combo is available.")
        chosen = random.choice(candidates)
        tags = [str(tag) for tag in chosen.tags]
        combo_id = self._combo_id(str(chosen.clothing_combo))
        return {
            "ok": True,
            "dataMode": "real",
            "dataAvailability": status["dataAvailability"],
            "selected": normalized["selected"],
            "lucky": {
                "comboId": combo_id,
                "comboText": str(chosen.clothing_combo),
                "tags": tags,
                "count": int(chosen.post_count),
                "displayCount": self._format_count(int(chosen.post_count)),
                "tagCount": int(chosen.tag_count),
                "basis": "staged" if seed_tags else "global",
                "seedTags": seed_tags,
                "matchedTags": [tag for tag in seed_tags if tag in set(tags)],
            },
            "promptFragment": {
                "tags": tags,
                "prompt": ", ".join(tags),
                "sources": {"lucky": len(tags)},
            },
        }

    def _lucky_seed_tags(self, normalized: dict[str, Any]) -> list[str]:
        staged = normalized.get("staged") or {}
        return self._ordered_unique(staged.get("tags") or staged.get("ruleSeedTags") or [])

    def _lucky_candidates(self, seed_tags: list[str]) -> list[Any]:
        def eligible(combo: Any, min_tags: int) -> bool:
            combo_text = str(combo.clothing_combo)
            return (
                int(combo.tag_count) >= min_tags
                and "cosplay" not in combo_text
                and "alternate" not in combo_text
            )

        if not seed_tags:
            return [combo for combo in self._combo_summaries if eligible(combo, 4)]

        staged = [tag for tag in seed_tags if tag]
        sets = [self._combo_tag_to_ids.get(tag, set()) for tag in staged]
        if not sets or any(not ids for ids in sets):
            return []
        sets.sort(key=len)
        id_set = set(sets[0])
        for ids_for_tag in sets[1:]:
            id_set.intersection_update(ids_for_tag)
            if not id_set:
                return []

        min_tags = max(4, len(staged))
        staged_sig = tuple(sorted(set(staged)))
        candidates: list[Any] = []
        for idx in sorted(id_set):
            if idx < 0 or idx >= len(self._combo_summaries):
                continue
            combo = self._combo_summaries[idx]
            combo_sig = tuple(sorted(set(str(tag) for tag in combo.tags)))
            if combo_sig == staged_sig:
                continue
            if eligible(combo, min_tags):
                candidates.append(combo)
        return candidates

    def combo_rows(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = self._coerce_payload(payload, kwargs)
        self._ensure_ready()
        normalized = self._normalize_selection(request)
        return {
            "ok": True,
            "selected": normalized["selected"],
            "comboRows": self._combo_rows_for_selection(request, normalized),
            "staged": normalized["staged"],
        }

    def browser(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = self._coerce_payload(payload, kwargs)
        self._ensure_ready()
        normalized = self._normalize_selection(request)
        return {
            "ok": True,
            "selected": normalized["selected"],
            "browser": self._browser_for_selection(request, normalized),
            "staged": normalized["staged"],
            "rules": self._rules_payload(normalized),
        }

    def normalize_staging(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = self._coerce_payload(payload, kwargs)
        self._ensure_ready()
        normalized = self._normalize_selection(request)
        return {
            "ok": True,
            "selected": normalized["selected"],
            "staged": normalized["staged"],
            "rules": self._rules_payload(normalized),
        }

    def prompt_fragment(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = self._coerce_payload(payload, kwargs)
        self._ensure_ready()
        normalized = self._normalize_selection(request)
        return {"ok": True, "promptFragment": self._fragment_for_selection(normalized)}

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------

    def _ensure_modules(self) -> _RuntimeModules:
        if self._modules is None:
            self._modules = _load_runtime_modules(self.data_path)
        return self._modules

    def _ensure_ready(self) -> None:
        with self._lock:
            if self._data_ready:
                return
            if self._data_error:
                raise RuntimeError(self._data_error)

            modules = self._ensure_modules()
            try:
                self._data_manager = modules.data_manager.ClothesPresetDataManager(self.data_path)
                self._install_safe_cache_loader(self._data_manager, modules)
                if not self._data_manager.is_data_available():
                    self._data_error = "Required Clothes Preset data files are missing."
                    raise RuntimeError(self._data_error)
                payload = self._data_manager.load_all()
            except Exception as exc:
                self._data_error = f"Clothes Preset data load failed: {exc}"
                raise

            self._combo_summaries = list(payload.get("combo_summaries", []))
            self._combo_summaries_ge2 = list(payload.get("combo_summaries_ge2", []))
            self._combo_tag_to_ids = {
                str(tag): set(ids)
                for tag, ids in dict(payload.get("combo_tag_to_ids", {})).items()
            }
            self._region_tags = list(payload.get("region_tags", []))
            self._tag_to_region = dict(payload.get("tag_to_region", {}))
            self._reco_by_seed = dict(payload.get("reco_by_seed", {}))
            self._avoid_by_seed = dict(payload.get("avoid_by_seed", {}))
            self._pair_by_seed = dict(payload.get("pair_by_seed", {}))
            self._conflict_pairs = set(payload.get("conflict_pairs", set()))
            self._conflict_exclusion_score = dict(payload.get("conflict_exclusion_score", {}))
            self._cache_status = str(payload.get("cache_status") or "")

            if payload.get("assigned_slot_by_tag"):
                self._assigned_slot_by_tag = dict(payload["assigned_slot_by_tag"])
                self._assigned_group_by_tag = dict(payload["assigned_group_by_tag"])
                self._assigned_row_by_tag = dict(payload["assigned_row_by_tag"])
                self._slot_rows_cache = {
                    slot: list(rows)
                    for slot, rows in dict(payload["slot_rows_cache"]).items()
                }
            else:
                taxonomy = modules.engines.ClothingTaxonomyEngine()
                result = taxonomy.rebuild_slot_assignment(self._region_tags)
                self._assigned_slot_by_tag = dict(result["assigned_slot_by_tag"])
                self._assigned_group_by_tag = dict(result["assigned_group_by_tag"])
                self._assigned_row_by_tag = dict(result["assigned_row_by_tag"])
                self._slot_rows_cache = {
                    slot: list(rows)
                    for slot, rows in dict(result["slot_rows_cache"]).items()
                }

            self._combo_id_lookup = {}
            self._combo_text_lookup = {}
            for combo in self._combo_summaries:
                combo_id = self._combo_id(str(combo.clothing_combo))
                self._combo_id_lookup[combo_id] = combo
                self._combo_text_lookup[str(combo.clothing_combo)] = combo

            self._data_ready = True

    def _install_safe_cache_loader(self, manager: Any, modules: _RuntimeModules) -> None:
        def loads_payload(raw: bytes) -> dict[str, Any] | None:
            try:
                return modules.data_manager._CacheUnpickler(io.BytesIO(raw)).load()
            except Exception:
                return None

        manager._loads_payload = loads_payload

    # ------------------------------------------------------------------
    # Selection and staging
    # ------------------------------------------------------------------

    def _normalize_selection(self, payload: dict[str, Any]) -> dict[str, Any]:
        modules = self._ensure_modules()
        pair_mode = self._normalize_pair_mode(payload.get("pairMode"))
        selected_combo = self._resolve_combo(payload)
        selected_combo_id = self._combo_id(str(selected_combo.clothing_combo)) if selected_combo else ""
        selected_combo_text = str(selected_combo.clothing_combo) if selected_combo else ""
        action = str(payload.get("action") or "").strip()

        staged_items = [] if action == "clearAll" else self._input_staged_items(payload)

        should_stage_combo = bool(
            payload.get("applyComboTags")
            or payload.get("stageCombo")
            or action in {"stageCombo", "applyComboTags"}
        )
        if should_stage_combo and selected_combo is not None:
            for tag in selected_combo.tags:
                staged_items.append({
                    "tag": str(tag),
                    "source": "combo",
                    "sourceId": selected_combo_id,
                    "sourceLabel": selected_combo_text,
                })

        if action == "addItem":
            item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
            staged_items.append({
                "tag": item.get("tag") or item.get("id") or "",
                "slot": item.get("slot") or item.get("group") or payload.get("categoryId") or "",
                "source": item.get("source") or "direct",
                "sourceId": item.get("sourceId") or "",
            })

        remove_tags = self._remove_tags(payload)
        clear_slot = str(payload.get("clearSlot") or "").strip()
        if action == "clearSlot":
            clear_slot = clear_slot or str(payload.get("categoryId") or payload.get("slot") or "").strip()
        if action == "removeItem":
            item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
            remove_tags.add(self._normalize_tag(item.get("tag") or item.get("id") or ""))

        by_slot: dict[str, list[dict[str, Any]]] = {slot: [] for slot in self._display_slots()}
        seen: set[str] = set()
        for raw_item in staged_items:
            item = self._normalize_stage_item(raw_item, default_source="direct")
            tag = item["tag"]
            if not tag or tag in seen or tag in remove_tags:
                continue
            slot = item["slot"]
            if clear_slot and slot == clear_slot:
                continue
            seen.add(tag)
            by_slot.setdefault(slot, []).append(item)

        region_staged = {
            slot: [item["tag"] for item in by_slot.get(slot, [])]
            for slot in self._display_slots()
        }
        promoted = modules.engines.compute_promoted_tags(
            region_staged,
            self._assigned_row_by_tag,
            self._assigned_group_by_tag,
        )
        prompt_tags = self._ordered_unique([
            tag
            for slot in self._display_slots()
            for tag in region_staged.get(slot, [])
        ])
        rule_seed_tags = self._ordered_unique([
            tag
            for slot in self._display_slots()
            for tag in region_staged.get(slot, [])
            if tag in promoted
        ])
        issue_map = modules.engines.RulesEngine.compute_staging_issue_map(
            prompt_tags,
            self._avoid_by_seed,
            self._conflict_pairs,
            self._conflict_exclusion_score,
        )

        flat_items: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []
        for slot in self._display_slots():
            slot_items: list[dict[str, Any]] = []
            for item in by_slot.get(slot, []):
                shaped = dict(item)
                shaped["promoted"] = item["tag"] in promoted
                shaped["issues"] = issue_map.get(item["tag"], [])
                slot_items.append(shaped)
                flat_items.append(shaped)
            groups.append({
                "id": slot,
                "label": self._slot_label(slot),
                "labelKo": self._slot_label_ko(slot),
                "tags": [item["tag"] for item in slot_items],
                "items": slot_items,
            })

        staged = {
            "items": flat_items,
            "groups": groups,
            "tags": prompt_tags,
            "promotedTags": rule_seed_tags,
            "ruleSeedTags": rule_seed_tags,
            "issues": issue_map,
            "sourceCounts": self._source_counts(flat_items),
        }
        selected = {
            "comboId": selected_combo_id,
            "comboText": selected_combo_text,
            "ratingId": str(payload.get("ratingId") or ""),
            "pairMode": pair_mode,
            "categoryId": self._normalize_slot(payload.get("categoryId") or payload.get("slot") or ""),
            "subcategoryId": str(payload.get("subcategoryId") or payload.get("subgroup") or ""),
            "search": str(payload.get("search") or ""),
            "comboSearch": str(payload.get("comboSearch") or payload.get("searchCombos") or payload.get("search") or ""),
            "itemSearch": str(payload.get("itemSearch") or payload.get("searchItems") or ""),
        }
        return {"selected": selected, "staged": staged}

    def _input_staged_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[Any] = []
        for key in ("amendedItems", "stagedItems", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)

        for tag in payload.get("stagedTags", []) if isinstance(payload.get("stagedTags"), list) else []:
            candidates.append({"tag": tag, "source": "direct"})

        normalized: list[dict[str, Any]] = []
        for item in candidates:
            if isinstance(item, dict):
                normalized.append(dict(item))
            elif isinstance(item, str):
                normalized.append({"tag": item, "source": "direct"})
        return normalized

    def _normalize_stage_item(self, item: dict[str, Any], default_source: str) -> dict[str, Any]:
        tag = self._normalize_tag(item.get("tag") or item.get("id") or item.get("name") or "")
        slot = self._normalize_slot(item.get("slot") or item.get("group") or "")
        if not slot:
            slot = self._slot_for_tag(tag)
        source = str(item.get("source") or default_source or "direct")
        if source not in self.SOURCE_TYPES:
            source = default_source if default_source in self.SOURCE_TYPES else "direct"
        row = self._assigned_row_by_tag.get(tag)
        subgroup = self._assigned_group_by_tag.get(tag, "other")
        post_count = int(getattr(row, "post_count", 0) or 0) if row is not None else 0
        return {
            "id": self._item_id(tag),
            "tag": tag,
            "slot": slot,
            "slotLabel": self._slot_label(slot),
            "slotLabelKo": self._slot_label_ko(slot),
            "group": subgroup,
            "groupLabelKo": self._group_label_ko(subgroup),
            "source": source,
            "sourceId": str(item.get("sourceId") or ""),
            "sourceLabel": str(item.get("sourceLabel") or ""),
            "postCount": post_count,
            "displayCount": self._format_count(post_count),
            **self._tag_translation_fields(tag),
        }

    def _remove_tags(self, payload: dict[str, Any]) -> set[str]:
        result: set[str] = set()
        for key in ("removeTags", "removedTags"):
            values = payload.get(key)
            if isinstance(values, list):
                result.update(self._normalize_tag(value) for value in values)
        for key in ("removeTag", "removedTag"):
            if payload.get(key):
                result.add(self._normalize_tag(payload.get(key)))
        item_id = str(payload.get("removeItemId") or payload.get("removedItemId") or "").strip()
        if item_id:
            for item in self._input_staged_items(payload):
                tag = self._normalize_tag(item.get("tag") or item.get("id") or "")
                if item_id in {str(item.get("id") or ""), self._item_id(tag), tag}:
                    result.add(tag)
        return {tag for tag in result if tag}

    # ------------------------------------------------------------------
    # Combo rows
    # ------------------------------------------------------------------

    def _combo_rows_for_selection(self, payload: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
        search = str(
            payload.get("comboSearch")
            or payload.get("searchCombos")
            or normalized["selected"].get("comboSearch")
            or ""
        )
        limit = self._limit(payload.get("comboLimit"), self._max_combo_rows())
        staged_tags = self._combo_staged_tags(payload, normalized)
        rows, base_count, hidden_exact, ignored_search = self._filter_combo_rows(
            search=search,
            staged_tags=staged_tags,
            selected_combo_id=normalized["selected"].get("comboId", ""),
            limit=limit,
        )
        suffix = ""
        if staged_tags:
            suffix = "match staged"
            if hidden_exact:
                suffix += f", exact hidden={hidden_exact:,}"
        return {
            "rows": rows,
            "shown": len(rows),
            "total": int(base_count),
            "hiddenExact": int(hidden_exact),
            "limit": limit,
            "search": search,
            "ignoredSearch": ignored_search,
            "summary": f"{len(rows):,} / {int(base_count):,} observed combos"
            + (f" ({suffix})" if suffix else ""),
        }

    def _combo_staged_tags(self, payload: dict[str, Any], normalized: dict[str, Any]) -> list[str]:
        explicit = payload.get("comboStagedTags")
        if isinstance(explicit, list):
            tags = [self._normalize_tag(tag) for tag in explicit]
            return self._ordered_unique([tag for tag in tags if tag])
        return self._ordered_unique(normalized["staged"].get("tags") or normalized["staged"].get("ruleSeedTags") or [])

    def _filter_combo_rows(
        self,
        search: str,
        staged_tags: list[str],
        selected_combo_id: str,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int, int, bool]:
        keyword = self._normalize_tag(search)
        ignored_search = bool(keyword and len(keyword) < 2)
        if ignored_search:
            keyword = ""
        staged = [tag for tag in staged_tags if tag]
        staged_sig = tuple(sorted(set(staged))) if staged else ()
        hidden_exact = 0
        rows: list[Any] = []
        base_count = 0

        if staged:
            sets = [self._combo_tag_to_ids.get(tag, set()) for tag in staged]
            if not sets or any(not ids for ids in sets):
                ids: list[int] = []
            else:
                sets.sort(key=len)
                id_set = set(sets[0])
                for ids_for_tag in sets[1:]:
                    id_set.intersection_update(ids_for_tag)
                    if not id_set:
                        break
                ids = sorted(id_set)
            min_tags = max(2, len(staged))
            for idx in ids:
                if idx < 0 or idx >= len(self._combo_summaries):
                    continue
                combo = self._combo_summaries[idx]
                if int(combo.tag_count) < min_tags:
                    continue
                if staged_sig and tuple(combo.tags) == staged_sig:
                    hidden_exact += 1
                    continue
                if keyword and keyword not in str(combo.clothing_combo):
                    continue
                base_count += 1
                if len(rows) < limit:
                    rows.append(combo)
        elif not keyword:
            rows = self._combo_summaries_ge2[:limit]
            base_count = len(self._combo_summaries_ge2)
        else:
            for combo in self._combo_summaries_ge2:
                if keyword not in str(combo.clothing_combo):
                    continue
                base_count += 1
                if len(rows) < limit:
                    rows.append(combo)

        return [
            self._combo_row(combo, selected_combo_id, staged)
            for combo in rows
        ], base_count, hidden_exact, ignored_search

    def _combo_row(self, combo: Any, selected_combo_id: str, staged_tags: list[str]) -> dict[str, Any]:
        combo_id = self._combo_id(str(combo.clothing_combo))
        tags = [str(tag) for tag in combo.tags]
        return {
            "id": combo_id,
            "comboText": str(combo.clothing_combo),
            "prompt": str(combo.clothing_combo),
            "tags": tags,
            "labelKo": ", ".join(self._translated_tag_labels(tags)[:4]),
            "count": int(combo.post_count),
            "displayCount": self._format_count(int(combo.post_count)),
            "tagCount": int(combo.tag_count),
            "selected": combo_id == selected_combo_id,
            "matchesStaged": bool(staged_tags) and all(tag in set(tags) for tag in staged_tags),
            "matchedTags": [tag for tag in staged_tags if tag in set(tags)],
            "actions": {
                "stageComboTags": True,
            },
        }

    # ------------------------------------------------------------------
    # Browser rows
    # ------------------------------------------------------------------

    def _browser_for_selection(self, payload: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
        category_id = normalized["selected"].get("categoryId") or self._first_slot()
        if category_id not in self._display_slots():
            category_id = self._first_slot()
        item_search = str(payload.get("itemSearch") or payload.get("searchItems") or "")
        search_active = bool(self._normalize_tag(item_search))
        rule_context = self._slot_candidate_context(normalized)
        if search_active and self._all_slot_browser_search_requested(payload):
            return self._browser_for_all_slot_search(payload, normalized, item_search, rule_context)
        base_rows, base_signal_cache = self._slot_candidate_rows(
            category_id,
            "",
            normalized,
            limit_rows=False,
            rule_context=rule_context,
        )
        if search_active:
            rows, signal_cache = self._slot_candidate_rows(
                category_id,
                item_search,
                normalized,
                limit_rows=False,
                rule_context=rule_context,
            )
        else:
            rows, signal_cache = base_rows, base_signal_cache
        if search_active and not rows:
            for slot in self._display_slots():
                if slot == category_id:
                    continue
                candidate_rows, candidate_signal_cache = self._slot_candidate_rows(
                    slot,
                    item_search,
                    normalized,
                    limit_rows=False,
                    rule_context=rule_context,
                )
                if not candidate_rows:
                    continue
                category_id = slot
                rows = candidate_rows
                signal_cache = candidate_signal_cache
                base_rows, base_signal_cache = self._slot_candidate_rows(
                    category_id,
                    "",
                    normalized,
                    limit_rows=False,
                    rule_context=rule_context,
                )
                break
        subgroups = self._merge_browser_subgroups(
            self._subgroups_from_rows(base_rows, base_signal_cache),
            self._subgroups_from_rows(rows, signal_cache),
            search_active=search_active,
        )
        subcategory_id = normalized["selected"].get("subcategoryId") or ""
        subgroup_by_id = {item["id"]: item for item in subgroups}
        selected_subgroup = subgroup_by_id.get(subcategory_id)
        if not selected_subgroup or (search_active and selected_subgroup.get("disabled")):
            first_enabled = next((item for item in subgroups if not item.get("disabled")), None)
            subcategory_id = (first_enabled or subgroups[0])["id"] if subgroups else ""
        item_limit = self._limit(payload.get("itemLimit"), self._max_items_per_slot())
        items = [
            self._browser_item(row, normalized, signal_cache)
            for row in rows
            if self._assigned_group_by_tag.get(str(row.tag), "other") == subcategory_id
        ][:item_limit]

        categories = []
        staged_by_slot = {
            group["id"]: len(group.get("items") or [])
            for group in normalized["staged"]["groups"]
        }
        for slot in self._display_slots():
            slot_base_rows, _slot_base_signal = self._slot_candidate_rows(
                slot,
                "",
                normalized,
                limit_rows=False,
                rule_context=rule_context,
            )
            if search_active and slot == category_id:
                slot_match_rows = rows
            elif search_active:
                slot_match_rows, _slot_match_signal = self._slot_candidate_rows(
                    slot,
                    item_search,
                    normalized,
                    limit_rows=False,
                    rule_context=rule_context,
                )
            else:
                slot_match_rows = slot_base_rows
            total = len(slot_base_rows)
            subcategory_count = len({
                self._assigned_group_by_tag.get(str(row.tag), "other")
                for row in slot_base_rows
            })
            matched_subcategory_count = len({
                self._assigned_group_by_tag.get(str(row.tag), "other")
                for row in slot_match_rows
            })
            categories.append({
                "id": slot,
                "label": self._slot_label(slot),
                "labelKo": self._slot_label_ko(slot),
                "count": total,
                "matchedCount": len(slot_match_rows),
                "subcategoryCount": subcategory_count,
                "matchedSubcategoryCount": matched_subcategory_count,
                "selectedCount": int(staged_by_slot.get(slot, 0) or 0),
                "disabled": bool(search_active and not slot_match_rows),
                "selected": slot == category_id,
            })

        return {
            "selected": {
                "categoryId": category_id,
                "subcategoryId": subcategory_id,
            },
            "categories": categories,
            "subcategories": [
                dict(item, selected=item["id"] == subcategory_id)
                for item in subgroups
            ],
            "items": items,
            "search": item_search,
            "searchActive": search_active,
            "limit": item_limit,
        }

    def _all_slot_browser_search_requested(self, payload: dict[str, Any]) -> bool:
        scope = str(payload.get("searchScope") or "").strip().lower().replace("-", "").replace("_", "")
        if scope in {"all", "allslots", "global", "catalog"}:
            return True
        flag = payload.get("allSlots")
        if isinstance(flag, str):
            return flag.strip().lower() in {"1", "true", "yes", "on"}
        return bool(flag)

    def _browser_for_all_slot_search(
        self,
        payload: dict[str, Any],
        normalized: dict[str, Any],
        item_search: str,
        rule_context: dict[str, Any],
    ) -> dict[str, Any]:
        display_slots = self._display_slots()
        selected_category_id = normalized["selected"].get("categoryId") or ""
        if selected_category_id not in display_slots:
            selected_category_id = ""

        base_rows_by_slot: dict[str, list[Any]] = {}
        base_signal_by_slot: dict[str, dict[str, tuple[float, float, int, int]]] = {}
        match_rows_by_slot: dict[str, list[Any]] = {}
        match_signal_by_slot: dict[str, dict[str, tuple[float, float, int, int]]] = {}
        first_match_slot = ""
        row_by_tag: dict[str, Any] = {}
        signal_cache: dict[str, tuple[float, float, int, int]] = {}

        for slot in display_slots:
            base_rows, base_signal = self._slot_candidate_rows(
                slot,
                "",
                normalized,
                limit_rows=False,
                rule_context=rule_context,
            )
            match_rows, match_signal = self._slot_candidate_rows(
                slot,
                item_search,
                normalized,
                limit_rows=False,
                rule_context=rule_context,
            )
            base_rows_by_slot[slot] = base_rows
            base_signal_by_slot[slot] = base_signal
            match_rows_by_slot[slot] = match_rows
            match_signal_by_slot[slot] = match_signal
            if match_rows and not first_match_slot:
                first_match_slot = slot
            for row in match_rows:
                tag = str(row.tag)
                row_by_tag.setdefault(tag, row)
                signal_cache[tag] = match_signal.get(tag, (0.0, 0.0, 0, 0))

        if selected_category_id and match_rows_by_slot.get(selected_category_id):
            category_id = selected_category_id
        else:
            category_id = first_match_slot or selected_category_id or self._first_slot()

        base_rows = base_rows_by_slot.get(category_id, [])
        match_rows = match_rows_by_slot.get(category_id, [])
        subgroups = self._merge_browser_subgroups(
            self._subgroups_from_rows(base_rows, base_signal_by_slot.get(category_id, {})),
            self._subgroups_from_rows(match_rows, match_signal_by_slot.get(category_id, {})),
            search_active=True,
        )
        subcategory_id = normalized["selected"].get("subcategoryId") or ""
        subgroup_by_id = {item["id"]: item for item in subgroups}
        selected_subgroup = subgroup_by_id.get(subcategory_id)
        if not selected_subgroup or selected_subgroup.get("disabled"):
            first_enabled = next((item for item in subgroups if not item.get("disabled")), None)
            subcategory_id = (first_enabled or subgroups[0])["id"] if subgroups else ""

        selected_tags = rule_context["selectedTags"]
        all_rows = list(row_by_tag.values())
        all_rows.sort(
            key=lambda row: (
                0 if str(row.tag) in selected_tags else 1,
                -signal_cache.get(str(row.tag), (0.0, 0.0, 0, 0))[0],
                -signal_cache.get(str(row.tag), (0.0, 0.0, 0, 0))[1],
                -signal_cache.get(str(row.tag), (0.0, 0.0, 0, 0))[2],
                -signal_cache.get(str(row.tag), (0.0, 0.0, 0, 0))[3],
                -int(row.post_count),
                str(row.tag),
            )
        )
        item_limit = self._limit(payload.get("itemLimit"), self._max_items_per_slot())
        items = [
            self._browser_item(row, normalized, signal_cache)
            for row in all_rows[:item_limit]
        ]

        staged_by_slot = {
            group["id"]: len(group.get("items") or [])
            for group in normalized["staged"]["groups"]
        }
        categories = []
        for slot in display_slots:
            slot_base_rows = base_rows_by_slot.get(slot, [])
            slot_match_rows = match_rows_by_slot.get(slot, [])
            total = len(slot_base_rows)
            subcategory_count = len({
                self._assigned_group_by_tag.get(str(row.tag), "other")
                for row in slot_base_rows
            })
            matched_subcategory_count = len({
                self._assigned_group_by_tag.get(str(row.tag), "other")
                for row in slot_match_rows
            })
            categories.append({
                "id": slot,
                "label": self._slot_label(slot),
                "labelKo": self._slot_label_ko(slot),
                "count": total,
                "matchedCount": len(slot_match_rows),
                "subcategoryCount": subcategory_count,
                "matchedSubcategoryCount": matched_subcategory_count,
                "selectedCount": int(staged_by_slot.get(slot, 0) or 0),
                "disabled": not bool(slot_match_rows),
                "selected": slot == category_id,
            })

        return {
            "selected": {
                "categoryId": category_id,
                "subcategoryId": subcategory_id,
            },
            "categories": categories,
            "subcategories": [
                dict(item, selected=item["id"] == subcategory_id)
                for item in subgroups
            ],
            "items": items,
            "search": item_search,
            "searchActive": True,
            "searchScope": "all",
            "limit": item_limit,
        }

    def _slot_candidate_context(self, normalized: dict[str, Any]) -> dict[str, Any]:
        staged = normalized["staged"]
        selected_tags = set(staged["tags"])
        rule_seed_tags = staged["ruleSeedTags"]
        pair_mode = normalized["selected"]["pairMode"]
        reco_agg, _avoid_agg, pair_agg = self._refresh_rules(rule_seed_tags, pair_mode)
        candidate_set: set[str] = set(selected_tags)
        if rule_seed_tags:
            candidate_set.update(reco_agg.keys())
            candidate_set.update(pair_agg.keys())
        return {
            "staged": staged,
            "selectedTags": selected_tags,
            "ruleSeedTags": rule_seed_tags,
            "recoAgg": reco_agg,
            "pairAgg": pair_agg,
            "candidateSet": candidate_set,
        }

    def _slot_candidate_rows(
        self,
        slot: str,
        search: str,
        normalized: dict[str, Any],
        *,
        limit_rows: bool = True,
        rule_context: dict[str, Any] | None = None,
    ) -> tuple[list[Any], dict[str, tuple[float, float, int, int]]]:
        context = rule_context or self._slot_candidate_context(normalized)
        staged = context["staged"]
        selected_tags = context["selectedTags"]
        rule_seed_tags = context["ruleSeedTags"]
        reco_agg = context["recoAgg"]
        pair_agg = context["pairAgg"]
        candidate_set = context["candidateSet"]

        rows = list(self._slot_rows_cache.get(slot, []))
        if rule_seed_tags:
            rows = [row for row in rows if str(row.tag) in candidate_set]

        slot_selected_tags = [
            item["tag"]
            for item in staged["items"]
            if item.get("slot") == slot
        ]
        if slot_selected_tags:
            slot_combo_ids = self._combo_ids_for_tags(slot_selected_tags)
            if slot_combo_ids:
                rows = [
                    row for row in rows
                    if str(row.tag) in selected_tags
                    or not self._combo_tag_to_ids.get(str(row.tag), set()).isdisjoint(slot_combo_ids)
                ]
            else:
                rows = [row for row in rows if str(row.tag) in selected_tags]

        keyword = self._normalize_tag(search)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.tag)
                or keyword in str(row.subgroup)
                or keyword in str(row.reason)
                or keyword in self._assigned_group_by_tag.get(str(row.tag), "")
            ]

        signal_cache = {
            str(row.tag): self._tag_signal(str(row.tag), reco_agg, pair_agg)
            for row in rows
        }
        rows.sort(
            key=lambda row: (
                0 if str(row.tag) in selected_tags else 1,
                -signal_cache[str(row.tag)][0],
                -signal_cache[str(row.tag)][1],
                -signal_cache[str(row.tag)][2],
                -signal_cache[str(row.tag)][3],
                -int(row.post_count),
                str(row.tag),
            )
        )
        max_rows = self._max_items_per_slot()
        if limit_rows and len(rows) > max_rows:
            rows = rows[:max_rows]
        return rows, signal_cache

    def _merge_browser_subgroups(
        self,
        base_subgroups: list[dict[str, Any]],
        matched_subgroups: list[dict[str, Any]],
        *,
        search_active: bool,
    ) -> list[dict[str, Any]]:
        matched_by_id = {str(item.get("id") or ""): item for item in matched_subgroups}
        result: list[dict[str, Any]] = []
        for subgroup in base_subgroups:
            subgroup_id = str(subgroup.get("id") or "")
            matched = matched_by_id.get(subgroup_id)
            matched_count = int(matched.get("count") or 0) if matched else 0
            shaped = dict(subgroup)
            shaped["matchedCount"] = matched_count if search_active else int(subgroup.get("count") or 0)
            shaped["matchedPostCount"] = int(matched.get("postCount") or 0) if matched else 0
            shaped["matchedDisplayCount"] = self._format_count(shaped["matchedPostCount"])
            shaped["disabled"] = bool(search_active and matched_count < 1)
            result.append(shaped)
        if search_active:
            result.sort(key=lambda item: bool(item.get("disabled")))
        return result

    def _subgroups_from_rows(
        self,
        rows: list[Any],
        signal_cache: dict[str, tuple[float, float, int, int]],
    ) -> list[dict[str, Any]]:
        by_subgroup: dict[str, list[Any]] = {}
        for row in rows:
            subgroup = self._assigned_group_by_tag.get(str(row.tag), "other")
            by_subgroup.setdefault(subgroup, []).append(row)

        def subgroup_key(subgroup: str) -> tuple[Any, ...]:
            items = by_subgroup[subgroup]
            reco_sum = 0.0
            reco_max = 0.0
            pair_conf_max = 0.0
            signal_hits = 0
            pair_conf_sum = 0.0
            pair_hits_sum = 0
            pair_max_count = 0
            post_sum = 0
            for item in items:
                rs, pc, ph, pcc = signal_cache.get(str(item.tag), (0.0, 0.0, 0, 0))
                if rs > 0.0 or pc > 0.0:
                    signal_hits += 1
                reco_sum += rs
                reco_max = max(reco_max, rs)
                pair_conf_max = max(pair_conf_max, pc)
                pair_conf_sum += pc
                pair_hits_sum += ph
                pair_max_count = max(pair_max_count, pcc)
                post_sum += int(item.post_count)
            return (
                -reco_sum,
                -reco_max,
                -pair_conf_max,
                -signal_hits,
                -pair_conf_sum,
                -pair_hits_sum,
                -pair_max_count,
                -post_sum,
                subgroup,
            )

        result: list[dict[str, Any]] = []
        for subgroup in sorted(by_subgroup, key=subgroup_key):
            items = by_subgroup[subgroup]
            post_count = sum(int(item.post_count) for item in items)
            result.append({
                "id": subgroup,
                "label": subgroup,
                "labelKo": self._group_label_ko(subgroup),
                "count": len(items),
                "postCount": post_count,
                "displayCount": self._format_count(post_count),
            })
        return result

    def _browser_item(
        self,
        row: Any,
        normalized: dict[str, Any],
        signal_cache: dict[str, tuple[float, float, int, int]],
    ) -> dict[str, Any]:
        tag = str(row.tag)
        selected = tag in set(normalized["staged"]["tags"])
        promoted = tag in set(normalized["staged"]["promotedTags"])
        conflicts = self._candidate_conflicts(tag, normalized["staged"]["tags"])
        reco_score, pair_conf, pair_hits, pair_count = signal_cache.get(tag, (0.0, 0.0, 0, 0))
        issues = list(normalized["staged"]["issues"].get(tag, []))
        issues.extend(conflicts)
        return {
            "id": self._item_id(tag),
            "tag": tag,
            "label": tag,
            **self._tag_translation_fields(tag),
            "slot": self._assigned_slot_by_tag.get(tag, ""),
            "slotLabel": self._slot_label(self._assigned_slot_by_tag.get(tag, "")),
            "slotLabelKo": self._slot_label_ko(self._assigned_slot_by_tag.get(tag, "")),
            "group": self._assigned_group_by_tag.get(tag, "other"),
            "groupLabelKo": self._group_label_ko(self._assigned_group_by_tag.get(tag, "other")),
            "postCount": int(row.post_count),
            "displayCount": self._format_count(int(row.post_count)),
            "selected": selected,
            "promoted": promoted,
            "incompatible": bool(issues),
            "issues": self._ordered_unique(issues),
            "recommendation": {
                "score": reco_score,
            },
            "pair": {
                "confidence": pair_conf,
                "hits": pair_hits,
                "maxPairCount": pair_count,
            },
            "source": "catalog",
        }

    # ------------------------------------------------------------------
    # Prompt and rules
    # ------------------------------------------------------------------

    def _fragment_for_selection(self, normalized: dict[str, Any]) -> dict[str, Any]:
        tags = list(normalized["staged"]["tags"])
        groups = []
        for group in normalized["staged"]["groups"]:
            items = list(group.get("items") or [])
            if not items:
                continue
            groups.append({
                "id": group["id"],
                "label": group["label"],
                "labelKo": group.get("labelKo", ""),
                "tags": [item["tag"] for item in items],
                "items": [
                    {
                        "id": item["id"],
                        "tag": item["tag"],
                        "labelKo": item.get("labelKo", ""),
                        "krDesc": item.get("krDesc", ""),
                        "source": item["source"],
                        "sourceId": item["sourceId"],
                        "group": item["group"],
                        "promoted": item["promoted"],
                    }
                    for item in items
                ],
            })
        return {
            "axisId": "clothes",
            "enabled": bool(tags),
            "tags": tags,
            "prompt": ", ".join(tags),
            "display": {
                "title": ", ".join(tags[:5]) if tags else "",
                "groups": groups,
            },
            "sources": normalized["staged"]["sourceCounts"],
            "warnings": self._fragment_warnings(normalized),
        }

    def _rules_payload(self, normalized: dict[str, Any]) -> dict[str, Any]:
        pair_mode = normalized["selected"]["pairMode"]
        seed_tags = normalized["staged"]["ruleSeedTags"]
        reco_agg, avoid_agg, pair_agg = self._refresh_rules(seed_tags, pair_mode)
        return {
            "pairMode": pair_mode,
            "seedTags": seed_tags,
            "issues": normalized["staged"]["issues"],
            "recommendations": self._rule_rows(reco_agg, "recommendation", "score", limit=24),
            "avoid": self._rule_rows(avoid_agg, "avoid", "score", limit=24),
            "pairs": self._rule_rows(pair_agg, "pair", "max_conf", limit=24),
        }

    def _refresh_rules(
        self,
        staged_tags: list[str],
        pair_mode: str,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        modules = self._ensure_modules()
        return modules.engines.RulesEngine.refresh_rules(
            staged_tags,
            self._reco_by_seed,
            self._avoid_by_seed,
            self._pair_by_seed,
            pair_mode,
        )

    def _rule_rows(
        self,
        rows: dict[str, dict[str, Any]],
        kind: str,
        sort_key: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        selected = sorted(
            rows.items(),
            key=lambda item: (
                -float(item[1].get(sort_key, item[1].get("score", 0.0)) or 0.0),
                -int(item[1].get("hits", 0) or 0),
                item[0],
            ),
        )[:limit]
        result: list[dict[str, Any]] = []
        for tag, metrics in selected:
            slot = self._slot_for_tag(tag)
            result.append({
                "id": self._item_id(tag),
                "tag": tag,
                "kind": kind,
                "slot": slot,
                "slotLabel": self._slot_label(slot),
                "slotLabelKo": self._slot_label_ko(slot),
                "group": self._assigned_group_by_tag.get(tag, "other"),
                "groupLabelKo": self._group_label_ko(self._assigned_group_by_tag.get(tag, "other")),
                **self._tag_translation_fields(tag),
                "metrics": self._json_metrics(metrics),
            })
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_combo(self, payload: dict[str, Any]) -> Any | None:
        combo_id = str(payload.get("comboId") or payload.get("selectedComboId") or "").strip()
        if combo_id and combo_id in self._combo_id_lookup:
            return self._combo_id_lookup[combo_id]
        combo_text = self._normalize_tag(payload.get("comboText") or payload.get("combo") or "")
        if combo_text and combo_text in self._combo_text_lookup:
            return self._combo_text_lookup[combo_text]
        return None

    def _combo_detail(self, combo_id: str) -> dict[str, Any] | None:
        combo = self._combo_id_lookup.get(str(combo_id or ""))
        if combo is None:
            return None
        return self._combo_row(combo, str(combo_id or ""), [])

    def _slot_for_tag(self, tag: str) -> str:
        tag = self._normalize_tag(tag)
        if tag in self._assigned_slot_by_tag:
            return self._assigned_slot_by_tag[tag]
        region = self._tag_to_region.get(tag, "")
        if region in {"LEGS", "FEET"}:
            return "LEGS_FEET"
        if region in self._display_slots():
            return region
        return "STYLE"

    def _combo_ids_for_tags(self, tags: list[str]) -> set[int]:
        sets = [self._combo_tag_to_ids.get(tag, set()) for tag in tags if tag]
        if not sets or any(not ids for ids in sets):
            return set()
        sets.sort(key=len)
        result = set(sets[0])
        for ids_for_tag in sets[1:]:
            result.intersection_update(ids_for_tag)
            if not result:
                break
        return result

    def _tag_signal(
        self,
        tag: str,
        reco_agg: dict[str, dict[str, Any]],
        pair_agg: dict[str, dict[str, Any]],
    ) -> tuple[float, float, int, int]:
        reco_score = float(reco_agg.get(tag, {}).get("score", 0.0))
        pair_conf = float(pair_agg.get(tag, {}).get("max_conf", 0.0))
        pair_hits = int(pair_agg.get(tag, {}).get("hits", 0))
        pair_count = int(pair_agg.get(tag, {}).get("max_pair", 0))
        return reco_score, pair_conf, pair_hits, pair_count

    def _candidate_conflicts(self, tag: str, staged_tags: list[str]) -> list[str]:
        result: list[str] = []
        for staged_tag in staged_tags:
            if not staged_tag or staged_tag == tag:
                continue
            key = tuple(sorted((tag, staged_tag)))
            if key in self._conflict_pairs:
                score = float(self._conflict_exclusion_score.get(key, 0.0))
                result.append(f"hard-conflict({score:.3f})")
        return result

    def _normalize_pair_mode(self, value: Any) -> str:
        modes = self._pair_mode_ids()
        raw = str(value or "").strip()
        for mode in modes:
            if raw.lower() == mode.lower():
                return mode
        return "Balanced"

    def _normalize_slot(self, value: Any) -> str:
        raw = str(value or "").strip()
        if raw in self._display_slots():
            return raw
        raw_upper = raw.upper()
        if raw_upper in self._display_slots():
            return raw_upper
        return ""

    def _normalize_tag(self, value: Any) -> str:
        modules = self._ensure_modules()
        return str(modules.data_manager.norm_text(value))

    def _format_count(self, value: int) -> str:
        modules = self._ensure_modules()
        return str(modules.data_manager.fmt_k_count(int(value or 0)))

    def _display_slots(self) -> list[str]:
        modules = self._ensure_modules() if self._modules is not None else None
        if modules is not None:
            return list(modules.engines.DISPLAY_SLOTS)
        return ["HEAD_NECK_FACE", "UPPER_BODY", "WAIST_HIP", "ARMS_HANDS", "LEGS_FEET", "STYLE"]

    def _slot_label(self, slot: str) -> str:
        modules = self._ensure_modules() if self._modules is not None else None
        if modules is not None:
            return str(modules.engines.SLOT_LABELS.get(slot, slot))
        return {
            "HEAD_NECK_FACE": "Head / Neck / Face",
            "UPPER_BODY": "Upper Body",
            "WAIST_HIP": "Waist / Hip",
            "ARMS_HANDS": "Arms / Hands",
            "LEGS_FEET": "Legs / Feet",
            "STYLE": "Style",
        }.get(slot, slot)

    def _slot_label_ko(self, slot: str) -> str:
        return str(self._translation_item("slots", slot).get("labelKo") or "").strip()

    def _group_label_ko(self, group: str) -> str:
        return str(self._translation_item("groups", group).get("labelKo") or "").strip()

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
        section_data = self._load_translations().get(section)
        if not isinstance(section_data, dict):
            return {}
        item = section_data.get(str(key or "").strip())
        return item if isinstance(item, dict) else {}

    def _load_kr_tag_payload(self) -> dict[str, dict[str, str]]:
        if self._kr_tag_payload is not None:
            return self._kr_tag_payload
        if not self.kr_tags_path.exists():
            self._kr_tag_payload = {}
            return self._kr_tag_payload
        try:
            import pandas as pd

            df = pd.read_parquet(self.kr_tags_path, columns=["tag", "category", "desc", "keywords"])
        except Exception:
            self._kr_tag_payload = {}
            return self._kr_tag_payload

        payload: dict[str, dict[str, str]] = {}
        for row in df.to_dict(orient="records"):
            tag = self._normalize_plain_text(row.get("tag"))
            if not tag:
                continue
            label = self._short_kr_label(row.get("keywords"), row.get("desc"))
            desc = str(row.get("desc") or "").strip()
            category = str(row.get("category") or "").strip()
            if label or desc or category:
                payload[tag] = {
                    "labelKo": label,
                    "krDesc": desc,
                    "krCategory": category,
                }
        self._kr_tag_payload = payload
        return self._kr_tag_payload

    def _tag_translation_fields(self, tag: str) -> dict[str, str]:
        info = self._load_kr_tag_payload().get(self._normalize_plain_text(tag), {})
        return {
            key: value
            for key, value in {
                "labelKo": info.get("labelKo", ""),
                "krDesc": info.get("krDesc", ""),
                "krCategory": info.get("krCategory", ""),
            }.items()
            if value
        }

    def _translated_tag_labels(self, tags: list[str]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        payload = self._load_kr_tag_payload()
        for tag in tags:
            label = str(payload.get(self._normalize_plain_text(tag), {}).get("labelKo") or "").strip()
            if not label:
                continue
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            labels.append(label)
        return labels

    @staticmethod
    def _short_kr_label(keywords: Any, desc: Any) -> str:
        raw_keywords = str(keywords or "").strip()
        plain: list[str] = []
        bracketed: list[str] = []
        for token in raw_keywords.split(","):
            clean = token.strip()
            if not clean:
                continue
            if clean.startswith("<") and clean.endswith(">"):
                bracketed.append(clean[1:-1].strip())
            else:
                plain.append(clean.strip("<>").strip())
        for candidate in [*plain, *bracketed]:
            if candidate:
                return candidate
        raw_desc = str(desc or "").strip()
        if not raw_desc:
            return ""
        return raw_desc.split(".")[0].strip()

    @staticmethod
    def _normalize_plain_text(value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().lower().replace("_", " ").split())

    def _first_slot(self) -> str:
        slots = self._display_slots()
        if DEFAULT_BROWSER_SLOT in slots:
            return DEFAULT_BROWSER_SLOT
        return slots[0] if slots else ""

    def _pair_mode_ids(self) -> list[str]:
        modules = self._ensure_modules() if self._modules is not None else None
        if modules is None:
            return ["Strict", "Balanced", "Explore"]
        return list(modules.engines.PAIR_MODE_PROFILES.keys())

    def _pair_modes(self) -> list[dict[str, Any]]:
        modules = self._ensure_modules()
        return [
            {
                "id": mode,
                "label": mode,
                "profile": self._json_metrics(profile),
            }
            for mode, profile in modules.engines.PAIR_MODE_PROFILES.items()
        ]

    def _max_combo_rows(self) -> int:
        modules = self._ensure_modules()
        return int(getattr(modules.engines, "MAX_COMBO_ROWS_DISPLAY", 3000))

    def _max_items_per_slot(self) -> int:
        modules = self._ensure_modules()
        return int(getattr(modules.engines, "MAX_ROWS_PER_REGION", 500))

    def _limit(self, value: Any, default: int) -> int:
        try:
            requested = int(value)
        except (TypeError, ValueError):
            requested = default
        return max(1, min(requested, default))

    def _source_counts(self, items: list[dict[str, Any]]) -> dict[str, int]:
        counts = {source: 0 for source in sorted(self.SOURCE_TYPES)}
        for item in items:
            source = str(item.get("source") or "direct")
            counts[source] = counts.get(source, 0) + 1
        return counts

    def _fragment_warnings(self, normalized: dict[str, Any]) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        if normalized["staged"]["issues"]:
            warnings.append({
                "id": "staging-issues",
                "message": "Some staged clothes tags have rule warnings.",
            })
        return warnings

    @staticmethod
    def _coerce_payload(payload: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
        request = dict(payload) if isinstance(payload, dict) else {}
        request.update(kwargs)
        return request

    @staticmethod
    def _combo_id(combo_text: str) -> str:
        digest = hashlib.sha1(combo_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"combo-{digest}"

    @staticmethod
    def _item_id(tag: str) -> str:
        digest = hashlib.sha1(str(tag).encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"tag-{digest}"

    @staticmethod
    def _ordered_unique(values: list[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            tag = str(value or "").strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            result.append(tag)
        return result

    @staticmethod
    def _json_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in metrics.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                result[str(key)] = value
        return result

    @staticmethod
    def _required_data_files() -> list[str]:
        return [
            "expression_combo_by_clothing_gsq_1girl_solo.parquet",
            "clothing_combo_index_gsq_1girl_solo.parquet",
            "clothing_region6_mapping_step42.parquet",
            "clothing_recommendation_rules_gsq_1girl_solo.parquet",
            "clothing_discouraged_rules_gsq_1girl_solo.parquet",
            "clothing_pair_cooccurrence_gsq_1girl_solo.parquet",
            "clothing_conflict_rules_gsq_1girl_solo.parquet",
        ]

    @staticmethod
    def _capabilities(data_ready: bool) -> dict[str, Any]:
        return {
            "bootstrap": data_ready,
            "select": data_ready,
            "comboSearch": data_ready,
            "itemBrowser": data_ready,
            "stageComboTags": data_ready,
            "promptFragment": data_ready,
            "pairModes": data_ready,
            "lucky": data_ready,
            "autoRandom": False,
            "deferred": [
                {"id": "autoRandom", "status": "deferred"},
            ],
        }

    @staticmethod
    def _empty_selected(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "comboId": str(payload.get("comboId") or ""),
            "comboText": "",
            "ratingId": str(payload.get("ratingId") or ""),
            "pairMode": "Balanced",
            "categoryId": "",
            "subcategoryId": "",
            "search": str(payload.get("search") or ""),
            "comboSearch": str(payload.get("comboSearch") or ""),
            "itemSearch": str(payload.get("itemSearch") or ""),
        }

    @staticmethod
    def _empty_combo_rows() -> dict[str, Any]:
        return {
            "rows": [],
            "shown": 0,
            "total": 0,
            "hiddenExact": 0,
            "limit": 0,
            "search": "",
            "ignoredSearch": False,
            "summary": "0 / 0 observed combos",
        }

    @staticmethod
    def _empty_browser() -> dict[str, Any]:
        return {
            "selected": {"categoryId": "", "subcategoryId": ""},
            "categories": [],
            "subcategories": [],
            "items": [],
            "search": "",
            "limit": 0,
        }

    @staticmethod
    def _empty_staged() -> dict[str, Any]:
        return {
            "items": [],
            "groups": [],
            "tags": [],
            "promotedTags": [],
            "ruleSeedTags": [],
            "issues": {},
            "sourceCounts": {},
        }

    @staticmethod
    def _empty_fragment() -> dict[str, Any]:
        return {
            "axisId": "clothes",
            "enabled": False,
            "tags": [],
            "prompt": "",
            "display": {"title": "", "groups": []},
            "sources": {},
            "warnings": [],
        }

    @staticmethod
    def _empty_rules(pair_mode: str) -> dict[str, Any]:
        return {
            "pairMode": pair_mode,
            "seedTags": [],
            "issues": {},
            "recommendations": [],
            "avoid": [],
            "pairs": [],
        }
