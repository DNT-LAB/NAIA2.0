import json
import os
import subprocess
import sys

from PIL import Image

from utils.image_bytes import pil_image_from_png_bytes, png_bytes_from_pil_image


def test_image_bytes_round_trip_png_without_qt():
    source = Image.new("RGBA", (2, 3), (10, 20, 30, 255))

    png_bytes = png_bytes_from_pil_image(source)
    result = pil_image_from_png_bytes(png_bytes)

    assert png_bytes and png_bytes.startswith(b"\x89PNG")
    assert result is not None
    assert result.size == (2, 3)
    assert result.getpixel((0, 0)) == (10, 20, 30, 255)


def test_image_bytes_import_does_not_import_pyqt_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
import utils.image_bytes
print(json.dumps({"pyqt_imported": "PyQt6" in sys.modules}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(result.stdout) == {"pyqt_imported": False}
