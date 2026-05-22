"""Validate the Remote Web feature contract against the headless app source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_CONTRACT = Path("release_assets/manifests/remote_web_feature_contract.json")
DEFAULT_ROUTE_SOURCE = Path("core/web_session_app.py")

ROUTE_DECORATOR_RE = re.compile(
    r"^\s*@app\.(get|post|put|patch|delete|websocket)\(\s*[\"']([^\"']+)[\"']",
    re.MULTILINE,
)
ALLOWED_LEGACY_DEPENDENCIES = {"none", "legacy_compat", "external", "needs_live_smoke"}
ALLOWED_SMOKE_LEVELS = {"static", "non_destructive", "state_mutation", "asset_runtime", "external_live"}


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def scan_app_routes(source_path: str | Path = DEFAULT_ROUTE_SOURCE) -> set[tuple[str, str]]:
    source = Path(source_path).read_text(encoding="utf-8")
    routes: set[tuple[str, str]] = set()
    for method, route_path in ROUTE_DECORATOR_RE.findall(source):
        normalized_method = "WEBSOCKET" if method == "websocket" else method.upper()
        routes.add((normalized_method, route_path))
    return routes


def scan_route_sources(source_paths: list[str | Path]) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for source_path in source_paths:
        routes.update(scan_app_routes(source_path))
    return routes


def _contract_routes(contract: dict[str, Any]) -> tuple[set[tuple[str, str]], list[dict[str, Any]]]:
    routes: set[tuple[str, str]] = set()
    duplicates: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], str] = {}
    for feature in contract.get("feature_groups", []):
        feature_id = str(feature.get("id") or "<missing>")
        for route in feature.get("routes", []):
            method = str(route.get("method") or "").upper()
            route_path = str(route.get("path") or "")
            key = (method, route_path)
            if key in seen:
                duplicates.append(
                    {
                        "method": method,
                        "path": route_path,
                        "first_feature": seen[key],
                        "duplicate_feature": feature_id,
                    }
                )
            seen[key] = feature_id
            routes.add(key)
    return routes, duplicates


def validate_remote_web_feature_contract(
    contract_path: str | Path = DEFAULT_CONTRACT,
    *,
    repo_root: str | Path = ".",
    route_source: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    contract_file = Path(contract_path)
    contract = load_contract(contract_file)
    if route_source is not None:
        route_sources = [Path(route_source)]
    else:
        configured_sources = contract.get("route_sources")
        if isinstance(configured_sources, list) and configured_sources:
            route_sources = [Path(str(source)) for source in configured_sources]
        else:
            route_sources = [Path(contract.get("route_source") or DEFAULT_ROUTE_SOURCE)]
    route_sources = [
        source if source.is_absolute() else root / source
        for source in route_sources
    ]

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not isinstance(contract.get("feature_groups"), list) or not contract["feature_groups"]:
        violations.append({"path": str(contract_file), "reason": "feature_groups must be a non-empty list"})

    for feature in contract.get("feature_groups", []):
        feature_id = str(feature.get("id") or "<missing>")
        dependency = str(feature.get("legacy_dependency") or "")
        if dependency not in ALLOWED_LEGACY_DEPENDENCIES:
            violations.append(
                {
                    "feature": feature_id,
                    "reason": f"invalid legacy_dependency: {dependency}",
                }
            )
        if not feature.get("routes"):
            violations.append({"feature": feature_id, "reason": "feature has no routes"})
        for source_file in feature.get("source_files", []):
            path = root / str(source_file)
            if not path.exists():
                violations.append(
                    {
                        "feature": feature_id,
                        "path": str(source_file),
                        "reason": "source file does not exist",
                    }
                )
        for route in feature.get("routes", []):
            smoke = str(route.get("smoke") or "")
            if smoke not in ALLOWED_SMOKE_LEVELS:
                violations.append(
                    {
                        "feature": feature_id,
                        "route": f"{route.get('method')} {route.get('path')}",
                        "reason": f"invalid smoke level: {smoke}",
                    }
                )

    for mount in contract.get("static_mounts", []):
        source = mount.get("source")
        if source and not (root / str(source)).exists():
            violations.append(
                {
                    "path": str(source),
                    "reason": "static mount source does not exist",
                }
            )
        compatibility_source = mount.get("compatibility_source")
        if compatibility_source and not (root / str(compatibility_source)).exists():
            warnings.append(
                {
                    "path": str(compatibility_source),
                    "reason": "static mount compatibility source does not exist",
                }
            )

    source_routes = scan_route_sources(route_sources)
    contract_routes, duplicates = _contract_routes(contract)
    for duplicate in duplicates:
        violations.append({"reason": "duplicate route in contract", **duplicate})

    missing_from_source = sorted(contract_routes - source_routes)
    undocumented_in_contract = sorted(source_routes - contract_routes)
    for method, route_path in missing_from_source:
        violations.append(
            {
                "method": method,
                "path": route_path,
                "reason": "contract route is not present in source route decorators",
            }
        )
    for method, route_path in undocumented_in_contract:
        violations.append(
            {
                "method": method,
                "path": route_path,
                "reason": "source route is not documented in contract",
            }
        )

    return {
        "ok": not violations,
        "contract": str(contract_file),
        "route_source": str(route_sources[0]),
        "route_sources": [str(source) for source in route_sources],
        "feature_count": len(contract.get("feature_groups", [])),
        "contract_route_count": len(contract_routes),
        "source_route_count": len(source_routes),
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Remote Web feature contract coverage.")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), help="Remote Web feature contract JSON path.")
    parser.add_argument("--repo-root", default=".", help="Repository root for source file checks.")
    parser.add_argument("--route-source", default=None, help="Override route source file.")
    args = parser.parse_args(argv)

    payload = validate_remote_web_feature_contract(
        args.contract,
        repo_root=args.repo_root,
        route_source=args.route_source,
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
