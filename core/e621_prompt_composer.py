"""Request-local E621 prompt composition; never rewrites another module's prompt."""
from __future__ import annotations

import math
import re
from decimal import Decimal
from uuid import uuid4

from core.tag_knowledge import normalize_display_tag
from core.wildcard_processor import split_tags_smart

WEIGHT_LIMITS = {mode: {"min": 0.0, "max": 2.0, "default": 1.0}
                 for mode in ("NAI", "WEBUI", "COMFYUI")}
# The shared display helper has no symbol exception. Keep this exception local.
_FACE = re.compile(r"^[oOxXTtUuVv0.^;:|><=\-]_[oOxXTtUuVv0.^;:|><=\-]$")
# Compact corpus spellings; do not broaden this to arbitrary underscore words.
_CORPUS_SYMBOLS = frozenset({"._.", "<_<", "=_=", ">_<", ">_>", ">_a", ">_o", "^_^",
    "e_e", "f_f", "l_v", "n_h", "n_n", "o_0", "o_<", "o_^", "o_o", "u_u", "ಠ_ಠ"})
_NAI_WEIGHT = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))::(.*?)\s*::", re.S)
_SD_WEIGHT = re.compile(r"^\((.*):([+-]?(?:\d+(?:\.\d*)?|\.\d+))\)$", re.S)


def display_tag(exact_tag: str) -> str:
    return exact_tag if exact_tag in _CORPUS_SYMBOLS or _FACE.fullmatch(exact_tag) else normalize_display_tag(exact_tag)


def validate_weight(value, api_mode: str = "NAI") -> float:
    if api_mode not in WEIGHT_LIMITS:
        raise ValueError(f"Unsupported E621 API mode: {api_mode}")
    if isinstance(value, bool):
        raise ValueError("weight must be a finite number between 0 and 2")
    try:
        weight = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("weight must be a finite number between 0 and 2") from exc
    if not math.isfinite(weight) or not 0.0 <= weight <= 2.0:
        raise ValueError("weight must be a finite number between 0 and 2")
    return weight


def serialize_tag(exact_tag: str, weight, api_mode: str) -> str:
    weight = validate_weight(weight, api_mode)
    tag = display_tag(exact_tag)
    if api_mode != "NAI":
        tag = tag.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        tag = tag.replace("[", "\\[").replace("]", "\\]")
    if weight == 1.0:
        return tag
    number = format(Decimal(str(weight)).normalize(), "f")
    return f"{number}::{tag} ::" if api_mode == "NAI" else f"({tag}:{number})"


def clean_prompt(text: str) -> str:
    """Full-line comments and physical line breaks are template separators."""
    lines = [line.strip() for line in str(text).splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    # Pipeline annotations are comma-delimited # tokens, too.
    return ", ".join(tag.strip() for tag in split_tags_smart(", ".join(lines))
                     if tag.strip() and not tag.lstrip().startswith("#"))


def prepare_template(template: str, selected_tags: list[dict], api_mode: str, *, expand=None) -> tuple[list[str], dict[str, str]]:
    """Protect explicit selection/weights through main hooks and final formatting.

    The pipeline still processes the template, prefix, suffix and wildcards. These
    explicit literals cannot become another tag, disappear via preprocessing, or
    acquire an automatic second weight. Restoration happens after that pipeline.
    """
    protected: dict[str, str] = {}
    nonce = uuid4().hex

    def protect(rendered):
        # ⚠️ 고정 폭 + 끝 표식. 예전 'x1' 은 'x10' · 'x11' 의 앞부분이라, 보호한 태그가 10개를 넘으면
        #    restore_literals 의 count 가 겹쳐 세어 '중복' 으로 막았다(V5 표준 템플릿 17개에서 실측 2026-10-03).
        token = f"e621literal{nonce}x{len(protected):05d}z"
        protected[token] = rendered
        return token

    def template_tokens(tag, weight=1.0):
        dynamic = "__" in tag or tag.startswith(("<", "$", "preset:"))
        if dynamic and expand is not None:
            return [protect(serialize_tag(value, weight, api_mode)) for value in expand(tag)]
        if dynamic:
            # Pipeline-off retains wildcard spelling, including double underscores.
            weight = validate_weight(weight, api_mode)
            number = format(Decimal(str(weight)).normalize(), "f")
            rendered = tag if weight == 1 else (f"{number}::{tag} ::" if api_mode == "NAI" else f"({tag}:{number})")
            return [protect(rendered)]
        return [protect(serialize_tag(tag, weight, api_mode))]

    selection = ", ".join(protect(serialize_tag(row["exact_tag"], row["weight"], api_mode))
                          for row in selected_tags)
    text = clean_prompt(template)
    if text.count("{{selected_tags}}") > 1:
        raise ValueError("Use {{selected_tags}} at most once")
    if "{{selected_tags}}" in text and not any(tag.strip() == "{{selected_tags}}" for tag in split_tags_smart(text)):
        raise ValueError("{{selected_tags}} must be a standalone tag without a weight wrapper")
    text = text.replace("{{selected_tags}}", selection) if "{{selected_tags}}" in text else ", ".join(
        piece for piece in (text, selection) if piece)
    # Legacy numeric NAI groups in the testbench are converted locally, including
    # groups with commas. They are not sent as NAI syntax to SD providers.
    text = _NAI_WEIGHT.sub(lambda m: ", ".join(
        token for tag in split_tags_smart(m[2]) if tag.strip()
        for token in template_tokens(tag.strip(), m[1])), text)
    if "::" in text:
        raise ValueError("Unbalanced or unsupported numeric weight in E621 template")
    tags = []
    for tag in split_tags_smart(text):
        tag = tag.strip()
        if tag in protected:
            tags.append(tag)
        elif match := _SD_WEIGHT.fullmatch(tag):
            tags.extend(template_tokens(match[1], match[2]))
        elif tag.startswith(("<lora:", "<hypernet:", "<lyco:", "lora:")):
            tags.append(tag)
        elif tag:
            tags.extend(template_tokens(tag))
    return tags, protected


def restore_literals(prompt: str, protected: dict[str, str]) -> str:
    for token, rendered in protected.items():
        if prompt.count(token) != 1:
            raise ValueError("Main pipeline removed or duplicated an E621 explicit tag")
        prompt = prompt.replace(token, rendered)
    return clean_prompt(prompt)
