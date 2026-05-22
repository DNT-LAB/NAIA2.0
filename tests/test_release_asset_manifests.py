import json
from pathlib import Path

from tools.audit_final_goal_completion import _parse_when_done_items


MANIFEST_DIR = Path("release_assets/manifests")


def _read_manifest(name: str) -> dict:
    return json.loads((MANIFEST_DIR / name).read_text(encoding="utf-8"))


def test_runtime_asset_policy_declares_user_runtime_roots():
    manifest = _read_manifest("runtime_asset_policy.json")

    assert manifest["source_is_not_heavy_by_default"] is True
    assert manifest["large_local_asset_classification_manifest"] == (
        "release_assets/manifests/runtime_asset_classification.json"
    )
    assert manifest["runtime_roots"] == {
        "installed": "%APPDATA%/NAIA",
        "portable": "user-data",
    }
    assert "ui_assets" in manifest["writable_runtime_dirs"]
    assert "wildcards" in manifest["writable_runtime_dirs"]
    assert manifest["runtime_asset_destinations"]["external_helper_binaries"] == "downloads"
    assert "data/**" in manifest["blocked_future_download_targets"]
    assert "ui/**" in manifest["blocked_future_download_targets"]


def test_project_layout_policy_declares_python_web_default_and_optional_electron():
    manifest = _read_manifest("project_layout_policy.json")

    assert manifest["policy_document"] == "PROJECT_LAYOUT_POLICY.md"
    assert manifest["default_runtime"]["name"] == "Python Headless Web"
    assert manifest["default_runtime"]["entrypoint"] == "NAIA_web_headless.py"
    assert "requirements-headless.txt" in manifest["default_runtime"]["required_launcher_terms"]
    assert "npm" in manifest["default_runtime"]["forbidden_launcher_terms"]
    assert manifest["canonical_remote_web"]["path"] == "app/web/remote"
    assert manifest["canonical_remote_web"]["legacy_path"] == "ui/remote_web"
    assert manifest["canonical_remote_web"]["legacy_path_status"] == "resolved_removed"
    assert manifest["optional_electron"]["root"] == "app/electron"
    assert manifest["evidence_manifests"]["round_completion"] == (
        "release_assets/manifests/project_layout_round_completion.json"
    )
    assert manifest["evidence_manifests"]["cleanup_candidates"] == (
        "release_assets/manifests/project_cleanup_candidates.json"
    )
    assert manifest["evidence_manifests"]["runtime_distribution_tracks"] == (
        "release_assets/manifests/runtime_distribution_tracks.json"
    )
    assert "app/electron/node_modules" in manifest["runtime_only_roots"]


def test_release_manifest_excludes_legacy_and_local_runtime_state():
    manifest = _read_manifest("release_include_exclude_draft.json")
    excluded = "\n".join(
        value
        for group in manifest["exclude"].values()
        for value in group
    )
    rules = "\n".join(manifest["hard_rules"])

    assert "legacy_desktop/**" in excluded
    assert "NAIA_cold_v4.py" in excluded
    assert "core/context.py" in excluded
    assert "core/image_crud_controller.py" in excluded
    assert "core/tag_data_manager.py" in excluded
    assert "tabs/comic_generator_tab.py" in excluded
    assert "tabs/comic_generator/**" in excluded
    assert "ui/variational/**" in excluded
    assert "experimental/ontology_visualizer/**" in excluded
    assert "temp/ezmode/**" in excluded
    assert "save/**" in excluded
    assert "logs/**" in excluded
    assert "output/**" in excluded
    assert "wildcards/**" in excluded
    assert "data/event_preset/**" in excluded
    assert "data/event_preset_thumbnail" in excluded
    assert "ui/event_preset/**" in excluded
    assert "artist_dictionary.py" in excluded
    assert "result_dupl.py" in excluded
    assert "00001.png" in excluded
    assert "**/.claude/**" in excluded
    assert "**/.cloudflared_bin/**" in excluded
    assert "**/AGENTS.md" in excluded
    assert "**/CLAUDE.md" in excluded
    assert "**/*.md" in excluded
    assert "pytest-cache-files-*/**" in excluded
    assert "*.xlsx" in excluded
    assert "PyQt6" in excluded
    assert "PyQt6" in rules
    assert "stage_release_assets.py" in rules
    assert "resources/naia-backend" in rules
    assert "smoke_staged_backend.py" in rules
    assert "smoke_remote_web_contract.py" in rules
    assert "write_release_metadata.py" in rules
    assert "check_release_preflight.py" in rules
    assert "check_backend_runtime_strategy.py" in rules
    assert "check_project_layout_policy.py" in rules
    assert "check_runtime_distribution_tracks.py" in rules
    assert "check_project_layout_round_completion.py" in rules
    assert "check_project_cleanup_candidates.py" in rules
    assert "check_remote_web_feature_contract.py" in rules
    assert "check_runtime_write_policy.py" in rules
    assert "check_runtime_asset_classification.py" in rules
    assert "check_legacy_pyqt_surface_classification.py" in rules
    assert "check_headless_core_boundary.py" in rules
    assert "release_manifest_audit.py" in rules


def test_release_manifest_tracks_staged_backend_and_web_ownership_paths():
    manifest = _read_manifest("release_include_exclude_draft.json")

    assert "app/backend/**" in manifest["include"]["backend_runtime"]
    assert "app/web/assets.py" in manifest["include"]["backend_runtime"]
    assert "interfaces/**" in manifest["include"]["backend_runtime"]
    assert "app/web/remote/**" in manifest["include"]["web_ui"]
    assert "data/clothes_list.txt" in manifest["include"]["bootstrap_assets"]
    assert "data/color.txt" in manifest["include"]["bootstrap_assets"]
    assert "data/characteristic_list.txt" in manifest["include"]["bootstrap_assets"]
    assert "data/taglist/*.json" in manifest["include"]["bootstrap_assets"]
    assert "wildcards/**" not in manifest["include"]["bootstrap_assets"]
    assert "ui/remote_web/**" not in manifest["include"]["web_ui"]
    assert "app/electron/**" in manifest["include"]["electron_shell"]


def test_runtime_asset_policy_uses_new_remote_web_source_root():
    manifest = _read_manifest("runtime_asset_policy.json")

    assert "app/web/remote/**" in manifest["source_bootstrap_assets"]
    assert "data/clothes_list.txt" in manifest["source_bootstrap_assets"]
    assert "data/taglist/*.json" in manifest["source_bootstrap_assets"]
    assert "wildcards/**" not in manifest["source_bootstrap_assets"]
    assert "ui/remote_web/**" not in manifest["source_bootstrap_assets"]


def test_electron_shell_contract_covers_browser_api_assumptions():
    manifest = _read_manifest("electron_shell_contract.json")
    assumptions = manifest["browser_api_assumptions"]
    maintenance = manifest["maintenance_view"]
    rules = "\n".join(manifest["hard_rules"])

    for key in (
        "websocket",
        "local_storage",
        "session_storage",
        "file_picker",
        "clipboard",
        "drag_drop",
        "downloads",
        "popups",
    ):
        assert key in assumptions
    assert manifest["primary_window"]["context_isolation"] is True
    assert manifest["primary_window"]["node_integration"] is False
    assert "Open logs" in maintenance["required_controls"]
    assert "maintenance view renders the shell log buffer" in maintenance["required_log_flow"]
    assert "NAIA_USER_DATA_DIR" in rules
    assert "PyQt6" in rules


def test_remote_web_feature_contract_covers_required_surface_groups():
    manifest = _read_manifest("remote_web_feature_contract.json")
    feature_ids = {feature["id"] for feature in manifest["feature_groups"]}
    all_routes = {
        (route["method"], route["path"])
        for feature in manifest["feature_groups"]
        for route in feature["routes"]
    }

    assert manifest["route_source"] == "core/web_session_app.py"
    assert {"prompt_tools", "params_workflow_search", "presets", "danbooru", "artist_thumbnail", "install_manager"} <= feature_ids
    assert ("WEBSOCKET", "/ws") in all_routes
    assert ("GET", "/api/install-manager") in all_routes
    assert ("POST", "/api/install-manager/initialize") in all_routes
    assert ("POST", "/api/image-action/{action}") in all_routes
    assert "Generate dispatch with configured NovelAI/WebUI/ComfyUI or controlled test doubles" in manifest["required_live_smoke"]


def test_runtime_write_policy_tracks_runtime_download_owners():
    manifest = _read_manifest("runtime_write_policy.json")
    features = {item["feature"] for item in manifest["required_runtime_download_owners"]}

    assert "cloudflared_download_implementation" in features
    assert "artist_thumbnail_download_implementation" in features
    assert "event_preset_download" in features
    assert "event_preset_service_read_preference" in features
    assert "remote_web_image_fetch" in features
    assert "artist_thumbnail_dictionary" in features
    assert "cloudflared_helper" in features


def test_final_goal_completion_evidence_maps_only_provable_release_items():
    manifest = _read_manifest("final_goal_completion_evidence.json")
    mapped_items = {item["item"] for item in manifest["rules"]}
    mapped_when_done = {(item["round"], item["item"]) for item in manifest["when_done_rules"]}
    intentionally_unmapped = {
        (item["round"], item["item"])
        for item in manifest["intentionally_unmapped"]
        if item["section"] == "when_done_rules"
    }
    all_condition_paths = {
        condition["path"]
        for item in [*manifest["rules"], *manifest["when_done_rules"]]
        for condition in item["requires"]
    }
    numeric_conditions = {
        condition["path"]
        for item in [*manifest["rules"], *manifest["when_done_rules"]]
        for condition in item["requires"]
        if "number_gt" in condition or "number_gte" in condition
    }

    assert manifest["portable_workspace_evidence"] == "app/electron/dist/electron_workspace_release_evidence.json"
    assert (
        "Round 0 - Baseline Freeze and Ownership Map",
        "No code files or large data files have been moved.",
    ) in intentionally_unmapped
    assert "Build the Electron app with the chosen backend runtime." in mapped_items
    assert "Validate packaged app with CDP/browser or Electron automation where possible." in mapped_items
    assert "Validate window sizing, file picker/download behavior, clipboard/image paste, drag/drop, websocket reconnect, and local storage/session behavior." in mapped_items
    assert "Measure cold start, package size, dependency drift, data-file handling, update/patch behavior, and scanner result." in mapped_items
    assert "Run packaged-app smoke tests for random prompt, Generate, result display, Prompt Tools, Params, Presets, Danbooru, Artist Thumb, img2img, Vibe Transfer Storage, Character Reference, Enhance, setup/API settings, history, save/output." in mapped_items
    assert "Measure cold start, first paint, random prompt latency after warmup, and Generate dispatch latency." in mapped_items
    assert (
        "Round 9 - Packaged App Integration",
        "Packaged app starts the headless server and hosts the UI in an owned desktop window.",
    ) in mapped_when_done
    assert (
        "Round 7 - Electron Shell Prototype",
        "Startup failure produces a visible maintenance/error view with logs.",
    ) in mapped_when_done
    assert (
        "Round 7 - Electron Shell Prototype",
        "Browser launch remains a fallback, not the primary UX.",
    ) in mapped_when_done
    assert (
        "Round 9 - Packaged App Integration",
        "Core Remote Web workflows pass from the packaged app, not just from the source checkout.",
    ) in mapped_when_done
    assert (
        "Round 9 - Packaged App Integration",
        "Logs are accessible from the Electron shell.",
    ) in mapped_when_done
    assert (
        "Round 10 - Clean-Machine Release Gate and Optional Installer",
        "A clean Windows machine can run the packaged app.",
    ) in mapped_when_done
    assert (
        "Round 10 - Clean-Machine Release Gate and Optional Installer",
        "Release notes list external dependencies such as NovelAI, WebUI, ComfyUI endpoints, and optional downloadable data.",
    ) in mapped_when_done
    assert (
        "Round 10 - Clean-Machine Release Gate and Optional Installer",
        "Upgrade/uninstall behavior is documented and non-destructive by default.",
    ) in mapped_when_done
    assert "dry_run" in all_condition_paths
    assert "sections.electron_builder.ok" in all_condition_paths
    assert "sections.electron_shell_contract.ok" in all_condition_paths
    assert "sections.electron_shell_contract.checks.maintenance_logs.logs_accessible" in all_condition_paths
    assert "sections.electron_shell_contract.checks.browser_fallback.fallback_only" in all_condition_paths
    assert "sections.electron_cdp_smoke.ok" in all_condition_paths
    assert "sections.electron_cdp_smoke.state.backendState" in all_condition_paths
    assert "sections.staged_workspace.sections.preflight.checks.release_notes.external_dependencies_listed" in all_condition_paths
    assert "sections.electron_cdp_smoke.checks.websocketReconnect.reconnected" in all_condition_paths
    assert "sections.electron_cdp_smoke.checks.featureWorkflows.allRequiredFeaturesObserved" in all_condition_paths
    assert "sections.electron_cdp_smoke.checks.randomPromptRoundTrip.latencyMs" in all_condition_paths
    assert "sections.electron_cdp_smoke.checks.performance.firstPaintProxyMs" in all_condition_paths
    assert "sections.clean_packaged.checks.measurement.scanner.ok" in all_condition_paths
    assert "sections.clean_packaged.checks.measurement.stats.total_bytes" in numeric_conditions
    assert "sections.electron_cdp_smoke.timings.shell_ready_s" in numeric_conditions
    assert "sections.electron_cdp_smoke.checks.performance.firstPaintProxyMs" in numeric_conditions


def test_final_plan_when_done_items_have_evidence_mapping_or_explicit_exception():
    manifest = _read_manifest("final_goal_completion_evidence.json")
    plan_items = _parse_when_done_items(
        Path("refactor_plans/final_headless_electron_release_reorganization_plan.md").read_text(encoding="utf-8")
    )
    mapped = {(item["round"], item["item"]) for item in manifest["when_done_rules"]}
    intentionally_unmapped = {
        (item["round"], item["item"])
        for item in manifest["intentionally_unmapped"]
        if item["section"] == "when_done_rules"
    }

    missing = [
        (item["round"], item["item"])
        for item in plan_items
        if (item["round"], item["item"]) not in mapped
        and (item["round"], item["item"]) not in intentionally_unmapped
    ]

    assert missing == []


def test_source_layout_contract_tracks_final_target_layout():
    manifest = _read_manifest("source_layout_contract.json")
    required = set(manifest["required_directories"])
    markers = set(manifest["python_package_markers"])

    assert "app/backend/generation" in required
    assert "app/backend/presets" in required
    assert "app/backend/search" in required
    assert "app/backend/settings" in required
    assert "app/backend/assets_storage" in required
    assert "data/source" in required
    assert "release_assets/samples" in required
    assert "legacy_desktop/interfaces" in required
    assert "legacy_desktop/utils" in required
    assert "app/backend/generation/__init__.py" in markers
    assert "app/electron/dist" in manifest["runtime_only_roots"]
