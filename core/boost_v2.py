"""Boost v2 — 랜덤 프롬프트 태그를 로컬 LLM(llama.cpp) 단일 호출로 하이브리드 텍스트로 강화한다.

기존 Ollama Scene Boost(``core/scene_boost.py``)의 증거 버킷·후필터 대신, 검증된 템플릿 하나로
5개 섹션을 받는다. 이 모듈은 순수 로직(설정 정규화·지시문 조립·출력 파싱·삽입 문자열 조립)과
설정 파일 입출력만 가진다 — 프로세스/HTTP 는 ``core/llama_runtime.py``, 프롬프트에 끼우는 일은
``app/backend/server/generation_commands.apply_boost_v2`` 가 맡는다.

사양(2026-09-23): Effort 없음 · 섹션 단위 On/Off · 섹션별 User preferences · 와일드카드/캐릭터
프롬프트 미지원(랜덤 프롬프트만) · 결과는 main 뒤에 붙인다(대체 아님).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# (키, 출력 라벨, 스킴 설명, 끈 섹션일 때 "쓰지 마라" 에 들어갈 대상)
SECTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "subject",
        "Subject & Action",
        "Descriptive tags and natural language covering the main subject, attire, expressions, and primary actions",
        "the subject's appearance, attire, expression or actions",
    ),
    (
        "composition",
        "Composition & Angle",
        "Camera framing, perspective, field of view, and shot type",
        "camera framing, angle or shot type",
    ),
    (
        "detail",
        "Detail & Object",
        "Environmental background details, secondary props, textures, and ambient elements",
        "background details, props or textures",
    ),
    (
        "lighting",
        "Lighting",
        "Lighting sources, color temperature, shadow dynamics, and volumetric effects",
        "lighting",
    ),
    (
        "quality",
        "Quality",
        "Mood enhancement, cinematic atmosphere, rendering subtleties, and atmospheric depth, "
        "strictly avoiding tags like 'anime' or 'realistic'",
        "mood or rendering quality",
    ),
)
SECTION_KEYS: tuple[str, ...] = tuple(s[0] for s in SECTIONS)
_LABEL_TO_KEY = {s[1].lower(): s[0] for s in SECTIONS}
_KEY_TO_LABEL = {s[0]: s[1] for s in SECTIONS}

BACKENDS = ("ollama", "llamacpp")
PREFERENCE_MAX_CHARS = 400
SETTINGS_FILE = "boost_v2_user.json"

BOOST_V2_DEFAULTS: dict[str, Any] = {
    # 켜기/끄기 토글은 기존 세션 토글(context.ollama_auto_boost)을 그대로 쓰고, 여기선 어느
    # 백엔드로 돌릴지만 고른다. 기본은 기존 Ollama — 사용자가 고를 때까지 동작이 안 바뀐다.
    "backend": "ollama",
    "sections": {key: True for key in SECTION_KEYS},
    "preferences": {key: "" for key in SECTION_KEYS},
    # 비우면 기본 위치(엔진=앱 동봉, 모델=user-data/models/llm)를 쓴다.
    "engine_path": "",
    "model_path": "",
}


def normalize_boost_v2_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}
    backend = str(source.get("backend") or BOOST_V2_DEFAULTS["backend"]).strip().lower()
    if backend not in BACKENDS:
        backend = BOOST_V2_DEFAULTS["backend"]
    raw_sections = source.get("sections") if isinstance(source.get("sections"), dict) else {}
    sections = {key: bool(raw_sections.get(key, True)) for key in SECTION_KEYS}
    raw_prefs = source.get("preferences") if isinstance(source.get("preferences"), dict) else {}
    preferences = {}
    for key in SECTION_KEYS:
        text = " ".join(str(raw_prefs.get(key) or "").split())
        preferences[key] = text[:PREFERENCE_MAX_CHARS]
    return {
        "backend": backend,
        "sections": sections,
        "preferences": preferences,
        "engine_path": str(source.get("engine_path") or "").strip(),
        "model_path": str(source.get("model_path") or "").strip(),
    }


def enabled_sections(settings: dict[str, Any]) -> list[str]:
    sections = (settings or {}).get("sections") or {}
    return [key for key in SECTION_KEYS if sections.get(key, True)]


def build_instruction(tags: str, settings: dict[str, Any]) -> str:
    """사용자 템플릿(llama_test 에서 검증)을 켠 섹션만으로 조립한다.

    끈 섹션은 스킴에서 빼는 것만으론 부족하다 — E2B 는 빠진 섹션의 내용을 남은 섹션으로
    옮겨 쓴다(실측: Subject 를 끄자 인물 묘사가 Detail 로 갔다). 그래서 대상을 명시해 금지한다.
    """
    enabled = enabled_sections(settings)
    if not enabled:
        return ""
    by_key = {s[0]: s for s in SECTIONS}
    scheme = "\n".join(f", ({by_key[k][1]}): [{by_key[k][2]}]" for k in enabled)
    lines = [
        "You are an expert prompt engineer specializing in image generation models.",
        "",
        "Convert the provided raw tags into a structured, hybrid image prompt combining comma-separated tags "
        "and descriptive natural language phrases.",
        "",
        "Strict Requirements:",
        "",
        "Format: Output ONLY raw plain text. Absolutely DO NOT use any Markdown syntax (no bolding, no italics, "
        "no backticks, no markdown code blocks, no headers).",
        "",
    ]
    if "quality" in enabled:
        lines += [
            'Quality Category Rule: In the (Quality) section, do NOT use generic medium tags like "anime", '
            '"photorealistic", "realistic", or "masterpiece". Instead, generate descriptive phrases and nuanced '
            "tags that elevate mood, micro-details, texture, and aesthetic atmosphere.",
            "",
        ]
    lines += [
        "Structure: Follow the exact output template provided below, including the leading comma and section "
        f"labels. Output exactly these {len(enabled)} section(s) in this order and nothing else.",
    ]
    omitted = [by_key[k][3] for k in SECTION_KEYS if k not in enabled]
    if omitted:
        lines.append("Do NOT describe " + "; ".join(omitted) + " anywhere in the output.")
    lines += ["", f"Input tags:  {tags}", "", "Expected output scheme:", "", scheme]
    prefs = settings.get("preferences") or {}
    pref_lines = [f"({by_key[k][1]}): {prefs[k]}" for k in enabled if str(prefs.get(k) or "").strip()]
    if pref_lines:
        lines += [
            "",
            "User preferences (in appropriate situations; use a preference only when it fits the input tags, "
            "otherwise leave it out):",
            *pref_lines,
        ]
    return "\n".join(lines) + "\n"


_SECTION_LINE = re.compile(r"^\s*,?\s*\(\s*([^()]+?)\s*\)\s*:\s*(.*)$")
_MARKDOWN = re.compile(r"\*\*|__|`")


def parse_output(text: str, settings: dict[str, Any]) -> dict[str, str]:
    """모델 출력에서 켠 섹션의 본문만 뽑는다. 모르는 라벨·끈 섹션·빈 본문은 버린다.

    라벨 없이 이어지는 줄은 직전 섹션에 붙인다(모델이 한 섹션을 여러 줄로 쓸 때).
    """
    enabled = set(enabled_sections(settings))
    out: dict[str, str] = {}
    current: str | None = None
    for raw_line in str(text or "").splitlines():
        line = _MARKDOWN.sub("", raw_line).strip()
        if not line:
            continue
        match = _SECTION_LINE.match(line)
        if match:
            key = _LABEL_TO_KEY.get(match.group(1).strip().lower())
            current = key if key in enabled and key not in out else None
            if current:
                out[current] = match.group(2).strip()
            continue
        if current:
            out[current] = (out[current] + " " + line.lstrip(", ")).strip()
    cleaned: dict[str, str] = {}
    for key in SECTION_KEYS:
        # 끝 마침표는 뗀다 — 섹션을 ", " 로 이으면 "solo., (Composition" 이 된다(실측).
        body = " ".join(out.get(key, "").split()).strip(" ,").rstrip(" .,")
        if body:
            cleaned[key] = body
    return cleaned


def compose_addition(sections: dict[str, str], *, is_nai: bool) -> str:
    """파싱한 섹션을 한 줄 삽입 문자열로. 라벨은 사용자 템플릿대로 유지한다.

    최종 전송 전 정리(api_service)가 개행을 지우므로 처음부터 ", " 로 잇는다. WEBUI/ComfyUI 는
    ``()`` 가 가중치 문법이라 라벨과 본문의 리터럴 괄호를 이스케이프한다 — 파이프라인 밖에서
    끼우므로 ``_escape_main_tags_parens`` 를 거치지 않는다(기존 Auto Boost 와 같은 이유).
    """
    parts = []
    for key in SECTION_KEYS:
        body = str(sections.get(key) or "").strip()
        if not body:
            continue
        parts.append(f"({_KEY_TO_LABEL[key]}): {body}")
    if not parts:
        return ""
    if not is_nai:
        from core.prompt_processor import _escape_parens_in_content

        parts = [_escape_parens_in_content(p) for p in parts]
    return ", ".join(parts)


# ── 설정 파일(전역·모드 무관 디스크 SSOT) ────────────────────────────────────


def load_boost_v2_settings(*, save_root: str | Path | None = None) -> dict[str, Any]:
    from core.prompt_engineering_settings import _existing_save_file

    path = _existing_save_file(SETTINGS_FILE, save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return normalize_boost_v2_settings(None)
    return normalize_boost_v2_settings(data if isinstance(data, dict) else {})


def save_boost_v2_settings(settings: dict[str, Any], *, save_root: str | Path | None = None) -> dict[str, Any]:
    from core.prompt_engineering_settings import _coerce_save_root

    normalized = normalize_boost_v2_settings(settings)
    path = _coerce_save_root(save_root) / SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized
