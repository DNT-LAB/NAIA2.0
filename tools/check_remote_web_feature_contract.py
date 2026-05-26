"""Validate the Remote Web feature contract against the headless app source."""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_CONTRACT = Path("release_assets/manifests/remote_web_feature_contract.json")
DEFAULT_ROUTE_SOURCE = Path("core/web_session_app.py")
DEFAULT_RELEASE_MANIFEST = Path("release_assets/manifests/release_include_exclude_draft.json")

ROUTE_DECORATOR_RE = re.compile(
    r"^\s*@app\.(get|post|put|patch|delete|websocket)\(\s*[\"']([^\"']+)[\"']",
    re.MULTILINE,
)
ALLOWED_LEGACY_DEPENDENCIES = {"none", "legacy_compat", "external", "needs_live_smoke"}
ALLOWED_SMOKE_LEVELS = {"static", "non_destructive", "state_mutation", "asset_runtime", "external_live"}
# Provisioning kinds for a feature's data/ dependency on a clean machine.
#  - bundled:           shipped inside the release payload (must match a manifest include glob)
#  - downloader:        fetched at runtime via a real download route (provisioned_by must be a contract route)
#  - runtime_generated: produced by the running app/user actions (no static guarantee required)
ALLOWED_DATA_PROVISIONING = {"bundled", "downloader", "runtime_generated"}


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_manifest_includes(path: str | Path = DEFAULT_RELEASE_MANIFEST) -> list[str]:
    """Flatten every include glob from the release include/exclude manifest."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    includes: list[str] = []
    for group in (manifest.get("include") or {}).values():
        if isinstance(group, list):
            includes.extend(str(pattern) for pattern in group)
    return includes


def _glob_covers(path: str, pattern: str) -> bool:
    """Return True when a release-manifest include ``pattern`` would stage ``path``.

    Handles the manifest's actual glob vocabulary: exact files, ``dir/*.ext``, and
    recursive ``prefix/**`` (which fnmatch alone does not treat as crossing separators).
    """
    candidate = path.replace("\\", "/").strip("/")
    glob = pattern.replace("\\", "/").strip("/")
    if glob.endswith("/**"):
        base = glob[:-3]
        return candidate == base or candidate.startswith(base + "/")
    return fnmatch.fnmatch(candidate, glob)


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
    manifest_path: str | Path | None = None,
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

    # Clean-machine data availability: every feature that depends on data/ must
    # have that data provisioned (bundled in the release payload or fetched by a
    # real download route). This guards the "feature renders but its data is
    # missing on a clean install" regression class.
    data_dependencies = contract.get("data_dependencies", [])
    feature_ids = {str(feature.get("id")) for feature in contract.get("feature_groups", [])}
    route_strings = {f"{method} {route_path}" for method, route_path in contract_routes}
    manifest_file = (
        Path(manifest_path)
        if manifest_path is not None
        else root / DEFAULT_RELEASE_MANIFEST
    )
    manifest_includes: list[str] = []
    if manifest_file.exists():
        manifest_includes = load_manifest_includes(manifest_file)
    elif data_dependencies:
        warnings.append(
            {
                "path": str(manifest_file),
                "reason": "release manifest not found; bundled data dependencies cannot be verified",
            }
        )

    for dependency in data_dependencies:
        feature_id = str(dependency.get("feature") or "<missing>")
        if feature_id not in feature_ids:
            violations.append(
                {"feature": feature_id, "reason": "data dependency references unknown feature id"}
            )
        provisioning = str(dependency.get("provisioning") or "")
        if provisioning not in ALLOWED_DATA_PROVISIONING:
            violations.append(
                {"feature": feature_id, "reason": f"invalid data provisioning: {provisioning}"}
            )
        paths = dependency.get("paths") or []
        if not paths:
            violations.append(
                {"feature": feature_id, "reason": "data dependency declares no paths"}
            )
        if provisioning == "bundled":
            for data_path in paths:
                if not any(_glob_covers(str(data_path), pattern) for pattern in manifest_includes):
                    violations.append(
                        {
                            "feature": feature_id,
                            "path": str(data_path),
                            "reason": "bundled data path is not covered by any release manifest include glob",
                        }
                    )
        elif provisioning == "downloader":
            provisioned_by = str(dependency.get("provisioned_by") or "")
            if provisioned_by not in route_strings:
                violations.append(
                    {
                        "feature": feature_id,
                        "provisioned_by": provisioned_by,
                        "reason": "downloader data dependency provisioned_by is not a contract route",
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
        "data_dependency_count": len(data_dependencies),
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Remote Web feature contract coverage.")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), help="Remote Web feature contract JSON path.")
    parser.add_argument("--repo-root", default=".", help="Repository root for source file checks.")
    parser.add_argument("--route-source", default=None, help="Override route source file.")
    parser.add_argument("--manifest", default=None, help="Override release include/exclude manifest path.")
    args = parser.parse_args(argv)

    payload = validate_remote_web_feature_contract(
        args.contract,
        repo_root=args.repo_root,
        route_source=args.route_source,
        manifest_path=args.manifest,
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
