from __future__ import annotations

from typing import Any, Dict


REFERENCE_INSET_TAG = "reference inset"
REFERENCE_INSET_PERSON_TAGS = frozenset(
    {
        "1boy",
        "2boys",
        "3boys",
        "4boys",
        "5boys",
        "6+boys",
        "1girl",
        "2girls",
        "3girls",
        "4girls",
        "5girls",
        "6+girls",
        "1other",
        "2others",
        "3others",
        "4others",
        "5others",
        "6+others",
    }
)
REFERENCE_INSET_TRIGGER_KEYS = (
    "reference_inset_tag_required",
    "cropped_image_request",
)
REFERENCE_INSET_HOOK_INFO = {
    "target_pipeline": "PromptProcessor",
    "hook_point": "final_hookpoint",
    "priority": 90,
}


def reference_inset_should_inject_context(context, app_context=None) -> bool:
    settings = getattr(context, "settings", None) or {}
    for key in REFERENCE_INSET_TRIGGER_KEYS:
        if settings.get(key):
            return True

    metadata = getattr(context, "metadata", None) or {}
    if metadata.get("reference_inset"):
        return True

    return reference_inset_should_inject_params(settings, app_context=app_context)


def reference_inset_context_already_present(context) -> bool:
    target = REFERENCE_INSET_TAG.lower()
    for bag_name in ("prefix_tags", "main_tags", "postfix_tags"):
        bag = getattr(context, bag_name, None) or []
        for tag in bag:
            if isinstance(tag, str) and target in tag.lower():
                return True
    return False


def apply_reference_inset_to_prompt_context(context, app_context=None):
    if not reference_inset_should_inject_context(context, app_context=app_context):
        return context
    if reference_inset_context_already_present(context):
        return context
    inject_reference_inset_into_context(context)
    return context


def inject_reference_inset_into_context(context) -> None:
    main_tags = getattr(context, "main_tags", None)
    if isinstance(main_tags, list):
        for index, tag in enumerate(main_tags):
            if isinstance(tag, str) and tag in REFERENCE_INSET_PERSON_TAGS:
                main_tags.insert(index + 1, REFERENCE_INSET_TAG)
                return

    prefix_tags = getattr(context, "prefix_tags", None)
    if isinstance(prefix_tags, list):
        for index, tag in enumerate(prefix_tags):
            if isinstance(tag, str) and tag in REFERENCE_INSET_PERSON_TAGS:
                prefix_tags.insert(index + 1, REFERENCE_INSET_TAG)
                return

    if isinstance(main_tags, list):
        main_tags.insert(0, REFERENCE_INSET_TAG)
    elif isinstance(prefix_tags, list):
        prefix_tags.insert(0, REFERENCE_INSET_TAG)


def reference_inset_should_inject_params(params: Dict[str, Any], app_context=None) -> bool:
    if params.get("reference_inset_tag_required") or params.get("cropped_image_request"):
        return True
    try:
        main_window = getattr(app_context, "main_window", None) if app_context else None
        panel = getattr(main_window, "img2img_panel", None) if main_window else None
        if panel is not None and getattr(panel, "_comic_panel_mode", False):
            return True
    except Exception:
        pass
    return False


def inject_reference_inset_into_prompt(prompt: str) -> str:
    if not prompt:
        return prompt
    if REFERENCE_INSET_TAG in prompt.lower():
        return prompt

    tokens = [token for token in prompt.split(",")]
    insert_at = None
    for index, raw_token in enumerate(tokens):
        cleaned = strip_nai_weight_for_match(raw_token.strip())
        if cleaned in REFERENCE_INSET_PERSON_TAGS:
            insert_at = index + 1
            break

    if insert_at is None:
        return f"{REFERENCE_INSET_TAG}, {prompt}"

    new_tokens = tokens[:insert_at] + [f" {REFERENCE_INSET_TAG}"] + tokens[insert_at:]
    return ",".join(new_tokens)


def strip_nai_weight_for_match(token: str) -> str:
    value = token.strip()
    while value.endswith("::"):
        value = value[:-2].rstrip()

    separator = value.find("::")
    if separator > 0:
        head = value[:separator].strip()
        try:
            float(head)
            value = value[separator + 2 :].lstrip()
        except ValueError:
            pass
    return value.strip()


class ReferenceInsetAutoInjectHook:
    def __init__(self, app_context=None):
        self.app_context = app_context

    def get_title(self) -> str:
        return "Reference Inset Auto-Inject"

    def get_pipeline_hook_info(self) -> Dict[str, Any]:
        return dict(REFERENCE_INSET_HOOK_INFO)

    def execute_pipeline_hook(self, context):
        try:
            return apply_reference_inset_to_prompt_context(context, app_context=self.app_context)
        except Exception as exc:
            print(f"ReferenceInsetAutoInjectHook failed: {exc}")
            return context
