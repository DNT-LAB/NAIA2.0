"""PyQt-free Artist Thumbnail service for the headless Remote Web runtime."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import random
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from core.resolution_utils import (
    MAX_1MP_PIXELS,
    STANDARD_1MP_RESOLUTIONS,
    nearest_standard_1mp_resolution,
)


def _safe_log(message: str, fallback: str | None = None) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        print(fallback or message.encode("ascii", "replace").decode("ascii"))


class ArtistThumbnailService:
    ARTIST_THUMB_MODES = {
        # ⚠️ **여기가 유일한 정의다**(future02). 이 표가 그대로 드롭다운이 된다 -
        #    프론트는 `key`/`label` 을 하드코딩하지 않는다.
        # ⚠️ 새 데이터셋은 **반드시 새 키 + 새 `path`** 로 낸다. 같은 키에 내용만
        #    갈아끼우면 이미 받은 사용자 기기에서는 갱신이 **안 일어난다** -
        #    갱신 판정이 `expected_size` 비교뿐이라 지문이 없으면 늘 최신으로 본다
        #    (ARTIST_THUMBNAIL_DATASET_UPDATE_REPORT.md 0절).
        # ⚠️ `expected_size`/`sha256` 은 **앱 소스에 박힌다** = 데이터셋 갱신에는
        #    앱 릴리즈가 따라야 사용자에게 닿는다.
        "NAID5F-20000-Q": {
            "label": "NAID5F-20000-Q",
            # ⚠️ **경로는 옛 판과 같다.** 이것이 갱신 통보의 전부다 - 사용자 기기의 파일
            #    크기가 아래 `expected_size` 와 달라지는 순간 `needs_update` 가 서고
            #    드롭다운이 `(update)`, 버튼이 `Update` 로 바뀐다. 새 경로를 주면 항목이
            #    둘로 늘고 옛 1.3GB 가 디스크에 남는다(ANIMA 계열이 쓰는 방식이 이것이다).
            "path": Path("data/artist_thumbnail_naid5f.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID5_artist_thumbnail/NAID5F-20000-Q",
            # 2026-09-03 판(10000-Q 를 대체). 지문은 업로드 원본에서 실측:
            #   C:\VNR\artist_thumb_tool\data\artist_thumb\nai-diffusion-5-full\json\NAID5F-20000-Q
            #   2,633,376,969 bytes · 2,511.38 MB
            # ⚠️ 옛 판(10000-Q · 1,373,203,772 · 54252858…BAF19)은 **여기서 지운다** =
            #    드롭다운에서 사라진다(사용자 지정: 기존 10000-Q 는 숨긴다).
            "expected_size": 2633376969,
            "sha256": "9997E0FA2509D7EB19AC7EABC0CC11FACEEEC0FFA97D2C4975E5E88418ECF547",
        },
        "NAID4.5F-31000": {
            "label": "NAID4.5F-31000",
            "path": Path("data/artist_thumbnail_nai.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID4.5_artist_thumbnail_31000/artist_thumbnail_nai",
        },
        "NoobNAI-XL-33000": {
            "label": "NoobNAI-XL-33000",
            "path": Path("data/artist_thumbnail.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Noob_artist_thumbnail_33000/artist_thumbnail",
        },
        "ANIMA-22000": {
            "label": "ANIMA-22000",
            "path": Path("data/artist_thumbnail_anima.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima.json",
            "expected_size": 2656390724,
            "sha256": "C831A5B186176AEBED394F320C3E5B75B3ACEB78AF2D97B84D04C277C276252E",
        },
        "ANIMA-44000": {
            "label": "ANIMA-44000",
            "path": Path("data/artist_thumbnail_anima_bucket2.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima_bucket2.json",
            "expected_size": 2604574500,
            "sha256": "3B581E8A5C596B4E2AE001C8842B486BF4D7BC36485D23B0861B0200C41017E2",
        },
        "ANIMA-60000": {
            "label": "ANIMA-60000",
            "path": Path("data/artist_thumbnail_anima_bucket3.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima_bucket3.json",
            "expected_size": 1882040677,
            "sha256": "C564F0A473F32A81DEA43696FBF1CAA477184C957C7C1A8B5B2B21781334FB7B",
        },
    }
    ARTIST_THUMB_OPTION_MODES = ("NAI", "WEBUI", "COMFYUI")

    def __init__(
        self,
        repo_root: str | Path,
        mode_getter: Callable[[], str] | None = None,
        *,
        mode_data_root: str | Path | None = None,
        state_root: str | Path | None = None,
        wildcards_root: str | Path | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.mode_data_root = Path(mode_data_root) if mode_data_root is not None else self.repo_root / "data"
        self.state_root = Path(state_root) if state_root is not None else self.repo_root / "artist_thumb"
        self.wildcards_root = Path(wildcards_root) if wildcards_root is not None else self.repo_root / "wildcards"
        self.legacy_state_root = self.repo_root / "artist_thumb"
        self.legacy_wildcards_root = self.repo_root / "wildcards"
        self._mode_getter = mode_getter or (lambda: "NAI")
        self._data_cache: dict[str, dict] = {}
        # 캐시한 팩의 **바이트 크기**. 갱신 중에도 옛 팩을 계속 보여 주되,
        # 다 받아 크기가 바뀌면 그때 새로 읽게 하는 열쇠다(2026-09-03).
        self._data_cache_size: dict[str, int] = {}
        self._image_cache: dict[tuple[str, str], tuple[bytes, str]] = {}
        self._random_history: dict[tuple[str, str, str, int], list[str]] = {}
        self._lock = threading.RLock()
        self._download_thread: threading.Thread | None = None
        self._download_cancel = threading.Event()
        self._download_state = {
            "active": False,
            "mode": "",
            "percent": 0,
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "message": "",
            "error": "",
            "done": False,
            "updated_at": "",
        }
        self.ensure_state()

    def _path(self, relative: str | Path) -> Path:
        path = Path(relative)
        return path if path.is_absolute() else self.repo_root / path

    def _mode_info(self, mode: str) -> dict:
        key = str(mode or "").strip()
        info = self.ARTIST_THUMB_MODES.get(key)
        if not info:
            raise KeyError("Unknown artist thumbnail mode")
        return info

    def _mode_path(self, mode: str) -> Path:
        info = self._mode_info(mode)
        primary = self._mode_download_path(info)
        legacy = self._path(info["path"])
        return primary if primary.exists() or not legacy.exists() else legacy

    def _mode_download_path(self, info: dict) -> Path:
        path = Path(info["path"])
        if path.is_absolute():
            return path
        try:
            return self.mode_data_root / path.relative_to("data")
        except ValueError:
            return self._path(path)

    def _file_state(self, info: dict) -> dict:
        path = self._mode_download_path(info)
        legacy = self._path(info["path"])
        if not path.exists() and legacy.exists():
            path = legacy
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        expected_size = int(info.get("expected_size") or 0)
        needs_update = bool(exists and expected_size and size != expected_size)
        return {
            "exists": exists,
            "available": bool(exists and not needs_update),
            "needs_update": needs_update,
            "size": size,
            "expected_size": expected_size,
            "size_mb": round(size / (1024 * 1024), 1) if exists else 0,
            "expected_size_mb": round(expected_size / (1024 * 1024), 1) if expected_size else 0,
            "sha256": str(info.get("sha256") or ""),
        }

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    def _artist_weights(self, mode: str = "") -> dict[str, int]:
        weights: dict[str, int] = {}
        dictionary_path = self.repo_root / "artist_dictionary.py"
        if dictionary_path.exists():
            try:
                spec = importlib.util.spec_from_file_location("naia_artist_dictionary", dictionary_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    artist_dict = getattr(module, "artist_dict", {})
                    if isinstance(artist_dict, dict):
                        weights.update({str(key): int(value or 0) for key, value in artist_dict.items()})
            except Exception as exc:
                _safe_log(
                    f"🌐 Headless Artist Thumb: artist dictionary load failed — {exc}",
                    f"[WARN] Headless Artist Thumb: artist dictionary load failed - {exc}",
                )

        mode_key = str(mode or "").strip()
        if mode_key:
            try:
                data = self.load_data(mode_key)
                for artist in data.keys():
                    weights.setdefault(str(artist), 0)
            except Exception:
                pass
        return weights

    def _read_lines(self, path: Path) -> list[str]:
        try:
            if not path.exists():
                return []
            return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception as exc:
            _safe_log(
                f"🌐 Headless Artist Thumb: list read failed ({path}) — {exc}",
                f"[WARN] Headless Artist Thumb: list read failed ({path}) - {exc}",
            )
            return []

    def _write_lines(self, path: Path, values: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        cleaned = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if path.exists() and self._read_lines(path) == cleaned:
            return
        path.write_text("".join(f"{value}\n" for value in cleaned), encoding="utf-8")

    def _state_path(self) -> Path:
        return self.state_root / "artist_state.json"

    def _favorite_path(self) -> Path:
        return self.wildcards_root / "favorite_artist.txt"

    def _banned_path(self) -> Path:
        return self.state_root / "banned_artist.txt"

    def _options_path(self) -> Path:
        return self.state_root / "generate_options.json"

    def _favorite_thumbnail_cache_path(self) -> Path:
        return self.state_root / "favorite_thumbnail_cache.json"

    # ── 사용자가 생성한 썸네일 ─────────────────────────────────────────
    # Artist 탭에서 그 아티스트로 생성한 그림을 카드에 남긴다. 예전에는 어디에도
    # 저장하지 않아 브라우저 메모리(`resultMemory`)에만 있었고 재시작하면 사라졌다.
    def _generated_dir(self) -> Path:
        return self.state_root / "generated"

    def _generated_index_path(self) -> Path:
        return self._generated_dir() / "index.json"

    def _legacy_favorite_path(self) -> Path:
        return self.legacy_wildcards_root / "favorite_artist.txt"

    def _legacy_banned_path(self) -> Path:
        return self.legacy_state_root / "banned_artist.txt"

    def _options_mode(self, mode: str = "") -> str:
        mode_key = str(mode or "").strip().upper()
        if mode_key in self.ARTIST_THUMB_OPTION_MODES:
            return mode_key
        current_mode = str(self._mode_getter() or "").strip().upper()
        if current_mode in self.ARTIST_THUMB_OPTION_MODES:
            return current_mode
        return "NAI"

    def _normalize_options(self, data: Any, mode: str = "") -> dict:
        source = data if isinstance(data, dict) else {}
        legacy = {
            "prefix": str(source.get("prefix") or ""),
            "postfix": str(source.get("postfix") or ""),
        }
        raw_modes = source.get("modes") if isinstance(source.get("modes"), dict) else {}
        modes = {}
        for mode_key in self.ARTIST_THUMB_OPTION_MODES:
            values = raw_modes.get(mode_key) if isinstance(raw_modes.get(mode_key), dict) else {}
            prefix = values.get("prefix") if "prefix" in values else legacy["prefix"]
            postfix = values.get("postfix") if "postfix" in values else legacy["postfix"]
            modes[mode_key] = {
                "prefix": str(prefix or ""),
                "postfix": str(postfix or ""),
            }
        mode_key = self._options_mode(mode)
        selected = modes.get(mode_key, modes["NAI"])
        return {
            "version": 2,
            "mode": mode_key,
            "prefix": selected["prefix"],
            "postfix": selected["postfix"],
            "modes": modes,
        }

    def load_options(self, mode: str = "") -> dict:
        path = self._options_path()
        if not path.exists():
            return self._normalize_options({}, mode)
        try:
            return self._normalize_options(json.loads(path.read_text(encoding="utf-8")), mode)
        except Exception as exc:
            _safe_log(
                f"🌐 Headless Artist Thumb: options load failed — {exc}",
                f"[WARN] Headless Artist Thumb: options load failed - {exc}",
            )
            return self._normalize_options({}, mode)

    def save_options(self, options: dict) -> dict:
        requested_mode = options.get("mode") if isinstance(options, dict) else ""
        mode = self._options_mode(requested_mode)
        current = self.load_options(mode)
        if isinstance(options, dict):
            mode_values = current["modes"].setdefault(mode, {"prefix": "", "postfix": ""})
            if "prefix" in options:
                mode_values["prefix"] = str(options.get("prefix") or "")
            if "postfix" in options:
                mode_values["postfix"] = str(options.get("postfix") or "")
        selected = current["modes"].get(mode, {"prefix": "", "postfix": ""})
        current["version"] = 2
        current["mode"] = mode
        current["prefix"] = selected.get("prefix", "")
        current["postfix"] = selected.get("postfix", "")
        path = self._options_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return current

    def _normalize_values(self, values: Any) -> list[str]:
        seen = set()
        normalized = []
        if not isinstance(values, (list, tuple, set)):
            return []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _merge_values(self, primary: Any, additions: Any) -> list[str]:
        return self._normalize_values([*self._normalize_values(primary), *self._normalize_values(additions)])

    def _normalize_state(self, data: Any, fallback: dict | None = None) -> dict:
        source = data if isinstance(data, dict) else {}
        fallback = fallback if isinstance(fallback, dict) else {}
        return {
            "version": 1,
            "favorites": self._normalize_values(source.get("favorites", fallback.get("favorites", []))),
            "banned": self._normalize_values(source.get("banned", fallback.get("banned", []))),
        }

    def _legacy_state(self) -> dict:
        return self._normalize_state({
            "favorites": self._merge_values(
                self._read_lines(self._favorite_path()),
                self._read_lines(self._legacy_favorite_path()),
            ),
            "banned": self._merge_values(
                self._read_lines(self._banned_path()),
                self._read_lines(self._legacy_banned_path()),
            ),
        })

    def _read_state_file(self, *, merge_legacy_additions: bool = True) -> dict:
        path = self._state_path()
        if not path.exists():
            raise FileNotFoundError(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"artist thumb state JSON is invalid: {path}: {exc}") from exc
        state = self._normalize_state(data)
        if merge_legacy_additions:
            legacy = self._legacy_state()
            state["favorites"] = self._merge_values(state["favorites"], legacy["favorites"])
            state["banned"] = self._merge_values(state["banned"], legacy["banned"])
        return state

    def _sync_state_mirrors(self, state: dict) -> None:
        normalized = self._normalize_state(state)
        self._write_lines(self._favorite_path(), normalized["favorites"])
        self._write_lines(self._banned_path(), normalized["banned"])

    def _write_state(self, state: dict) -> dict:
        normalized = self._normalize_state(state)
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        try:
            temp_path.replace(path)
        except PermissionError:
            path.write_text(payload, encoding="utf-8")
            try:
                temp_path.unlink(missing_ok=True)
            except PermissionError:
                pass
        self._sync_state_mirrors(normalized)
        return normalized

    def ensure_state(self) -> dict:
        with self._lock:
            if not self._state_path().exists():
                return self._write_state(self._legacy_state())
            return self._read_state_file()

    def _state(self) -> dict:
        with self._lock:
            return self._read_state_file()

    def _favorites(self) -> list[str]:
        return list(self._state().get("favorites", []))

    def _banned(self) -> list[str]:
        return list(self._state().get("banned", []))

    def _generated_model_filters(self, weights: dict, banned_set: set[str]) -> list[dict]:
        """FILTER 하단의 '생성한 모델' 묶음. 앞에 구분선 항목을 하나 끼운다."""
        try:
            models = self.generated_models()
        except Exception:
            return []
        rows = []
        for entry in models:
            model_name = entry["name"]
            listed = [a for a in self.generated_artists_for_model(model_name)
                      if a in weights and a not in banned_set]
            if listed:
                rows.append({"key": entry["key"], "name": model_name, "count": len(listed)})
        if not rows:
            return []
        return [{"key": "__generated_sep__", "name": "생성한 모델", "count": 0,
                 "separator": True}, *rows]

    def _custom_filters(self, weights: dict | None = None, banned_set: set[str] | None = None) -> list[dict]:
        bases = [self.state_root]
        if self.legacy_state_root.resolve() != self.state_root.resolve():
            bases.append(self.legacy_state_root)
        filters = []
        weights = weights or self._artist_weights()
        banned_set = banned_set if banned_set is not None else set(self._banned())
        seen_keys = set()
        for base in bases:
            if not base.exists():
                continue
            for path in sorted(base.glob("*.txt")):
                if path.name == "banned_artist.txt":
                    continue
                key = f"custom:{path.stem}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                items = self._read_lines(path)
                filters.append({
                    "key": key,
                    "name": path.stem,
                    "count": len([artist for artist in items if artist in weights and artist not in banned_set]),
                })
        return filters

    def _normalize_thumbnail_cache(self, data: Any) -> dict:
        source = data if isinstance(data, dict) else {}
        raw_items = source.get("items", source.get("thumbnails", {}))
        if not isinstance(raw_items, dict):
            raw_items = {}
        items = {}
        for artist, value in raw_items.items():
            artist_name = str(artist or "").strip()
            if not artist_name:
                continue
            if isinstance(value, dict):
                thumbnail = str(value.get("thumbnail") or value.get("image") or "").strip()
                mode = str(value.get("mode") or "").strip()
                updated_at = str(value.get("updated_at") or "").strip()
            elif isinstance(value, (list, tuple)):
                thumbnail = str(value[0] if value else "").strip()
                mode = ""
                updated_at = ""
            else:
                thumbnail = str(value or "").strip()
                mode = ""
                updated_at = ""
            if thumbnail:
                items[artist_name] = {"mode": mode, "thumbnail": thumbnail, "updated_at": updated_at}
        return {"version": 1, "items": items}

    def _load_thumbnail_cache(self) -> dict:
        path = self._favorite_thumbnail_cache_path()
        if not path.exists():
            return {"version": 1, "items": {}}
        try:
            return self._normalize_thumbnail_cache(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise RuntimeError(f"artist thumb thumbnail cache JSON is invalid: {path}: {exc}") from exc

    def _write_thumbnail_cache(self, cache: dict) -> dict:
        normalized = self._normalize_thumbnail_cache(cache)
        path = self._favorite_thumbnail_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(path)
        return normalized

    def _cache_entry_from_data(self, artist: str, mode: str, thumb_data: dict) -> dict | None:
        artist_name = str(artist or "").strip()
        if not artist_name or not isinstance(thumb_data, dict):
            return None
        encoded_list = thumb_data.get(artist_name)
        if not isinstance(encoded_list, (list, tuple)) or not encoded_list:
            return None
        thumbnail = str(encoded_list[0] or "").strip()
        if not thumbnail:
            return None
        return {
            "mode": str(mode or "").strip(),
            "thumbnail": thumbnail,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def sync_favorite_thumbnail_cache(self, mode: str = "", thumb_data: dict | None = None) -> dict:
        mode_key = str(mode or "").strip()
        with self._lock:
            favorites = self._favorites()
            favorite_set = set(favorites)
            cache = self._load_thumbnail_cache()
            items = dict(cache.get("items") or {})
            changed = False
            removed = 0
            added = 0

            for artist in list(items.keys()):
                if artist not in favorite_set:
                    items.pop(artist, None)
                    removed += 1
                    changed = True

            missing_artists = [artist for artist in favorites if not items.get(artist, {}).get("thumbnail")]
            if mode_key and thumb_data is None:
                thumb_data = self._data_cache.get(mode_key)

            if mode_key and isinstance(thumb_data, dict):
                for artist in missing_artists:
                    entry = self._cache_entry_from_data(artist, mode_key, thumb_data)
                    if entry:
                        items[artist] = entry
                        added += 1
                        changed = True

            cache = self._write_thumbnail_cache({"version": 1, "items": items}) if changed else {"version": 1, "items": items}
            missing = len([artist for artist in favorites if not items.get(artist, {}).get("thumbnail")])
            return {
                "count": len(items),
                "added": added,
                "removed": removed,
                "missing": missing,
                "changed": changed,
                "path": str(self._favorite_thumbnail_cache_path()),
                "cache": cache,
            }

    def _cache_favorite_from_loaded_mode(self, artist: str, mode: str) -> bool:
        artist_name = str(artist or "").strip()
        mode_key = str(mode or "").strip()
        if not artist_name or not mode_key:
            return False
        with self._lock:
            entry = self._cache_entry_from_data(artist_name, mode_key, self._data_cache.get(mode_key) or {})
            if not entry:
                return False
            try:
                cache = self._load_thumbnail_cache()
            except Exception:
                cache = {"version": 1, "items": {}}
            items = dict(cache.get("items") or {})
            current = items.get(artist_name) or {}
            if current.get("thumbnail") == entry.get("thumbnail") and current.get("mode") == entry.get("mode"):
                return False
            items[artist_name] = entry
            self._write_thumbnail_cache({"version": 1, "items": items})
            return True

    def _remove_favorite_thumbnail_cache(self, artist: str) -> bool:
        artist_name = str(artist or "").strip()
        if not artist_name:
            return False
        with self._lock:
            try:
                cache = self._load_thumbnail_cache()
            except Exception:
                return False
            items = dict(cache.get("items") or {})
            if artist_name not in items:
                return False
            items.pop(artist_name, None)
            self._write_thumbnail_cache({"version": 1, "items": items})
            return True

    def load_data(self, mode: str) -> dict:
        key = str(mode or "").strip()
        if not key:
            return {}
        with self._lock:
            info = self._mode_info(key)
            file_state = self._file_state(info)
            # ⚠️ **낡아도 있으면 쓴다**(사용자 지정 2026-09-03).
            #    예전에는 `needs_update` 면 캐시를 버리고 예외를 던져서, 2.5GB 를 받는
            #    내내 그리드가 "No matching artists." 로 비어 있었다 - 옛 팩이 디스크에
            #    멀쩡히 있는데도 아무것도 못 봤다. 갱신은 **알리는 것**이지 막는 것이
            #    아니다. 다 받으면 파일 크기가 바뀌고, 아래 캐시 열쇠가 그걸 알아채
            #    새 팩으로 갈아 끼운다.
            cached = self._data_cache.get(key)
            if cached is not None and self._data_cache_size.get(key) == file_state["size"]:
                if key == "NAID4.5F-31000":
                    self.sync_favorite_thumbnail_cache(key, cached)
                return cached
            if not file_state["exists"]:
                self._data_cache.pop(key, None)
                self._data_cache_size.pop(key, None)
                raise FileNotFoundError(f"Artist thumbnail data not found: {self._mode_path(key)}")
            data = json.loads(self._mode_path(key).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Artist thumbnail data is invalid")
            self._data_cache.clear()
            self._data_cache_size.clear()
            self._image_cache.clear()
            self._data_cache[key] = data
            self._data_cache_size[key] = file_state["size"]
            if key == "NAID4.5F-31000":
                self.sync_favorite_thumbnail_cache(key, data)
            return data

    @staticmethod
    def _format_count(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    def _base_list(
        self,
        filter_key: str,
        weights: dict,
        *,
        exclude_banned: bool = True,
        allow_banned_filter: bool = True,
    ) -> tuple[list[str], str]:
        key = str(filter_key or "all").strip() or "all"
        favorites = self._favorites()
        banned = self._banned()
        banned_set = set(banned)
        if key == "favorites":
            items = [artist for artist in favorites if artist in weights]
            return ([artist for artist in items if artist not in banned_set] if exclude_banned else items), "관심 작가"
        if key == "banned":
            if not allow_banned_filter:
                return [], "제외 작가"
            return [artist for artist in banned if artist in weights], "제외 작가"
        if key.startswith("model:"):
            model_name = key.split(":", 1)[1].strip()
            # 지금 모드 안에서만 (백엔드가 다르면 그림의 결이 다르다).
            items = [a for a in self.generated_artists_for_model(model_name) if a in weights]
            return ([a for a in items if a not in banned_set] if exclude_banned else items), model_name
        if key.startswith("custom:"):
            name = Path(key.split(":", 1)[1].strip()).name
            items = self._read_lines(self._path("artist_thumb") / f"{name}.txt")
            items = [artist for artist in items if artist in weights]
            return ([artist for artist in items if artist not in banned_set] if exclude_banned else items), name
        return [artist for artist in weights.keys() if artist not in banned_set], "전체 목록"

    def _random_sample(self, artists: list[str], sample_size: int, history_key: tuple[str, str, str, int]) -> list[str]:
        if sample_size <= 0 or not artists:
            return []
        with self._lock:
            recent = set(self._random_history.get(history_key, []))
        candidates = [artist for artist in artists if artist not in recent]
        if len(candidates) < sample_size:
            candidates = list(artists)
        picked = random.SystemRandom().sample(candidates, min(sample_size, len(candidates)))
        with self._lock:
            history = [artist for artist in self._random_history.get(history_key, []) if artist in artists]
            history.extend(picked)
            max_history = max(sample_size * 8, sample_size)
            self._random_history[history_key] = history[-max_history:]
            if len(self._random_history) > 64:
                self._random_history.pop(next(iter(self._random_history)), None)
        return picked

    def state(self) -> dict:
        weights = self._artist_weights()
        favorites = self._favorites()
        banned = self._banned()
        banned_set = set(banned)
        try:
            favorite_thumbnail_cache = self.sync_favorite_thumbnail_cache()
            favorite_thumbnail_cache.pop("cache", None)
        except Exception as exc:
            favorite_thumbnail_cache = {
                "count": 0,
                "added": 0,
                "removed": 0,
                "missing": len(favorites),
                "changed": False,
                "error": str(exc),
            }
        modes = []
        for key, info in self.ARTIST_THUMB_MODES.items():
            file_state = self._file_state(info)
            modes.append({
                "key": key,
                "label": str(info.get("label") or key),
                "available": file_state["available"],
                "needs_update": file_state["needs_update"],
                # ⚠️ 화면은 **`exists` 로 판단해야 한다.** `available` 은 "최신인가" 지
                #    "볼 수 있는가" 가 아니다 - 갱신 중에도 옛 팩이 있으면 그려야 한다
                #    (사용자 제보 2026-09-03: 2.5GB 받는 내내 빈 격자였다).
                "exists": file_state["exists"],
                "loaded": key in self._data_cache and file_state["exists"],
                "size": file_state["size"],
                "expected_size": file_state["expected_size"],
                "size_mb": file_state["size_mb"],
                "expected_size_mb": file_state["expected_size_mb"],
                "sha256": file_state["sha256"],
            })
        return {
            "modes": modes,
            "filters": [
                {"key": "all", "name": "전체 목록", "count": len(self._base_list("all", weights)[0])},
                {"key": "favorites", "name": "관심 작가", "count": len(self._base_list("favorites", weights)[0])},
                {"key": "banned", "name": "제외 작가", "count": len([artist for artist in banned if artist in weights])},
                *self._custom_filters(weights, banned_set),
                # 생성한 모델 목록. 전체/관심/제외와 성격이 달라 구분선으로 가른다
                # (사용자 지정 2026-08-26).
                *self._generated_model_filters(weights, banned_set),
            ],
            "artist_count": len(weights),
            "favorites": favorites,
            "banned": banned,
            "options": self.load_options(),
            "download": self.download_snapshot(),
            "favorite_thumbnail_cache": favorite_thumbnail_cache,
        }

    def build_list(
        self,
        mode: str = "",
        filter_key: str = "all",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        random_sample: bool = False,
    ) -> dict:
        mode_key = str(mode or "").strip()
        thumb_data = self.load_data(mode_key) if mode_key else {}
        weights = self._artist_weights(mode_key)
        base_list, filter_name = self._base_list(
            filter_key,
            weights,
            exclude_banned=True,
            allow_banned_filter=not random_sample,
        )
        if thumb_data:
            thumb_keys = set(thumb_data.keys())
            base_list = [artist for artist in base_list if artist in thumb_keys]
        query_text = str(query or "").strip().lower().replace("_", " ")
        if query_text:
            base_list = [artist for artist in base_list if query_text in artist.lower().replace("_", " ")]
        base_list = sorted(base_list, key=lambda artist: weights.get(artist, 0), reverse=True)
        total = len(base_list)
        per_page = max(12, min(96, int(per_page or 48)))
        page = max(0, int(page or 0))
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page >= total_pages:
            page = max(0, total_pages - 1)
        if random_sample:
            artists = self._random_sample(
                base_list,
                min(per_page, total),
                (mode_key, str(filter_key or "all"), query_text, per_page),
            )
        else:
            artists = base_list[page * per_page:page * per_page + per_page]
        favorite_set = set(self._favorites())
        banned_set = set(self._banned())
        try:
            favorite_thumb_items = self._load_thumbnail_cache().get("items", {})
        except Exception:
            favorite_thumb_items = {}

        # ⚠️ **지금 모드의 것만 본다.** 백엔드가 다르면 그림의 결이 전혀 다르다.
        api_key = self._generated_api_key()
        try:
            generated_models = self.generated_index().get(api_key, {})
        except Exception:
            generated_models = {}
        # 모델 필터로 보고 있으면 **그 모델의** 그림을 보여 준다. 아니면 가장 최근 것.
        filter_model = (str(filter_key or "")[len("model:"):]
                        if str(filter_key or "").startswith("model:") else "")
        generated_lookup: dict[str, str] = {}
        if filter_model:
            for artist_name in generated_models.get(self._generated_model_key(filter_model), {}):
                generated_lookup[artist_name] = filter_model
        else:
            newest: dict[str, tuple[str, str]] = {}
            for model_name, entries in generated_models.items():
                for artist_name, entry in entries.items():
                    stamp = entry.get("updated_at") or ""
                    if artist_name not in newest or stamp > newest[artist_name][0]:
                        newest[artist_name] = (stamp, model_name)
            generated_lookup = {a: m for a, (_stamp, m) in newest.items()}

        def item_image_url(artist: str) -> str:
            # ⚠️ 순서가 규약이다(사용자 결정 2026-08-26): 모드 팩 -> 즐겨찾기 캐시 ->
            #    사용자가 생성한 것. 사용자 썸네일은 **빈 칸을 메꾸는 용도**지 공식 팩
            #    그림을 밀어내지 않는다. 모드를 안 고르면 앞의 둘이 대부분 비어 있어
            #    실질적으로 사용자 썸네일이 먼저 보인다(즐겨찾기 123명 제외).
            if mode_key and artist in thumb_data:
                return f"/api/artist-thumb/image?mode={quote(mode_key, safe='')}&artist={quote(artist, safe='')}"
            if artist in favorite_thumb_items:
                return f"/api/artist-thumb/favorite-image?artist={quote(artist, safe='')}"
            if artist in generated_lookup:
                return self._generated_image_url(artist, generated_lookup[artist], api_key)
            return ""

        return {
            "mode": mode_key,
            "filter": str(filter_key or "all"),
            "filter_name": filter_name,
            "query": query,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "random": bool(random_sample),
            "excluded_count": len(banned_set),
            "items": [
                {
                    "artist": artist,
                    "weight": self._format_count(weights.get(artist, 0)),
                    "favorite": artist in favorite_set,
                    "banned": artist in banned_set,
                    "has_image": bool(item_image_url(artist)),
                    "image_url": item_image_url(artist),
                }
                for artist in artists
            ],
        }

    @staticmethod
    def media_type(image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    def _image_payload_from_encoded(self, encoded: Any) -> tuple[bytes, str]:
        encoded_text = str(encoded or "")
        if encoded_text.startswith("data:") and "," in encoded_text:
            encoded_text = encoded_text.split(",", 1)[1]
        raw = base64.b64decode(encoded_text)
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(raw))
            image.load()
            if image.width > 170:
                image = image.crop((85, 0, image.width - 85, image.height))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=86, optimize=True)
            return output.getvalue(), "image/jpeg"
        except Exception:
            return raw, self.media_type(raw)

    def image_payload(self, mode: str, artist: str) -> tuple[bytes, str]:
        mode_key = str(mode or "").strip()
        artist_name = str(artist or "").strip()
        if not mode_key:
            raise ValueError("mode is required")
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = (mode_key, artist_name)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached:
                return cached
        data = self.load_data(mode_key)
        encoded_list = data.get(artist_name)
        if not encoded_list or not encoded_list[0]:
            raise FileNotFoundError(f"Artist thumbnail not found: {artist_name}")
        image_bytes, media_type = self._image_payload_from_encoded(encoded_list[0])
        with self._lock:
            if len(self._image_cache) > 512:
                self._image_cache.pop(next(iter(self._image_cache)), None)
            self._image_cache[cache_key] = (image_bytes, media_type)
        return image_bytes, media_type

    GENERATED_THUMB_MAX_SIZE = (896, 1152)
    GENERATED_UNKNOWN_MODEL = "unknown"

    # 인덱스 = {"version": 3, "items": {api_mode: {model: {artist: {filename, updated_at}}}}}
    #
    # ⚠️ **api_mode 가 맨 위 층이다**(사용자 지정 2026-08-26). 앱은 이미 모드별 파라미터
    #    plane(`remote_param_planes`)을 갖고 있고, 백엔드가 다르면 같은 아티스트라도
    #    그림의 결이 전혀 다르다. 게다가 WEBUI/COMFYUI 의 `model` 은 체크포인트 파일
    #    이름이라 NAI 의 모델 키와 성격이 다르고, ComfyUI LOCKED 워크플로우나 모델을
    #    못 읽은 경우 모두 `unknown` 으로 떨어져 **백엔드끼리 섞인다** - 그 충돌을 막는다.
    # ⚠️ 그 아래가 모델(폴더)이다. 같은 모델이라도 아티스트마다 한 장씩.
    def generated_index(self) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
        """읽기 실패는 빈 dict 로 삼킨다(썸네일 하나 때문에 탭이 죽으면 안 된다)."""
        try:
            data = json.loads(self._generated_index_path().read_text(encoding="utf-8"))
        except Exception:
            return {}
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, dict) or int(data.get("version") or 0) < 3:
            # v1(평면) · v2(모델만)는 버린다 - 배포 전 형식이라 쓰는 사람이 없다.
            return {}
        out: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
        for api_mode, models in items.items():
            if not isinstance(models, dict):
                continue
            mode_bucket: dict[str, dict[str, dict[str, str]]] = {}
            for model, entries in models.items():
                if not isinstance(entries, dict):
                    continue
                bucket = {}
                for artist, entry in entries.items():
                    if isinstance(entry, dict) and entry.get("filename"):
                        bucket[str(artist)] = {
                            "filename": str(entry.get("filename")),
                            "updated_at": str(entry.get("updated_at") or ""),
                        }
                if bucket:
                    mode_bucket[str(model)] = bucket
            if mode_bucket:
                out[str(api_mode)] = mode_bucket
        return out

    def _write_generated_index(self, index: dict) -> None:
        target = self._generated_index_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_name(target.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 3, "items": index}, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(target)

    @staticmethod
    def _safe_component(value: str, fallback: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', "_", str(value or "").strip()).strip(". ")
        return safe or fallback

    def _current_api_mode(self) -> str:
        try:
            return str(self._mode_getter() or "").strip().upper() or "NAI"
        except Exception:
            return "NAI"

    def _generated_api_key(self, api_mode: str = "") -> str:
        return self._safe_component(api_mode or self._current_api_mode(), "NAI").upper()

    def _generated_model_key(self, model: str) -> str:
        return self._safe_component(model, self.GENERATED_UNKNOWN_MODEL)

    def save_generated_thumbnail(self, pil_image: Any, artist: str, model: str = "",
                                 api_mode: str = "") -> dict[str, Any] | None:
        """생성 결과를 (api_mode, 모델, 아티스트) 칸에 남긴다. **매번 덮어쓴다**(사용자 결정).

        ⚠️ 최종 경로에 바로 쓰면 덮어쓰는 동안 들어온 GET 이 **잘린 파일**을 받는다.
           임시 파일 -> replace 로 맞춘다(캐릭터 뷰어와 같은 방식).
        """
        artist_name = str(artist or "").strip()
        if not artist_name or pil_image is None:
            return None
        from PIL import Image

        api_key = self._generated_api_key(api_mode)
        model_key = self._generated_model_key(model)
        target_dir = self._generated_dir() / api_key / model_key
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = self._safe_component(artist_name, "artist") + ".webp"
        target = target_dir / filename

        thumb = pil_image.copy()
        if thumb.mode not in ("RGB", "RGBA"):
            thumb = thumb.convert("RGB")
        thumb.thumbnail(self.GENERATED_THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
        tmp_path = target.with_name(target.name + ".tmp")
        thumb.save(tmp_path, "WEBP", quality=82)
        tmp_path.replace(target)

        with self._lock:
            index = self.generated_index()
            index.setdefault(api_key, {}).setdefault(model_key, {})[artist_name] = {
                "filename": filename,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._write_generated_index(index)
            # 덮어썼으니 이전 바이트를 물고 있는 캐시를 버린다.
            for key in list(self._image_cache):
                if key[:1] == ("__generated__",) and key[-1] == artist_name:
                    self._image_cache.pop(key, None)
        return {
            "artist": artist_name,
            "api_mode": api_key,
            "model": model_key,
            "filename": filename,
            "url": self._generated_image_url(artist_name, model_key, api_key),
            "count": sum(len(m) for models in index.values() for m in models.values()),
        }

    @staticmethod
    def _generated_image_url(artist: str, model: str = "", api_mode: str = "") -> str:
        url = f"/api/artist-thumb/generated-image?artist={quote(str(artist), safe='')}"
        if model:
            url += f"&model={quote(str(model), safe='')}"
        if api_mode:
            url += f"&api={quote(str(api_mode), safe='')}"
        return url

    def _generated_entry(self, artist: str, model: str = "",
                         api_mode: str = "") -> tuple[str, str, str] | None:
        """(api_key, model_key, filename). 모델을 안 주면 그 모드 안에서 **가장 최근** 것."""
        api_key = self._generated_api_key(api_mode)
        models = self.generated_index().get(api_key, {})
        if model:
            model_key = self._generated_model_key(model)
            entry = models.get(model_key, {}).get(artist)
            return (api_key, model_key, entry["filename"]) if entry else None
        best: tuple[str, str, str] | None = None   # (updated_at, model, filename)
        for model_key, entries in models.items():
            entry = entries.get(artist)
            if not entry:
                continue
            stamp = entry.get("updated_at") or ""
            if best is None or stamp > best[0]:
                best = (stamp, model_key, entry["filename"])
        return (api_key, best[1], best[2]) if best else None

    def generated_models(self, api_mode: str = "") -> list[dict[str, Any]]:
        """지금 모드에서 생성 썸네일이 있는 모델 목록. FILTER 하단에 나열된다."""
        models = self.generated_index().get(self._generated_api_key(api_mode), {})
        return [
            {"key": f"model:{model}", "name": model, "count": len(entries)}
            for model, entries in sorted(models.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            if entries
        ]

    def generated_artists_for_model(self, model: str, api_mode: str = "") -> list[str]:
        models = self.generated_index().get(self._generated_api_key(api_mode), {})
        return sorted(models.get(self._generated_model_key(model), {}).keys())

    def generated_image_payload(self, artist: str, model: str = "",
                                api_mode: str = "") -> tuple[bytes, str]:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = ("__generated__", self._generated_api_key(api_mode), str(model or ""), artist_name)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached:
                return cached
            found = self._generated_entry(artist_name, str(model or ""), api_mode)
        if not found:
            raise FileNotFoundError(f"Generated artist thumbnail not found: {artist_name}")
        api_key, model_key, filename = found
        path = self._generated_dir() / api_key / model_key / filename
        try:
            payload = (path.read_bytes(), "image/webp")
        except OSError as exc:
            raise FileNotFoundError(f"Generated artist thumbnail unreadable: {artist_name}") from exc
        with self._lock:
            if len(self._image_cache) > 512:
                self._image_cache.pop(next(iter(self._image_cache)), None)
            self._image_cache[cache_key] = payload
        return payload

    def favorite_image_payload(self, artist: str) -> tuple[bytes, str]:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = ("__favorite_cache__", artist_name)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached:
                return cached
            entry = (self._load_thumbnail_cache().get("items") or {}).get(artist_name) or {}
            encoded = entry.get("thumbnail")
        if not encoded:
            raise FileNotFoundError(f"Favorite artist thumbnail not found: {artist_name}")
        image_bytes, media_type = self._image_payload_from_encoded(encoded)
        with self._lock:
            if len(self._image_cache) > 512:
                self._image_cache.pop(next(iter(self._image_cache)), None)
            self._image_cache[cache_key] = (image_bytes, media_type)
        return image_bytes, media_type

    def set_favorite(self, artist: str, favorite: bool, mode: str = "") -> dict:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        with self._lock:
            state = self._state()
            favorites = list(state.get("favorites", []))
            if favorite and artist_name not in favorites:
                favorites.append(artist_name)
            elif not favorite and artist_name in favorites:
                favorites = [item for item in favorites if item != artist_name]
            state["favorites"] = favorites
            self._write_state(state)
            if favorite:
                self._cache_favorite_from_loaded_mode(artist_name, mode)
            else:
                self._remove_favorite_thumbnail_cache(artist_name)
        return self.state()

    def set_banned(self, artist: str, banned: bool) -> dict:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        with self._lock:
            state = self._state()
            banned_list = list(state.get("banned", []))
            if banned and artist_name not in banned_list:
                banned_list.append(artist_name)
            elif not banned and artist_name in banned_list:
                banned_list = [item for item in banned_list if item != artist_name]
            state["banned"] = banned_list
            if banned:
                state["favorites"] = [item for item in state.get("favorites", []) if item != artist_name]
            self._write_state(state)
        return self.state()

    @staticmethod
    def final_prompt(payload: dict) -> str:
        prompt_parts = []
        for key in ("prefix", "positive", "postfix"):
            value = str(payload.get(key) or "").strip()
            if value:
                prompt_parts.append(value)
        return ", ".join(prompt_parts).strip()

    def random_prompt_override(self, artist_prompt: str, module_settings: dict | None = None) -> dict:
        artist_value = str(artist_prompt or "").strip().rstrip(",")
        if not artist_value:
            raise ValueError("artist_prompt is required")
        settings = module_settings if isinstance(module_settings, dict) else {}
        pre_prompt = str(settings.get("pre_prompt") or "").strip()
        return {
            "pre_prompt": f"{artist_value}, {pre_prompt}" if pre_prompt else artist_value,
            "post_prompt": str(settings.get("post_prompt") or ""),
            "auto_hide": str(settings.get("auto_hide_prompt") or settings.get("auto_hide") or ""),
            "preprocessing_options": dict(settings.get("preprocessing_options") or {}),
        }

    def _resolution_allowed(self, width: int, height: int) -> bool:
        if width <= 0 or height <= 0:
            return False
        if width % 64 != 0 or height % 64 != 0:
            return False
        return width * height <= MAX_1MP_PIXELS

    def coerce_resolution(self, width: Any, height: Any) -> tuple[int, int]:
        pair = nearest_standard_1mp_resolution(width, height)
        if self._resolution_allowed(*pair):
            return pair
        return (832, 1216)

    def generation_overrides(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        final_positive = self.final_prompt(payload)
        if not final_positive:
            raise ValueError("prompt is empty")
        negative = str(payload.get("negative_prompt") or "")
        try:
            width = int(payload.get("width") or 832)
            height = int(payload.get("height") or 1216)
        except Exception:
            width, height = 832, 1216
        use_active_resolution = str(payload.get("artist_thumb_use_active_resolution", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        } or payload.get("artist_thumb_use_active_resolution") is True
        if not use_active_resolution:
            width, height = self.coerce_resolution(width, height)
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        artist_name = str(payload.get("artist") or "").strip()
        overrides = {
            "input": final_positive,
            "_raw_input": final_positive,
            "negative_prompt": negative,
            "width": width,
            "height": height,
            "resolution": f"{width} x {height}",
            "artist_thumb_request": True,
            "artist_thumb_request_id": request_id,
            "artist_thumb_artist": artist_name,
            "_remote_queue_source": "Artist Thumb",
            "_remote_queue_label": artist_name,
        }
        if use_active_resolution:
            for key in (
                "api_mode",
                "resolution",
                "random_resolution",
                "auto_fit_resolution",
                "resolution_preset_enabled",
                "resolution_preset",
                "enable_hr",
                "hr_scale",
                "hr_upscaler",
                "denoising_strength",
                "hires_steps",
                "hr_cfg",
                "hires_preset_swap",
                "webui_hiresfix_assist",
                "webui_hiresfix_assist_target",
            ):
                if key in payload:
                    overrides[key] = payload.get(key)
            overrides["width"] = width
            overrides["height"] = height
            overrides.setdefault("resolution", f"{width} x {height}")
            overrides["artist_thumb_use_active_resolution"] = True
        else:
            overrides["random_resolution"] = False
        return overrides

    def validate_download_file(self, mode: str, path: Path) -> int:
        file_size = Path(path).stat().st_size
        if file_size < (1024 * 1024):
            raise ValueError(f"다운로드된 파일이 너무 작습니다 ({file_size / 1024:.1f} KB)")
        mode_info = self._mode_info(mode)
        expected_size = int(mode_info.get("expected_size") or 0)
        if expected_size and file_size != expected_size:
            raise ValueError(f"다운로드된 파일 크기가 예상과 다릅니다 ({file_size} / {expected_size} bytes)")
        expected_sha256 = str(mode_info.get("sha256") or "").upper()
        if expected_sha256:
            self._set_download_state(message="다운로드 파일을 검증하는 중...")
            actual_sha256 = self._file_sha256(path)
            if actual_sha256 != expected_sha256:
                raise ValueError(f"다운로드된 파일 해시가 예상과 다릅니다 ({actual_sha256})")
        return file_size

    def download_snapshot(self) -> dict:
        with self._lock:
            return dict(self._download_state)

    def _set_download_state(self, **updates) -> dict:
        with self._lock:
            self._download_state.update(updates)
            self._download_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._download_state)

    def start_download(self, mode: str) -> dict:
        key = str(mode or "").strip()
        info = self._mode_info(key)
        path = self._mode_download_path(info)
        url = str(info.get("url") or "")
        if not url:
            raise ValueError(f"download url is not configured: {key}")
        file_state = self._file_state(info)
        if file_state["available"]:
            return self._set_download_state(
                active=False,
                mode=key,
                percent=100,
                downloaded_mb=file_state["size_mb"],
                total_mb=file_state["size_mb"],
                message="이미 다운로드되어 있습니다.",
                error="",
                done=True,
            )
        with self._lock:
            if self._download_state.get("active"):
                return dict(self._download_state)
            self._download_cancel.clear()
            self._download_state.update({
                "active": True,
                "mode": key,
                "percent": 0,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "message": "다운로드 준비 중...",
                "error": "",
                "done": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            worker = threading.Thread(
                target=self._run_download,
                args=(key, path, url),
                daemon=True,
                name=f"artist-thumb-download-{key}",
            )
            self._download_thread = worker
            worker.start()
            return dict(self._download_state)

    def cancel_download(self) -> dict:
        state = self.download_snapshot()
        if state.get("active"):
            self._download_cancel.set()
            return self._set_download_state(message="다운로드 취소 중...")
        return state

    def _run_download(self, mode: str, target_path: Path, url: str) -> None:
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(url, headers={"User-Agent": "NAIA/2.0.42 ArtistThumb Headless"})
            self._set_download_state(message="다운로드 연결 중...")
            with urllib.request.urlopen(request, timeout=30) as response:
                total_size = int(response.headers.get("content-length", 0) or 0)
                total_mb = round(total_size / (1024 * 1024), 1) if total_size else 0.0
                downloaded = 0
                last_update = 0.0
                with temp_path.open("wb") as output:
                    while True:
                        if self._download_cancel.is_set():
                            raise InterruptedError("다운로드가 취소되었습니다.")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_update >= 0.25:
                            percent = min(100, int((downloaded * 100) / total_size)) if total_size else 0
                            downloaded_mb = round(downloaded / (1024 * 1024), 1)
                            self._set_download_state(
                                percent=percent,
                                downloaded_mb=downloaded_mb,
                                total_mb=total_mb,
                                message=(
                                    f"다운로드 중... {percent}% ({downloaded_mb}/{total_mb} MB)"
                                    if total_size else f"다운로드 중... {downloaded_mb} MB"
                                ),
                            )
                            last_update = now
            file_size = self.validate_download_file(mode, temp_path)
            temp_path.replace(target_path)
            with self._lock:
                self._data_cache.clear()
                self._image_cache.clear()
            size_mb = round(file_size / (1024 * 1024), 1)
            self._set_download_state(
                active=False,
                mode=mode,
                percent=100,
                downloaded_mb=size_mb,
                total_mb=size_mb,
                message=f"다운로드 완료 ({size_mb} MB)",
                error="",
                done=True,
            )
        except InterruptedError as exc:
            temp_path.unlink(missing_ok=True)
            self._set_download_state(active=False, mode=mode, message=str(exc), error=str(exc), done=False)
        except urllib.error.HTTPError as exc:
            temp_path.unlink(missing_ok=True)
            message = f"HTTP 오류 {exc.code}: {exc.reason}"
            self._set_download_state(active=False, mode=mode, message=message, error=message, done=False)
        except urllib.error.URLError as exc:
            temp_path.unlink(missing_ok=True)
            message = f"네트워크 오류: {exc.reason}"
            self._set_download_state(active=False, mode=mode, message=message, error=message, done=False)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            message = f"다운로드 실패: {exc}"
            self._set_download_state(active=False, mode=mode, message=message, error=message, done=False)
