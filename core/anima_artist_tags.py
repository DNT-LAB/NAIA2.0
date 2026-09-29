"""ANIMA 모드 - 작가 태그는 '@이름' 으로 보낸다(사용자 지정 2026-09-29).

ANIMA 는 작가를 '@이름' 으로 알아본다. @ 없이 들어온 작가 태그(손으로 친 프리픽스 · 와일드카드가 뱉은 이름 · 붙여 넣은
프롬프트)는 랜덤 프롬프트 단계(prompt_processor._step_final_format)와 생성 단계(api_service._call_comfyui_api)에서
조용히 '@' 를 붙인다. 가중치로 감싼 것도 같다:
    작가 -> @작가 · (작가:1.2) -> (@작가:1.2) · (a, 작가:1.15) -> (a, @작가:1.15) · (작가, a:0.8) -> (@작가, a:0.8)
    1.2::작가:: -> 1.2::@작가:: · 2::작가, 작가 :: -> 2::@작가, @작가 :: · {작가} -> {@작가} · [작가] -> [@작가]
작가인지는 태그 사전의 분류로 가린다(`_cat == 'artist'` - 툴팁 · 강조가 'artist' 로 보이는 것과 같다). 주석 줄(#) ·
아직 안 풀린 와일드카드(__x__ · <x> · $x) · 이미 @ 가 붙은 것은 건드리지 않는다. 나머지 글자는 한 자도 바꾸지 않는다.
"""
from __future__ import annotations

import re
from functools import lru_cache

# 조각 앞의 공백 · 여는 괄호 · NAI 가중치(1.2::) / 뒤의 공백 · :가중치 · 닫는 괄호(\) 는 이름의 일부) · NAI 닫기(::)
_LEAD = re.compile(r"\s+|[(\[{]|[-+]?(?:\d+(?:\.\d+)?|\.\d+)::")
_TAIL = re.compile(r"(?:\s+|(?<!\\)[)\]}]|::|:\s*[-+]?(?:\d+(?:\.\d+)?|\.\d+))$")


def _key(text: str) -> str:
    """사전 열쇠 모양 - 괄호 이스케이프를 풀고 '_' 는 공백, 소문자."""
    return " ".join(text.replace("\\(", "(").replace("\\)", ")").replace("_", " ").split()).lower()


def _split(segment: str) -> tuple[str, str, str]:
    """쉼표 사이 조각 -> (앞, 태그, 뒤)."""
    start, end = 0, len(segment)
    while start < end:
        match = _LEAD.match(segment, start, end)
        if not match or match.end() == start:
            break
        start = match.end()
    while end > start:
        match = _TAIL.search(segment[start:end])
        if not match or match.start() == end - start:
            break
        end = start + match.start()
    return segment[:start], segment[start:end], segment[end:]


def add_anima_artist_at(prompt, artists) -> str:
    """작가 태그 앞에 '@' 를 붙인 프롬프트 - 작가가 아니면 글자 그대로."""
    text = str(prompt or "")
    if not text or not artists:
        return text
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        pieces = line.split(",")
        changed = False
        for number, piece in enumerate(pieces):
            lead, tag, tail = _split(piece)
            if (not tag or tag.startswith("@") or "__" in tag or tag[0] in "<$#"
                    or _key(tag) not in artists):
                continue
            pieces[number] = f"{lead}@{tag}{tail}"
            changed = True
        if changed:
            lines[index] = ",".join(pieces)
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _dictionary_artists() -> frozenset:
    """태그 사전을 아직 안 읽었을 때 - 같은 원천(저장소 루트 artist_dictionary.artist_dict)을 직접 읽는다."""
    try:
        import artist_dictionary
        from core.kr_tag_loader import _normalize_tag_text
        return frozenset(_normalize_tag_text(str(name)).lower() for name in artist_dictionary.artist_dict)
    except Exception:          # 사전이 없는 판 - 붙이지 않는다
        return frozenset()


def artist_names(context=None) -> frozenset:
    """작가로 분류된 태그 이름(사전 열쇠 모양). 자동완성이 읽어 둔 태그 사전(context.kr_tags_raw)이 있으면 그것으로 -
    툴팁 · 강조와 같은 분류다. 사전이 바뀌면(다시 읽기 · 데이터 가져오기) 다시 모은다."""
    raw = getattr(context, "kr_tags_raw", None) if context is not None else None
    if not isinstance(raw, dict) or not raw:
        return _dictionary_artists()
    cached = getattr(context, "_anima_artist_names", None)
    if cached and cached[0] is raw:
        return cached[1]
    names = frozenset(key for key, info in raw.items() if isinstance(info, dict) and info.get("_cat") == "artist")
    try:
        context._anima_artist_names = (raw, names)
    except Exception:          # 속성을 못 다는 대상 - 매번 모은다
        pass
    return names


def apply_to_request(params, context=None):
    """생성 요청의 프롬프트(params['input'])에 '@' - **시도마다 그 시도의 모드로** 다시 만든다.

    ⚠️ 외부 ComfyUI 는 두 번 실패하면 EPS <-> ANIMA 를 바꿔 같은 요청으로 다시 부른다(api_service 자동 스왑). 예전엔
       붙인 '@' 가 요청에 그대로 남아 EPS 요청 · 그 결과의 히스토리까지 '@작가' 로 갔다(Codex 09-30). 그래서 붙이기 전
       원문과 보낸 글을 요청에 적어 두고, 다음 시도가 그 보낸 글을 그대로 들고 오면 원문에서 다시 만든다. 보낸 글과
       다르면(요청을 다른 프롬프트로 다시 쓴 경우) 들어온 글이 원문이다.
    """
    original = params.get("input")
    if original is not None and original == params.get("_anima_at_sent"):
        original = params.get("_anima_at_original", original)
    sent = add_anima_artist_at(original, artist_names(context)) if is_anima_request(params) else original
    params["input"] = sent
    if sent != original:
        params["_anima_at_original"], params["_anima_at_sent"] = original, sent
    else:
        params.pop("_anima_at_original", None)
        params.pop("_anima_at_sent", None)
    return params


def is_anima_request(params) -> bool:
    """생성 요청이 ANIMA 로 가는가 - 관리형 엔진이거나, ComfyUI 의 ANIMA 샘플링(unet 그래프)."""
    from core.anima_engine import integration
    if integration.is_managed_credential(params.get("credential")):
        return True
    sampling = str(params.get("sampling_mode") or params.get("comfyui_sampling_mode") or "").strip().lower()
    workflow = str(params.get("workflow_type") or "").strip().lower()
    return sampling == "anima" or (not sampling and workflow == "unet")
