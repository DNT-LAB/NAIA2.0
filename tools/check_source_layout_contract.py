"""Validate the final headless/Electron source layout contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_MANIFEST = Path("release_assets/manifests/source_layout_contract.json")


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _check_path_list(
    *,
    repo_root: Path,
    paths: list[str],
    kind: str,
    expect_dir: bool,
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    seen: set[str] = set()

    for raw_path in paths:
        if raw_path in seen:
            violations.append({
                "type": f"duplicate_{kind}",
                "path": raw_path,
            })
            continue
        seen.add(raw_path)

        if not _is_safe_relative_path(raw_path):
            violations.append({
                "type": f"unsafe_{kind}",
                "path": raw_path,
            })
            continue

        resolved = repo_root / raw_path
        if not resolved.exists():
            violations.append({
                "type": f"missing_{kind}",
                "path": raw_path,
            })
            continue

        if expect_dir and not resolved.is_dir():
            violations.append({
                "type": f"not_a_directory_{kind}",
                "path": raw_path,
            })
        if not expect_dir and not resolved.is_file():
            violations.append({
                "type": f"not_a_file_{kind}",
                "path": raw_path,
            })

    return violations


def check_source_layout_contract(
    *,
    repo_root: Path = Path("."),
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path if manifest_path.is_absolute() else repo_root / manifest_path

    if not manifest_path.is_file():
        return {
            "ok": False,
            "contract": _repo_relative(manifest_path, repo_root),
            "violations": [{"type": "missing_manifest", "path": _repo_relative(manifest_path, repo_root)}],
            "warnings": [],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_directories = list(manifest.get("required_directories", []))
    python_package_markers = list(manifest.get("python_package_markers", []))
    runtime_only_roots = list(manifest.get("runtime_only_roots", []))
    development_only_roots = list(manifest.get("development_only_roots", []))

    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    violations.extend(
        _check_path_list(
            repo_root=repo_root,
            paths=required_directories,
            kind="required_directory",
            expect_dir=True,
        )
    )
    violations.extend(
        _check_path_list(
            repo_root=repo_root,
            paths=python_package_markers,
            kind="python_package_marker",
            expect_dir=False,
        )
    )

    for root in runtime_only_roots:
        if not _is_safe_relative_path(root):
            violations.append({"type": "unsafe_runtime_only_root", "path": root})
        if root in required_directories:
            warnings.append({
                "type": "runtime_root_also_required_source_directory",
                "path": root,
            })

    for root in development_only_roots:
        if not _is_safe_relative_path(root):
            violations.append({"type": "unsafe_development_only_root", "path": root})
        if root in required_directories:
            violations.append({
                "type": "development_only_root_required_as_source_directory",
                "path": root,
            })

    return {
        "ok": not violations,
        "contract": _repo_relative(manifest_path, repo_root),
        "required_directory_count": len(required_directories),
        "python_package_marker_count": len(python_package_markers),
        "runtime_only_root_count": len(runtime_only_roots),
        "development_only_root_count": len(development_only_roots),
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    payload = check_source_layout_contract(repo_root=args.repo_root, manifest_path=args.manifest)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
