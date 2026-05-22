from __future__ import annotations

import importlib
from pathlib import Path
from typing import Optional

from PIL import Image

from utils.image_bytes import pil_image_from_png_bytes


def _load_qt_contracts():
    try:
        qt_core = importlib.import_module("PyQt6.QtCore")
        qt_gui = importlib.import_module("PyQt6.QtGui")
        qt_widgets = importlib.import_module("PyQt6.QtWidgets")
        return {
            "QByteArray": qt_core.QByteArray,
            "QBuffer": qt_core.QBuffer,
            "QIODevice": qt_core.QIODevice,
            "QMimeData": qt_core.QMimeData,
            "QImage": qt_gui.QImage,
            "QPixmap": qt_gui.QPixmap,
            "QApplication": qt_widgets.QApplication,
        }
    except ImportError:
        return {
            "QByteArray": None,
            "QBuffer": None,
            "QIODevice": None,
            "QMimeData": None,
            "QImage": None,
            "QPixmap": None,
            "QApplication": None,
        }


_QT = _load_qt_contracts()
QByteArray = _QT["QByteArray"]
QBuffer = _QT["QBuffer"]
QIODevice = _QT["QIODevice"]
QMimeData = _QT["QMimeData"]
QImage = _QT["QImage"]
QPixmap = _QT["QPixmap"]
QApplication = _QT["QApplication"]


IMAGE_CLIPBOARD_FORMATS = (
    "image/png",
    'application/x-qt-windows-mime;value="PNG"',
)


def _require_qt(name: str):
    value = _QT.get(name)
    if value is None:
        raise RuntimeError("Qt clipboard image support is not available in this runtime")
    return value


def qimage_to_png_bytes(image: QImage) -> Optional[bytes]:
    qbuffer = _require_qt("QBuffer")
    qiodevice = _require_qt("QIODevice")
    if image is None or image.isNull():
        return None
    buffer = qbuffer()
    if not buffer.open(qiodevice.OpenModeFlag.WriteOnly):
        return None
    if not image.save(buffer, "PNG"):
        return None
    return bytes(buffer.data())


def clipboard_mime_png_bytes(mime_data: QMimeData | None, clipboard_image: Optional[QImage] = None) -> Optional[bytes]:
    """Return PNG bytes from Qt clipboard MIME data.

    Some copy paths expose only raw image/png clipboard bytes. Prefer that raw
    PNG payload when present so paste targets keep metadata and do not depend on
    Qt's hasImage() conversion.
    """
    if mime_data is None:
        return None

    for fmt in IMAGE_CLIPBOARD_FORMATS:
        if mime_data.hasFormat(fmt):
            data = bytes(mime_data.data(fmt))
            if data:
                return data

    if mime_data.hasImage():
        image_data = mime_data.imageData()
        if QImage is not None and isinstance(image_data, QImage):
            png_bytes = qimage_to_png_bytes(image_data)
            if png_bytes:
                return png_bytes
        elif QPixmap is not None and isinstance(image_data, QPixmap):
            png_bytes = qimage_to_png_bytes(image_data.toImage())
            if png_bytes:
                return png_bytes

    if clipboard_image is not None and not clipboard_image.isNull():
        png_bytes = qimage_to_png_bytes(clipboard_image)
        if png_bytes:
            return png_bytes

    return None


def clipboard_png_bytes(clipboard=None) -> Optional[bytes]:
    qapplication = _require_qt("QApplication")
    clipboard = clipboard or qapplication.clipboard()
    return clipboard_mime_png_bytes(clipboard.mimeData(), clipboard.image())


def pil_image_from_mime_data(mime_data: QMimeData | None, clipboard_image: Optional[QImage] = None) -> Optional[Image.Image]:
    return pil_image_from_png_bytes(clipboard_mime_png_bytes(mime_data, clipboard_image))


def pil_image_from_clipboard(clipboard=None) -> Optional[Image.Image]:
    return pil_image_from_png_bytes(clipboard_png_bytes(clipboard))


def qimage_from_png_bytes(png_bytes: bytes | None) -> QImage:
    qimage = _require_qt("QImage")
    image = qimage()
    if png_bytes:
        image.loadFromData(bytes(png_bytes), "PNG")
    return image


def qimage_from_clipboard(clipboard=None) -> QImage:
    return qimage_from_png_bytes(clipboard_png_bytes(clipboard))


def pixmap_from_clipboard(clipboard=None) -> QPixmap:
    qpixmap = _require_qt("QPixmap")
    image = qimage_from_clipboard(clipboard)
    return qpixmap.fromImage(image) if not image.isNull() else qpixmap()


def set_png_clipboard_bytes(png_bytes: bytes, filename: str = ""):
    if not png_bytes:
        raise ValueError("No PNG data is available")

    qbytearray = _require_qt("QByteArray")
    qmimedata = _require_qt("QMimeData")
    qapplication = _require_qt("QApplication")
    byte_array = qbytearray(bytes(png_bytes))
    mime_data = qmimedata()
    mime_data.setData("image/png", byte_array)
    mime_data.setData('application/x-qt-windows-mime;value="PNG"', byte_array)
    qimage = qimage_from_png_bytes(png_bytes)
    if not qimage.isNull():
        mime_data.setImageData(qimage)
    if filename:
        mime_data.setText(Path(str(filename)).name)
    qapplication.clipboard().setMimeData(mime_data)
