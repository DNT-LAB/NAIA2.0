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
import json
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
BENCH_DEFAULTS_FILE = "bench_defaults.json"
BENCH_DEFAULT_MAIN_PROMPT = "2koma, borderless panel"
BENCH_DEFAULT_EXTRA_NEGATIVE = "border"


def reencode_with_nai_meta(edited_image, source_image, parameters: dict) -> bytes:
    """Re-save ``edited_image`` as PNG carrying over NAI tEXt chunks from
    ``source_image.info`` (Dev0714 storage-window port, pure PIL). Falls back to
    synthesising a minimal Comment JSON from ``parameters`` when the original
    lacks the core NAI fields. Keeps PNG Info / prompt recovery working for
    cropped variation saves.
    """
    import json as _json

    from PIL.PngImagePlugin import PngInfo

    pnginfo = PngInfo()
    source_info = getattr(source_image, "info", {}) or {}
    preserved_keys = (
        "Title",
        "Description",
        "Software",
        "Source",
        "Comment",
        "Generation time",
        "Author",
    )
    added_any = False
    for key in preserved_keys:
        value = source_info.get(key)
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        if isinstance(value, str) and value:
            pnginfo.add_text(key, value)
            added_any = True

    has_core_nai = bool(source_info.get("Software")) and bool(source_info.get("Comment"))
    if not has_core_nai:
        comment_payload: dict = {
            "prompt": parameters.get("input", "") or "",
            "uc": parameters.get("negative_prompt", "") or "",
        }
        for key in ("steps", "scale", "seed", "sampler", "noise_schedule", "cfg_rescale", "sm", "sm_dyn"):
            if parameters.get(key) is not None:
                comment_payload[key] = parameters[key]
        try:
            comment_json = _json.dumps(comment_payload, ensure_ascii=False)
        except Exception:
            comment_json = None
        if not source_info.get("Software"):
            pnginfo.add_text("Software", "NovelAI")
            added_any = True
        if not source_info.get("Description"):
            description_text = parameters.get("input", "") or ""
            if description_text:
                pnginfo.add_text("Description", description_text)
                added_any = True
        if not source_info.get("Comment") and comment_json:
            pnginfo.add_text("Comment", comment_json)
            added_any = True

    buffer = io.BytesIO()
    edited_image.save(buffer, format="PNG", pnginfo=pnginfo if added_any else None)
    return buffer.getvalue()


class HeadlessCharacterAssetService:
    def __init__(self, context: Any):
        self.context = context
        self._lock = threading.RLock()
        self._bootstrapped = False
        # (path, mtime_ns) -> extracted prompt meta. Bounded like the viewer
        # thumb cache: cleared wholesale past 256 entries.
        self._prompt_meta_cache: dict[tuple[str, int], dict[str, Any]] = {}
        # (primary path, mtime_ns) -> (canvas_png, small_mask_png). Canvases are
        # ~1MB each; keep only a handful.
        self._bench_canvas_cache: dict[tuple[str, int], tuple[bytes, bytes]] = {}

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

    # ------------------------------------------------ variation bench
    def _bench_defaults_path(self) -> Path:
        return Path(self.context._save_path(CHARACTER_ASSET_DIR_NAME, BENCH_DEFAULTS_FILE))

    def bench_defaults(self) -> dict[str, Any]:
        defaults = {
            "main_prompt": BENCH_DEFAULT_MAIN_PROMPT,
            "extra_negative": BENCH_DEFAULT_EXTRA_NEGATIVE,
        }
        try:
            path = self._bench_defaults_path()
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for key in defaults:
                        if isinstance(data.get(key), str):
                            defaults[key] = data[key]
        except Exception as exc:
            print(f"[CharacterAsset] bench defaults load failed: {exc}")
        return defaults

    def save_bench_defaults(self, main_prompt: str, extra_negative: str) -> None:
        try:
            path = self._bench_defaults_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(
                json.dumps(
                    {"main_prompt": str(main_prompt or ""), "extra_negative": str(extra_negative or "")},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception as exc:
            print(f"[CharacterAsset] bench defaults save failed: {exc}")

    def _bench_canvas(self, character_id: str) -> tuple[bytes, bytes]:
        """Build (or reuse) the variation inpaint canvas + NAI small mask for a
        character's primary image. Narrow 512x896 edit rect - keeps NAI from
        painting a second character into the free area (Dev0714 spec)."""
        from PIL import Image

        from utils.reference_inpaint_preprocess import prepare_variation_inpaint_canvas

        primary = self.resolve_image_path(character_id)
        try:
            cache_key = (str(primary), primary.stat().st_mtime_ns)
        except OSError as exc:
            raise FileNotFoundError(f"primary image unavailable: {exc}")
        cached = self._bench_canvas_cache.get(cache_key)
        if cached is not None:
            return cached
        with Image.open(primary) as opened:
            opened.load()
            result = prepare_variation_inpaint_canvas(opened)
        canvas_buffer = io.BytesIO()
        result.canvas_image.save(canvas_buffer, format="PNG")
        mask_buffer = io.BytesIO()
        result.small_mask_image.save(mask_buffer, format="PNG")
        payload = (canvas_buffer.getvalue(), mask_buffer.getvalue())
        if len(self._bench_canvas_cache) > 8:
            self._bench_canvas_cache.clear()
        self._bench_canvas_cache[cache_key] = payload
        return payload

    def build_bench_overrides(self, payload: dict[str, Any], candidate: int) -> dict[str, Any]:
        """Inpaint overrides for one variation candidate - mirrors the shape the
        img2img service enqueues (proven consumer path), plus the Dev0714
        variation contract: fixed strength 1.0 / noise 0.0, reference inset tag,
        sketchbook character override, and NO cropped_image_request (the bbox
        shrink would make results unusable for reuse)."""
        from utils.reference_inpaint_preprocess import VariationInpaintSpec

        if str(self.context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("variation bench requires NAI mode")
        payload = payload if isinstance(payload, dict) else {}
        character_id = self._validate_id(str(payload.get("id") or ""))
        character_prompt = str(payload.get("character_prompt") or "").strip()
        if not character_prompt:
            raise ValueError("character_prompt is required")
        character_uc = str(payload.get("character_uc") or "").strip()
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise ValueError("request_id is required")
        main_prompt = str(payload.get("main_prompt") or "").strip() or BENCH_DEFAULT_MAIN_PROMPT
        extra_negative = str(payload.get("extra_negative") or "").strip()
        base_negative = str(getattr(self.context, "negative_prompt_text", "") or "").strip()
        negative = ", ".join(part for part in (base_negative, extra_negative) if part)
        canvas_png, mask_png = self._bench_canvas(character_id)
        spec = VariationInpaintSpec()
        label = character_prompt.split(",")[0].strip()[:40] or character_id
        return {
            "type": "inpaint",
            "image_bytes": canvas_png,
            "mask_bytes": mask_png,
            "input": main_prompt,
            "_raw_input": main_prompt,
            "negative_prompt": negative,
            "strength": 1.0,
            "noise": 0.0,
            "width": spec.canvas_width,
            "height": spec.canvas_height,
            "random_resolution": False,
            "sketchbook_character_prompts": [(character_prompt, character_uc)],
            "reference_inset_tag_required": True,
            "character_asset_request": True,
            "character_asset_request_id": request_id,
            "character_asset_candidate": int(candidate),
            "character_asset_bench": True,
            "character_asset_bench_character": character_id,
            "_remote_queue_source": "Character Asset",
            "_remote_queue_label": f"variation: {label}",
            "seed": -1,
            "seed_fixed": False,
            "_skip_vibe_transfer_late_binding": True,
            "_skip_character_reference_late_binding": True,
            "wildcard_standalone": True,
        }

    def save_bench_result(self, character_id: str, history_id: str) -> dict[str, Any]:
        """Crop the 512x896 edit rect out of a bench canvas result, transplant
        the NAI tEXt metadata, LANCZOS-upscale 1.5x to 768x1344 (exact 4:7
        landing) and store it as a variation of the character."""
        from PIL import Image

        from utils.reference_inpaint_preprocess import VariationInpaintSpec

        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            item = self.context.result_store.get_item(str(history_id or "").strip())
            if item is None:
                raise FileNotFoundError("bench result not found in history (already evicted?)")
            raw = getattr(item, "raw_bytes", None)
            if not raw or not bytes(raw).startswith(PNG_SIGNATURE):
                raise ValueError("bench result is not an original PNG")
            spec = VariationInpaintSpec()
            with Image.open(io.BytesIO(bytes(raw))) as source:
                source.load()
                if source.size != (spec.canvas_width, spec.canvas_height):
                    raise ValueError("history item is not a variation bench canvas result")
                crop = source.crop((spec.edit_left, spec.edit_top, spec.edit_right, spec.edit_bottom))
                target_width = (spec.edit_right - spec.edit_left) * 3 // 2
                target_height = (spec.edit_bottom - spec.edit_top) * 3 // 2
                upscaled = crop.resize((target_width, target_height), Image.Resampling.LANCZOS)
                params = item.generation_params if isinstance(item.generation_params, dict) else {}
                png = reencode_with_nai_meta(upscaled, source, params)
            self._ensure_current(character_id)
            path = asset_storage.save_character_variation(
                character_id, raw_bytes=png, root=self.write_root()
            )
            return {"character_id": character_id, "hash": path.stem}
