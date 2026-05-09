import io
import json
import os

os.environ.setdefault("NAIA_SKIP_AUTO_DOWNLOAD", "true")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QByteArray, QMimeData
from PyQt6.QtGui import QImage

from modules.vibe_transfer_module import (
    VibeTransferFrame,
    VibeTransferModule,
    _clipboard_mime_png_bytes,
    _coerce_information_extracted,
    _coerce_reference_strength,
)


class _FakeContext:
    def __init__(self, mode="NAI"):
        self.mode = mode

    def get_api_mode(self):
        return self.mode


class _FakeSlider:
    def __init__(self):
        self.value = None

    def setValue(self, value):
        self.value = value


class _FakeLabel:
    def __init__(self):
        self.text = None

    def setText(self, text):
        self.text = text


class _FakeCheckBox:
    def __init__(self, checked=False):
        self.checked = checked

    def isChecked(self):
        return self.checked

    def setChecked(self, checked):
        self.checked = checked


class _FalseyLayout:
    def __bool__(self):
        return False


class _FakeFrame:
    def __init__(self):
        self.reference_strength = 0.6
        self.information_extracted = 1.0
        self.is_no_image = False
        self.ref_strength_slider = _FakeSlider()
        self.info_extracted_slider = _FakeSlider()
        self.ref_strength_label = _FakeLabel()
        self.info_extracted_label = _FakeLabel()
        self.status_updates = 0
        self.button_updates = 0

    def _update_encoding_status(self):
        self.status_updates += 1

    def _update_encode_button_visibility(self):
        self.button_updates += 1


def _png_bytes(color=(12, 34, 56)):
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _metadata_storage_frame(file_hash="abc123metadata"):
    frame = VibeTransferFrame.__new__(VibeTransferFrame)
    frame.app_context = _FakeContext()
    frame.file_path = f"metadata_vibe_{file_hash}"
    frame.file_name = f"metadata_vibe_{file_hash}"
    frame.file_hash = file_hash
    frame.is_no_image = True
    frame.target_model = "NAID4.5F"
    frame.storage_type = "metadata_vibe"
    frame.vibe_encodings = {1.0: "encoded-metadata"}
    frame.reference_strength = 0.21
    frame.information_extracted = 1.0
    frame.is_enabled = True
    return frame


def _write_vibe_storage(tmp_path, model, file_hash, original_path):
    storage_dir = tmp_path / "save" / "vibe_transfer" / model
    image_dir = storage_dir / "images"
    image_dir.mkdir(parents=True)
    Image.new("RGB", (4, 4), (88, 44, 22)).save(image_dir / f"{file_hash}.png")
    storage_data = {
        "file_hash": file_hash,
        "file_path": str(original_path),
        "file_name": "source.png",
        "encodings": {"0.42": "encoded"},
        "reference_strength": 0.73,
        "information_extracted": 0.42,
    }
    (storage_dir / f"{file_hash}.json").write_text(
        json.dumps(storage_data),
        encoding="utf-8",
    )
    return storage_data


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


def test_clipboard_mime_png_bytes_prefers_raw_png_over_qt_image_data():
    png_bytes = _png_bytes((11, 22, 33))
    qimage = QImage(4, 4, QImage.Format.Format_RGB32)
    qimage.fill(0xFF336699)
    mime_data = QMimeData()
    mime_data.setImageData(qimage)
    mime_data.setData("image/png", QByteArray(png_bytes))

    assert _clipboard_mime_png_bytes(mime_data) == png_bytes


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


def test_vibe_autosave_skips_until_widget_ready(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = VibeTransferModule()
    module.app_context = _FakeContext()
    calls = []
    module.save_mode_settings = lambda mode=None: calls.append(mode)

    module._autosave_current_mode_settings()

    assert calls == []


def test_vibe_autosave_saves_current_mode_when_ready(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = VibeTransferModule()
    module.app_context = _FakeContext()
    module.widget = object()
    module.scroll_layout = object()
    calls = []
    module.save_mode_settings = lambda mode=None: calls.append(mode)

    module._autosave_current_mode_settings()

    assert calls == ["NAI"]


def test_vibe_autosave_accepts_empty_qt_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = VibeTransferModule()
    module.app_context = _FakeContext()
    module.widget = object()
    module.scroll_layout = _FalseyLayout()
    calls = []
    module.save_mode_settings = lambda mode=None: calls.append(mode)

    module._autosave_current_mode_settings()

    assert calls == ["NAI"]


def test_vibe_autosave_ignores_apply_settings_reentry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = VibeTransferModule()
    module.app_context = _FakeContext()
    module.widget = object()
    module.scroll_layout = object()
    module._applying_settings = True
    calls = []
    module.save_mode_settings = lambda mode=None: calls.append(mode)

    module._autosave_current_mode_settings()

    assert calls == []


def test_vibe_load_after_widget_ready_runs_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = VibeTransferModule()
    module.app_context = _FakeContext()
    module.widget = object()
    module.scroll_layout = object()
    module.normalize_checkbox = object()
    calls = []
    module.load_mode_settings = lambda mode=None: calls.append(mode)

    module._load_settings_after_widget_ready()
    module._load_settings_after_widget_ready()

    assert calls == ["NAI"]


def test_vibe_load_after_widget_ready_accepts_empty_qt_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = VibeTransferModule()
    module.app_context = _FakeContext()
    module.widget = object()
    module.scroll_layout = _FalseyLayout()
    module.normalize_checkbox = object()
    calls = []
    module.load_mode_settings = lambda mode=None: calls.append(mode)

    module._load_settings_after_widget_ready()

    assert calls == ["NAI"]


def test_vibe_restore_uses_storage_image_when_original_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing_path = tmp_path / "missing.png"
    _write_vibe_storage(tmp_path, "NAID4.5F", "abc123", missing_path)

    module = VibeTransferModule()
    module.app_context = _FakeContext()

    file_path, file_hash, storage_data = module._resolve_regular_frame_restore_source({
        "file_path": str(missing_path),
        "file_hash": "abc123",
        "target_model": "NAID4.5F",
    })

    assert tmp_path.joinpath(file_path).resolve() == (
        tmp_path / "save" / "vibe_transfer" / "NAID4.5F" / "images" / "abc123.png"
    )
    assert file_hash == "abc123"
    assert storage_data["reference_strength"] == 0.73


def test_vibe_restore_finds_legacy_storage_without_saved_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing_path = tmp_path / "legacy-source.png"
    _write_vibe_storage(tmp_path, "NAID4.5F", "legacy123", missing_path)

    module = VibeTransferModule()
    module.app_context = _FakeContext()

    file_path, file_hash, storage_data = module._resolve_regular_frame_restore_source({
        "file_path": str(missing_path),
        "target_model": "NAID4.5F",
    })

    assert tmp_path.joinpath(file_path).resolve() == (
        tmp_path / "save" / "vibe_transfer" / "NAID4.5F" / "images" / "legacy123.png"
    )
    assert file_hash == "legacy123"
    assert storage_data["information_extracted"] == 0.42


def test_apply_frame_storage_metadata_updates_strength_and_information_extracted():
    module = VibeTransferModule()
    frame = _FakeFrame()

    changed = module._apply_frame_storage_metadata(frame, {
        "reference_strength": "0.81",
        "information_extracted": "0.37",
    })

    assert changed is True
    assert frame.reference_strength == 0.81
    assert frame.information_extracted == 0.37
    assert frame.ref_strength_slider.value == 81
    assert frame.info_extracted_slider.value == 37
    assert frame.ref_strength_label.text == "Reference Strength 0.81"
    assert frame.info_extracted_label.text == "Information Extracted 0.37"
    assert frame.status_updates == 1
    assert frame.button_updates == 1


def test_no_image_metadata_hash_is_filesystem_safe():
    assert VibeTransferFrame._calculate_no_image_hash(
        "temp/no_image_metadata_abcdef1234567890.png"
    ) == "abcdef1234567890"


def test_metadata_vibe_restore_does_not_pollute_vibe_storage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    frame = _metadata_storage_frame()
    frame._save_encodings()

    storage_json = tmp_path / "save" / "vibe_transfer" / "NAID4.5F" / f"{frame.file_hash}.json"
    assert not storage_json.exists()
    assert not (tmp_path / "save" / "vibe_transfer" / "NAID4.5F" / "images" / f"{frame.file_hash}.png").exists()


def test_metadata_vibe_settings_restore_uses_inline_encoding(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original = _metadata_storage_frame()
    original._save_encodings()

    module = VibeTransferModule()
    module.app_context = _FakeContext()
    module.normalize_checkbox = _FakeCheckBox()
    module.vibe_frames = [original]
    settings = module.collect_current_settings()
    entry = settings["vibe_frames"][0]
    assert entry["file_hash"] == original.file_hash
    assert entry["storage_type"] == "metadata_vibe"
    assert entry["vibe_encodings"] == {"1.0": "encoded-metadata"}

    restored = VibeTransferModule()
    restored.app_context = _FakeContext()
    restored.normalize_checkbox = _FakeCheckBox()
    restored.vibe_frames = []
    captured = {}

    def fake_add(no_image_path, vibe_data, storage_hash_override=None):
        captured["no_image_path"] = no_image_path
        captured["vibe_data"] = vibe_data
        captured["storage_hash_override"] = storage_hash_override
        frame = _FakeFrame()
        frame.file_hash = storage_hash_override
        frame.vibe_encodings = {
            float(key): value
            for key, value in zip(
                vibe_data["reference_information_extracted_multiple"],
                vibe_data["reference_image_multiple"],
            )
        }
        frame.reference_strength = vibe_data["reference_strength_multiple"][0]
        frame.is_no_image = True
        frame.target_model = vibe_data["source_model"]
        frame.storage_type = "metadata_vibe"
        frame.file_name = f"metadata_vibe_{storage_hash_override}"
        frame._update_model_compatibility_display = lambda current_model: None
        frame.enable_check = _FakeCheckBox()
        restored.vibe_frames.append(frame)
        return frame

    restored._add_vibe_frame_from_metadata = fake_add
    restored.apply_settings(settings)

    assert len(restored.vibe_frames) == 1
    frame = restored.vibe_frames[0]
    assert frame.file_hash == original.file_hash
    assert frame.vibe_encodings == {1.0: "encoded-metadata"}
    assert frame.reference_strength == 0.21
    assert captured["storage_hash_override"] == original.file_hash
