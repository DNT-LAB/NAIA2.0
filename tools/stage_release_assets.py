"""Stage manifest-approved NAIA release source assets.

The default mode is a dry run that only reports files. Use ``--copy`` with an
empty target directory to materialize the selected files.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path
import shutil

try:
    from tools.release_manifest_audit import DEFAULT_MANIFEST, load_manifest
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from release_manifest_audit import DEFAULT_MANIFEST, load_manifest


@dataclass(frozen=True)
class StageResult:
    source_root: str
    target_root: str
    files: list[str]
    copied: bool


def _as_posix(path: Path) -> str:
    return path.as_posix()


def _matches_pattern(relative: Path, pattern: str) -> bool:
    posix = _as_posix(relative)
    clean_pattern = pattern.replace("\\", "/").strip()
    if not clean_pattern:
        return False
    if clean_pattern.endswith("/**"):
        base = clean_pattern[:-3].strip("/")
        if posix == base or posix.startswith(f"{base}/"):
            return True
        return f"/{base}/" in f"/{posix}"
    if "/" not in clean_pattern:
        return relative.name == clean_pattern or fnmatch.fnmatchcase(relative.name, clean_pattern) or clean_pattern in relative.parts
    return fnmatch.fnmatchcase(posix, clean_pattern)


FORCED_EXCLUDE_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
FORCED_EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def _is_forced_excluded(relative: Path) -> bool:
    return (
        any(part in FORCED_EXCLUDE_PARTS for part in relative.parts)
        or relative.suffix in FORCED_EXCLUDE_SUFFIXES
    )


def _flatten_patterns(groups: dict) -> list[str]:
    return [
        pattern
        for patterns in groups.values()
        for pattern in patterns
        if isinstance(pattern, str)
    ]


def _iter_included_files(source_root: Path, include_patterns: list[str]) -> set[Path]:
    files: set[Path] = set()
    for pattern in include_patterns:
        if not pattern or pattern in {"PyQt6", "PyQt6-WebEngine"}:
            continue
        clean_pattern = pattern.replace("\\", "/")
        if clean_pattern.endswith("/**"):
            base = source_root / clean_pattern[:-3]
            if base.exists():
                for path in base.rglob("*"):
                    if path.is_file():
                        files.add(path.relative_to(source_root))
            continue
        for path in source_root.glob(pattern):
            if path.is_file():
                files.add(path.relative_to(source_root))
    return files


def collect_release_files(
    source_root: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> list[Path]:
    root = Path(source_root).resolve()
    manifest = load_manifest(manifest_path)
    include_patterns = _flatten_patterns(manifest.get("include", {}))
    exclude_patterns = _flatten_patterns(manifest.get("exclude", {}))
    selected = _iter_included_files(root, include_patterns)
    filtered = [
        relative
        for relative in selected
        if not _is_forced_excluded(relative)
        and not any(_matches_pattern(relative, pattern) for pattern in exclude_patterns)
    ]
    return sorted(filtered, key=lambda path: path.as_posix())


def stage_release_assets(
    source_root: str | Path,
    target_root: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    copy: bool = False,
) -> StageResult:
    root = Path(source_root).resolve()
    target = Path(target_root).resolve()
    files = collect_release_files(root, manifest_path=manifest_path)

    if copy:
        if target.exists() and any(target.iterdir()):
            raise RuntimeError(f"Target directory is not empty: {target}")
        target.mkdir(parents=True, exist_ok=True)
        for relative in files:
            source = root / relative
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    return StageResult(
        source_root=str(root),
        target_root=str(target),
        files=[path.as_posix() for path in files],
        copied=copy,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage NAIA release assets from the draft manifest.")
    parser.add_argument("--source", default=".", help="Source checkout root.")
    parser.add_argument("--target", required=True, help="Target staging directory.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Release include/exclude manifest path.")
    parser.add_argument("--copy", action="store_true", help="Copy selected files into the target directory.")
    args = parser.parse_args(argv)

    result = stage_release_assets(
        args.source,
        args.target,
        manifest_path=args.manifest,
        copy=args.copy,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
