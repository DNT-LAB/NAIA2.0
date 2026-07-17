from __future__ import annotations

from typing import Any, Dict


# 인셋 마커 태그. Dev0714의 "reference inset"을 "borderless panels"로 교체(사용자
# 지시 2026-07-18). "2koma" 동반 확장은 품질 이슈로 취소 - 단독 태그만 쓴다.
# 튜플 구조(태그별 개별 삽입/검사, 이미 있으면 누락분만 보충)는 유지.
REFERENCE_INSET_TAGS = ("borderless panels",)
# 하위 호환 표기(로그/표시용 조합 문자열)
REFERENCE_INSET_TAG = ", ".join(REFERENCE_INSET_TAGS)
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


def _missing_inset_tags_for_context(context) -> list[str]:
    """컨텍스트 태그백(prefix/main/postfix) 어디에도 없는 인셋 태그 목록.

    와일드카드 전개 관용상 원소 하나가 "2koma, borderless panels"처럼 콤마 결합
    문자열일 수 있어 substring 검사를 유지한다.
    """
    haystack = " , ".join(
        tag.lower()
        for bag_name in ("prefix_tags", "main_tags", "postfix_tags")
        for tag in (getattr(context, bag_name, None) or [])
        if isinstance(tag, str)
    )
    return [tag for tag in REFERENCE_INSET_TAGS if tag not in haystack]


def reference_inset_context_already_present(context) -> bool:
    return not _missing_inset_tags_for_context(context)


def apply_reference_inset_to_prompt_context(context, app_context=None):
    if not reference_inset_should_inject_context(context, app_context=app_context):
        return context
    if reference_inset_context_already_present(context):
        return context
    inject_reference_inset_into_context(context)
    return context


def _person_run_end_index(bag) -> int | None:
    """인물 태그 연속 구간(1boy, 1girl 등)의 마지막 다음 인덱스.

    첫 인물 태그가 아니라 **연속 구간의 끝** 뒤에 삽입해야 여러 인물 프롬프트에서
    "1boy, borderless panels, 1girl"가 아니라 "1boy, 1girl, borderless panels"가
    된다(사용자 지시). 인물 태그가 없으면 None.
    """
    insert_at = None
    for index, tag in enumerate(bag):
        if isinstance(tag, str) and tag in REFERENCE_INSET_PERSON_TAGS:
            insert_at = index + 1
        elif insert_at is not None:
            break
    return insert_at


def inject_reference_inset_into_context(context) -> None:
    # 누락분만 개별 원소로 삽입한다 - 태그백은 "원소=단일 태그" 관용이라 콤마 결합
    # 원소를 새로 만들지 않는다.
    missing = _missing_inset_tags_for_context(context)
    if not missing:
        return

    main_tags = getattr(context, "main_tags", None)
    if isinstance(main_tags, list):
        insert_at = _person_run_end_index(main_tags)
        if insert_at is not None:
            main_tags[insert_at:insert_at] = missing
            return

    prefix_tags = getattr(context, "prefix_tags", None)
    if isinstance(prefix_tags, list):
        insert_at = _person_run_end_index(prefix_tags)
        if insert_at is not None:
            prefix_tags[insert_at:insert_at] = missing
            return

    if isinstance(main_tags, list):
        main_tags[0:0] = missing
    elif isinstance(prefix_tags, list):
        prefix_tags[0:0] = missing


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
    lowered = prompt.lower()
    # 태그별 개별 검사 - 이미 있는 것(예: 벤치 인페인트의 "2koma, borderless panels",
    # 사용자가 직접 넣은 2koma)은 건너뛰고 누락분만 보충한다.
    missing = [tag for tag in REFERENCE_INSET_TAGS if tag not in lowered]
    if not missing:
        return prompt

    tokens = [token for token in prompt.split(",")]
    insert_at = None
    for index, raw_token in enumerate(tokens):
        cleaned = strip_nai_weight_for_match(raw_token.strip())
        if cleaned in REFERENCE_INSET_PERSON_TAGS:
            # 첫 인물 태그가 아니라 연속 구간의 끝 뒤에 삽입한다(사용자 지시):
            # "1boy, 1girl" -> "1boy, 1girl, 2koma, borderless panels".
            insert_at = index + 1
        elif insert_at is not None:
            break

    if insert_at is None:
        return ", ".join(missing) + f", {prompt}"

    new_tokens = tokens[:insert_at] + [f" {tag}" for tag in missing] + tokens[insert_at:]
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
