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
from collections import Counter
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
_SAME_OUTFIT_OFF = {"character&style": "character&style_anyoutfit", "character_mainoutfit": "character"}
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
    # 마지막 다듬기가 괄호를 `\(` 로 감싼다 - 이름의 괄호는 글 그대로 읽는다
    body = token[4:].strip().replace("\\(", "(").replace("\\)", ")")
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
    stored = stored if stored in _CHAR_TYPES else DEFAULT_REFERENCE_TYPE
    # 프롬프트로 부른 캐릭터는 '같은 옷 유지(Prefer same outfit)' 를 끈다(사용자 지시 2026-11-25) - 옷은 의상 호출 ·
    # 프롬프트가 정한다. 보관 그림에 적힌 종류는 그대로 두고 이 호출에서만 끈 쪽으로 바꾼다.
    return _SAME_OUTFIT_OFF.get(stored, stored)


def _one_line(text: Any) -> str:
    pieces = [piece.strip() for line in str(text or "").splitlines() for piece in line.split(",")]
    return ", ".join(piece for piece in pieces if piece and not is_ref_token(piece))


def call_text(item: dict[str, Any], group: str) -> tuple[str, str]:
    """부른 자리에 넣을 (프롬프트, 네거티브). 꺼 두었으면 둘 다 빈 글.
    캐릭터 그림 = 캐릭터 프롬프트(슬롯을 대치) · 의상 · 스타일 = 호출 프롬프트(부른 자리에)."""
    if item.get("call_prompt_on") is False:
        return "", ""
    if group == "character":
        return _one_line(item.get("character_prompt")), _one_line(item.get("character_uc"))
    return _one_line(item.get("call_prompt")), _one_line(item.get("call_uc"))


_CALL_NAME_BAD = (":", ",", "__", "\\")


def call_names(folder_items: list[dict[str, Any]]) -> dict[str, str]:
    """폴더 안 그림마다 **그 그림 하나만** 가리키는 호출 이름(해시 -> 이름) - 호출 복사 · 자동완성 · 와일드카드 기록이 같이 쓴다.
    - 이름이 있고 폴더에서 하나뿐이고 갈라지는 글자가 없으면 이름.
    - 아니면 해시 앞 8자 - 그 8자가 다른 그림의 **이름**이거나 다른 해시와 겹치면 해시 전체(`_pick` 은 이름을 먼저 본다 ·
      Codex 리뷰 2차 #2). 빈도는 한 번만 센다(분류 전체 폴더가 커도 줄마다 다시 훑지 않는다 · 2차 #10)."""
    names = Counter(str(item.get("display_name") or "").casefold() for item in folder_items)
    prefixes = Counter(str(item.get("file_hash") or "")[:8].casefold() for item in folder_items)
    out: dict[str, str] = {}
    for item in folder_items:
        file_hash = str(item.get("file_hash") or "")
        name = str(item.get("display_name") or "")
        if (name and name != file_hash and name == name.strip() and names[name.casefold()] == 1
                and not any(mark in name for mark in _CALL_NAME_BAD)):
            out[file_hash] = name
            continue
        short = file_hash[:8]
        out[file_hash] = file_hash if (names.get(short.casefold()) or prefixes[short.casefold()] > 1) else short
    return out


def resolved_call(frame: dict[str, Any], folder_items: list[dict[str, Any]]) -> str:
    """고른 그림을 다시 같은 그림으로 부르는 글 - 와일드카드 호출을 기록에 남길 때(파생 요청이 다시 굴리지 않게)."""
    name = call_names(folder_items).get(frame["file_hash"]) or str(frame["file_hash"])
    strength = "" if frame["strength"] == STRENGTH_DEFAULT else f":{frame['strength']:g}"
    return f"ref:{frame['folder']}:{name}{strength}"


def check_pickable(call: dict[str, Any], folder: dict[str, Any]) -> None:
    """고르기 전에 틀린 호출을 잡는다(이름 없음 · 이름 겹침 · 빈 폴더) - 차례를 굴리지 않는다(Codex 리뷰 2차 #4)."""
    if call["mode"] == "name":
        _pick(call, folder)                       # 이름 호출은 굴림이 없다 - 찾기만 한다
    elif not any(item.get("has_image", True) for item in folder["items"]):
        raise RefPromptError(f"'{call['token']}' - 폴더 '{folder['name']}' 에 그림이 없습니다")


def _folder_index(library: Any) -> dict[str, dict[str, Any]]:
    return {folder["name"].casefold(): folder for folder in library.callable_folders()}


def resolve_ref_call(library: Any, token: str, *, folders: dict[str, dict[str, Any]] | None = None,
                     scope: str = "main") -> dict[str, Any]:
    """호출 하나를 칸으로. 못 찾으면 RefPromptError(생성을 멈추고 까닭을 보여 준다).
    캐릭터 분류는 캐릭터 프롬프트에서만 부른다(사용자 결정) - 메인에서 부르면 고르기 전에 멈춘다(차례가 안 넘어간다)."""
    folders = folders if folders is not None else _folder_index(library)
    call, folder = locate_ref_call(token, folders, scope)
    return frame_for(library, call, folder)


def locate_ref_call(token: str, folders: dict[str, dict[str, Any]], scope: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """호출의 폴더를 찾고 부를 수 있는 자리인지 본다 - 그림은 아직 안 고른다(차례가 안 넘어간다)."""
    call = parse_ref_token(token)
    folder = folders.get(call["folder"].casefold())
    if folder is None:
        raise RefPromptError(f"'{call['token']}' - 폴더 '{call['folder']}' 이 보관함에 없습니다")
    if scope != "char" and folder["group"] == "character":
        raise RefPromptError(f"'{call['token']}' - 캐릭터 분류 폴더는 캐릭터 프롬프트 칸에서만 부를 수 있습니다")
    return call, folder


def frame_for(library: Any, call: dict[str, Any], folder: dict[str, Any]) -> dict[str, Any]:
    """찾은 폴더에서 그림을 고르고(차례 · 무작위는 여기서 굴린다) 칸을 만든다."""
    from PIL import Image

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
    prompt, uc = call_text(item, folder["group"])
    frame = {
        "token": call["token"],
        "mode": call["mode"],
        "folder": folder["name"],
        "group": folder["group"],
        "file_hash": file_hash,
        "display_name": str(item.get("display_name") or ""),
        "name": str(item.get("display_name") or file_hash),
        "reference_type": _reference_type(folder["group"], settings),
        "strength": call["strength"],
        "secondary_strength": round((1.0 - fidelity) * 20) / 20.0,
        "prompt": prompt,
        "uc": uc,
        "image_data": image_data,
    }
    frame["call"] = resolved_call(frame, folder["items"])
    return frame


def resolve_ref_tokens(library: Any, tokens: list[str], *, scope: str = "char") -> list[dict[str, Any]]:
    """호출들을 칸으로(시험 · 도구용 - 생성 길은 RefCallSession)."""
    folders = _folder_index(library) if tokens else {}
    return [resolve_ref_call(library, token, folders=folders, scope=scope) for token in tokens]


def _join(*texts: Any) -> str:
    return ", ".join(str(text).strip() for text in texts if str(text or "").strip())


class RefCallSession:
    """NAI 요청 하나(시도 하나)의 `ref:` 호출 - 프롬프트 · 캐릭터 프롬프트를 **부른 자리에서** 풀어 쓴다.

    - 메인(`scope="main"` · 앞뒤 고정 포함): 호출 자리에 호출 프롬프트 · 네거티브는 메인 네거티브 끝에.
    - 캐릭터(`scope="char"`): 의상 · 스타일은 호출 자리에 · 캐릭터 그림은 그 슬롯을 대치(캐릭터 프롬프트가 맨 앞,
      슬롯에 따로 적은 태그는 뒤에 남는다) · 네거티브는 그 캐릭터의 네거티브 끝에.
    - 막힘(그림도 글도 안 넣음): V4.5 의 Outfit · V5 인페인트. CR 을 못 받는 모델은 오류(멈춤).
    - 해석은 `cache`(params 에 둔다)에 자리 + 글로 적어 재시도가 같은 그림을 쓴다(차례 호출이 안 넘어간다).
    """

    def __init__(self, library_getter, cache: dict, *, profile: Any, inpainting: bool, model_name: str = ""):
        self._library_getter = library_getter
        self._library = None
        self._folders = None
        self.cache = cache
        self.profile = profile
        self.inpainting = inpainting
        self.model_name = model_name
        self.frames: list[dict[str, Any]] = []

    def _locate(self, token: str, scope: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._library is None:
            self._library = self._library_getter()
            self._folders = _folder_index(self._library)
        return locate_ref_call(token, self._folders, scope)

    def _group_block(self, group: str) -> str:
        """그림을 고르기 전에 정해지는 막힘(모델 · 작업 · 분류만 본다) - 막힌 호출은 그림을 고르지도 읽지도 않는다."""
        from core.nai_character_reference_spec import wire_type

        if self.inpainting and not self.profile.inpaint:
            return "V5 인페인트는 Character Reference 를 받지 않는다"
        if group in GROUP_TYPE and wire_type(GROUP_TYPE[group], self.profile) is None:
            return "이 모델은 Outfit 을 받지 않는다"
        return ""

    def blocked(self, frame: dict[str, Any]) -> str:
        from core.nai_character_reference_spec import wire_type

        if frame.get("unpicked"):
            return frame["blocked"]
        if self.inpainting and not self.profile.inpaint:
            return "V5 인페인트는 Character Reference 를 받지 않는다"
        if wire_type(frame["reference_type"], self.profile) is None:
            return "이 모델은 Outfit 을 받지 않는다"
        return ""

    def render(self, text: Any, scope: str, slot: int = 0) -> tuple[Any, str]:
        """(풀어 쓴 글, 덧붙일 네거티브). 호출이 없으면 글을 그대로 돌려준다."""
        if not isinstance(text, str) or REF_PREFIX not in text.lower():
            return text, ""
        pieces = text.split(",")
        if not any(is_ref_token(piece) for piece in pieces):
            return text, ""
        if self.profile is None:
            raise RefPromptError(f"이 모델({self.model_name})은 Character Reference 를 받지 않아 ref: 를 쓸 수 없습니다")
        # 1) 이 글의 호출을 **모두** 찾고 자리를 본다 - 하나라도 틀리면 아무것도 고르기 전에 멈춘다(Codex 리뷰 #3:
        #    앞 호출이 차례를 먹은 뒤 뒤 호출이 오류면, 고쳐 다시 눌렀을 때 한 장을 건너뛰었다).
        located: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        occurrence = 0
        for piece in pieces:
            piece = piece.strip()
            if is_ref_token(piece):
                key = f"{scope}|{slot}|{occurrence}|{piece}"
                occurrence += 1
                if key not in self.cache:
                    call, folder = located[key] = self._locate(piece, scope)
                    if not self._group_block(folder["group"]):
                        check_pickable(call, folder)        # 막힌 호출은 고르지 않으니 묻지도 않는다
        lead, kept, negatives = [], [], []
        occurrence = 0
        for piece in pieces:
            piece = piece.strip()
            if not is_ref_token(piece):
                kept.append(piece)
                continue
            key = f"{scope}|{slot}|{occurrence}|{piece}"
            occurrence += 1
            frame = self.cache.get(key)
            if frame is None:
                call, folder = located[key]
                reason = self._group_block(folder["group"])
                if reason:
                    # 2) 막힌 호출은 고르지 않는다(빈 폴더 · 지운 그림이어도 멈추지 않는다 · 와일드카드는 그대로 남는다)
                    frame = {"token": call["token"], "mode": call["mode"], "folder": folder["name"],
                             "group": folder["group"], "call": call["token"], "strength": call["strength"],
                             "prompt": "", "uc": "", "unpicked": True, "blocked": reason}
                else:
                    frame = frame_for(self._library, call, folder)
                frame.update(scope=scope, slot=slot, occurrence=occurrence - 1)
                self.cache[key] = frame
            frame["blocked"] = self.blocked(frame)
            if frame["blocked"]:
                print(f"  - [REF] {piece} - {frame['blocked']} - 그림도 글도 넣지 않았다")
                continue
            self.frames.append(frame)
            if frame["prompt"]:
                (lead if (scope == "char" and frame["group"] == "character") else kept).append(frame["prompt"])
            if frame["uc"]:
                negatives.append(frame["uc"])
        return _join(*lead, *kept), _join(*negatives)


def finish_main_prompt(prompt: Any, cache: dict) -> Any:
    """끝난 요청의 메인 프롬프트 - 와일드카드 호출(`ref:__폴더__`)을 고른 그림의 호출로 바꿔 둔다.
    기록 · 다시 생성 · 파생 요청이 다시 굴리지 않는다. 이름 호출은 그대로."""
    if not isinstance(prompt, str) or not cache:
        return prompt
    pieces = prompt.split(",")
    occurrence = 0
    changed = False
    for index, piece in enumerate(pieces):
        token = piece.strip()
        if not is_ref_token(token):
            continue
        frame = cache.get(f"main|0|{occurrence}|{token}")
        occurrence += 1
        if frame and frame.get("mode") in ("random", "sequential"):
            pieces[index] = (" " if index else "") + frame["call"]
            changed = True
    return ",".join(pieces) if changed else prompt


def ref_picks(cache: dict) -> list[dict[str, Any]]:
    """생성 정보에 남길 짧은 기록(그림 base64 는 안 남긴다)."""
    keys = ("token", "scope", "slot", "folder", "name", "file_hash", "reference_type", "strength", "blocked")
    picks = []
    for frame in (cache or {}).values():
        pick = {key: frame.get(key) for key in keys}
        pick["prompt_applied"] = bool(frame.get("prompt") or frame.get("uc")) and not frame.get("blocked")
        picks.append(pick)
    return picks


def append_to_director_lists(api_parameters: dict[str, Any], frames: list[dict[str, Any]]) -> None:
    """요청의 director_* 목록 뒤에 칸을 붙인다(활성 칸 뒤 · adapt_payload 전에)."""
    if not frames:
        return
    # ⚠️ 새 목록으로 - 활성 칸 목록은 params · GenerationRequest 의 것을 그대로 가리킨다(같은 객체).
    #    제자리에 붙이면 재시도마다 칸이 또 붙고, 생성 정보 · 파생 요청에 base64 가 남는다.
    added = {
        "director_reference_descriptions": [
            {"caption": {"base_caption": frame["reference_type"], "char_captions": []}, "legacy_uc": False}
            for frame in frames],
        "director_reference_images": [frame["image_data"] for frame in frames],
        "director_reference_information_extracted": [1 for _ in frames],
        "director_reference_strength_values": [frame["strength"] for frame in frames],
        "director_reference_secondary_strength_values": [frame["secondary_strength"] for frame in frames],
    }
    for key, values in added.items():
        api_parameters[key] = list(api_parameters.get(key) or []) + values
    # CR 을 실을 때의 곁 설정 - 활성 칸이 없고 ref: 만 있어도 같게(headless_character_reference_service.active_params)
    api_parameters.pop("skip_cfg_above_sigma", None)
    api_parameters.setdefault("controlnet_strength", 1)
    api_parameters.setdefault("inpaintImg2ImgStrength", 1)
    api_parameters["normalize_reference_strength_multiple"] = True


# ── 자동완성(프롬프트 칸에서 `ref:` 를 치면) ────────────────────────────────────
GROUP_LABEL = {"character": "캐릭터", "outfit": "의상", "style": "스타일"}
TYPE_LABEL = {"costume": "Outfit", "style": "Style", "character&style": "Char&Style",
              "character&style_anyoutfit": "Char&Style", "character": "Character", "character_mainoutfit": "Character"}


def _rank(text: str, needle: str) -> int | None:
    low = text.casefold()
    if not needle:
        return 3
    if low == needle:
        return 0
    if low.startswith(needle):
        return 1
    if needle in low:
        return 2
    return None


def _thumbs(folder: dict[str, Any], count: int = 6) -> list[str]:
    return [str(i.get("thumbnail_url")) for i in folder["items"] if i.get("thumbnail_url")][:count]


def search_ref_calls(library: Any, query: str, limit: int = 14, scope: str = "") -> list[dict[str, Any]]:
    """`ref:` 뒤에 친 글로 후보를 낸다.
    - `폴더`(콜론 전): 맞는 폴더(-> ref:폴더: 로 이어 치기) + 이름이 맞는 그림(-> ref:폴더:이름)
    - `__` · `__*`: 폴더 무작위 · 차례 호출
    - `폴더:이름`: 그 폴더의 그림(이름을 비우면 무작위 · 차례 호출도 맨 위에)
    - 강도(`:1.5`)를 치는 중이면 후보 없음.
    `scope="main"`(메인 · 앞뒤 고정 칸) = 캐릭터 분류 폴더는 빼고(거기서 못 부른다 · 사용자 결정)."""
    text = str(query or "").strip()
    parts = text.split(":")
    if len(parts) >= 3:
        return []
    folders = library.callable_folders()
    if scope == "main":
        folders = [folder for folder in folders if folder["group"] != "character"]
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    names_by_folder: dict[str, dict[str, str]] = {}

    def names_of(folder):
        if folder["id"] not in names_by_folder:
            names_by_folder[folder["id"]] = call_names(folder["items"])
        return names_by_folder[folder["id"]]

    def wild_ok(folder, sequential):
        # 그림이 없으면 반드시 실패한다(2차 #9) · `*` 로 시작하는 옛 폴더의 무작위는 `ref:__*폴더__` 가 되어
        # 다른 폴더의 차례 호출로 읽힌다 - 그 줄은 안 낸다(2차 #3 · 차례는 `ref:__**폴더__` 로 맞게 읽힌다)
        has = any(item.get("has_image", True) for item in folder["items"])
        return has and (sequential or not folder["name"].startswith("*"))

    def folder_row(folder):
        count = len(folder["items"])
        whole = "분류 전체 · " if folder.get("virtual") else ""
        return {"tag": folder["name"], "value": f"ref:{folder['name']}:", "_wc_type": "ref_folder", "cat": "",
                "group": GROUP_LABEL.get(folder["group"], folder["group"]), "desc": f"{whole}{count}장",
                "preview": f"{whole}{count}장 - 고르면 그림 이름을 이어서 고릅니다", "thumbs": _thumbs(folder)}

    def wild_row(folder, sequential):
        mark = "*" if sequential else ""
        return {"tag": f"__{mark}{folder['name']}__", "value": f"ref:__{mark}{folder['name']}__", "_wc_type": "ref_wild",
                "cat": "", "group": GROUP_LABEL.get(folder["group"], folder["group"]),
                "desc": "차례로" if sequential else "무작위",
                "preview": ("장마다 다음 그림" if sequential else "장마다 무작위 한 장") + f" · {len(folder['items'])}장"
                           " · 끝에 :1.5 처럼 강도(생략 = 1.0)",
                "thumbs": _thumbs(folder)}

    def item_row(folder, item):
        reference_type = _reference_type(folder["group"], item.get("settings") or {})
        return {"tag": f"{folder['name']}:{item.get('display_name') or item.get('file_hash')}",
                "value": f"ref:{folder['name']}:{names_of(folder).get(item.get('file_hash'), item.get('file_hash'))}",
                "_wc_type": "ref_item", "cat": "",
                "group": GROUP_LABEL.get(folder["group"], folder["group"]),
                "desc": TYPE_LABEL.get(reference_type, reference_type),
                "preview": f"{TYPE_LABEL.get(reference_type, reference_type)} · 끝에 :1.5 처럼 강도(생략 = 1.0)",
                "thumb": str(item.get("thumbnail_url") or "")}

    if len(parts) == 2:
        folder = next((f for f in folders if f["name"].casefold() == parts[0].strip().casefold()), None)
        if folder is None:
            return []
        needle = parts[1].strip().casefold()
        if not needle:
            ranked += [(-1, n, wild_row(folder, seq)) for n, seq in enumerate((False, True)) if wild_ok(folder, seq)]
        for index, item in enumerate(folder["items"]):
            rank = _rank(str(item.get("display_name") or ""), needle)
            if rank is None and len(needle) >= 2 and str(item.get("file_hash") or "").startswith(needle):
                rank = 2
            if rank is not None:
                ranked.append((rank, index, item_row(folder, item)))
    elif text.startswith("__"):
        sequential = text.startswith("__*")
        needle = text[3 if sequential else 2:].rstrip("_").strip().casefold()
        for index, folder in enumerate(folders):
            rank = _rank(folder["name"], needle)
            if rank is not None and wild_ok(folder, sequential):
                ranked.append((rank, index, wild_row(folder, sequential)))
    else:
        needle = text.casefold()
        for index, folder in enumerate(folders):
            rank = _rank(folder["name"], needle)
            if rank is not None:
                ranked.append((rank, index * 3, folder_row(folder)))
                # 폴더 이름을 치는 중이면 그 폴더의 무작위 · 차례 호출도 바로 아래에(사용자 2026-11-25 - `ref:캐릭터`)
                if needle:
                    ranked += [(rank, index * 3 + 1 + n, wild_row(folder, seq))
                               for n, seq in enumerate((False, True)) if wild_ok(folder, seq)]
        if needle:
            order = len(folders) * 3
            for folder in folders:
                for item in folder["items"]:
                    rank = _rank(str(item.get("display_name") or ""), needle)
                    if rank is not None:
                        ranked.append((rank + 4, order, item_row(folder, item)))
                        order += 1
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [row for _, _, row in ranked[:limit]]


def describe(frames: list[dict[str, Any]]) -> str:
    return " · ".join(f"{f['folder']}:{f['name']}({f['reference_type']} {f['strength']:g})" for f in frames)
