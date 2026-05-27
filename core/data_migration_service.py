"""Import user data from a previous NAIA 2.0 install into the runtime user-data root.

Two kinds of previous install are supported and auto-detected by which buckets
are present in the chosen folder:
  * a legacy source checkout (future01 / Dev0714 / main) that wrote user data to
    ``os.getcwd()``-relative folders (``save/``, ``wildcards/``, ``output/``,
    ``artist_thumb/``);
  * an older packaged / Electron install whose data already uses the runtime
    ``user_root`` layout (``save/``, ``wildcards/``, ``output/``, ``ui_assets/``,
    ``config/``) — so users can carry data forward across version updates.

Source runs resolve ``user_root`` to ``%APPDATA%/NAIA``; the portable build uses
``<exe>/user-data``. The release write policy forbids writing user state into the
read-only resource/source tree, so the new install never reuses the old layout in
place — this service copies the chosen folder into the current ``user_root``,
remapping the few buckets whose parent differs (legacy ``artist_thumb/`` ->
``ui_assets/artist_thumb``). It is **non-destructive**: it only ever reads the
source and copies into the target (never moves or deletes), and by default it
skips files that already exist in the target so it cannot clobber data created in
the new install (including existing credentials).

The legacy multi-account credential file (``save/nai_accounts.json``) uses a
different at-rest scheme than the current ``config/secure_tokens.json`` and is
excluded from the save bucket (handled by a separate opt-in transform). An
Electron-source ``config/`` already holds ``secure_tokens.json`` and migrates
directly via the config bucket, carrying the token forward across versions.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable, Iterator

# (source subpath relative to the chosen folder, target relative to user_root, label)
#
# Two source layouts are supported and auto-detected by which buckets are present:
#   * legacy source checkout (future01 / Dev0714 / main): cwd-relative flat dirs
#     save/, wildcards/, output/, and artist_thumb/ at the top level.
#   * older Electron / packaged install: the runtime user-data layout, where
#     artist thumbnails live under ui_assets/ and credentials under config/.
# A given source has either a top-level artist_thumb/ (legacy) or ui_assets/ +
# config/ (user-data), so the per-bucket "present" check selects the right set.
MIGRATION_BUCKETS: tuple[tuple[str, str, str], ...] = (
    ("save", "save", "설정·프리셋·상태"),
    ("wildcards", "wildcards", "와일드카드"),
    ("output", "output", "생성 이미지"),
    ("ui_assets", "ui_assets", "썸네일·UI 자산"),            # user-data layout (incl. artist_thumb)
    ("artist_thumb", "ui_assets/artist_thumb", "아티스트 필터 상태"),  # legacy checkout layout
    ("config", "config", "API 설정·토큰"),                  # user-data layout (NAI 토큰 등)
)

# Legacy credential file — detected but never auto-imported (separate opt-in flow).
LEGACY_CREDENTIAL_FILE = "save/nai_accounts.json"

_SKIP_PART_NAMES = {"__pycache__"}

# Files excluded from a bucket copy, keyed by bucket; values are POSIX paths
# relative to the bucket root. Credentials live in save/ but are migrated only by
# the separate opt-in flow, never by the bulk copy.
_EXCLUDED_BY_BUCKET: dict[str, set[str]] = {
    "save": {"nai_accounts.json"},
}

# Entry-point markers that identify a folder as a NAIA checkout even if it has no
# user-data folders yet.
_SOURCE_MARKERS = ("NAIA_web_headless.py", "NAIA_cold_v4.py", "__init__.py")


def _iter_files(root: Path, *, bucket: str = "") -> Iterator[Path]:
    excluded = _EXCLUDED_BY_BUCKET.get(bucket, set())
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_PART_NAMES for part in path.parts):
            continue
        if excluded and path.relative_to(root).as_posix() in excluded:
            continue
        yield path


class DataMigrationService:
    def __init__(self, context: Any = None, *, user_root: str | Path | None = None):
        self.context = context
        self._user_root_override = Path(user_root) if user_root is not None else None

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    def user_root(self) -> Path:
        if self._user_root_override is not None:
            return self._user_root_override.expanduser().resolve()
        runtime_paths = getattr(self.context, "runtime_paths", None)
        root = getattr(runtime_paths, "user_root", None)
        if root is not None:
            return Path(root).resolve()
        from app.backend.runtime.paths import resolve_runtime_paths

        return resolve_runtime_paths().user_root.resolve()

    def _target_dir(self, target_rel: str) -> Path:
        return (self.user_root() / target_rel).resolve()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def is_plausible_source(self, source: Path) -> bool:
        source = Path(source)
        if not source.is_dir():
            return False
        if any((source / bucket).is_dir() for bucket, _, _ in MIGRATION_BUCKETS):
            return True
        return any((source / marker).exists() for marker in _SOURCE_MARKERS)

    def _overlaps_target(self, source: Path) -> bool:
        """True if source is the user_root or sits inside it (self-import)."""
        user_root = self.user_root()
        try:
            source = source.resolve()
        except OSError:
            return False
        if source == user_root:
            return True
        return user_root in source.parents

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def preview(self, source_dir: str | Path) -> dict[str, Any]:
        source = Path(source_dir).expanduser()
        result: dict[str, Any] = {
            "source": str(source),
            "user_root": str(self.user_root()),
            "plausible": False,
            "same_as_target": False,
            "buckets": [],
            "credentials": {"present": False, "note": ""},
            "error": None,
        }
        if not source.is_dir():
            result["error"] = "선택한 폴더를 찾을 수 없습니다."
            return result
        source = source.resolve()
        result["source"] = str(source)
        if self._overlaps_target(source):
            result["same_as_target"] = True
            result["error"] = "현재 데이터 폴더와 같은(또는 그 내부) 위치는 가져올 수 없습니다."
            return result
        result["plausible"] = self.is_plausible_source(source)

        for bucket, target_rel, label in MIGRATION_BUCKETS:
            src = source / bucket
            target = self._target_dir(target_rel)
            present = src.is_dir()
            file_count = 0
            total_bytes = 0
            conflict_count = 0
            if present:
                for path in _iter_files(src, bucket=bucket):
                    file_count += 1
                    try:
                        total_bytes += path.stat().st_size
                    except OSError:
                        pass
                    if (target / path.relative_to(src)).exists():
                        conflict_count += 1
            result["buckets"].append({
                "bucket": bucket,
                "label": label,
                "source": str(src),
                "target": str(target),
                "present": present,
                "file_count": file_count,
                "total_bytes": total_bytes,
                "conflict_count": conflict_count,
            })

        credential = source / LEGACY_CREDENTIAL_FILE
        result["credentials"] = {
            "present": credential.is_file(),
            "note": "보안상 자격증명은 이 단계에서 가져오지 않습니다. NAI 토큰은 설정에서 다시 입력하세요.",
        }
        return result

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_from(
        self,
        source_dir: str | Path,
        *,
        conflict: str = "skip",
        include: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        source = Path(source_dir).expanduser()
        if not source.is_dir():
            return {"ok": False, "error": "선택한 폴더를 찾을 수 없습니다."}
        source = source.resolve()
        if self._overlaps_target(source):
            return {"ok": False, "error": "현재 데이터 폴더와 같은(또는 그 내부) 위치는 가져올 수 없습니다."}
        if not self.is_plausible_source(source):
            return {"ok": False, "error": "NAIA 데이터 폴더로 보이지 않습니다 (save/wildcards/output 등이 없음)."}

        conflict = conflict if conflict in {"skip", "overwrite"} else "skip"
        selected = set(include) if include is not None else {bucket for bucket, _, _ in MIGRATION_BUCKETS}

        copied: dict[str, int] = {}
        total_files = 0
        total_bytes = 0
        skipped_existing = 0
        overwritten = 0
        errors: list[str] = []

        for bucket, target_rel, _label in MIGRATION_BUCKETS:
            if bucket not in selected:
                continue
            src = source / bucket
            if not src.is_dir():
                continue
            target = self._target_dir(target_rel)
            bucket_files = 0
            for path in _iter_files(src, bucket=bucket):
                dest = target / path.relative_to(src)
                if dest.exists():
                    if conflict == "skip":
                        skipped_existing += 1
                        continue
                    overwritten += 1
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
                except OSError as exc:
                    errors.append(f"{path.name}: {exc}")
                    continue
                bucket_files += 1
                total_files += 1
                try:
                    total_bytes += dest.stat().st_size
                except OSError:
                    pass
            copied[bucket] = bucket_files

        return {
            "ok": True,
            "source": str(source),
            "user_root": str(self.user_root()),
            "copied": copied,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "skipped_existing": skipped_existing,
            "overwritten": overwritten,
            "conflict_policy": conflict,
            "errors": errors,
        }
