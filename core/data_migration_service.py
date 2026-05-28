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

import json
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
# Each entry is ``(source_rel, target_rel, label)``. The source path may be a
# directory (whole tree copies) or a single file (copies that file to the
# target path verbatim). Buckets whose source path is missing in a chosen
# install are silently skipped, so adding both layouts is safe.
MIGRATION_BUCKETS: tuple[tuple[str, str, str], ...] = (
    ("save", "save", "설정·프리셋·상태"),
    ("wildcards", "wildcards", "와일드카드"),
    ("output", "output", "생성 이미지"),
    ("ui_assets", "ui_assets", "썸네일·UI 자산"),            # user-data layout (incl. artist_thumb)
    ("artist_thumb", "ui_assets/artist_thumb", "아티스트 필터 상태"),  # legacy checkout layout
    ("config", "config", "API 설정·토큰"),                  # user-data layout (NAI 토큰 등)
    # User-generated content under ``data/`` that previously was not migrated.
    # Each subdir is a known user-state directory (the rest of ``data/`` is
    # bundled with the app or re-downloadable via Install Manager — never
    # copied to avoid carrying stale bundles forward).
    ("data/character_thumbnails", "data/character_thumbnails", "캐릭터 뷰어 썸네일"),
    ("data/event_preset", "data/event_preset", "프리셋 사용자 데이터"),
    ("data/event_preset_thumbnail", "data/event_preset_thumbnail", "프리셋 썸네일"),
    ("data/quick_search", "data/quick_search", "퀵 검색 데이터"),
    # Heavy runtime-downloadable tag corpora — usually fetched from Hugging Face
    # via Install Manager. Migrating an existing copy lets users skip the ~2GB
    # Hugging Face download when they already have it from a prior NAIA install.
    ("data/tags", "data/tags", "태그 데이터 (~2GB)"),
    ("data/tag_index", "data/tag_index", "태그 인덱스"),
    # Legacy source-checkout layout stored artist thumbnail packs as multi-GB
    # JSON files directly under ``data/``; the portable runtime keeps them at
    # ``ui_assets/artist_thumb/<filename>``. Explicit remap so users who had
    # downloaded packs in a legacy install do not lose ~10GB of cached data.
    # Each file is opt-in (large size) and skipped if absent in the source.
    ("data/artist_thumbnail.json", "ui_assets/artist_thumb/artist_thumbnail.json", "아티스트 썸네일 팩 (기본)"),
    ("data/artist_thumbnail_nai.json", "ui_assets/artist_thumb/artist_thumbnail_nai.json", "아티스트 썸네일 팩 (NAI)"),
    ("data/artist_thumbnail_anima.json", "ui_assets/artist_thumb/artist_thumbnail_anima.json", "아티스트 썸네일 팩 (ANIMA)"),
    ("data/artist_thumbnail_anima_bucket2.json", "ui_assets/artist_thumb/artist_thumbnail_anima_bucket2.json", "아티스트 썸네일 팩 (ANIMA bucket2)"),
    ("data/artist_thumbnail_anima_bucket3.json", "ui_assets/artist_thumb/artist_thumbnail_anima_bucket3.json", "아티스트 썸네일 팩 (ANIMA bucket3)"),
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
    # A bucket may point at a directory (tree copy) or at a single file (e.g.
    # ``data/event_preset_thumbnail`` is a multi-hundred-MB JSON file, not a
    # folder). Yield the file itself in the single-file case so the same
    # preview/import code paths handle both shapes.
    if root.is_file():
        yield root
        return
    excluded = _EXCLUDED_BY_BUCKET.get(bucket, set())
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_PART_NAMES for part in path.parts):
            continue
        if excluded and path.relative_to(root).as_posix() in excluded:
            continue
        yield path


def _bucket_target_for(src: Path, source_root: Path, target_root: Path) -> Path:
    """Resolve the destination path for a file copied from ``source_root``.

    For directory buckets, the file is placed under ``target_root`` preserving
    its path relative to the bucket root. For single-file buckets (where the
    bucket source path *is* the file), the target is ``target_root`` itself
    so the file can be renamed/relocated as part of the bucket mapping.
    """
    if source_root.is_file():
        return target_root
    return target_root / src.relative_to(source_root)


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

    def _resolve_source_root(self, source: Path) -> Path:
        """Descend into a portable install's ``user-data`` folder when needed.

        A downloaded portable build keeps its data buckets under
        ``<NAIA-Portable>/user-data`` (next to ``NAIA.exe``), so a user who picks
        the portable folder itself is pointing one level above the actual data.
        When the chosen folder is not a plausible source on its own but contains a
        plausible ``user-data`` subfolder, transparently import from that
        subfolder. All entry points (``preview``/``import_from``/
        ``import_nai_token``) funnel through here so they agree on the location.
        """
        source = Path(source)
        if self.is_plausible_source(source):
            return source
        candidate = source / "user-data"
        if candidate.is_dir() and self.is_plausible_source(candidate):
            return candidate.resolve()
        return source

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
        source = self._resolve_source_root(source.resolve())
        result["source"] = str(source)
        if self._overlaps_target(source):
            result["same_as_target"] = True
            result["error"] = "현재 데이터 폴더와 같은(또는 그 내부) 위치는 가져올 수 없습니다."
            return result
        result["plausible"] = self.is_plausible_source(source)

        for bucket, target_rel, label in MIGRATION_BUCKETS:
            src = source / bucket
            target = self._target_dir(target_rel)
            present = src.is_dir() or src.is_file()
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
                    dest_path = _bucket_target_for(path, src, target)
                    if dest_path.exists():
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
            "note": "보안상 자격증명은 일반 가져오기에 포함되지 않습니다. NAI 토큰은 아래 전용 버튼으로 따로 가져오거나 설정에서 다시 입력하세요.",
        }
        # The main NAI token lives in the legacy install's encrypted token store
        # (config/secure_tokens.json), never in the bulk-copied buckets. Surface
        # whether it can be imported via the dedicated opt-in button.
        token, token_error = self._read_legacy_nai_token(source)
        result["nai_token"] = {
            "legacy_present": bool(token),
            "current_present": bool(self._current_nai_token()),
            "error": token_error,
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
        source = self._resolve_source_root(source.resolve())
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
            if not (src.is_dir() or src.is_file()):
                continue
            target = self._target_dir(target_rel)
            bucket_files = 0
            for path in _iter_files(src, bucket=bucket):
                dest = _bucket_target_for(path, src, target)
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
            # ``ok`` means the import ran (top-level failures already returned
            # early). A partial run still copies what it can; ``partial`` /
            # ``failed_files`` surface per-file OSErrors so callers don't report a
            # run that dropped files as a clean success.
            "ok": True,
            "partial": bool(errors),
            "failed_files": len(errors),
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

    # ------------------------------------------------------------------
    # NAI credential (opt-in, separate from the bulk copy)
    # ------------------------------------------------------------------

    def _current_nai_token(self) -> str:
        manager = getattr(self.context, "secure_token_manager", None)
        if manager is None:
            return ""
        try:
            return str(manager.get_token("nai_token") or "")
        except Exception:
            return ""

    def _read_legacy_nai_token(self, source: Path) -> tuple[str, str | None]:
        """Decrypt the main ``nai_token`` from a legacy install's token store.

        Returns ``(token, error)``. The token is read from
        ``<source>/config/secure_tokens.json`` and decrypted with that file's own
        embedded Fernet key (the legacy install's key, not the current one). The
        legacy multi-account file (``save/nai_accounts.json``) only holds account
        metadata, never the token itself, so it is intentionally not consulted.
        """
        # Candidate locations, in priority order:
        #   1. ``<source>/config/secure_tokens.json`` — portable user-data layout;
        #      the source resolver normally lands here for a portable root.
        #   2. ``<source>/user-data/config/secure_tokens.json`` — legacy source
        #      checkout whose top-level looks plausible (save/, wildcards/ from
        #      a non-portable run) but whose portable runtime wrote the token
        #      under a nested ``user-data/``. Without this fallback, picking the
        #      checkout root passes plausibility yet the token is invisible.
        cred_candidates = (
            source / "config" / "secure_tokens.json",
            source / "user-data" / "config" / "secure_tokens.json",
        )
        cred_file = next((path for path in cred_candidates if path.is_file()), None)
        if cred_file is None:
            return "", "이전 설치에서 NAI 토큰 파일(config/secure_tokens.json)을 찾지 못했습니다. 설정에서 직접 입력하세요."
        try:
            data = json.loads(cred_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return "", f"토큰 파일을 읽을 수 없습니다: {exc}"
        if not isinstance(data, dict):
            return "", "토큰 파일 형식이 올바르지 않습니다."
        key = data.get("_key")
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        stored = tokens.get("nai_token")
        if not stored:
            return "", "이전 설치에 저장된 NAI 토큰이 없습니다."
        if not key:
            return "", "토큰 파일에 복호화 키가 없어 NAI 토큰을 가져올 수 없습니다."
        try:
            from cryptography.fernet import Fernet

            token = Fernet(str(key).encode()).decrypt(str(stored).encode()).decode()
        except Exception:
            return "", "NAI 토큰을 복호화하지 못했습니다 (키 불일치 또는 파일 손상)."
        return token, None

    def import_nai_token(self, source_dir: str | Path, *, overwrite: bool = False) -> dict[str, Any]:
        """Import only the main NAI token from a legacy install into the current
        secure token store. Opt-in / explicit; never part of the bulk copy.

        When the current store already holds a token and ``overwrite`` is False,
        returns ``needs_confirm`` so the caller can ask before clobbering it.
        """
        source = Path(source_dir).expanduser()
        if not source.is_dir():
            return {"ok": False, "error": "선택한 폴더를 찾을 수 없습니다."}
        source = self._resolve_source_root(source.resolve())
        if self._overlaps_target(source):
            return {"ok": False, "error": "현재 데이터 폴더와 같은(또는 그 내부) 위치는 가져올 수 없습니다."}
        token, error = self._read_legacy_nai_token(source)
        if not token:
            return {"ok": False, "error": error or "가져올 NAI 토큰이 없습니다."}
        manager = getattr(self.context, "secure_token_manager", None)
        if manager is None:
            return {"ok": False, "error": "토큰 저장소를 사용할 수 없습니다."}
        current = self._current_nai_token()
        if current and not overwrite:
            return {
                "ok": False,
                "needs_confirm": True,
                "current_present": True,
                "error": "현재 설치에 이미 NAI 토큰이 저장돼 있습니다. 덮어쓰시겠습니까?",
            }
        manager.save_token("nai_token", token)
        return {"ok": True, "imported": True, "overwritten": bool(current)}
