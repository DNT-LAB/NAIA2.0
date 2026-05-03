import io
import json

from PIL import Image
from PyQt6.QtCore import QByteArray, QMimeData
from PyQt6.QtGui import QImage

from modules.vibe_transfer_module import (
    VibeTransferModule,
    _clipboard_mime_png_bytes,
    _coerce_information_extracted,
    _coerce_reference_strength,
)


def _png_bytes(color=(12, 34, 56)):
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_clipboard_mime_png_bytes_reads_raw_png_format():
    png_bytes = _png_bytes()
    mime_data = QMimeData()
    mime_data.setData("image/png", QByteArray(png_bytes))

    assert mime_data.hasImage() is False
    assert _clipboard_mime_png_bytes(mime_data) == png_bytes


def test_clipboard_mime_png_bytes_reads_native_windows_png_format():
    png_bytes = _png_bytes((90, 12, 33))
    mime_data = QMimeData()
    mime_data.setData('application/x-qt-windows-mime;value="PNG"', QByteArray(png_bytes))

    assert mime_data.hasImage() is False
    assert _clipboard_mime_png_bytes(mime_data) == png_bytes


def test_clipboard_mime_png_bytes_reads_qt_image_data():
    qimage = QImage(4, 4, QImage.Format.Format_RGB32)
    qimage.fill(0xFF336699)
    mime_data = QMimeData()
    mime_data.setImageData(qimage)

    extracted = _clipboard_mime_png_bytes(mime_data)

    assert extracted
    with Image.open(io.BytesIO(extracted)) as image:
        assert image.size == (4, 4)


def test_vibe_reference_strength_coercion_keeps_slider_bounds():
    assert _coerce_reference_strength("0.72") == 0.72
    assert _coerce_reference_strength("2.0") == 1.0
    assert _coerce_reference_strength("-2.0") == -1.0
    assert _coerce_reference_strength("bad", 0.6) == 0.6


def test_vibe_information_extracted_coercion_keeps_slider_bounds():
    assert _coerce_information_extracted("0.35") == 0.35
    assert _coerce_information_extracted("2.0") == 1.0
    assert _coerce_information_extracted("-2.0") == 0.0
    assert _coerce_information_extracted(None, 0.8) == 0.8


def test_imported_vibe_storage_persists_reference_strength(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    image_path = tmp_path / "source.png"
    Image.new("RGB", (4, 4), (12, 34, 56)).save(image_path)

    module = VibeTransferModule()
    module._save_imported_vibe(
        "NAID4.5F",
        "abc123",
        str(image_path),
        {1.0: "encoded"},
        reference_strength=0.73,
        information_extracted=0.42,
    )

    storage_json = tmp_path / "save" / "vibe_transfer" / "NAID4.5F" / "abc123.json"
    data = json.loads(storage_json.read_text(encoding="utf-8"))

    assert data["reference_strength"] == 0.73
    assert data["information_extracted"] == 0.42


def test_imported_vibe_storage_preserves_existing_strength_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    image_path = tmp_path / "source.png"
    Image.new("RGB", (4, 4), (12, 34, 56)).save(image_path)

    module = VibeTransferModule()
    module._save_imported_vibe(
        "NAID4.5F",
        "abc123",
        str(image_path),
        {1.0: "encoded"},
        reference_strength=0.73,
        information_extracted=0.42,
    )
    module._save_imported_vibe(
        "NAID4.5F",
        "abc123",
        str(image_path),
        {1.0: "encoded-again"},
    )

    storage_json = tmp_path / "save" / "vibe_transfer" / "NAID4.5F" / "abc123.json"
    data = json.loads(storage_json.read_text(encoding="utf-8"))

    assert data["encodings"] == {"1.0": "encoded-again"}
    assert data["reference_strength"] == 0.73
    assert data["information_extracted"] == 0.42
