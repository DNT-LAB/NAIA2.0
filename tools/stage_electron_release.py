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


# 사용자가 Codex · Claude 같은 AI 에이전트에게 NAIA 를 맡길 때 에이전트가 읽는 안내(2026-11-06 사용자 지시).
# 에이전트가 읽으므로 영어로 쓴다. 상세는 `NAIA_cli.py --help` 와 `capabilities` 가 스스로 알려 준다.
AGENT_CLI_README = [
    "Using NAIA from an AI agent (Codex, Claude, other CLI agents)",
    "",
    "NAIA ships a command-line tool for agents. Run it with the bundled Python, from this folder:",
    "  resources\\python\\python.exe resources\\naia-backend\\NAIA_cli.py --help",
    "Every command prints one JSON object on stdout ({\"ok\": ..., \"result\" or \"error\": ...}).",
    "",
    "1. NAIA window open (recommended): talk to the running app and its current settings.",
    "     NAIA_cli.py capabilities overview --server http://127.0.0.1:7243",
    "     NAIA_cli.py capabilities search \"character reference\" --server http://127.0.0.1:7243",
    "     NAIA_cli.py capabilities describe <id> --server http://127.0.0.1:7243",
    "     NAIA_cli.py call <id> --server http://127.0.0.1:7243 --input @request.json",
    "   http://127.0.0.1:7243 is the default address; use the address the NAIA window shows if it differs.",
    "2. NAIA closed: add --user-data with this folder's user-data, or the CLI reads %APPDATA%\\NAIA instead.",
    "     NAIA_cli.py --user-data \"<this folder>\\user-data\" presets",
    "     NAIA_cli.py --user-data \"<this folder>\\user-data\" generate --prompt \"...\" --output out.png --dry-run",
    "     NAIA_cli.py --user-data \"<this folder>\\user-data\" capabilities overview --standalone",
    "",
    "Rules for agents:",
    "- Use the user's current preset. Do not pass --preset/--model/size/steps unless the user asks for them.",
    "- Run generate with --dry-run first: it shows the preset, final parameters and the Anlas cost.",
    "  Ask the user before any generation that costs Anlas.",
    "- dispatch_complete means the command was accepted, not that an image is finished. Never blindly retry",
    "  a generation after a timeout; check the result first.",
    "- set_prompt changes only the fields you send (prompt and/or negative_prompt).",
    "- Never print or paste tokens. auth reports only whether a provider is configured.",
    "- NAIA does not filter content. The calling agent's own policy applies.",
    "",
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
                *AGENT_CLI_README,
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
