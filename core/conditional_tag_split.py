from __future__ import annotations


def split_tags_bracket_aware(text: str) -> list[str]:
    r"""Split conditional-prompt tag text on top-level commas only.

    Commas inside ``<...>``, ``(...)``, and ``[...]`` are preserved. Brackets are
    tracked with the same forgiving depth-counter style as ``split_tags_smart``:
    opener characters increase depth, closer characters decrease it without
    requiring type-matched pairs. Escaped Danbooru parens like ``\(`` and
    ``\)`` are still counted as literal parens; balanced escaped pairs remain
    safe, while malformed or unbalanced text is handled best-effort.
    """
    if not text:
        return []

    result: list[str] = []
    current: list[str] = []
    depth = 0

    for char in str(text):
        if char in "<([":
            depth += 1
            current.append(char)
        elif char in ">)]":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            tag = "".join(current).strip()
            if tag:
                result.append(tag)
            current = []
        else:
            current.append(char)

    tag = "".join(current).strip()
    if tag:
        result.append(tag)
    return result