"""Validate manifest-selected release source payload before staging.

This checker is non-mutating. It audits the files selected by
``tools/stage_release_assets.py`` so stale files under app/electron/dist do not
hide source-selection regressions.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import sys
from typing import Any

try:
    from tools.release_manifest_audit import DEFAULT_MANIFEST
    from tools.release_manifest_audit import audit_release_paths
    from tools.stage_release_assets import collect_release_files
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from release_manifest_audit import DEFAULT_MANIFEST
    from release_manifest_audit import audit_release_paths
    from stage_release_assets import collect_release_files


REQUIRED_SELECTED_FILES = {
    "NAIA_web_headless.py",
    "requirements-headless.txt",
    "app/web/remote/index.html",
    "app/web/remote/app.js",
    "data/clothes_list.txt",
    "data/color.txt",
    "data/characteristic_list.txt",
}
REQUIRED_SELECTED_GLOBS = {
    "data/taglist/*.json",
}
FORBIDDEN_SELECTED_PATTERNS = {
    "wildcards/**",
    "data/tags/**",
    "data/event_preset/**",
    "data/event_preset_thumbnail",
    "data/character_thumbnails/**",
    "data/tagger/**",
    "ui/remote_web/**",
    "legacy_desktop/**",
    "app/electron/dist/**",
    "app/electron/node_modules/**",
    "save/**",
    "output/**",
    "logs/**",
    "tmp/**",
    "temp/**",
    "requirements-desktop-legacy*.txt",
}


def _matches(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    candidate = pattern.replace("\\", "/")
    if candidate.endswith("/**"):
        base = candidate[:-3].rstrip("/")
        return normalized == base or normalized.startswith(base + "/")
    return fnmatch.fnmatchcase(normalized, candidate)


def validate_selected_release_files(files: list[str]) -> list[dict[str, str]]:
    selected = {str(path).replace("\\", "/") for path in files}
    violations: list[dict[str, str]] = []

    for required in sorted(REQUIRED_SELECTED_FILES):
        if required not in selected:
            violations.append({"path": required, "reason": "required release source file is not selected"})

    for pattern in sorted(REQUIRED_SELECTED_GLOBS):
        if not any(_matches(path, pattern) for path in selected):
            violations.append({"path": pattern, "reason": "required release source pattern has no selected files"})

    for path in sorted(selected):
        for pattern in sorted(FORBIDDEN_SELECTED_PATTERNS):
            if _matches(path, pattern):
                violations.append({"path": path, "reason": f"forbidden release source pattern selected: {pattern}"})
                break
    return violations


def check_release_source_payload(
    source_root: str | Path = ".",
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    files = [path.as_posix() for path in collect_release_files(source_root, manifest_path=manifest_path)]
    violations = validate_selected_release_files(files)
    for violation in audit_release_paths(files, manifest_path=manifest_path):
        violations.append({"path": violation.path, "reason": f"release manifest audit: {violation.reason}"})
    return {
        "ok": not violations,
        "source_root": str(Path(source_root)),
        "manifest": str(Path(manifest_path)),
        "selected_file_count": len(files),
        "required_file_count": len(REQUIRED_SELECTED_FILES),
        "required_glob_count": len(REQUIRED_SELECTED_GLOBS),
        "forbidden_pattern_count": len(FORBIDDEN_SELECTED_PATTERNS),
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate manifest-selected release source payload.")
    parser.add_argument("--source", default=".", help="Source checkout root.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Release include/exclude manifest path.")
    args = parser.parse_args(argv)

    payload = check_release_source_payload(args.source, manifest_path=args.manifest)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
