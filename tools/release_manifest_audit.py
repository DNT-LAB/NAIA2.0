"""Audit a NAIA release directory against the draft include/exclude policy."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path
from typing import Iterable


DEFAULT_MANIFEST = Path("release_assets/manifests/release_include_exclude_draft.json")
FORBIDDEN_PATH_PARTS = {
    ".claude",
    ".cloudflared_bin",
    ".experimental",
    ".pytest_cache",
    "__pycache__",
    "docs",
    "legacy_desktop",
    "logs",
    "node_modules",
    "output",
    "refactor_docs",
    "refactor_plans",
    "save",
    "temp",
    "tests",
    "tmp",
    "venv",
    "wildcards",
}
FORBIDDEN_FILE_GLOBS = (
    "AGENTS.md",
    "CLAUDE.md",
    "*.md",
    "NAIA_cold_v4.py",
    "requirements-desktop-legacy*.txt",
    "artist_dictionary.py",
    "danbooru_character.py",
    "result_dict_copyright.py",
    "result_dupl.py",
    "artist_thumbnail*.json",
    "*.xlsx",
    "*.naiv4vibe",
    "*.naiv4vibebundle",
    "00001.png",
    "20250827_*.png",
    "manual_*.png",
    "test*.png",
    "temp_image.png",
    "character_reference_*_result.png",
    "vibe_transfer_*_result.png",
    "stickman_canvas_tmp.webp",
    "~$*",
    "naia_temp_rows.parquet",
)
FORBIDDEN_PATH_GLOBS = (
    "core/context.py",
    "core/image_crud_controller.py",
    "core/mode_ware_manager.py",
    "core/tag_data_manager.py",
    "core/dll_fix.py",
    "tabs/comic_generator/*",
    "ui/variational/*",
    "experimental/ontology_visualizer/*",
    "temp/ezmode/*",
    "data/character_thumbnails/*",
    "data/event_preset/*",
    "data/event_preset_thumbnail",
    "data/e621_boost_static.py",
    "data/tags/*",
    "data/tagger/*",
    "ui/event_preset/*",
    "ui/*/downloaded/*",
    "*/data/character_thumbnails/*",
    "*/data/event_preset/*",
    "*/data/event_preset_thumbnail",
    "*/data/e621_boost_static.py",
    "*/data/tags/*",
    "*/data/tagger/*",
    "*/ui/event_preset/*",
    "*/ui/*/downloaded/*",
    "tmp_codex_*/*",
    "*/tmp_codex_*/*",
    "*/core/context.py",
    "*/core/image_crud_controller.py",
    "*/core/mode_ware_manager.py",
    "*/core/tag_data_manager.py",
    "*/core/dll_fix.py",
    "*/tabs/comic_generator/*",
    "*/ui/variational/*",
    "*/experimental/ontology_visualizer/*",
    "*/temp/ezmode/*",
    "app/electron/dist/*",
    "app/electron/node_modules/*",
    "*/app/electron/dist/*",
    "*/app/electron/node_modules/*",
)
ALLOWED_BOOTSTRAP_DATA_GLOBS = (
    "data/clothes_list.txt",
    "data/color.txt",
    "data/characteristic_list.txt",
    "data/taglist/*.json",
    "*/data/clothes_list.txt",
    "*/data/color.txt",
    "*/data/characteristic_list.txt",
    "*/data/taglist/*.json",
)
FORBIDDEN_PACKAGE_NAMES = (
    "PyQt6",
    "PyQt6-Qt6",
    "PyQt6-WebEngine",
    "PyQt6-WebEngine-Qt6",
    "PyQt6_sip",
    "PyQt6-QScintilla",
)


@dataclass(frozen=True)
class ReleaseViolation:
    path: str
    reason: str


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _relative_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file():
            yield path.relative_to(root)
        elif path.is_dir() and not any(path.iterdir()):
            yield path.relative_to(root)


def _has_forbidden_part(relative: Path) -> str | None:
    if relative.parts and relative.parts[0] == "user-data" and len(relative.parts) > 1:
        return "portable user-data must not contain bundled runtime state"
    is_python_runtime = len(relative.parts) >= 2 and relative.parts[0] == "resources" and relative.parts[1] == "python"
    for part in relative.parts:
        if is_python_runtime and part == "venv":
            continue
        if part in FORBIDDEN_PATH_PARTS:
            return f"forbidden runtime/development path part: {part}"
        if part in FORBIDDEN_PACKAGE_NAMES:
            return f"forbidden desktop dependency package: {part}"
    return None


def _has_forbidden_filename(relative: Path) -> str | None:
    name = relative.name
    for pattern in FORBIDDEN_FILE_GLOBS:
        if fnmatch.fnmatchcase(name, pattern):
            return f"forbidden file pattern: {pattern}"
    return None


def _has_forbidden_path_pattern(relative: Path) -> str | None:
    posix = relative.as_posix()
    if len(relative.parts) >= 2 and relative.parts[0] == "resources" and relative.parts[1] == "python":
        return None
    if any(fnmatch.fnmatchcase(posix, pattern) for pattern in ALLOWED_BOOTSTRAP_DATA_GLOBS):
        return None
    for index, part in enumerate(relative.parts):
        if part == "data":
            next_part = relative.parts[index + 1] if len(relative.parts) > index + 1 else ""
            if next_part != "source":
                return "forbidden runtime data path: data/**"
    for pattern in FORBIDDEN_PATH_GLOBS:
        if fnmatch.fnmatchcase(posix, pattern):
            return f"forbidden path pattern: {pattern}"
    return None


def audit_release_directory(
    release_root: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> list[ReleaseViolation]:
    root = Path(release_root)
    if not root.exists():
        return [ReleaseViolation(str(root), "release root does not exist")]
    if not root.is_dir():
        return [ReleaseViolation(str(root), "release root is not a directory")]

    return audit_release_paths(_relative_files(root), manifest_path=manifest_path)


def audit_release_paths(
    relative_paths: Iterable[str | Path],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> list[ReleaseViolation]:
    manifest = load_manifest(manifest_path)
    manifest_rules = "\n".join(manifest.get("hard_rules", []))
    violations: list[ReleaseViolation] = []

    if "PyQt6" not in manifest_rules or "legacy_desktop" not in manifest_rules:
        violations.append(
            ReleaseViolation(str(manifest_path), "manifest hard rules do not mention PyQt6 and legacy_desktop")
        )

    for item in relative_paths:
        relative = Path(item)
        reason = (
            _has_forbidden_path_pattern(relative)
            or _has_forbidden_part(relative)
            or _has_forbidden_filename(relative)
        )
        if reason:
            violations.append(ReleaseViolation(relative.as_posix(), reason))

    return violations


def audit_payload(release_root: str | Path, *, manifest_path: str | Path = DEFAULT_MANIFEST) -> dict:
    violations = audit_release_directory(release_root, manifest_path=manifest_path)
    return {
        "ok": not violations,
        "release_root": str(Path(release_root)),
        "manifest": str(Path(manifest_path)),
        "violations": [violation.__dict__ for violation in violations],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a NAIA release directory.")
    parser.add_argument("release_root", help="Directory containing a staged or packaged NAIA release.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Release include/exclude manifest path.")
    args = parser.parse_args(argv)

    payload = audit_payload(args.release_root, manifest_path=args.manifest)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
