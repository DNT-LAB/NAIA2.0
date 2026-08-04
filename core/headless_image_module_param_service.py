"""NAI image-module parameter assembly for the headless generation path."""

from __future__ import annotations

from typing import Any

from core.auto_generation_flags import is_special_request
from core.event_stream_vibe import (
    EVENT_STREAM_VIBE_CAPTURE_KEY,
    EVENT_STREAM_VIBE_MARKER_KEY,
    EVENT_STREAM_VIBE_STRENGTH,
    halve_floor_strength,
)


# Auto Gen 매 반복마다 라이브 Character Reference 상태를 다시 읽기 위해 직전 생성의 baked
# overrides 에서 제거해야 하는 키 집합. active_character_reference_params() 가 내보내는
# director_reference_* 전부와 일치해야 한다 — 이 중 하나라도(특히 가드 키
# director_reference_descriptions) baked 상태로 핀되면 apply() 가 라이브 재조립을 건너뛴다
# (헤드리스 Auto Gen 중 char-ref 끄기/수치 조절이 반영 안 되던 버그). generation_runner 의
# Auto Gen continuation 이 이 집합을 pop 한다.
CHARACTER_REFERENCE_LIVE_REFETCH_KEYS = (
    "director_reference_descriptions",
    "director_reference_images",
    "director_reference_information_extracted",
    "director_reference_strength_values",
    "director_reference_secondary_strength_values",
)

# Vibe Transfer 도 char-ref 와 동일 클래스 — Auto Gen 매 반복마다 라이브 모듈 프레임 상태(교체/
# 삭제/강도·IE 조절)를 다시 읽기 위해 직전 생성의 baked params 에서 제거해야 하는 키 집합.
# active_vibe_transfer_params()(= vibe active_params)가 내보내는 키와 일치해야 한다 — 특히
# reference_image_multiple 이 baked 로 핀되면 apply() 의 'reference_image_multiple 존재' 가드가
# active_vibe_transfer_params() 라이브 재조립을 건너뛴다(Auto Gen 중 vibe 교체/삭제가 반영 안 되던
# 버그). 클러스터 vibe 도 load_cluster 가 모듈 프레임으로 넣으므로 이 재조회로 함께 갱신된다.
# generation_runner 의 Auto Gen continuation 이 이 집합을 pop 한다.
VIBE_TRANSFER_LIVE_REFETCH_KEYS = (
    "reference_image_multiple",
    "reference_strength_multiple",
    "normalize_reference_strength_multiple",
    "reference_information_extracted_multiple",
)

# 레퍼런스 인셋 핀도 동일 클래스 - Auto Gen continuation의 baked overrides에서
# 제거해야 매 반복 라이브 핀 상태로 재조립된다(핀 해제 후에도 baked 캔버스로
# 계속 인셋 생성되는 버그 방지). _reference_inset_pin 마커가 있을 때만 pop한다 -
# width/height는 일반 키라 무조건 pop하면 남의 해상도를 지운다.
REFERENCE_INSET_LIVE_REFETCH_KEYS = (
    "type",
    "image_bytes",
    "mask_bytes",
    "width",
    "height",
    "resolution",
    "strength",
    "noise",
    "add_original_image",
    "reference_inset_tag_required",
    "_reference_inset_pin",
)


class HeadlessImageModuleParamService:
    def __init__(self, context: Any):
        self.context = context

    def active_character_reference_params(self) -> dict[str, Any]:
        return self.context._character_reference_service().active_params()

    def active_interactive_reference_params(self) -> dict[str, Any]:
        """Interactive 전용 레퍼런스. 서비스가 없는 구버전 컨텍스트에서도 죽지 않는다."""
        getter = getattr(self.context, "_interactive_reference_service", None)
        if not callable(getter):
            return {}
        try:
            return getter().active_params()
        except Exception:      # noqa: BLE001 — 레퍼런스 때문에 생성이 막히면 안 된다
            return {}

    def active_vibe_transfer_params(self) -> dict[str, Any]:
        return self.context._vibe_transfer_service().active_params()

    def apply(self, params: dict[str, Any], api_mode: str) -> None:
        if str(api_mode or "").upper() != "NAI":
            return
        if not params.get("director_reference_descriptions"):
            if params.get("_skip_character_reference_late_binding"):
                # Interactive 가 운전 중이다. 세션 CR 은 건너뛰되 **Interactive 자신의**
                # 레퍼런스를 실는다 — 둘은 상태가 독립이다(2026-08-04 사용자 지시).
                # 이 분기가 없으면 Interactive 에서 붙인 레퍼런스가 생성에 아예 안 실린다.
                params.update(self.active_interactive_reference_params())
            else:
                params.update(self.active_character_reference_params())
        if not params.get("_skip_vibe_transfer_late_binding"):
            if not params.get("reference_image_multiple"):
                params.update(self.active_vibe_transfer_params())
            self._apply_event_stream_vibe(params)
        # 인셋 핀은 마지막에 - type=inpaint 주입이 위 스트림 vibe의 plain 판정을
        # 건드리지 않도록(마커 화이트리스트가 있지만 순서로도 안전하게).
        self._apply_reference_inset_pin(params)

    # ------------------------------------ 레퍼런스 인셋 핀 (C1 + 레퍼런스 인셋)
    def _apply_reference_inset_pin(self, params: dict[str, Any]) -> None:
        """핀이 살아 있는 동안 plain 생성을 1152x896 인셋 인페인트로 바꾼다.

        - 인페인트/img2img 등 이미 이미지 배관을 가진 요청은 인셋을 역으로
          무시한다(사용자 계약) - type/image_bytes 가드가 그 관문이다.
        - 특수 요청(벤치/프리셋/인핸스)도 대상 밖 - Result 탭 일반 생성뿐이다.
        - CR과는 상호배타: 요청에 CR 파라미터가 실려 있으면(활성 CR 프레임
          late-binding) 인셋 핀을 강제 종료한다(생성 단계 이중 체크 - 사용자 계약).
        """
        asset_service_getter = getattr(self.context, "_character_asset_service", None)
        if not callable(asset_service_getter):
            return
        if params.get("type") or params.get("image_bytes"):
            return
        if is_special_request(params, getattr(self.context, "_coerce_bool", None)):
            return
        try:
            asset_service = asset_service_getter()
            if params.get("director_reference_descriptions"):
                # plain 생성에 CR이 실렸다 = CR 활성. _persist 훅이 놓친 경로가
                # 있어도 여기서 핀을 확정 종료한다(주입도 하지 않는다).
                if asset_service.clear_reference_inset_pin():
                    print("[CharacterAsset] reference inset pin released - CR present at generation")
                return
            pin_params = asset_service.reference_inset_generation_params()
        except Exception:
            return
        if pin_params:
            params.update(pin_params)

    # ------------------------------------ Storyteller "Use Vibe" (1회성 스트림 vibe)
    def _apply_event_stream_vibe(self, params: dict[str, Any]) -> None:
        """스트림 활성 중 plain generate에 한해: ①현재 노드가 use_vibe 스텝이면 완료
        캡처 stamp(run_id) ②스트림 vibe가 준비돼 있으면 reference에 '딱 1장' append.
        마커를 함께 실어 히스토리/리플레이/정지 후 실행에서 이 발급분만 정밀 제거된다.
        특수 요청(인핸스/프리셋/img2img류)은 Auto Gen 억제 규칙과 동일하게 캡처도
        주입도 하지 않는다."""
        runtime = getattr(self.context, "event_stream_runtime", None)
        if runtime is None or not getattr(runtime, "is_active", False):
            return
        if is_special_request(params, getattr(self.context, "_coerce_bool", None)):
            return
        stamp_issuer = getattr(runtime, "issue_vibe_capture_stamp", None)
        stamp = stamp_issuer() if callable(stamp_issuer) else None
        if stamp:
            params[EVENT_STREAM_VIBE_CAPTURE_KEY] = stamp
        getter = getattr(runtime, "get_stream_vibe", None)
        vibe = getter() if callable(getter) else None
        if not vibe:
            return
        encoding = str(vibe.get("encoding") or "")
        if not encoding:
            return
        # 인코딩은 모델 종속 — 스트림 도중 모델을 바꾼 경우 주입하지 않는다(NAI 오류 방지).
        vibe_model = str(vibe.get("model") or "")
        if vibe_model:
            try:
                if vibe_model != str(self.context._current_model_key() or ""):
                    return
            except Exception:
                pass
        issued: set[str] = set()
        issued_getter = getattr(runtime, "issued_stream_encodings", None)
        if callable(issued_getter):
            issued = issued_getter() or set()
        raw_refs = params.get("reference_image_multiple")
        raw_refs = list(raw_refs) if isinstance(raw_refs, list) else []
        raw_strengths = params.get("reference_strength_multiple")
        raw_strengths = list(raw_strengths) if isinstance(raw_strengths, list) else []
        refs: list[Any] = []
        strengths: list[Any] = []
        for index, ref in enumerate(raw_refs):
            # 직전 페이지에서 발급된 스트림 인코딩이 어떤 경로로든 params에 실려 왔다면
            # 걷어낸다 — 스트림이 추가하는 vibe는 항상 '현재' 1장뿐(이중 방어).
            if ref in issued:
                continue
            refs.append(ref)
            strengths.append(raw_strengths[index] if index < len(raw_strengths) else 0.6)
        # 공존하는 기존 Vibe Transfer 의 RS 는 절반(퍼센트 floor)으로 감쇠해 스트림 vibe 가
        # 상대적으로 더 지배하게 한다(Sequence 와 동일 패치). 스트림 vibe 자신은 풀 RS 유지.
        strengths = [halve_floor_strength(s) for s in strengths]
        refs.append(encoding)
        strengths.append(float(vibe.get("strength") or EVENT_STREAM_VIBE_STRENGTH))
        params["reference_image_multiple"] = refs
        params["reference_strength_multiple"] = strengths
        params.setdefault(
            "normalize_reference_strength_multiple",
            bool(getattr(self.context, "vibe_transfer_normalize", False)),
        )
        params[EVENT_STREAM_VIBE_MARKER_KEY] = {
            "run_id": str(runtime.run_id or ""),
            "encoding": encoding,
        }
