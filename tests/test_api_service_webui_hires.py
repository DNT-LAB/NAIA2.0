from core.api_service import APIService


def test_webui_hires_uses_explicit_hires_steps_and_scale_path():
    service = APIService(app_context=None)
    payload = {"width": 512, "height": 512}

    service._apply_webui_hires_params(
        payload,
        {
            "enable_hr": "true",
            "hr_scale": "3",
            "hr_upscaler": "Latent",
            "denoising_strength": "0.5",
            "hires_steps": "10",
            "hr_cfg": "7",
            "steps": 30,
        },
        is_img2img=False,
    )

    assert payload["enable_hr"] is True
    assert payload["hr_scale"] == 3
    assert payload["hr_upscaler"] == "Latent"
    assert payload["denoising_strength"] == 0.5
    assert payload["hr_second_pass_steps"] == 10
    assert payload["hr_resize_x"] == 0
    assert payload["hr_resize_y"] == 0
    assert payload["hr_additional_modules"] == ["Use same choices"]
    assert payload["hr_cfg"] == 7


def test_webui_hires_does_not_enable_from_false_string():
    service = APIService(app_context=None)
    payload = {"width": 512, "height": 512}

    service._apply_webui_hires_params(
        payload,
        {"enable_hr": "false", "hires_steps": "10"},
        is_img2img=False,
    )

    assert payload == {"width": 512, "height": 512, "enable_hr": False}


def test_webui_hires_uses_naia_defaults_when_optional_values_are_missing():
    service = APIService(app_context=None)
    payload = {"width": 512, "height": 512}

    service._apply_webui_hires_params(
        payload,
        {"enable_hr": True},
        is_img2img=False,
    )

    assert payload["hr_scale"] == 2.0
    assert payload["hr_upscaler"] == "Latent (nearest-exact)"
    assert payload["denoising_strength"] == 0.5
    assert payload["hr_second_pass_steps"] == 10
    assert payload["hr_additional_modules"] == ["Use same choices"]
    assert payload["hr_cfg"] == 7.0


def test_webui_hires_fields_are_txt2img_only():
    service = APIService(app_context=None)
    payload = {"width": 512, "height": 512, "denoising_strength": 0.45}

    service._apply_webui_hires_params(
        payload,
        {"enable_hr": True, "hires_steps": 10, "hr_scale": 3},
        is_img2img=True,
    )

    assert payload == {"width": 512, "height": 512, "denoising_strength": 0.45}
