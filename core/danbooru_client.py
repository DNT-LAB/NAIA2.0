"""
Small Danbooru API adapter used by the Remote Web shell.

The PyQt desktop tab uses QWebEngine and extracts tags from the loaded page.
The web shell cannot embed Danbooru reliably, so it mirrors the same tag
categories through the public post JSON endpoint.
"""
from __future__ import annotations

import re
import time
from typing import Callable, Iterable

import requests


DANBOORU_BASE_URL = "https://danbooru.donmai.us"

# Cloudflare in front of donmai resets plain non-browser clients (the "NAIA2 Remote
# Shell" UA) — especially under the embed's per-navigation auto-extract. A browser UA +
# a reused session + a short retry on connection resets makes the server-side JSON
# lookup behave like the embedded WebContentsView that already loads the page fine.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CONNECTION_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)
_session: "requests.Session | None" = None


def _danbooru_session() -> "requests.Session":
    global _session
    if _session is None:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{DANBOORU_BASE_URL}/",
        })
        _session = sess
    return _session


def _get_with_retry(url: str, *, timeout: float, retries: int):
    attempts = max(1, int(retries))
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return _danbooru_session().get(url, timeout=timeout)
        except _CONNECTION_ERRORS as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                time.sleep(0.6 * (attempt + 1))
    assert last_exc is not None
    raise last_exc
POST_ID_RE = re.compile(
    r"(?:https?://)?(?:www\.)?danbooru\.donmai\.us/posts/(\d+)",
    re.IGNORECASE,
)


def extract_danbooru_post_id(query: str) -> int:
    text = str(query or "").strip()
    if not text:
        raise ValueError("Danbooru post URL or ID is required")

    match = POST_ID_RE.search(text)
    if match:
        return int(match.group(1))

    if text.isdigit():
        return int(text)

    loose_match = re.search(r"\bposts?[/#: ]+(\d+)\b", text, re.IGNORECASE)
    if loose_match:
        return int(loose_match.group(1))

    raise ValueError("Could not read a Danbooru post ID")


def _split_tag_string(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return [
        tag.replace("_", " ").strip()
        for tag in value.split()
        if tag.strip()
    ]


def _normalize_characteristic_tags(tags: Iterable[str] | None) -> set[str]:
    return {
        str(tag or "").replace("_", " ").strip()
        for tag in (tags or [])
        if str(tag or "").strip()
    }


def normalize_danbooru_post_payload(
    payload: dict,
    *,
    query: str = "",
    characteristic_tags: Iterable[str] | None = None,
) -> dict:
    post_id = int(payload.get("id") or extract_danbooru_post_id(query))
    tags = {
        "artist": _split_tag_string(payload.get("tag_string_artist")),
        "copyright": _split_tag_string(payload.get("tag_string_copyright")),
        "character": _split_tag_string(payload.get("tag_string_character")),
        "general": _split_tag_string(payload.get("tag_string_general")),
        "meta": _split_tag_string(payload.get("tag_string_meta")),
    }

    characteristic_set = _normalize_characteristic_tags(characteristic_tags)
    if characteristic_set:
        moved = [tag for tag in tags["general"] if tag in characteristic_set]
        if moved:
            tags["general"] = [tag for tag in tags["general"] if tag not in characteristic_set]
            for tag in moved:
                if tag not in tags["character"]:
                    tags["character"].append(tag)

    image_url = (
        payload.get("large_file_url")
        or payload.get("file_url")
        or payload.get("preview_file_url")
        or ""
    )
    preview_url = payload.get("preview_file_url") or image_url
    post_url = f"{DANBOORU_BASE_URL}/posts/{post_id}"

    return {
        "post_id": post_id,
        "post_url": post_url,
        "image_url": image_url,
        "preview_url": preview_url,
        "rating": payload.get("rating") or "",
        "score": payload.get("score"),
        "source": payload.get("source") or "",
        "tags": tags,
        "tag_counts": {key: len(value) for key, value in tags.items()},
    }


def fetch_danbooru_post(
    query: str,
    *,
    timeout: float = 12.0,
    http_get: Callable[..., object] | None = None,
    characteristic_tags: Iterable[str] | None = None,
    retries: int = 3,
) -> dict:
    post_id = extract_danbooru_post_id(query)
    url = f"{DANBOORU_BASE_URL}/posts/{post_id}.json"
    if http_get is not None:
        response = http_get(url, timeout=timeout, headers={"User-Agent": _BROWSER_UA})
    else:
        response = _get_with_retry(url, timeout=timeout, retries=retries)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Danbooru returned an invalid post payload")
    return normalize_danbooru_post_payload(
        payload,
        query=str(post_id),
        characteristic_tags=characteristic_tags,
    )
