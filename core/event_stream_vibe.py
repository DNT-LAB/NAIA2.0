"""Storyteller "Use Vibe" 파라미터 계약 — 1회성 스트림 vibe의 비영속 보장.

스트림이 발급한 vibe reference는 휘발성이다: 히스토리 메타/리플레이/정지 후 실행되는
큐 잔존 요청 어디에도 남으면 안 된다. 주입부(headless_image_module_param_service)가
params에 마커를 함께 싣고, 저장(add_api_result)·리플레이(_history_item_replay_params)·
실행 시점 검증(execute_request)이 이 모듈의 strip으로 **스트림 발급분만** 정밀 제거한다
— 일반 Vibe Transfer refs는 절대 건드리지 않는다.
"""

from __future__ import annotations

from typing import Any

# 생성 params에 싣는 키. 언더스코어 키라 Auto Gen continuation overrides에는 복사되지
# 않는다(generation_runner._auto_generation_overrides의 화이트리스트 밖).
EVENT_STREAM_VIBE_CAPTURE_KEY = "_event_stream_vibe_capture"  # 값=run_id (완료 시 캡처 게이트)
EVENT_STREAM_VIBE_MARKER_KEY = "_event_stream_vibe"           # 값={run_id, encoding} (주입 마커)

# Storyteller "Use Vibe" 사용자 확정 사양: encode IE 0.6, reference strength 0.9.
EVENT_STREAM_VIBE_IE = 0.6
EVENT_STREAM_VIBE_STRENGTH = 0.9

# Sequence "첫 이미지를 Vibe로 사용" 임시 vibe 전용 IE/RS — Storyteller(위)와 분리해 독립 튜닝
# (사용자 최종 확정값). encode IE 1.0, 임시 vibe reference strength 0.6. (공존하는 기존
# Vibe Transfer 의 RS 는 _halve_floor_strength 로 별도 절반 처리.)
SEQUENCE_VIBE_IE = 1.0
SEQUENCE_VIBE_STRENGTH = 0.6

_REFERENCE_PARAM_KEYS = (
    "reference_image_multiple",
    "reference_strength_multiple",
    "normalize_reference_strength_multiple",
    "reference_information_extracted_multiple",
)


def strip_event_stream_vibe_params(params: dict[str, Any]) -> bool:
    """스트림 발급 vibe 1장만 reference 리스트에서 제거하고 마커를 지운다.

    마커가 없으면 키 정리 외 no-op(False 반환). 일반 vibe refs는 strength 인덱스
    정렬을 유지한 채 보존한다. 스트림 vibe뿐이었다면 reference 파라미터 자체를 비운다.
    """
    marker = params.pop(EVENT_STREAM_VIBE_MARKER_KEY, None)
    params.pop(EVENT_STREAM_VIBE_CAPTURE_KEY, None)
    if not isinstance(marker, dict):
        return False
    encoding = str(marker.get("encoding") or "")
    refs = params.get("reference_image_multiple")
    if not encoding or not isinstance(refs, list) or encoding not in refs:
        return False
    strengths = params.get("reference_strength_multiple")
    strengths = strengths if isinstance(strengths, list) else []
    kept_refs: list[Any] = []
    kept_strengths: list[Any] = []
    for index, ref in enumerate(refs):
        if ref == encoding:
            continue
        kept_refs.append(ref)
        if index < len(strengths):
            kept_strengths.append(strengths[index])
    if kept_refs:
        params["reference_image_multiple"] = kept_refs
        if "reference_strength_multiple" in params:
            params["reference_strength_multiple"] = kept_strengths
    else:
        for key in _REFERENCE_PARAM_KEYS:
            params.pop(key, None)
    return True
