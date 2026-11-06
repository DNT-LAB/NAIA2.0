"""Discover, describe and invoke NAIA capabilities as JSON.

Start with capabilities overview/search/describe/audit. call and batch invoke
registered transports on a live backend, using that backend's state and credentials.
Convenience commands (auth/presets/tags/random/generate) own a separate serverless
session; they do not define the full feature boundary.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
from typing import Any


class CliError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError("invalid_arguments", message)


def parser() -> argparse.ArgumentParser:
    p = JsonParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user-data", help="Existing NAIA user-data directory (default: normal runtime resolution)")
    p.add_argument("--credentials-file", help="Existing secure_tokens.json; contents are never printed")
    p.add_argument("--mode", choices=["NAI", "WEBUI", "COMFYUI"], default="NAI")
    p.add_argument("--credential-env", help="Read a credential from this environment variable, without saving it")
    commands = p.add_subparsers(dest="command", required=True)
    capabilities = commands.add_parser("capabilities", help="Discover, describe and audit the full registered/source capability catalog")
    capabilities.add_argument("action", choices=["overview", "list", "search", "describe", "audit"], nargs="?", default="overview")
    capabilities.add_argument("query", nargs="?", default="", help="Search terms or capability ID")
    capabilities.add_argument("--kind", default="", choices=["", "http", "websocket", "module", "service", "python", "frontend", "shell"])
    capabilities.add_argument("--offset", type=int, default=0)
    capabilities.add_argument("--limit", type=int, default=30)
    capability_target = capabilities.add_mutually_exclusive_group()
    capability_target.add_argument("--server", help="Inspect the actual live backend; omitted means source-only discovery")
    capability_target.add_argument("--standalone", action="store_true", help="Inspect a private command-scoped runtime using existing local data")
    capabilities.add_argument("--timeout", type=float, default=60)
    capabilities.add_argument("--details", action="store_true", help="Include full audit gaps and file coverage")
    capabilities.add_argument("--output", help="Write full discovery JSON to a new file")
    call = commands.add_parser("call", help="Invoke a discovered HTTP/WebSocket/module capability on a live backend")
    call.add_argument("capability", help="ID returned by capabilities; e.g. http:GET:/api/thumb/state")
    batch = commands.add_parser("batch", help="Invoke a JSON array of discovered operations in one connected session")
    for sub in (call, batch):
        target = sub.add_mutually_exclusive_group()
        target.add_argument("--server", default="http://127.0.0.1:7243")
        target.add_argument("--standalone", action="store_true", help="Run existing routes in a private CLI session; no running web server required")
        sub.add_argument("--input", default="{}" if sub is call else "-", help="JSON, @file.json or - for stdin")
        sub.add_argument("--timeout", type=float, default=60)
        sub.add_argument("--observe", type=float, default=0, help="Observe WebSocket events after dispatch, in seconds (0..300)")
    call.add_argument("--output", help="Save an HTTP response (including binary images) to a new file")
    run = commands.add_parser("run", help="Read a JSON request object from a file or stdin (-)")
    run.add_argument("request", help="JSON file path, or - for stdin")
    commands.add_parser("auth", help="Report credential availability; does not call a provider")
    commands.add_parser("models", help="Offline model catalog, differences, constraints and exact selection keys")
    assets = commands.add_parser("assets", help="Inspect required downloads; install only after item-specific user approval")
    assets.add_argument("action", choices=["list", "install"], nargs="?", default="list")
    assets.add_argument("item", nargs="?", default="")
    assets.add_argument("--approve-download", help="Exact asset ID approved by the user; never infer consent from the original task")
    presets = commands.add_parser("presets", help="List presets, or inspect one with --name")
    presets.add_argument("--name")
    tags = commands.add_parser("tags", help="Search the existing English/Korean tag index")
    tags.add_argument("query")
    tags.add_argument("--limit", type=int, default=20)
    for name in ("random", "generate"):
        sub = commands.add_parser(name, help="Compose a parquet prompt" if name == "random" else "Generate and save one image")
        sub.add_argument("--preset", help="Omit to use the user's current preset; override only for a deliberate change")
        sub.add_argument("--parquet", action="append", default=[], help="Input parquet; repeat to combine files")
        sub.add_argument("--query", default="", help="Existing search syntax: comma AND, {a|b} OR, *exact")
        sub.add_argument("--exclude", default="")
        sub.add_argument("--ratings", default="g", help="Allowed ratings, e.g. g or gsqe (default: g)")
        sub.add_argument("--random-seed", type=int, help="Seed Python/NumPy prompt sampling separately from image seed")
        sub.add_argument("--negative", help="Override the preset negative, including an empty string")
        sub.add_argument("--model", help="NAI: namespaced ID such as nai:NAID5F; run models for valid choices")
        sub.add_argument("--width", type=int)
        sub.add_argument("--height", type=int)
        sub.add_argument("--steps", type=int)
        sub.add_argument("--cfg", type=float)
        sub.add_argument("--seed", type=int, help="Image generation seed")
        if name == "generate":
            source = sub.add_mutually_exclusive_group(required=True)
            source.add_argument("--random", action="store_true", help="Compose a parquet prompt, then generate it")
            source.add_argument("--prompt", help="Exact prompt (preset still supplies generation settings)")
            sub.add_argument("--output", required=True, help="New PNG path; existing files are never overwritten")
            sub.add_argument("--dry-run", action="store_true", help="Normalize request without calling the provider")
    return p


def parse_args(argv=None):
    args = parser().parse_args(argv)
    if args.command != "run":
        return args
    try:
        raw = sys.stdin.read() if args.request == "-" else Path(args.request).read_text(encoding="utf-8-sig")
        request = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise CliError("invalid_request", "Cannot read JSON request") from exc
    if not isinstance(request, dict) or request.get("command") not in {"auth", "models", "assets", "presets", "tags", "random", "generate", "capabilities", "call", "batch"}:
        raise CliError("invalid_request", "Request must be an object with a supported command")
    tokens = []
    request = dict(request)
    command = request.pop("command")
    for key in ("user_data", "credentials_file", "credential_env", "mode"):
        value = request.pop(key, getattr(args, key))
        if value is not None:
            tokens.extend(["--" + key.replace("_", "-"), str(value)])
    tokens.append(command)
    if command == "capabilities":
        tokens.extend([str(request.pop("action", "overview")), str(request.pop("query", ""))])
    elif command == "assets":
        tokens.extend([str(request.pop("action", "list")), str(request.pop("item", ""))])
    elif command == "call":
        tokens.append(str(request.pop("capability", "")))
    tag_query = None
    if command == "tags":
        tag_query = str(request.pop("query", ""))
    for key, value in request.items():
        if key == "input" and command in {"call", "batch"} and isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        if key in {"random", "dry_run", "details", "standalone"}:
            if not isinstance(value, bool):
                raise CliError("invalid_request", f"{key} must be a JSON boolean")
            if value:
                tokens.append("--" + key.replace("_", "-"))
            continue
        values = value if isinstance(value, list) and key == "parquet" else [value]
        for item in values:
            if isinstance(item, (dict, list, bool)) or item is None:
                raise CliError("invalid_request", f"Invalid value for {key}")
            # Equals keeps a prompt starting with '-' from being parsed as a flag.
            tokens.append("--" + key.replace("_", "-") + "=" + str(item))
    if tag_query is not None:
        tokens.extend(["--", tag_query])
    return parser().parse_args(tokens)


def validate(args):
    if args.command == "tags" and not 1 <= args.limit <= 100:
        raise CliError("invalid_arguments", "--limit must be between 1 and 100")
    if args.command not in {"random", "generate"}:
        return
    if not args.ratings or set(args.ratings) - set("gsqe"):
        raise CliError("invalid_arguments", "--ratings must contain only g, s, q, e")
    if args.cfg is not None and (not math.isfinite(args.cfg) or args.cfg < 0):
        raise CliError("invalid_arguments", "--cfg must be a finite non-negative number")
    for key in ("width", "height", "steps"):
        value = getattr(args, key)
        if value is not None and value <= 0:
            raise CliError("invalid_arguments", f"--{key} must be positive")
    if args.command == "generate":
        if args.prompt is not None and not args.prompt.strip():
            raise CliError("invalid_arguments", "--prompt must not be empty")
        if args.prompt is not None and (args.parquet or args.query or args.exclude):
            raise CliError("invalid_arguments", "Parquet/search options require --random")
        target = Path(args.output).expanduser().resolve()
        if target.suffix.lower() != ".png":
            raise CliError("invalid_arguments", "--output must be a .png path")
        if target.exists():
            raise CliError("output_exists", "Output already exists; choose a new path")


@contextmanager
def isolated_session(args, secrets: list[str]):
    from core.runtime_paths import RuntimePaths, resolve_runtime_paths
    from core.secure_token_manager import SecureTokenManager
    from core.headless_token_store import InMemoryTokenManager

    source = resolve_runtime_paths()
    if args.user_data:
        source = RuntimePaths(source.project_root, source.resource_root,
                              Path(args.user_data).expanduser().resolve(), source.portable)
        if source.user_root.exists() and not source.user_root.is_dir():
            raise CliError("missing_data", "--user-data must be a directory")
    credential_path = (Path(args.credentials_file).expanduser().resolve() if args.credentials_file
                       else source.config_dir / "secure_tokens.json")
    if args.credentials_file and not credential_path.is_file():
        raise CliError("missing_credentials", "--credentials-file does not exist")
    # No blank token file is created by a read-only auth check.
    token_store = SecureTokenManager(credential_path) if credential_path.is_file() else InMemoryTokenManager()
    values = {key: token_store.get_token(key) for key in ("nai_token", "webui_url", "comfyui_url")}
    if args.credential_env:
        value = os.environ.get(args.credential_env, "")
        if not value:
            raise CliError("missing_credentials", "Credential environment variable is empty or missing")
        values[{"NAI": "nai_token", "WEBUI": "webui_url", "COMFYUI": "comfyui_url"}[args.mode]] = value
    secrets.extend(value for value in values.values() if value)

    @dataclass(frozen=True)
    class SessionPaths(RuntimePaths):
        def writable_dir(self, name):
            # Large shared dictionaries, wildcards and rebuildable caches stay in
            # their normal locations. All settings/results use the private root.
            if name in {"data", "wildcards", "cache", "ui_assets"}:
                return source.writable_dir(name)
            return super().writable_dir(name)

    with tempfile.TemporaryDirectory(prefix="naia-cli-") as temporary:
        root = Path(temporary)
        paths = SessionPaths(source.project_root, source.resource_root, root, source.portable)
        # Mirror preset JSON only, not thumbnails, images or web-session state.
        roots = [source.project_root / "save", source.save_dir]
        if os.environ.get("NAIA_DISABLE_LEGACY_SAVE_FALLBACK") == "1" or os.environ.get("NAIA_ELECTRON") == "1":
            roots = [source.save_dir]
        for save_root in roots:
            files = list((save_root / "presets").rglob("*.json")) if (save_root / "presets").is_dir() else []
            files += list(save_root.glob("PromptEngineeringModule_*.json"))
            if (save_root / "nai_models.json").is_file():
                files.append(save_root / "nai_models.json")
            for file in files:
                dest = paths.save_dir / file.relative_to(save_root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, dest)
        env_keys = {"NAIA_USER_DATA_DIR": str(root), "NAIA_DISABLE_LEGACY_SAVE_FALLBACK": "1"}
        before = {key: os.environ.get(key) for key in env_keys}
        os.environ.update(env_keys)
        try:
            from core.web_session_context import WebSessionContext
            context = WebSessionContext(runtime_paths=paths, token_manager=InMemoryTokenManager(values))
            context.agent_source_paths = source
            # Read installed previews from persistent storage; panel preferences
            # remain private even though images live alongside them in Web mode.
            from core.artist_thumbnail_service import ArtistThumbnailService
            context.artist_thumbnail_service = ArtistThumbnailService(
                source.project_root, mode_getter=context.get_api_mode,
                mode_data_root=source.ui_assets_dir / "artist_thumb",
                state_root=root / "artist_thumb", wildcards_root=root / "artist-wildcards")
            context.set_api_mode(args.mode)
            # Explicit standalone invocation always uses the external COMFYUI URL.
            if args.mode == "COMFYUI":
                context.remote_params["comfyui_engine"] = "external"
            yield context, source
        finally:
            for key, value in before.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def select_preset(context, name):
    from core.prompt_engineering_settings import get_prompt_engineering_store
    store = get_prompt_engineering_store(context)
    selected = name or store.state().get("current_preset", "default")
    if selected not in store.preset_options():
        raise CliError("preset_not_found", f"Unknown preset: {selected}")
    response = context._prompt_engineering_service().set_param("preset", selected)
    messages = response if isinstance(response, list) else [response]
    for message in messages:
        if isinstance(message, dict) and message.get("level") == "error":
            raise CliError("preset_failed", str(message.get("message") or "Preset selection failed"))
    return selected


def overrides(args):
    values = {key: getattr(args, key) for key in ("model", "width", "height", "steps", "seed")
              if getattr(args, key) is not None}
    if args.cfg is not None:
        values["cfg_scale"] = args.cfg
    if args.negative is not None:
        values["negative_prompt"] = args.negative
    return values


def compose(context, source, args, params):
    import pandas as pd
    from app.backend.server.search_runtime import filter_source_frame, normalize_custom_parquet_frame
    from core.headless_random_prompt_service import HeadlessRandomPromptService
    from core.search_result_model import SearchResultModel

    files = [Path(item).expanduser().resolve() for item in args.parquet]
    if not files:
        files = sorted((source.data_dir / "tags").glob("tags_*.parquet"))
        if not files:
            files = sorted((source.project_root / "data" / "tags").glob("tags_*.parquet"))
    if not files:
        from core.agent_setup import asset_catalog, request_assets
        request_assets(asset_catalog(source), ["tag_archive"], request={"command": args.command})
    sampled = None
    matched = 0
    seen_ids = set()
    for file in files:
        if not file.is_file():
            raise CliError("missing_data", f"Parquet file does not exist: {file}")
        frame = pd.read_parquet(file)
        if "general" not in frame or "rating" not in frame:
            raise CliError("invalid_parquet", "Parquet must contain general and rating columns")
        frame = filter_source_frame(frame, query=args.query, exclude=args.exclude, ratings=set(args.ratings))
        frame = normalize_custom_parquet_frame(frame)
        if "id" in frame:
            frame = frame.loc[~frame["id"].isin(seen_ids)]
            seen_ids.update(frame["id"].tolist())
        if frame.empty:
            continue
        matched += len(frame)
        # Weighted reservoir across files: every matching row has equal chance,
        # while only one parquet shard and one selected row stay in memory.
        if random.randrange(matched) < len(frame):
            sampled = frame.iloc[[random.randrange(len(frame))]].copy()
    if sampled is None:
        raise CliError("no_matches", "No parquet rows match the query and ratings")
    context.search_results = SearchResultModel(sampled)
    context.search_results_snapshot = sampled.copy()
    result = HeadlessRandomPromptService(context).generate(
        active_ratings=set(args.ratings), overrides={**params, "auto_generate": False,
                                                    "prompt_fixed": False, "wildcard_standalone": False})
    if not result.success:
        raise CliError("composition_failed", result.error)
    row = context.current_source_row
    row_id = row.get("id") if row is not None else None
    return {"prompt": result.prompt, "negative_prompt": context.negative_prompt_text,
            "prompt_run_id": result.prompt_run_id, "matched_rows": matched,
            "source_id": str(row_id) if row_id is not None else None,
            "parquet_files": [str(file) for file in files]}


def preset_summary(store, name, current):
    from core.prompt_engineering_settings import is_randomized_preset_name
    data = store.read_preset_data(name, store.mode()) or {}
    main = data.get("main_settings") or {}
    module = data.get("module_settings") or {}
    randomized = is_randomized_preset_name(name)
    model = main.get("model") or None
    size = (f"{main['width']} x {main['height']}" if main.get("width") and main.get("height")
            else main.get("resolution") or None)
    prefix = None if randomized else bool(str(module.get("pre_prompt") or "").strip())
    postfix = None if randomized else bool(str(module.get("post_prompt") or "").strip())
    def label(value):
        return "dynamic" if value is None else "yes" if value else "no"
    return {"name": name, "is_current": name == current, "model": model, "size": size,
            "has_prefix": prefix, "has_postfix": postfix,
            "summary": f"{'*' if name == current else '-'} {name}: model={model or 'inherited'}, size={size or 'inherited'}, prefix={label(prefix)}, postfix={label(postfix)}"}


def generation_cost(context, params, mode):
    if mode != "NAI":
        return {"applicable": False, "reason": "Anlas applies only to NAI"}
    from core.nai_anlas_cost import estimate_anlas_cost
    from core.nai_free_usage import is_free_generation
    return {"applicable": True, "unit": "Anlas", "estimated": True,
            "anlas": estimate_anlas_cost(context, params),
            "anlas_if_paid": estimate_anlas_cost(context, params, ignore_free=True),
            "meets_free_conditions": is_free_generation(context, params),
            "account_access_verified": False, "quota_verified": False,
            "note": "Local estimate only. Zero requires eligible Opus access and available free usage; otherwise anlas_if_paid applies. Actual provider billing may differ."}


def execute(context, source, args):
    from core.prompt_engineering_settings import get_prompt_engineering_store
    store = get_prompt_engineering_store(context)
    if args.command == "auth":
        return {"providers": {mode: {"configured": bool(context.secure_token_manager.get_token(key))}
                              for mode, key in (("NAI", "nai_token"), ("WEBUI", "webui_url"), ("COMFYUI", "comfyui_url"))},
                "user_data": str(source.user_root)}
    if args.command == "presets":
        current = store.state()["current_preset"]
        if args.name:
            selected = select_preset(context, args.name)
            return {"mode": args.mode, "preset": selected, "current_preset": current,
                    **preset_summary(store, selected, current), "data": store.read_preset_data(selected, store.mode())}
        names = store.preset_options()
        return {"mode": args.mode, "current_preset": current, "presets": names,
                "items": [preset_summary(store, name, current) for name in names],
                "selection_help": "Omit --preset to use the user's current preset; only override settings you have a reason to change."}
    if args.command == "tags":
        from app.backend.server.autocomplete_commands import search_kr_tags
        rows = search_kr_tags(context, args.query, limit=args.limit)
        if not getattr(context, "kr_tags_raw", None):
            from core.agent_setup import SetupRequired, asset_catalog
            raise SetupRequired("asset_setup_required", "Bundled tag dictionaries are unavailable. Inspect the catalog and restore missing bundle files; preview packs do not replace dictionaries.",
                                {"requires_user_input": True, "catalog": asset_catalog(source),
                                 "request": {"command": "tags", "query": args.query}, "submitted": False})
        return {"query": args.query, "tags": rows}
    if args.random_seed is not None:
        import numpy as np
        random.seed(args.random_seed)
        np.random.seed(args.random_seed % (2**32))
    selected = select_preset(context, args.preset)
    if args.command == "generate" and args.mode == "NAI":
        from core.agent_setup import SetupRequired, model_catalog, resolve_model
        saved = store.read_preset_data(selected, store.mode()) or {}
        # A generated default preset is not a user's model choice. Existing saved
        # presets and explicit --preset/--model remain authoritative.
        persisted = any((base / "presets" / args.mode / (selected + ".json")).is_file()
                        for base in (source.save_dir,))
        chosen = args.model or (saved.get("main_settings", {}).get("model") if args.preset or persisted else None)
        if not chosen:
            raise SetupRequired("model_selection_required", "Choose a model before generating in a fresh environment.",
                                {"requires_user_input": True, "catalog": model_catalog(source)})
        args.model = resolve_model(source, chosen)
    params = overrides(args)
    if args.command == "random" or args.random:
        result = compose(context, source, args, params)
    else:
        result = {"prompt": args.prompt, "negative_prompt": (
            args.negative if args.negative is not None else context.negative_prompt_text)}
    result.update({"mode": args.mode, "preset": selected})
    if args.command == "random":
        return result
    from core.headless_generation_service import HeadlessGenerationService
    service = HeadlessGenerationService(context)
    dispatch = service.enqueue_remote_request({"prompt": result["prompt"],
        "negative_prompt": result["negative_prompt"], "prompt_run_id": result.get("prompt_run_id", ""),
        "overrides": params}, enqueue=False)
    if not dispatch.ok:
        raise CliError("generation_blocked", dispatch.blocked_reason)
    result["request_id"] = dispatch.request_id
    result["parameters"] = dispatch.websocket_payload()["params"]
    result["negative_prompt"] = dispatch.request.params.get("negative_prompt", "")
    if args.dry_run:
        return {**result, "executed": False, "cost": generation_cost(context, dispatch.request.params, args.mode)}
    if not context.headless_generation_execute_enabled:
        raise CliError("generation_disabled", "Generation execution is disabled by the environment")
    target = Path(args.output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before any paid call, and never truncate an existing image.
    output = target.open("xb")
    reservation = os.fstat(output.fileno())
    try:
        with output:
            stored = service.execute_request(dispatch.request)
            from core.result_image_payload_service import history_item_png_payload
            png, _ = history_item_png_payload(stored.item)
            output.write(png)
    except BaseException:
        # Only remove the empty reservation created by this invocation. A partial
        # image is retained for recovery if disk writing failed after generation.
        try:
            current = target.stat()
            if (current.st_size == 0 and current.st_ino == reservation.st_ino
                    and current.st_dev == reservation.st_dev):
                target.unlink()
        except OSError:
            pass
        raise
    executed = stored.item.generation_params
    for key in result["parameters"]:
        if key in executed:
            result["parameters"][key] = executed[key]
    result["prompt"] = executed.get("input", result["prompt"])
    result["negative_prompt"] = executed.get("negative_prompt", result["negative_prompt"])
    return {**result, "executed": True, "output": str(target), "bytes": len(png),
            "width": stored.item.image.width, "height": stored.item.image.height}


def redact(value, secrets):
    if isinstance(value, dict):
        return {key: redact(item, secrets) for key, item in value.items()
                if str(key).lower() not in {"credential", "token", "nai_token", "authorization", "_key"}}
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        from core.agent_protocol import mask_url_credentials
        for secret in sorted((s for s in secrets if isinstance(s, str) and len(s) >= 4), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = mask_url_credentials(value)
    return value


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    secrets: list[str] = []
    from core.agent_client import AgentCallError
    from core.agent_setup import SetupRequired
    try:
        args = parse_args(argv)
        validate(args)
        # Legacy services print diagnostics, including provider errors. Keep them
        # out of both the JSON protocol and stderr; only return sanitized errors.
        with open(os.devnull, "w", encoding="utf-8") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
            if args.command in {"models", "assets"}:
                from core.agent_setup import source_paths, model_catalog, asset_catalog, install_asset
                source = source_paths(args)
                if args.command == "models":
                    result = model_catalog(source, args.mode)
                elif args.action == "list":
                    result = asset_catalog(source)
                else:
                    result = install_asset(source, args.item, args.approve_download)
            elif args.command in {"capabilities", "call", "batch"}:
                from core.agent_client import run_discovery_command
                result = run_discovery_command(args, Path(__file__).resolve().parents[1], secrets)
            else:
                with isolated_session(args, secrets) as (context, source):
                    result = execute(context, source, args)
        payload, code = {"ok": True, "schema_version": 1, "result": result}, 0
    except AgentCallError as exc:
        payload, code = {"ok": False, "schema_version": 1, "error": {
            "code": exc.code, "message": str(exc), "details": exc.details}}, 2
    except SetupRequired as exc:
        payload, code = {"ok": False, "schema_version": 1, "error": {
            "code": exc.code, "message": str(exc), "details": exc.details}}, 2
    except CliError as exc:
        payload, code = {"ok": False, "schema_version": 1, "error": {"code": exc.code, "message": str(exc)}}, 2
    except KeyboardInterrupt:
        payload, code = {"ok": False, "schema_version": 1, "error": {"code": "interrupted", "message": "Interrupted; inspect the operation state before retrying. Work may already have started."}}, 130
    except Exception as exc:
        payload, code = {"ok": False, "schema_version": 1, "error": {"code": "execution_failed", "message": str(exc), "type": type(exc).__name__}}, 1
    try:
        serialized = json.dumps(redact(payload, secrets), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        serialized = json.dumps({"ok": False, "schema_version": 1, "error": {
            "code": "serialization_failed", "message": "Service result is not valid JSON"}})
        code = 1
    print(serialized)
    return code
