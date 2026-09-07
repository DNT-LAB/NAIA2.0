"""Opt-in E2B CPU inference smoke on a private Ollama process, with no downloads.

Uses an installed CLI and existing model storage. Never addresses the user's
running Ollama endpoint. Stops only the child process it started.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.ai_backend import AIBackend, ExecutionProfile, MINIMUM_RUNTIME_MODEL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ollama", default=shutil.which("ollama"))
    parser.add_argument("--models", type=Path, default=Path(os.environ.get("OLLAMA_MODELS", Path.home() / ".ollama/models")))
    args = parser.parse_args()
    if not args.ollama or not Path(args.ollama).is_file() or not args.models.is_dir():
        parser.error("Existing Ollama binary and model directory are required; nothing will be downloaded")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{port}", OLLAMA_MODELS=str(args.models.resolve()),
               CUDA_VISIBLE_DEVICES="-1", ROCR_VISIBLE_DEVICES="-1", GGML_VK_VISIBLE_DEVICES="-1",
               OLLAMA_VULKAN="0", OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_NUM_PARALLEL="1")
    result = {"model": MINIMUM_RUNTIME_MODEL, "device": "cpu", "endpoint": endpoint,
              "scope": "CPU transport/JSON/native-tool smoke, not Chat semantic quality or minimum RAM certification"}
    process = None
    try:
        with (out / "server.log").open("wb") as log:
            process = subprocess.Popen([args.ollama, "serve"], env=env, cwd=out,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                stdout=log, stderr=log)
            b = AIBackend(endpoint, profile=ExecutionProfile("cpu"))
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Private server exited during startup")
                try:
                    tags = b.get("/api/tags", timeout=1).json()
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.2)
            if MINIMUM_RUNTIME_MODEL not in {m["name"] for m in tags.get("models", [])}:
                raise RuntimeError("Verified E2B runtime is not installed; no download was attempted")
            result["server_version"] = b.get("/api/version").json()
            def infer(payload, task):
                started = time.monotonic()
                r = b.post("/api/chat", {"model": MINIMUM_RUNTIME_MODEL, **payload},
                           timeout=(5, 300), task=task)
                r.raise_for_status()
                return r.json(), round(time.monotonic() - started, 3)
            structured, elapsed = infer({"messages": [{"role": "user", "content":
                'Return exactly this JSON object: {"status":"ready"}'}], "think": False,
                "format": {"type": "object", "properties": {"status": {"type": "string", "enum": ["ready"]}},
                           "required": ["status"]}, "options": {"num_predict": 64}}, "assist")
            result["structured"] = {"seconds": elapsed, "valid":
                json.loads(structured["message"]["content"]) == {"status": "ready"}}
            tools = [{"type": "function", "function": {"name": "search_tags",
                "description": "Find an exact dictionary tag.", "parameters": {"type": "object",
                    "properties": {"query": {"type": "string"}}, "required": ["query"]}}}]
            messages = [{"role": "user", "content": "Call search_tags with query blue sky. Use the tool before answering."}]
            native, elapsed = infer({"messages": messages, "tools": tools, "think": True,
                                    "options": {"num_predict": 256}}, "chat")
            calls = native.get("message", {}).get("tool_calls") or []
            result["native_tool"] = {"seconds": elapsed, "valid": any(
                c.get("function", {}).get("name") == "search_tags" and
                c.get("function", {}).get("arguments", {}).get("query") == "blue sky" for c in calls)}
            if result["native_tool"]["valid"]:
                messages.extend([native["message"], {"role": "tool", "tool_name": "search_tags",
                    "content": json.dumps({"tags": ["blue sky"]})}, {"role": "user",
                    "content": "Return the exact tool result as JSON with key tag. Do not call tools again."}])
                final, elapsed = infer({"messages": messages, "think": False,
                    "format": {"type": "object", "properties": {"tag": {"type": "string", "enum": ["blue sky"]}},
                               "required": ["tag"]}, "options": {"num_predict": 64}}, "chat")
                result["tool_feedback"] = {"seconds": elapsed,
                    "valid": json.loads(final["message"]["content"]) == {"tag": "blue sky"}}
            result["ps"] = b.get("/api/ps").json()
            loaded = [m for m in result["ps"].get("models", []) if m.get("name") == MINIMUM_RUNTIME_MODEL]
            result["cpu_only_verified"] = bool(loaded) and all(m.get("size_vram") == 0 for m in loaded)
            # Force a small context and check that source evidence is not silently dropped.
            overflow = b.post("/api/chat", {"model": MINIMUM_RUNTIME_MODEL, "think": False,
                "messages": [{"role": "user", "content": "blue sky " * 2000}],
                "options": {"num_ctx": 512, "num_predict": 8}}, timeout=(5, 60), task="chat")
            overflow_error = str(overflow.json().get("error") or "")
            result["context_overflow"] = {"http_status": overflow.status_code, "error": overflow_error,
                "rejected": overflow.status_code >= 400 and "context" in overflow_error.lower()}
            result["runtime"] = b.status(include_details=True)
            result["ok"] = (result["cpu_only_verified"] and result["structured"]["valid"] and
                            result["native_tool"]["valid"] and result.get("tool_feedback", {}).get("valid", False)
                            and result["context_overflow"]["rejected"])
    except Exception as exc:
        result.update(ok=False, error=str(exc))
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        result["private_server_stopped"] = process is None or process.poll() is not None
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
