"""Validate runtime write/download ownership rules for the headless release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_POLICY = Path("release_assets/manifests/runtime_write_policy.json")
DEFAULT_RUNTIME_POLICY = Path("release_assets/manifests/runtime_asset_policy.json")


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_runtime_write_policy(
    policy_path: str | Path = DEFAULT_POLICY,
    *,
    runtime_policy_path: str | Path = DEFAULT_RUNTIME_POLICY,
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(repo_root)
    policy_file = Path(policy_path)
    policy = load_json(policy_file)
    runtime_policy = load_json(runtime_policy_path)
    violations: list[dict[str, Any]] = []

    blocked_targets = runtime_policy.get("blocked_future_download_targets", [])
    for required in ("data/**", "ui/**", "./*"):
        if required not in blocked_targets:
            violations.append(
                {
                    "path": str(runtime_policy_path),
                    "reason": f"runtime asset policy missing blocked target: {required}",
                }
            )

    owners = policy.get("required_runtime_download_owners", [])
    for owner in owners:
        feature = str(owner.get("feature") or "<missing>")
        source = str(owner.get("source") or "")
        source_path = root / source
        if not source or not source_path.is_file():
            violations.append(
                {
                    "feature": feature,
                    "path": source,
                    "reason": "source file does not exist",
                }
            )
            continue
        text = source_path.read_text(encoding="utf-8")
        for snippet in owner.get("must_contain", []):
            if str(snippet) not in text:
                violations.append(
                    {
                        "feature": feature,
                        "path": source,
                        "reason": "required runtime-path snippet missing",
                        "snippet": str(snippet),
                    }
                )
        for snippet in owner.get("must_not_contain", []):
            if str(snippet) in text:
                violations.append(
                    {
                        "feature": feature,
                        "path": source,
                        "reason": "blocked source-checkout write snippet present",
                        "snippet": str(snippet),
                    }
                )

    scan = policy.get("download_api_scan", {})
    patterns = [str(pattern) for pattern in scan.get("patterns", []) if str(pattern)]
    source_roots = [str(path) for path in scan.get("source_roots", []) if str(path)]
    ignored_sources = {str(path).replace("\\", "/") for path in scan.get("ignored_sources", [])}
    ignored_roots = {
        str(path).replace("\\", "/").strip("/")
        for path in scan.get("ignored_roots", [])
        if str(path).strip()
    }
    owner_sources = {str(owner.get("source") or "").replace("\\", "/") for owner in owners}
    discovered_download_sources: set[str] = set()
    if patterns and source_roots:
        compiled = [re.compile(re.escape(pattern)) for pattern in patterns]
        for source_root in source_roots:
            root_path = root / source_root
            if not root_path.exists():
                continue
            for path in root_path.rglob("*.py"):
                relative = path.relative_to(root).as_posix()
                if relative in ignored_sources:
                    continue
                if any(relative == ignored or relative.startswith(f"{ignored}/") for ignored in ignored_roots):
                    continue
                text = path.read_text(encoding="utf-8")
                if any(pattern.search(text) for pattern in compiled):
                    discovered_download_sources.add(relative)
        for relative in sorted(discovered_download_sources - owner_sources):
            violations.append(
                {
                    "path": relative,
                    "reason": "download API source is not registered in runtime write policy owners",
                }
            )

    return {
        "ok": not violations,
        "policy": str(policy_file),
        "runtime_policy": str(runtime_policy_path),
        "owner_count": len(owners),
        "download_api_sources": sorted(discovered_download_sources),
        "violations": violations,
        "exceptions": policy.get("known_compatibility_exceptions", []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate NAIA runtime write/download policy.")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY), help="Runtime write policy JSON path.")
    parser.add_argument("--runtime-policy", default=str(DEFAULT_RUNTIME_POLICY), help="Runtime asset policy JSON path.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    args = parser.parse_args(argv)

    payload = check_runtime_write_policy(
        args.policy,
        runtime_policy_path=args.runtime_policy,
        repo_root=args.repo_root,
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
