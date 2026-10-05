"""Snapshot v1 storage. Only stdlib dependencies; no runtime or UI ownership."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from uuid import uuid4

SNAPSHOT_SCHEMA = "naia.snapshot.v1"
SNAPSHOT_SECTIONS = (
    "prompt", "negative", "params", "prompt_engineering", "characters",
    "conditional", "vibe_transfer", "character_reference", "search",
)
PRESET_SECTIONS = SNAPSHOT_SECTIONS[:4]
_FORBIDDEN_NAME_CHARS = '<>:"/\\|?*'


def sanitize_snapshot_name(name: Any) -> str:
    """Preset filename rules, with traversal and internal names rejected."""
    if not isinstance(name, str) or any(ch in name for ch in ("/", "\\")):
        return ""
    clean = name.strip()
    if clean.startswith("_") or any(ord(ch) < 32 for ch in clean):
        return ""
    for char in _FORBIDDEN_NAME_CHARS:
        clean = clean.replace(char, "")
    clean = clean.strip().rstrip(". ")
    if not clean or clean in {".", ".."} or clean.startswith("_"):
        return ""
    # Windows device names are not ordinary files, even with an extension.
    stem = clean.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}:
        return ""
    return clean


def snapshot_defaults() -> dict[str, Any]:
    """Provisional SRS A1-A4 choices, kept together for the next stages."""
    return {
        "save_conditional_user_presets": True,
        "persist_working": True,
        "merge_references": True,
        "extra_main_keys": ("random_resolution", "auto_fit_resolution"),
    }


def main_setting_section(key: str) -> str:
    return "prompt" if key == "prompt" else "negative" if key in {"negative", "negative_prompt"} else "params"


def snapshot_parts(data: dict[str, Any]) -> dict[str, Any]:
    # 파일의 preset 구역은 유지하고, 선택/보고 경계에서만 아홉 항목으로 나눈다.
    parts = {key: data[key] for key in SNAPSHOT_SECTIONS[4:] if data.get(key) is not None}
    preset = data.get("preset")
    if isinstance(preset, dict):
        if "module_settings" in preset:
            parts["prompt_engineering"] = preset["module_settings"]
        main = preset.get("main_settings")
        if isinstance(main, dict):
            for key, value in main.items():
                parts.setdefault(main_setting_section(key), {})[key] = copy.deepcopy(value)
            # 옛 별칭이 함께 있어도 정식 negative 값이 우선한다.
            if "negative" in main:
                parts["negative"].pop("negative_prompt", None)
        elif "main_settings" in preset:
            parts.update({key: None for key in PRESET_SECTIONS[:3]})
    elif "preset" in data:
        parts.update({key: None for key in PRESET_SECTIONS})
    return parts


def normalize_working(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if not all(isinstance(data.get(key), dict) for key in ("module_settings", "main_settings")):
        return {}
    return {
        "source": str(data.get("source") or ""),
        "api_mode": str(data.get("api_mode") or ""),
        "module_settings": copy.deepcopy(data["module_settings"]),
        # Session process/internal keys never belong to a portable working copy.
        "main_settings": {key: copy.deepcopy(value) for key, value in data["main_settings"].items()
                          if isinstance(key, str) and not key.startswith(("_", "web_session_"))},
    }


def normalize_snapshot(data: Any) -> dict[str, Any] | None:
    """Validate the envelope, preserving bad sections for the apply report."""
    if not isinstance(data, dict) or data.get("schema") != SNAPSHOT_SCHEMA:
        return None
    if not isinstance(data.get("mode"), str) or not data["mode"]:
        return None
    if not sanitize_snapshot_name(data.get("name")):
        return None
    return copy.deepcopy(data)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding="utf-8", newline="\n")


class SnapshotStore:
    """A single mode's root: context._save_path('snapshots', MODE)."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._working_cache: dict[str, Any] | None = None
        self._summary_cache: dict[Path, tuple[tuple[Any, ...], dict[str, Any] | None]] = {}

    def directory(self, name: str, *, exact: bool = False) -> Path:
        clean = sanitize_snapshot_name(name)
        if not clean or (exact and clean != name):
            raise ValueError("Invalid snapshot name")
        # Windows에서는 대소문자만 다른 요청도 기존 이름을 유지하는 같은 스냅샷이다.
        if self.root.is_dir():
            matches = [entry.name for entry in self.root.iterdir() if entry.name.casefold() == clean.casefold()]
            if matches:
                clean = clean if clean in matches else sorted(matches)[0]
        path = self.root / clean
        # Reject symlinks/junctions as well as textual traversal. Deletion, rename,
        # image reads and writes all pass through this same boundary.
        if path.is_symlink() or path.resolve() != path or path.resolve().parent != self.root:
            raise ValueError("Snapshot path escapes its root")
        return path

    def _file(self, name: str, filename: str, *, exact: bool = False) -> Path:
        directory = self.directory(name, exact=exact)
        path = directory / filename
        if path.is_symlink() or path.resolve().parent != directory:
            raise ValueError("Snapshot file escapes its directory")
        return path

    def read(self, name: str, *, resolve_folder: bool = True) -> dict[str, Any] | None:
        path = self._file(name, "snapshot.json")
        if not path.exists():
            return None
        try:
            data = normalize_snapshot(json.loads(path.read_text(encoding="utf-8")))
            if data is None or data["name"] != path.parent.name:
                raise ValueError("Invalid snapshot envelope")
            if resolve_folder:
                ids = {row["id"] for row in self.load_folders()}
                folder = data.get("folder")
                data["folder"] = folder if isinstance(folder, str) and folder in ids else ""
            return data
        except (OSError, ValueError, TypeError) as exc:
            print(f"[snapshot] skipped {ascii(path.parent.name)}: {ascii(exc)}")
            return None

    def list(self, *, folders: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        # 같은 목록 안에서 분류를 한 번만 읽어 카드마다 다른 시점을 보지 않게 한다.
        ids = {row["id"] for row in (self.load_folders() if folders is None else folders)}
        rows = []
        for entry in self.root.iterdir():
            if entry.name.startswith("_") or not entry.is_dir():
                continue
            try:
                self.directory(entry.name, exact=True)
                data = self.read(entry.name, resolve_folder=False)
                if data is not None:
                    folder = data.get("folder")
                    data["folder"] = folder if isinstance(folder, str) and folder in ids else ""
                    rows.append(data)
            except (OSError, ValueError) as exc:
                print(f"[snapshot] skipped {ascii(entry.name)}: {ascii(exc)}")
        return sorted(rows, key=lambda row: str(row.get("saved_at") or ""), reverse=True)

    def list_summaries(self, summarize: Callable[[dict[str, Any]], dict[str, Any]], *,
                       folders: list[dict[str, str]]) -> list[dict[str, Any]]:
        # 큰 인코딩을 품은 원본 대신 카드만 캐시한다. 외부 편집/분류 삭제/그림 교체도 반영한다.
        if not self.root.is_dir():
            self._summary_cache.clear()
            return []
        folder_revision = tuple((row["id"], row["name"], row["parent"]) for row in folders)
        ids = {row["id"] for row in folders}
        rows, next_cache = [], {}
        for entry in self.root.iterdir():
            if entry.name.startswith("_") or not entry.is_dir():
                continue
            try:
                path = self._file(entry.name, "snapshot.json", exact=True)
                stat = path.stat()
                revision = (stat.st_mtime_ns, stat.st_size, self.image_url(entry.name), folder_revision)
                cached = self._summary_cache.get(path)
                if cached is None or cached[0] != revision:
                    data = self.read(entry.name, resolve_folder=False)
                    summary = None
                    if data is not None:
                        folder = data.get("folder")
                        data["folder"] = folder if isinstance(folder, str) and folder in ids else ""
                        summary = summarize(data)
                    cached = (revision, summary)
                next_cache[path] = cached
                summary = cached[1]
                if summary is not None:
                    # 응답을 호출자가 고쳐도 다음 state의 캐시가 오염되지 않게 분리한다.
                    rows.append(copy.deepcopy(summary))
            except (OSError, ValueError) as exc:
                print(f"[snapshot] skipped {ascii(entry.name)}: {ascii(exc)}")
        # 병렬 state가 삭제된 카드의 캐시를 정리해도 이 호출의 로컬 결과는 보존한다.
        self._summary_cache = next_cache
        return sorted(rows, key=lambda row: str(row.get("saved_at") or ""), reverse=True)

    def write(self, name: str, data: dict[str, Any], image: bytes, *, overwrite: bool = False,
              reference_images: dict[str, bytes] | None = None,
              stage_search: Callable[[Path], dict[str, Any] | None] | None = None) -> str:
        target = self.directory(name)
        if not image:
            raise ValueError("Snapshot image is required")
        if target.exists() and not overwrite:
            raise FileExistsError(target.name)
        previous = self.read(target.name, resolve_folder=False) if target.exists() else None
        now = datetime.now(timezone.utc).isoformat()
        payload = copy.deepcopy(data)
        payload.update(schema=SNAPSHOT_SCHEMA, name=target.name, saved_at=now,
                       created_at=(previous or {}).get("created_at") or now)
        # 덮어쓰기는 분류 변경이 아니다. 삭제된 분류 ID도 원본 그대로 보존한다.
        payload["folder"] = (previous or {}).get("folder", "") if previous else self.validate_folder(data.get("folder", ""))
        if normalize_snapshot(payload) is None:
            raise ValueError("Invalid snapshot envelope")
        self.root.mkdir(parents=True, exist_ok=True)
        # The staging directory cannot appear in the list, even after a crash.
        with tempfile.TemporaryDirectory(prefix="_pending_", dir=self.root) as temporary:
            stage = Path(temporary)
            if stage_search is not None:
                search = stage_search(stage)
                if search is not None:
                    payload["search"] = search
            _write_json(stage / "snapshot.json", payload)
            (stage / "image.webp").write_bytes(image)
            for relative, source_bytes in (reference_images or {}).items():
                target_image = stage / relative
                if not target_image.resolve().is_relative_to(stage.resolve()):
                    raise ValueError("Snapshot reference image escapes staging")
                target_image.parent.mkdir(parents=True, exist_ok=True)
                target_image.write_bytes(source_bytes)
            backup = None
            if target.exists():
                if not overwrite:
                    raise FileExistsError(target.name)
                # ⚠️ 옛 폴더를 **지우지 않고 비켜 둔다**. 먼저 지우면, 바로 다음의 교체가 실패했을 때
                #    (윈도우에서는 폴더 안 파일을 누가 쥐고 있으면 rename 이 거부된다) 옛 스냅샷도 새 스냅샷도
                #    남지 않는다(Codex 리뷰 2026-10-05 BLOCK). `_` 로 시작하는 이름은 목록에 나오지 않는다.
                backup = self.root / f"_old_{uuid4().hex}"
                target.rename(backup)
            try:
                stage.rename(target)
            except BaseException:
                if backup is not None:
                    backup.rename(target)
                raise
            if backup is not None:
                # 새 폴더가 자리 잡은 뒤에야 옛것을 버린다. 못 지워도(파일이 잡혀 있다) 저장은 끝난 것이다 -
                # 남은 것은 다음 저장 때 다시 치운다.
                shutil.rmtree(backup, ignore_errors=True)
            self._sweep_old()
        return target.name

    def _sweep_old(self) -> None:
        """덮어쓰기가 비켜 둔 옛 폴더(`_old_*`) 가운데 그때 못 지운 것을 치운다. 실패해도 조용히 둔다."""
        try:
            for entry in self.root.iterdir():
                if entry.name.startswith("_old_") and entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            pass

    def delete(self, name: str) -> bool:
        target = self.directory(name)
        if not target.is_dir():
            return False
        shutil.rmtree(target)
        return True

    def rename(self, old: str, new: str) -> str:
        source, target = self.directory(old), self.directory(new)
        data = self.read(old, resolve_folder=False)
        if data is None:
            raise FileNotFoundError(old)
        if source == target:
            return source.name
        if target.exists():
            raise FileExistsError(target.name)
        data["name"] = target.name
        source.rename(target)
        try:
            self._atomic_json(self._file(target.name, "snapshot.json"), data)
            working = self.read_working()
            if str(working.get("source") or "").casefold() == source.name.casefold():
                working["source"] = target.name
                self.write_working(working)
        except Exception:
            # Restore the original envelope and name on a failed metadata write.
            data["name"] = source.name
            self._atomic_json(target / "snapshot.json", data)
            target.rename(source)
            raise
        return target.name

    def _folders_path(self) -> Path:
        path = self.root / "_folders.json"
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError("Snapshot folders path escapes its root")
        return path

    def load_folders(self) -> list[dict[str, str]]:
        try:
            data = json.loads(self._folders_path().read_text(encoding="utf-8"))
            rows = data.get("folders") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                return []
            result = []
            seen = set()
            for row in rows:
                if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                        or row["id"] in seen or not isinstance(row.get("name"), str)
                        or not isinstance(row.get("parent", ""), str)):
                    continue
                result.append({"id": row["id"], "name": row["name"], "parent": row.get("parent", "")})
                seen.add(row["id"])
            roots = {row["id"] for row in result if not row["parent"]}
            return [row for row in result if not row["parent"]] + [row for row in result if row["parent"] in roots]
        except (OSError, ValueError, TypeError):
            # 분류 파일 손상은 스냅샷 유실이 아니다. 읽을 때만 미분류로 취급한다.
            return []

    def validate_folder(self, folder: Any) -> str:
        if not isinstance(folder, str) or (folder and not any(row["id"] == folder for row in self.load_folders())):
            raise ValueError("Unknown snapshot folder")
        return folder

    def create_folder(self, name: str, parent: str = "") -> dict[str, str]:
        label = str(name or "").strip()
        if not label:
            raise ValueError("Snapshot folder name is empty")
        rows = self.load_folders()
        up = next((row for row in rows if row["id"] == parent), None)
        # Finder의 두 층을 넘지 않도록 소분류의 부모 아래에 붙인다.
        parent = (up["parent"] or up["id"]) if up else ""
        hit = next((row for row in rows if row["parent"] == parent and row["name"] == label), None)
        if hit is not None:
            return hit
        row = {"id": "f" + uuid4().hex[:12], "name": label, "parent": parent}
        self._atomic_json(self._folders_path(), {"folders": [*rows, row]})
        return row

    def rename_folder(self, folder_id: str, name: str) -> None:
        label = str(name or "").strip()
        if not label:
            raise ValueError("Snapshot folder name is empty")
        rows = self.load_folders()
        hit = next((row for row in rows if row["id"] == folder_id), None)
        if hit is None:
            raise ValueError("Unknown snapshot folder")
        hit["name"] = label
        self._atomic_json(self._folders_path(), {"folders": rows})

    def delete_folder(self, folder_id: str) -> None:
        rows = self.load_folders()
        if not any(row["id"] == folder_id for row in rows):
            raise ValueError("Unknown snapshot folder")
        doomed = {folder_id} | {row["id"] for row in rows if row["parent"] == folder_id}
        # 분류만 지운다. 원본 파일은 그대로 두어 나중에 분류 정보를 복구할 수 있다.
        self._atomic_json(self._folders_path(), {"folders": [row for row in rows if row["id"] not in doomed]})

    def move(self, name: str, folder: str) -> None:
        folder = self.validate_folder(folder)
        data = self.read(name, resolve_folder=False)
        if data is None:
            raise FileNotFoundError(name)
        data["folder"] = folder
        # 분류 이동으로 카드 정렬이 바뀌지 않도록 saved_at은 보존한다.
        self._atomic_json(self._file(name, "snapshot.json"), data)

    def pool_path(self, name: str) -> Path:
        # 파일명은 고정한다. 가져온 JSON의 pool_file로 경로를 조립하지 않는다.
        return self._file(name, "pool.parquet", exact=True)

    def image_path(self, name: str) -> Path | None:
        # HTTP queries must name the actual directory, not an alias produced by
        # stripping filename punctuation from untrusted input.
        path = self._file(name, "image.webp", exact=True)
        return path if path.is_file() else None

    def reference_directory(self, name: str, kind: str) -> Path:
        directory = self.directory(name)
        path = directory / "refs" / ("vibe" if kind == "vibe_transfer" else "character_reference")
        if path.resolve() != path:
            raise ValueError("Snapshot reference directory escapes its boundary")
        return path

    def image_url(self, name: str) -> str:
        try:
            path = self.image_path(name)
            if path is None:
                return ""
            stat = path.stat()
            return f"/api/snapshot/image?name={quote(name, safe='')}&v={stat.st_mtime_ns}-{stat.st_size}"
        except (OSError, ValueError):
            return ""

    def _working_path(self) -> Path:
        path = self.root / "_working.json"
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError("Snapshot working path escapes its root")
        return path

    def read_working(self, *, refresh: bool = False) -> dict[str, Any]:
        # 빈 작업본도 캐시한다. 잦은 PE state 요청마다 디스크를 다시 읽지 않는다.
        if refresh or self._working_cache is None:
            try:
                self._working_cache = normalize_working(json.loads(self._working_path().read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                self._working_cache = {}
        return copy.deepcopy(self._working_cache)

    def write_working(self, data: dict[str, Any]) -> None:
        payload = normalize_working(data)
        if not payload:
            raise ValueError("Invalid snapshot working copy")
        self._atomic_json(self._working_path(), payload)
        self._working_cache = copy.deepcopy(payload)

    def _atomic_json(self, target: Path, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="_write_", suffix=".json", dir=self.root)
        os.close(fd)
        path = Path(temporary)
        try:
            _write_json(path, data)
            os.replace(path, target)
        finally:
            path.unlink(missing_ok=True)
