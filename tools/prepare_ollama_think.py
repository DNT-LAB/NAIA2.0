"""Prepare already-downloaded NAIA Gemma4 models without downloading any weights."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.ollama_assistant_service import OllamaAssistantService
from core.ollama_model_spec import RUNTIME_MODELS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--model", choices=list(RUNTIME_MODELS))
    group.add_argument("--all-installed", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    service = OllamaAssistantService(base_url=args.base_url)
    response = service._http_get("/api/tags", timeout=5)
    if response.status_code != 200:
        parser.error("Ollama is not reachable")
    installed = {r["name"] for r in response.json().get("models", [])}
    models = [args.model] if args.model else [m for m in RUNTIME_MODELS if m in installed]
    results = []
    for model in models:
        try:
            if model not in installed:
                raise ValueError("Source model must already be downloaded")
            runtime = service._model_spec.prepare(model)
            info = service._model_spec.show(runtime)
            results.append({"source_model": model, "runtime_model": runtime, "ok": True,
                            "capabilities": info.get("capabilities"), "details": info.get("details")})
        except Exception as exc:
            results.append({"source_model": model, "ok": False, "error": str(exc)})
    report = json.dumps({"results": results}, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report)
    return int(not results or any(not r["ok"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
