"""Headless search filter and parquet source state service."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import re


SUPPORTED_RATINGS = ("g", "s", "q", "e")
# Safe first-run default: Explicit (e) is intentionally OFF so a brand-new user
# does not get explicit content on first launch. After first run the user's saved
# filter state takes over, so this only governs the initial/fallback active set.
# Do NOT "unify" this up to all four — that would flip first-run to Explicit. The
# real off-by-one was generation_commands' /api/comfyui/random fallback, which now
# uses context.get_active_ratings() to agree with this default and the sibling paths.
DEFAULT_ACTIVE_RATINGS = ("g", "s", "q")


def _tag_archive_sort_key(path: Path) -> tuple[int, str]:
    match = re.match(r"^tags_(\d+)\.parquet$", path.name)
    if match:
        return int(match.group(1)), path.name
    return 10**9, path.name


class HeadlessSearchStateService:
    def __init__(self, context: Any):
        self.context = context

    def set_active_ratings(self, ratings: Any) -> set[str]:
        context = self.context
        if isinstance(ratings, str):
            ratings = list(ratings)
        if not isinstance(ratings, (list, tuple, set)):
            normalized = set(DEFAULT_ACTIVE_RATINGS)
        else:
            normalized = {
                str(item).strip().lower()
                for item in ratings
                if str(item).strip().lower() in SUPPORTED_RATINGS
            }
            if not normalized:
                normalized = set(DEFAULT_ACTIVE_RATINGS)
        context.remote_active_ratings = normalized
        context.publish("remote_active_ratings_changed", self.search_state_payload())
        return normalized

    def get_active_ratings(self) -> set[str]:
        ratings = self.context.remote_active_ratings
        if not ratings:
            return set(DEFAULT_ACTIVE_RATINGS)
        return {rating for rating in SUPPORTED_RATINGS if rating in ratings} or set(DEFAULT_ACTIVE_RATINGS)

    def search_filter_state_path(self) -> Path:
        return self.context._save_path("remote_web_filter_state.json")

    @staticmethod
    def default_search_filter_state() -> dict[str, Any]:
        return {
            "version": 1,
            "query": "",
            "exclude": "",
            "ratings": list(DEFAULT_ACTIVE_RATINGS),
            "search_ratings": list(DEFAULT_ACTIVE_RATINGS),
            "tag_filter": [],
            "tag_filter_exclude": [],
            "tag_filter_active": False,
            "bucket_start": None,
            "bucket_end": None,
            "updated_at": None,
        }

    @staticmethod
    def _coerce_bucket_index(value: Any) -> Any:
        if value is None:
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def normalize_rating_list(ratings: Any) -> list[str]:
        if isinstance(ratings, str):
            ratings = list(ratings)
        if not isinstance(ratings, (list, tuple, set)):
            return list(DEFAULT_ACTIVE_RATINGS)
        normalized = [
            rating
            for rating in SUPPORTED_RATINGS
            if rating in {
                str(item).strip().lower()
                for item in ratings
                if str(item).strip().lower() in SUPPORTED_RATINGS
            }
        ]
        return normalized or list(DEFAULT_ACTIVE_RATINGS)

    @staticmethod
    def normalize_filter_tags(tags: Any) -> list[str]:
        if tags is None:
            return []
        if isinstance(tags, str):
            raw_items = re.split(r"[,\n]", tags)
        elif isinstance(tags, (list, tuple, set)):
            raw_items = list(tags)
        else:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = str(item or "").strip().replace("_", " ")
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return normalized

    def normalize_search_filter_state(self, raw: Any) -> dict[str, Any]:
        state = self.default_search_filter_state()
        if isinstance(raw, dict):
            state["query"] = str(raw.get("query", state["query"]) or "")
            state["exclude"] = str(raw.get("exclude", state["exclude"]) or "")
            state["ratings"] = self.normalize_rating_list(raw.get("ratings", state["ratings"]))
            state["search_ratings"] = self.normalize_rating_list(
                raw.get("search_ratings", raw.get("ratings", state["search_ratings"]))
            )
            state["tag_filter"] = [
                tag.lstrip("-") for tag in self.normalize_filter_tags(
                    raw.get("tag_filter") or raw.get("include") or raw.get("include_tags")
                )
            ]
            state["tag_filter_exclude"] = [
                tag.lstrip("-") for tag in self.normalize_filter_tags(
                    raw.get("tag_filter_exclude") or raw.get("exclude_tags")
                )
            ]
            state["tag_filter_active"] = bool(raw.get("tag_filter_active")) and (
                bool(state["tag_filter"]) or bool(state["tag_filter_exclude"])
            )
            state["bucket_start"] = self._coerce_bucket_index(raw.get("bucket_start", state["bucket_start"]))
            state["bucket_end"] = self._coerce_bucket_index(raw.get("bucket_end", state["bucket_end"]))
            if (
                "search_ratings" not in raw
                and (state["query"] or state["exclude"])
                and not state["tag_filter_active"]
                and not state["tag_filter"]
                and not state["tag_filter_exclude"]
            ):
                state["ratings"] = list(DEFAULT_ACTIVE_RATINGS)
            state["updated_at"] = raw.get("updated_at")
        return state

    def load_search_filter_state(self) -> dict[str, Any]:
        context = self.context
        paths = [self.search_filter_state_path()]
        if context._legacy_save_fallback_enabled():
            paths.append(context._legacy_save_path("remote_web_filter_state.json"))
        for path in paths:
            try:
                if path.exists():
                    with path.open("r", encoding="utf-8") as f:
                        return self.normalize_search_filter_state(json.load(f))
            except Exception as exc:
                print(f"Headless Remote: filter state load failed - {exc}", flush=True)
        return self.default_search_filter_state()

    def save_search_filter_state(self, **updates: Any) -> dict[str, Any]:
        context = self.context
        state = dict(
            getattr(context, "search_filter_state", None)
            or self.default_search_filter_state()
        )
        for key in ("query", "exclude"):
            if key in updates and updates[key] is not None:
                state[key] = str(updates[key] or "")
        if "ratings" in updates and updates["ratings"] is not None:
            state["ratings"] = self.normalize_rating_list(updates["ratings"])
        if "search_ratings" in updates and updates["search_ratings"] is not None:
            state["search_ratings"] = self.normalize_rating_list(updates["search_ratings"])
        if "tag_filter" in updates and updates["tag_filter"] is not None:
            state["tag_filter"] = [
                tag.lstrip("-") for tag in self.normalize_filter_tags(updates["tag_filter"])
            ]
        if "tag_filter_exclude" in updates and updates["tag_filter_exclude"] is not None:
            state["tag_filter_exclude"] = [
                tag.lstrip("-") for tag in self.normalize_filter_tags(updates["tag_filter_exclude"])
            ]
        if "tag_filter_active" in updates and updates["tag_filter_active"] is not None:
            state["tag_filter_active"] = bool(updates["tag_filter_active"])
        for bkey in ("bucket_start", "bucket_end"):
            if bkey in updates and updates[bkey] is not None:
                state[bkey] = self._coerce_bucket_index(updates[bkey])
        state = self.normalize_search_filter_state(state)
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        context.search_filter_state = state
        context.remote_active_ratings = set(state["ratings"])
        try:
            path = self.search_filter_state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.write("\n")
            tmp_path.replace(path)
        except Exception as exc:
            print(f"Headless Remote: filter state save failed - {exc}", flush=True)
        return state

    def save_search_filter_state_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self.normalize_search_filter_state(getattr(self.context, "search_filter_state", None))
        return self.save_search_filter_state(
            query=payload.get("query") if "query" in payload else None,
            exclude=payload.get("exclude") if "exclude" in payload else None,
            ratings=payload.get("ratings") if "ratings" in payload else None,
            search_ratings=payload.get("search_ratings") if "search_ratings" in payload else None,
            tag_filter=payload.get("tag_filter") if "tag_filter" in payload else None,
            tag_filter_exclude=payload.get("tag_filter_exclude") if "tag_filter_exclude" in payload else None,
            tag_filter_active=payload.get("tag_filter_active") if "tag_filter_active" in payload else None,
            bucket_start=payload.get("bucket_start") if "bucket_start" in payload else None,
            bucket_end=payload.get("bucket_end") if "bucket_end" in payload else None,
        )

    def custom_parquet_dir(self) -> Path:
        return self.context._existing_save_path("custom_tags")

    def runner_parquet_path(self) -> Path:
        context = self.context
        if context.runtime_paths is not None:
            return context.runtime_paths.cache_dir / "naia_temp_rows.parquet"
        return Path(context.repo_root) / "naia_temp_rows.parquet"

    def tag_archive_parquet_sources(self) -> list[tuple[Path, str]]:
        """Return the active image-tag archive shards for full search.

        Runtime user data is the authoritative archive location for packaged
        runs. Source-tree data is only a development fallback when no runtime
        archive has been installed yet.
        """

        context = self.context
        root = Path(context.repo_root)
        directories: list[tuple[Path, str]] = []
        if context.runtime_paths is not None:
            directories.append((
                context.runtime_paths.data_dir / "tags",
                "runtime tag archive parquet",
            ))
            directories.append((
                context.runtime_paths.resource_path("data") / "tags",
                "resource tag archive parquet",
            ))
        directories.append((root / "data" / "tags", "source tag archive parquet"))

        seen_dirs: set[Path] = set()
        for directory, label in directories:
            resolved_dir = Path(directory).resolve()
            if resolved_dir in seen_dirs:
                continue
            seen_dirs.add(resolved_dir)
            if not resolved_dir.is_dir():
                continue
            files = [
                path.resolve()
                for path in sorted(resolved_dir.glob("tags_*.parquet"), key=_tag_archive_sort_key)
                if path.is_file()
            ]
            if files:
                return [(path, label) for path in files]
        return []

    def runner_parquet_sources(self) -> list[tuple[Path, str]]:
        context = self.context
        root = Path(context.repo_root)
        candidates: list[tuple[Path, str]] = [(self.runner_parquet_path(), "runtime cache parquet")]
        if context.runtime_paths is not None:
            candidates.append((
                context.runtime_paths.data_dir / "naia_temp_rows.parquet",
                "runtime data parquet",
            ))
            tag_archive_sources = self.tag_archive_parquet_sources()
            if tag_archive_sources:
                candidates.append(tag_archive_sources[-1])
        candidates.extend([
            (root / "data" / "naia_temp_rows.parquet", "legacy data parquet"),
            (root / "naia_temp_rows.parquet", "legacy temp parquet"),
        ])

        seen: set[Path] = set()
        unique_candidates: list[tuple[Path, str]] = []
        for path, label in candidates:
            resolved = Path(path).resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_candidates.append((path, label))
        return unique_candidates

    def custom_parquet_names(self) -> list[str]:
        custom_dir = self.custom_parquet_dir()
        if not custom_dir.exists():
            return []
        return sorted(path.name for path in custom_dir.glob("*.parquet") if path.is_file())

    def search_state_payload(self) -> dict[str, Any]:
        context = self.context
        active_ratings = self.get_active_ratings()
        filter_preferences = self.normalize_search_filter_state(
            getattr(context, "search_filter_state", None)
        )
        search_ratings = self.normalize_rating_list(
            getattr(context, "search_query_ratings", None)
            or filter_preferences.get("search_ratings")
            or list(DEFAULT_ACTIVE_RATINGS)
        )
        snapshot = getattr(context, "search_results_snapshot", None)
        if snapshot is not None and not getattr(snapshot, "empty", True) and "rating" in snapshot.columns:
            rating_counts = {
                rating: int((snapshot["rating"] == rating).sum())
                for rating in SUPPORTED_RATINGS
            }
        else:
            rating_counts = context.search_results.get_count_by_rating()
        count = (
            context.search_results.get_filtered_count(active_ratings)
            if active_ratings
            else context.search_results.get_count()
        )
        return {
            "type": "search_state",
            "count": int(count or 0),
            "total_count": int(context.search_results.get_count() if context.search_results else 0),
            "active_ratings": [rating for rating in SUPPORTED_RATINGS if rating in active_ratings],
            "rating_counts": rating_counts,
            "query": filter_preferences.get("query", ""),
            "exclude": filter_preferences.get("exclude", ""),
            "ratings": {rating: rating in search_ratings for rating in SUPPORTED_RATINGS},
            "filter_preferences": filter_preferences,
            "parquets": self.custom_parquet_names(),
        }
