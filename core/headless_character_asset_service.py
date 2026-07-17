"""Headless Character Asset service — web port of the desktop character asset storage.

Storage policy (Codex-reviewed):
  - write root  = ``context._save_path("character_asset")`` — the ONLY mutation target
  - legacy root = ``context._legacy_save_path("character_asset")``, read-only; a
    mutation on a legacy-owned character triggers copy-on-write migration into the
    write root first. On id collision the write root wins.
  - delete is the single exception: it removes the character from BOTH roots so a
    legacy copy cannot resurrect a deleted character.

Prompt/UC recovery stays inside the saved PNG (NAI Comment, v4 character block
only — never the scene-level main prompt). The sidecar ``meta.json`` holds the
display name only.
"""

from __future__ import annotations

import io
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Optional

from utils import character_asset_storage as asset_storage

CHARACTER_ASSET_DIR_NAME = "character_asset"
ASSET_ID_RE = re.compile(r"^[0-9a-f]{16}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_ASSET_PIXELS = 36_000_000
GENERATION_WIDTH = 768
GENERATION_HEIGHT = 1344
MAX_GENERATION_COUNT = 8
MAX_DISPLAY_NAME_LEN = 80


class HeadlessCharacterAssetService:
    def __init__(self, context: Any):
        self.context = context
        self._lock = threading.RLock()
        self._bootstrapped = False
        # (path, mtime_ns) -> extracted prompt meta. Bounded like the viewer
        # thumb cache: cleared wholesale past 256 entries.
        self._prompt_meta_cache: dict[tuple[str, int], dict[str, Any]] = {}

    # ------------------------------------------------------------------ roots
    def write_root(self) -> Path:
        return Path(self.context._save_path(CHARACTER_ASSET_DIR_NAME))

    def legacy_root(self) -> Optional[Path]:
        try:
            if not self.context._runtime_path_service().legacy_save_fallback_enabled():
                return None
            legacy = Path(self.context._legacy_save_path(CHARACTER_ASSET_DIR_NAME))
            if legacy.resolve() == self.write_root().resolve():
                return None
        except Exception:
            return None
        return legacy if legacy.exists() else None

    def _list_roots(self) -> list[Path]:
        roots = [self.write_root()]
        legacy = self.legacy_root()
        if legacy is not None and (legacy / "characters").exists():
            roots.append(legacy)
        return roots

    def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        with self._lock:
            if self._bootstrapped:
                return
            root = self.write_root()
            try:
                asset_storage.migrate_legacy_flat_layout(root)
            except Exception as exc:
                print(f"[CharacterAsset] flat layout migration failed: {exc}")
            legacy = self.legacy_root()
            if legacy is not None:
                self._absorb_legacy_flat(legacy)
            self._bootstrapped = True

    def _absorb_legacy_flat(self, legacy: Path) -> None:
        """Copy legacy-root flat ``images/*`` into the write root (grouped layout).

        The legacy tree stays read-only: files are copied, never moved. Idempotent
        because the character id is content-derived and ``save_new_character``
        dedupes on an existing id.
        """
        images_dir = legacy / "images"
        if not images_dir.exists():
            return
        for legacy_file in sorted(images_dir.iterdir()):
            if not legacy_file.is_file():
                continue
            if legacy_file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
                continue
            try:
                asset_storage.save_new_character(
                    raw_bytes=legacy_file.read_bytes(), root=self.write_root()
                )
            except Exception as exc:
                print(f"[CharacterAsset] legacy flat absorb failed for {legacy_file.name}: {exc}")

    def _owner_root(self, character_id: str) -> Optional[Path]:
        write_root = self.write_root()
        if asset_storage.get_character_primary_path(character_id, write_root).exists():
            return write_root
        legacy = self.legacy_root()
        if legacy is not None and asset_storage.get_character_primary_path(character_id, legacy).exists():
            return legacy
        return None

    def _ensure_current(self, character_id: str) -> Path:
        """Return the write root, copy-on-write migrating a legacy-owned character
        into it first. On id collision the write root wins (no copy)."""
        write_root = self.write_root()
        if asset_storage.get_character_primary_path(character_id, write_root).exists():
            return write_root
        legacy = self.legacy_root()
        if legacy is None:
            raise FileNotFoundError(f"character {character_id} not found")
        legacy_dir = asset_storage.get_character_dir(character_id, legacy)
        if not (legacy_dir / asset_storage.PRIMARY_FILE_NAME).exists():
            raise FileNotFoundError(f"character {character_id} not found")
        characters_dir = write_root / "characters"
        characters_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = characters_dir / f".{character_id}.cow-tmp"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        shutil.copytree(legacy_dir, tmp_dir)
        tmp_dir.replace(asset_storage.get_character_dir(character_id, write_root))
        return write_root

    # ------------------------------------------------------------- validation
    @staticmethod
    def _validate_id(character_id: str) -> str:
        value = str(character_id or "").strip().lower()
        if not ASSET_ID_RE.match(value):
            raise ValueError("invalid character id")
        return value

    @staticmethod
    def _validate_hash(variation_hash: str) -> str:
        value = str(variation_hash or "").strip().lower()
        if not ASSET_ID_RE.match(value):
            raise ValueError("invalid variation hash")
        return value

    @staticmethod
    def _validate_image_bytes(data: bytes) -> None:
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError("image bytes required")
        if len(data) > MAX_ASSET_BYTES:
            raise ValueError("image too large (max 32MB)")
        if not bytes(data).startswith(PNG_SIGNATURE):
            raise ValueError("PNG image required (NAI metadata lives in the PNG)")
        from PIL import Image

        try:
            with Image.open(io.BytesIO(bytes(data))) as image:
                width, height = image.size
                if width * height > MAX_ASSET_PIXELS:
                    raise ValueError("image dimensions too large")
                # Actually decode - a truncated PNG passes the lazy open/size
                # probe but must be rejected before it lands on disk.
                image.load()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"corrupted or unreadable PNG: {exc}")

    # ------------------------------------------------------------ prompt meta
    def _extract_prompt_meta(self, character_id: str, image_path: Path) -> dict[str, Any]:
        try:
            cache_key = (str(image_path), image_path.stat().st_mtime_ns)
        except OSError:
            return {}
        cached = self._prompt_meta_cache.get(cache_key)
        if cached is not None:
            return cached
        meta = asset_storage.load_character_asset_metadata(character_id, image_path)
        if len(self._prompt_meta_cache) > 256:
            self._prompt_meta_cache.clear()
        self._prompt_meta_cache[cache_key] = meta
        return meta

    # ------------------------------------------------------------------ reads
    def list_state(self) -> dict[str, Any]:
        self._bootstrap()
        with self._lock:
            entries: list[dict[str, Any]] = []
            seen: set[str] = set()
            for root in self._list_roots():
                try:
                    records = asset_storage.list_characters(root)
                except Exception as exc:
                    print(f"[CharacterAsset] list failed for root: {exc}")
                    continue
                for record in records:
                    if record.character_id in seen or not ASSET_ID_RE.match(record.character_id):
                        continue
                    seen.add(record.character_id)
                    sidecar = asset_storage.read_character_meta(record.character_id, root)
                    try:
                        revision = record.primary_path.stat().st_mtime_ns
                    except OSError:
                        revision = 0
                    entries.append({
                        "id": record.character_id,
                        "display_name": str(sidecar.get("display_name") or ""),
                        "variation_count": record.variation_count,
                        "mtime": record.mtime,
                        "revision": revision,
                    })
            entries.sort(key=lambda entry: entry["mtime"], reverse=True)
            return {
                "characters": entries,
                "api_mode": str(self.context.get_api_mode() or "").upper(),
            }

    def detail(self, character_id: str) -> dict[str, Any]:
        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            root = self._owner_root(character_id)
            if root is None:
                raise FileNotFoundError(f"character {character_id} not found")
            primary = asset_storage.get_character_primary_path(character_id, root)
            meta = self._extract_prompt_meta(character_id, primary)
            variations: list[dict[str, Any]] = []
            for path in asset_storage.list_character_variations(character_id, root):
                if not ASSET_ID_RE.match(path.stem):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                variations.append({
                    "hash": path.stem,
                    "mtime": stat.st_mtime,
                    "revision": stat.st_mtime_ns,
                })
            sidecar = asset_storage.read_character_meta(character_id, root)
            prompt = str(meta.get("character_prompt") or "").strip()
            return {
                "id": character_id,
                "display_name": str(sidecar.get("display_name") or ""),
                "character_prompt": prompt,
                "character_uc": str(meta.get("character_uc") or "").strip(),
                "recovered": bool(prompt),
                "variations": variations,
                "revision": primary.stat().st_mtime_ns,
            }

    def resolve_image_path(self, character_id: str, variation: str = "") -> Path:
        self._bootstrap()
        character_id = self._validate_id(character_id)
        root = self._owner_root(character_id)
        if root is None:
            raise FileNotFoundError(f"character {character_id} not found")
        if str(variation or "").strip():
            variation = self._validate_hash(variation)
            for path in asset_storage.list_character_variations(character_id, root):
                if path.stem == variation:
                    return path
            raise FileNotFoundError(f"variation {variation} not found")
        return asset_storage.get_character_primary_path(character_id, root)

    # -------------------------------------------------------------- mutations
    def save_bytes(self, data: bytes, target: dict[str, Any]) -> dict[str, Any]:
        self._bootstrap()
        self._validate_image_bytes(data)
        with self._lock:
            kind = str((target or {}).get("kind") or "new").strip().lower()
            if kind == "variation":
                character_id = self._validate_id(str((target or {}).get("character_id") or ""))
                self._ensure_current(character_id)
                saved_path = asset_storage.save_character_variation(
                    character_id, raw_bytes=bytes(data), root=self.write_root()
                )
                saved_id = character_id
            elif kind == "new":
                saved_id, saved_path = asset_storage.save_new_character(
                    raw_bytes=bytes(data), root=self.write_root()
                )
            else:
                raise ValueError(f"unknown save target kind: {kind}")
            meta = self._extract_prompt_meta(saved_id, saved_path)
            return {
                "character_id": saved_id,
                "kind": kind,
                "character_prompt_recovered": bool(str(meta.get("character_prompt") or "").strip()),
            }

    def rename(self, character_id: str, display_name: str) -> dict[str, Any]:
        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            self._ensure_current(character_id)
            meta = asset_storage.read_character_meta(character_id, self.write_root())
            meta["display_name"] = str(display_name or "").strip()[:MAX_DISPLAY_NAME_LEN]
            if not asset_storage.write_character_meta(character_id, meta, self.write_root()):
                raise RuntimeError("failed to write character meta")
            return {"id": character_id, "display_name": meta["display_name"]}

    def delete(self, character_id: str) -> bool:
        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            deleted = False
            # Explicit user delete removes the character from BOTH roots — the
            # legacy tree is otherwise read-only, but leaving a copy there would
            # resurrect the character on the next listing.
            write_root = self.write_root()
            if asset_storage.get_character_primary_path(character_id, write_root).exists():
                deleted = asset_storage.delete_character(character_id, write_root) or deleted
            legacy = self.legacy_root()
            if legacy is not None and asset_storage.get_character_primary_path(character_id, legacy).exists():
                deleted = asset_storage.delete_character(character_id, legacy) or deleted
            return deleted

    def delete_variation(self, character_id: str, variation_hash: str) -> bool:
        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            variation_hash = self._validate_hash(variation_hash)
            self._ensure_current(character_id)
            for path in asset_storage.list_character_variations(character_id, self.write_root()):
                if path.stem == variation_hash:
                    return asset_storage.delete_variation(character_id, path, root=self.write_root())
            return False

    def promote(self, character_id: str, variation_hash: str) -> bool:
        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            variation_hash = self._validate_hash(variation_hash)
            self._ensure_current(character_id)
            for path in asset_storage.list_character_variations(character_id, self.write_root()):
                if path.stem == variation_hash:
                    return asset_storage.promote_variation_to_primary(
                        character_id, path, root=self.write_root()
                    )
            return False

    # ------------------------------------------------------------ slot apply
    def _attach_character_reference(self, image_path: Path) -> None:
        """Register the asset image as an enabled Character Reference frame.

        Mirrors the CR module's apply_storage semantics: build an enabled frame
        (image_data() normalizes any resolution onto the nearest NAI canvas -
        2:3 1024x1536 / 3:2 1536x1024 / 1:1 1472x1472, letterboxed), persist the
        storage PNG, and cross-disable Vibe frames (mutual exclusion contract).
        Re-applying the same image enables the existing frame instead of
        stacking a duplicate.
        """
        context = self.context
        service = context._character_reference_service()
        service._ensure_loaded()
        image_bytes = image_path.read_bytes()
        frame = service.frame_from_bytes(
            image_bytes,
            file_name=image_path.name,
            file_path=str(image_path),
            enabled=True,
        )
        frames = context.character_reference_frames
        existing = next(
            (item for item in frames if item.get("file_hash") == frame["file_hash"]), None
        )
        if existing is not None:
            existing["is_enabled"] = True
            service.save_storage(existing)
        else:
            frames.append(frame)
            service.save_storage(frame)
        context._disable_all_vibe_frames()
        service._persist()

    def apply_to_slot(
        self,
        character_id: str,
        variation: str = "",
        mode: str = "c1",
        with_reference: bool = False,
    ) -> dict[str, Any]:
        self._bootstrap()
        context = self.context
        if str(context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("character slot apply requires NAI mode")
        mode = str(mode or "c1").strip().lower()
        if mode not in {"c1", "add_slot"}:
            raise ValueError(f"unknown apply mode: {mode}")
        path = self.resolve_image_path(character_id, variation)
        meta = self._extract_prompt_meta(self._validate_id(character_id), path)
        prompt = str(meta.get("character_prompt") or "").strip()
        uc = str(meta.get("character_uc") or "").strip()
        if not prompt:
            raise ValueError("no NAI character block in this image - cannot recover the character prompt")
        state = context._character_service().apply_asset(prompt, uc, mode)
        reference_attached = False
        if with_reference:
            try:
                self._attach_character_reference(path)
                reference_attached = True
            except Exception as exc:
                print(f"[CharacterAsset] character reference attach failed: {exc}")
        return {
            "ok": True,
            "state": state,
            "character_prompt": prompt,
            "character_uc": uc,
            "reference_attached": reference_attached,
        }

    # ------------------------------------------------ reference generation
    def build_generation_overrides(self, payload: dict[str, Any], candidate: int) -> dict[str, Any]:
        if str(self.context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("Character Asset generation requires NAI mode")
        payload = payload if isinstance(payload, dict) else {}
        character_prompt = str(payload.get("character_prompt") or "").strip()
        if not character_prompt:
            raise ValueError("character_prompt is required")
        character_uc = str(payload.get("character_uc") or "").strip()
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise ValueError("request_id is required")
        from utils.reference_inpaint_preprocess import ReferenceGenerationSpec

        label = character_prompt.split(",")[0].strip()[:48] or "character asset"
        return {
            # Correlation / suppression markers. NOT the characters routing:
            # characters/uc below are absorbed as NAICharacterData early binding
            # (headless_generation_service._extract_nai_data) — the dormant
            # api_service character_asset branch stays unreachable by design.
            "character_asset_request": True,
            "character_asset_request_id": request_id,
            "character_asset_candidate": int(candidate),
            "_remote_queue_source": "Character Asset",
            "_remote_queue_label": label,
            # Generation content (Dev0714 parity: fixed full-body scaffold).
            "input": ReferenceGenerationSpec().build_prompt(),
            "characters": [character_prompt],
            "uc": [character_uc],
            "width": GENERATION_WIDTH,
            "height": GENERATION_HEIGHT,
            "random_resolution": False,
            # Isolation (Codex plan review): no source-row wildcards, no active
            # Character Reference / Vibe late binding, fresh random seed per
            # candidate even while the user has seed-fix enabled.
            "wildcard_standalone": True,
            "_skip_vibe_transfer_late_binding": True,
            "_skip_character_reference_late_binding": True,
            "seed": -1,
            "seed_fixed": False,
        }
