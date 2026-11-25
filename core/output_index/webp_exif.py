"""Add the history item's PNG metadata to its on-disk WebP, not its preview."""
import io
import json
import struct

from core.output_index.head_reader import HeadResult, _png_text
from core.result_image_payload_service import PNG_SIGNATURE, history_item_png_payload


def build_generation_exif(texts: dict[str, str], description: str | None) -> bytes:
    desc = (description or "").encode("utf-8") + b"\0"
    wrapper = json.dumps({"naia_png_text": texts}, ensure_ascii=False)
    comment = b"UNICODE\0" + wrapper.encode("utf-16le")

    # TIFF offsets are relative to the byte-order mark. Each IFD has a
    # two-byte count, twelve bytes per entry and a four-byte next-IFD link.
    sub_ifd = 8 + 2 + 2 * 12 + 4
    data_start = sub_ifd + 2 + 12 + 4
    if len(desc) <= 4:
        desc_field, extra = desc.ljust(4, b"\0"), b""
    else:
        desc_field, extra = struct.pack("<I", data_start), desc + bytes(len(desc) % 2)
    return b"".join((
        struct.pack("<2sHIH", b"II", 42, 8, 2),
        struct.pack("<HHI4s", 0x010E, 2, len(desc), desc_field),
        struct.pack("<HHII", 0x8769, 4, 1, sub_ifd), bytes(4),
        struct.pack("<H", 1),
        struct.pack("<HHII", 0x9286, 7, len(comment), data_start + len(extra)), bytes(4),
        extra, comment,
    ))


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack("<4sI", kind, len(data)) + data + bytes(len(data) % 2)


def _canvas(kind: bytes, frame: memoryview) -> tuple[int, int, bool]:
    if kind == b"VP8 " and len(frame) >= 10 and frame[3:6] == b"\x9d\x01\x2a":
        w, h = (v & 0x3fff for v in struct.unpack_from("<HH", frame, 6))
        if w and h:
            return w, h, False
    if kind == b"VP8L" and len(frame) >= 5 and frame[0] == 0x2f:
        bits, = struct.unpack_from("<I", frame, 1)
        return (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1, bool(bits & (1 << 28))
    raise ValueError("invalid WebP frame header")


def add_exif_chunk(webp: bytes, exif: bytes) -> bytes:
    if (webp[:4] != b"RIFF" or webp[8:12] != b"WEBP"
            or int.from_bytes(webp[4:8], "little") != len(webp) - 8):
        raise ValueError("invalid WebP RIFF header")
    view = memoryview(webp)
    chunks = []
    vp8x = None
    canvas = None
    flags = 0x08
    has_frame = False
    xmp_pos = None
    pos = 12
    while pos < len(webp):
        kind, n = struct.unpack_from("<4sI", view, pos)
        start = pos + 8
        end = start + n + (n & 1)
        if end > len(webp):
            raise ValueError("truncated WebP chunk")
        if kind == b"VP8X":
            if n != 10 or vp8x is not None:
                raise ValueError("invalid VP8X chunk")
            vp8x = bytearray(view[start:start + n])
        elif kind != b"EXIF":
            if kind in (b"VP8 ", b"VP8L", b"ANMF"):
                has_frame = True
                if vp8x is None:
                    canvas = _canvas(kind, view[start:start + n])
            elif kind == b"ALPH":
                flags |= 0x10
            elif kind == b"ICCP":
                flags |= 0x20
            elif kind == b"XMP " and xmp_pos is None:
                flags |= 0x04
                xmp_pos = len(chunks)
            chunks.append(view[pos:end])  # Includes the original header and padding.
        pos = end
    if not has_frame:
        raise ValueError("missing WebP frame")
    if vp8x is None:
        w, h, alpha = canvas
        vp8x = bytearray(4) + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
        if alpha:
            flags |= 0x10
    vp8x[0] |= flags
    chunks.insert(xmp_pos if xmp_pos is not None else len(chunks), _chunk(b"EXIF", exif))
    chunks.insert(0, _chunk(b"VP8X", vp8x))
    size = 4 + sum(map(len, chunks))
    return b"".join([struct.pack("<4sI4s", b"RIFF", size, b"WEBP"), *chunks])


def texts_for_item(item) -> dict[str, str]:
    png, _ = history_item_png_payload(item)
    if not png.startswith(PNG_SIGNATURE):
        raise ValueError("expected PNG payload")
    # Unlike the budgeted disk index reader, the PNG is already in memory:
    # visit every text chunk, including ones after IDAT, without decoding pixels.
    out = HeadResult("png")
    pos = len(PNG_SIGNATURE)
    while pos < len(png):
        n, kind = struct.unpack_from(">I4s", png, pos)
        end = pos + 12 + n
        if end > len(png):
            raise ValueError("truncated PNG chunk")
        if kind in (b"tEXt", b"zTXt", b"iTXt"):
            _png_text(kind, png[pos + 8:end - 4], out)
        elif kind == b"IEND":
            return out.texts
        pos = end
    raise ValueError("missing PNG terminator")


# NAI 가 돌려주는 PNG 의 Comment 에는 **이미 인코딩된 vibe** 가 통째로 실린다(하나에 base64 약 65KB).
# EXIF 는 UTF-16 이라 vibe 하나에 약 130KB 가 붙어, vibe 4개면 디스크 WebP 가 5배를 넘었다(사용자 제보 11-25 ·
# v2.0.73 회귀). v2.0.72 까지 WebP 에는 메타가 아예 없었고, 색인은 프롬프트만 본다 - vibe 본문만 뺀다.
# 강도 · IE 같은 작은 값과 PNG 저장(NAI 원본 그대로)은 건드리지 않는다.
_VIBE_PAYLOAD_KEYS = ("reference_image_multiple", "reference_image")


def _without_vibe_payload(texts: dict[str, str]) -> dict[str, str]:
    comment = texts.get("Comment")
    if not isinstance(comment, str) or not any(key in comment for key in _VIBE_PAYLOAD_KEYS):
        return texts
    try:
        payload = json.loads(comment)
    except ValueError:
        return texts
    if not isinstance(payload, dict) or not any(key in payload for key in _VIBE_PAYLOAD_KEYS):
        return texts
    for key in _VIBE_PAYLOAD_KEYS:
        payload.pop(key, None)
    return {**texts, "Comment": json.dumps(payload, ensure_ascii=False)}


def _description(texts: dict[str, str]) -> str | None:
    from utils.image_info import parse_metadata_texts

    try:
        prompt = (parse_metadata_texts(texts) or {}).get("prompt")
        if isinstance(prompt, str) and prompt:
            return prompt
    except Exception:
        # Unknown provider schemas must not prevent copying the original text.
        pass
    return texts.get("Description")


def webp_bytes_for_disk(item) -> bytes:
    original = item.webp_bytes
    try:
        texts = _without_vibe_payload(texts_for_item(item))
        exif = build_generation_exif(texts, _description(texts))
    except Exception:
        # No usable metadata; a second lossy encoding would not help.
        return original
    try:
        return add_exif_chunk(original, exif)
    except Exception:
        try:
            buffer = io.BytesIO()
            item.image.save(buffer, format="WEBP", quality=85, method=0, exif=exif)
            return buffer.getvalue()
        except Exception:
            return original
