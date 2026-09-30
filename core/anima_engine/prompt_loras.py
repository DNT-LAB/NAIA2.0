"""프롬프트의 LoRA 예약어 - `lora:예약어:강도` (사용자 지정 2026-09-30).

LoRA 창에서 LoRA 마다 예약어를 정해 두면, 프롬프트에 `<` 없이 `lora:watercolor:0.8` 처럼 적어 그 생성에서 LoRA 를
켠다(강도를 빼면 1). 와일드카드 · 랜덤 프롬프트가 다 풀린 뒤의 글(엔진에 보내기 직전)에서 찾는다.

- 토큰은 쉼표 · 줄 · 괄호로 나뉜 한 조각 **전체**다 - 조각이 `lora:` 로 시작할 때만 읽는다. 문장 속(`sign reading lora:wc`) ·
  앞이 글자(`flora:`) · `<lora:..>` 는 LoRA 표기가 아니다. 역슬래시로 이스케이프한 괄호는 경계가 아니다(이름의 글자).
- 창의 체인(적용 순서)에 이미 있으면 그 자리에서 강도만 이 값으로(꺼져 있어도 이 생성에서는 켠다), 없으면 체인 뒤에
  프롬프트 순서대로 붙는다. 같은 LoRA 가 프롬프트에 두 번이면 뒤의 것.
- 엔진에 가는 글에서는 토큰(과 이웃 쉼표)을 뺀다. 요청의 원문(`input`)은 그대로 둔다 - 기록 · 다시 쓰기 · 재시도가
  같은 LoRA 를 다시 켠다.
- 읽지 못한 표기 · 없는 예약어 · 범위 밖 강도(-2 ~ 2)는 조용히 넘기지 않고 이유를 들어 생성을 멈춘다.
"""
from __future__ import annotations

import re

KEYWORD_PATTERN = r"[\w.\-]+"
# 조각 = 쉼표 · 줄바꿈 · 이스케이프 안 된 괄호로 나뉜 글(`\(` `\)` 는 한 글자로 먹는다)
_PIECE = re.compile(r"(?:\\.|[^,\n()\[\]{}\\])+")
_TOKEN = re.compile(r"(?i)lora:(?P<kw>" + KEYWORD_PATTERN + r")(?:\s*:\s*(?P<w>[+-]?(?:\d+(?:\.\d*)?|\.\d+)))?")
STRENGTH_MIN, STRENGTH_MAX = -2.0, 2.0


class PromptLoraError(ValueError):
    def __init__(self, code: str, message: str, token: str):
        self.code, self.message, self.token = code, message, token
        super().__init__(message)


def extract_prompt_loras(text: str, keywords: dict[str, str]) -> tuple[str, list[tuple[str, float, str]]]:
    """keywords = {예약어.casefold(): LoRA 이름}. -> (토큰을 뺀 글, [(LoRA 이름, 강도, 토큰 원문)] 프롬프트 순서)."""
    text = str(text or "")
    found, spans = [], []
    for start, raw in _lora_pieces(text):
        token = _TOKEN.fullmatch(raw)
        if token is None:
            raise PromptLoraError("LORA_TOKEN_INVALID",
                                  f"LoRA 표기를 읽지 못했습니다: {raw} - lora:예약어:강도 (예: lora:watercolor:0.8)", raw)
        name = keywords.get(token.group("kw").casefold())
        if name is None:
            raise PromptLoraError("LORA_KEYWORD_NOT_FOUND",
                                  f"LoRA 예약어를 찾지 못했습니다: {raw} - LoRA 창에서 예약어를 정해 주세요.", raw)
        strength = float(token.group("w")) if token.group("w") is not None else 1.0
        if not STRENGTH_MIN <= strength <= STRENGTH_MAX:
            raise PromptLoraError("PARAM_OUT_OF_RANGE", f"LoRA 강도는 -2 ~ 2 사이로 적어 주세요: {raw}", raw)
        found.append((name, strength, raw))
        spans.append((start, start + len(raw)))
    return _remove_spans(text, spans), found


def _lora_pieces(text: str):
    """(시작 자리, 조각) - 앞뒤 공백을 뺀 조각이 lora: 로 시작하는 것만."""
    for match in _PIECE.finditer(text):
        piece = match.group(0)
        body = piece.strip()
        if body[:5].lower() == "lora:":
            yield match.start() + len(piece) - len(piece.lstrip()), body


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    # 뒤에서부터 - 앞 자리가 밀리지 않게. 뒤의 쉼표를 함께 빼고, 없으면(맨 끝 조각) 앞의 쉼표를.
    for start, end in reversed(spans):
        after = re.match(r"\s*,[ \t]*", text[end:])
        if after:
            end += after.end()
        else:
            before = re.search(r",[ \t]*$", text[:start])
            if before:
                start = before.start()
        text = text[:start] + text[end:]
    return text


def merge_prompt_loras(chain: list[dict], found: list[tuple[str, float, str]]) -> list[dict]:
    merged = [dict(item) for item in chain]
    for name, strength, _token in found:
        hit = next((item for item in merged if item.get("name") == name), None)
        if hit is None:
            merged.append({"name": name, "strength": strength, "enabled": True})
        else:
            hit.update(strength=strength, enabled=True)
    return merged
