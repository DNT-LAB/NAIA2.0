"""Curated Gemma4 runtime registration through Ollama's API (no local blob edits).

Keep the downloaded model and its projector intact. ``from`` shares their layers;
importing GGUF files again can rewrite several GB of weights. A runtime is usable
only after /api/show proves thinking support and identical FROM blob digests.
"""
from __future__ import annotations

import re
RUNTIME_MODELS = {
    "hf.co/HauhauCS/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive:IQ3_M":
        "naia-gemma4-e2b-iq3_m:think",
    "hf.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive:Q4_K_M":
        "naia-gemma4-e4b-q4_k_m:think",
    "hf.co/HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced:IQ4_XS":
        "naia-gemma4-26b-iq4_xs:think",
}


def source_model(model: str) -> str:
    return next((source for source, runtime in RUNTIME_MODELS.items()
                 if runtime == model), model)


def same_runtime_spec(source: dict, runtime: dict) -> bool:
    def blobs(info):
        return re.findall(r"(?mi)^FROM\s+.*?sha256[:-]([a-f0-9]{64})\b",
                          str(info.get("modelfile") or ""))
    caps = set(runtime.get("capabilities") or [])
    return ("thinking" in caps
            and set(source.get("capabilities") or []).issubset(caps)
            and bool(blobs(source)) and blobs(source) == blobs(runtime)
            and (runtime.get("details") or {}).get("family") == "gemma4")


class OllamaModelSpec:
    def __init__(self, http_get, http_post):
        self.get = http_get
        self.post = http_post
        self._cache: dict[tuple, dict] = {}

    def clear(self):
        self._cache.clear()

    def show(self, model: str) -> dict:
        response = self.post("/api/show", {"model": model}, timeout=(5, 15))
        if response.status_code != 200:
            raise RuntimeError(f"모델 사양 확인 실패: {model} (HTTP {response.status_code})")
        return response.json() or {}

    def ready_models(self, records: list[dict], *, fresh=False) -> dict[str, str]:
        if fresh:
            self.clear()
        by_name = {r.get("name"): r for r in records if isinstance(r, dict)}
        ready = {}
        for source, runtime in RUNTIME_MODELS.items():
            if source not in by_name:
                continue
            key = (source, by_name[source].get("digest"), by_name.get(runtime, {}).get("digest"))
            try:
                cached = self._cache.get(key)
                if cached is None:
                    source_info = self.show(source)
                    if "thinking" in (source_info.get("capabilities") or []):
                        cached = {"model": source}
                    else:
                        cached = {"model": runtime if runtime in by_name and
                                  same_runtime_spec(source_info, self.show(runtime)) else ""}
                    # A replaced source or runtime digest invalidates the old verdict.
                    self._cache = {k: v for k, v in self._cache.items() if k[0] != source}
                    self._cache[key] = cached
                if cached["model"]:
                    ready[source] = cached["model"]
            except Exception:
                # A transient show failure must not select an unverified runtime.
                continue
        return ready

    def prepare(self, model: str) -> str:
        source = source_model(model)
        runtime = RUNTIME_MODELS.get(source)
        if not runtime:
            return model
        before = self.show(source)
        if (before.get("details") or {}).get("family") != "gemma4":
            raise RuntimeError("다운로드한 모델이 Gemma4가 아니므로 사양을 변경하지 않았습니다.")
        if "thinking" in (before.get("capabilities") or []):
            return source
        try:
            if same_runtime_spec(before, self.show(runtime)):
                return runtime
        except Exception:
            pass
        version_response = self.get("/api/version", timeout=5)
        version = str((version_response.json() or {}).get("version") or "")
        parsed = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
        if version_response.status_code != 200 or not parsed or tuple(map(int, parsed.groups())) < (0, 30, 6):
            raise RuntimeError("think 사양 준비에는 Ollama 0.30.6 이상이 필요합니다. 업데이트 후 다시 준비하세요.")
        response = self.post("/api/create", {
            "model": runtime, "from": source, "renderer": "gemma4", "parser": "gemma4",
            "stream": False,
            "parameters": {"stop": ["<turn|>"], "temperature": 1.0,
                           "top_k": 64, "top_p": 0.95, "num_ctx": 8192},
        }, timeout=(5, 180))
        result = response.json() or {}
        if response.status_code != 200 or result.get("status") != "success":
            raise RuntimeError(str(result.get("error") or "think 사양 등록 실패"))
        if not same_runtime_spec(before, self.show(runtime)):
            raise RuntimeError("think 사양 검증 실패: 원본 가중치·이미지/오디오 지원을 확인할 수 없습니다.")
        self.clear()
        return runtime
