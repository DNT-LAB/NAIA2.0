"""앱 소유 llama-server 가 돌릴 수 있는 모델 목록 — Boost v2 · Assist v2 가 함께 쓴다(사용자 지정 2026-09-26).

기존 Ollama 파이프라인이 쓰던 **그 파일**을 그대로 쓴다: Ollama 가 ``hf.co/HauhauCS/<repo>:<quant>`` 로 받던
Hugging Face HauhauCS 저장소의 같은 양자화 GGUF(해시가 Ollama 저장소의 blob 이름과 같다). 받는 곳은 모델마다
``user-data/save/models/llm/<HF 파일 이름>`` — 업데이트가 지우지 않는 사용자 데이터 쪽이다.

추론 옵션은 HauhauCS 모델 카드의 권장값(= Gemma 공식값)을 따른다 — ``temperature 1.0 · top_p 0.95 · top_k 64``,
``--jinja``, think 끔(``enable_thinking=false``). 세 모델 모두 같아서 ``llama_runtime.SAMPLING`` 한 곳에 둔다.

권장(``recommend``)은 메모리(외장 VRAM · RAM)만 본다 — 화면에 예상 속도는 싣지 않는다(PC 마다 다르다, 사용자 지정
2026-09-26). 참고로 개발 PC(285H · Arc 140T · RTX 5090 Laptop 24GB · RAM 63GB) 실측, 요청 한 번(Assist 라우트 · Boost),
두 번째 실행부터:

    RTX 5090   E2B 1.4 · 1.3초   E4B 1.3 · 1.9초   26B 1.8 · 2.2초(로드 19초)
    CPU        E2B 12 · 12초     E4B 18 · 20초     26B 22 · 21초(MoE 라 E4B 와 비슷하다)

처음 쓰는 모델 · 장치는 셰이더 준비로 첫 요청에 수십 초가 붙는다(5090: E2B 34초 · 26B 42초) — 받은 직후 뒤에서
태운다(``boost_v2_service.prime_runtime``). 자세한 수치는 ``docs/BOOST_V2_LLAMACPP_2026_09_23.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LlamaModel:
    id: str
    label: str
    repo: str
    revision: str
    file: str
    size: int
    sha256: str
    quant: str
    license: str
    note: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.file}"

    @property
    def ollama_name(self) -> str:
        """기존 Ollama 파이프라인이 받던 이름(core/ollama_model_spec.RUNTIME_MODELS 의 키)과 같다."""
        return f"hf.co/{self.repo}:{self.quant}"

    @property
    def size_gb(self) -> float:
        return round(self.size / 1e9, 1)


MODELS: tuple[LlamaModel, ...] = (
    LlamaModel(
        id="e2b", label="Gemma 4 E2B", repo="HauhauCS/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive",
        revision="da8593c3e407afcd3e7da94ff2d69d77e2a28a48",
        file="Gemma-4-E2B-Uncensored-HauhauCS-Aggressive-IQ3_M.gguf", size=3_134_964_672,
        sha256="0796d58372742ef8ddc76dd64cd2fde217b7ef32e3dc58e10873253e569cad6b", quant="IQ3_M",
        license="Gemma", note="가장 가볍다",
    ),
    LlamaModel(
        id="e4b", label="Gemma 4 E4B", repo="HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive",
        revision="45b6a334b4bcd1d7f37179df58b3b1d66a184e5d",
        file="Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf", size=5_335_285_728,
        sha256="d0027dd3a9128d9323e9f282c8bf010a8526c46477584535991dc1a869b56e96", quant="Q4_K_M",
        license="Gemma", note="E2B 보다 똑똑하다",
    ),
    LlamaModel(
        id="26b", label="Gemma 4 26B-A4B", repo="HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced",
        revision="96c11c22b1128c3c8c655b21557b409f307c557f",
        file="Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf", size=13_917_726_048,
        sha256="61b277f4dde555fc6c04c9024a9580ef8c83f2f19504f3989a15f95684257426", quant="IQ4_XS",
        license="Apache-2.0", note="가장 똑똑하다",
    ),
)
DEFAULT_MODEL_ID = "e2b"
_BY_ID = {model.id: model for model in MODELS}


def model_by_id(model_id: Any) -> LlamaModel:
    """모르는 id 는 기본(E2B)으로."""
    return _BY_ID.get(str(model_id or "").strip().lower(), _BY_ID[DEFAULT_MODEL_ID])


def normalize_model_id(model_id: Any) -> str:
    return model_by_id(model_id).id


def model_path(save_root: str | Path, model_id: Any = None) -> Path:
    return Path(save_root) / "models" / "llm" / model_by_id(model_id).file


# 이 크기 이상의 외장 GPU 면 모델이 VRAM 에 다 올라간다(가중치 + 컨텍스트 8192 + 계산 버퍼, 여유 포함).
# 카드는 표기보다 조금 작게 보고한다(16GB 카드 = 16376 MiB = 15.99 GiB) — 문턱은 표기 크기에서 1GB 뺀 값.
# 모자라면 엔진이 GPU 로 못 떠서 CPU 로 내려온다(llama_runtime — 느려질 뿐 멈추지 않는다).
_DISCRETE_VRAM_GIB = {"e2b": 4, "e4b": 7, "26b": 15}
# CPU · 내장 그래픽으로 돌릴 때 필요한 RAM(가중치 + 앱 여유).
_RAM_GIB = {"e2b": 6, "e4b": 12, "26b": 24}   # 8GB PC 는 7.8GB 로 보인다


def _pick_gpu(gpus: list[dict[str, Any]], gpu_id: Any = None) -> dict[str, Any] | None:
    """GPU 모드에서 쓰일 GPU — 고른 것, 없으면 외장 우선(llama_runtime.choose_device 와 같은 규칙)."""
    if not gpus:
        return None
    for gpu in gpus:
        if gpu_id and gpu.get("id") == gpu_id:
            return gpu
    return next((g for g in gpus if g.get("kind") == "discrete"), gpus[0])


def _fit(fit: str, why: str) -> dict[str, str]:
    return {"fit": fit, "why": why}


def recommend(hardware: dict[str, Any] | None, gpu_id: Any = None) -> dict[str, Any]:
    """이 PC(hardware_summary) 에서 모델마다 [CPU 모드 | GPU 모드] 가 어떤가 — 메모리만 본다.

    fit: "good"(외장 GPU 에 다 올라간다 / 가장 가벼운 E2B) · "ok"(돈다 — 메모리는 된다) · "no"(메모리가 모자라다).
    why 에는 메모리 사실만 싣는다 — 예상 속도는 PC 마다 달라 보이지 않는다(사용자 지정 2026-09-26).
    권장 = 모드마다 "good" 중 가장 큰 것(없으면 E2B). GPU 가 하나도 없으면 GPU 모드는 없다(None).
    """
    hw = hardware or {}
    ram = float(hw.get("ram_gib") or 0)
    gpu = _pick_gpu(list(hw.get("gpus") or []), gpu_id)
    models: dict[str, dict[str, Any]] = {}
    for model in MODELS:
        need_ram = _RAM_GIB[model.id]
        short_ram = bool(ram) and ram < need_ram
        light = model.id == DEFAULT_MODEL_ID
        if short_ram:
            cpu = _fit("no", f"RAM {ram:.0f}GB — {need_ram}GB 이상 필요")
        else:
            cpu = _fit("good" if light else "ok", "")
        if gpu is None:
            on_gpu = None
        elif gpu.get("kind") == "discrete":
            vram = int(gpu.get("vram_mib") or 0) / 1024
            need = _DISCRETE_VRAM_GIB[model.id]
            on_gpu = (_fit("good", f"VRAM {vram:.0f}GB 에 다 올라감") if vram >= need
                      else _fit("ok", f"VRAM {vram:.0f}GB — {need + 1}GB 이상이어야 다 올라감(모자라면 CPU 로 돕니다)"))
        elif short_ram:
            on_gpu = _fit("no", f"RAM {ram:.0f}GB — {need_ram}GB 이상 필요(내장 그래픽은 RAM 을 나눠 씁니다)")
        else:
            on_gpu = _fit("good" if light else "ok", "내장 그래픽(RAM 을 나눠 씁니다)")
        models[model.id] = {"gpu": on_gpu, "cpu": cpu}

    def best(mode: str) -> str:
        good = [m.id for m in MODELS if (models[m.id][mode] or {}).get("fit") == "good"]
        return good[-1] if good else DEFAULT_MODEL_ID

    return {
        "gpu": gpu,
        "recommended": {"gpu": best("gpu") if gpu else None, "cpu": best("cpu")},
        "models": models,
    }


def catalog(save_root: str | Path, hardware: dict[str, Any] | None = None, gpu_id: Any = None) -> list[dict[str, Any]]:
    """화면용 목록 — 설치 여부 · 크기 · 모드별 적합(gpu/cpu: {fit, why}) · 모드별 권장."""
    rec = recommend(hardware, gpu_id)
    out = []
    for model in MODELS:
        path = model_path(save_root, model.id)
        part = path.with_name(path.name + ".part")
        out.append({
            "id": model.id,
            "label": model.label,
            "quant": model.quant,
            "size": model.size,
            "size_gb": model.size_gb,
            "note": model.note,
            "license": model.license,
            "source": model.url,
            "installed": path.is_file(),
            "partial_mb": round(part.stat().st_size / 1048576, 1) if part.is_file() else 0.0,
            "gpu": rec["models"][model.id]["gpu"],
            "cpu": rec["models"][model.id]["cpu"],
            "recommended": {mode: rec["recommended"][mode] == model.id for mode in ("gpu", "cpu")},
        })
    return out


__all__ = ["LlamaModel", "MODELS", "DEFAULT_MODEL_ID", "model_by_id", "normalize_model_id", "model_path",
           "recommend", "catalog"]
