"""Validate the Round 3 runtime asset classification manifest."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


DEFAULT_CLASSIFICATION = Path("release_assets/manifests/runtime_asset_classification.json")
DEFAULT_RELEASE_MANIFEST = Path("release_assets/manifests/release_include_exclude_draft.json")
REQUIRED_DECISION_IDS = {
    "random_prompt_runner_cache",
    "artist_thumbnail_bundles",
    "downloaded_tag_archives",
    "event_preset_runtime_assets",
    "generated_tag_dictionaries",
    "root_image_samples",
    "vibe_transfer_files",
    "local_state_and_outputs",
    "user_wildcards",
    "bootstrap_source_assets",
    "installer_seed_templates",
}
ALLOWED_DECISIONS = {
    "bundle_source_bootstrap",
    "local_sample_or_debug",
    "runtime_downloaded_data",
    "runtime_downloaded_optional_bundle",
    "runtime_generated_cache",
    "runtime_generated_index",
    "runtime_user_state",
    "user_imported_runtime_asset",
}
ALLOWED_RELEASE_ACTIONS = {"include", "exclude"}


@dataclass(frozen=True)
class ClassificationViolation:
    feature: str
    reason: str


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_release_groups(groups: dict[str, Any]) -> set[str]:
    flattened: set[str] = set()
    for patterns in groups.values():
        if isinstance(patterns, list):
            flattened.update(str(pattern) for pattern in patterns)
    return flattened


def validate_runtime_asset_classification(
    classification_path: str | Path = DEFAULT_CLASSIFICATION,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
) -> list[ClassificationViolation]:
    classification_file = Path(classification_path)
    release_file = Path(release_manifest_path)
    violations: list[ClassificationViolation] = []

    if not classification_file.is_file():
        return [ClassificationViolation(str(classification_file), "classification manifest does not exist")]
    if not release_file.is_file():
        return [ClassificationViolation(str(release_file), "release manifest does not exist")]

    manifest = _read_json(classification_file)
    release_manifest = _read_json(release_file)
    decisions = manifest.get("decisions")
    if not isinstance(decisions, list):
        return [ClassificationViolation(str(classification_file), "decisions must be a list")]

    release_includes = _flatten_release_groups(release_manifest.get("include", {}))
    release_excludes = _flatten_release_groups(release_manifest.get("exclude", {}))
    seen_ids: set[str] = set()

    for item in decisions:
        if not isinstance(item, dict):
            violations.append(ClassificationViolation("<unknown>", "decision item must be an object"))
            continue
        item_id = str(item.get("id") or "").strip()
        feature = item_id or "<missing id>"
        if not item_id:
            violations.append(ClassificationViolation(feature, "id is required"))
        elif item_id in seen_ids:
            violations.append(ClassificationViolation(feature, "duplicate decision id"))
        seen_ids.add(item_id)

        patterns = item.get("patterns")
        if not isinstance(patterns, list) or not patterns or not all(isinstance(pattern, str) and pattern for pattern in patterns):
            violations.append(ClassificationViolation(feature, "patterns must be a non-empty string list"))

        decision = str(item.get("decision") or "")
        if decision not in ALLOWED_DECISIONS:
            violations.append(ClassificationViolation(feature, f"unsupported decision: {decision}"))

        release_action = str(item.get("release_action") or "")
        if release_action not in ALLOWED_RELEASE_ACTIONS:
            violations.append(ClassificationViolation(feature, f"unsupported release_action: {release_action}"))

        runtime_destination = str(item.get("runtime_destination") or "").strip()
        if decision.startswith("runtime_") and not runtime_destination:
            violations.append(ClassificationViolation(feature, "runtime decisions require runtime_destination"))

        if release_action == "exclude":
            exclude_patterns = item.get("release_exclude_patterns")
            if not isinstance(exclude_patterns, list) or not exclude_patterns:
                violations.append(ClassificationViolation(feature, "excluded decisions require release_exclude_patterns"))
            else:
                missing = [pattern for pattern in exclude_patterns if pattern not in release_excludes]
                if missing:
                    violations.append(
                        ClassificationViolation(feature, f"release manifest missing exclude patterns: {missing}")
                    )
        elif release_action == "include":
            include_patterns = item.get("release_include_patterns")
            if not isinstance(include_patterns, list) or not include_patterns:
                violations.append(ClassificationViolation(feature, "included decisions require release_include_patterns"))
            else:
                missing = [pattern for pattern in include_patterns if pattern not in release_includes]
                if missing:
                    violations.append(
                        ClassificationViolation(feature, f"release manifest missing include patterns: {missing}")
                    )

    missing_ids = sorted(REQUIRED_DECISION_IDS - seen_ids)
    for item_id in missing_ids:
        violations.append(ClassificationViolation(item_id, "required decision is missing"))

    return violations


def validation_payload(
    classification_path: str | Path = DEFAULT_CLASSIFICATION,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
) -> dict[str, Any]:
    violations = validate_runtime_asset_classification(classification_path, release_manifest_path)
    manifest = _read_json(Path(classification_path)) if Path(classification_path).is_file() else {"decisions": []}
    return {
        "ok": not violations,
        "classification": str(Path(classification_path)),
        "release_manifest": str(Path(release_manifest_path)),
        "decision_count": len(manifest.get("decisions", [])) if isinstance(manifest.get("decisions"), list) else 0,
        "required_decisions": sorted(REQUIRED_DECISION_IDS),
        "violations": [violation.__dict__ for violation in violations],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate NAIA runtime asset classification policy.")
    parser.add_argument("--classification", default=str(DEFAULT_CLASSIFICATION), help="Runtime asset classification manifest.")
    parser.add_argument("--release-manifest", default=str(DEFAULT_RELEASE_MANIFEST), help="Release include/exclude manifest.")
    args = parser.parse_args(argv)

    payload = validation_payload(args.classification, args.release_manifest)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
