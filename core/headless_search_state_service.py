"""Headless search filter and parquet source state service."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import re
import threading


SUPPORTED_RATINGS = ("g", "s", "q", "e")
# Safe first-run default: Explicit (e) is intentionally OFF so a brand-new user
# does not get explicit content on first launch. After first run the user's saved
# filter state takes over, so this only governs the initial/fallback active set.
# Do NOT "unify" this up to all four — that would flip first-run to Explicit. The
# real off-by-one was generation_commands' /api/comfyui/random fallback, which now
# uses context.get_active_ratings() to agree with this default and the sibling paths.
DEFAULT_ACTIVE_RATINGS = ("g", "s", "q")

# 필터 프리셋 파일의 read-modify-write 직렬화. 단일 백엔드 프로세스를 여러 Remote Web
# 클라이언트(기기)가 공유하므로, 모듈 단위 락이면 동시 저장/삭제의 lost-update를 막는다.
# (읽기 get_filter_presets는 os.replace 원자성으로 안전 → 쓰기만 직렬화하면 됨.)
_PRESETS_LOCK = threading.Lock()


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
            # 리스트 항목도 쉼표/개행으로 분리한다 — 프론트가 "1girl, armpits"를 한 항목으로
            # 보내도 두 태그로 분해(예약 버그). str 분기와 동형. 저장/에코 상태가 분리되어
            # search_state echo→applyPreferences로 칩이 2개로 자기교정된다.
            raw_items = []
            for x in tags:
                raw_items.extend(re.split(r"[,\n]", str(x)))
        else:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            # replace 후 strip: 쉼표분리로 생긴 "_armpits"의 선행 '_'(원래 공백)를 제거.
            text = str(item or "").replace("_", " ").strip()
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
        # B2: updated_at 제외 내용이 직전 상태와 동일하면 디스크 tmp+replace 쓰기를 생략한다.
        # 라이브 Quick Filter 는 칩마다 save 를 여러 번 호출(중복 동일 쓰기)하므로 disk churn 완화.
        # 메모리 상태/등급은 일관성 위해 계속 갱신(updated_at 은 직전 값 보존).
        prev = getattr(context, "search_filter_state", None)
        if isinstance(prev, dict):
            prev_cmp = {k: v for k, v in prev.items() if k != "updated_at"}
            next_cmp = {k: v for k, v in state.items() if k != "updated_at"}
            if prev_cmp == next_cmp:
                context.search_filter_state = prev
                context.remote_active_ratings = set(prev.get("ratings", state.get("ratings", [])))
                return prev
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

    # ---- 마지막 검색(작업 데이터셋) 영속 (Part 3) ----
    # runner 캐시(naia_temp_rows = 비필터 오토젠 풀, 필터 검색은 의도적으로 transient)와는 별개의
    # 전용 파일. 사용자가 마지막으로 검색/로드한 *원본*(master_base = 풀 등급·태그필터 적용 전 전체)
    # 을 저장해, 재시작/가져오기 후에도 그 데이터셋이 복원되게 한다. 복원 위에 풀 등급/태그필터가
    # 다시 적용되므로 runner-cache의 'filtered cache는 복원 안 함' 계약을 건드리지 않는다.
    def last_search_parquet_path(self) -> Path:
        context = self.context
        if context.runtime_paths is not None:
            return context.runtime_paths.cache_dir / "naia_last_search.parquet"
        return Path(context.repo_root) / "naia_last_search.parquet"

    def persist_last_search(self) -> Path | None:
        """현재 작업 데이터셋을 전용 파일로 저장. best-effort.

        snapshot(=실제 마지막 검색 결과/작업 뷰) 우선, 없으면 master_base. 아카이브 검색·커스텀
        로드에선 둘이 같지만, 로드된 셋 *안에서* 재검색한 경우 snapshot=부분집합(사용자가 마지막에
        본 것)이라 그게 더 충실한 '마지막 검색'이다."""
        context = self.context
        frame = getattr(context, "search_results_snapshot", None)
        if frame is None or getattr(frame, "empty", True):
            frame = getattr(context, "search_results_master_base_snapshot", None)
        if frame is None or getattr(frame, "empty", True):
            return None
        try:
            import os

            path = self.last_search_parquet_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            # atomic write(Codex): temp 에 쓰고 os.replace 로 교체 — 대형 프레임/동시 재시작 시
            # 부분쓰기 손상을 막는다.
            tmp = path.with_suffix(path.suffix + ".tmp")
            frame.to_parquet(tmp, index=False)
            os.replace(tmp, path)
            return path
        except Exception as exc:
            print(f"Headless Remote: last-search persist failed - {exc}", flush=True)
            return None

    def restore_last_search(self, progress=None) -> bool:
        """전용 last-search 파일이 있으면 search_results/snapshot/master_base 로 복원(True=복원).
        runner-cache 스킵(태그필터 활성 시)과 무관하게 무조건 복원 — 사용자의 실제 마지막 작업
        데이터셋(비필터 원본)이라, 풀 등급/태그필터는 그 위에 재적용된다.

        ``progress(loaded, total)`` 가 주어지면 대용량 파일을 row-batch 청크로 읽어(이벤트 루프
        양보 + 진행률 보고) 시작 대기시간 체감을 줄인다(결과는 통짜 read 와 동일)."""
        context = self.context
        try:
            path = self.last_search_parquet_path()
            if not path.exists():
                return False
            from core.parquet_chunk_loader import read_parquet_chunked
            from core.search_result_model import SearchResultModel

            frame = read_parquet_chunked(path, progress=progress)
            if frame is None or frame.empty:
                return False
            # 컬럼 검증(Codex): 프롬프트 컬럼('general')이 없으면 검색 결과가 아닌 외부/손상 파일로
            # 보고 설치하지 않는다(fall-through 으로 다른 복원 소스 시도). id/rating 은
            # SearchResultModel 이 없을 때 graceful degrade 하므로 강제하지 않는다(=id 없는 정상
            # 커스텀셋도 수용).
            if "general" not in getattr(frame, "columns", []):
                print("Headless Remote: last-search restore skipped - no 'general' column", flush=True)
                return False
            frame = frame.reset_index(drop=True)
            context.search_results = SearchResultModel(frame)
            context.search_results_snapshot = frame.copy()
            context.search_results_master_base_snapshot = frame.copy()
            # 복원셋은 디스크에서 로드된 작업셋 → custom_parquet 스코프로 표기(Codex: scope 미설정
            # 수정). 현재 정보용이며 green 검색은 스코프와 무관하게 아카이브를 재스캔한다. 상수는
            # app.backend 계층이라 core 에서 import 하지 않고 리터럴을 쓴다.
            context.search_results_scope = "custom_parquet"
            return True
        except Exception as exc:
            print(f"Headless Remote: last-search restore failed - {exc}", flush=True)
            return False

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

    # ---- 저장된 Tag Filter 프리셋 (backend 영속·기기 공유, 태그만: include/exclude) ----
    def filter_presets_path(self) -> Path:
        return self.context._save_path("remote_web_filter_presets.json")

    @staticmethod
    def _normalize_filter_preset(raw: Any) -> dict | None:
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name") or "").strip()
        if not name:
            return None

        def _tags(value: Any) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for item in (value or []):
                tag = str(item or "").strip()
                if tag and tag not in seen:
                    seen.add(tag)
                    out.append(tag)
            return out

        return {"name": name, "include": _tags(raw.get("include")), "exclude": _tags(raw.get("exclude"))}

    def get_filter_presets(self) -> list[dict]:
        try:
            path = self.filter_presets_path()
            if path.exists():
                with path.open(encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return [p for p in (self._normalize_filter_preset(item) for item in data) if p]
        except Exception:
            pass
        return []

    def _write_filter_presets(self, presets: list[dict]) -> None:
        try:
            path = self.filter_presets_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(presets, f, ensure_ascii=False, indent=2)
                f.write("\n")
            tmp_path.replace(path)
        except Exception as exc:
            print(f"Headless Remote: filter presets save failed - {exc}", flush=True)

    def save_filter_preset(self, name: Any, include: Any = None, exclude: Any = None) -> list[dict]:
        entry = self._normalize_filter_preset({"name": name, "include": include, "exclude": exclude})
        if entry is None:
            return self.get_filter_presets()
        with _PRESETS_LOCK:
            # 같은 이름은 덮어쓰기(대소문자 무시 매칭). 락 안에서 read-modify-write 원자화.
            presets = [p for p in self.get_filter_presets() if p["name"].lower() != entry["name"].lower()]
            presets.append(entry)
            presets.sort(key=lambda p: p["name"].lower())
            self._write_filter_presets(presets)
            return presets

    def delete_filter_preset(self, name: Any) -> list[dict]:
        target = str(name or "").strip().lower()
        with _PRESETS_LOCK:
            presets = [p for p in self.get_filter_presets() if p["name"].lower() != target]
            self._write_filter_presets(presets)
            return presets

    def search_state_payload(self) -> dict[str, Any]:
        context = self.context
        active_ratings = self.get_active_ratings()
        filter_preferences = self.normalize_search_filter_state(
            getattr(context, "search_filter_state", None)
        )
        # 풀(생성) 등급의 단일 권위값은 라이브 active_ratings 다. 검색은 메모리에서만
        # remote_active_ratings 를 gsqe 로 열고(run_search_command — 결과 재필터 방지) 디스크
        # search_filter_state["ratings"] 는 기본값(gsq, e OFF)으로 남길 수 있다. 이때 페이로드의
        # filter_preferences.ratings(=디스크값)와 active_ratings(=라이브 gsqe)가 갈라지면,
        # 프론트 onSearchState→applyPreferences 가 라이브값을 디스크값으로 덮어써(searchPanel.mjs)
        # 풀 토글이 gsq 로 desync → 수동 Random 이 explicit 결과를 못 뽑아 "처리할 프롬프트가 더
        # 이상 없습니다" 로 죽는다(오토메이션은 백엔드 active_ratings 사용이라 정상). 페이로드에서
        # filter_preferences.ratings 를 라이브 active_ratings 로 일치시켜 desync 를 차단한다(디스크
        # 영속은 건드리지 않음 — '검색이 풀 취향을 영구 변경'하지 않는 기존 의도 보존).
        filter_preferences["ratings"] = [
            rating for rating in SUPPORTED_RATINGS if rating in active_ratings
        ]
        search_ratings = self.normalize_rating_list(
            getattr(context, "search_query_ratings", None)
            or filter_preferences.get("search_ratings")
            or list(DEFAULT_ACTIVE_RATINGS)
        )
        # 활성 태그필터가 있으면 표시 등급별 카운트도 '필터 매칭' 기준으로 — 스냅샷 전체 카운트를
        # 쓰면 표시(전체)와 실제 랜덤 풀(필터 매칭)이 어긋난다(사용자 리포트: 하단 데이터 정합성).
        # 백엔드 재조립(reconstruct_active_tag_filter)/할당이 채운 매칭 등급별 카운트를 우선 사용한다.
        active_tag_filter = getattr(context, "active_tag_filter", None)
        tag_filter_rating_counts = (
            active_tag_filter.get("rating_counts") if isinstance(active_tag_filter, dict) else None
        )
        snapshot = getattr(context, "search_results_snapshot", None)
        if tag_filter_rating_counts:
            rating_counts = {
                rating: int(tag_filter_rating_counts.get(rating, 0) or 0)
                for rating in SUPPORTED_RATINGS
            }
        elif snapshot is not None and not getattr(snapshot, "empty", True) and "rating" in snapshot.columns:
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
            "filter_presets": self.get_filter_presets(),
            "parquets": self.custom_parquet_names(),
        }
