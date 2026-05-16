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


def test_webui_hiresfix_assist_maps_square_to_selected_base():
    for target in (512, 768):
        service = APIService(app_context=None)
        payload = {"width": 1024, "height": 1024}

        service._apply_webui_hires_params(
            payload,
            {
                "enable_hr": True,
                "webui_hiresfix_assist": True,
                "webui_hiresfix_assist_target": target,
            },
            is_img2img=False,
        )

        assert payload["width"] == target
        assert payload["height"] == target


def test_webui_hiresfix_assist_uses_64_multiple_ratio_match():
    service = APIService(app_context=None)
    payload = {"width": 832, "height": 1216}

    service._apply_webui_hires_params(
        payload,
        {
            "enable_hr": "true",
            "webui_hiresfix_assist": "true",
            "webui_hiresfix_assist_target": "512",
        },
        is_img2img=False,
    )

    assert payload["width"] == 448
    assert payload["height"] == 640
    assert payload["width"] % 64 == 0
    assert payload["height"] % 64 == 0


def test_webui_hiresfix_assist_reduces_hr_scale_until_final_size_is_safe():
    service = APIService(app_context=None)
    payload = {"width": 832, "height": 1216}

    service._apply_webui_hires_params(
        payload,
        {
            "enable_hr": True,
            "hr_scale": 3.0,
            "webui_hiresfix_assist": True,
            "webui_hiresfix_assist_target": 512,
        },
        is_img2img=False,
    )

    assert payload["width"] == 448
    assert payload["height"] == 640
    assert payload["hr_scale"] == 2.8
    assert round(payload["width"] * payload["hr_scale"]) == 1254
    assert round(payload["height"] * payload["hr_scale"]) == 1792
    assert 1254 * 1792 <= 1536 * 1536


def test_webui_hiresfix_assist_keeps_safe_hr_scale():
    service = APIService(app_context=None)
    payload = {"width": 832, "height": 1216}

    service._apply_webui_hires_params(
        payload,
        {
            "enable_hr": True,
            "hr_scale": 2.7,
            "webui_hiresfix_assist": True,
            "webui_hiresfix_assist_target": 512,
        },
        is_img2img=False,
    )

    assert payload["hr_scale"] == 2.7


def test_webui_hiresfix_assist_requires_hires_enabled():
    service = APIService(app_context=None)
    payload = {"width": 1024, "height": 1024}

    service._apply_webui_hires_params(
        payload,
        {
            "enable_hr": False,
            "webui_hiresfix_assist": True,
            "webui_hiresfix_assist_target": 512,
        },
        is_img2img=False,
    )

    assert payload == {"width": 1024, "height": 1024, "enable_hr": False}


def test_webui_hires_preset_swap_passes_hr_prompts_to_payload():
    service = APIService(app_context=None)
    payload = {"width": 512, "height": 512}

    service._apply_webui_hires_params(
        payload,
        {
            "enable_hr": True,
            "hr_prompt": "best quality, detailed face, sharp focus",
            "hr_negative_prompt": "blurry, soft focus",
        },
        is_img2img=False,
    )

    assert payload["hr_prompt"] == "best quality, detailed face, sharp focus"
    assert payload["hr_negative_prompt"] == "blurry, soft focus"


def test_webui_hires_preset_swap_omits_empty_hr_prompts():
    service = APIService(app_context=None)
    payload = {"width": 512, "height": 512}

    service._apply_webui_hires_params(
        payload,
        {
            "enable_hr": True,
            "hr_prompt": "",
            "hr_negative_prompt": "   ",
        },
        is_img2img=False,
    )

    # 빈 값은 키 자체를 보내지 않아 Forge 가 메인 프롬프트를 그대로 재사용하도록 한다.
    assert "hr_prompt" not in payload
    assert "hr_negative_prompt" not in payload


def test_webui_hires_preset_swap_skipped_when_img2img():
    service = APIService(app_context=None)
    payload = {"width": 512, "height": 512}

    service._apply_webui_hires_params(
        payload,
        {
            "enable_hr": True,
            "hr_prompt": "should not appear",
            "hr_negative_prompt": "should not appear",
        },
        is_img2img=True,
    )

    assert "hr_prompt" not in payload
    assert "hr_negative_prompt" not in payload
