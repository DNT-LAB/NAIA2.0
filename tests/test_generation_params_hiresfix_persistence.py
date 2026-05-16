from types import SimpleNamespace

from utils.load_generation_params import GenerationParamsManager


class _ValueWidget:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class _CheckWidget:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)


class _ComboWidget:
    def __init__(self, values, current):
        self._values = list(values)
        self._current = current

    def currentText(self):
        return self._current

    def findText(self, value):
        try:
            return self._values.index(value)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self._current = self._values[index]


def _webui_window():
    return SimpleNamespace(
        enable_hr_checkbox=_CheckWidget(True),
        hr_scale_spinbox=_ValueWidget(3.0),
        hr_upscaler_combo=_ComboWidget(["Lanczos", "Latent (nearest-exact)"], "Latent (nearest-exact)"),
        denoising_strength_spinbox=_ValueWidget(0.42),
        hires_steps_spinbox=_ValueWidget(12),
        hr_cfg_spinbox=_ValueWidget(6.0),
    )


def test_webui_hiresfix_params_are_collected_from_current_widgets():
    manager = GenerationParamsManager(_webui_window())

    settings = manager.collect_current_settings()

    assert settings["enable_hr"] is True
    assert settings["hr_scale"] == 3.0
    assert settings["hr_upscaler"] == "Latent (nearest-exact)"
    assert settings["denoising_strength"] == 0.42
    assert settings["hires_steps"] == 12
    assert settings["hr_cfg"] == 6.0


def test_webui_hiresfix_params_are_restored_to_current_widgets():
    window = _webui_window()
    manager = GenerationParamsManager(window)

    manager.apply_settings({
        "enable_hr": False,
        "hr_scale": 2.5,
        "hr_upscaler": "Lanczos",
        "denoising_strength": 0.65,
        "hires_steps": 18,
        "hr_cfg": 5.5,
    })

    assert window.enable_hr_checkbox.isChecked() is False
    assert window.hr_scale_spinbox.value() == 2.5
    assert window.hr_upscaler_combo.currentText() == "Lanczos"
    assert window.denoising_strength_spinbox.value() == 0.65
    assert window.hires_steps_spinbox.value() == 18
    assert window.hr_cfg_spinbox.value() == 5.5
