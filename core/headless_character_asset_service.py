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
import math
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from core.nai_model_contract import resolve_nai_model_for_context
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
BENCH_DEFAULT_MAIN_PROMPT = "2koma, borderless panels"
BENCH_LEGACY_DEFAULT_MAIN_PROMPT = "2koma, borderless panel"
BENCH_DEFAULT_EXTRA_NEGATIVE = "border, border, nsfw"
BENCH_LEGACY_DEFAULT_EXTRA_NEGATIVE = "border"
BENCH_MODES = ("inpaint", "char_reference")
BENCH_REFERENCE_TYPES = {"character&style", "character"}
# 생성 벤치 랜덤 슬롯 풀(data/random_*.txt). 각 줄 = 콤마로 구분된 태그 한 세트.
RANDOM_CHARACTER_POOLS = {
    "appearance": "random_character.txt",
    "outfit": "random_outfits.txt",
}
RANDOM_GENDER_TAGS = ("girl", "boy")
# 의상 스왑에서 보존할 리전 - 머리/목 장식은 캐릭터 정체성이라 옷과 함께 벗기지 않는다.
OUTFIT_KEEP_REGION = "HEAD_NECK_FACE"
BENCH_PROMPT_SOURCES = {"primary", "current", "preset"}
BENCH_MODE_DEFAULTS = {
    "inpaint": {"main_prompt": BENCH_DEFAULT_MAIN_PROMPT, "extra_negative": BENCH_DEFAULT_EXTRA_NEGATIVE},
    "char_reference": {"main_prompt": "", "extra_negative": ""},
}

_REFERENCE_PIVOT_CURRENT = (
    "solo", "1koma", "standing", "looking away", "white background",
    "simple background", "centered composition", "occupying most of frame",
    "front view", "narrow margins", "top of head near top edge",
    "feet near bottom edge", "full-body portrait", "white seamless background",
    "rating:general", "safe",
)
_REFERENCE_PIVOT_LEGACY = (
    "solo", "standing", "looking away", "occupying most of frame",
    "front view", "narrow margins", "top of head near top edge",
    "feet near bottom edge", "full-body portrait", "rating:general", "safe",
)
# 바리에이션 벤치 생성 시 조합의 solo 자리에 조용히 태우는 자세 스캐폴드.
# 사용자가 의도를 갖고 등급을 조절할 수 있도록 rating:general / safe는 제외.
_SILENT_SCAFFOLD_TAGS = _REFERENCE_PIVOT_LEGACY[:-2]
BENCH_SILENT_SCAFFOLD = ", ".join(_SILENT_SCAFFOLD_TAGS)
# Dev0714 "Save with Enhance" 고정 프로파일: 인페인트 크롭(512x896)을 NAI img2img
# 1패스로 1.5x(768x1344) 선명화. strength 0.3 = 내용 드리프트 없이 소프트함만 걷어냄
# (0.2는 헤이즈가 남는다는 Dev0714 실측으로 상향된 값).
BENCH_ENHANCE_UPSCALE = 1.5
BENCH_ENHANCE_STRENGTH = 0.3
BENCH_ENHANCE_NOISE = 0.0
# Count tags are routing tags, not content: "1boy" / "2boys" / "6+girls" all
# resolve like their bare form. Anchored per-tag so "cowboy shot" is not a boy.
_COUNT_BOY_TAG_RE = re.compile(r"^(?:\d+\+?)?boys?$", re.IGNORECASE)
_COUNT_GIRL_TAG_RE = re.compile(r"^(?:\d+\+?)?girls?$", re.IGNORECASE)
_COUNT_TAG_EDGE_RE = re.compile(r"^(?:\d+\+?)?(?:girls?|boys?)$", re.IGNORECASE)
# 히스토리 퇴출(200개 상한) 후에도 화면에 떠 있는 후보는 저장 가능해야 한다.
# 캐릭터 에셋 후보만, 이 개수만큼 FIFO로 붙잡는다(파이썬 refcount가 bytes를 살림).
CANDIDATE_RETENTION_LIMIT = 24
# 인페인트 핀 동시 상한. 핀은 원본 PNG(~수 MB)를 통째로 붙잡으므로 새는 것을
# 막는다 - 상한 도달 시 가장 오래된 핀부터 회수(리로드로 pin_id를 잃은 고아
# 복구 경로 - 명시 거부로 두면 재시작 전까지 영구 소진된다, Codex).
PINNED_CANDIDATE_LIMIT = 8
_BENCH_PROFILE_PARAM_ALIASES = {
    "model": ("model", "Model", "model_name"),
    "sampler": ("sampler", "sampler_name"),
    "scheduler": ("scheduler", "noise_schedule"),
    "steps": ("steps",),
    "cfg_scale": ("cfg_scale", "scale", "cfg"),
    "cfg_rescale": ("cfg_rescale", "rescale_cfg"),
    "uncond_scale": ("uncond_scale", "uc_strength"),
    "SMEA": ("SMEA", "sm"),
    "DYN": ("DYN", "sm_dyn"),
    "VAR+": ("VAR+", "skip_cfg_above_sigma"),
    "DECRISP": ("DECRISP", "dynamic_thresholding"),
}


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
        # (primary path, mtime_ns) -> normalized CR image_data (base64, ~1-2MB).
        self._bench_reference_cache: dict[tuple[str, int], str] = {}
        # (primary path, mtime_ns) -> Metadata Viewer-compatible prompt profile.
        self._bench_profile_cache: dict[tuple[str, int], dict[str, Any]] = {}
        # history_id -> HeadlessHistoryItem for character-asset candidates only.
        # Bounded FIFO lease so a candidate stays saveable after the result
        # store hard-evicts it (Codex plan review §2: an expired badge is a
        # post-hoc notice, not preservation). Never held during IO.
        self._retained_candidates: dict[str, Any] = {}
        self._retain_lock = threading.Lock()
        # 인페인트 핀: 리스 FIFO와 별개로, 사용자가 해제할 때까지 원본 PNG를
        # 명시적으로 붙잡는다(리스는 24개 한도라 오래 열어둔 핀이 밀려날 수
        # 있다 - Codex BLOCK). pin_id -> {history_id, png, width, height}
        self._pinned_candidates: dict[str, dict[str, Any]] = {}
        # 레퍼런스 인셋 핀([C1 + 레퍼런스 인셋 적용]): 메인 생성이 이 캔버스로
        # 인셋 인페인트가 되도록 고정한다. 해제는 사용자만(Result 탭 X 버튼).
        # {character_id, variation, canvas_png, mask_png, width, height}
        self._reference_inset_pin: Optional[dict[str, Any]] = None
        # data/random_*.txt lines. 수 MB라 1회만 읽는다.
        self._random_pools: dict[str, list[str]] = {}

    # ------------------------------------------------------- candidate lease
    def retain_candidate(self, item: Any) -> None:
        """Lease a character-asset generation result so it stays saveable.

        The result store hard-evicts past its cap, but a bench candidate must
        remain saveable while the user is looking at it. Only character-asset
        requests are leased, bounded FIFO - holding the item keeps its bytes
        alive by refcount even after the store drops it.
        """
        history_id = str(getattr(item, "history_id", "") or "")
        if not history_id:
            return
        with self._retain_lock:
            self._retained_candidates.pop(history_id, None)
            self._retained_candidates[history_id] = item
            while len(self._retained_candidates) > CANDIDATE_RETENTION_LIMIT:
                self._retained_candidates.pop(next(iter(self._retained_candidates)))

    def candidate_item(self, history_id: str) -> Any:
        """Live history item, falling back to this service's leased copy."""
        history_id = str(history_id or "").strip()
        if not history_id:
            return None
        item = self.context.result_store.get_item(history_id)
        if item is not None:
            return item
        with self._retain_lock:
            return self._retained_candidates.get(history_id)

    # -------------------------------------------------------- inpaint pin
    def pin_candidate(self, history_id: str) -> dict[str, Any]:
        """생성 벤치 후보를 인페인트 소스로 고정한다(opaque pin_id 반환).

        원본 PNG bytes를 핀에 복사하므로 히스토리 퇴출과 리스 FIFO 밀림 모두에서
        살아남는다. 해제는 unpin_candidate 뿐이다(핀 계약: 포커스와 무관하게
        사용자가 해제할 때까지 고정). provenance: 캐릭터 에셋 생성 플로우의
        결과만 - 우연히 같은 크기인 남의 히스토리를 인페인트 소스로 쓰면 안 된다.
        """
        from PIL import Image

        history_id = str(history_id or "").strip()
        if not history_id:
            raise ValueError("history_id is required")
        item = self.candidate_item(history_id)
        if item is None:
            raise FileNotFoundError("candidate is no longer available")
        raw = getattr(item, "raw_bytes", None)
        if not raw or not bytes(raw).startswith(PNG_SIGNATURE):
            raise ValueError("candidate is not an original PNG")
        params = item.generation_params if isinstance(item.generation_params, dict) else {}
        if str(params.get("character_asset_flow") or "") != "creation":
            raise ValueError("only creation bench results can be pinned for inpaint")
        raw = bytes(raw)
        with Image.open(io.BytesIO(raw)) as opened:
            width, height = opened.size
        with self._retain_lock:
            # 같은 후보 재핀 = 기존 핀 재사용(중복 적재 방지, 편집 중 마스크 유지).
            for existing_id, pin in self._pinned_candidates.items():
                if pin["history_id"] == history_id:
                    return {
                        "pin_id": existing_id,
                        "history_id": history_id,
                        "width": pin["width"],
                        "height": pin["height"],
                    }
            while len(self._pinned_candidates) >= PINNED_CANDIDATE_LIMIT:
                # 상한 도달 = 대부분 리로드로 pin_id를 잃은 고아 핀(프론트는 클라이언트당
                # 1핀). 명시 거부로 두면 서버 재시작 전까지 인페인트가 영구 불능이 되므로
                # (Codex BLOCK) 가장 오래된 핀부터 회수한다. 활성 핀은 사실상 최신이다.
                evicted = next(iter(self._pinned_candidates))
                self._pinned_candidates.pop(evicted)
                print("[CharacterAsset] pin limit reached - evicted oldest pin " + evicted[:8])
            pin_id = uuid.uuid4().hex
            self._pinned_candidates[pin_id] = {
                "history_id": history_id,
                "png": raw,
                "width": int(width),
                "height": int(height),
            }
        return {"pin_id": pin_id, "history_id": history_id, "width": int(width), "height": int(height)}

    def unpin_candidate(self, pin_id: str) -> bool:
        with self._retain_lock:
            return self._pinned_candidates.pop(str(pin_id or "").strip(), None) is not None

    # ------------------------------------------------- reference inset pin
    def set_reference_inset_pin(
        self,
        character_id: str,
        variation: str = "",
        width: Any = 0,
        height: Any = 0,
    ) -> dict[str, Any]:
        """선택 이미지를 레퍼런스 인셋 소스로 고정한다(Dev0714 Comic Panel 계보).

        prepare_reference_inpaint_canvas가 고른 캔버스 왼쪽에 이미지를 붙이고
        보존 마스크(+우측 seam 스트립)를 만든다. 핀이 살아 있는 동안 plain NAI
        생성은 전부 이 캔버스 위 인셋 인페인트로 나간다(주입은
        headless_image_module_param_service). 이번 버전은 마스크 크롭 저장 미지원 -
        결과는 캔버스 전체가 히스토리에 남는다.

        캔버스는 `REFERENCE_INSET_CANVAS_SIZES` 중에서 고른다(사용자 지정 2026-08-25).
        안 주면 기본 1152x896. 목록에 없는 값은 조용히 기본값으로 떨어뜨린다 -
        아무 숫자나 통과시키면 돈이 나가는 요청이 엉뚱한 크기로 나간다.
        """
        from PIL import Image

        from utils.reference_inpaint_preprocess import (
            ReferenceInsetPreprocessSpec,
            prepare_reference_inpaint_canvas,
            resolve_reference_inset_canvas,
        )

        character_id = self._validate_id(character_id)
        variation = self._validate_hash(variation) if str(variation or "").strip() else ""
        canvas_w, canvas_h = resolve_reference_inset_canvas(width, height)
        spec = ReferenceInsetPreprocessSpec(canvas_width=canvas_w, canvas_height=canvas_h)
        path = self.resolve_image_path(character_id, variation)
        with Image.open(path) as opened:
            opened.load()
            result = prepare_reference_inpaint_canvas(opened, spec)
        canvas_buffer = io.BytesIO()
        result.canvas_image.save(canvas_buffer, format="PNG")
        mask_buffer = io.BytesIO()
        result.small_mask_image.save(mask_buffer, format="PNG")
        pin = {
            "character_id": character_id,
            "variation": variation,
            "canvas_png": canvas_buffer.getvalue(),
            "mask_png": mask_buffer.getvalue(),
            "width": int(result.canvas_image.width),
            "height": int(result.canvas_image.height),
        }
        with self._retain_lock:
            self._reference_inset_pin = pin
        return self.reference_inset_state()

    def set_reference_inset_canvas(self, width: Any, height: Any) -> dict[str, Any]:
        """핀은 그대로 두고 **캔버스 크기만** 바꾼다.

        캔버스가 바뀌면 붙이는 배율과 마스크가 통째로 달라지므로 같은 원본으로 다시
        만든다. 핀이 없으면 아무것도 하지 않는다(화면이 배지를 안 그리는 상태다).
        """
        with self._retain_lock:
            pin = self._reference_inset_pin
            character_id = str(pin["character_id"]) if pin else ""
            variation = str(pin["variation"]) if pin else ""
        if not character_id:
            raise ValueError("고정된 레퍼런스 인셋이 없습니다.")
        return self.set_reference_inset_pin(character_id, variation, width, height)

    def clear_reference_inset_pin(self) -> bool:
        with self._retain_lock:
            had = self._reference_inset_pin is not None
            self._reference_inset_pin = None
        return had

    def reference_inset_state(self) -> dict[str, Any]:
        from utils.reference_inpaint_preprocess import REFERENCE_INSET_CANVAS_SIZES

        with self._retain_lock:
            pin = self._reference_inset_pin
            if not pin:
                return {"active": False}
            return {
                "active": True,
                "character_id": pin["character_id"],
                "variation": pin["variation"],
                "width": pin["width"],
                "height": pin["height"],
                # 고를 수 있는 목록을 함께 싣는다 - 화면이 표를 따로 들면 한쪽만
                # 고쳐져 서로 다른 말을 한다(SSOT 는 reference_inpaint_preprocess).
                "sizes": [list(size) for size in REFERENCE_INSET_CANVAS_SIZES],
            }

    def reference_inset_generation_params(self) -> dict[str, Any]:
        """plain NAI 생성에 주입할 인셋 오버라이드(핀 없으면 빈 dict).

        strength 1.0 / noise 0.0 = NovelAI 레퍼런스 인페인트 가이드 권장값.
        reference_inset_tag_required는 api_service가 최종 프롬프트에 2koma 인셋
        태그를 주입하는 근거, 마커는 Auto Gen plain 판정 + continuation의 라이브
        재조회 pop 근거다.
        """
        from core.auto_generation_flags import REFERENCE_INSET_PIN_MARKER

        with self._retain_lock:
            pin = self._reference_inset_pin
            if not pin:
                return {}
            return {
                "type": "inpaint",
                "image_bytes": pin["canvas_png"],
                "mask_bytes": pin["mask_png"],
                "width": pin["width"],
                "height": pin["height"],
                "strength": 1.0,
                "noise": 0.0,
                "add_original_image": True,
                "reference_inset_tag_required": True,
                REFERENCE_INSET_PIN_MARKER: True,
            }

    def pinned_candidate(self, pin_id: str) -> Optional[dict[str, Any]]:
        with self._retain_lock:
            pin = self._pinned_candidates.get(str(pin_id or "").strip())
            return dict(pin) if pin else None

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

    @staticmethod
    def _prompt_override(sidecar: dict[str, Any], variation: str = "") -> dict[str, Any]:
        """User prompt corrections for ONE image.

        primary는 sidecar 최상위 키(기존 계약), 바리에이션은 hash별 블록. 캐릭터
        단위 키를 바리에이션에 적용하면 바리에이션이 자기 PNG의 프롬프트 대신
        대표 이미지의 프롬프트로 표시/적용되는 누수가 생긴다.
        """
        if not variation:
            return sidecar if isinstance(sidecar, dict) else {}
        block = sidecar.get("variation_prompts") if isinstance(sidecar, dict) else None
        block = block.get(variation) if isinstance(block, dict) else None
        return block if isinstance(block, dict) else {}

    def _prompt_for(
        self,
        character_id: str,
        path: Path,
        sidecar: dict[str, Any],
        variation: str = "",
    ) -> tuple[str, str]:
        """(prompt, uc) for the image at ``path`` - its own NAI char block,
        overridden by the user's EDIT correction for THAT image if present."""
        meta = self._extract_prompt_meta(character_id, path)
        override = self._prompt_override(sidecar, variation)
        prompt = str(
            override["character_prompt"]
            if "character_prompt" in override
            else meta.get("character_prompt") or ""
        ).strip()
        uc = str(
            override["character_uc"]
            if "character_uc" in override
            else meta.get("character_uc") or ""
        ).strip()
        return prompt, uc

    def detail(self, character_id: str, variation: str = "") -> dict[str, Any]:
        """Character detail. ``variation`` selects WHICH image's prompt/UC are
        reported - each saved variation carries its own NAI character block."""
        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            root = self._owner_root(character_id)
            if root is None:
                raise FileNotFoundError(f"character {character_id} not found")
            primary = asset_storage.get_character_primary_path(character_id, root)
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
            origins = sidecar.get("variation_origins") if isinstance(sidecar.get("variation_origins"), dict) else {}
            for entry in variations:
                # 벤치 저장 시 기록된 생성 방식(inpaint|char_reference|enhance).
                # 기록 이전 저장분/승격 잔여 키는 빈 값으로 노출된다.
                entry["origin"] = str(origins.get(entry["hash"]) or "")
            variation = str(variation or "").strip()
            if variation:
                variation = self._validate_hash(variation)
                if not any(entry["hash"] == variation for entry in variations):
                    raise FileNotFoundError(f"variation {variation} not found")
                target = next(
                    path
                    for path in asset_storage.list_character_variations(character_id, root)
                    if path.stem == variation
                )
            else:
                target = primary
            prompt, character_uc = self._prompt_for(character_id, target, sidecar, variation)
            return {
                "id": character_id,
                "display_name": str(sidecar.get("display_name") or ""),
                "variation": variation,
                "character_prompt": prompt,
                "character_uc": character_uc,
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

    def update_prompt(
        self,
        character_id: str,
        character_prompt: str,
        character_uc: str = "",
        variation: str = "",
    ) -> dict[str, Any]:
        """Persist user-corrected prompt values without rewriting the source PNG.

        The correction is scoped to the image being viewed: primary edits land on
        the sidecar's top-level keys, variation edits on their own hash block.
        """
        self._bootstrap()
        prompt = str(character_prompt or "").strip()
        if not prompt:
            raise ValueError("character_prompt is required")
        uc = str(character_uc or "").strip()
        with self._lock:
            character_id = self._validate_id(character_id)
            variation = self._validate_hash(variation) if str(variation or "").strip() else ""
            root = self._ensure_current(character_id)
            if variation:
                # 존재 확인 - 고아 override가 sidecar에 쌓이지 않게 한다.
                if not any(
                    path.stem == variation
                    for path in asset_storage.list_character_variations(character_id, root)
                ):
                    raise FileNotFoundError(f"variation {variation} not found")
            meta = asset_storage.read_character_meta(character_id, root)
            if variation:
                block = meta.get("variation_prompts")
                block = dict(block) if isinstance(block, dict) else {}
                block[variation] = {"character_prompt": prompt, "character_uc": uc}
                meta["variation_prompts"] = block
            else:
                meta["character_prompt"] = prompt
                meta["character_uc"] = uc
            if not asset_storage.write_character_meta(character_id, meta, root):
                raise RuntimeError("failed to write character prompt metadata")
            return {
                "id": character_id,
                "variation": variation,
                "character_prompt": prompt,
                "character_uc": uc,
                "recovered": True,
            }

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

    def _prune_variation_sidecar(self, character_id: str, root: Path, variation_hash: str) -> None:
        """Drop per-variation sidecar entries for a hash that no longer exists."""
        meta = asset_storage.read_character_meta(character_id, root)
        changed = False
        for key in ("variation_prompts", "variation_origins"):
            block = meta.get(key)
            if isinstance(block, dict) and variation_hash in block:
                block = dict(block)
                block.pop(variation_hash, None)
                meta[key] = block
                changed = True
        if changed:
            asset_storage.write_character_meta(character_id, meta, root)

    def delete_variation(self, character_id: str, variation_hash: str) -> bool:
        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            variation_hash = self._validate_hash(variation_hash)
            self._ensure_current(character_id)
            for path in asset_storage.list_character_variations(character_id, self.write_root()):
                if path.stem == variation_hash:
                    deleted = asset_storage.delete_variation(character_id, path, root=self.write_root())
                    if deleted:
                        self._prune_variation_sidecar(character_id, self.write_root(), variation_hash)
                    return deleted
            return False

    def promote(self, character_id: str, variation_hash: str) -> bool:
        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            variation_hash = self._validate_hash(variation_hash)
            root = self._ensure_current(character_id)
            for path in asset_storage.list_character_variations(character_id, root):
                if path.stem != variation_hash:
                    continue
                if not asset_storage.promote_variation_to_primary(character_id, path, root=root):
                    return False
                # 승격 = primary와 바리에이션의 스왑. 이미지가 자리를 바꿨으므로
                # 프롬프트 보정도 함께 옮기지 않으면 남의 이미지에 붙는다.
                # (기존 primary는 새 해시의 바리에이션으로 보존되지만, 그 해시는
                # 이미지 바이트에서 재계산되므로 여기서 알 수 없다 - 보정은 버린다.)
                meta = asset_storage.read_character_meta(character_id, root)
                block = meta.get("variation_prompts")
                block = dict(block) if isinstance(block, dict) else {}
                promoted = block.pop(variation_hash, None)
                if isinstance(promoted, dict):
                    meta["character_prompt"] = str(promoted.get("character_prompt") or "")
                    meta["character_uc"] = str(promoted.get("character_uc") or "")
                else:
                    meta.pop("character_prompt", None)
                    meta.pop("character_uc", None)
                meta["variation_prompts"] = block
                origins = meta.get("variation_origins")
                origins = dict(origins) if isinstance(origins, dict) else {}
                origins.pop(variation_hash, None)
                meta["variation_origins"] = origins
                asset_storage.write_character_meta(character_id, meta, root)
                return True
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

        The asset becomes the ONLY enabled reference: every other CR frame is
        disabled (사용자 지시) so C1 + CR never blends a leftover reference from
        a previous session into this character's generation.
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
        target = existing if existing is not None else frame
        if existing is None:
            frames.append(frame)
        for item in frames:
            item["is_enabled"] = item is target
        service.save_storage(target)
        context._disable_all_vibe_frames()
        service._persist()

    def attach_reference_only(self, character_id: str, variation: str = "") -> dict[str, Any]:
        """에셋 이미지를 **레퍼런스로만** 붙인다. 슬롯 프롬프트는 건드리지 않는다.

        `apply_to_slot(with_reference=True)` 는 캐릭터 프롬프트까지 슬롯에 적용한다.
        Interactive 는 캐릭터 블록이 프롬프트를 소유하므로 그 경로를 쓰면 두 소스가
        다툰다(`character` 도구를 Interactive 에서 막아 둔 것과 같은 이유). 레퍼런스만
        원하는 자리에는 이 함수를 쓴다.

        회수·상호배제 규약은 `_attach_character_reference` 가 그대로 맡는다 —
        고른 것이 **유일하게 켜진** 레퍼런스가 되고 Vibe 프레임은 전부 꺼진다.
        """
        self._bootstrap()
        context = self.context
        if str(context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("character reference requires NAI mode")
        character_id = self._validate_id(character_id)
        variation = self._validate_hash(variation) if str(variation or "").strip() else ""
        path = self.resolve_image_path(character_id, variation)
        self._attach_character_reference(path)
        return {"ok": True, "id": character_id, "variation": variation}

    def _disable_all_character_reference_frames(self) -> bool:
        """C1 단독 적용의 계약 = CR 없는 깨끗한 상태(사용자 지시 2026-07-17).

        이전 세션/직전 C1+CR에서 켜둔 레퍼런스가 남아 있으면 단독 적용 캐릭터의
        생성에 몰래 섞인다 - 전부 끈다(프레임 자체는 보존, enable만 해제).
        """
        context = self.context
        service = context._character_reference_service()
        service._ensure_loaded()
        changed = False
        for item in context.character_reference_frames:
            if item.get("is_enabled"):
                item["is_enabled"] = False
                changed = True
        if changed:
            service._persist()
        return changed

    def apply_to_slot(
        self,
        character_id: str,
        variation: str = "",
        mode: str = "c1",
        with_reference: bool = False,
        with_inset: bool = False,
    ) -> dict[str, Any]:
        self._bootstrap()
        context = self.context
        if str(context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("character slot apply requires NAI mode")
        mode = str(mode or "c1").strip().lower()
        if mode not in {"c1", "add_slot"}:
            raise ValueError(f"unknown apply mode: {mode}")
        if with_inset:
            # 인셋은 C1 전용이며 CR과 상호배타(개념 중복 - 함께 켜면 안 된다).
            if mode != "c1":
                raise ValueError("reference inset requires C1 apply mode")
            with_reference = False
        character_id = self._validate_id(character_id)
        variation = self._validate_hash(variation) if str(variation or "").strip() else ""
        path = self.resolve_image_path(character_id, variation)
        root = self._owner_root(character_id)
        sidecar = asset_storage.read_character_meta(character_id, root) if root else {}
        # 선택된 이미지 자신의 캐릭터 블록을 적용한다(바리에이션이면 그 PNG의 것).
        prompt, uc = self._prompt_for(character_id, path, sidecar, variation)
        if not prompt:
            raise ValueError("no NAI character block in this image - cannot recover the character prompt")
        state = context._character_service().apply_asset(prompt, uc, mode)
        reference_attached = False
        references_disabled = False
        if with_reference:
            try:
                self._attach_character_reference(path)
                reference_attached = True
            except Exception as exc:
                print(f"[CharacterAsset] character reference attach failed: {exc}")
        elif mode == "c1":
            # C1 단독/인셋: 기존에 켜져 있던 CR을 전부 끈다(add_slot은 슬롯 추가만 -
            # CR 상태 불변). 인셋은 CR과 개념이 겹치므로 특히 함께 켜두면 안 된다.
            try:
                references_disabled = self._disable_all_character_reference_frames()
            except Exception as exc:
                print(f"[CharacterAsset] character reference disable failed: {exc}")
        reference_inset = None
        if with_inset:
            # C1 + 레퍼런스 인셋: 선택 이미지를 인셋 핀으로 고정한다. 실패 시
            # C1 적용 자체는 이미 끝난 상태 - 명시 에러로 알린다(조용한 절반 성공 금지).
            reference_inset = self.set_reference_inset_pin(character_id, variation)
        return {
            "ok": True,
            "state": state,
            "character_prompt": prompt,
            "character_uc": uc,
            "reference_attached": reference_attached,
            "references_disabled": references_disabled,
            "reference_inset": reference_inset,
        }

    # ------------------------------------------------ reference generation
    def build_generation_overrides(self, payload: dict[str, Any], candidate: int) -> dict[str, Any]:
        """Creation bench: a brand-new character on the fixed full-body scaffold.

        Composition is ``count + PREFIX + scaffold + POSTFIX`` - the count tag
        stays OUTSIDE any weight group the PREFIX opens (e.g. ``0.77::`` closed
        by the POSTFIX's ``::``), matching the Char Reference bench. The spec's
        artists/quality slots already produce exactly that order.
        """
        if str(self.context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("Character Asset generation requires NAI mode")
        payload = payload if isinstance(payload, dict) else {}
        # 슬롯머신(횟수 N)은 후보마다 다른 랜덤 프롬프트를 쓴다 - 배치 하나에
        # 후보별 프롬프트를 실어 request_id/상관관계를 그대로 유지한다.
        prompts = payload.get("character_prompts")
        if isinstance(prompts, list) and prompts:
            if not 0 <= candidate < len(prompts):
                raise ValueError("character_prompts is shorter than the requested count")
            character_prompt = str(prompts[candidate] or "").strip()
        else:
            character_prompt = str(payload.get("character_prompt") or "").strip()
        if not character_prompt:
            raise ValueError("character_prompt is required")
        character_uc = str(payload.get("character_uc") or "").strip()
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise ValueError("request_id is required")
        # 레퍼런스는 별개 모드가 아니라 스캐폴드에 얹는 레이어다(2축: base x reference).
        generation_mode = str(payload.get("generation_mode") or "scaffold").strip().lower()
        inpaint = payload.get("inpaint") if isinstance(payload.get("inpaint"), dict) else None
        if inpaint:
            # 인페인트 payload가 곧 모드다 - 프론트 상태와 어긋나도 payload가 권위.
            generation_mode = "inpaint"
        if generation_mode not in {"scaffold", "inpaint"}:
            raise ValueError(f"unknown creation mode: {generation_mode}")
        if generation_mode == "inpaint" and not inpaint:
            raise ValueError("inpaint mode requires an inpaint payload (source_pin_id + mask_png)")
        references = payload.get("references")
        references = [item for item in references if isinstance(item, dict)] if isinstance(references, list) else []
        prompt_source = str(payload.get("prompt_source") or "current").strip().lower()
        if prompt_source == "custom":
            # 생성 벤치도 CUSTOM 지원(사용자 지시 2026-07-17): 요청에 실린 일시
            # 프로파일 - negative 포함, 저장 없음. CR 게이트는 동봉 model로 판정.
            profile = self._custom_prompt_profile(payload.get("custom_profile"))
        else:
            # PRIMARY는 캐릭터가 있어야 성립 - 생성 벤치에선 _bench_prompt_profile이 거부.
            profile = self._bench_prompt_profile(
                "",
                prompt_source,
                str(payload.get("prompt_preset") or ""),
            )
        prefix = str(profile.get("prefix") or "").strip()
        postfix = str(profile.get("postfix") or "").strip()
        base_negative = str(profile.get("negative_prompt") or "").strip()
        extra_negative = str(payload.get("extra_negative") or "").strip()
        negative = ", ".join(part for part in (base_negative, extra_negative) if part)
        # 유효 모델(프로파일 override 우선)로 4.5 게이트를 판정한다.
        reference_params = self._creation_reference_params(references, profile)
        # TOCTOU 차단(Codex BLOCK): 레퍼런스가 붙는 요청은 게이트를 통과한 모델을
        # 그대로 고정한다 - enqueue까지의 모델 전환으로 CR이 조용히 drop되지 않게.
        frozen_model = self._effective_model_key(profile) if reference_params else ""

        from utils.reference_inpaint_preprocess import ReferenceGenerationSpec

        label = character_prompt.split(",")[0].strip()[:48] or "character asset"
        overrides = {
            # PRIMARY/PRESET only override generation-tuning values explicitly
            # stored in that source. CURRENT inherits the live session params.
            **dict(profile.get("params") or {}),
            # Correlation / suppression markers. NOT the characters routing:
            # characters/uc below are absorbed as NAICharacterData early binding
            # (headless_generation_service._extract_nai_data) — the dormant
            # api_service character_asset branch stays unreachable by design.
            "character_asset_request": True,
            "character_asset_request_id": request_id,
            "character_asset_candidate": int(candidate),
            # Creation flow marker. Deliberately NOT character_asset_bench: that
            # flag means "variation bench result for character X" and drives both
            # the variation candidate routing and save_bench_result provenance.
            # Error broadcasts only carry {requestId, candidate}, which is enough
            # because each overlay owns its own request_id.
            "character_asset_flow": "creation",
            # 2축 provenance: base(scaffold|inpaint) x reference 유무 - 후보 배지가
            # STD / STD+CR / INP / INP+CR을 구분한다.
            "character_asset_base_mode": generation_mode,
            "character_asset_has_reference": bool(reference_params),
            "_remote_queue_source": "Character Asset",
            "_remote_queue_label": label,
            # Generation content (Dev0714 parity: fixed full-body scaffold).
            "input": ReferenceGenerationSpec(
                base_subject=self._count_tag_for(character_prompt)
            ).build_prompt(
                artists=(prefix,) if prefix else (),
                quality_tags=(postfix,) if postfix else (),
            ),
            "negative_prompt": negative,
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
            # 아래 director 파라미터가 late-binding 억제기 역할도 겸한다 - 벤치
            # 레퍼런스가 없으면 세션 CR 프레임이 새어들지 않도록 플래그로 봉쇄.
            "_skip_character_reference_late_binding": True,
            "seed": -1,
            "seed_fixed": False,
            **reference_params,
        }
        if generation_mode == "inpaint":
            overrides.update(self._creation_inpaint_params(inpaint))
        return overrides

    def _creation_inpaint_params(self, inpaint: dict[str, Any]) -> dict[str, Any]:
        """핀된 후보 + 사용자 마스크를 NAI 인페인트 오버라이드로 변환한다.

        - 소스는 서버 핀(pin_candidate)이 붙잡은 원본 PNG - 히스토리/리스 퇴출과
          무관하게 유효하다. 핀이 없으면 명시 거부(다시 핀하라는 404).
        - 마스크는 require_exact_size: 벤치는 베이스 크기를 정확히 알므로
          리사이즈로 좌표계 버그를 숨기지 않는다. 1/8 축소+검증은 공유 유틸이
          수행한다(api_service는 무검증 x8 - 여기가 유일한 방어선).
        - strength 1.0 / noise 0.0 = 변형 벤치 인페인트 패리티.
          cropped_image_request 금지(bbox 축소 트랩).
        """
        from utils.inpaint_mask import decode_mask_to_small_png

        pin = self.pinned_candidate(str(inpaint.get("source_pin_id") or ""))
        if pin is None:
            raise FileNotFoundError("pinned candidate not found - pin the image again")
        try:
            decoded = decode_mask_to_small_png(
                str(inpaint.get("mask_png") or ""),
                (pin["width"], pin["height"]),
                require_exact_size=True,
            )
        except ValueError as exc:
            raise ValueError(f"inpaint mask rejected: {exc}") from exc
        return {
            "type": "inpaint",
            "image_bytes": pin["png"],
            "mask_bytes": decoded.small_png,
            "strength": 1.0,
            "noise": 0.0,
            "width": pin["width"],
            "height": pin["height"],
        }

    # ------------------------------------------------ variation bench
    def _bench_defaults_path(self) -> Path:
        return Path(self.context._save_path(CHARACTER_ASSET_DIR_NAME, BENCH_DEFAULTS_FILE))

    @classmethod
    def _strip_silent_scaffold(cls, text: str) -> str:
        """MAIN PROMPT에서 자세 스캐폴드를 걷어낸다.

        스캐폴드는 이제 build_bench_overrides가 조용히 주입한다(BENCH_SILENT_SCAFFOLD).
        입력창에 남아 있으면 이중으로 실려 나가므로, 예전에 저장된 값도 로드/저장
        시점에 제거한다(사용자 제보: char_reference MAIN PROMPT에 자동 입력됨).
        """
        cleaned = str(text or "")
        for tags in (_REFERENCE_PIVOT_CURRENT, _REFERENCE_PIVOT_LEGACY, _SILENT_SCAFFOLD_TAGS):
            cleaned = cls._prompt_pivot_pattern(tags).sub("", cleaned)
        # 스캐폴드를 들어낸 자리에 남는 콤마/공백 정리
        parts = [part.strip() for part in cleaned.split(",")]
        return ", ".join(part for part in parts if part)

    def bench_defaults(self) -> dict[str, Any]:
        """Per-mode bench form defaults. Main prompts are managed SEPARATELY per
        generation mode; a legacy flat file (pre mode-split) maps to inpaint."""
        defaults = {mode: dict(values) for mode, values in BENCH_MODE_DEFAULTS.items()}
        try:
            path = self._bench_defaults_path()
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if isinstance(data.get("main_prompt"), str):
                        # legacy flat layout -> inpaint mode values
                        data = {"inpaint": data}
                    for mode in BENCH_MODES:
                        block = data.get(mode)
                        if not isinstance(block, dict):
                            continue
                        for key in ("main_prompt", "extra_negative"):
                            if isinstance(block.get(key), str):
                                defaults[mode][key] = block[key]
                        # 스캐폴드가 silent 주입으로 바뀌기 전 저장분 정리
                        defaults[mode]["main_prompt"] = self._strip_silent_scaffold(
                            defaults[mode]["main_prompt"]
                        )
                    # 이전 기본값 그대로였던 저장분만 새 기본값으로 승격한다
                    # (사용자가 직접 바꾼 값은 건드리지 않음).
                    if defaults["inpaint"]["main_prompt"] == BENCH_LEGACY_DEFAULT_MAIN_PROMPT:
                        defaults["inpaint"]["main_prompt"] = BENCH_DEFAULT_MAIN_PROMPT
                    if defaults["inpaint"]["extra_negative"] == BENCH_LEGACY_DEFAULT_EXTRA_NEGATIVE:
                        defaults["inpaint"]["extra_negative"] = BENCH_DEFAULT_EXTRA_NEGATIVE
        except Exception as exc:
            print(f"[CharacterAsset] bench defaults load failed: {exc}")
        return defaults

    def save_bench_defaults(self, mode: str, main_prompt: str, extra_negative: str) -> None:
        mode = str(mode or "inpaint").strip().lower()
        if mode not in BENCH_MODES:
            mode = "inpaint"
        try:
            merged = self.bench_defaults()
            merged[mode] = {
                # 스캐폴드는 백엔드가 조용히 주입한다 - 입력창 값으로 되살리지 않는다.
                "main_prompt": self._strip_silent_scaffold(main_prompt),
                "extra_negative": str(extra_negative or ""),
            }
            path = self._bench_defaults_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            print(f"[CharacterAsset] bench defaults save failed: {exc}")

    def _pe_pre_post(self) -> tuple[str, str]:
        """Current PREFIX/POSTFIX from the user's Prompt Engineering module."""
        try:
            from core.prompt_engineering_settings import get_prompt_engineering_store

            settings = get_prompt_engineering_store(self.context).collect_settings()
            return (
                str(settings.get("pre_prompt") or "").strip(),
                str(settings.get("post_prompt") or "").strip(),
            )
        except Exception as exc:
            print(f"[CharacterAsset] prompt engineering settings unavailable: {exc}")
            return "", ""

    @staticmethod
    def _prompt_pivot_pattern(tags: tuple[str, ...]) -> re.Pattern[str]:
        parts = [re.escape(tag).replace(r"\ ", r"\s+") for tag in tags]
        return re.compile(r"(?<![\w:])" + r"\s*,\s*".join(parts) + r"(?![\w:])", re.IGNORECASE)

    @classmethod
    def _split_reference_prompt(cls, prompt: str) -> tuple[str, str] | None:
        """Split a primary prompt around the fixed reference scaffold.

        Both the current scaffold and the older compact scaffold used by the
        user's existing primary.png files are accepted. Count tags surrounding
        the scaffold are routing tags, not Prompt Engineering PREFIX content.
        """
        text = str(prompt or "").strip()
        if not text:
            return None
        match = None
        for tags in (_REFERENCE_PIVOT_CURRENT, _REFERENCE_PIVOT_LEGACY):
            candidate = cls._prompt_pivot_pattern(tags).search(text)
            if candidate is not None:
                match = candidate
                break
        if match is None:
            return None

        prefix = text[:match.start()].strip(" ,")
        postfix = text[match.end():].strip(" ,")
        prefix_parts = [part.strip() for part in prefix.split(",")]
        while prefix_parts and _COUNT_TAG_EDGE_RE.fullmatch(prefix_parts[0]):
            prefix_parts.pop(0)
        while prefix_parts and _COUNT_TAG_EDGE_RE.fullmatch(prefix_parts[-1]):
            prefix_parts.pop()
        prefix = ", ".join(part for part in prefix_parts if part)
        return prefix, postfix

    @staticmethod
    def _metadata_value(sources: tuple[dict[str, Any], ...], aliases: tuple[str, ...]) -> Any:
        for source in sources:
            for alias in aliases:
                value = source.get(alias)
                if value is not None and value != "":
                    return value
        return None

    def _normalize_nai_model(self, value: Any, source: Any = "") -> str:
        source_text = str(source or "")
        raw = str(value or "").strip()
        if raw.upper().startswith("NAID"):
            return raw
        # 사용자가 등록한 커스텀 모델이 먼저다 - 내장 라벨과 겹칠 수 있다.
        try:
            custom_key = self.context._nai_model_registry().key_for_api_model(raw)
            if custom_key:
                return custom_key
        except Exception:
            pass
        # 내장 모델은 **계약에서 파생**한다(해시·와이어 이름·라벨·계열 순).
        # 예전에는 Source 마커 표와 와이어 이름 표를 각각 하드코딩해 뒀는데 V5 를
        # 추가할 때 둘 다 안 고쳐서, V5 이미지의 라벨이 키 자리로 흘러가
        # `등록되지 않은 NAI 모델 키입니다: NOVELAI DIFFUSION V5` 로 생성이 막혔다
        # (사용자 제보 2026-08-22).
        from core.nai_model_contract import nai_key_from_metadata

        resolved = nai_key_from_metadata(raw, source_text)
        if resolved:
            return resolved
        # ⚠️ **못 찾으면 원문을 돌려주지 않는다.** 라벨을 키인 척 넘기면 resolver 가
        # 터져 생성 자체가 막힌다. 빈 값이면 호출부가 모델을 안 건드리고 지금 고른
        # 것을 그대로 쓴다 - 모르는 모델 때문에 사용자의 선택을 뒤엎지 않는다.
        return ""

    def _profile_generation_params(self, *sources: dict[str, Any]) -> dict[str, Any]:
        valid_sources = tuple(source for source in sources if isinstance(source, dict))
        result: dict[str, Any] = {}
        for target, aliases in _BENCH_PROFILE_PARAM_ALIASES.items():
            value = self._metadata_value(valid_sources, aliases)
            if value is not None and value != "":
                if target in {"SMEA", "DYN", "VAR+", "DECRISP"}:
                    if isinstance(value, str):
                        value = value.strip().lower() not in {"", "0", "false", "none", "null"}
                    else:
                        value = bool(value)
                result[target] = value
        source = self._metadata_value(valid_sources, ("Source", "source"))
        if "model" in result or source:
            model = self._normalize_nai_model(result.get("model"), source)
            if model:
                result["model"] = model
        return result

    def _primary_prompt_profile(self, character_id: str) -> dict[str, Any]:
        primary = self.resolve_image_path(character_id)
        try:
            cache_key = (str(primary), primary.stat().st_mtime_ns)
        except OSError as exc:
            return {"available": False, "reason": f"primary image unavailable: {exc}"}
        cached = self._bench_profile_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        extracted: dict[str, Any] = {}
        try:
            # Same shared extractor used by Metadata Viewer for NAI Comment,
            # Source, Description and stealth-PNG metadata.
            from utils.image_info import extract_embedded_metadata

            extracted = extract_embedded_metadata(primary.read_bytes()) or {}
        except Exception as exc:
            profile = {"available": False, "reason": f"primary metadata extraction failed: {exc}"}
            self._bench_profile_cache[cache_key] = profile
            return dict(profile)

        comment = extracted.get("Comment") if isinstance(extracted.get("Comment"), dict) else {}
        parameters = extracted.get("parameters") if isinstance(extracted.get("parameters"), dict) else {}
        sources = (extracted, comment, parameters)
        prompt = str(self._metadata_value(sources, ("prompt", "input", "Description", "description")) or "")
        split = self._split_reference_prompt(prompt)
        if split is None:
            profile = {
                "available": False,
                "reason": "primary prompt does not contain a recognized standard-reference pivot",
            }
        else:
            prefix, postfix = split
            negative = str(self._metadata_value(sources, ("uc", "negative", "negative_prompt")) or "")
            profile = {
                "available": True,
                "prefix": prefix,
                "postfix": postfix,
                "negative_prompt": negative,
                "params": self._profile_generation_params(extracted, comment, parameters),
            }
            # params에서만 유도되므로 mtime 캐시에 넣어도 안전하다.
            profile["cr_capable"] = self._profile_cr_capability(profile, self.context)
        if len(self._bench_profile_cache) > 32:
            self._bench_profile_cache.clear()
        self._bench_profile_cache[cache_key] = profile
        return dict(profile)

    def _preset_prompt_profile(
        self,
        preset_name: str,
        preset_names: Optional[list[str]] = None,
        thumbnail_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """preset_names/thumbnail_url은 bench_prompt_profiles의 목록 루프가
        전달하는 벌크 값 - 프리셋별 list_preset_names/stat 재탐색(O(n^2))을 피한다."""
        from core.prompt_engineering_settings import (
            get_prompt_engineering_store,
            preset_thumbnail_url as resolve_thumbnail_url,
        )

        name = str(preset_name or "").strip()
        if not name or name == "*randomized":
            return {"available": False, "reason": "Prompt Engineering preset is required"}
        store = get_prompt_engineering_store(self.context)
        known_names = preset_names if preset_names is not None else store.list_preset_names("NAI")
        if name not in known_names:
            return {"available": False, "reason": f"Prompt Engineering preset not found: {name}"}
        data = store.read_preset_data(name, "NAI")
        if not data:
            return {"available": False, "reason": f"Prompt Engineering preset is empty: {name}"}
        module_settings = data.get("module_settings") if isinstance(data.get("module_settings"), dict) else {}
        main_settings = data.get("main_settings") if isinstance(data.get("main_settings"), dict) else {}
        profile = {
            "available": True,
            "name": name,
            "prefix": str(module_settings.get("pre_prompt") or "").strip(),
            "postfix": str(module_settings.get("post_prompt") or "").strip(),
            "negative_prompt": str(
                main_settings.get("negative") or main_settings.get("negative_prompt") or ""
            ).strip(),
            # Quick Preset floating preview parity: thumbnail is file-derived
            # (previews dir) — preset JSON never carries thumbnail_url.
            "description": str(data.get("description") or ""),
            "thumbnail_url": (
                thumbnail_url
                if thumbnail_url is not None
                else resolve_thumbnail_url(self.context, name, "NAI")
            ),
            "params": self._profile_generation_params(main_settings),
        }
        profile["cr_capable"] = self._profile_cr_capability(profile, self.context)
        return profile

    def _current_prompt_profile(self) -> dict[str, Any]:
        prefix, postfix = self._pe_pre_post()
        return {
            "available": True,
            "prefix": prefix,
            "postfix": postfix,
            "negative_prompt": str(getattr(self.context, "negative_prompt_text", "") or "").strip(),
            # Empty by design: current remote params are inherited by enqueue.
            "params": {},
        }

    def bench_prompt_profiles(self, character_id: str = "") -> dict[str, Any]:
        """Prompt profiles for a bench form.

        ``character_id`` is optional: the CREATION bench has no character yet,
        so PRIMARY is simply unavailable there and only CURRENT/PRESET apply.
        """
        character_id = str(character_id or "").strip()
        if character_id:
            character_id = self._validate_id(character_id)
            primary = self._primary_prompt_profile(character_id)
        else:
            primary = {
                "available": False,
                "reason": "no primary image yet - PRIMARY applies to existing characters only",
            }
        current = self._current_prompt_profile()
        presets: list[dict[str, Any]] = []
        try:
            from core.prompt_engineering_settings import (
                get_prompt_engineering_store,
                preset_thumbnail_url_map,
            )

            store = get_prompt_engineering_store(self.context)
            names = store.list_preset_names("NAI")
            thumbnails = preset_thumbnail_url_map(self.context, names, "NAI")
            for name in names:
                profile = self._preset_prompt_profile(
                    name, preset_names=names, thumbnail_url=thumbnails.get(name, "")
                )
                if profile.get("available"):
                    presets.append(profile)
        except Exception as exc:
            print(f"[CharacterAsset] prompt preset list unavailable: {exc}")
        return {"primary": primary, "current": current, "presets": presets}

    # CUSTOM 편집 허용 파라미터(사용자 지시 2026-07-17): CFG Scale/CFG Rescale/
    # Sampler/Scheduler/VAR+. model은 시드 프로파일의 값 통과(출력 전용 - effective
    # -model 게이트 판정에 필요). 그 외 키는 화이트리스트로 차단해 요청 주입으로
    # 임의 오버라이드(steps 폭주, 플래그 조작 등)가 실리는 것을 막는다.
    _CUSTOM_PROFILE_NUMERIC_KEYS = (("cfg_scale", 0.0, 30.0), ("cfg_rescale", 0.0, 1.0))

    def _custom_prompt_profile(self, raw: Any) -> dict[str, Any]:
        """CUSTOM: 요청에 실려온 일시 프로파일. 어디에도 저장하지 않는다.

        영구 변경은 원본 이미지 교체가 유일한 경로(사용자 계약) - 이 프로파일은
        해당 생성 요청에만 유효하다.
        """
        if not isinstance(raw, dict):
            raise ValueError("custom prompt profile payload is required")
        params_raw = raw.get("params") if isinstance(raw.get("params"), dict) else {}
        params: dict[str, Any] = {}
        for key in ("model", "sampler", "scheduler"):
            value = params_raw.get(key)
            if value is None or value == "":
                continue
            # dict/list 등을 str()로 뭉개 통과시키지 않는다(Codex CONCERN).
            if not isinstance(value, str):
                raise ValueError(f"custom {key} must be a string")
            value = value.strip()
            if value:
                params[key] = value
        for key, low, high in self._CUSTOM_PROFILE_NUMERIC_KEYS:
            value = params_raw.get(key)
            if value is None or value == "":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError(f"invalid custom {key}: {value!r}")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid custom {key}: {value!r}") from exc
            if not low <= number <= high:
                raise ValueError(f"custom {key} out of range ({low}~{high}): {number}")
            params[key] = number
        if "VAR+" in params_raw:
            varplus = params_raw.get("VAR+")
            if isinstance(varplus, str):
                varplus = varplus.strip().lower() not in {"", "0", "false", "none", "null"}
            # False도 명시 전달한다 - 생략하면 라이브 세션의 VAR+가 그대로 상속돼
            # 체크 해제가 무력해진다(Codex CONCERN: enqueue는 live 상속 후 override).
            params["VAR+"] = bool(varplus)
        profile = {
            "available": True,
            "prefix": str(raw.get("prefix") or "").strip(),
            "postfix": str(raw.get("postfix") or "").strip(),
            "negative_prompt": str(raw.get("negative_prompt") or "").strip(),
            "params": params,
        }
        profile["cr_capable"] = self._profile_cr_capability(profile, self.context)
        return profile

    def _bench_prompt_profile(self, character_id: str, source: str, preset_name: str = "") -> dict[str, Any]:
        source = str(source or "current").strip().lower()
        if source not in BENCH_PROMPT_SOURCES:
            raise ValueError(f"unknown prompt profile source: {source}")
        if source == "primary":
            if not str(character_id or "").strip():
                # 생성 벤치에는 대표 이미지가 없다 - 조용한 폴백 대신 명시 거부.
                raise ValueError("PRIMARY profile requires an existing character")
            profile = self._primary_prompt_profile(character_id)
        elif source == "preset":
            profile = self._preset_prompt_profile(preset_name)
        else:
            profile = self._current_prompt_profile()
        if not profile.get("available"):
            raise ValueError(str(profile.get("reason") or f"{source} prompt profile unavailable"))
        return profile

    @staticmethod
    def _count_tag_for(character_prompt: str) -> str:
        """1girl/1boy by the girl/boy count tag in the user's character prompt.

        Count-prefixed forms are normalized ("1boy"/"2boys" -> boy): a bare
        \\b regex misses "1boy" because there is no word boundary between the
        digit and the letter (Codex plan review).
        """
        text = str(character_prompt or "")
        tags = [tag.strip().lower() for tag in text.split(",")]
        if any(_COUNT_BOY_TAG_RE.match(tag) for tag in tags):
            return "1boy"
        if any(_COUNT_GIRL_TAG_RE.match(tag) for tag in tags):
            return "1girl"
        # 여러 단어로 된 태그 안의 boy(예: "school boy"). "cowboy"는 단어 경계가
        # 없어 걸리지 않는다.
        if re.search(r"\b\d*boys?\b", text, re.IGNORECASE):
            return "1boy"
        return "1girl"

    @staticmethod
    def _bench_reference_scale(value: Any, default: float, label: str) -> float:
        raw = default if value is None or value == "" else value
        try:
            parsed = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid Character Reference {label}") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"invalid Character Reference {label}")
        return round(max(0.0, min(1.0, parsed)) * 20) / 20.0

    # ------------------------------------------------------ random character
    def _random_pool(self, name: str) -> list[str]:
        """Lazy-load a data/random_*.txt pool (line = one comma-separated set).

        경로 해석은 FilterDataManager 선례를 따른다: 쓰기 가능한 data_dir 우선,
        없으면 번들 리소스 data, 마지막으로 리포 data. 파일이 크므로(수 MB)
        서비스 인스턴스에 1회 캐시한다.
        """
        cached = self._random_pools.get(name)
        if cached is not None:
            return cached
        candidates: list[Path] = []
        runtime_paths = getattr(self.context, "runtime_paths", None)
        if runtime_paths is not None:
            try:
                candidates.append(Path(runtime_paths.data_dir) / name)
            except Exception:
                pass
            try:
                candidates.append(Path(runtime_paths.resource_path("data")) / name)
            except Exception:
                pass
        candidates.append(Path(__file__).resolve().parents[1] / "data" / name)
        lines: list[str] = []
        for candidate in candidates:
            try:
                if not candidate.is_file():
                    continue
                lines = [
                    line.strip()
                    for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if line.strip()
                ]
            except OSError as exc:
                print(f"[CharacterAsset] random pool read failed ({candidate}): {exc}")
                continue
            if lines:
                break
        if not lines:
            raise FileNotFoundError(f"random pool is unavailable: {name}")
        self._random_pools[name] = lines
        return lines

    @staticmethod
    def _split_pool_line(line: str) -> list[str]:
        seen: list[str] = []
        for tag in str(line or "").split(","):
            clean = tag.strip()
            if clean and clean not in seen:
                seen.append(clean)
        return seen

    def roll_random_character(self, parts: Any = (), gender: str = "girl") -> dict[str, Any]:
        """Roll random appearance/outfit tag sets for the creation bench.

        parts에 없는 카테고리는 굴리지 않는다(프론트가 기존 태그를 유지) - 성별은
        토글이라 항상 반환한다.
        """
        import random

        requested = {str(part).strip().lower() for part in (parts or []) if str(part).strip()}
        unknown = requested - set(RANDOM_CHARACTER_POOLS)
        if unknown:
            raise ValueError(f"unknown random parts: {', '.join(sorted(unknown))}")
        gender = str(gender or "girl").strip().lower()
        if gender not in RANDOM_GENDER_TAGS:
            raise ValueError(f"unknown gender: {gender}")
        result: dict[str, Any] = {"gender": gender}
        for part, file_name in RANDOM_CHARACTER_POOLS.items():
            if part not in requested:
                continue
            pool = self._random_pool(file_name)
            result[part] = self._split_pool_line(random.choice(pool))
        return result

    def _outfit_strip_vocabulary(self) -> set[str]:
        """의상 스왑 시 걷어낼 태그 어휘 = clothes_list − HEAD_NECK_FACE.

        어느 한쪽만으로는 안 된다(실측):
        - clothing_regions.json은 429태그뿐이라 'front-tie bikini top' 같은 의상이
          UNASSIGNED로 빠져 남는다.
        - clothes_list(11k)만 쓰면 'hair ornament'/'hairclip'/'ribbon'까지 지워
          캐릭터 정체성이 무너진다.
        둘을 교차해 "옷은 벗기고 머리 장식은 남긴다"를 만든다(사용자 결정).
        """
        cached = getattr(self, "_outfit_strip_cache", None)
        if cached is not None:
            return cached
        manager = getattr(self.context, "filter_data_manager", None)
        if manager is None:
            # 어휘 로더는 랜덤 프롬프트 서비스가 소유한다(같은 data/ 경로 정책).
            # 접근 패턴은 headless_conditional_prompt_service:397의 선례를 따른다.
            try:
                from core.headless_random_prompt_service import HeadlessRandomPromptService

                service = getattr(self.context, "headless_random_prompt_service", None)
                if service is None:
                    service = HeadlessRandomPromptService(self.context)
                    self.context.headless_random_prompt_service = service
                service._ensure_filter_data_manager()
                manager = getattr(self.context, "filter_data_manager", None)
            except Exception as exc:
                print(f"[CharacterAsset] filter data manager unavailable: {exc}")
        if manager is None:
            raise RuntimeError("clothing vocabulary is unavailable")
        clothes = {str(tag).strip() for tag in (getattr(manager, "clothes_list", None) or []) if str(tag).strip()}
        vocabulary = {
            tag for tag in clothes
            if manager.get_clothing_region(tag) != OUTFIT_KEEP_REGION
        }
        if not vocabulary:
            raise RuntimeError("clothing vocabulary is empty")
        self._outfit_strip_cache = vocabulary
        return vocabulary

    def roll_outfit_swap(self, prompt: str, owned: Any = ()) -> dict[str, Any]:
        """Swap the outfit tags of an existing character prompt.

        생성 벤치와 달리 프롬프트가 에셋 PNG에서 온 기존 의상 태그로 시작하므로,
        슬롯 소유 태그만으로는 첫 굴림에서 옛 옷이 남는다. 어휘 기반으로 걷어낸다.
        정체성 태그(외형/머리 장식)는 순서를 지켜 앞에 남고 새 의상이 뒤에 붙는다.
        """
        import random

        strip_vocabulary = self._outfit_strip_vocabulary()
        owned_set = {str(tag).strip() for tag in (owned or []) if str(tag).strip()}
        kept: list[str] = []
        for raw in str(prompt or "").split(","):
            tag = raw.strip()
            if not tag or tag in kept:
                continue
            if tag in owned_set or tag in strip_vocabulary:
                continue
            kept.append(tag)
        outfit = self._split_pool_line(random.choice(self._random_pool(RANDOM_CHARACTER_POOLS["outfit"])))
        composed = kept + [tag for tag in outfit if tag not in kept]
        return {"prompt": ", ".join(composed), "outfit": outfit}

    # -------------------------------------------------- creation references
    def reference_storage_path(self, file_hash: str) -> Optional[Path]:
        """Resolve a CR storage PNG by hash under the runtime save-dir policy.

        고정 경로 대신 scan_storage와 같은 _existing_save_dirs 정책을 쓴다(Codex).
        해시는 16자리 hex로 제한해 path traversal을 원천 차단한다.
        """
        file_hash = self._validate_hash(file_hash)
        for images_dir in self.context._existing_save_dirs("character_reference", "images"):
            candidate = Path(images_dir) / f"{file_hash}.png"
            try:
                resolved = candidate.resolve()
                if resolved.is_file() and resolved.parent == Path(images_dir).resolve():
                    return resolved
            except OSError:
                continue
        return None

    def _validate_reference_bytes(self, data: bytes) -> None:
        """CR 레퍼런스 입력 검증.

        캐릭터 에셋 PNG(_validate_image_bytes)와 달리 PNG 서명을 요구하지 않는다 -
        레퍼런스는 NAI 메타데이터를 실어나르지 않고, frame_from_bytes가 어떤 포맷이든
        RGBA PNG로 정규화한다(CR 모듈 업로드와 같은 의미). UI가 image/*를 허용하는데
        서버가 PNG만 받으면 계약이 어긋난다(Codex).
        """
        from PIL import Image

        if not data:
            raise ValueError("image payload is empty")
        if len(data) > MAX_ASSET_BYTES:
            raise ValueError("image is too large")
        try:
            with Image.open(io.BytesIO(data)) as opened:
                width, height = opened.size
                if width * height > MAX_ASSET_PIXELS:
                    raise ValueError("image resolution is too large")
                opened.load()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"unsupported image payload: {exc}")

    def save_reference_image(self, data: bytes) -> dict[str, Any]:
        """Store a creation-bench reference in the CR image library.

        세션 프레임(character_reference_frames)은 건드리지 않는다 - set_param을
        어떤 경로로도 호출하지 않는다(Codex). 저장소는 write-once 자산 라이브러리라
        모델 독립적으로 허용하고, 실제 사용/생성 시점에 유효 모델을 검사한다.
        """
        self._validate_reference_bytes(data)
        service = self.context._character_reference_service()
        frame = service.frame_from_bytes(data, file_name="creation_bench.png", enabled=False)
        service.save_storage(frame)
        return {
            "file_hash": frame["file_hash"],
            "file_name": frame["file_name"],
            "thumbnail": frame.get("thumbnail", ""),
        }

    def reference_storage_list(self) -> dict[str, Any]:
        return self.context._character_reference_service().scan_storage()

    @staticmethod
    def _profile_cr_capability(
        profile: dict[str, Any],
        context: Any = None,
    ) -> Optional[bool]:
        """프로파일이 model을 덮어쓸 때만 CR 가능 여부를 판정한다(None = live 위임).

        PRESET/PRIMARY params의 model은 라이브 세션 모델을 덮어쓰므로, 라이브가
        4.5여도 실제 요청은 4.0이 될 수 있다. 생성 경로와 같은 모델 계약으로
        effective model의 Character Reference 기능을 판정해야 한다.
        """
        params = profile.get("params") if isinstance(profile, dict) else None
        model = str((params or {}).get("model") or "").strip()
        if not model:
            return None
        return resolve_nai_model_for_context(
            context,
            model,
        ).supports_character_reference

    def _effective_model_key(self, profile: dict[str, Any]) -> str:
        """모델의 최종 권위 = 프로파일이 덮어쓴 값 우선, 없으면 라이브 세션 값.

        PRESET params가 model을 포함하면 라이브 모델이 4.5여도 실제 요청은 4.0이 될
        수 있다. 따라서 Character Reference 게이트는 이 값으로 판단한다.
        """
        params = profile.get("params") if isinstance(profile, dict) else None
        model = str((params or {}).get("model") or "").strip()
        if model:
            return model
        live = getattr(self.context, "_remote_state_service", None)
        try:
            return str(live().current_model_key() or "") if callable(live) else ""
        except Exception:
            return ""

    def _creation_reference_params(
        self,
        references: list[dict[str, Any]],
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Build director params for creation-bench references (request-local).

        active_params()와 동형이나 세션 프레임이 아니라 요청 payload의 storage
        해시 목록을 쓴다. fidelity는 여기서 반전한다(UI 0.8 -> secondary 0.2).
        """
        from PIL import Image

        if not references:
            return {}
        model_key = self._effective_model_key(profile)
        model_spec = (
            resolve_nai_model_for_context(self.context, model_key)
            if model_key
            else None
        )
        if model_spec is not None and not model_spec.supports_character_reference:
            # 조용한 drop 금지: 비지원 모델이면 명시 거부(Codex).
            raise ValueError(
                "Character Reference requires a model with the v4.5 compatibility "
                f"profile (effective model: {model_key})"
            )
        service = self.context._character_reference_service()
        descriptions: list[dict[str, Any]] = []
        images: list[str] = []
        extracted: list[int] = []
        strengths: list[float] = []
        secondary: list[float] = []
        for reference in references:
            file_hash = self._validate_hash(str(reference.get("file_hash") or ""))
            path = self.reference_storage_path(file_hash)
            if path is None:
                raise FileNotFoundError(f"reference image not found: {file_hash}")
            reference_type = str(reference.get("reference_type") or "character&style").strip().lower()
            if reference_type not in BENCH_REFERENCE_TYPES:
                raise ValueError(f"unknown Character Reference type: {reference_type}")
            strength = self._bench_reference_scale(reference.get("strength", 1.0), 1.0, "strength")
            fidelity = self._bench_reference_scale(reference.get("fidelity", 0.8), 0.8, "fidelity")
            cache_key = (str(path), path.stat().st_mtime_ns)
            cached = self._bench_reference_cache.get(cache_key)
            if cached is None:
                with Image.open(path) as opened:
                    opened.load()
                    cached = service.image_data(opened)
                if len(self._bench_reference_cache) > 8:
                    self._bench_reference_cache.clear()
                self._bench_reference_cache[cache_key] = cached
            descriptions.append({
                "caption": {"base_caption": reference_type, "char_captions": []},
                "legacy_uc": False,
            })
            images.append(cached)
            extracted.append(1)
            strengths.append(strength)
            secondary.append(round((1.0 - fidelity) * 20) / 20.0)
        return {
            "director_reference_descriptions": descriptions,
            "director_reference_images": images,
            "director_reference_information_extracted": extracted,
            "director_reference_strength_values": strengths,
            "director_reference_secondary_strength_values": secondary,
            "controlnet_strength": 1,
            "inpaintImg2ImgStrength": 1,
            "normalize_reference_strength_multiple": True,
        }

    def _bench_reference_params(
        self,
        character_id: str,
        reference_type: str = "character&style",
        strength: Any = 0.8,
        fidelity: Any = 0.9,
    ) -> dict[str, Any]:
        """Late-bind the character's primary image as a Character Reference for
        THIS request only (mirrors HeadlessCharacterReferenceService.active_params;
        variation-bench defaults are S 0.8 / F 0.9, sliders may override).
        image_data() normalizes any resolution onto the nearest NAI canvas."""
        from PIL import Image

        reference_type = str(reference_type or "character&style").strip().lower()
        if reference_type not in BENCH_REFERENCE_TYPES:
            raise ValueError(f"unknown Character Reference type: {reference_type}")
        strength = self._bench_reference_scale(strength, 1.0, "strength")
        fidelity = self._bench_reference_scale(fidelity, 0.8, "fidelity")
        primary = self.resolve_image_path(character_id)
        try:
            cache_key = (str(primary), primary.stat().st_mtime_ns)
        except OSError as exc:
            raise FileNotFoundError(f"primary image unavailable: {exc}")
        cached = self._bench_reference_cache.get(cache_key)
        if cached is None:
            reference_service = self.context._character_reference_service()
            with Image.open(primary) as opened:
                opened.load()
                cached = reference_service.image_data(opened)
            if len(self._bench_reference_cache) > 8:
                self._bench_reference_cache.clear()
            self._bench_reference_cache[cache_key] = cached
        return {
            "director_reference_descriptions": [{
                "caption": {"base_caption": reference_type, "char_captions": []},
                "legacy_uc": False,
            }],
            "director_reference_images": [cached],
            "director_reference_information_extracted": [1],
            "director_reference_strength_values": [strength],
            "director_reference_secondary_strength_values": [
                round((1.0 - fidelity) * 20) / 20.0
            ],
            "controlnet_strength": 1,
            "inpaintImg2ImgStrength": 1,
            "normalize_reference_strength_multiple": True,
        }

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
        """Overrides for one variation candidate, per generation mode.

        - "inpaint" (Dev0714 parity): reference-inset inpaint on the 1152x896
          canvas - img2img-shaped overrides, fixed strength 1.0 / noise 0.0,
          reference inset tag, NO cropped_image_request (bbox shrink trap).
        - "char_reference": no inpaint plumbing - the primary image is
          late-bound as a Character Reference and a normal 768x1344 generation
          runs.

        Prompt composition (PREFIX/POSTFIX from the Prompt Engineering module):
          inpaint        = {1girl|1boy} + MAIN + PREFIX + "solo" + POSTFIX
                           (MAIN leads after the count tag - NAI inpainting spec
                           needs the 2koma scaffold up front)
          char_reference = {1girl|1boy} + PREFIX + MAIN + "solo" + POSTFIX
        """
        from utils.reference_inpaint_preprocess import VariationInpaintSpec

        if str(self.context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("variation bench requires NAI mode")
        payload = payload if isinstance(payload, dict) else {}
        generation_mode = str(payload.get("generation_mode") or "inpaint").strip().lower()
        if generation_mode not in BENCH_MODES:
            raise ValueError(f"unknown generation mode: {generation_mode}")
        character_id = self._validate_id(str(payload.get("id") or ""))
        character_prompt = str(payload.get("character_prompt") or "").strip()
        if not character_prompt:
            raise ValueError("character_prompt is required")
        character_uc = str(payload.get("character_uc") or "").strip()
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise ValueError("request_id is required")
        main_prompt = str(payload.get("main_prompt") or "").strip()
        extra_negative = str(payload.get("extra_negative") or "").strip()
        prompt_source = str(payload.get("prompt_source") or "current").strip().lower()
        prompt_preset = str(payload.get("prompt_preset") or "").strip()
        if prompt_source == "custom":
            # CUSTOM = 요청에 실린 일시 프로파일(저장소 없음). 시드의 model이
            # 함께 오므로 아래 CR effective-model 게이트가 그대로 판정한다.
            profile = self._custom_prompt_profile(payload.get("custom_profile"))
        else:
            profile = self._bench_prompt_profile(character_id, prompt_source, prompt_preset)
        base_negative = str(profile.get("negative_prompt") or "").strip()
        negative = ", ".join(part for part in (base_negative, extra_negative) if part)
        prefix = str(profile.get("prefix") or "").strip()
        postfix = str(profile.get("postfix") or "").strip()
        label = character_prompt.split(",")[0].strip()[:40] or character_id
        common = {
            # PRIMARY/PRESET only override generation-tuning values explicitly
            # stored in that source. CURRENT inherits the live session params.
            **dict(profile.get("params") or {}),
            "negative_prompt": negative,
            "random_resolution": False,
            "sketchbook_character_prompts": [(character_prompt, character_uc)],
            "character_asset_request": True,
            "character_asset_request_id": request_id,
            "character_asset_candidate": int(candidate),
            "character_asset_bench": True,
            "character_asset_bench_character": character_id,
            "character_asset_bench_mode": generation_mode,
            "character_asset_bench_prompt_source": prompt_source,
            "character_asset_bench_prompt_preset": prompt_preset if prompt_source == "preset" else "",
            "_remote_queue_source": "Character Asset",
            "_remote_queue_label": f"variation: {label}",
            "seed": -1,
            "seed_fixed": False,
            "_skip_vibe_transfer_late_binding": True,
            "wildcard_standalone": True,
        }

        if generation_mode == "char_reference":
            # 게이트 권위 = effective model. 프로파일이 model을 덮으면(PRIMARY/PRESET)
            # 라이브 모델 판정은 무의미하다. 생성 경로와 같은 모델 계약을 사용한다.
            cr_capable = self._profile_cr_capability(profile, self.context)
            if cr_capable is False:
                forced_model = str((profile.get("params") or {}).get("model") or "")
                raise ValueError(
                    "Char Reference mode requires a NAI 4.5 model "
                    f"(selected profile forces model: {forced_model})"
                )
            if cr_capable is None:
                is_naid45 = getattr(self.context, "_is_naid45_model", None)
                if callable(is_naid45) and not is_naid45():
                    raise ValueError("Char Reference mode requires a NAI 4.5 model")
            # TOCTOU 차단(Codex BLOCK): 게이트를 통과한 모델을 요청에 고정한다.
            # 안 그러면 enqueue까지의 모델 전환(4.5->4.0)으로 api_service가 director
            # reference를 조용히 버린 채 과금 생성이 진행된다.
            frozen_model = self._effective_model_key(profile)
            count_tag = self._count_tag_for(character_prompt)
            reference_type = str(payload.get("reference_type") or "character&style")
            # 기본 S 0.8 / F 0.9 (사용자 지시 2026-07-17)
            reference_strength = payload.get("reference_strength", 0.8)
            reference_fidelity = payload.get("reference_fidelity", 0.9)
            composed = ", ".join(
                part for part in (count_tag, prefix, main_prompt, BENCH_SILENT_SCAFFOLD, postfix) if part
            )
            return {
                **common,
                **({"model": frozen_model} if frozen_model else {}),
                "input": composed,
                "_raw_input": composed,
                "width": GENERATION_WIDTH,
                "height": GENERATION_HEIGHT,
                # our own director params below double as the late-binding
                # suppressor for the user's active CR frames
                "_skip_character_reference_late_binding": True,
                **self._bench_reference_params(
                    character_id,
                    reference_type,
                    reference_strength,
                    reference_fidelity,
                ),
            }

        count_tag = self._count_tag_for(character_prompt)
        composed = ", ".join(
            part
            for part in (count_tag, main_prompt or BENCH_DEFAULT_MAIN_PROMPT, prefix, BENCH_SILENT_SCAFFOLD, postfix)
            if part
        )
        canvas_png, mask_png = self._bench_canvas(character_id)
        spec = VariationInpaintSpec()
        return {
            **common,
            "type": "inpaint",
            "image_bytes": canvas_png,
            "mask_bytes": mask_png,
            "input": composed,
            "_raw_input": composed,
            "strength": 1.0,
            "noise": 0.0,
            "width": spec.canvas_width,
            "height": spec.canvas_height,
            "reference_inset_tag_required": True,
            "_skip_character_reference_late_binding": True,
        }

    def build_bench_enhance_overrides(self, payload: dict[str, Any], candidate: int = 0) -> dict[str, Any]:
        """Dev0714 "Save with Enhance" parity for 1/2 Inpaint bench results.

        Crops the 512x896 edit rect out of the canvas result and runs ONE
        plain NAI img2img pass over the ORIGINAL generation params (deepcopy,
        inpaint plumbing stripped, character block kept) at strength 0.3 /
        noise 0.0 / 1.5x round64 -> 768x1344. The result arrives with mode
        stamp "enhance" and is stored raw (same save branch as char_reference).
        """
        import copy

        from PIL import Image

        from utils.reference_inpaint_preprocess import VariationInpaintSpec

        self._bootstrap()
        if str(self.context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("Enhance requires NAI mode")
        character_id = self._validate_id(str(payload.get("id") or ""))
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise ValueError("request_id is required")
        item = self.candidate_item(str(payload.get("history_id") or ""))
        if item is None:
            raise FileNotFoundError("bench result not found in history (already evicted?)")
        raw = getattr(item, "raw_bytes", None)
        if not raw or not bytes(raw).startswith(PNG_SIGNATURE):
            raise ValueError("bench result is not an original PNG")
        params = item.generation_params if isinstance(item.generation_params, dict) else {}
        if not params.get("character_asset_bench"):
            raise ValueError("history item is not a variation bench result")
        if str(params.get("character_asset_bench_character") or "") != character_id:
            raise ValueError("bench result belongs to a different character")
        if str(params.get("character_asset_bench_mode") or "inpaint") != "inpaint":
            raise ValueError("Enhance is for 1/2 Inpaint results only")

        spec = VariationInpaintSpec()
        with Image.open(io.BytesIO(bytes(raw))) as source:
            source.load()
            if source.size != (spec.canvas_width, spec.canvas_height):
                raise ValueError("history item is not a variation bench canvas result")
            crop = source.crop((spec.edit_left, spec.edit_top, spec.edit_right, spec.edit_bottom))
            crop_width, crop_height = crop.size
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            crop_png = buf.getvalue()

        overrides = copy.deepcopy(params)
        # Plain img2img: strip the inpaint plumbing and one-shot injection
        # flags. The stored input is the EXECUTED prompt (scaffold + inset tag
        # included) so no pipeline re-injection is wanted here - Dev0714 also
        # ran the Enhance pass on the final prompt text.
        for key in (
            "type", "mask_bytes", "cropped_image_request", "full_mask_pil",
            "reference_inset_tag_required",
            "_executed_characters", "_executed_character_ids", "_executed_characters_uc",
            "_executed_character_positions",
        ):
            overrides.pop(key, None)
        overrides.update({
            "image_bytes": crop_png,
            "strength": BENCH_ENHANCE_STRENGTH,
            "noise": BENCH_ENHANCE_NOISE,
            "width": int(round(crop_width * BENCH_ENHANCE_UPSCALE / 64)) * 64,
            "height": int(round(crop_height * BENCH_ENHANCE_UPSCALE / 64)) * 64,
            "random_resolution": False,
            "character_asset_request": True,
            "character_asset_request_id": request_id,
            "character_asset_candidate": int(candidate),
            "character_asset_bench": True,
            "character_asset_bench_character": character_id,
            "character_asset_bench_mode": "enhance",
            "character_asset_bench_enhance_source": str(payload.get("history_id") or "").strip(),
            "_remote_queue_source": "Character Asset",
            "_remote_queue_label": "variation enhance",
            "seed": -1,
            "seed_fixed": False,
            "_skip_vibe_transfer_late_binding": True,
            "_skip_character_reference_late_binding": True,
            "wildcard_standalone": True,
        })
        overrides["_raw_input"] = str(overrides.get("input") or "")
        return overrides

    def save_bench_result(self, character_id: str, history_id: str) -> dict[str, Any]:
        """Store a bench result as a variation of the character.

        - inpaint results: crop the 512x896 edit rect out of the 1152x896
          canvas, transplant the NAI tEXt metadata, LANCZOS-upscale 1.5x to
          768x1344 (exact 4:7 landing).
        - char_reference / enhance results: already finished full-resolution
          PNGs with their own NAI Comment - stored byte-identical (no
          re-encode).

        The generation mode is recorded in the sidecar (``variation_origins``)
        so the UI can distinguish how each variation was produced.
        """
        from PIL import Image

        from utils.reference_inpaint_preprocess import VariationInpaintSpec

        self._bootstrap()
        with self._lock:
            character_id = self._validate_id(character_id)
            item = self.candidate_item(str(history_id or ""))
            if item is None:
                raise FileNotFoundError("bench result not found in history (already evicted?)")
            raw = getattr(item, "raw_bytes", None)
            if not raw or not bytes(raw).startswith(PNG_SIGNATURE):
                raise ValueError("bench result is not an original PNG")
            # Provenance: only THIS character's bench results are saveable - a
            # coincidental same-size result or another character's bench result
            # must not be filed as a variation.
            params = item.generation_params if isinstance(item.generation_params, dict) else {}
            if not params.get("character_asset_bench"):
                raise ValueError("history item is not a variation bench result")
            if str(params.get("character_asset_bench_character") or "") != character_id:
                raise ValueError("bench result belongs to a different character")
            bench_mode = str(params.get("character_asset_bench_mode") or "inpaint")

            if bench_mode in ("char_reference", "enhance"):
                # finished full-resolution generation - save the original bytes
                self._ensure_current(character_id)
                path = asset_storage.save_character_variation(
                    character_id, raw_bytes=bytes(raw), root=self.write_root()
                )
            else:
                spec = VariationInpaintSpec()
                with Image.open(io.BytesIO(bytes(raw))) as source:
                    source.load()
                    if source.size != (spec.canvas_width, spec.canvas_height):
                        raise ValueError("history item is not a variation bench canvas result")
                    crop = source.crop((spec.edit_left, spec.edit_top, spec.edit_right, spec.edit_bottom))
                    target_width = (spec.edit_right - spec.edit_left) * 3 // 2
                    target_height = (spec.edit_bottom - spec.edit_top) * 3 // 2
                    upscaled = crop.resize((target_width, target_height), Image.Resampling.LANCZOS)
                    png = reencode_with_nai_meta(upscaled, source, params)
                self._ensure_current(character_id)
                path = asset_storage.save_character_variation(
                    character_id, raw_bytes=png, root=self.write_root()
                )
            # 생성 방식 기록 - detail()이 존재하는 해시만 걸러 UI 배지로 노출한다.
            meta = asset_storage.read_character_meta(character_id, self.write_root())
            origins = meta.get("variation_origins") if isinstance(meta.get("variation_origins"), dict) else {}
            origins[path.stem] = bench_mode
            meta["variation_origins"] = origins
            asset_storage.write_character_meta(character_id, meta, self.write_root())
            return {"character_id": character_id, "hash": path.stem, "origin": bench_mode}
