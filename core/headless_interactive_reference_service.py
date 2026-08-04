# -*- coding: utf-8 -*-
"""Interactive 전용 캐릭터 레퍼런스 — NAI 캐릭터 레퍼런스 모듈과 **독립**이다.

## 왜 따로 두나

Interactive 는 캐릭터 블록이 프롬프트의 소유자라서 NAI `character` 모듈을 막아
둔다. 레퍼런스도 같은 이유로 막혀 있었는데(`INTERACTIVE_BLOCKED_NAI_TOOLS` 에
`character_reference` 가 함께 있었다) 2026-08-04 에 그것을 풀고 세션 CR 모듈을
그대로 열게 했다 — 잘못이었다. 상태를 공유하니:

  · Interactive 에서 붙인 레퍼런스가 NAI 모듈 목록에 나타난다
  · NAI 쪽에서 켜 둔 프레임이 Interactive 생성에 몰래 섞인다
  · 상호배제(CR 켜면 Vibe 끔)가 세션 전역으로 번진다

선례는 캐릭터 에셋 벤치다(`headless_character_asset_service._bench_reference_params`).
**상태는 자기가 갖고 인코딩 유틸만 빌린다.** 이 서비스도 같은 규약이다 —
`image_data()` / `frame_from_bytes()` 는 CR 서비스 것을 쓰되, 프레임 목록은
여기 따로 산다.

## 생성에 실리는 길

`HeadlessImageModuleParamService.apply()` 는 요청에 이미
`director_reference_descriptions` 가 있으면 세션 CR 을 늦은바인딩하지 않는다.
그래서 Interactive 가 자기 파라미터를 실으면 NAI CR 은 저절로 비켜난다 —
가로채는 코드를 따로 두지 않았다.
"""
from __future__ import annotations

import json
from typing import Any

_STORE = "InteractiveReferenceModule"
MAX_FRAMES = 4          # NAI 스펙 상한과 같다. 넘겨 보내면 API 가 거부한다.
REFERENCE_TYPES = ("character&style", "character", "style")


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


class HeadlessInteractiveReferenceService:
    def __init__(self, context: Any):
        self.context = context

    # ------------------------------------------------------------------ 저장
    def _settings_mode(self) -> str:
        return str(getattr(self.context, "get_api_mode", lambda: "NAI")() or "NAI")

    def _cr(self):
        """인코딩 유틸만 빌린다. 프레임 목록은 건드리지 않는다."""
        return self.context._character_reference_service()

    def _path(self):
        return self.context._save_path(f"{_STORE}_{self._settings_mode()}.json")

    def _ensure_loaded(self) -> None:
        mode = self._settings_mode()
        if getattr(self.context, "_interactive_reference_loaded_mode", None) == mode:
            return
        self.context._interactive_reference_loaded_mode = mode
        self.context.interactive_reference_frames = self._load()

    def _load(self) -> list[dict[str, Any]]:
        try:
            path = self.context._existing_save_path(
                f"{_STORE}_{self._settings_mode()}.json")
            if not path.exists():
                return []
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        frames = raw.get("frames") if isinstance(raw, dict) else None
        out: list[dict[str, Any]] = []
        for item in (frames or []):
            if not isinstance(item, dict) or not item.get("image_data"):
                continue
            out.append({
                "file_hash": str(item.get("file_hash") or ""),
                "label": str(item.get("label") or ""),
                "image_data": str(item.get("image_data") or ""),
                "thumbnail": str(item.get("thumbnail") or ""),
                "reference_type": (
                    str(item.get("reference_type"))
                    if str(item.get("reference_type") or "") in REFERENCE_TYPES
                    else "character&style"),
                "strength": _as_float(item.get("strength"), 1.0),
                "fidelity": _as_float(item.get("fidelity"), 0.8),
            })
        return out[:MAX_FRAMES]

    def _persist(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # `image_bytes` 는 담지 않는다 — 원본은 출처(에셋/보관함)에 있고, 여기 두면
        # 세션 파일이 수십 MB 로 불어난다. 재사용에 필요한 것은 인코딩된 image_data 다.
        path.write_text(json.dumps(
            {"frames": self.context.interactive_reference_frames}, ensure_ascii=False),
            encoding="utf-8")

    # ------------------------------------------------------------------ 조회
    def frames(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return list(self.context.interactive_reference_frames)

    def state(self) -> dict[str, Any]:
        """프론트가 그리는 목록. 무거운 `image_data` 는 빼고 썸네일만 준다."""
        return {
            "frames": [{
                "file_hash": f.get("file_hash", ""),
                "label": f.get("label", ""),
                "thumbnail": f.get("thumbnail", ""),
                "reference_type": f.get("reference_type", "character&style"),
                "strength": f.get("strength", 1.0),
                "fidelity": f.get("fidelity", 0.8),
            } for f in self.frames()],
            "max": MAX_FRAMES,
        }

    # ------------------------------------------------------------------ 변경
    def attach_bytes(self, image_bytes: bytes, label: str = "") -> dict[str, Any]:
        if str(self.context.get_api_mode() or "").upper() != "NAI":
            raise ValueError("character reference requires NAI mode")
        frame = self._cr().frame_from_bytes(image_bytes, file_name=label or "reference.png")
        self._ensure_loaded()
        rows = self.context.interactive_reference_frames
        # 같은 그림을 두 번 붙이면 강도만 두 배가 된다 — 해시로 막는다.
        if any(r.get("file_hash") == frame["file_hash"] for r in rows):
            return {"ok": True, "duplicate": True, "count": len(rows)}
        if len(rows) >= MAX_FRAMES:
            raise ValueError(f"레퍼런스는 최대 {MAX_FRAMES}장입니다")
        rows.append({
            "file_hash": frame["file_hash"],
            "label": str(label or ""),
            "image_data": frame["image_data"],
            "thumbnail": frame["thumbnail"],
            "reference_type": frame["reference_type"],
            "strength": frame["strength"],
            "fidelity": frame["fidelity"],
        })
        self._persist()
        return {"ok": True, "count": len(rows)}

    def remove(self, file_hash: str) -> dict[str, Any]:
        self._ensure_loaded()
        key = str(file_hash or "")
        rows = self.context.interactive_reference_frames
        kept = [r for r in rows if r.get("file_hash") != key]
        self.context.interactive_reference_frames = kept
        self._persist()
        return {"ok": True, "count": len(kept)}

    def clear(self) -> dict[str, Any]:
        self._ensure_loaded()
        self.context.interactive_reference_frames = []
        self._persist()
        return {"ok": True, "count": 0}

    def set_param(self, file_hash: str, key: str, value: Any) -> dict[str, Any]:
        self._ensure_loaded()
        if key not in ("strength", "fidelity", "reference_type"):
            raise ValueError(f"unknown param: {key}")
        for row in self.context.interactive_reference_frames:
            if row.get("file_hash") != str(file_hash or ""):
                continue
            if key == "reference_type":
                # NAI 가 받는 값은 셋뿐이다. 아무 문자열이나 넣으면 base_caption 으로
                # 그대로 나가 API 가 거부한다(기존 CR 서비스도 같은 목록을 쓴다).
                v = str(value or "character&style")
                if v not in REFERENCE_TYPES:
                    raise ValueError(f"unknown reference_type: {v!r}")
                row[key] = v
            else:
                row[key] = max(0.0, min(1.0, _as_float(value, row.get(key, 1.0))))
            self._persist()
            return {"ok": True}
        raise KeyError(file_hash)

    # ------------------------------------------------------------------ 생성
    def active_params(self) -> dict[str, Any]:
        """생성 요청에 실을 파라미터. CR 서비스의 같은 이름 함수와 **모양이 같다**
        (NAI 스펙이라 형태를 바꿀 수 없다). 다른 것은 읽는 목록뿐이다."""
        if not self.context._is_naid45_model():
            return {}
        rows = [f for f in self.frames() if f.get("image_data")]
        if not rows:
            return {}
        return {
            "director_reference_descriptions": [{
                "caption": {"base_caption": str(f.get("reference_type") or "character&style"),
                            "char_captions": []},
                "legacy_uc": False,
            } for f in rows],
            "director_reference_images": [str(f["image_data"]) for f in rows],
            "director_reference_information_extracted": [1] * len(rows),
            "director_reference_strength_values": [
                round(max(0.0, min(1.0, _as_float(f.get("strength"), 1.0))) * 20) / 20.0
                for f in rows],
            "director_reference_secondary_strength_values": [
                round((1.0 - max(0.0, min(1.0, _as_float(f.get("fidelity"), 0.8)))) * 20) / 20.0
                for f in rows],
            "controlnet_strength": 1,
            "inpaintImg2ImgStrength": 1,
            "normalize_reference_strength_multiple": True,
        }
