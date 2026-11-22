"""Local prompt vocabulary. No dependency on the wildcard manager or its data."""
import re
from collections.abc import Iterator

from core.boost_v2 import _bare_tag


# A comma (or end of line) after '<' ends a face, not an angle block.
# This is the distinction split_tags_smart makes, without importing its
# wildcard/PromptContext stack (which requires pandas).
_FACE = re.compile(r"(?:[^\w\s]|[oOxXtT0uUvVQq])_+(?:[^\w\s]|[oOxXtT0uUvVQq])")
_END = r"\s*(?::-?[\d.]+|::)?[)\]}]*\s*(?:,|$)"
_ANGLE = re.compile(rf"<(?!{_END})|>(?![^,<>]?<{_END})|,")


def _tokens(line: str) -> Iterator[str]:
    depth = start = 0
    pieces = []
    for match in _ANGLE.finditer(line):
        pos = match.start()
        char = line[pos]
        if char == "<":
            if not depth:
                pieces.append(line[start:pos])
            depth += 1
        elif char == ">" and depth:
            depth -= 1
            if not depth:
                pieces.append(" ")
                start = pos + 1
        elif char == "," and not depth:
            yield "".join(pieces) + line[start:pos]
            pieces.clear()
            start = pos + 1
    yield "".join(pieces) + ("" if depth else line[start:])


def normalize_tag(text: str) -> str:
    text = text.strip().casefold()
    if not (_FACE.fullmatch(text) or re.fullmatch(r"(\S)_+\1", text)):
        text = text.replace("_", " ")
    return " ".join(text.split())


def _unweight(token: str) -> str:
    # Keep balanced qualifiers (e.g. "hero (series)") but discard unmatched
    # wrapper edges of comma-separated groups before stripping the weight.
    # _bare_tag normally folds underscores itself. Preserve them through
    # that step so normalize_tag can distinguish a face from a word tag.
    token = _bare_tag(token.replace("_", "\x00"))
    excess = {}
    for left, right in ("()", "[]", "{}"):
        excess[left] = token.count(left) - token.count(right)
        excess[right] = -excess[left]
    start, end = 0, len(token)
    while start < end and token[start] in "([{" and excess[token[start]] > 0:
        excess[token[start]] -= 1
        start += 1
    while end > start and token[end-1] in ")]}" and excess[token[end-1]] > 0:
        excess[token[end-1]] -= 1
        end -= 1
    return _bare_tag(token[start:end]).replace("\x00", "_")


def prompt_tags(prompt: str, characters: list[str]) -> list[str]:
    tags = set()
    for field in (prompt, *characters):
        field = ",".join(line for line in field.splitlines() if not line.lstrip().startswith("#"))
        for token in _tokens(field):
            tag = normalize_tag(_unweight(token.strip()))
            if tag and not tag.startswith("#") and len(tag.split()) <= 6:
                tags.add(tag)
    return sorted(tags)
