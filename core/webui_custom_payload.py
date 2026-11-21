"""Parse the always-on part of a WebUI generation request without repairing its contents."""

import json
import re


def _invalid_constant(value):
    raise ValueError(f"JSON 숫자가 아닙니다: {value}")


_QUOTED = re.compile(r'''"(?:\\.|[^"\\])*"|“((?:\\.|[^”\\])*)”|‘(.*?)’(?=\s*[:,}\]]|\s*$)''', re.S)


def _straight_quotes(match):
    if match[0].startswith('"'):
        return match[0]
    content = match[1] if match[1] is not None else match[2]
    return '"' + content.replace("’", "'").replace("‘", "'") + '"'


def normalize_custom_payload(text: str) -> dict:
    scripts = {}
    issues = []

    def issue(level, message, script=None):
        issues.append({"level": level, "script": script, "message": message})

    def result():
        ok = not any(item["level"] == "error" for item in issues)
        return {"ok": ok, "scripts": scripts, "canonical": json.dumps(scripts, ensure_ascii=False, indent=2),
                "issues": issues}

    text = text.strip() if isinstance(text, str) else ""
    if not text:
        # 빈 칸 = payload 를 비운 것이다. 오류가 아니다(비우려고 Apply 하는 길 · 켜 둔 채 비어 있어도 생성은 그대로).
        return result()
    if re.search(r"\{\s*(?:…|\.\.\.)\s*\}", text):
        issue("error", "생략 기호가 들어 있어 설정이 잘렸습니다. WebUI 에서 다시 복사하세요.")
        return result()
    # Preserve ordinary JSON strings, including apostrophes and quoted prose.
    try:
        try:
            block = json.loads(text, parse_constant=_invalid_constant)
        except json.JSONDecodeError:
            clean = _QUOTED.sub(_straight_quotes, text)
            if clean.startswith('"'):
                clean = "{" + clean + "}"
            block = json.loads(clean, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as exc:
        issue("error", f"JSON 형식 오류: {exc}")
        return result()

    if isinstance(block, dict) and "alwayson_scripts" in block:
        block = block["alwayson_scripts"]
    if not isinstance(block, dict):
        issue("error", "스크립트 목록은 JSON 객체여야 합니다.")
        return result()
    for name, script in block.items():
        if not isinstance(script, dict):
            issue("error", "스크립트 설정은 JSON 객체여야 합니다.", name)
            continue
        if "args" in script and not isinstance(script["args"], list):
            args = script["args"]
            if not isinstance(args, dict) or not all(str(i) in args for i in range(len(args))):
                issue("error", "args는 배열이거나 0부터 연속된 정수 키를 가진 객체여야 합니다.", name)
                continue
            script["args"] = [args[str(i)] for i in range(len(args))]
            issue("warn", "숫자 키로 된 args를 순서대로 배열로 변환했습니다.", name)
        scripts[name] = script
    return result()


def disabled_script_names(value):
    """Remote params may contain a list or its WebSocket JSON representation."""
    if isinstance(value, str):
        value = json.loads(value or "[]")
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise ValueError("꺼진 스크립트 목록은 이름 배열이어야 합니다.")
    return value
