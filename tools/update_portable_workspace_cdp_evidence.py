"""Augment portable workspace evidence with real packaged Electron runtime checks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Callable

try:
    from tools.check_clean_machine_readiness import check_clean_machine_readiness
    from tools.run_electron_portable_workspace import DEFAULT_OUTPUT, summarize_electron_portable_workspace
    from tools.smoke_electron_cdp import smoke_electron_cdp
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from check_clean_machine_readiness import check_clean_machine_readiness
    from run_electron_portable_workspace import DEFAULT_OUTPUT, summarize_electron_portable_workspace
    from smoke_electron_cdp import smoke_electron_cdp


SmokeRunner = Callable[..., dict[str, Any]]
CleanRunner = Callable[..., dict[str, Any]]


def _load_evidence(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _failure(path: Path, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "evidence": str(path),
        "violations": [{"path": str(path), "reason": reason}],
    }


def _section_violations(section_name: str, section: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(section, dict):
        return []
    return [
        {
            "path": str(item.get("path", "")),
            "reason": f"{section_name}: {item.get('reason', '')}",
        }
        for item in section.get("violations", [])
        if isinstance(item, dict)
    ]


def _resolve_packaged_root(payload: dict[str, Any], package_root: str | Path | None) -> Path | None:
    raw = package_root or payload.get("packaged_root") or payload.get("portable_release_root")
    if not raw:
        return None
    return Path(raw).resolve()


def _write_payload(payload: dict[str, Any], output: str | Path | None) -> None:
    if not output:
        return
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload["output"] = str(output_path.resolve())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_portable_workspace_cdp_evidence(
    *,
    evidence_path: str | Path = DEFAULT_OUTPUT,
    output: str | Path | None = None,
    package_root: str | Path | None = None,
    timeout: float = 180.0,
    debug_port: int = 9336,
    backend_port: int = 7243,
    user_data: str | Path | None = None,
    skip_download: bool = False,
    skip_restart: bool = False,
    defender_scan: bool = False,
    require_defender_scan: bool = False,
    require_bundled_python: bool | None = None,
    smoke_runner: SmokeRunner | None = None,
    clean_runner: CleanRunner | None = None,
) -> dict[str, Any]:
    """Run runtime checks against an existing portable build and update evidence.

    This is intentionally an evidence augmentation path, not a build path. It
    lets the final-goal audit consume a real packaged CDP smoke result without
    forcing a full Electron rebuild when a previous portable build already
    exists.
    """

    evidence = Path(evidence_path)
    payload = _load_evidence(evidence)
    if payload is None:
        return _failure(evidence, "portable workspace evidence is missing or invalid JSON")

    packaged_root = _resolve_packaged_root(payload, package_root)
    if packaged_root is None:
        return _failure(evidence, "packaged_root is missing from portable workspace evidence")
    if not packaged_root.is_dir():
        return _failure(packaged_root, "packaged_root is not a directory")

    try:
        smoke = (smoke_runner or smoke_electron_cdp)(
            mode="packaged",
            package_root=packaged_root,
            timeout=timeout,
            debug_port=debug_port,
            backend_port=backend_port,
            user_data=user_data,
            skip_download=skip_download,
            skip_restart=skip_restart,
        )
    except Exception as exc:
        smoke = {
            "ok": False,
            "violations": [{
                "path": "electron_cdp",
                "reason": f"{type(exc).__name__}: {exc}",
            }],
        }

    clean_packaged: dict[str, Any] | None = None
    effective_require_bundled_python = (
        bool(payload.get("require_bundled_python"))
        if require_bundled_python is None
        else bool(require_bundled_python)
    )
    if defender_scan or require_defender_scan:
        try:
            clean_packaged = (clean_runner or check_clean_machine_readiness)(
                packaged_root,
                kind="packaged-electron",
                require_bundled_python=effective_require_bundled_python,
                skip_backend_smoke=True,
                defender_scan=defender_scan,
                require_defender_scan=require_defender_scan,
            )
        except Exception as exc:
            clean_packaged = {
                "ok": False,
                "violations": [{
                    "path": "clean_packaged",
                    "reason": f"{type(exc).__name__}: {exc}",
                }],
            }

    sections = payload.get("sections")
    if not isinstance(sections, dict):
        sections = {}
        payload["sections"] = sections
    sections["electron_cdp_smoke"] = smoke
    if clean_packaged is not None:
        sections["clean_packaged"] = clean_packaged

    violations = [
        item
        for item in payload.get("blocking_violations", [])
        if isinstance(item, dict) and not str(item.get("reason", "")).startswith(("electron-cdp:", "clean-packaged:"))
    ]
    violations.extend(_section_violations("electron-cdp", smoke))
    if clean_packaged is not None:
        violations.extend(_section_violations("clean-packaged", clean_packaged))

    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["cdp_evidence_updated_at"] = payload["generated_at"]
    payload["packaged_root"] = str(packaged_root)
    payload["run_electron_cdp"] = True
    payload["electron_timeout"] = float(timeout)
    if defender_scan or require_defender_scan:
        payload["defender_scan"] = bool(defender_scan or require_defender_scan)
        payload["require_defender_scan"] = bool(require_defender_scan)
    payload["violations"] = violations
    payload["blocking_violations"] = violations
    payload["ok"] = not violations

    _write_payload(payload, output if output is not None else evidence)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update portable workspace evidence with packaged Electron CDP smoke.")
    parser.add_argument("--evidence", default=str(DEFAULT_OUTPUT), help="Portable workspace evidence JSON to update.")
    parser.add_argument("--output", default=None, help="Optional output path. Defaults to updating --evidence in place.")
    parser.add_argument("--package-root", default=None, help="Existing NAIA-Portable package root. Defaults to evidence packaged_root.")
    parser.add_argument("--debug-port", type=int, default=9336)
    parser.add_argument("--backend-port", type=int, default=7243)
    parser.add_argument("--electron-timeout", "--timeout", dest="timeout", type=float, default=180.0)
    parser.add_argument("--user-data", default=None)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-restart", action="store_true")
    parser.add_argument("--defender-scan", action="store_true", help="Refresh clean-machine evidence with Defender scan.")
    parser.add_argument("--require-defender-scan", action="store_true", help="Fail unless Defender scan succeeds.")
    parser.add_argument("--require-bundled-python", action="store_true", help="Require packaged resources/python in refreshed clean-machine evidence.")
    parser.add_argument("--summary", action="store_true", help="Print compact portable evidence summary.")
    args = parser.parse_args(argv)

    payload = update_portable_workspace_cdp_evidence(
        evidence_path=args.evidence,
        output=args.output,
        package_root=args.package_root,
        timeout=args.timeout,
        debug_port=args.debug_port,
        backend_port=args.backend_port,
        user_data=args.user_data,
        skip_download=args.skip_download,
        skip_restart=args.skip_restart,
        defender_scan=args.defender_scan,
        require_defender_scan=args.require_defender_scan,
        require_bundled_python=True if args.require_bundled_python else None,
    )
    if args.summary and payload.get("sections"):
        payload = summarize_electron_portable_workspace(payload)
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
