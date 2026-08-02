"""PyQt-free result and history state for the headless Remote Web runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import io
from pathlib import Path
import uuid
import zipfile
from typing import Any, Optional

from PIL import Image

from core import result_image_payload_service as result_images
from core.event_stream_vibe import strip_event_stream_vibe_params


HISTORY_ITEM_PREFIX = "__history_item__/"


@dataclass
class HeadlessHistoryItem:
    image: Image.Image
    raw_bytes: bytes
    webp_bytes: bytes
    generation_params: dict[str, Any]
    prompt_context: dict[str, Any]
    source_row: Any = None
    api_metadata: dict[str, Any] = field(default_factory=dict)
    filepath: str = ""
    history_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=datetime.now)
    # 비-PNG(WEBP 등) ComfyUI 결과에서 raw_bytes는 원본을 보존하고, 저장/PNG 합류점이 쓸
    # 메타데이터-임베드 PNG를 여기에 둔다(history_item_png_payload가 우선 사용). None이면 미사용.
    png_payload_override: bytes | None = None

    @property
    def rel_path(self) -> str:
        return f"{HISTORY_ITEM_PREFIX}{self.history_id}"

    @property
    def filename(self) -> str:
        timestamp = self.created_at.strftime("%Y%m%d_%H%M%S")
        return f"naia_result_{timestamp}_{self.history_id[:8]}.png"


@dataclass
class HeadlessStoredResult:
    item: HeadlessHistoryItem
    image_meta: dict[str, Any]
    metadata_payload: dict[str, Any]
    # viewer_history_removed payloads for items dropped by overflow eviction, so
    # callers can broadcast them and the frontend trims the matching thumbnails.
    evicted_payloads: list[dict[str, Any]] = field(default_factory=list)
    # True when this is a ComfyUI result whose downloaded image carried NO native
    # metadata (e.g. server ran with --disable-metadata) and NAIA injected its own.
    # The caller surfaces a one-time warning toast on the first such image.
    comfyui_metadata_injected: bool = False
    # Set when the ComfyUI generation only succeeded after an automatic EPS↔ANIMA
    # sampling-mode swap (2 failures → 3rd attempt swapped). Shape:
    # {from, to, from_workflow_type, to_workflow_type}. The caller commits the swap
    # to the UI flags + remote_params and shows a yellow warning toast.
    comfyui_mode_swap: Optional[dict[str, Any]] = None


class HeadlessResultStore:
    """Stores latest result, history entries, and image export payloads."""

    # Interactive 스냅샷 훅이 세션 컨텍스트를 찾을 때 쓴다. 컨텍스트가 자기 필드로
    # 이 저장소를 들고 있으므로(WebSessionContext.result_store) 생성 뒤 주입한다.
    # 없으면 훅은 조용히 아무것도 하지 않는다.
    _context = None

    def __init__(self, max_items: int = 200):
        self.max_items = max(1, int(max_items))
        self._items: list[HeadlessHistoryItem] = []
        self.latest_item: HeadlessHistoryItem | None = None
        self.latest_webp: bytes | None = None
        self.latest_metadata_payload: dict[str, Any] | None = None

    def _attach_interactive_snapshot_thumb(self, request, image_bytes: bytes) -> None:
        """Interactive 조합 스냅샷에 결과 썸네일을 붙인다(있을 때만)."""
        params = getattr(request, "params", {}) or {}
        snapshot_id = str(params.get("interactive_snapshot_id") or "")
        if not snapshot_id or not image_bytes:
            return
        context = getattr(self, "_context", None) or getattr(request, "context", None)
        if context is None:
            return
        try:
            from app.backend.server.interactive_assets_routes import (
                interactive_assets_service,
            )

            interactive_assets_service(context).attach_thumb(snapshot_id, image_bytes)
        except Exception as exc:                     # 썸네일 실패가 생성을 막지 않는다
            print(f"[interactive-assets] thumb attach skipped: {exc}")

    def add_api_result(self, api_result: dict[str, Any], request) -> HeadlessStoredResult:
        image = self._coerce_image(api_result)
        raw_bytes = self._coerce_raw_bytes(api_result, image)
        # WEBUI returns the infotext only in the API `info` field; the image bytes forge
        # sends back usually have NO `parameters` chunk, so a NAIA-saved WEBUI PNG would
        # carry no metadata. Bake the infotext into the PNG here (no-op if forge already
        # embedded it, or for NAI/ComfyUI which never set generation_info).
        info_text = api_result.get("generation_info")
        if info_text:
            from utils.webui_generation_info import embed_webui_parameters

            raw_bytes = embed_webui_parameters(raw_bytes, info_text)
        webp_bytes = self._image_to_webp(image)
        # Interactive 조합 스냅샷에 384px 썸네일을 붙인다. 프론트가 생성 요청에
        # `interactive_snapshot_id` 를 실었을 때만 돈다 — 그 밖의 경로는 영향 없다.
        # 실패해도 생성 결과 저장을 막지 않는다(썸네일은 부가 정보다).
        self._attach_interactive_snapshot_thumb(request, raw_bytes or webp_bytes)
        params = dict(getattr(request, "params", {}) or {})
        params.pop("credential", None)
        # Storyteller Use Vibe: 스트림 발급 vibe는 휘발성 — 히스토리 메타/리플레이에
        # 남기지 않는다(마커로 그 1장만 정밀 제거, 일반 vibe refs는 리플레이 의미 보존).
        strip_event_stream_vibe_params(params)
        # 입력창 와일드카드는 실행 시점에 로컬 복사본에서 전개된다(execute_request의
        # _expand_input_wildcards — 요청 원본에는 토큰이 남아 반복 시 재롤). 저장 메타의
        # 프롬프트는 "이 이미지가 실제로 생성된 값"이어야 하므로 실행본의 input/negative만
        # 덮어쓴다. 그 외 파라미터는 요청 원본 유지(리플레이/큐 의미 보존).
        executed = api_result.get("generation_params")
        if isinstance(executed, dict):
            for key in ("input", "negative_prompt"):
                value = executed.get(key)
                if isinstance(value, str) and value and value != params.get(key):
                    params[key] = value
            # ComfyUI 자동 EPS↔ANIMA 스왑이 성공한 경우, 저장 메타/리플레이가 "실제 생성된
            # 모드"를 반영하도록 스왑된 sampling_mode/workflow_type 도 실행본에서 덮어쓴다
            # (스왑 미발생 시엔 naia_comfyui_mode_swap 부재 → 원본 모드 그대로 유지).
            if isinstance(api_result.get("naia_comfyui_mode_swap"), dict):
                for key in ("sampling_mode", "comfyui_sampling_mode", "workflow_type"):
                    value = executed.get(key)
                    if value:
                        params[key] = value
            # NAI 캐릭터는 페이로드 빌드 시점 늦은 바인딩이라 요청 params에 없다 —
            # api_service가 기록한 실행본(_executed_*)을 메타데이터로 보존한다
            # (메타데이터 뷰어 캐릭터 슬롯 표시용). 리플레이된 request.params에 직전
            # 실행의 값이 남아 있을 수 있으므로 항상 실행본 기준으로 재설정한다.
            for key in ("_executed_characters", "_executed_character_ids", "_executed_characters_uc"):
                params.pop(key, None)
                value = executed.get(key)
                if isinstance(value, list) and value:
                    params[key] = list(value)
        # WEBUI custom payload is a LIVE editor/session setting (remote_params), not a per-image
        # baked param. Never persist it into a stored result, so EVERY replay path (Result Enhance,
        # history replay/reopen, queue 'original', and any future one) injects the user's CURRENT
        # payload from remote_params instead of resurrecting a stale enabled/disabled state.
        params.pop("webui_custom_payload", None)
        params.pop("webui_custom_payload_enabled", None)
        # NOTE: input image/mask bytes (image_bytes/mask_bytes/init_image_bytes/...) are KEPT here
        # on purpose. "큐 앞/뒤에 추가 → 원본 프롬프트 유지"(queue_mode='original') replays the stored
        # params directly, and APIService picks img2img/inpaint from those byte fields. Stripping them
        # would silently downgrade an img2img/inpaint replay to txt2img / drop the mask. They are freed
        # with the item on delete (proven by the weakref GC test), so this is not a leak.
        prompt_context = {
            "main_prompt": params.get("input", ""),
            "final_prompt": params.get("input", ""),
            "negative_prompt": params.get("negative_prompt", ""),
        }
        # 읽기 전용 생성 추적을 이 이미지에 영속한다(execute_request 가 current_prompt_context
        # 에서 떠서 api_result 에 실어 보낸다). prompt_context 는 HeadlessHistoryItem·메타데이터
        # API 3종·PNG naia_prompt_context 청크로 자동 전파되므로 한 번 쓰면 모든 조회면에 보인다.
        #  • pipeline_trace: 단계별 added/removed/note (제거된 Hooker의 코드 실행을 관측으로 대체)
        #  • wildcards: 이 이미지에 적용된 와일드카드 history/state (Wildcard Watch)
        # 전부 JSON-safe(문자열/정수/리스트/딕트) — raw bytes 없음(과거 image_bytes 직렬화 500 회피).
        trace_payload = api_result.get("naia_generation_trace")
        if isinstance(trace_payload, dict):
            stages = trace_payload.get("pipeline_trace")
            if isinstance(stages, list) and stages:
                prompt_context["pipeline_trace"] = stages
            wildcards = trace_payload.get("wildcards")
            if isinstance(wildcards, dict) and (wildcards.get("history") or wildcards.get("state")):
                prompt_context["wildcards"] = wildcards
        # ComfyUI 결과 메타데이터 보강 (단일 저장 합류점 패턴, WEBUI embed_webui_parameters와 동형).
        # 데스크톱 generation_controller 보강(82856b6)이 헤드리스 이관(30542db 아카이브) 시
        # 누락된 회귀를 복구하는 경로. prompt_context/params가 조립된 이 시점에서 호출한다.
        #  • PNG: 서버가 네이티브 메타(prompt/workflow 청크)를 남겼으면 보존(사용자 요청:
        #    누락 시에만 대응). ``--disable-metadata`` 서버처럼 비어 있으면 naia_* 를 in-place
        #    보강한다(원본도 PNG라 손실 없음).
        #  • 비-PNG(WEBP/JPEG — 워크플로우의 SaveAnimatedWEBP / WebP 저장 노드 출력):
        #    원본 바이트는 raw_bytes로 **그대로 보존**한다 — /api/history/image, /api/result/
        #    image/original, img2img 소스가 raw_bytes를 verbatim 사용하므로 애니메이션/원본을
        #    잃으면 안 된다(Codex 적대리뷰). 다만 저장 합류점 history_item_png_payload가 비-PNG를
        #    PNG로 재인코딩하며 메타를 잃으므로, 메타 임베드 PNG를 png_payload_override에 별도
        #    보관해 **저장/PNG 경로만** 그것을 쓰게 한다(PNG 저장은 원래 단일 프레임으로 평탄화
        #    되므로 애니메이션 손실은 기존 동작과 동일).
        # NAI/WEBUI는 게이트로 건너뛴다. ⚠️add_api_result는 외부 이미지 임포트
        # (insert_external_image_to_history)도 거치는데 거긴 api_mode를 현재 UI 모드 태그로만
        # 박는다 — 실제 ComfyUI 생성 신호(prompt_id/workflow_api/source_node_id)가 있고
        # imported_external이 아닌 경우로 한정한다.
        comfyui_metadata_injected = False
        comfyui_png_override: bytes | None = None
        is_comfyui_generation = (
            str(params.get("api_mode") or "").strip().upper() == "COMFYUI"
            and not params.get("imported_external")
            and bool(
                api_result.get("prompt_id")
                or api_result.get("workflow_api")
                or api_result.get("source_node_id")
            )
        )
        if is_comfyui_generation:
            from utils.comfyui_png_metadata import (
                enrich_comfyui_png_bytes,
                png_has_generation_metadata,
            )

            raw_is_png = result_images.is_png_bytes(raw_bytes)
            if raw_is_png:
                source_has_metadata = png_has_generation_metadata(raw_bytes)
            else:
                # WEBP/JPEG: ComfyUI(예: SaveAnimatedWEBP)가 EXIF에 prompt/workflow를 남겼는지.
                try:
                    from utils.comfyui_png_metadata import (
                        extract_comfyui_workflow_metadata_from_image_bytes,
                    )

                    extract_comfyui_workflow_metadata_from_image_bytes(raw_bytes)
                    source_has_metadata = True
                except Exception:
                    source_has_metadata = False
            # PNG: 네이티브 메타가 없을 때만 보강(있으면 보존). 비-PNG: 저장 시 PNG 재인코딩으로
            # 메타를 잃으므로 원본 메타 유무와 무관하게 항상 PNG 오버라이드를 만든다.
            should_enrich = (not raw_is_png) or (not source_has_metadata)
            if should_enrich:
                try:
                    enriched_bytes, _enriched_image, _changed = enrich_comfyui_png_bytes(
                        # 비-PNG는 None을 넘겨 디코드된 PIL 이미지로부터 PNG를 생성한다.
                        raw_bytes if raw_is_png else None,
                        image,
                        workflow_api=api_result.get("workflow_api") or params.get("workflow"),
                        workflow_ui=api_result.get("workflow_ui") or params.get("_comfyui_workflow_ui"),
                        generation_params=params,
                        prompt_context=prompt_context,
                        api_metadata=dict(api_result.get("api_metadata", {}) or {}) or {"backend": "COMFYUI"},
                    )
                    if raw_is_png:
                        raw_bytes = enriched_bytes              # PNG: in-place(원본도 PNG라 무손실)
                    else:
                        comfyui_png_override = enriched_bytes   # 비-PNG: 원본 raw_bytes 보존 + 저장용 PNG 별도
                    # "--disable-metadata" 경고 토스트는 원본에 메타가 정말 없었을 때만 1회 띄운다
                    # (네이티브 메타를 가진 WEBP를 PNG로 변환·임베드한 경우엔 오발 금지).
                    comfyui_metadata_injected = not source_has_metadata
                except Exception as exc:  # pragma: no cover - defensive
                    print(f"⚠️ ComfyUI PNG 메타데이터 보강 실패(원본 사용): {exc}")
        item = HeadlessHistoryItem(
            image=image,
            raw_bytes=raw_bytes,
            webp_bytes=webp_bytes,
            generation_params=params,
            prompt_context=prompt_context,
            source_row=getattr(request, "source_row", None),
            api_metadata=dict(api_result.get("api_metadata", {}) or {}),
            png_payload_override=comfyui_png_override,
        )
        self._items.insert(0, item)
        evicted = self._items[self.max_items:]
        del self._items[self.max_items:]
        image_meta = self._set_latest_item(item) or {}
        metadata_payload = self.latest_metadata_payload or {}
        # Build removal payloads AFTER eviction so their `total` reflects the capped count.
        evicted_payloads = [self.viewer_removed_payload(ev) for ev in evicted]
        return HeadlessStoredResult(
            item=item,
            image_meta=image_meta,
            metadata_payload=metadata_payload,
            evicted_payloads=evicted_payloads,
            comfyui_metadata_injected=comfyui_metadata_injected,
        )

    def get_item(self, history_id: str) -> HeadlessHistoryItem | None:
        history_id = str(history_id or "")
        for item in self._items:
            if item.history_id == history_id:
                return item
        return None

    def find_by_generation_request_id(self, request_id: str) -> HeadlessHistoryItem | None:
        """생성 요청 id로 히스토리 항목 조회(없으면 None) — 확장 ctx의
        get_result_image가 쓰는 public 표면(비공개 _items 직접 스캔 대체)."""
        clean = str(request_id or "")
        if not clean:
            return None
        for item in list(self._items):  # add/evict 동시 변경 대비 스냅샷 순회
            params = getattr(item, "generation_params", None) or {}
            if str(params.get("generation_request_id") or "") == clean:
                return item
        return None

    def history_total(self) -> int:
        return len(self._items)

    def unsaved_items(self) -> list[HeadlessHistoryItem]:
        return [item for item in self._items if not item.filepath]

    def unsaved_history_count(self) -> int:
        return len(self.unsaved_items())

    def mark_saved(self, item: HeadlessHistoryItem, filepath: str | Path) -> None:
        item.filepath = str(filepath)

    def remove_item(self, item_or_history_id: HeadlessHistoryItem | str) -> HeadlessHistoryItem | None:
        history_id = (
            item_or_history_id.history_id
            if isinstance(item_or_history_id, HeadlessHistoryItem)
            else str(item_or_history_id or "")
        )
        for index, item in enumerate(self._items):
            if item.history_id != history_id:
                continue
            removed = self._items.pop(index)
            if self.latest_item and self.latest_item.history_id == history_id:
                self._set_latest_item(self._items[0] if self._items else None)
            return removed
        return None

    def viewer_removed_payload(self, item: HeadlessHistoryItem) -> dict[str, Any]:
        return {
            "type": "viewer_history_removed",
            "rel_path": item.rel_path,
            "history_id": item.history_id,
            "total": len(self._items),
        }

    def unsaved_zip_payload(self) -> tuple[bytes, str]:
        items = self.unsaved_items()
        if not items:
            raise FileNotFoundError("No unsaved history")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in items:
                png_bytes, filename = result_images.history_item_png_payload(item, label=item.filename)
                archive.writestr(filename, png_bytes)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return buffer.getvalue(), f"naia_unsaved_history_{timestamp}.zip"

    def history_summary(self, item: HeadlessHistoryItem, index: int = 0) -> dict[str, Any]:
        mtime = item.created_at.timestamp()
        return {
            "rel_path": item.rel_path,
            "history_id": item.history_id,
            "filename": item.filename,
            "file_path": item.filepath,
            "source": "file" if item.filepath else "memory",
            "size_bytes": len(item.raw_bytes or item.webp_bytes or b""),
            "mtime": mtime,
            "mtime_iso": item.created_at.isoformat(),
            "index": index,
            "thumb_url": f"/api/history/thumb/{item.history_id}",
            "image_url": f"/api/history/image/{item.history_id}",
            "metadata_url": f"/api/history/meta/{item.history_id}",
            **self._history_pipeline_ids(item),
        }

    def history_list(self, page: int = 0, per_page: int = 30) -> dict[str, Any]:
        page = max(0, int(page or 0))
        per_page = min(100, max(1, int(per_page or 30)))
        start = page * per_page
        selected = self._items[start:start + per_page]
        return {
            "images": [
                self.history_summary(item, index=start + offset)
                for offset, item in enumerate(selected)
            ],
            "total": len(self._items),
            "page": page,
            "per_page": per_page,
        }

    def latest_image_payload(self) -> tuple[bytes, str]:
        if not self.latest_webp:
            raise FileNotFoundError("No image generated yet")
        return self.latest_webp, "image/webp"

    def current_png_payload(self) -> tuple[bytes, str]:
        if not self.latest_item:
            raise FileNotFoundError("No image generated yet")
        return result_images.history_item_png_payload(self.latest_item, label=self.latest_item.filename)

    def history_image_payload(self, history_id: str) -> tuple[bytes, str]:
        item = self.get_item(history_id)
        if item is None:
            raise FileNotFoundError("History item not found")
        return result_images.history_item_image_payload(item)

    def history_thumb_payload(self, history_id: str, max_side: int = 0) -> bytes:
        item = self.get_item(history_id)
        if item is None:
            raise FileNotFoundError("History item not found")
        return result_images.memory_history_thumbnail_payload(item, max_side)

    def history_meta_payload(self, history_id: str, include_full: bool = False) -> dict[str, Any]:
        from utils.image_info import json_safe_generation_params

        item = self.get_item(history_id)
        if item is None:
            raise FileNotFoundError("History item not found")
        # full=1 응답의 raw에는 generation_params가 그대로 실린다 — img2img/inpaint
        # 항목의 리플레이용 bytes가 JSON 직렬화를 500으로 만들지 않도록 위생 처리.
        payload = result_images.history_item_meta_payload(
            item,
            include_full=include_full,
            metadata_json_safe=json_safe_generation_params,
        )
        payload.update(self._history_pipeline_ids(item))
        return payload

    def viewer_new_image_payload(self, item: HeadlessHistoryItem) -> dict[str, Any]:
        payload = self.history_summary(item, index=0)
        payload.update({"type": "viewer_new_image", "total": len(self._items)})
        return payload

    def _set_latest_item(self, item: HeadlessHistoryItem | None) -> dict[str, Any] | None:
        self.latest_item = item
        if item is None:
            self.latest_webp = None
            self.latest_metadata_payload = None
            return None
        image_meta = self._build_image_meta(item)
        self.latest_webp = item.webp_bytes
        self.latest_metadata_payload = self._build_metadata_payload(item, image_meta)
        return image_meta

    def _build_image_meta(self, item: HeadlessHistoryItem) -> dict[str, Any]:
        params = item.generation_params
        payload = {
            "width": item.image.width,
            "height": item.image.height,
            "size_kb": len(item.webp_bytes) // 1024,
            "timestamp": item.created_at.isoformat(),
            "can_enhance": bool(params),
            "prompt": params.get("input", ""),
            "negative_prompt": params.get("negative_prompt", ""),
            "seed": params.get("seed", ""),
            "steps": params.get("steps", ""),
            "cfg_scale": params.get("cfg_scale", ""),
            "sampler": params.get("sampler", ""),
            "model": params.get("model", ""),
            "remote_queue_source": str(params.get("_remote_queue_source") or ""),
            "prompt_run_id": str(params.get("prompt_run_id") or ""),
            "generation_request_id": str(params.get("generation_request_id") or ""),
        }
        for key, value in params.items():
            if str(key).startswith("artist_thumb_"):
                payload[key] = value
            elif str(key).startswith("event_preset_"):
                payload[key] = value
            elif str(key).startswith("remote_preset_"):
                payload[key] = value
            elif str(key).startswith("character_asset_"):
                payload[key] = value
        if payload.get("character_asset_request"):
            payload["history_id"] = str(getattr(item, "history_id", "") or "")
        if payload.get("artist_thumb_request") and not payload.get("artist_thumb_artist"):
            payload["artist_thumb_artist"] = str(params.get("_remote_queue_label") or "")
        return payload

    @staticmethod
    def _history_pipeline_ids(item: HeadlessHistoryItem) -> dict[str, str]:
        params = item.generation_params if isinstance(item.generation_params, dict) else {}
        return {
            "prompt_run_id": str(params.get("prompt_run_id") or ""),
            "generation_request_id": str(params.get("generation_request_id") or ""),
        }

    def _build_metadata_payload(self, item: HeadlessHistoryItem, image_meta: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "width": item.image.width,
            "height": item.image.height,
            "mode": item.image.mode,
            "size_kb": len(item.webp_bytes) // 1024,
            "prompt": item.generation_params.get("input", ""),
            "negative": item.generation_params.get("negative_prompt", ""),
            "seed": item.generation_params.get("seed", ""),
            "steps": item.generation_params.get("steps", ""),
            "sampler": item.generation_params.get("sampler", ""),
            "cfg_scale": item.generation_params.get("cfg_scale", ""),
            "model": item.generation_params.get("model", ""),
        }
        raw: dict[str, Any] = {
            "image": {
                "width": item.image.width,
                "height": item.image.height,
                "mode": item.image.mode,
                "format": item.image.format,
                "size_kb": len(item.webp_bytes) // 1024,
            },
            "generation_params": item.generation_params,
            "prompt_context": item.prompt_context,
            "api_metadata": item.api_metadata,
            "image_meta": image_meta,
        }
        # External images (imported into history) have no naia_* params; recover
        # prompt/params from the embedded PNG metadata so the viewer is not limited
        # to in-session generations. Only runs when there is no in-app prompt, so
        # normal generated results never pay the extraction cost.
        if not summary["prompt"]:
            from utils.image_info import extract_embedded_metadata

            extracted = extract_embedded_metadata(getattr(item, "raw_bytes", None))
            if extracted:
                raw["extracted_metadata"] = extracted
                summary["prompt"] = summary["prompt"] or str(extracted.get("prompt") or "")
                summary["negative"] = summary["negative"] or str(
                    extracted.get("negative") or extracted.get("uc") or ""
                )
                ext_params = extracted.get("parameters") if isinstance(extracted.get("parameters"), dict) else {}
                for key in ("seed", "steps", "sampler", "cfg_scale", "scale", "model"):
                    if summary.get(key) in ("", None):
                        value = extracted.get(key)
                        if value in ("", None):
                            value = ext_params.get(key)
                        if value not in ("", None):
                            summary[key] = value
        # img2img/inpaint params는 리플레이용 원시 bytes(image_bytes/mask_bytes)를
        # 보존한다(add_api_result NOTE) — 응답 경계에서 자리표시자로 치환하지 않으면
        # FastAPI의 strict UTF-8 bytes 디코드가 /api/result/metadata를 500으로 만든다.
        # 저장본(item.generation_params)은 사본 변환이라 영향 없다.
        from utils.image_info import json_safe_generation_params

        return {
            "source": "current",
            "label": "Current Result",
            "summary": {key: value for key, value in summary.items() if value not in ("", None)},
            "raw": json_safe_generation_params(raw),
            "has_metadata": True,
        }

    @staticmethod
    def _coerce_image(api_result: dict[str, Any]) -> Image.Image:
        image = api_result.get("image")
        if image is not None:
            image.load()
            return image.copy()
        raw_bytes = api_result.get("raw_bytes")
        if raw_bytes:
            with Image.open(io.BytesIO(raw_bytes)) as opened:
                opened.load()
                return opened.copy()
        raise ValueError("API result does not include an image")

    @staticmethod
    def _coerce_raw_bytes(api_result: dict[str, Any], image: Image.Image) -> bytes:
        raw_bytes = api_result.get("raw_bytes")
        if isinstance(raw_bytes, bytes):
            return raw_bytes
        if isinstance(raw_bytes, bytearray):
            return bytes(raw_bytes)
        return result_images.pil_image_to_png_bytes(image)

    @staticmethod
    def _image_to_webp(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=85, method=0)
        return buffer.getvalue()


__all__ = [
    "HISTORY_ITEM_PREFIX",
    "HeadlessHistoryItem",
    "HeadlessResultStore",
    "HeadlessStoredResult",
]
