"""NovelAI UI model keys and outbound API model names."""

from __future__ import annotations

from typing import Any


DEFAULT_NAI_API_MODEL = "nai-diffusion-4-5-full"

# Remote Web exposes the short aliases NAID4.5 and NAID4 alongside canonical
# F/C keys. Keep every outbound NAI request on one mapping so generation and
# encode-vibe cannot silently choose different model families.
NAI_API_MODEL_BY_KEY = {
    "NAID4.5F": "nai-diffusion-4-5-full",
    "NAID4.5C": "nai-diffusion-4-5-curated",
    "NAID4.5": "nai-diffusion-4-5-full",
    "NAID4.0F": "nai-diffusion-4-full",
    "NAID4.0C": "nai-diffusion-4-curated-preview",
    "NAID4": "nai-diffusion-4-full",
    "NAID3": "nai-diffusion-3",
}


def resolve_nai_api_model(model_key: Any) -> str:
    """Resolve a NAIA/UI model key, preserving the established 4.5 fallback."""
    normalized = str(model_key or "").strip().upper()
    return NAI_API_MODEL_BY_KEY.get(normalized, DEFAULT_NAI_API_MODEL)
