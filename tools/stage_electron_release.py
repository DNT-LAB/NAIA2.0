"""Stage an Electron release resource skeleton for NAIA.

This does not build Electron or package Python. It prepares the resource layout
that Electron can consume:

```
<target>/
  resources/
    naia-backend/
      NAIA_web_headless.py
      app/backend/...
      app/web/remote/...
      core/...
      interfaces/...
      utils/...
  user-data/
  README_RELEASE.txt
```
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil

try:
    from tools.stage_release_assets import collect_release_files
    from tools.write_release_metadata import write_release_metadata
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from stage_release_assets import collect_release_files
    from write_release_metadata import write_release_metadata


BACKEND_RESOURCE_DIR = Path("resources") / "naia-backend"


@dataclass(frozen=True)
class ElectronStageResult:
    source_root: str
    target_root: str
    backend_root: str
    files: list[str]
    copied: bool


def _is_backend_resource_file(relative: Path) -> bool:
    posix = relative.as_posix()
    return not posix.startswith("app/electron/")


def collect_electron_backend_files(source_root: str | Path) -> list[Path]:
    return [
        relative
        for relative in collect_release_files(source_root)
        if _is_backend_resource_file(relative)
    ]


def _write_release_readme(target: Path) -> None:
    (target / "README_RELEASE.txt").write_text(
        "\n".join(
            [
                "NAIA Headless Electron release skeleton",
                "",
                "This folder is staged for Electron packaging.",
                "The backend resources live under resources/naia-backend.",
                "Writable runtime data belongs in user-data for portable mode or %APPDATA%/NAIA for installed mode.",
                "",
                "External runtime dependencies:",
                "- NovelAI account/token for NovelAI generation.",
                "- WebUI endpoint for WEBUI generation.",
                "- ComfyUI endpoint for COMFYUI generation.",
                "- Optional downloadable tag, preset, thumbnail, and model-support data.",
                "",
                "Validation artifacts:",
                "- RELEASE_MANIFEST.json lists staged files, sizes, and SHA-256 hashes.",
                "- CHECKSUMS.sha256 contains release payload checksums.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def stage_electron_release(
    source_root: str | Path,
    target_root: str | Path,
    *,
    copy: bool = False,
) -> ElectronStageResult:
    source = Path(source_root).resolve()
    target = Path(target_root).resolve()
    backend_target = target / BACKEND_RESOURCE_DIR
    files = collect_electron_backend_files(source)

    if copy:
        if target.exists() and any(target.iterdir()):
            raise RuntimeError(f"Target directory is not empty: {target}")
        backend_target.mkdir(parents=True, exist_ok=True)
        (target / "user-data").mkdir(parents=True, exist_ok=True)
        _write_release_readme(target)
        for relative in files:
            source_file = source / relative
            destination = backend_target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)
        write_release_metadata(target)

    return ElectronStageResult(
        source_root=str(source),
        target_root=str(target),
        backend_root=str(backend_target),
        files=[relative.as_posix() for relative in files],
        copied=copy,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage NAIA Electron backend resources.")
    parser.add_argument("--source", default=".", help="Source checkout root.")
    parser.add_argument("--target", required=True, help="Target release skeleton directory.")
    parser.add_argument("--copy", action="store_true", help="Copy backend resources into the target skeleton.")
    args = parser.parse_args(argv)

    result = stage_electron_release(args.source, args.target, copy=args.copy)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
