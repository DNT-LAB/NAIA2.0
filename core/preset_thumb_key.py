"""Stable image keys shared by the preset thumbnail tools and runtime."""

from collections.abc import Iterable
from hashlib import sha1


HEADS = {"girl_boy": "1girl, 1boy", "girl_girl": "2girls", "boy_boy": "2boys"}


def head_for(kind: str, pool: str) -> str:
    if kind == "scene":
        return "no humans"
    if kind == "link":
        return HEADS[pool]
    return "1girl"


def preset_thumb_key(kind: str, head: str, tags: Iterable[str]) -> str:
    identity = f"{kind}|{head}|{','.join(sorted(tags))}"
    return sha1(identity.encode("utf-8")).hexdigest()[:16]
