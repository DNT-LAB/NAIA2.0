"""Dedicated storage helpers for character asset images.

New layout (MVP: character as a group of variations):

```
save/character_asset/
  characters/
    {character_id}/
      primary.png              ← 대표 이미지 (C1 프롬프트/UC 원본)
      variations/
        {hash}.png             ← 의상/자세 바리에이션
  images/                      ← legacy flat layout (자동 마이그레이션 대상)
```

`character_id` is derived from the primary image's SHA-256 prefix (16 chars) —
same scheme the legacy layout used for file names, so migrated entries keep
their identity.
"""

from __future__ import annotations

import hashlib
import io
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from utils.image_info import ImageMetadataExtractor


CHARACTER_ASSET_ROOT_DIR = Path("save/character_asset")
CHARACTER_ASSET_IMAGE_DIR = CHARACTER_ASSET_ROOT_DIR / "images"  # legacy flat
CHARACTER_ASSET_LEGACY_METADATA_DIR = CHARACTER_ASSET_ROOT_DIR / "metadata"
CHARACTER_ASSET_CHARACTERS_DIR = CHARACTER_ASSET_ROOT_DIR / "characters"

PRIMARY_FILE_NAME = "primary.png"
VARIATIONS_DIR_NAME = "variations"


@dataclass(frozen=True)
class CharacterRecord:
    """A single character entry on disk."""

    character_id: str
    primary_path: Path
    variations_dir: Path
    variation_count: int
    mtime: float


def ensure_character_asset_storage_dirs() -> None:
    """Ensure the asset storage folders exist."""
    CHARACTER_ASSET_CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    # Keep legacy dir around for compatibility (migration reads from it).
    CHARACTER_ASSET_IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def get_legacy_character_asset_metadata_path(file_hash: str) -> Path:
    """Return the legacy metadata JSON path used by previous builds."""
    return CHARACTER_ASSET_LEGACY_METADATA_DIR / f"{file_hash}.json"


def get_character_dir(character_id: str) -> Path:
    return CHARACTER_ASSET_CHARACTERS_DIR / character_id


def get_character_primary_path(character_id: str) -> Path:
    return get_character_dir(character_id) / PRIMARY_FILE_NAME


def get_character_variations_dir(character_id: str) -> Path:
    return get_character_dir(character_id) / VARIATIONS_DIR_NAME


def _compute_hash_prefix(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()[:16]


def _ensure_raw_bytes(
    raw_bytes: Optional[bytes] = None,
    image: Optional[Image.Image] = None,
) -> bytes:
    """Return raw_bytes, falling back to re-encoding a PIL image.

    Re-encoding strips NAI Comment tEXt, so raw_bytes should always be
    preferred. Callers that only pass `image` opt in to metadata loss.
    """
    if raw_bytes is not None:
        return raw_bytes
    if image is None:
        raise ValueError("Either raw_bytes or image must be provided.")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_character_asset_metadata(
    file_hash: str,
    file_name: str,
    extracted_metadata: Optional[Dict[str, Any]] = None,
    metadata_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the metadata payload for an asset image."""
    extracted_metadata = extracted_metadata or {}

    characters = list(extracted_metadata.get("characters") or [])
    characters_uc = list(extracted_metadata.get("characters_uc") or [])

    # The character prompt MUST come from NAI's character block (v4_prompt
    # char_captions). Falling back to ``extracted_metadata["prompt"]`` is
    # wrong — that is the scene-level main prompt (pose, clothing,
    # background). If it's copied into the C1 slot or the Variations tab's
    # Character Prompt field, the main prompt leaks into the character
    # identity and contaminates every downstream variation. Assets without a
    # character block simply have no character prompt to restore; callers
    # already handle the empty case ("캐릭터 프롬프트를 복구할 수 없습니다").
    metadata = {
        "asset_type": "character_asset",
        "display_mode": "contain",
        "file_hash": file_hash,
        "file_name": file_name,
        "character_prompt": characters[0] if characters else "",
        "character_uc": characters_uc[0] if characters_uc else "",
        "source_prompt": extracted_metadata.get("prompt", ""),
        "source_uc": extracted_metadata.get("uc", ""),
    }

    if metadata_overrides:
        metadata.update({key: value for key, value in metadata_overrides.items() if value is not None})

    return metadata


def load_character_asset_metadata(
    file_hash: str,
    image_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load asset metadata directly from the saved image (NAI Comment recovery)."""
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


# ---------------------------------------------------------------------------
# New grouped layout API
# ---------------------------------------------------------------------------


def list_characters() -> List[CharacterRecord]:
    """Enumerate all on-disk characters, sorted by primary mtime (newest first)."""
    ensure_character_asset_storage_dirs()
    records: List[CharacterRecord] = []
    for character_dir in CHARACTER_ASSET_CHARACTERS_DIR.iterdir():
        if not character_dir.is_dir():
            continue
        primary = character_dir / PRIMARY_FILE_NAME
        if not primary.exists():
            continue
        variations_dir = character_dir / VARIATIONS_DIR_NAME
        variation_count = 0
        if variations_dir.exists():
            variation_count = sum(1 for path in variations_dir.iterdir() if path.is_file())
        records.append(
            CharacterRecord(
                character_id=character_dir.name,
                primary_path=primary,
                variations_dir=variations_dir,
                variation_count=variation_count,
                mtime=primary.stat().st_mtime,
            )
        )
    records.sort(key=lambda record: record.mtime, reverse=True)
    return records


def list_character_variations(character_id: str) -> List[Path]:
    """List variation image files (sorted newest first)."""
    variations_dir = get_character_variations_dir(character_id)
    if not variations_dir.exists():
        return []
    files: List[Path] = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.webp"):
        files.extend(variations_dir.glob(ext))
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def save_new_character(
    raw_bytes: Optional[bytes] = None,
    image: Optional[Image.Image] = None,
) -> tuple[str, Path]:
    """Create a new character folder and save the primary image.

    Returns: (character_id, primary_path)
    If a character with the same hash already exists, returns the existing one.
    """
    data = _ensure_raw_bytes(raw_bytes, image)
    character_id = _compute_hash_prefix(data)

    ensure_character_asset_storage_dirs()
    character_dir = get_character_dir(character_id)
    character_dir.mkdir(parents=True, exist_ok=True)
    variations_dir = character_dir / VARIATIONS_DIR_NAME
    variations_dir.mkdir(parents=True, exist_ok=True)

    primary_path = character_dir / PRIMARY_FILE_NAME
    if not primary_path.exists():
        with open(primary_path, "wb") as file:
            file.write(data)
    return character_id, primary_path


def save_character_variation(
    character_id: str,
    raw_bytes: Optional[bytes] = None,
    image: Optional[Image.Image] = None,
) -> Path:
    """Save a variation image under the given character's variations folder."""
    data = _ensure_raw_bytes(raw_bytes, image)
    variation_hash = _compute_hash_prefix(data)

    character_dir = get_character_dir(character_id)
    if not character_dir.exists():
        raise FileNotFoundError(f"Character {character_id} does not exist.")

    variations_dir = character_dir / VARIATIONS_DIR_NAME
    variations_dir.mkdir(parents=True, exist_ok=True)

    variation_path = variations_dir / f"{variation_hash}.png"
    if not variation_path.exists():
        with open(variation_path, "wb") as file:
            file.write(data)
    return variation_path


def delete_character(character_id: str) -> bool:
    """Remove an entire character folder (primary + all variations)."""
    character_dir = get_character_dir(character_id)
    if not character_dir.exists():
        return False
    try:
        shutil.rmtree(character_dir)
        return True
    except Exception as exc:
        print(f"Failed to delete character {character_id}: {exc}")
        return False


def delete_variation(character_id: str, variation_path: Path) -> bool:
    """Delete a single variation file under a character."""
    try:
        expected_dir = get_character_variations_dir(character_id).resolve()
        target = variation_path.resolve()
        if expected_dir not in target.parents:
            print(f"Refusing to delete variation outside character dir: {target}")
            return False
        if target.exists():
            target.unlink()
        return True
    except Exception as exc:
        print(f"Failed to delete variation {variation_path}: {exc}")
        return False


def promote_variation_to_primary(character_id: str, variation_path: Path) -> bool:
    """Swap a variation with the character's primary image.

    The existing primary is preserved as a new variation so nothing is lost.
    The character_id itself is NOT changed — it stays pinned to the original
    hash so other references continue to resolve.
    """
    character_dir = get_character_dir(character_id)
    primary_path = character_dir / PRIMARY_FILE_NAME
    variations_dir = character_dir / VARIATIONS_DIR_NAME
    if not primary_path.exists() or not variation_path.exists():
        return False

    try:
        # Move current primary into variations under a fresh hash name.
        with open(primary_path, "rb") as file:
            old_primary_bytes = file.read()
        old_primary_hash = _compute_hash_prefix(old_primary_bytes)
        preserved_path = variations_dir / f"{old_primary_hash}.png"
        if not preserved_path.exists():
            shutil.move(str(primary_path), str(preserved_path))
        else:
            primary_path.unlink()

        # Move chosen variation up to primary.
        shutil.move(str(variation_path), str(primary_path))
        return True
    except Exception as exc:
        print(f"Failed to promote variation {variation_path}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


def migrate_legacy_flat_layout() -> int:
    """Promote legacy `images/{hash}.png` files to the grouped layout.

    Each legacy file becomes a 1-character-1-primary entry (no variations).
    Returns the number of migrated files. Idempotent — already migrated
    characters are skipped silently.
    """
    if not CHARACTER_ASSET_IMAGE_DIR.exists():
        return 0

    ensure_character_asset_storage_dirs()
    migrated = 0
    for legacy_file in list(CHARACTER_ASSET_IMAGE_DIR.iterdir()):
        if not legacy_file.is_file():
            continue
        if legacy_file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
            continue
        character_id = legacy_file.stem
        character_dir = get_character_dir(character_id)
        primary_path = character_dir / PRIMARY_FILE_NAME
        if primary_path.exists():
            # Already migrated — drop the legacy copy.
            try:
                legacy_file.unlink()
            except Exception:
                pass
            continue
        try:
            character_dir.mkdir(parents=True, exist_ok=True)
            (character_dir / VARIATIONS_DIR_NAME).mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_file), str(primary_path))
            migrated += 1
        except Exception as exc:
            print(f"Failed to migrate legacy asset {legacy_file}: {exc}")

    # Clean up legacy metadata sidecars — they have been unused since NAI
    # Comment-based recovery took over.
    if CHARACTER_ASSET_LEGACY_METADATA_DIR.exists():
        for legacy_meta in list(CHARACTER_ASSET_LEGACY_METADATA_DIR.iterdir()):
            try:
                legacy_meta.unlink()
            except Exception:
                pass
        try:
            CHARACTER_ASSET_LEGACY_METADATA_DIR.rmdir()
        except Exception:
            pass

    return migrated


# ---------------------------------------------------------------------------
# Legacy compatibility shim
# ---------------------------------------------------------------------------


def save_character_asset(
    raw_bytes: Optional[bytes] = None,
    image: Optional[Image.Image] = None,
) -> tuple[Path, Dict[str, Any]]:
    """Legacy entry point — now creates a new character in the grouped layout.

    Kept so that older callers still work. New code should call
    `save_new_character` directly.
    """
    data = _ensure_raw_bytes(raw_bytes, image)
    character_id, primary_path = save_new_character(raw_bytes=data)

    try:
        extracted_metadata = ImageMetadataExtractor.extract_metadata(Image.open(io.BytesIO(data)))
    except Exception as exc:
        print(f"Failed to extract character asset metadata: {exc}")
        extracted_metadata = None

    metadata = build_character_asset_metadata(
        file_hash=character_id,
        file_name=primary_path.name,
        extracted_metadata=extracted_metadata,
    )
    return primary_path, metadata
