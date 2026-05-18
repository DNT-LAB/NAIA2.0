from types import SimpleNamespace

from core.reference_inset_service import (
    apply_reference_inset_to_prompt_context,
    inject_reference_inset_into_prompt,
    reference_inset_should_inject_params,
    strip_nai_weight_for_match,
)


def test_reference_inset_context_inserts_after_first_person_tag():
    context = SimpleNamespace(
        settings={"reference_inset_tag_required": True},
        metadata={},
        prefix_tags=[],
        main_tags=["solo", "1girl", "looking at viewer"],
        postfix_tags=[],
    )

    apply_reference_inset_to_prompt_context(context)

    assert context.main_tags == ["solo", "1girl", "reference inset", "looking at viewer"]


def test_reference_inset_context_does_not_duplicate_existing_tag():
    context = SimpleNamespace(
        settings={"cropped_image_request": True},
        metadata={},
        prefix_tags=["1girl", "reference inset"],
        main_tags=["solo"],
        postfix_tags=[],
    )

    apply_reference_inset_to_prompt_context(context)

    assert context.prefix_tags == ["1girl", "reference inset"]
    assert context.main_tags == ["solo"]


def test_reference_inset_prompt_preserves_weighted_person_match():
    prompt = "solo, 0.5::1girl ::, looking at viewer"

    assert inject_reference_inset_into_prompt(prompt) == (
        "solo, 0.5::1girl ::, reference inset, looking at viewer"
    )


def test_reference_inset_uses_img2img_panel_state_as_backup_trigger():
    app_context = SimpleNamespace(
        main_window=SimpleNamespace(img2img_panel=SimpleNamespace(_comic_panel_mode=True))
    )

    assert reference_inset_should_inject_params({}, app_context=app_context) is True


def test_strip_nai_weight_for_match_handles_weight_wrappers():
    assert strip_nai_weight_for_match("0.5::1girl ::") == "1girl"
    assert strip_nai_weight_for_match("1girl ::") == "1girl"
