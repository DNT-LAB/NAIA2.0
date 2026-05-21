"""Write release file metadata and SHA-256 checksums for a staged NAIA release."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


CHECKSUMS_NAME = "CHECKSUMS.sha256"
MANIFEST_NAME = "RELEASE_MANIFEST.json"
EXCLUDED_METADATA_FILES = {CHECKSUMS_NAME, MANIFEST_NAME}


@dataclass(frozen=True)
class ReleaseFileRecord:
    path: str
    size: int
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _python_runtime_path(release_root: Path) -> Path | None:
    candidates = (
        release_root / "resources" / "python" / "python.exe",
        release_root / "resources" / "python" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _iter_release_files(release_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in release_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(release_root)
        if relative.as_posix() in EXCLUDED_METADATA_FILES:
            continue
        files.append(relative)
    return sorted(files, key=lambda item: item.as_posix())


def build_release_metadata(release_root: str | Path) -> dict:
    root = Path(release_root).resolve()
    backend_root = root / "resources" / "naia-backend"
    python_runtime = _python_runtime_path(root)
    records = [
        ReleaseFileRecord(
            path=relative.as_posix(),
            size=(root / relative).stat().st_size,
            sha256=_sha256(root / relative),
        )
        for relative in _iter_release_files(root)
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "release_root": str(root),
        "file_count": len(records),
        "total_size_bytes": sum(record.size for record in records),
        "runtime": {
            "backend_root": str(backend_root),
            "backend_entry": str(backend_root / "NAIA_web_headless.py"),
            "backend_entry_exists": (backend_root / "NAIA_web_headless.py").is_file(),
            "bundled_python": str(python_runtime) if python_runtime else "",
            "bundled_python_exists": python_runtime is not None,
            "user_data_root": str(root / "user-data"),
            "portable_user_data_exists": (root / "user-data").is_dir(),
        },
        "external_dependencies": [
            "NovelAI account/token for NovelAI generation",
            "WebUI endpoint for WEBUI generation",
            "ComfyUI endpoint for COMFYUI generation",
            "Optional downloadable tag, preset, thumbnail, and model-support data",
        ],
        "files": [record.__dict__ for record in records],
    }


def write_release_metadata(release_root: str | Path) -> dict:
    root = Path(release_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    payload = build_release_metadata(root)
    (root / MANIFEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    checksum_lines = [
        f"{record['sha256']}  {record['path']}"
        for record in payload["files"]
    ]
    (root / CHECKSUMS_NAME).write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write RELEASE_MANIFEST.json and CHECKSUMS.sha256.")
    parser.add_argument("release_root", help="Staged NAIA release directory.")
    args = parser.parse_args(argv)

    payload = write_release_metadata(args.release_root)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
