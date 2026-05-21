"""Measure a staged NAIA release artifact directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

try:
    from tools.write_release_metadata import CHECKSUMS_NAME, MANIFEST_NAME
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from write_release_metadata import CHECKSUMS_NAME, MANIFEST_NAME


def _find_defender_scanner() -> Path | None:
    candidates = [
        Path("C:/Program Files/Windows Defender/MpCmdRun.exe"),
        *sorted(Path("C:/ProgramData/Microsoft/Windows Defender/Platform").glob("*/MpCmdRun.exe"), reverse=True),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    resolved = shutil.which("MpCmdRun.exe")
    return Path(resolved) if resolved else None


def _file_stats(root: Path) -> dict[str, Any]:
    files = [path for path in root.rglob("*") if path.is_file()]
    total_bytes = sum(path.stat().st_size for path in files)
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "total_mib": round(total_bytes / (1024 * 1024), 2),
    }


def _run_defender_scan(root: Path) -> dict[str, Any]:
    scanner = _find_defender_scanner()
    if scanner is None:
        return {
            "available": False,
            "ok": None,
            "scanner": None,
            "exit_code": None,
            "stdout": "",
            "stderr": "MpCmdRun.exe not found",
        }
    completed = subprocess.run(
        [
            str(scanner),
            "-Scan",
            "-ScanType",
            "3",
            "-File",
            str(root),
            "-DisableRemediation",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "available": True,
        "ok": completed.returncode == 0,
        "scanner": str(scanner),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def measure_release_artifact(
    release_root: str | Path,
    *,
    defender_scan: bool = False,
    require_defender_scan: bool = False,
) -> dict[str, Any]:
    root = Path(release_root).resolve()
    if not root.is_dir():
        return {
            "ok": False,
            "release_root": str(root),
            "violations": [{"path": str(root), "reason": "release root is not a directory"}],
        }

    stats = _file_stats(root)
    metadata = {
        "readme": (root / "README_RELEASE.txt").is_file(),
        "release_manifest": (root / MANIFEST_NAME).is_file(),
        "checksums": (root / CHECKSUMS_NAME).is_file(),
        "backend_entry": (root / "resources" / "naia-backend" / "NAIA_web_headless.py").is_file()
        or (root / "resources" / "naia-backend" / "NAIA_web_headless.exe").is_file(),
        "bundled_python": (root / "resources" / "python" / "python.exe").is_file()
        or (root / "resources" / "python" / "bin" / "python").is_file(),
    }
    violations = [
        {"path": key, "reason": "required release metadata is missing"}
        for key, exists in metadata.items()
        if key in {"readme", "release_manifest", "checksums", "backend_entry"} and not exists
    ]
    payload: dict[str, Any] = {
        "ok": not violations,
        "release_root": str(root),
        "stats": stats,
        "metadata": metadata,
        "scanner": None,
        "violations": violations,
    }
    if defender_scan:
        scan = _run_defender_scan(root)
        payload["scanner"] = scan
        if scan.get("ok") is not True and require_defender_scan:
            payload["ok"] = False
            payload["violations"].append({"path": str(root), "reason": "Defender scan evidence is required"})
        elif scan.get("ok") is False:
            payload["ok"] = False
            payload["violations"].append({"path": str(root), "reason": "Defender scan failed or found threats"})
    elif require_defender_scan:
        payload["ok"] = False
        payload["violations"].append({"path": str(root), "reason": "Defender scan was required but not requested"})
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure a staged NAIA release artifact directory.")
    parser.add_argument("release_root", help="Staged release directory.")
    parser.add_argument("--defender-scan", action="store_true", help="Run Microsoft Defender local scan when available.")
    parser.add_argument("--require-defender-scan", action="store_true", help="Fail unless a Defender scan runs and succeeds.")
    args = parser.parse_args(argv)

    payload = measure_release_artifact(
        args.release_root,
        defender_scan=args.defender_scan or args.require_defender_scan,
        require_defender_scan=args.require_defender_scan,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
