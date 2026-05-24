"""Validate the two-track runtime/distribution boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_MANIFEST = Path("release_assets/manifests/runtime_distribution_tracks.json")


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _check_relative_file(
    repo_root: Path,
    raw_path: str,
    violations: list[dict[str, str]],
    reason: str,
) -> Path | None:
    if not raw_path or not _is_safe_relative_path(raw_path):
        violations.append({"type": "unsafe_or_empty_path", "path": raw_path or "<empty>", "reason": reason})
        return None
    path = repo_root / raw_path
    if not path.is_file():
        violations.append({"type": "missing_file", "path": raw_path, "reason": reason})
        return None
    return path


def _check_relative_dir(
    repo_root: Path,
    raw_path: str,
    violations: list[dict[str, str]],
    reason: str,
) -> Path | None:
    if not raw_path or not _is_safe_relative_path(raw_path):
        violations.append({"type": "unsafe_or_empty_path", "path": raw_path or "<empty>", "reason": reason})
        return None
    path = repo_root / raw_path
    if not path.is_dir():
        violations.append({"type": "missing_directory", "path": raw_path, "reason": reason})
        return None
    return path


def _contains_any(text: str, terms: list[str]) -> str:
    lowered = text.lower()
    for term in terms:
        term_text = str(term or "").strip()
        if term_text and term_text.lower() in lowered:
            return term_text
    return ""


def _check_source_web_track(repo_root: Path, track: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    _check_relative_file(repo_root, str(track.get("entrypoint") or ""), violations, "source web entrypoint is required")
    requirements_path = _check_relative_file(
        repo_root,
        str(track.get("requirements") or ""),
        violations,
        "source web requirements are required",
    )

    if requirements_path is not None:
        blocked = _contains_any(_read_text(requirements_path), [str(item) for item in track.get("forbidden_requirements_terms", [])])
        if blocked:
            violations.append({
                "type": "source_requirements_forbidden_term",
                "path": _repo_relative(requirements_path, repo_root),
                "reason": f"source web requirements must not include {blocked}",
            })

    required_terms = [str(item) for item in track.get("required_launcher_terms", [])]
    forbidden_terms = [str(item) for item in track.get("forbidden_launcher_terms", [])]
    for raw_launcher in track.get("launchers", []):
        launcher = _check_relative_file(repo_root, str(raw_launcher), violations, "source web launcher is required")
        if launcher is None:
            continue
        text = _read_text(launcher)
        for term in required_terms:
            if term and term not in text:
                violations.append({
                    "type": "source_launcher_missing_required_term",
                    "path": str(raw_launcher),
                    "reason": f"source web launcher must reference {term}",
                })
        blocked = _contains_any(text, forbidden_terms)
        if blocked:
            violations.append({
                "type": "source_launcher_forbidden_term",
                "path": str(raw_launcher),
                "reason": f"source web launcher must not require {blocked}",
            })
    local_only_roots = [str(item).strip().strip("/\\") for item in track.get("local_only_roots", [])]
    if "tests" not in local_only_roots:
        violations.append({
            "type": "source_track_missing_tests_local_only",
            "path": "source_web.local_only_roots",
            "reason": "tests must stay local-development-only and out of remote-published source",
        })
    for root in local_only_roots:
        if root and not _is_safe_relative_path(root):
            violations.append({
                "type": "unsafe_source_track_local_only_root",
                "path": root,
                "reason": "source web local-only roots must be repository-relative",
            })
    return violations


def _check_electron_release_track(repo_root: Path, track: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    _check_relative_dir(repo_root, str(track.get("root") or ""), violations, "Electron shell root is required")
    main_path = _check_relative_file(repo_root, str(track.get("main") or ""), violations, "Electron main source is required")
    package_path = _check_relative_file(
        repo_root,
        str(track.get("package_manifest") or ""),
        violations,
        "Electron package manifest is required",
    )

    if main_path is not None:
        main_text = _read_text(main_path)
        for term in track.get("required_main_terms", []):
            term_text = str(term)
            if term_text and term_text not in main_text:
                violations.append({
                    "type": "electron_main_missing_required_term",
                    "path": _repo_relative(main_path, repo_root),
                    "reason": f"Electron main must reference {term_text}",
                })

    if package_path is not None:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        if package.get("main") != "main/main.cjs":
            violations.append({
                "type": "electron_package_unexpected_main",
                "path": _repo_relative(package_path, repo_root),
                "reason": "Electron package main must remain main/main.cjs",
            })
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        for script in track.get("required_scripts", []):
            if script not in scripts:
                violations.append({
                    "type": "electron_package_missing_script",
                    "path": str(script),
                    "reason": "Electron release track requires this package script",
                })
    return violations


def _check_shared_runtime(repo_root: Path, shared: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    _check_relative_file(repo_root, str(shared.get("backend_api") or ""), violations, "shared backend API source is required")
    _check_relative_file(repo_root, str(shared.get("runtime_paths") or ""), violations, "shared runtime path source is required")
    remote_web = _check_relative_dir(repo_root, str(shared.get("remote_web") or ""), violations, "shared Remote Web source is required")
    if remote_web is not None:
        for filename in shared.get("remote_web_required_files", []):
            name = str(filename)
            if not name or "/" in name or "\\" in name:
                violations.append({
                    "type": "unsafe_remote_web_required_file",
                    "path": name or "<empty>",
                    "reason": "Remote Web required files must be filenames",
                })
                continue
            if not (remote_web / name).is_file():
                violations.append({
                    "type": "missing_remote_web_required_file",
                    "path": f"{_repo_relative(remote_web, repo_root)}/{name}",
                    "reason": "Remote Web required source file is missing",
                })

    removed_legacy = str(shared.get("removed_legacy_remote_web") or "")
    if removed_legacy:
        if not _is_safe_relative_path(removed_legacy):
            violations.append({
                "type": "unsafe_removed_legacy_path",
                "path": removed_legacy,
                "reason": "removed legacy path must be repository-relative",
            })
        elif (repo_root / removed_legacy).exists():
            violations.append({
                "type": "removed_legacy_remote_web_present",
                "path": removed_legacy,
                "reason": "ui/remote_web must not be recreated as a source-owned Remote Web UI",
            })
    return violations


def _check_release_manifest(repo_root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    raw_path = str(manifest.get("release_manifest") or "")
    path = _check_relative_file(repo_root, raw_path, violations, "release include/exclude manifest is required")
    if path is None:
        return violations

    release = json.loads(path.read_text(encoding="utf-8"))
    include = release.get("include") if isinstance(release.get("include"), dict) else {}
    exclude = release.get("exclude") if isinstance(release.get("exclude"), dict) else {}
    web_ui = set(include.get("web_ui", []))
    runtime_state = set(exclude.get("local_runtime_state", []))
    development = set(exclude.get("development_only", []))
    flattened_excludes = {
        str(value)
        for values in exclude.values()
        if isinstance(values, list)
        for value in values
    }

    if "app/web/remote/**" not in web_ui:
        violations.append({
            "type": "release_manifest_missing_canonical_web",
            "path": raw_path,
            "reason": "release web_ui include must use app/web/remote/**",
        })
    if "ui/remote_web/**" in web_ui:
        violations.append({
            "type": "release_manifest_includes_legacy_web",
            "path": raw_path,
            "reason": "release web_ui include must not use ui/remote_web/**",
        })
    for required in ("app/electron/dist/**", "user-data/**", "wildcards/**", "tests/**"):
        if required not in runtime_state and required not in development and required not in flattened_excludes:
            violations.append({
                "type": "release_manifest_missing_runtime_exclude",
                "path": required,
                "reason": "release manifest must exclude local runtime/build/test output from source staging",
            })
    return violations


def check_runtime_distribution_tracks(
    *,
    repo_root: Path = Path("."),
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path if manifest_path.is_absolute() else repo_root / manifest_path

    if not manifest_path.is_file():
        return {
            "ok": False,
            "manifest": _repo_relative(manifest_path, repo_root),
            "violations": [{"type": "missing_manifest", "path": _repo_relative(manifest_path, repo_root)}],
            "warnings": [],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracks = manifest.get("tracks") if isinstance(manifest.get("tracks"), dict) else {}
    source_web = tracks.get("source_web") if isinstance(tracks.get("source_web"), dict) else {}
    electron_release = tracks.get("electron_release") if isinstance(tracks.get("electron_release"), dict) else {}
    shared_runtime = manifest.get("shared_runtime") if isinstance(manifest.get("shared_runtime"), dict) else {}

    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    violations.extend(_check_source_web_track(repo_root, source_web))
    violations.extend(_check_electron_release_track(repo_root, electron_release))
    violations.extend(_check_shared_runtime(repo_root, shared_runtime))
    violations.extend(_check_release_manifest(repo_root, manifest))

    return {
        "ok": not violations,
        "manifest": _repo_relative(manifest_path, repo_root),
        "source_track": source_web.get("name", ""),
        "electron_track": electron_release.get("name", ""),
        "shared_remote_web": shared_runtime.get("remote_web", ""),
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    payload = check_runtime_distribution_tracks(repo_root=args.repo_root, manifest_path=args.manifest)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
