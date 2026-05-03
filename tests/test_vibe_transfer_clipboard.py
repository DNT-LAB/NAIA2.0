import io

from PIL import Image
from PyQt6.QtCore import QByteArray, QMimeData
from PyQt6.QtGui import QImage

from modules.vibe_transfer_module import _clipboard_mime_png_bytes


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
