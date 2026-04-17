"""Dedicated storage helpers for character asset images."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from utils.image_info import ImageMetadataExtractor


CHARACTER_ASSET_ROOT_DIR = Path("save/character_asset")
CHARACTER_ASSET_IMAGE_DIR = CHARACTER_ASSET_ROOT_DIR / "images"
CHARACTER_ASSET_LEGACY_METADATA_DIR = CHARACTER_ASSET_ROOT_DIR / "metadata"


def ensure_character_asset_storage_dirs() -> None:
    """Ensure the asset storage folders exist."""
    CHARACTER_ASSET_IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def get_legacy_character_asset_metadata_path(file_hash: str) -> Path:
    """Return the legacy metadata JSON path used by previous builds."""
    return CHARACTER_ASSET_LEGACY_METADATA_DIR / f"{file_hash}.json"


def build_character_asset_metadata(
    file_hash: str,
    file_name: str,
    extracted_metadata: Optional[Dict[str, Any]] = None,
    metadata_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the metadata payload stored next to an asset image."""
    extracted_metadata = extracted_metadata or {}

    characters = list(extracted_metadata.get("characters") or [])
    characters_uc = list(extracted_metadata.get("characters_uc") or [])

    metadata = {
        "asset_type": "character_asset",
        "display_mode": "contain",
        "file_hash": file_hash,
        "file_name": file_name,
        "character_prompt": characters[0] if characters else extracted_metadata.get("prompt", ""),
        "character_uc": characters_uc[0] if characters_uc else extracted_metadata.get("uc", ""),
        "source_prompt": extracted_metadata.get("prompt", ""),
        "source_uc": extracted_metadata.get("uc", ""),
    }

    if metadata_overrides:
        metadata.update({key: value for key, value in metadata_overrides.items() if value is not None})

    return metadata


def save_character_asset(
    raw_bytes: Optional[bytes] = None,
    image: Optional[Image.Image] = None,
) -> tuple[Path, Dict[str, Any]]:
    """Save a generated character asset into dedicated storage.

    Only the image itself is persisted. Character prompt recovery relies on
    the NovelAI metadata embedded in the PNG payload.
    """
    if raw_bytes is None and image is None:
        raise ValueError("Either raw_bytes or image must be provided.")

    if raw_bytes is None and image is not None:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        raw_bytes = buffer.getvalue()

    ensure_character_asset_storage_dirs()
    file_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
    image_path = CHARACTER_ASSET_IMAGE_DIR / f"{file_hash}.png"

    if not image_path.exists():
        with open(image_path, "wb") as file:
            file.write(raw_bytes)

    try:
        extracted_metadata = ImageMetadataExtractor.extract_metadata(Image.open(io.BytesIO(raw_bytes)))
    except Exception as exc:
        print(f"Failed to extract character asset metadata: {exc}")
        extracted_metadata = None

    legacy_metadata_path = get_legacy_character_asset_metadata_path(file_hash)
    if legacy_metadata_path.exists():
        try:
            legacy_metadata_path.unlink()
        except Exception as exc:
            print(f"Failed to remove legacy character asset metadata {legacy_metadata_path}: {exc}")

    metadata = build_character_asset_metadata(
        file_hash=file_hash,
        file_name=image_path.name,
        extracted_metadata=extracted_metadata,
    )
    return image_path, metadata


def load_character_asset_metadata(file_hash: str, image_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load asset metadata directly from the saved image."""
    extracted_metadata = None
    if image_path and image_path.exists():
        try:
            extracted_metadata = ImageMetadataExtractor.extract_metadata(image_path)
        except Exception as exc:
            print(f"Failed to rebuild metadata from asset image {image_path}: {exc}")

    return build_character_asset_metadata(
        file_hash=file_hash,
        file_name=image_path.name if image_path else f"{file_hash}.png",
        extracted_metadata=extracted_metadata,
    )
