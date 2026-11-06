"""Agent onboarding: local catalogs, explicit download consent and durable setup.

Catalog reads never fetch URLs or initialize a session. Install is a separate
operation: callers must obtain the user's consent for the exact item first.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class SetupRequired(ValueError):
    def __init__(self, code, message, details):
        super().__init__(message)
        self.code, self.details = code, details


def source_paths(args):
    from core.runtime_paths import RuntimePaths, resolve_runtime_paths
    paths = resolve_runtime_paths()
    if getattr(args, "user_data", None):
        paths = RuntimePaths(paths.project_root, paths.resource_root,
                             Path(args.user_data).expanduser().resolve(), paths.portable)
    return paths


def model_catalog(paths, mode="NAI"):
    if mode != "NAI":
        return {"provider": mode, "items": [], "requires_connection": True,
                "message": "Installed models belong to the configured provider server; no universal local model list.",
                "next_step": "Search connected capabilities for model/options; the provider's installed model list must be queried on that server.",
                "account_access_verified": False}
    from core.nai_model_registry import NaiModelRegistry
    registry = NaiModelRegistry(SimpleNamespace(runtime_paths=paths))
    items = []
    for row in registry.option_metadata():
        spec = registry.resolve(row["key"])
        alias = next((item for item in items if spec.source == "builtin" and item["source"] == "builtin"
                      and item["api_model"] == spec.api_model), None)
        if alias is not None:
            alias.setdefault("aliases", []).append(spec.key)
            continue
        from core.nai_model_contract import nai_model_variant
        row.update(variant=nai_model_variant(spec) if spec.source == "builtin" else "custom",
                   usage="opus_usage_limit" if spec.uses_opus_usage_limit else "anlas",
                   inpainting_is_substitute=spec.inpainting_is_substitute,
                   account_access_verified=False)
        notes = []
        if not spec.supports_negative_prompt:
            notes.append("Negative prompts are not supported; do not rely on them to exclude content.")
        if spec.fixed_params:
            notes.append("Fixed parameters override requested values: " + str(dict(spec.fixed_params)))
        if spec.inpainting_is_substitute:
            notes.append("Inpainting uses the Full variant rather than this Curated model.")
        row["selection_notes"] = notes
        row["id"] = "nai:" + spec.key
        row["select"] = {"model": row["id"]}
        items.append(row)
    return {"provider": "NAI", "source": "NAIA model contract + user's registry (offline)",
            "account_access_verified": False, "items": items,
            "model_schema": {"type": "string", "enum": [item["id"] for item in items]},
            "choice_required_without_saved_model": True,
            "selection_help": [
                "Choose a generation (V5/V4.5), then Full/Curated/Medium where available.",
                "Medium is a V5 Full variant, not an image resolution or a prompt preset.",
                "Check capabilities and fixed_params before choosing references, negative prompts or sampling settings.",
                "This catalog describes NAIA support, not current subscription access, provider pricing or model quality rankings.",
                "Pass a namespaced ID via --model (e.g. nai:NAID5F). Bare keys and exact API names remain accepted aliases; ambiguous names such as v5 or curated require a choice."]}


def resolve_model(paths, value):
    """Accept exact registry/wire names; never guess Full vs Curated."""
    from core.nai_model_registry import NaiModelRegistry, UnknownNaiModelError
    from core.nai_model_contract import BUILTIN_NAI_MODEL_SPECS, NAI_LEGACY_KEY_ALIASES
    registry = NaiModelRegistry(SimpleNamespace(runtime_paths=paths))
    value = str(value or "").strip()
    try:
        # Namespace identifies registry keys, never API wire names. Keep custom
        # keys in the registry rather than freezing an incomplete Python Enum.
        key = value[4:] if value.startswith("nai:") else (registry.key_for_api_model(value) or value)
        if not key or (value.startswith("nai:") and not registry.has_key(key)):
            raise UnknownNaiModelError(value)
        if not registry.has_key(key):
            key = NAI_LEGACY_KEY_ALIASES.get(str(key).upper(), key)
            key = next((s.key for s in BUILTIN_NAI_MODEL_SPECS.values() if s.api_model == key), key)
        spec = registry.resolve(key)
        if spec.source == "builtin":
            # Old aliases may precede the selectable key (V4: NAID4.0F vs
            # NAID4). Return the same identity advertised by the catalog.
            return next((s.key for s in BUILTIN_NAI_MODEL_SPECS.values()
                         if s.selectable and s.api_model == spec.api_model), spec.key)
        return spec.key
    except UnknownNaiModelError:
        catalog = model_catalog(paths)
        names = [item["key"] for item in catalog["items"]]
        raise SetupRequired("model_selection_required", "Unknown model. Valid names: " + ", ".join(names)
                            + ". Prefer nai:<name>; run models for details.",
                            {"requested": value, "valid_names": names,
                             "valid_model_ids": catalog["model_schema"]["enum"], "catalog": catalog}) from None


def _artist_rows(paths):
    # Do not construct ArtistThumbnailService: its constructor writes UI state.
    from core.artist_thumbnail_service import ArtistThumbnailService
    for key, info in ArtistThumbnailService.ARTIST_THUMB_MODES.items():
        if not info.get("url") or not info.get("path"):
            continue
        relative = Path(info["path"])
        target = paths.ui_assets_dir / "artist_thumb" / relative.relative_to("data")
        existing = target if target.is_file() else paths.project_root / relative
        size = existing.stat().st_size if existing.is_file() else 0
        expected = info.get("expected_size")
        yield {"id": "artist_thumbnail:" + key, "label": info.get("label", key),
               "ready": bool(size and (not expected or size == expected)),
               "readiness_check": "size; downloader verifies checksum on installation",
               "target": str(target), "url": info["url"], "downloadable": True,
               "size_bytes": expected or None, "sha256": info.get("sha256"),
               "purpose": "Optional artist preview images; not required to type an artist tag."}


def asset_catalog(paths):
    from core.runtime_install_manager import RuntimeInstallManager, EVENT_MAP_INDEX_APPROX_MB, STYLE_VARIANTS_APPROX_MB
    manager = RuntimeInstallManager(paths)
    from core.runtime_paths import RuntimePaths
    legacy = RuntimeInstallManager(RuntimePaths(paths.project_root, paths.resource_root, paths.project_root, paths.portable))
    rows = []
    for key, spec in manager._specs.items():
        # snapshot() creates directories; the per-archive read is intentionally used.
        row = manager._archive_snapshot(spec, {})
        row["available_at"] = row["target"] if row["ready"] else None
        # Search and event services also consume existing source-tree data.
        if not row["ready"] and key in {"tag_archive", "tag_archive_increment", "corpus_archive", "event_map"}:
            fallback = legacy._archive_snapshot(legacy._specs[key], {})
            if fallback["ready"]:
                row.update(ready=True, available_at=fallback["target"], availability_source="existing_source_data")
        row.update(id=key, size_bytes=None, readiness_check="installer availability check",
                   requires=["tag_archive"] if key == "tag_archive_increment" else [])
        if key in {"event_map", "style_variants"}:
            row["approx_mb"] = EVENT_MAP_INDEX_APPROX_MB if key == "event_map" else STYLE_VARIANTS_APPROX_MB
        rows.append(row)
    rows.extend(_artist_rows(paths))
    from core.artist_thumbnail_service import ArtistThumbnailService
    physical = {row["id"]: row for row in rows}
    for key, spec in ArtistThumbnailService.ARTIST_THUMB_VIRTUAL_MODES.items():
        members = ["artist_thumbnail:" + name for name in ArtistThumbnailService.ARTIST_THUMB_MODES
                   if name.startswith(spec["prefix"]) and not any(x in name for x in spec.get("exclude_contains", ()))]
        rows.append({"id": "artist_thumbnail:" + key, "label": spec["label"], "virtual": True,
                     "ready": any(physical[m]["ready"] for m in members), "downloadable": False,
                     "members": members, "install_candidates": [m for m in members if not physical[m]["ready"]],
                     "purpose": "Use installed members; ask about one concrete missing pack at a time, not the entire collection."})
    from core.tag_combo.download import BUNDLE_NAME, BUNDLE_URL, BUNDLE_BYTES, BUNDLE_SHA256
    from core.tag_combo.service import ComboService, resolve_dirs
    target, search = resolve_dirs(paths.project_root, paths.data_dir)
    combo = ComboService(target, search_dirs=search)
    rows.append({"id": "tag_combo", "label": "태그 조합 추천", "ready": combo.ready(),
                 "target": str(target / BUNDLE_NAME), "url": BUNDLE_URL,
                 "downloadable": True, "size_bytes": BUNDLE_BYTES, "sha256": BUNDLE_SHA256})
    from core.event_preset_service import EventPresetService
    from core.event_preset_download_service import DOWNLOAD_URL, THUMBNAIL_DOWNLOAD_URL
    preset = EventPresetService(paths.project_root, data_root=paths.data_dir, thumbnail_root=paths.ui_assets_dir)
    availability = preset.status().get("dataAvailability", {})
    for key, label, ready, urls in (
        ("event_preset", "이벤트 프리셋 데이터", availability.get("main") == "ready", [DOWNLOAD_URL]),
        ("event_preset_thumbnails", "이벤트 프리셋 + 썸네일", availability.get("main") == "ready" and availability.get("thumbnails") == "ready", [DOWNLOAD_URL, THUMBNAIL_DOWNLOAD_URL]),
    ):
        rows.append({"id": key, "label": label, "ready": ready, "urls": urls,
                     "downloadable": True, "size_bytes": None,
                     "target": str(paths.data_dir), "thumbnail_target": str(paths.ui_assets_dir)})
    from core.sequence_download_service import DOWNLOAD_URL as SEQ_URL, TARGET_RELPATH, SequenceDownloadService
    seq_path = paths.data_dir / TARGET_RELPATH
    if not seq_path.exists():
        seq_path = paths.project_root / "data" / TARGET_RELPATH
    rows.append({"id": "sequence", "label": "시퀀스 데이터", "ready": seq_path.is_file() and SequenceDownloadService._validate(seq_path),
                 "target": str(paths.data_dir / TARGET_RELPATH), "url": SEQ_URL,
                 "downloadable": bool(SEQ_URL), "size_bytes": None})
    for key, filename, label in (("character_dictionary", "danbooru_character.py", "캐릭터 이름 사전"),
                                  ("artist_dictionary", "artist_dictionary.py", "작가 이름 사전")):
        rows.append({"id": key, "label": label, "ready": (paths.project_root / filename).is_file(),
                     "downloadable": False, "source": "bundled", "target": str(paths.project_root / filename),
                     "repair": "Restore this bundled file from the matching NAIA release; thumbnail packs do not replace it."})
    return {"items": rows, "user_data": str(paths.user_root),
            "policy": "Pause the requested operation. Ask the user about the exact missing items, sizes (unknown if null), sources and destinations. Install only approved IDs, verify completion, then retry the suspended request. Refusal leaves the request paused; do not silently substitute another feature.",
            "catalog_only": True, "network_used": False}


def request_assets(catalog, ids, *, reason="missing_assets", request=None):
    by_id = {row["id"]: row for row in catalog["items"]}
    items = [by_id[key] for key in dict.fromkeys(ids) if key in by_id]
    items = [by_id[row["install_candidates"][0]] if row.get("virtual") and row.get("install_candidates") else row for row in items]
    raise SetupRequired("asset_setup_required", "User approval is required before downloading the requested assets.", {
        "reason": reason, "requires_user_input": True, "items": items,
        "question": ("필요한 자산을 표시된 출처에서 다운로드하여 설치할까요?" if any(row.get("downloadable") for row in items)
                     else "필수 번들 파일이 없습니다. 같은 버전의 NAIA 배포본에서 복원할까요?"),
        "request": request, "resume": "After installation succeeds, retry the suspended request; do not replay completed batch mutations.",
        "install_requests": [{"command": "assets", "action": "install", "item": row["id"],
                              "user_data": catalog.get("user_data"), "approve_download": row["id"]}
                             for row in items if row.get("downloadable") and catalog.get("user_data")],
        "installation_host": "Run the approved installer on the backend host. Remote catalogs do not expose its local paths.",
        "approval_note": "These are proposed commands, not consent. Send approve_download only after the user approves this item."})


def require_assets(paths, ids, *, request=None):
    if not ids:
        return
    catalog = asset_catalog(paths)
    unknown = set(ids) - {row["id"] for row in catalog["items"]}
    if unknown:
        raise SetupRequired("unknown_asset", "Unknown prerequisite IDs; inspect the asset catalog.", {"items": sorted(unknown)})
    missing = [row["id"] for row in catalog["items"] if row["id"] in ids and not row["ready"]]
    if missing:
        request_assets(catalog, missing, request=request)


def _wait_worker(thread, snapshot, cancel=None):
    # Keep the command alive until the existing downloader has verified/published
    # the asset. A dispatch acknowledgment is never reported as installed.
    try:
        if thread is not None:
            while thread.is_alive():
                thread.join(.25)
    except KeyboardInterrupt:
        if cancel:
            cancel()
            if thread:
                thread.join(35)
        raise
    state = snapshot()
    if state.get("error") or state.get("active") or not (state.get("done") or state.get("state") == "ready"):
        raise SetupRequired("asset_install_failed", "Asset installation did not complete.", {"download": state})
    return state


def install_asset(paths, item, approved):
    catalog = asset_catalog(paths)
    row = next((r for r in catalog["items"] if r["id"] == item), None)
    if row is None:
        raise SetupRequired("unknown_asset", "Unknown asset ID; inspect assets list.", {"item": item})
    if row["ready"]:
        return {"item": item, "installed": True, "already_ready": True, "asset": row}
    if approved != item:
        request_assets(catalog, [item], reason="download_consent_required")
    if not row.get("downloadable"):
        raise SetupRequired("asset_not_downloadable", "This asset ships with NAIA or is a collection; choose a concrete downloadable item.", row)
    require_assets(paths, row.get("requires", []))
    from core.runtime_install_manager import RuntimeInstallManager
    manager = RuntimeInstallManager(paths)
    if item in manager._specs:
        manager.start_archive_download(item)
        state = _wait_worker(manager._thread, lambda: dict(manager._download_state), manager.cancel_archive_download)
    elif item.startswith("artist_thumbnail:"):
        from core.artist_thumbnail_service import ArtistThumbnailService
        # Installer construction must not reset the user's artist-panel settings.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="naia-asset-state-") as state_dir:
            svc = ArtistThumbnailService(paths.project_root, mode_data_root=paths.ui_assets_dir / "artist_thumb",
                                         state_root=state_dir, wildcards_root=Path(state_dir) / "wildcards")
            svc.start_download(item.split(":", 1)[1])
            state = _wait_worker(svc._download_thread, svc.download_snapshot, svc.cancel_download)
    elif item == "tag_combo":
        from core.tag_combo.service import ComboService, resolve_dirs
        target, search = resolve_dirs(paths.project_root, paths.data_dir)
        svc = ComboService(target, search_dirs=search)
        svc.ensure_bundle(retry=True)
        state = _wait_worker(svc.downloader._thread, svc.downloader.status)
    elif item in {"event_preset", "event_preset_thumbnails"}:
        from core.event_preset_service import EventPresetService
        from core.event_preset_download_service import EventPresetDownloadService
        def status():
            return EventPresetService(paths.project_root, data_root=paths.data_dir, thumbnail_root=paths.ui_assets_dir).status()
        svc = EventPresetDownloadService(paths.project_root, data_root=paths.data_dir,
                                        thumbnail_root=paths.ui_assets_dir, status_provider=status)
        svc.start(main_only=item == "event_preset")
        state = _wait_worker(svc._thread, svc.snapshot, svc.cancel)
    else:  # sequence
        from core.sequence_preset_service import SequencePresetService
        from core.sequence_download_service import SequenceDownloadService
        svc = SequenceDownloadService(paths.project_root, data_root=paths.data_dir,
                status_provider=lambda: SequencePresetService(paths.project_root, data_root=paths.data_dir).status())
        svc.start()
        state = _wait_worker(svc._thread, svc.snapshot, svc.cancel)
    current = next(r for r in asset_catalog(paths)["items"] if r["id"] == item)
    if not current["ready"]:
        raise SetupRequired("asset_install_failed", "Download finished but the asset is not ready.", {"asset": current, "download": state})
    return {"item": item, "installed": True, "asset": current, "download": state,
            "resume": "Retry the suspended operation in a new CLI session; the asset is stored in persistent user data."}


def capability_assets(identifier, payload):
    """Requirements for data-dependent operations; browsing state remains available."""
    path = identifier.split(":", 2)[-1]
    if path.startswith("/api/event-map/") and path.rsplit("/", 1)[-1] in {"resolve", "explore", "sample", "apply"}:
        return ["event_map"]
    if path == "/api/tag-combo":
        return ["tag_combo"]
    if path.startswith("/api/event-preset/") and not path.endswith(("status", "download")):
        return ["event_preset_thumbnails" if "thumbnail" in path else "event_preset"]
    if path.startswith("/api/sequence-preset/") and not any(x in path for x in ("status", "download")):
        return ["sequence"]
    if identifier in {"websocket:search", "websocket:bootstrap_random"}:
        return ["tag_archive"]
    if identifier == "websocket:event_corpus_query":
        return ["corpus_archive"]
    if path in {"/api/artist-thumb/list", "/api/artist-thumb/image"}:
        mode = payload.get("query", {}).get("mode")
        # Empty mode is a dictionary-only list, not a request for every preview.
        return ["artist_thumbnail:" + str(mode)] if mode else []
    return []


def download_asset_id(identifier, payload):
    """Identify network setup mutations, including those outside this asset catalog."""
    if not identifier.startswith("http:POST:"):
        return ""
    path = identifier.split(":", 2)[-1]
    if path.endswith("/cancel") or not {"download", "install"}.intersection(path.strip("/").split("/")):
        return ""
    fixed = {"/api/tag-combo/download": "tag_combo", "/api/event-preset/download": "event_preset_thumbnails",
             "/api/sequence-preset/download/start": "sequence", "/api/artist-thumb/download": "artist_thumbnail:" + str(payload.get("json", {}).get("mode", ""))}
    if path in fixed:
        return fixed[path]
    if path.startswith("/api/install-manager/") and path.endswith("/download"):
        return path.split("/")[-2].replace("-", "_")
    return identifier
