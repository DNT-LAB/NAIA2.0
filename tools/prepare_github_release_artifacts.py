"""Prepare GitHub Release assets from the validated NAIA portable build."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile
from typing import Any


DEFAULT_FINAL_GATE = Path("app/electron/dist/final_electron_release_gate.json")
DEFAULT_WORKSPACE_EVIDENCE = Path("app/electron/dist/electron_workspace_release_evidence.json")
DEFAULT_PACKAGE_ROOT = Path("app/electron/dist/win-unpacked")
DEFAULT_OUTPUT_DIR = Path("app/electron/dist/github-release")
PORTABLE_ZIP_NAME = "NAIA-Portable.zip"
SHA256SUMS_NAME = "SHA256SUMS.txt"
RELEASE_SUMMARY_NAME = "RELEASE_EVIDENCE_SUMMARY.json"
RELEASE_BODY_NAME = "GITHUB_RELEASE_BODY.md"
FALSE_POSITIVE_NAME = "DEFENDER_FALSE_POSITIVE.md"
FINAL_GATE_COPY_NAME = "final_electron_release_gate.json"
WORKSPACE_EVIDENCE_COPY_NAME = "electron_workspace_release_evidence.json"
MICROSOFT_FILE_SUBMISSION_URL = "https://www.microsoft.com/en-us/wdsi/filesubmission"


@dataclass(frozen=True)
class AssetRecord:
    name: str
    size: int
    sha256: str


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolved_package_root(final_gate: dict[str, Any], package_root: str | Path | None) -> Path:
    if package_root:
        return Path(package_root).resolve()
    portable = final_gate.get("sections", {}).get("portable_workspace", {})
    evidence_root = portable.get("packaged_root") if isinstance(portable, dict) else ""
    if evidence_root and Path(str(evidence_root)).is_dir():
        return Path(str(evidence_root)).resolve()
    return DEFAULT_PACKAGE_ROOT.resolve()


def _validate_final_gate(final_gate: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []

    def require(condition: bool, path: str, reason: str) -> None:
        if not condition:
            violations.append({"path": path, "reason": reason})

    require(final_gate.get("ok") is True, "final_gate.ok", "final release gate must pass")
    require(final_gate.get("release_ready") is True, "final_gate.release_ready", "final release gate must be release-ready")
    require(final_gate.get("execute") is True, "final_gate.execute", "final release gate must be a real execution")
    require(final_gate.get("run_electron_cdp") is True, "final_gate.run_electron_cdp", "Electron CDP smoke must run")
    require(final_gate.get("defender_scan") is True, "final_gate.defender_scan", "Defender scan must run")
    require(
        final_gate.get("require_defender_scan") is True,
        "final_gate.require_defender_scan",
        "Defender scan must be release-blocking",
    )
    require(
        final_gate.get("require_bundled_python") is True,
        "final_gate.require_bundled_python",
        "bundled Python must be required",
    )
    require(not final_gate.get("failed_sections"), "final_gate.failed_sections", "final gate has failed sections")
    require(not final_gate.get("violations"), "final_gate.violations", "final gate has violations")

    goal = final_gate.get("completion_blockers", {}).get("goal_audit", {})
    require(goal.get("ok") is True, "completion_blockers.goal_audit", "goal audit must pass")
    require(int(goal.get("blocker_count") or 0) == 0, "completion_blockers.goal_audit.blocker_count", "goal blockers remain")

    portable = final_gate.get("sections", {}).get("portable_workspace", {})
    sections = portable.get("sections", {}) if isinstance(portable, dict) else {}
    for section_name in ("electron_builder", "packaged_smoke", "clean_packaged", "electron_cdp_smoke"):
        section = sections.get(section_name, {}) if isinstance(sections, dict) else {}
        require(section.get("ok") is True, f"portable_workspace.sections.{section_name}", f"{section_name} must pass")

    clean = sections.get("clean_packaged", {}) if isinstance(sections, dict) else {}
    scanner = clean.get("checks", {}).get("measurement", {}).get("scanner", {}) if isinstance(clean, dict) else {}
    require(scanner.get("ok") is True, "clean_packaged.measurement.scanner", "Defender scanner evidence must pass")
    return violations


def _validate_package_root(package_root: Path) -> list[dict[str, str]]:
    required = [
        "NAIA.exe",
        "README_RELEASE.txt",
        "RELEASE_MANIFEST.json",
        "CHECKSUMS.sha256",
        "resources/naia-backend",
        "resources/python",
        "user-data",
    ]
    violations = []
    if not package_root.is_dir():
        return [{"path": str(package_root), "reason": "package root is not a directory"}]
    for relative in required:
        if not (package_root / relative).exists():
            violations.append({"path": str(package_root / relative), "reason": "required packaged release path is missing"})
    return violations


def _assert_writable_targets(output_dir: Path, targets: list[str], *, force: bool) -> None:
    existing = [str(output_dir / name) for name in targets if (output_dir / name).exists()]
    if existing and not force:
        joined = "\n".join(f"- {item}" for item in existing)
        raise FileExistsError(f"release artifact target already exists; pass --force to overwrite:\n{joined}")


def _write_zip(package_root: Path, output_zip: Path) -> None:
    root_name = Path("NAIA-Portable")
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(str(root_name).replace("\\", "/") + "/", b"")
        for path in sorted(package_root.rglob("*"), key=lambda item: item.relative_to(package_root).as_posix()):
            relative = path.relative_to(package_root)
            archive_name = (root_name / relative).as_posix()
            if path.is_dir():
                archive.writestr(archive_name.rstrip("/") + "/", b"")
            elif path.is_file():
                archive.write(path, archive_name)


def _record(path: Path) -> AssetRecord:
    return AssetRecord(name=path.name, size=path.stat().st_size, sha256=_sha256(path))


def _defender_from_gate(final_gate: dict[str, Any]) -> dict[str, Any]:
    clean = (
        final_gate.get("sections", {})
        .get("portable_workspace", {})
        .get("sections", {})
        .get("clean_packaged", {})
    )
    measurement = clean.get("checks", {}).get("measurement", {}) if isinstance(clean, dict) else {}
    scanner = measurement.get("scanner", {}) if isinstance(measurement, dict) else {}
    return {
        "required": bool(final_gate.get("require_defender_scan")),
        "requested": bool(final_gate.get("defender_scan")),
        "ok": scanner.get("ok"),
        "available": scanner.get("available"),
        "scanner": scanner.get("scanner"),
        "exit_code": scanner.get("exit_code"),
    }


def _build_summary(
    *,
    package_root: Path,
    final_gate_path: Path,
    workspace_evidence_path: Path,
    final_gate: dict[str, Any],
    workspace_evidence: dict[str, Any] | None,
    assets: list[AssetRecord],
) -> dict[str, Any]:
    portable = final_gate.get("sections", {}).get("portable_workspace", {})
    portable_sections = portable.get("sections", {}) if isinstance(portable, dict) else {}
    clean = portable_sections.get("clean_packaged", {}) if isinstance(portable_sections, dict) else {}
    cdp = portable_sections.get("electron_cdp_smoke", {}) if isinstance(portable_sections, dict) else {}
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "distribution_channel": "github-release",
        "package_root": str(package_root),
        "signing": {
            "status": "unsigned-portable-beta",
            "smartscreen_warning_accepted": True,
            "code_signing_status": "deferred",
            "reason": "Public beta accepts SmartScreen friction; release-blocking gate is Defender scan evidence plus immutable checksums.",
        },
        "false_positive_response": {
            "portal": MICROSOFT_FILE_SUBMISSION_URL,
            "submit_as": "Software developer",
            "include_assets": [
                PORTABLE_ZIP_NAME,
                SHA256SUMS_NAME,
                RELEASE_SUMMARY_NAME,
                FINAL_GATE_COPY_NAME,
            ],
        },
        "final_gate": {
            "path": str(final_gate_path),
            "ok": bool(final_gate.get("ok")),
            "release_ready": bool(final_gate.get("release_ready")),
            "require_bundled_python": bool(final_gate.get("require_bundled_python")),
            "build_clean_python_runtime": bool(final_gate.get("build_clean_python_runtime")),
            "python_runtime_version": str(final_gate.get("python_runtime_version") or ""),
            "failed_sections": list(final_gate.get("failed_sections") or []),
            "violations": list(final_gate.get("violations") or []),
        },
        "portable_workspace": {
            "ok": bool(portable.get("ok")) if isinstance(portable, dict) else False,
            "packaged_root": str(portable.get("packaged_root") or "") if isinstance(portable, dict) else "",
            "clean_packaged_ok": bool(clean.get("ok")) if isinstance(clean, dict) else False,
            "electron_cdp_smoke_ok": bool(cdp.get("ok")) if isinstance(cdp, dict) else False,
            "backend_state": str(cdp.get("state", {}).get("backendState") or "") if isinstance(cdp, dict) else "",
        },
        "defender": _defender_from_gate(final_gate),
        "workspace_evidence": {
            "path": str(workspace_evidence_path),
            "ok": bool(workspace_evidence.get("ok")) if isinstance(workspace_evidence, dict) else None,
            "ready_to_build": bool(workspace_evidence.get("ready_to_build")) if isinstance(workspace_evidence, dict) else None,
            "failed_sections": list(workspace_evidence.get("failed_sections") or []) if isinstance(workspace_evidence, dict) else [],
        },
        "assets": [record.__dict__ for record in assets],
    }


def _write_false_positive_note(summary: dict[str, Any], path: Path) -> None:
    zip_asset = next((item for item in summary["assets"] if item["name"] == PORTABLE_ZIP_NAME), {})
    defender_ok = bool(summary.get("defender", {}).get("ok"))
    if defender_ok:
        scan_sentence = (
            f"This release is unsigned, but it passed the local Microsoft Defender scan recorded in "
            f"`{RELEASE_SUMMARY_NAME}` and `{FINAL_GATE_COPY_NAME}`."
        )
    else:
        scan_sentence = (
            f"This release is unsigned. The recorded Microsoft Defender scan status is in "
            f"`{RELEASE_SUMMARY_NAME}` and `{FINAL_GATE_COPY_NAME}`."
        )
    text = f"""# Microsoft Defender false-positive response

Use this note only when Microsoft Defender flags the release artifact.

Submission portal:
{MICROSOFT_FILE_SUBMISSION_URL}

Submit as:
Software developer

Primary file:
{PORTABLE_ZIP_NAME}

SHA-256:
{zip_asset.get("sha256", "")}

Suggested context:
NAIA is a portable Electron shell for the NAIA headless Remote Web backend. {scan_sentence} The artifact is distributed through GitHub Releases with immutable SHA-256 checksums in `{SHA256SUMS_NAME}`. Please review this detection as a false positive if Defender classifies the archive or bundled executable as malware.

Attach or reference:
- {PORTABLE_ZIP_NAME}
- {SHA256SUMS_NAME}
- {RELEASE_SUMMARY_NAME}
- {FINAL_GATE_COPY_NAME}
- {WORKSPACE_EVIDENCE_COPY_NAME}
"""
    path.write_text(text, encoding="utf-8")


def _write_release_body(summary: dict[str, Any], path: Path) -> None:
    zip_asset = next((item for item in summary["assets"] if item["name"] == PORTABLE_ZIP_NAME), {})
    total_mib = round(int(zip_asset.get("size") or 0) / (1024 * 1024), 2)
    gate = summary.get("final_gate", {})
    defender = summary.get("defender", {})
    portable = summary.get("portable_workspace", {})
    release_ready = str(bool(gate.get("release_ready"))).lower()
    bundled_python = "required" if gate.get("require_bundled_python") else "not required"
    clean_python = "required" if gate.get("build_clean_python_runtime") else "not required"
    defender_required = bool(defender.get("required"))
    defender_ok = bool(defender.get("ok"))
    if defender_ok:
        defender_line = "required and passed" if defender_required else "passed"
    else:
        defender_line = "required but NOT passed" if defender_required else "not run"
    cdp_line = "passed" if portable.get("electron_cdp_smoke_ok") else "not passed"
    backend_state = str(portable.get("backend_state") or "unknown")
    defender_notice = (
        "The release artifact itself was scanned locally by Microsoft Defender, and immutable checksums are included for verification."
        if defender_ok
        else "Immutable checksums are included for verification."
    )
    text = f"""# NAIA Portable Release

## Download

- `{PORTABLE_ZIP_NAME}`
- `{SHA256SUMS_NAME}`

## Verification

```powershell
Get-FileHash .\\{PORTABLE_ZIP_NAME} -Algorithm SHA256
Get-Content .\\{SHA256SUMS_NAME}
```

Expected SHA-256 for `{PORTABLE_ZIP_NAME}`:

```text
{zip_asset.get("sha256", "")}
```

## Release Gate

- Final gate: `release_ready={release_ready}`
- Bundled Python: {bundled_python}
- Clean Python runtime build: {clean_python}
- Defender scan: {defender_line}
- Electron CDP smoke: {cdp_line}
- Packaged backend state: {backend_state}

## Windows Notice

This portable beta is unsigned. Microsoft Defender SmartScreen may show an unrecognized-app warning on first run. {defender_notice}

## Artifact

- Size: {total_mib} MiB
- Channel: GitHub Release portable zip
"""
    path.write_text(text, encoding="utf-8")


def prepare_github_release_artifacts(
    *,
    package_root: str | Path | None = None,
    final_gate_path: str | Path = DEFAULT_FINAL_GATE,
    workspace_evidence_path: str | Path = DEFAULT_WORKSPACE_EVIDENCE,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    require_final_gate: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    final_gate_file = Path(final_gate_path).resolve()
    workspace_evidence_file = Path(workspace_evidence_path).resolve()
    if not final_gate_file.is_file():
        raise FileNotFoundError(f"final gate evidence is missing: {final_gate_file}")
    final_gate = _load_json(final_gate_file)
    workspace_evidence = _load_json(workspace_evidence_file) if workspace_evidence_file.is_file() else None
    root = _resolved_package_root(final_gate, package_root)
    out = Path(output_dir).resolve()

    if _is_relative_to(out, root):
        raise ValueError("output directory must not be inside the package root")

    violations = _validate_package_root(root)
    if require_final_gate:
        violations.extend(_validate_final_gate(final_gate))
    if violations:
        return {
            "ok": False,
            "output_dir": str(out),
            "package_root": str(root),
            "violations": violations,
        }

    targets = [
        PORTABLE_ZIP_NAME,
        SHA256SUMS_NAME,
        RELEASE_SUMMARY_NAME,
        RELEASE_BODY_NAME,
        FALSE_POSITIVE_NAME,
        FINAL_GATE_COPY_NAME,
        WORKSPACE_EVIDENCE_COPY_NAME,
    ]
    out.mkdir(parents=True, exist_ok=True)
    _assert_writable_targets(out, targets, force=force)

    zip_path = out / PORTABLE_ZIP_NAME
    _write_zip(root, zip_path)
    shutil.copy2(final_gate_file, out / FINAL_GATE_COPY_NAME)
    if workspace_evidence_file.is_file():
        shutil.copy2(workspace_evidence_file, out / WORKSPACE_EVIDENCE_COPY_NAME)

    release_assets = [
        _record(zip_path),
        _record(out / FINAL_GATE_COPY_NAME),
    ]
    if (out / WORKSPACE_EVIDENCE_COPY_NAME).is_file():
        release_assets.append(_record(out / WORKSPACE_EVIDENCE_COPY_NAME))

    summary = _build_summary(
        package_root=root,
        final_gate_path=final_gate_file,
        workspace_evidence_path=workspace_evidence_file,
        final_gate=final_gate,
        workspace_evidence=workspace_evidence,
        assets=release_assets,
    )
    summary_path = out / RELEASE_SUMMARY_NAME
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_false_positive_note(summary, out / FALSE_POSITIVE_NAME)
    _write_release_body(summary, out / RELEASE_BODY_NAME)

    release_assets = [
        _record(zip_path),
        _record(out / RELEASE_BODY_NAME),
        _record(out / FALSE_POSITIVE_NAME),
        _record(out / FINAL_GATE_COPY_NAME),
    ]
    if (out / WORKSPACE_EVIDENCE_COPY_NAME).is_file():
        release_assets.append(_record(out / WORKSPACE_EVIDENCE_COPY_NAME))

    summary = _build_summary(
        package_root=root,
        final_gate_path=final_gate_file,
        workspace_evidence_path=workspace_evidence_file,
        final_gate=final_gate,
        workspace_evidence=workspace_evidence,
        assets=release_assets,
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Public release upload set = portable zip + SHA256SUMS.txt only (handoff policy).
    # Evidence files (release summary, final gate, workspace evidence, false-positive note,
    # release body) are still generated locally for records and false-positive submission,
    # but are NOT advertised as release downloads nor listed in the public checksum manifest.
    checksum_assets = [_record(zip_path)]
    checksum_lines = [f"{record.sha256}  {record.name}" for record in sorted(checksum_assets, key=lambda item: item.name)]
    (out / SHA256SUMS_NAME).write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    all_assets = [*release_assets, _record(summary_path), _record(out / SHA256SUMS_NAME)]

    return {
        "ok": True,
        "output_dir": str(out),
        "package_root": str(root),
        "asset_count": len(all_assets),
        "assets": [record.__dict__ for record in sorted(all_assets, key=lambda item: item.name)],
        "violations": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare NAIA GitHub Release assets from final release evidence.")
    parser.add_argument("--package-root", default=None, help="Packaged portable root. Defaults to final-gate packaged_root.")
    parser.add_argument("--final-gate", default=str(DEFAULT_FINAL_GATE), help="Final release gate JSON.")
    parser.add_argument("--workspace-evidence", default=str(DEFAULT_WORKSPACE_EVIDENCE), help="Portable workspace evidence JSON.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for GitHub Release assets.")
    parser.add_argument("--require-final-gate", action="store_true", help="Fail unless final release gate is release-ready.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing generated release asset files.")
    args = parser.parse_args(argv)

    try:
        payload = prepare_github_release_artifacts(
            package_root=args.package_root,
            final_gate_path=args.final_gate,
            workspace_evidence_path=args.workspace_evidence,
            output_dir=args.output_dir,
            require_final_gate=args.require_final_gate,
            force=args.force,
        )
    except Exception as exc:
        payload = {"ok": False, "violations": [{"path": "prepare_github_release_artifacts", "reason": str(exc)}]}
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
