"""Validate a release artifact shape for clean-machine NAIA startup.

This gate is stricter than the lower-level smoke checks. It answers one
release question: can this artifact be moved away from the source checkout and
still contain the launch resources, metadata, and empty writable-root skeleton
that a fresh Windows machine needs?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from tools.check_release_preflight import check_release_preflight
    from tools.measure_release_artifact import measure_release_artifact
    from tools.smoke_packaged_electron_app import smoke_packaged_electron_app
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from check_release_preflight import check_release_preflight
    from measure_release_artifact import measure_release_artifact
    from smoke_packaged_electron_app import smoke_packaged_electron_app


KIND_STAGED_RELEASE = "staged-release"
KIND_PACKAGED_ELECTRON = "packaged-electron"
VALID_KINDS = (KIND_STAGED_RELEASE, KIND_PACKAGED_ELECTRON)

FORBIDDEN_TOP_LEVEL = {
    ".git",
    ".github",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "docs",
    "legacy_desktop",
    "logs",
    "output",
    "refactor_docs",
    "refactor_plans",
    "save",
    "temp",
    "tests",
    "tmp",
    "venv",
}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _top_level_residue_violations(root: Path) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    if not root.is_dir():
        return violations
    for child in root.iterdir():
        if child.name in FORBIDDEN_TOP_LEVEL:
            violations.append({
                "path": child.name,
                "reason": "source checkout or runtime-state residue is not allowed in a clean-machine artifact",
            })
    return violations


def _portable_user_data_check(root: Path) -> dict[str, Any]:
    user_data = root / "user-data"
    exists = user_data.is_dir()
    empty = exists and not any(user_data.iterdir())
    return {
        "path": "user-data",
        "exists": exists,
        "empty": empty,
        "ok": exists and empty,
    }


def _metadata_check(root: Path) -> dict[str, Any]:
    required = [
        "README_RELEASE.txt",
        "RELEASE_MANIFEST.json",
        "CHECKSUMS.sha256",
    ]
    missing = [relative for relative in required if not (root / relative).is_file()]
    return {
        "required": required,
        "missing": missing,
        "ok": not missing,
    }


def _backend_resource_check(root: Path) -> dict[str, Any]:
    backend = root / "resources" / "naia-backend"
    expected = [
        backend / "NAIA_web_headless.py",
        backend / "app" / "web" / "remote" / "index.html",
        backend / "app" / "web" / "remote" / "app.js",
    ]
    missing = [_relative(path, root) for path in expected if not path.is_file()]
    return {
        "backend_root": _relative(backend, root),
        "missing": missing,
        "ok": backend.is_dir() and not missing,
    }


def _add_violations(
    violations: list[dict[str, str]],
    *,
    source: str,
    items: list[dict[str, str]],
) -> None:
    for item in items:
        violations.append({
            "path": str(item.get("path", "")),
            "reason": f"{source}: {item.get('reason', '')}",
        })


def check_clean_machine_readiness(
    artifact_root: str | Path,
    *,
    kind: str,
    require_bundled_python: bool = False,
    skip_backend_smoke: bool = True,
    defender_scan: bool = False,
    require_defender_scan: bool = False,
) -> dict[str, Any]:
    root = Path(artifact_root).resolve()
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    checks: dict[str, Any] = {
        "metadata": _metadata_check(root),
        "backend_resources": _backend_resource_check(root),
        "portable_user_data": _portable_user_data_check(root),
    }

    if kind not in VALID_KINDS:
        return {
            "ok": False,
            "kind": kind,
            "artifact_root": str(root),
            "violations": [{"path": "kind", "reason": f"unsupported artifact kind: {kind}"}],
            "warnings": [],
            "checks": checks,
        }

    if not root.is_dir():
        return {
            "ok": False,
            "kind": kind,
            "artifact_root": str(root),
            "violations": [{"path": str(root), "reason": "artifact root is not a directory"}],
            "warnings": [],
            "checks": checks,
        }

    violations.extend(_top_level_residue_violations(root))
    if not checks["metadata"]["ok"]:
        for path in checks["metadata"]["missing"]:
            violations.append({"path": path, "reason": "release metadata is required for clean-machine handoff"})
    if not checks["backend_resources"]["ok"]:
        for path in checks["backend_resources"]["missing"]:
            violations.append({"path": path, "reason": "backend launch resource is missing"})
    if not checks["portable_user_data"]["ok"]:
        violations.append({"path": "user-data", "reason": "portable user-data must exist and be empty"})

    preflight = check_release_preflight(root, require_bundled_python=require_bundled_python)
    checks["preflight"] = preflight
    _add_violations(violations, source="preflight", items=preflight.get("violations", []))
    warnings.extend(preflight.get("warnings", []))

    measurement = measure_release_artifact(
        root,
        defender_scan=defender_scan or require_defender_scan,
        require_defender_scan=require_defender_scan,
    )
    checks["measurement"] = measurement
    _add_violations(violations, source="measurement", items=measurement.get("violations", []))

    packaged_smoke: dict[str, Any] | None = None
    if kind == KIND_PACKAGED_ELECTRON:
        packaged_smoke = smoke_packaged_electron_app(
            root,
            require_bundled_python=require_bundled_python,
            skip_backend_smoke=skip_backend_smoke,
        )
        _add_violations(violations, source="packaged-smoke", items=packaged_smoke.get("violations", []))
    checks["packaged_smoke"] = packaged_smoke

    return {
        "ok": not violations,
        "kind": kind,
        "artifact_root": str(root),
        "require_bundled_python": bool(require_bundled_python),
        "skip_backend_smoke": bool(skip_backend_smoke),
        "defender_scan": bool(defender_scan or require_defender_scan),
        "require_defender_scan": bool(require_defender_scan),
        "bundled_python": bool(preflight.get("bundled_python")),
        "stats": measurement.get("stats"),
        "violations": violations,
        "warnings": warnings,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check NAIA release artifact clean-machine readiness.")
    parser.add_argument("artifact_root", help="Staged release or packaged Electron directory.")
    parser.add_argument("--kind", required=True, choices=VALID_KINDS, help="Artifact shape to validate.")
    parser.add_argument("--require-bundled-python", action="store_true", help="Fail unless resources/python exists.")
    parser.add_argument("--defender-scan", action="store_true", help="Run Microsoft Defender local scan when available.")
    parser.add_argument("--require-defender-scan", action="store_true", help="Fail unless a Defender scan runs and succeeds.")
    parser.add_argument(
        "--run-backend-smoke",
        action="store_true",
        help="For packaged Electron artifacts, also import/smoke the packaged backend.",
    )
    args = parser.parse_args(argv)

    payload = check_clean_machine_readiness(
        args.artifact_root,
        kind=args.kind,
        require_bundled_python=args.require_bundled_python,
        skip_backend_smoke=not args.run_backend_smoke,
        defender_scan=args.defender_scan,
        require_defender_scan=args.require_defender_scan,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
