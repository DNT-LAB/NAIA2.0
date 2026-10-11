"""Opt-in local Assist retrieval pack. Similarity supplies candidates, never tag authority.

NAIA_ASSIST_RAG_DIR points to a verified documents.jsonl + embeddings/manifest.json
pack. No download, settings mutation, or dependency on the research HTTP server.
The embedding model has its own CPU process and releases it after idle time.
"""
from __future__ import annotations

import hashlib
import atexit
import json
from pathlib import Path
import time
import urllib.request

import numpy as np

from core.llama_runtime import LlamaServerRuntime

QUERY_PREFIX = "task: search result | query: "
MODEL_FILE = "embeddinggemma-300M-qat-Q4_0.gguf"
MIN_SCORE = 0.58  # Conservative experimental cutoff; not a probability or acceptance score.


def _verify(path: Path, digest: str) -> None:
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if not digest or actual != digest:
        raise ValueError(f"RAG asset checksum mismatch: {path.name}")


class EmbeddingRuntime(LlamaServerRuntime):
    def server_args(self, port: int) -> list[str]:
        return [str(self.engine_path), "-m", str(self.model_path),
                "--host", "127.0.0.1", "--port", str(port), "--embedding",
                "--pooling", "mean", "--parallel", "1", "-c", "2048",
                "-b", "2048", "-ub", "2048", "-t", str(self.threads), "-ngl", "0"]

    def embed(self, query: str, timeout: float = 30.0) -> np.ndarray:
        deadline = time.monotonic() + timeout
        if not self._slot.acquire(timeout=timeout):
            raise TimeoutError("RAG embedding slot busy")
        try:
            self._new_call()
            self._cancel_idle_timer()
            port = self._ensure(deadline)
            body = json.dumps({"input": [QUERY_PREFIX + query], "encoding_format": "float"}).encode()
            request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/embeddings", data=body,
                                             headers={"Content-Type": "application/json"})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("RAG embedding startup timeout")
            with urllib.request.urlopen(request, timeout=remaining) as response:
                data = json.load(response)
            rows = data.get("data") or []
            if len(rows) != 1 or rows[0].get("index") != 0:
                raise ValueError("RAG embedding response alignment mismatch")
            vector = np.asarray(rows[0]["embedding"], dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if vector.shape != (768,) or not np.isfinite(vector).all() or norm < 1e-8:
                raise ValueError("Invalid 768-dimensional query embedding")
            return vector / norm
        except Exception:
            self.stop()
            raise
        finally:
            self._slot.release()
            if self.is_running():
                self._arm_idle_timer()


class RetrievalPack:
    def __init__(self, root: Path, engine: Path, *, log_path: Path | None = None):
        root = Path(root)
        manifest = json.loads((root / "embeddings/manifest.json").read_text(encoding="utf-8"))
        signature = manifest["signature"]
        if not manifest.get("complete") or any(signature.get(k) != v for k, v in
                {"dimensions": 768, "pooling": "mean", "normalization": "L2", "dtype": "float32"}.items()):
            raise ValueError("Unsupported or incomplete RAG pack")
        model = root / "models" / MODEL_FILE
        documents = root / "documents.jsonl"
        _verify(model, signature["model_sha256"])
        _verify(documents, signature["documents_sha256"])
        for filename in ("ids.json", "vectors_768.f32.npy"):
            _verify(root / "embeddings" / filename, manifest["files"][filename]["sha256"])
        ids = json.loads((root / "embeddings/ids.json").read_text(encoding="utf-8"))
        with documents.open(encoding="utf-8") as handle:
            self.records = [json.loads(line) for line in handle]
        if ids != [row["id"] for row in self.records] or len(set(ids)) != len(ids):
            raise ValueError("RAG document/vector ID alignment mismatch")
        self.vectors = np.load(root / "embeddings/vectors_768.f32.npy", mmap_mode="r", allow_pickle=False)
        if self.vectors.shape != (signature["records"], 768) or len(ids) != len(self.vectors) \
                or self.vectors.dtype != np.float32:
            raise ValueError("RAG vector shape mismatch")
        for offset in range(0, len(ids), 4096):
            block = self.vectors[offset:offset + 4096]
            if not np.isfinite(block).all() or not np.allclose(np.linalg.norm(block, axis=1), 1, atol=1e-4):
                raise ValueError("RAG vectors must be finite and normalized")
        # Artist, copyright and character names have their own approved-name lanes.
        self.eligible = np.array([i for i, r in enumerate(self.records)
                                  if r.get("category", "") in ("", "general", "e621")
                                  and enriched(r)], dtype=np.int64)
        self.runtime = EmbeddingRuntime(engine, model, use_gpu=False, idle_seconds=60, log_path=log_path)
        atexit.register(self.runtime.stop)
        self.signature = signature

    def search(self, query: str, limit: int = 48, min_score: float = MIN_SCORE) -> list[dict]:
        query = str(query).strip()
        # Conservative UTF-8 upper bound prevents silent context truncation.
        if not query or len((QUERY_PREFIX + query).encode("utf-8")) + 8 > 2048:
            return []
        vector = self.runtime.embed(query)
        scores = self.vectors @ vector
        ranked = self.eligible[np.argsort(-scores[self.eligible], kind="stable")[:limit]]
        return [{"tag": self.records[i]["tag"], "score": round(float(scores[i]), 6),
                 "description": self.records[i]["embedding_text"].split(" | text: ", 1)[-1],
                 "id": self.records[i]["id"]} for i in ranked if scores[i] >= min_score]


def enriched(record: dict) -> bool:
    body = record.get("embedding_text", "").split(" | text: ", 1)[-1]
    return body.startswith(("Description:", "Keywords:"))
