import io
from pathlib import Path
from typing import Optional

from PIL import Image
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QMimeData


IMAGE_CLIPBOARD_FORMATS = (
    "image/png",
    'application/x-qt-windows-mime;value="PNG"',
)


def qimage_to_png_bytes(image: QImage) -> Optional[bytes]:
    if image is None or image.isNull():
        return None
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
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
        if isinstance(image_data, QImage):
            png_bytes = qimage_to_png_bytes(image_data)
            if png_bytes:
                return png_bytes
        elif isinstance(image_data, QPixmap):
            png_bytes = qimage_to_png_bytes(image_data.toImage())
            if png_bytes:
                return png_bytes

    if clipboard_image is not None and not clipboard_image.isNull():
        png_bytes = qimage_to_png_bytes(clipboard_image)
        if png_bytes:
            return png_bytes

    return None


def clipboard_png_bytes(clipboard=None) -> Optional[bytes]:
    clipboard = clipboard or QApplication.clipboard()
    return clipboard_mime_png_bytes(clipboard.mimeData(), clipboard.image())


def pil_image_from_png_bytes(png_bytes: bytes | None) -> Optional[Image.Image]:
    if not png_bytes:
        return None
    with Image.open(io.BytesIO(png_bytes)) as image:
        image.load()
        return image.copy()


def pil_image_from_mime_data(mime_data: QMimeData | None, clipboard_image: Optional[QImage] = None) -> Optional[Image.Image]:
    return pil_image_from_png_bytes(clipboard_mime_png_bytes(mime_data, clipboard_image))


def pil_image_from_clipboard(clipboard=None) -> Optional[Image.Image]:
    return pil_image_from_png_bytes(clipboard_png_bytes(clipboard))


def qimage_from_png_bytes(png_bytes: bytes | None) -> QImage:
    image = QImage()
    if png_bytes:
        image.loadFromData(bytes(png_bytes), "PNG")
    return image


def qimage_from_clipboard(clipboard=None) -> QImage:
    return qimage_from_png_bytes(clipboard_png_bytes(clipboard))


def pixmap_from_clipboard(clipboard=None) -> QPixmap:
    image = qimage_from_clipboard(clipboard)
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


def set_png_clipboard_bytes(png_bytes: bytes, filename: str = ""):
    if not png_bytes:
        raise ValueError("No PNG data is available")

    byte_array = QByteArray(bytes(png_bytes))
    mime_data = QMimeData()
    mime_data.setData("image/png", byte_array)
    mime_data.setData('application/x-qt-windows-mime;value="PNG"', byte_array)
    qimage = qimage_from_png_bytes(png_bytes)
    if not qimage.isNull():
        mime_data.setImageData(qimage)
    if filename:
        mime_data.setText(Path(str(filename)).name)
    QApplication.clipboard().setMimeData(mime_data)
