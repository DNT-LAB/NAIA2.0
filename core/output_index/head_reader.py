"""Read container headers, not decoded images. All offsets are checked before I/O."""
from dataclasses import dataclass, field
from pathlib import Path
import struct
from typing import BinaryIO, Literal
import zlib


@dataclass
class HeadResult:
    kind: Literal["png", "webp", "jpeg"]
    texts: dict[str, str] = field(default_factory=dict)
    exif_user_comment: str | None = None
    width: int = 0
    height: int = 0
    alpha: bool = False
    bytes_read: int = 0


class _Reader:
    def __init__(self, file: BinaryIO):
        self.file = file
        self.end = file.seek(0, 2)
        self.count = 0

    def at(self, pos: int, n: int) -> bytes:
        if pos < 0 or n < 0 or pos + n > self.end:
            raise ValueError("truncated image header")
        self.file.seek(pos)
        data = self.file.read(n)
        self.count += len(data)
        if len(data) != n:
            raise ValueError("short read")
        return data


def _exif(data: bytes, out: HeadResult) -> None:
    data = data.removeprefix(b"Exif\0\0")
    order = {b"II": "little", b"MM": "big"}.get(data[:2])
    if order is None:
        raise ValueError("invalid TIFF byte order")

    def take(pos: int, size: int) -> bytes:
        if pos + size > len(data):
            raise ValueError("truncated TIFF")
        return data[pos:pos + size]

    def number(pos: int, size: int) -> int:
        return int.from_bytes(take(pos, size), order)

    def ifd(pos: int) -> dict[int, int]:
        count = number(pos, 2)
        if pos < 8 or pos + 2 + count * 12 + 4 > len(data):
            raise ValueError("invalid TIFF directory")
        return {number(p, 2): p for p in range(pos + 2, pos + 2 + count * 12, 12)}

    def string(entry: int) -> bytes:
        if number(entry + 2, 2) not in (1, 2, 7):
            raise ValueError("invalid EXIF string type")
        size = number(entry + 4, 4)
        return take(entry + 8 if size <= 4 else number(entry + 8, 4), size)

    if number(2, 2) != 42:
        raise ValueError("invalid TIFF magic")
    main = ifd(number(4, 4))
    if 0x010E in main:
        out.texts["ImageDescription"] = string(main[0x010E]).rstrip(b"\0").decode("utf8", "replace")
    sub = main
    if 0x8769 in main:
        sub = ifd(number(main[0x8769] + 8, 4))
    if 0x9286 in sub:
        value = string(sub[0x9286])
        encoding = {b"ASCII\0\0\0": "ascii", b"JIS\0\0\0\0\0": "shift_jis",
                    b"UNICODE\0": "utf-16-le" if order == "little" else "utf-16-be"}.get(value[:8])
        # An undefined/unknown prefix has no specified text encoding.
        if encoding:
            out.exif_user_comment = value[8:].decode(encoding, "replace")


_TEXT = {b"tEXt", b"zTXt", b"iTXt"}
_KNOWN = _TEXT | set(b"IEND IDAT PLTE tRNS cHRM gAMA iCCP sBIT sRGB bKGD hIST pHYs sPLT tIME "
                     b"eXIf acTL fcTL fdAT cICP mDCV cLLI sTER oFFs pCAL sCAL dSIG".split())
_WINDOW = 64 * 1024
# A corrupt (or highly compressed) metadata chunk must not exhaust the process.
_MAX_TEXT = 64 * 1024 * 1024


def _inflate(data: bytes) -> bytes:
    try:
        decoder = zlib.decompressobj()
        result = decoder.decompress(data, _MAX_TEXT + 1)
    except zlib.error as exc:
        raise ValueError("invalid compressed PNG text") from exc
    if len(result) > _MAX_TEXT or not decoder.eof:
        raise ValueError("oversized or truncated PNG text")
    return result


def _png_text(kind: bytes, data: bytes, out: HeadResult) -> None:
    key, value = data.split(b"\0", 1)
    if not 1 <= len(key) <= 79:
        raise ValueError("invalid PNG text keyword")
    if kind == b"zTXt":
        if value[:1] != b"\0":
            raise ValueError("unknown PNG compression")
        value = _inflate(value[1:])
    elif kind == b"iTXt":
        if value[:2] not in (b"\0\0", b"\1\0"):
            raise ValueError("invalid iTXt flags")
        _, _, text = value[2:].split(b"\0", 2)
        value = _inflate(text) if value[0] else text
    out.texts[key.decode("latin1")] = value.decode("utf8" if kind == b"iTXt" else "latin1")


def _crc(kind: bytes, data: bytes) -> int:
    return zlib.crc32(data, zlib.crc32(kind))


def _png_tail(r: _Reader, pos: int, out: HeadResult) -> None:
    base = r.end - _WINDOW
    tail = r.at(base, _WINDOW)

    def at(p: int, n: int) -> bytes:
        return tail[p-base:p-base+n] if p >= base else r.at(p, n)

    # Anchor to the actual IDAT end, not a possible chunk signature inside
    # pixel data. Lengths let us recover the start of a straddling chunk
    # even when neither its type nor its length is visible in the window.
    while pos + 12 <= r.end:
        n, kind = struct.unpack(">I4s", at(pos, 8))
        end = pos + n + 12
        if end > r.end:
            raise ValueError("truncated PNG tail")
        if kind == b"IEND":
            if n:
                raise ValueError("invalid IEND")
            return
        if (kind in _TEXT and end > base and end + 8 <= r.end
                and (pos >= base or n + 12 <= 1024 * 1024)
                and at(end + 4, 4) in _KNOWN):
            chunk = at(pos, n + 12)
            if _crc(kind, chunk[8:-4]) == int.from_bytes(chunk[-4:], "big"):
                _png_text(kind, chunk[8:-4], out)
        pos = end
    raise ValueError("missing IEND")


def _png(r: _Reader) -> HeadResult:
    if r.at(2, 6) != b"NG\r\n\x1a\n" or r.at(8, 8) != b"\0\0\0\rIHDR":
        raise ValueError("invalid PNG header")
    header = r.at(16, 17)
    w, h = struct.unpack(">II", header[:8])
    if _crc(b"IHDR", header[:13]) != int.from_bytes(header[13:], "big"):
        raise ValueError("bad IHDR checksum")
    depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    if header[8] not in depths.get(header[9], ()) or header[10:12] != bytes(2) or header[12] > 1:
        raise ValueError("invalid IHDR fields")
    out = HeadResult("png", width=w, height=h, alpha=header[9] in (4, 6))
    pos = 33
    saw_text = False
    while True:
        n, kind = struct.unpack(">I4s", r.at(pos, 8))
        end = pos + 12 + n
        if end > r.end or kind == b"IEND":
            raise ValueError("truncated PNG or missing IDAT")
        if kind == b"IDAT":
            if end + 12 > r.end:
                raise ValueError("missing PNG terminator")
            if not saw_text and r.end > _WINDOW:
                _png_tail(r, end, out)
            return out
        if kind in _TEXT or kind == b"eXIf":
            if n > _MAX_TEXT:
                raise ValueError("oversized PNG metadata")
            data = r.at(pos + 8, n)
            if _crc(kind, data) != int.from_bytes(r.at(end - 4, 4), "big"):
                raise ValueError("bad PNG metadata checksum")
            if kind == b"eXIf":
                _exif(data, out)
            else:
                _png_text(kind, data, out)
                saw_text = True
        pos = end


def _webp_frame(kind: bytes, header: bytes, out: HeadResult) -> None:
    # A simple WebP has no VP8X canvas. Only its fixed frame header holds
    # dimensions; the compressed pixel stream starts immediately after it.
    if kind == b"VP8 " and header[3:6] == b"\x9d\x01\x2a":
        out.width, out.height = (v & 0x3fff for v in struct.unpack("<HH", header[6:]))
    elif kind == b"VP8L" and header[0] == 0x2f:
        bits = int.from_bytes(header[1:], "little")
        out.width, out.height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
        out.alpha |= bool(bits & (1 << 28))
    else:
        raise ValueError("bad WebP frame header")


def _webp(r: _Reader) -> HeadResult:
    if r.at(2, 2) != b"FF" or r.at(8, 4) != b"WEBP":
        raise ValueError("invalid WebP signature")
    limit = 8 + int.from_bytes(r.at(4, 4), "little")
    if limit > r.end:
        raise ValueError("truncated RIFF")
    out = HeadResult("webp")
    pos = 12
    frame = False
    while pos < limit:
        kind, n = struct.unpack("<4sI", r.at(pos, 8))
        pos += 8
        end = pos + n + (n & 1)
        if end > limit:
            raise ValueError("bad RIFF chunk size")
        if kind == b"VP8X":
            if n != 10:
                raise ValueError("invalid VP8X")
            header = r.at(pos, 10)
            out.alpha |= bool(header[0] & 0x10)
            out.width = int.from_bytes(header[4:7], "little") + 1
            out.height = int.from_bytes(header[7:], "little") + 1
        elif kind in (b"VP8 ", b"VP8L"):
            needed = 10 if kind == b"VP8 " else 5
            if n < needed:
                raise ValueError("truncated WebP frame")
            if not out.width:
                _webp_frame(kind, r.at(pos, needed), out)
            frame = True
        elif kind == b"ANMF":
            frame = True
        elif kind == b"ALPH":
            out.alpha = True
        elif kind in (b"EXIF", b"XMP "):
            if n > _MAX_TEXT:
                raise ValueError("oversized WebP metadata")
            data = r.at(pos, n)
            if kind == b"EXIF":
                _exif(data, out)
            else:
                out.texts["XMP"] = data.decode("utf8")
        pos = end
    if not frame:
        raise ValueError("missing WebP frame")
    return out


_SOF = {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}


def _jpeg(r: _Reader) -> HeadResult:
    pos = 2
    out = HeadResult("jpeg")
    while True:
        if r.at(pos, 1) != b"\xff":
            raise ValueError("invalid JPEG marker")
        pos += 1
        marker = r.at(pos, 1)[0]
        while marker == 0xff:
            pos += 1
            marker = r.at(pos, 1)[0]
        pos += 1
        if marker == 0xda:
            if pos + 6 > r.end:
                raise ValueError("truncated JPEG scan header")
            return out
        if marker in (0, 0xd8, 0xd9):
            raise ValueError("unexpected JPEG marker")
        if marker == 1 or 0xd0 <= marker <= 0xd7:
            continue
        n = int.from_bytes(r.at(pos, 2), "big")
        if n < 2 or pos + n > r.end:
            raise ValueError("bad JPEG segment length")
        if marker in _SOF:
            if n < 8:
                raise ValueError("truncated SOF")
            out.height, out.width = struct.unpack(">HH", r.at(pos + 3, 4))
        elif marker == 0xe1 and n >= 8 and r.at(pos + 2, 6) == b"Exif\0\0":
            _exif(r.at(pos + 8, n - 8), out)
        elif marker == 0xfe:
            data = r.at(pos + 2, n - 2)
            try:
                out.texts["comment"] = data.decode("utf8")
            except UnicodeDecodeError:
                out.texts["comment"] = data.decode("latin1")
        pos += n


def read_head(path: str | Path) -> HeadResult:
    with open(path, "rb", buffering=0) as file:
        r = _Reader(file)
        parse = {b"\x89P": _png, b"RI": _webp, b"\xff\xd8": _jpeg}.get(r.at(0, 2))
        if parse is None:
            raise ValueError("unsupported image signature")
        out = parse(r)
        if not out.width or not out.height:
            raise ValueError("missing image dimensions")
        out.bytes_read = r.count
        return out
