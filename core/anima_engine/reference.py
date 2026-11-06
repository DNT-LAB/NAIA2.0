"""ANIMA 참조(Ref Adapter v2 · 사용자 지정 2026-11-05) - 켠 Char Ref 칸 + 설정 -> 관리형 생성 요청.

- 칸은 Character Reference 서비스의 것 그대로다. 그 서비스는 칸을 모드별 파일(CharacterReferenceModule_{mode}.json)에
  두므로 ANIMA(COMFYUI 모드)의 칸은 NAI 의 칸과 따로다. 그림 보관함(save/character_reference/images)은 같이 쓴다.
- 설정(참조 세기 등)은 칸이 아니라 ANIMA 참조 전체에 하나 - save/anima_reference.json. 기본값 = 제작자 기본값.
- 여러 장(최대 MAX_REFS)은 NAIA 가 높이를 맞춰 왼쪽부터 나란히 붙여 한 장으로 보낸다(어댑터는 그림 하나를 받고, 두
  캐릭터는 나란히 붙인 그림으로 그리는 방식 - 원격 실측 11-05: 2 · 3장 모두 제자리에 나왔고 시간은 1장과 같다).
- 큐에 넣을 때 켠 칸(해시)과 설정을 잡고(snapshot), 보낼 때 그림을 읽어 붙이고 엔진 input 에 올린다(upload).
- 칸마다 저장한 캐릭터 프롬프트는 큐에 넣을 때 프롬프트 끝에 싣는다(사용자 지정 2026-11-06 · 선행 고정 칸을 고치지
  않는다). 1장 = (character at center: 태그:0.8) · 2~3장 = 칸 차례대로 'the girl on the left is a girl with 태그…'.
  원격 실측 11-06: 여러 장에서 자리를 정하는 것은 붙인 그림의 차례가 아니라 이 글이다 - 태그 목록 그대로나
  (character at left: …:0.8) 은 맞바꿔도 자리가 그대로였고, 문장형은 맞바꾼 것까지 8/8. top/bottom 은 0/4 라 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import io
import json
from typing import Any

from .profile import REF_CORRECTIONS, REF_DEFAULTS, REF_RANGES

MAX_REFS = 3
SETTINGS_FILE = "anima_reference.json"
PROMPT_OPTION = "character_prompts"   # 같은 파일의 켜고 끄기 - 칸의 캐릭터 프롬프트를 싣는가(기본 켬)
CHARACTER_WEIGHT = "0.8"              # 1장 덩어리의 가중치(사용자 지정 2026-11-05)
PLACES = {2: ("on the left", "on the right"), 3: ("on the left", "in the middle", "on the right")}
SUBJECTS = {"girl": "girl", "1girl": "girl", "boy": "boy", "1boy": "boy", "woman": "woman", "man": "man",
            "1woman": "woman", "1man": "man"}
STITCH_HEIGHT_RANGE = (512, 1536)
STITCH_MAX_ASPECT = 4          # 한 장의 너비 <= 높이 x 4


def _clean(key: str, value: Any):
    if key == "correction":
        return value if value in REF_CORRECTIONS else None
    if key not in REF_RANGES or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:        # NaN
        return None
    low, high = REF_RANGES[key]
    return round(min(high, max(low, number)), 2)


def _read_raw(context) -> dict:
    try:
        raw = json.loads(context._existing_save_path(SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        raw = {}
    return raw if isinstance(raw, dict) else {}


def load_settings(context) -> dict:
    """그래프로 가는 값(참조 세기 등)만 - 켜고 끄기(PROMPT_OPTION)는 load_prompt_option."""
    values = dict(REF_DEFAULTS)
    raw = _read_raw(context)
    for key in REF_DEFAULTS:
        cleaned = _clean(key, raw.get(key))
        if cleaned is not None:
            values[key] = cleaned
    return values


def load_prompt_option(context) -> bool:
    value = _read_raw(context).get(PROMPT_OPTION)
    return value if isinstance(value, bool) else True


def save_setting(context, key: str, value: Any) -> dict:
    """한 값만 바꾼다. 'reset' 은 그래프 값을 전부 제작자 기본값으로(싣기 켜고 끄기는 그대로)."""
    values = load_settings(context)
    prompts = load_prompt_option(context)
    if key == "reset":
        values = dict(REF_DEFAULTS)
    elif key == PROMPT_OPTION:
        if not isinstance(value, bool) and str(value).strip().lower() not in {"true", "false", "1", "0"}:
            raise ValueError(key)
        prompts = value if isinstance(value, bool) else str(value).strip().lower() in {"true", "1"}
    else:
        cleaned = _clean(key, value)
        if cleaned is None:
            raise ValueError(key)
        values[key] = cleaned
    path = context._save_path(SETTINGS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**values, PROMPT_OPTION: prompts}, indent=2), encoding="utf-8")
    return values


def enabled_hashes(context) -> list[str]:
    # Char Ref 서비스가 없는 context(시험용 · 최소 런타임)는 참조 없음
    factory = getattr(context, "_character_reference_service", None)
    if factory is None:
        return []
    service = factory()
    # 칸은 모드별 파일이다 - 이 요청은 ANIMA(COMFYUI) 것이다. 화면이 다른 모드면(NAI 화면에서 COMFYUI 요청) 그 모드의
    # 칸이 아니라 COMFYUI 파일의 칸을 읽는다(Codex 리뷰 2026-11-05).
    if service._settings_mode() == "COMFYUI":
        service._ensure_loaded()
        frames = getattr(context, "character_reference_frames", None) or []
    else:
        frames = service._load_persisted("COMFYUI")
    hashes = [str(f.get("file_hash") or "") for f in frames if f.get("is_enabled")]
    return [h for h in hashes if h][:MAX_REFS]


def _tags(prompt: str) -> list[str]:
    body = " ".join(str(prompt or "").split())
    return [part.strip() for part in body.split(",") if part.strip()]


def prompt_block(prompts: list[str]) -> str:
    """칸 차례대로의 캐릭터 프롬프트 -> 프롬프트 끝에 실을 글. 빈 칸은 건너뛴다(자리 이름은 칸 차례 그대로).
    1장 = (character at center: 태그:0.8). 2~3장 = the <주어> on the left is a <주어> with 태그, … - 주어는 태그 중
    처음 나온 girl/boy/woman/man(1girl 등 포함 · 그 태그는 문장에서 뺀다), 없으면 girl."""
    if len(prompts) == 1:
        tags = _tags(prompts[0])
        return f"(character at center: {', '.join(tags)}:{CHARACTER_WEIGHT})" if tags else ""
    places = PLACES.get(len(prompts))
    if not places:
        return ""
    parts = []
    for prompt, place in zip(prompts, places):
        tags = _tags(prompt)
        if not tags:
            continue
        at = next((i for i, tag in enumerate(tags) if tag.lower() in SUBJECTS), None)
        noun = SUBJECTS[tags[at].lower()] if at is not None else "girl"
        rest = [tag for i, tag in enumerate(tags) if i != at]
        parts.append(f"the {noun} {place} is a {noun}" + (f" with {', '.join(rest)}" if rest else ""))
    return ", ".join(parts)


def character_prompts(context, hashes: list[str]) -> list[str]:
    from core.ref_vibe_library import get_ref_vibe_library
    try:
        saved = get_ref_vibe_library(context).character_prompts(hashes)
    except Exception:            # 보관함을 못 읽었다 - 그림은 그대로 보내고 글만 싣지 않는다
        return ["" for _ in hashes]
    return [str((saved.get(file_hash) or {}).get("character_prompt") or "") for file_hash in hashes]


def with_block(text: str, block: str) -> str:
    """프롬프트 끝에 붙인다. 이미 그대로 들어 있으면(히스토리에서 불러온 글 등) 다시 붙이지 않는다."""
    text = str(text or "")
    if not block or block in text:
        return text
    head = text.rstrip().rstrip(",").rstrip()
    return f"{head}, {block}" if head else block


def strip_appended(text, captured) -> str:
    """지난번 snapshot 이 **붙인** 캐릭터 문장을 글 끝에서 걷는다(재시도 · Prompt Fixed 자동 생성이 지난 글을 다시 쓸 때).
    사용자가 직접 적어 둔 같은 문장(appended=False)은 건드리지 않는다. 옛 큐 항목(appended 없음)은 붙였을 때만
    prompt 를 적었다 - 붙인 것으로 본다."""
    text = str(text or "")
    if not isinstance(captured, dict):
        return text
    block = captured.get("prompt") or ""
    if not block or not captured.get("appended", True) or not text.endswith(block):
        return text
    return text[:-len(block)].rstrip().rstrip(",").rstrip()


def snapshot(context, params: dict) -> None:
    """큐에 넣는 순간의 참조 - 기다리는 동안 칸을 바꿔도 이 생성은 그대로(LoRA · 모델과 같은 규칙).
    캐릭터 에셋처럼 '레퍼런스를 붙이지 마라' 고 표시한 요청은 건너뛴다(NAI Char Ref 와 같은 표식).
    칸의 캐릭터 프롬프트도 이때 읽어 input 끝에 싣는다(기다리는 동안 글을 고쳐도 이 생성은 그대로)."""
    captured = params.pop("_anima_reference", None)
    # 같은 요청을 다시 잡으면(재시도 등) 지난번에 실은 글부터 걷는다 - 겹쳐 붙지 않게
    if isinstance(params.get("input"), str):
        params["input"] = strip_appended(params["input"], captured)
    if params.get("_skip_character_reference_late_binding"):
        return
    hashes = enabled_hashes(context)
    if not hashes:
        return
    captured = {"hashes": hashes, "settings": load_settings(context)}
    if load_prompt_option(context):
        block = prompt_block(character_prompts(context, hashes))
        if block:
            before = str(params.get("input") or "")
            params["input"] = with_block(before, block)
            # 블록은 늘 적는다 - 시퀀스의 다른 컷이 이것을 다시 싣는다(첫 컷에 이미 들어 있어도 · Codex 재리뷰 2026-11-06)
            if params["input"] != before:
                captured["prompt"] = block
    params["_anima_reference"] = captured


def _flatten(image):
    from PIL import Image
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return image.convert("RGB")


def stitch(images) -> bytes:
    """왼쪽부터 나란히 - 높이는 가장 낮은 그림에 맞춘다(512~1536 안으로). 투명한 자리는 흰색."""
    from PIL import Image
    flat = [_flatten(image) for image in images]
    low, high = STITCH_HEIGHT_RANGE
    height = max(low, min(high, min(image.height for image in flat)))
    # 한 장의 너비는 높이의 4배까지 - 극단적으로 납작한 그림(2048x1 등)을 높이 512 로 늘리면 너비가 백만 픽셀이 된다
    # (Codex 리뷰 2026-11-05). 넘는 것은 그 비율로 눌러 담는다(참조로 쓸 그림이 아니다).
    resized = [image if image.height == height and image.width <= height * STITCH_MAX_ASPECT else
               image.resize((max(1, min(height * STITCH_MAX_ASPECT, round(image.width * height / image.height))),
                             height), Image.LANCZOS)
               for image in flat]
    canvas = Image.new("RGB", (sum(image.width for image in resized), height), (255, 255, 255))
    x = 0
    for image in resized:
        canvas.paste(image, (x, 0))
        x += image.width
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def engine_image_name(png: bytes) -> str:
    return "naia_ref_" + hashlib.sha256(png).hexdigest()[:16] + ".png"


def build(context, captured: dict) -> tuple[bytes, str, dict]:
    """잡아 둔 해시 -> (붙인 PNG, 엔진 파일 이름, 그래프 설정). 그림이 사라졌으면 거절한다(몰래 빼고 그리지 않는다)."""
    from PIL import Image
    from .runtime import ManagedEngineError
    hashes = [str(h) for h in (captured.get("hashes") or [])][:MAX_REFS]
    images = []
    for file_hash in hashes:
        path = context._existing_save_path("character_reference", "images", f"{file_hash}.png")
        try:
            with Image.open(path) as opened:
                opened.load()
                images.append(opened.copy())
        except OSError:
            raise ManagedEngineError("REFERENCE_NOT_FOUND", "참조 그림을 찾지 못했습니다.", file_hash) from None
    if not images:
        raise ManagedEngineError("REFERENCE_NOT_FOUND", "참조 그림을 찾지 못했습니다.")
    png = stitch(images)
    name = engine_image_name(png)
    settings = dict(REF_DEFAULTS)
    for key, value in (captured.get("settings") or {}).items():
        cleaned = _clean(key, value) if key in REF_DEFAULTS else None
        if cleaned is not None:
            settings[key] = cleaned
    return png, name, {"image": name, **settings}


def upload(url: str, png: bytes, name: str, *, post=None) -> None:
    """엔진 input 폴더로(POST /upload/image). 같은 그림이면 같은 이름이라 덮어써도 같다."""
    import requests
    from .runtime import ManagedEngineError
    response = (post or requests.post)(url + "/upload/image", files={"image": (name, png, "image/png")},
                                       data={"type": "input", "overwrite": "true"}, timeout=30)
    try:
        response.raise_for_status()
        saved = response.json()
    except Exception as exc:
        raise ManagedEngineError("REFERENCE_UPLOAD_FAILED", "참조 그림을 엔진에 올리지 못했습니다.", str(exc)) from None
    if saved.get("name") != name or saved.get("subfolder"):
        raise ManagedEngineError("REFERENCE_UPLOAD_FAILED", "참조 그림을 엔진에 올리지 못했습니다.", json.dumps(saved)[:200])


def engine_has_nodes(url: str, *, get=None) -> bool:
    import requests
    from .ref_adapter import NODE_CLASSES, WEIGHT
    from core.headless_api_option_service import extract_combo_options
    try:
        for name in (*NODE_CLASSES, "LoraLoaderModelOnly"):
            response = (get or requests.get)(url + "/object_info/" + name, timeout=10)
            response.raise_for_status()
            info = response.json().get(name)
            if not info:
                return False
            required = info["input"]["required"]
            # 고정판(99c222e1)은 strength · ref_end · ref_megapixels 가 optional 이다 - 둘을 합쳐 본다
            # (11-05 원격 e2e: required 만 봐서 노드가 있는데도 '없음' 이라 했다)
            inputs = set(required) | set(info["input"].get("optional") or {})
            if name == "AnimaRefAdapter" and not set(REF_DEFAULTS) | {"model", "vae", "image", "lora_name"} <= inputs:
                return False
            # 가중치가 엔진에 실제로 보이는가 - 어댑터 노드의 목록은 없는 파일도 보이고(없으면 HF 에서 받는다) ComfyUI 의
            # loras 목록(LoraLoaderModelOnly)은 있는 파일만 보인다. 모델 경로 파일의 naia_ref_adapter 칸을 엔진이 읽었는지.
            if name == "LoraLoaderModelOnly" and WEIGHT["filename"] not in extract_combo_options(required.get("lora_name")):
                return False
        return True
    except Exception:
        return False
