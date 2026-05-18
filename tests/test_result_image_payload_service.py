import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from core import result_image_payload_service as result_images


def _png_bytes(color="white", *, comment=""):
    image = Image.new("RGB", (2, 2), color)
    if comment:
        image.info["Comment"] = comment
    return result_images.pil_image_to_png_bytes(image)


def test_result_image_payload_service_has_no_pyqt_dependency():
    source = Path(result_images.__file__).read_text(encoding="utf-8")

    assert "PyQt" not in source
    assert "QObject" not in source


def test_image_media_type_detection_from_bytes_and_path(tmp_path):
    webp = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(webp, format="WEBP")

    assert result_images.image_media_type_for_bytes(_png_bytes()) == "image/png"
    assert result_images.image_media_type_for_bytes(b"\xff\xd8\xffjpeg") == "image/jpeg"
    assert result_images.image_media_type_for_bytes(webp.getvalue()) == "image/webp"
    assert result_images.image_media_type_for_bytes(b"unknown") == "application/octet-stream"
    assert result_images.image_media_type_for_path(tmp_path / "result.webp") == "image/webp"
    assert result_images.image_media_type_for_path(tmp_path / "result.png") == "image/png"


def test_history_item_image_payload_prefers_raw_bytes():
    raw = _png_bytes("blue", comment="raw-marker")
    item = SimpleNamespace(raw_bytes=bytearray(raw), image=Image.new("RGB", (2, 2), "red"))

    payload, media_type = result_images.history_item_image_payload(item)

    assert payload == raw
    assert media_type == "image/png"


def test_history_item_image_payload_converts_pil_with_metadata():
    image = Image.new("RGB", (2, 2), "white")
    image.info["Comment"] = "history-marker"
    item = SimpleNamespace(raw_bytes=b"", image=image)

    payload, media_type = result_images.history_item_image_payload(item)

    assert media_type == "image/png"
    with Image.open(io.BytesIO(payload)) as opened:
        assert opened.info.get("Comment") == "history-marker"


def test_history_item_png_payload_prefers_saved_png_file(tmp_path):
    image_path = tmp_path / "00001.png"
    saved = _png_bytes("green", comment="saved-file-marker")
    image_path.write_bytes(saved)
    item = SimpleNamespace(
        filepath=str(image_path),
        raw_bytes=b"not-a-png",
        image=Image.new("RGB", (2, 2), "red"),
    )

    payload, filename = result_images.history_item_png_payload(item)

    assert payload == saved
    assert filename == "00001.png"


def test_memory_history_thumbnail_payload_returns_webp():
    item = SimpleNamespace(image=Image.new("RGB", (64, 96), "white"))

    payload = result_images.memory_history_thumbnail_payload(item, 128)

    assert payload
    assert result_images.image_media_type_for_bytes(payload) == "image/webp"


def test_history_item_meta_payload_summary_and_full_sanitizer():
    item = SimpleNamespace(
        generation_params={"input": "prompt", "negative_prompt": "bad"},
        prompt_context={"characters": ["alice"]},
        api_metadata={"raw_bytes": b"secret"},
    )

    result = result_images.history_item_meta_payload(
        item,
        include_full=True,
        metadata_json_safe=lambda value: {"sanitized": value["generation_params"]["input"]},
    )

    assert result["prompt"] == "prompt"
    assert result["negative"] == "bad"
    assert result["characters"] == ["alice"]
    assert result["summary"]["prompt"] == "prompt"
    assert result["raw"] == {"sanitized": "prompt"}
