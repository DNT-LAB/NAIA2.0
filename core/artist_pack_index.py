"""작가 썸네일 팩(JSON · 1~2.7GB)에서 **작가 한 명의 자리만** 읽는다.

팩은 `{"작가": ["base64 JPEG", ...], ...}` 한 덩어리다. 통째로 읽으면 1.37GB 팩 하나에 3.7초 · 최대 3.9GB 가
든다(2026-11-11 실측). 작가 몇 명의 그림만 필요한 자리(아티스트 태그 관리 창)에서는 그럴 까닭이 없다 -
작가마다 값이 놓인 **바이트 자리**(시작 · 끝)를 한 번 훑어 적어 두고, 그 뒤로는 그 자리만 읽는다
(색인 만들기 1.5초 · 13명 읽기 10~20ms · 21MB).

⚠️ 줄 번호가 아니라 바이트 자리다. 팩은 줄바꿈 없는 한 줄짜리도 있고(지금 팩 전부), 줄 번호로는 건너뛸 수 없다.
⚠️ 색인은 **그 파일**의 것이다(크기 · 수정 시각이 지문). 팩이 갈리면 자리가 전부 달라지므로 지문이 다르면
   버리고 다시 훑는다 - 낡은 팩도 제 색인으로는 바르게 읽힌다.
훑는 방식은 `character_preview_index` 와 같다: base64 본문에는 따옴표가 없어 따옴표에서 따옴표로 건너뛴다.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from core.character_preview_index import _ByteWindow

SCHEMA = 1
_SPACE = b" \t\r\n"


def scan_pack(path) -> dict[str, list[int]]:
    """맨 위 객체의 열쇠 -> [값의 시작, 끝). 본문은 메모리에 올리지 않는다."""
    path = Path(path)
    offsets: dict[str, list[int]] = {}
    with path.open("rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        if not size:
            return offsets
        body = _ByteWindow(handle, size)

        def space(pos):
            while pos < size and body[pos] in _SPACE:
                pos += 1
            return pos

        def string_end(pos):
            end = pos
            while True:
                end = body.find(b'"', end + 1)
                if end < 0:
                    raise ValueError("Unterminated string in artist pack")
                slash = end - 1
                while slash > pos and body[slash] == 92:
                    slash -= 1
                if (end - 1 - slash) % 2 == 0:
                    return end + 1

        def skip(pos):
            # ⚠️ 한 걸음도 못 나가는 입력은 여기서 끊는다. `{"x":[}` 처럼 닫는 짝이 어긋나면 예전에는 같은 자리를 되돌려
            #    끝없이 돌았고, 그동안 색인 잠금을 쥐고 있어 다른 요청까지 섰다(Codex 리뷰 2026-11-12 #1).
            pos = space(pos)
            if body[pos] == 34:
                return string_end(pos)
            if body[pos] in (123, 91):
                close = 125 if body[pos] == 123 else 93
                pos = space(pos + 1)
                while body[pos] != close:
                    pos = space(skip(pos))
                    if body[pos] in (44, 58):
                        pos = space(pos + 1)
                    elif body[pos] != close:
                        raise ValueError("Malformed artist pack value")
                return pos + 1
            start = pos
            while pos < size and body[pos] not in b",:}] \t\r\n":
                pos += 1
            if pos == start:
                raise ValueError("Malformed artist pack value")
            return pos

        pos = space(0)
        if body[pos] != 123:
            raise ValueError("Artist pack must be a JSON object")
        pos = space(pos + 1)
        while body[pos] != 125:
            if body[pos] != 34:
                raise ValueError("Invalid artist pack key")
            end = string_end(pos)
            key = json.loads(bytes(body[pos:end]))
            pos = space(end)
            if body[pos] != 58:
                raise ValueError("Invalid artist pack key")
            start = space(pos + 1)
            pos = skip(start)
            offsets[str(key)] = [start, pos]
            pos = space(pos)
            if body[pos] == 44:
                pos = space(pos + 1)
            elif body[pos] != 125:
                raise ValueError("Missing artist pack separator")
        if space(pos + 1) != size:
            raise ValueError("Trailing data after artist pack")
    return offsets


def _valid_offsets(offsets, size) -> bool:
    """적어 둔 자리가 이 파일 안의 것처럼 생겼는가 - 글 열쇠 · 정수 둘 · 0 <= 시작 < 끝 <= 크기 · 앞 것과 안 겹침."""
    if not isinstance(offsets, dict):
        return False
    previous = 0
    for key, span in offsets.items():
        if not (isinstance(key, str) and isinstance(span, list) and len(span) == 2
                and all(type(x) is int for x in span) and previous <= span[0] < span[1] <= size):
            return False
        previous = span[1]
    return True


def _signature(path: Path) -> list[int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]


class ArtistPackIndex:
    """팩 하나의 자리 색인. `cache_path` 에 적어 두고, 팩의 지문이 그대로면 다시 훑지 않는다."""

    def __init__(self, path, cache_path=None):
        self.path = Path(path)
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self.signature = _signature(self.path)
        self.offsets: dict[str, list[int]] = {}
        self.reused = False
        self._folded: dict[str, str] | None = None
        self._repair_attempted = False
        if self.signature is None:
            return
        if self.cache_path is not None:
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                # 지문이 같아도 자리는 따로 본다 - 깨졌거나 남의 파일 것이면 버리고 다시 훑는다(Codex 리뷰 #4).
                if (data.get("schema") == SCHEMA and data.get("signature") == self.signature
                        and _valid_offsets(data.get("offsets"), self.signature[0])):
                    self.offsets = data["offsets"]
                    self.reused = True
                    return
            except (OSError, ValueError, AttributeError):
                pass
        self._rescan()

    def _rescan(self) -> None:
        self.offsets, self._folded, self.reused = {}, None, False
        self.offsets = scan_pack(self.path)
        if _signature(self.path) != self.signature:
            self.offsets = {}
            raise ValueError("Artist pack changed while indexing")
        self._save()

    def _save(self) -> None:
        if self.cache_path is None:
            return
        temp = None
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_path.parent,
                                             prefix=self.cache_path.name, suffix=".tmp", delete=False) as handle:
                temp = handle.name
                json.dump({"schema": SCHEMA, "signature": self.signature, "offsets": self.offsets},
                          handle, ensure_ascii=False, separators=(",", ":"))
            os.replace(temp, self.cache_path)
        except OSError:
            pass        # 적어 두지 못하면 다음에 다시 훑을 뿐이다
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)

    def is_current(self) -> bool:
        return self.signature is not None and _signature(self.path) == self.signature

    def find(self, name: str) -> str | None:
        """팩에 적힌 그대로의 이름. 못 찾으면 대소문자 · 밑줄 · 공백을 접어 한 번 더 본다."""
        name = str(name or "")
        if name in self.offsets:
            return name
        if self._folded is None:
            self._folded = {}
            for key in self.offsets:
                self._folded.setdefault(_fold(key), key)
        return self._folded.get(_fold(name))

    def read(self, key: str) -> str:
        """그 작가의 첫 그림(base64). 없으면 KeyError.

        자리 바로 앞의 열쇠가 **그 작가인지** 확인하고 읽는다 - 적어 둔 자리가 남의 값을 가리키면(깨진 색인 · 크기와 시각이
        우연히 같은 다른 파일) 남의 그림이 멀쩡히 나온다(Codex 리뷰 #4). 어긋나면 한 번 다시 훑고 읽는다.
        """
        try:
            return self._read(key)
        except _SpanMismatch:
            if self._repair_attempted:
                raise KeyError(key) from None
            self._repair_attempted = True
            try:
                self._rescan()
            except (OSError, ValueError):
                raise KeyError(key) from None
            if key not in self.offsets:
                raise KeyError(key) from None
            try:
                return self._read(key)
            except _SpanMismatch:
                raise KeyError(key) from None

    def _read(self, key: str) -> str:
        start, end = self.offsets[key]
        head = min(start, len(key.encode("utf-8")) * 6 + 64)
        with self.path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            if [stat.st_size, stat.st_mtime_ns] != self.signature:
                raise KeyError(key)         # 갈린 팩을 옛 자리로 읽지 않는다
            if not 0 <= start < end <= stat.st_size:
                raise _SpanMismatch(key)
            handle.seek(start - head)
            header = handle.read(head)
            raw = handle.read(end - start)
        match = re.search(rb'("(?:[^"\\]|\\.)*")[ \t\r\n]*:[ \t\r\n]*$', header)
        try:
            if match is None or json.loads(match[1]) != key:
                raise _SpanMismatch(key)
            value = json.loads(raw)
        except ValueError:
            raise _SpanMismatch(key) from None
        first = value[0] if isinstance(value, list) and value else value
        if not isinstance(first, str) or not first:
            raise KeyError(key)
        return first


class _SpanMismatch(KeyError):
    """적어 둔 자리가 그 작가의 값이 아니다."""


def _fold(name: str) -> str:
    return " ".join(str(name).replace("_", " ").split()).casefold()
