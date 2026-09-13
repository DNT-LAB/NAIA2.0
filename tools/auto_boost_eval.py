"""Auto Boost source -> production prompt -> wire request -> raw/final audit.

prepare: stream a reproducible, screened parquet sample.
audit: capture using real WebSessionContext/random/Auto Boost paths; optional
       reviewed, non-explicit live cases use a PRIVATE CPU Ollama process.
compare: join independent references by case ID AND exact boost-input digest.
No image generation, model downloads, user-server changes, or runtime patches.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import html
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.auto_boost_eval_dataset import (digest, file_digest, live_candidate, prepare_dataset,
                                           screen_row, normalize, EXPLICIT_OR_SUGGESTIVE)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


class CaptureOnly(RuntimeError):
    pass


def stop_private_process(process):
    """Stop our Popen tree before its parent; Windows terminate() orphans runners.

    Never target an image name or discover/kill other servers. An already exited
    parent cannot be used to prove child ownership; report that case explicitly.
    """
    if process is None:
        return {"method": "not_started", "tree_stopped": True}
    if process.poll() is not None:
        return {"method": "parent_already_exited", "tree_stopped": False}
    if sys.platform == "win32":
        completed = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if completed.returncode != 0:
            raise RuntimeError(f"Private process tree cleanup failed for PID {process.pid}: "
                               f"{completed.stderr.decode(errors='replace').strip()}")
        process.wait(timeout=5)
        return {"method": "taskkill_owned_tree", "root_pid": process.pid,
                "tree_stopped": True, "returncode": completed.returncode}
    # Private servers start a dedicated session on POSIX; kill only that group.
    import signal
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    return {"method": "private_process_group", "root_pid": process.pid,
            "tree_stopped": True}


@contextmanager
def private_ollama(output, model, executable=None):
    """Launch only the installed runtime and model; own/stop only our child."""
    import requests
    executable = executable or shutil.which("ollama")
    if not executable or not Path(executable).is_file():
        raise ValueError("Installed Ollama binary required; no installation will be attempted")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{port}", CUDA_VISIBLE_DEVICES="-1",
               ROCR_VISIBLE_DEVICES="-1", GGML_VK_VISIBLE_DEVICES="-1", OLLAMA_VULKAN="0",
               OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1")
    process = None
    metadata = {"endpoint": endpoint, "device": "cpu", "model": model}
    try:
        with (output / "ollama-server.log").open("wb") as log:
            process = subprocess.Popen([executable, "serve"], env=env, cwd=output, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                start_new_session=sys.platform != "win32")
            metadata["private_server_pid"] = process.pid
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Private Ollama server exited")
                try:
                    response = requests.get(endpoint + "/api/tags", timeout=1)
                    response.raise_for_status()
                    installed = response.json()
                    break
                except requests.RequestException:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.2)
            if model not in {m.get("name") for m in installed.get("models", [])}:
                raise ValueError("Requested model is not installed; no download attempted")
            metadata["version"] = requests.get(endpoint + "/api/version", timeout=5).json()
            # /api/show is read-only. Preserve actual template/system provenance.
            metadata["model_info"] = requests.post(endpoint + "/api/show", json={"model": model}, timeout=10).json()
            yield endpoint, metadata
            metadata["ps"] = requests.get(endpoint + "/api/ps", timeout=5).json()
    finally:
        try:
            metadata["cleanup"] = stop_private_process(process)
        except Exception as exc:
            metadata["cleanup"] = {"tree_stopped": False, "error": str(exc)}
            raise
        finally:
            metadata["private_server_stopped"] = process is None or process.poll() is not None
            write_json(output / "runtime.json", metadata)


def make_context(output, endpoint, model, transport, api_mode, settings):
    # Must be set before constructing any service; never read the user's saves.
    user_data = output / "user-data"
    os.environ.update(NAIA_USER_DATA_DIR=str(user_data), NAIA_DISABLE_LEGACY_SAVE_FALLBACK="1",
                      NAIA_HEADLESS_DISABLE_GENERATION_EXECUTION="1")
    from core.web_session_context import WebSessionContext, InMemoryTokenManager
    from core.ai_backend import AIBackend, ExecutionProfile
    from core.ollama_assistant_service import OllamaAssistantService
    from core.prompt_engineering_settings import save_ollama_boost_settings
    context = WebSessionContext(repo_root=ROOT, token_manager=InMemoryTokenManager({}), current_api_mode=api_mode)
    context.headless_generation_execute_enabled = False
    backend = AIBackend(endpoint, profile=ExecutionProfile("cpu"), http_post=transport)
    context.ollama_assistant_service = OllamaAssistantService(base_url=endpoint, default_model=model, backend=backend)
    context.ollama_auto_boost = True
    save_ollama_boost_settings(settings, save_root=context.runtime_paths.save_dir)
    return context


def stage_recorder(original, name, stages):
    def observe(*args, **kwargs):
        before = deepcopy(args[0])
        result = original(*args, **kwargs)
        stages.append({"stage": name, "before": before, "after": deepcopy(result)})
        return result
    return observe


def run_case(context, row, state, *, live=False, replay=None):
    """Real Random source replay + real apply function. Spies do not alter outputs."""
    from core.headless_random_prompt_service import HeadlessRandomPromptService
    from app.backend.server import generation_commands as commands, ollama_routes as routes
    from core import scene_boost
    reasons = screen_row(row)
    if reasons:
        return {"case_id": row.get("case_id"), "state": "excluded", "reasons": reasons}
    state.clear()
    state.update(live=bool(live and live_candidate(row)), calls=[], replay=replay)
    started = time.perf_counter()
    result = HeadlessRandomPromptService(context).generate_from_source_row(
        row, active_ratings={row["rating"]}, update_context=False, source="boost_eval",
        overrides={"auto_generate": False, "auto_fit_resolution": False},
        random_request_id=row["case_id"])
    record = {"case_id": row["case_id"], "source_rating": row["rating"], "source_id": row.get("id"),
              "sample_cohort": row.get("sample_cohort", "unspecified"),
              "source_general": row["general"], "source_general_sha256": digest(row["general"]),
              "source_file": row.get("source_file"), "source_row_index": row.get("source_row_index"),
              "random_seconds": round(time.perf_counter() - started, 4), "random_success": result.success}
    if not result.success:
        return dict(record, state="random_error", error=result.error)
    record["prompt_before"] = result.prompt
    record["settings"] = routes.ollama_boost_settings(context)
    record["settings_sha256"] = digest(json.dumps(record["settings"], sort_keys=True, ensure_ascii=False))
    record["boost_input"] = commands._build_boost_input(result, record["settings"]) or result.prompt
    record["boost_input_sha256"] = digest(record["boost_input"])
    source_tags = {normalize(t) for t in row["general"].split(",") if normalize(t)}
    boost_tags = {normalize(t) for t in record["boost_input"].split(",") if normalize(t)}
    record["source_tags_absent_from_boost_input"] = sorted(source_tags - boost_tags)
    # Recheck the post-processing input too: never rely only on archive rating.
    if EXPLICIT_OR_SUGGESTIVE.search(normalize(record["boost_input"])):
        state["live"] = False
    stages = []
    boost_results = []
    original = routes.scene_boost_prompt
    def observe_boost(*args, **kwargs):
        value = original(*args, **kwargs)
        boost_results.append(deepcopy(value))
        return value
    started = time.perf_counter()
    with ExitStack() as stack:
        stack.enter_context(patch.object(routes, "scene_boost_prompt", observe_boost))
        for name in ("filter_descriptions", "_drop_if_all_generic", "filter_composition"):
            stack.enter_context(patch.object(scene_boost, name, stage_recorder(getattr(scene_boost, name), name, stages)))
        record["applied"] = asyncio.run(commands.apply_ollama_auto_boost(context, result))
    record.update(boost_seconds=round(time.perf_counter() - started, 4), calls=deepcopy(state["calls"]),
                  filter_stages=stages, boost_result=boost_results[-1] if boost_results else None,
                  prompt_after=result.prompt)
    actual = [call for call in record["calls"] if call.get("executed")]
    replayed = any(call.get("replayed") for call in record["calls"])
    record["state"] = ("live" if actual else "captured_only") if record["calls"] else "no_model_request"
    if replayed:
        record["state"] = "replayed"
    elif state.get("replay_error"):
        record["state"] = "replay_error"
    if actual and (not record["boost_result"] or not record["boost_result"].get("ok")):
        record["state"] = "model_error"
    if record["state"] == "captured_only":
        # Intercepting the HTTP boundary intentionally terminates the production call.
        # This is NOT a model failure or a successful empty output.
        record["capture_note"] = "No inference executed; production call interrupted after request capture"
    return record


def capture_transport(state):
    def send(url, **kwargs):
        import requests
        payload = deepcopy(kwargs["json"])
        call = {"url": url, "request": payload, "timeout": kwargs.get("timeout"), "executed": False}
        call["request_sha256"] = digest(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        state["calls"].append(call)
        instruction = "\n".join(m.get("content", "") for m in payload.get("messages", []))
        focus = re.search(r"Rating focus \[([gsqe])\]", instruction)
        call["effective_tone_rating"] = focus.group(1) if focus else None
        call["instruction_characters"] = len(instruction)
        replay = state.get("replay")
        if replay is not None:
            if replay.get("request_sha256") != call["request_sha256"]:
                state["replay_error"] = "request_hash_mismatch"
                raise ValueError("Existing response does not match this exact model request")
            from types import SimpleNamespace
            body = deepcopy(replay["response"])
            call.update(replayed=True, response=body, status_code=int(replay.get("status_code", 200)),
                        response_origin=str(replay.get("origin") or "supplied_existing_response"))
            content = (body.get("message") or {}).get("content")
            if content:
                try:
                    call["parsed_model_output"] = json.loads(content)
                except ValueError:
                    call["model_json_invalid"] = True
            return SimpleNamespace(status_code=call["status_code"], json=lambda: body)
        if not state.get("live") or "Rating focus [q]" in instruction or "Rating focus [e]" in instruction:
            raise CaptureOnly("evaluation_capture_only")
        call["executed"] = True
        started = time.perf_counter()
        try:
            response = requests.post(url, **kwargs)
            call["status_code"] = response.status_code
            try:
                call["response"] = response.json()
                content = (call["response"].get("message") or {}).get("content")
                if content:
                    try:
                        call["parsed_model_output"] = json.loads(content)
                    except ValueError:
                        call["model_json_invalid"] = True
            except ValueError:
                call["response_text"] = response.text
            return response
        except Exception as exc:
            call["error"] = str(exc)
            raise
        finally:
            call["http_seconds"] = round(time.perf_counter() - started, 4)
    return send


def summarize(records):
    from collections import Counter
    counts = Counter(r["state"] for r in records)
    live = [r for r in records if r["state"] in {"live", "model_error"}]
    success = [r for r in live if (r.get("boost_result") or {}).get("ok")]
    replays = [r for r in records if r["state"] == "replayed"]
    rating_pairs = Counter(f"{r.get('source_rating')}->{c.get('effective_tone_rating')}"
                           for r in records for c in r.get("calls", []))
    return {"total": len(records), "states": dict(counts), "live_attempted": len(live),
            "live_success": len(success), "applied": sum(bool(r.get("applied")) for r in live),
            "successful_empty_additions": sum(not any((r["boost_result"].get("additions") or {}).values()) for r in success),
            "successful_no_descriptions": sum(not (r["boost_result"].get("additions") or {}).get("descriptions") for r in success),
            "source_to_effective_tone_rating": dict(rating_pairs),
            "replayed": len(replays),
            "replay_success": sum(bool((r.get("boost_result") or {}).get("ok")) for r in replays),
            "scope": "Text and transport diagnostics; no image-quality claim or scalar semantic score"}


def render_report(records, output, references=None):
    references = references or {}
    cards = []
    def block(title, value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, default=str)
        return f"<details><summary>{html.escape(title)}</summary><pre>{html.escape(text)}</pre></details>"
    for row in records:
        key = row["case_id"]
        card = f'<article><h2>{html.escape(key)} · {html.escape(row.get("source_rating", ""))} · {html.escape(row["state"])}</h2>'
        card += block("NAIA source / exact Boost input", {k: row.get(k) for k in ("source_general", "boost_input", "boost_input_sha256", "settings")})
        card += block("Wire request / raw Ollama response", row.get("calls", []))
        card += block("Actual filter stages / final additions", {"stages": row.get("filter_stages"), "result": row.get("boost_result")})
        card += block("Final image prompt before / after", {k: row.get(k) for k in ("prompt_before", "prompt_after")})
        if key in references:
            card += block("Independent reference (not ground truth)", references[key])
        card += '</article>'
        cards.append(card)
    page = '<!doctype html><meta charset="utf-8"><title>NAIA Auto Boost audit</title><style>body{background:#171722;color:#eee;font:16px system-ui;max-width:1200px;margin:32px auto;padding:20px}article{border:1px solid #555;padding:18px;margin:20px 0}summary{cursor:pointer;padding:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#242433;padding:16px}</style><h1>NAIA Auto Boost audit</h1><p>Capture-only ≠ model failure. Metadata screening ≠ verified age/consent. No images generated.</p>'
    page += block("Summary", summarize(records)) + "".join(cards)
    Path(output).write_text(page, encoding="utf-8")


def audit(args):
    import pyarrow.parquet as pq
    from core.ai_backend import MINIMUM_RUNTIME_MODEL
    dataset = args.dataset.resolve()
    manifest = json.loads((dataset.parent / "manifest.json").read_text(encoding="utf-8"))
    if file_digest(dataset) != manifest["dataset_sha256"]:
        raise ValueError("Dataset fingerprint differs from screening manifest")
    rows = pq.read_table(dataset).to_pylist()
    ids = {r["case_id"] for r in rows}
    if len(ids) != len(rows):
        raise ValueError("Duplicate case IDs")
    reviews = {}
    if args.review:
        items = json.loads(args.review.read_text(encoding="utf-8"))["cases"]
        for item in items:
            if item["case_id"] not in ids or item["case_id"] in reviews:
                raise ValueError("Unknown/duplicate reviewed case")
            source = next(r for r in rows if r["case_id"] == item["case_id"])
            if item["source_general_sha256"] != digest(source["general"]):
                raise ValueError("Reviewed input does not match dataset")
            if item.get("nonexplicit_generation_reviewed") is not True or not live_candidate(source):
                raise ValueError("Reviewed live case is not eligible for non-explicit generation")
            reviews[item["case_id"]] = item
    replays = {}
    if args.replay:
        for item in json.loads(args.replay.read_text(encoding="utf-8"))["cases"]:
            if item["case_id"] not in ids or item["case_id"] in replays or item["case_id"] in reviews:
                raise ValueError("Unknown/duplicate replay ID or live/replay overlap")
            if not isinstance(item.get("response"), dict) or not item.get("request_sha256"):
                raise ValueError("Replay requires an existing response object and exact request digest")
            replays[item["case_id"]] = item
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    settings = {"effort": "rich", "nl_weight": 1.5, "allow_scent_style": True,
                "allow_material_style": True, "allow_light_style": False, "emphasize_framing": False,
                "include_prefix": False, "include_postfix": False, "include_e621": False}
    if args.settings:
        settings.update(json.loads(args.settings.read_text(encoding="utf-8")))
    model = args.model or MINIMUM_RUNTIME_MODEL
    source_snapshot = {str(path.relative_to(ROOT)): file_digest(path) for path in (
        Path(__file__).resolve(), ROOT / "tools/auto_boost_eval_dataset.py", ROOT / "core/scene_boost.py",
        ROOT / "core/ollama_tag_assist_service.py", ROOT / "app/backend/server/generation_commands.py",
        ROOT / "app/backend/server/ollama_routes.py")}
    state = {}
    records = []
    with ExitStack() as stack:
        endpoint = "http://127.0.0.1:1"
        if reviews:
            endpoint, _ = stack.enter_context(private_ollama(output, model, args.ollama))
        context = make_context(output, endpoint, model, capture_transport(state), args.api_mode, settings)
        for row in rows:
            record = run_case(context, row, state, live=row["case_id"] in reviews, replay=replays.get(row["case_id"]))
            records.append(record)
            with (output / "records.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            print(json.dumps({"case_id": row["case_id"], "rating": row["rating"], "state": record["state"]}), flush=True)
    write_json(output / "summary.json", summarize(records))
    write_json(output / "run.json", {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dataset": str(dataset), "dataset_sha256": file_digest(dataset), "model": model,
        "settings": settings, "api_mode": args.api_mode, "review": reviews,
        "source_file_hashes_at_start": source_snapshot,
        "replayed_case_ids": sorted(replays),
        "path": "WebSessionContext -> generate_from_source_row -> apply_ollama_auto_boost -> scene_boost_prompt -> shared AIBackend",
        "limits": "Fresh recommended preset; not user's saved settings or Auto Gen prefetch path. CPU live cases manually reviewed; no downloads or images."})
    render_report(records, output / "report.html")
    return summarize(records)


def validate_case_fingerprints(record):
    if digest(record["boost_input"]) != record["boost_input_sha256"]:
        raise ValueError("Recorded input fingerprint is stale")
    if digest(json.dumps(record["settings"], sort_keys=True, ensure_ascii=False)) != record["settings_sha256"]:
        raise ValueError("Recorded settings fingerprint is stale")


def compare(records, references):
    index = {r["case_id"]: r for r in records}
    if len(index) != len(records):
        raise ValueError("Duplicate audit case IDs")
    seen = set()
    comparisons = []
    for ref in references:
        key = ref["case_id"]
        if key in seen or key not in index:
            raise ValueError("Unknown or duplicate reference ID")
        seen.add(key)
        row = index[key]
        validate_case_fingerprints(row)
        if ref["boost_input_sha256"] != row.get("boost_input_sha256"):
            raise ValueError("Reference input differs from exact Ollama boost input")
        if ref["settings_sha256"] != row.get("settings_sha256"):
            raise ValueError("Reference settings differ from the Ollama case")
        if not isinstance(ref.get("descriptions"), list) or any(not isinstance(d, str) for d in ref["descriptions"]):
            raise ValueError("Reference descriptions must be an array of strings")
        comparisons.append({"case_id": key, "input_hash_matches": True, "state": row["state"],
                            "reference": ref, "ollama_final": (row.get("boost_result") or {}).get("additions"),
                            "boost_seconds": row.get("boost_seconds"), "review": None})
    return {"pairs": comparisons, "unpaired_case_ids": sorted(set(index) - seen),
            "limits": "Matched inputs, not automatic semantic scoring; independent agent is not ground truth or holdout."}


def export_review(records, rows):
    """Blind reference packet: no model output, model identity, or filter result."""
    source = {r["case_id"]: r for r in rows}
    cases = []
    for record in records:
        row = source.get(record["case_id"])
        if not row or not live_candidate(row) or "boost_input" not in record:
            continue
        validate_case_fingerprints(record)
        if digest(row["general"]) != record["source_general_sha256"]:
            raise ValueError("Source changed since capture")
        processed = dict(row, general=record["boost_input"])
        if not live_candidate(processed):
            continue
        calls = record.get("calls", [])
        if any(c.get("effective_tone_rating") not in {"g", "s"} for c in calls) or not calls:
            continue
        cases.append({"case_id": record["case_id"], "rating": record["source_rating"],
                      "input_prompt": record["boost_input"], "boost_input_sha256": record["boost_input_sha256"],
                      "settings": record["settings"], "settings_sha256": record["settings_sha256"],
                      "source_general_sha256": record["source_general_sha256"],
                      "character_slots": None, "eligibility": "metadata_screened_requires_individual_review"})
    return {"cases": cases, "limits": "Candidate packet only; individual review still required. No model output provided."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--source-dir", type=Path, default=ROOT / "data/tags")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--per-rating", type=int, default=6)
    prep.add_argument("--shards", type=int, default=4)
    prep.add_argument("--seed", type=int, default=20260907)
    prep.add_argument("--min-tags", type=int, default=8)
    prep.add_argument("--max-tags", type=int, default=60)
    prep.add_argument("--review-per-rating", type=int, default=4, help="Separate non-explicit G/S review cohort; not an unbiased sample")
    run = commands.add_parser("audit")
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--review", type=Path, help="Individually reviewed non-explicit case IDs and source digests")
    run.add_argument("--replay", type=Path, help="Inspect supplied existing responses with exact request hashes; no new generation")
    run.add_argument("--settings", type=Path)
    run.add_argument("--model")
    run.add_argument("--ollama")
    run.add_argument("--api-mode", choices=["NAI", "WEBUI", "COMFYUI"], default="NAI")
    join = commands.add_parser("compare")
    join.add_argument("--records", type=Path, required=True)
    join.add_argument("--references", type=Path, required=True)
    join.add_argument("--output", type=Path, required=True)
    export = commands.add_parser("export-review")
    export.add_argument("--records", type=Path, required=True)
    export.add_argument("--dataset", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        value = prepare_dataset(args.source_dir, args.output, per_rating=args.per_rating, shards=args.shards,
                                seed=args.seed, min_tags=args.min_tags, max_tags=args.max_tags,
                                review_per_rating=args.review_per_rating)
    elif args.command == "audit":
        value = audit(args)
    elif args.command == "export-review":
        import pyarrow.parquet as pq
        records = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines() if line.strip()]
        value = export_review(records, pq.read_table(args.dataset).to_pylist())
        if args.output.exists():
            raise ValueError("Preserve existing review packets; use a new output path")
        write_json(args.output, value)
    else:
        records = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines() if line.strip()]
        references = json.loads(args.references.read_text(encoding="utf-8"))["cases"]
        value = compare(records, references)
        args.output.mkdir(parents=True, exist_ok=False)
        write_json(args.output / "comparison.json", value)
        render_report(records, args.output / "report.html", {r["case_id"]: r for r in references})
    print(json.dumps(value, ensure_ascii=False, indent=2))
    if args.command == "audit" and any(value.get("states", {}).get(s, 0) for s in ("model_error", "random_error", "replay_error")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
