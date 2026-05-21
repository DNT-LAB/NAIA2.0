"""Preflight checks for a staged NAIA Electron release directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    from tools.release_manifest_audit import audit_payload
    from tools.write_release_metadata import CHECKSUMS_NAME, MANIFEST_NAME
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from release_manifest_audit import audit_payload
    from write_release_metadata import CHECKSUMS_NAME, MANIFEST_NAME


REQUIRED_PATHS = (
    "README_RELEASE.txt",
    MANIFEST_NAME,
    CHECKSUMS_NAME,
    "resources/naia-backend/NAIA_web_headless.py",
    "resources/naia-backend/app/web/remote/index.html",
    "resources/naia-backend/app/web/remote/app.js",
    "user-data",
)

REQUIRED_EXTERNAL_DEPENDENCY_TERMS = (
    "NovelAI",
    "WebUI",
    "ComfyUI",
    "downloadable",
)


def _python_runtime_exists(root: Path) -> bool:
    return (
        (root / "resources" / "python" / "python.exe").is_file()
        or (root / "resources" / "python" / "bin" / "python").is_file()
    )


def _user_data_empty(root: Path) -> bool:
    user_data = root / "user-data"
    return user_data.is_dir() and not any(user_data.iterdir())


def _release_notes_check(root: Path) -> dict:
    readme_path = root / "README_RELEASE.txt"
    manifest_path = root / MANIFEST_NAME
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    manifest_terms: list[str] = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_terms = [str(item) for item in manifest.get("external_dependencies", [])]
        except Exception:
            manifest_terms = []
    manifest_text = "\n".join(manifest_terms)
    missing_readme_terms = [
        term
        for term in REQUIRED_EXTERNAL_DEPENDENCY_TERMS
        if term not in readme_text
    ]
    missing_manifest_terms = [
        term
        for term in REQUIRED_EXTERNAL_DEPENDENCY_TERMS
        if term not in manifest_text
    ]
    return {
        "required_terms": list(REQUIRED_EXTERNAL_DEPENDENCY_TERMS),
        "missing_readme_terms": missing_readme_terms,
        "missing_manifest_terms": missing_manifest_terms,
        "readme_exists": readme_path.is_file(),
        "manifest_external_dependency_count": len(manifest_terms),
        "external_dependencies_listed": (
            not missing_readme_terms
            and not missing_manifest_terms
            and readme_path.is_file()
            and bool(manifest_terms)
        ),
        "ok": (
            not missing_readme_terms
            and not missing_manifest_terms
            and readme_path.is_file()
            and bool(manifest_terms)
        ),
    }


def check_release_preflight(
    release_root: str | Path,
    *,
    require_bundled_python: bool = False,
) -> dict:
    root = Path(release_root).resolve()
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not root.is_dir():
        return {
            "ok": False,
            "release_root": str(root),
            "violations": [{"path": str(root), "reason": "release root is not a directory"}],
            "warnings": warnings,
        }

    for relative in REQUIRED_PATHS:
        path = root / relative
        if not path.exists():
            violations.append({"path": relative, "reason": "required release path is missing"})

    audit = audit_payload(root)
    for violation in audit.get("violations", []):
        violations.append({
            "path": str(violation.get("path", "")),
            "reason": f"release manifest audit: {violation.get('reason', '')}",
        })

    if not _user_data_empty(root):
        violations.append({"path": "user-data", "reason": "portable user-data must exist and be empty in a fresh release"})

    bundled_python = _python_runtime_exists(root)
    if require_bundled_python and not bundled_python:
        violations.append({"path": "resources/python", "reason": "bundled Python runtime is required but missing"})
    elif not bundled_python:
        warnings.append({"path": "resources/python", "reason": "bundled Python runtime is absent; release needs system Python or later runtime staging"})

    manifest_path = root / MANIFEST_NAME
    checksums_path = root / CHECKSUMS_NAME
    manifest: dict | None = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not manifest.get("runtime", {}).get("backend_entry_exists"):
                violations.append({"path": MANIFEST_NAME, "reason": "metadata does not confirm backend entry exists"})
        except Exception as exc:
            violations.append({"path": MANIFEST_NAME, "reason": f"metadata parse failed: {exc}"})
    if checksums_path.is_file() and not checksums_path.read_text(encoding="utf-8").strip():
        violations.append({"path": CHECKSUMS_NAME, "reason": "checksum manifest is empty"})

    release_notes = _release_notes_check(root)
    if not release_notes["ok"]:
        violations.append({
            "path": "README_RELEASE.txt",
            "reason": "release notes must list NovelAI, WebUI, ComfyUI, and optional downloadable data dependencies",
        })

    return {
        "ok": not violations,
        "release_root": str(root),
        "bundled_python": bundled_python,
        "require_bundled_python": bool(require_bundled_python),
        "checks": {
            "release_notes": release_notes,
        },
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a staged NAIA Electron release directory.")
    parser.add_argument("release_root", help="Staged NAIA release directory.")
    parser.add_argument(
        "--require-bundled-python",
        action="store_true",
        help="Fail if resources/python does not contain a Python runtime.",
    )
    args = parser.parse_args(argv)

    payload = check_release_preflight(args.release_root, require_bundled_python=args.require_bundled_python)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
