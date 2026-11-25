"""프롬프트의 `ref:` 호출 - 보관함 그림을 **그 장에만** Character Reference 칸으로 더한다(사용자 지시 2026-11-25).

문법(쉼표로 나뉜 한 조각 전체가 호출이어야 한다):
    ref:폴더:이름[:강도]      폴더의 그 그림(이름 = 보관함에 보이는 이름 · 대소문자 무시 · 또는 해시 앞 6자 이상)
    ref:__폴더__[:강도]       폴더에서 무작위 한 장
    ref:__*폴더__[:강도]      폴더를 차례로(장마다 다음 그림 · 프로세스가 살아 있는 동안)
강도를 빼면 1.0(사용자 결정). 폴더 이름은 세 분류(캐릭터 · 의상 · 스타일)를 통틀어 하나라 분류는 폴더가 정한다.

종류: 의상 폴더 = Outfit(costume) · 스타일 폴더 = Style · 캐릭터 폴더 = 그 그림에 저장된 캐릭터 종류(없으면 Char&Style).
Fidelity(V4.5)는 그림에 저장된 값. 그림은 보관함 원본(images/<해시>.png) - 모델에 맞추기는 요청 목의 adapt_payload 가 한다.

활성 칸은 건드리지 않는다 - 요청에만 칸을 덧붙인다(활성 칸에 더하기 · 사용자 결정).
"""
from __future__ import annotations

import math
import random
import re
import threading
from typing import Any

from core.nai_character_reference_spec import (
    DEFAULT_REFERENCE_TYPE,
    STRENGTH_STORE_MAX,
    normalize_reference_type,
    source_image_data,
)

REF_PREFIX = "ref:"
STRENGTH_DEFAULT = 1.0
GROUP_TYPE = {"outfit": "costume", "style": "style"}
_CHAR_TYPES = ("character&style", "character&style_anyoutfit", "character", "character_mainoutfit")
_WILD = re.compile(r"__(\*?)(.+?)__(?::\s*(.*))?", re.S)
_HASH_PREFIX_MIN = 6

# 차례 호출(`ref:__*폴더__`)의 다음 자리 - 폴더 id 마다. 재시도는 같은 해석을 다시 쓰므로 넘기지 않는다(api_service).
_sequence: dict[str, int] = {}
_sequence_lock = threading.Lock()


class RefPromptError(ValueError):
    """사용자에게 그대로 보여 줄 글."""


def is_ref_token(text: Any) -> bool:
    return str(text or "").strip()[:4].lower() == REF_PREFIX


def parse_ref_token(text: str) -> dict[str, Any]:
    token = str(text).strip()
    body = token[4:].strip()
    match = _WILD.fullmatch(body)
    if match:
        mode = "sequential" if match.group(1) else "random"
        folder, name, strength_text = match.group(2).strip(), "", match.group(3)
    else:
        parts = [part.strip() for part in body.split(":")]
        if len(parts) not in (2, 3) or not parts[0] or not parts[1]:
            raise RefPromptError(f"'{token}' - ref:폴더:이름[:강도] 또는 ref:__폴더__[:강도] 로 쓰세요")
        mode, folder, name = "name", parts[0], parts[1]
        strength_text = parts[2] if len(parts) == 3 else None
    if not folder:
        raise RefPromptError(f"'{token}' - 폴더 이름이 비었습니다")
    strength = STRENGTH_DEFAULT
    if strength_text is not None:
        try:
            strength = float(str(strength_text).strip())
        except ValueError:
            raise RefPromptError(f"'{token}' - 강도 '{strength_text}' 를 숫자로 읽지 못했습니다") from None
        if not math.isfinite(strength) or strength < 0:
            raise RefPromptError(f"'{token}' - 강도는 0 이상이어야 합니다")
        strength = min(STRENGTH_STORE_MAX, strength)
    return {"token": token, "mode": mode, "folder": folder, "name": name, "strength": strength}


def split_ref_tokens(prompt: Any) -> tuple[Any, list[str]]:
    """쉼표 조각 중 `ref:` 호출을 걷는다 - (남은 프롬프트, 호출들). 호출이 없으면 원문을 그대로 돌려준다."""
    if not isinstance(prompt, str) or REF_PREFIX not in prompt.lower():
        return prompt, []
    kept, found = [], []
    for piece in prompt.split(","):
        (found if is_ref_token(piece) else kept).append(piece.strip())
    if not found:
        return prompt, []
    return ", ".join(piece for piece in kept if piece), found


def _pick(call: dict[str, Any], folder: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in folder["items"] if item.get("has_image", True)]
    if not items:
        raise RefPromptError(f"'{call['token']}' - 폴더 '{folder['name']}' 에 그림이 없습니다")
    if call["mode"] == "random":
        return random.choice(items)
    if call["mode"] == "sequential":
        with _sequence_lock:
            index = _sequence.get(folder["id"], 0)
            _sequence[folder["id"]] = index + 1
        return items[index % len(items)]
    wanted = call["name"].casefold()
    hits = [item for item in items if str(item.get("display_name") or "").casefold() == wanted]
    if not hits and len(wanted) >= _HASH_PREFIX_MIN:
        hits = [item for item in items if str(item.get("file_hash") or "").casefold().startswith(wanted)]
    if not hits:
        raise RefPromptError(f"'{call['token']}' - 폴더 '{folder['name']}' 에 '{call['name']}' 이 없습니다")
    if len(hits) > 1:
        raise RefPromptError(f"'{call['token']}' - 폴더 '{folder['name']}' 에 '{call['name']}' 이 {len(hits)}장입니다"
                             " - 이름을 하나로 바꾸거나 해시 앞자리로 부르세요")
    return hits[0]


def _reference_type(group: str, settings: dict[str, Any]) -> str:
    if group in GROUP_TYPE:
        return GROUP_TYPE[group]
    stored = normalize_reference_type((settings or {}).get("reference_type"))
    return stored if stored in _CHAR_TYPES else DEFAULT_REFERENCE_TYPE


def resolve_ref_tokens(library: Any, tokens: list[str]) -> list[dict[str, Any]]:
    """호출들을 보낼 칸으로. 하나라도 못 찾으면 RefPromptError(생성을 멈추고 까닭을 보여 준다)."""
    if not tokens:
        return []
    from PIL import Image

    calls = [parse_ref_token(token) for token in tokens]
    folders = {folder["name"].casefold(): folder for folder in library.callable_folders()}
    frames = []
    for call in calls:
        folder = folders.get(call["folder"].casefold())
        if folder is None:
            raise RefPromptError(f"'{call['token']}' - 폴더 '{call['folder']}' 이 보관함에 없습니다")
        item = _pick(call, folder)
        file_hash = str(item["file_hash"])
        settings = item.get("settings") or {}
        try:
            with Image.open(library.character_image_path(file_hash)) as opened:
                opened.load()
                image_data = source_image_data(opened)
        except RefPromptError:
            raise
        except Exception as exc:
            raise RefPromptError(f"'{call['token']}' - 그림을 읽지 못했습니다({type(exc).__name__})") from None
        try:
            fidelity = max(0.0, min(1.0, float(settings.get("fidelity", 0.8))))
        except (TypeError, ValueError):
            fidelity = 0.8
        frames.append({
            "token": call["token"],
            "folder": folder["name"],
            "group": folder["group"],
            "file_hash": file_hash,
            "name": str(item.get("display_name") or file_hash),
            "reference_type": _reference_type(folder["group"], settings),
            "strength": call["strength"],
            "secondary_strength": round((1.0 - fidelity) * 20) / 20.0,
            "image_data": image_data,
        })
    return frames


def append_to_director_lists(api_parameters: dict[str, Any], frames: list[dict[str, Any]]) -> None:
    """요청의 director_* 목록 뒤에 칸을 붙인다(활성 칸 뒤 · adapt_payload 전에)."""
    if not frames:
        return
    for frame in frames:
        api_parameters.setdefault("director_reference_descriptions", []).append(
            {"caption": {"base_caption": frame["reference_type"], "char_captions": []}, "legacy_uc": False})
        api_parameters.setdefault("director_reference_images", []).append(frame["image_data"])
        api_parameters.setdefault("director_reference_information_extracted", []).append(1)
        api_parameters.setdefault("director_reference_strength_values", []).append(frame["strength"])
        api_parameters.setdefault("director_reference_secondary_strength_values", []).append(frame["secondary_strength"])
    # CR 을 실을 때의 곁 설정 - 활성 칸이 없고 ref: 만 있어도 같게(headless_character_reference_service.active_params)
    api_parameters.pop("skip_cfg_above_sigma", None)
    api_parameters.setdefault("controlnet_strength", 1)
    api_parameters.setdefault("inpaintImg2ImgStrength", 1)
    api_parameters["normalize_reference_strength_multiple"] = True


def describe(frames: list[dict[str, Any]]) -> str:
    return " · ".join(f"{f['folder']}:{f['name']}({f['reference_type']} {f['strength']:g})" for f in frames)
