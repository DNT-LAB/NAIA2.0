"""
Reference Inset Auto-Inject Module

Comic Panel / 레퍼런스 인셋 인페인트 컨텍스트일 때 'reference inset' 태그가
프롬프트에 없으면 자동으로 첫 person 태그(1girl/1boy 등) 직후에 삽입한다.

NAI 가 인페인트 영역 안에 추가 캐릭터를 그려 넣지 않도록 막는 트릭. 수동으로
사용자가 매번 태그를 넣지 않아도 되도록 파이프라인 'final_hookpoint' 에서 주입한다.

트리거 조건 (settings/metadata 중 하나라도 truthy):
- settings['reference_inset_tag_required']  ← reference_inpaint_preprocess 권장값
- settings['cropped_image_request']         ← 마스크 크롭 경로 (Comic Panel 출력)
- metadata['reference_inset']               ← 임의 외부 트리거
"""
from typing import TYPE_CHECKING, Any, Dict

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLabel

from interfaces.base_module import BaseMiddleModule
from ui.theme import DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

if TYPE_CHECKING:
    from core.prompt_context import PromptContext


_PERSON_TAGS = frozenset({
    '1boy', '2boys', '3boys', '4boys', '5boys', '6+boys',
    '1girl', '2girls', '3girls', '4girls', '5girls', '6+girls',
    '1other', '2others', '3others', '4others', '5others', '6+others',
})

_TARGET_TAG = 'reference inset'

_TRIGGER_KEYS = (
    'reference_inset_tag_required',
    'cropped_image_request',
)


class ReferenceInsetAutoInjectModule(BaseMiddleModule):
    """레퍼런스 인셋 컨텍스트에서 'reference inset' 자동 삽입."""

    def __init__(self):
        super().__init__()
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True
        self.ignore_save_load = True   # 단순 토글뿐, 모드별 저장 불필요
        self._enabled_checkbox = None

    # ─── BaseMiddleModule ────────────────────────────────────────
    def get_title(self) -> str:
        return "🩹 레퍼런스 인셋 보호"

    def get_order(self) -> int:
        return 350

    def create_widget(self, parent) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(4),
                                  get_scaled_size(8), get_scaled_size(4))
        layout.setSpacing(get_scaled_size(4))

        self._enabled_checkbox = QCheckBox(
            "Comic Panel / 레퍼런스 인페인트 시 'reference inset' 태그 자동 주입"
        )
        self._enabled_checkbox.setChecked(True)
        self._enabled_checkbox.setStyleSheet(DARK_STYLES.get('dark_checkbox', ''))
        layout.addWidget(self._enabled_checkbox)

        info = QLabel(
            "NAI 가 인페인트 영역에 추가 캐릭터를 그려 넣지 않도록 보호합니다.\n"
            "프롬프트에 'reference inset' 이 이미 있으면 중복 주입하지 않습니다."
        )
        info.setStyleSheet(
            f"color: #999; font-size: {get_scaled_font_size(12)}px;"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.widget = widget
        return widget

    def get_pipeline_hook_info(self) -> Dict[str, Any]:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'final_hookpoint',
            'priority': 90,
        }

    def execute_pipeline_hook(self, context: 'PromptContext') -> 'PromptContext':
        try:
            if not self._is_enabled():
                return context
            if not self._should_inject(context):
                return context
            if self._already_present(context):
                return context
            self._inject_after_first_person_tag(context)
        except Exception as e:
            print(f"⚠️ ReferenceInsetAutoInjectModule hook 실패: {e}")
        return context

    # ─── 헬퍼 ────────────────────────────────────────────────────
    def _is_enabled(self) -> bool:
        if self._enabled_checkbox is None:
            return True
        return bool(self._enabled_checkbox.isChecked())

    def _should_inject(self, context) -> bool:
        # 1) settings 트리거 (생성 시점에 img2img_panel.get_parameters 가 주입)
        s = getattr(context, 'settings', None) or {}
        for k in _TRIGGER_KEYS:
            if s.get(k):
                return True
        # 2) metadata 트리거 (외부에서 임의 주입한 케이스)
        meta = getattr(context, 'metadata', None) or {}
        if meta.get('reference_inset'):
            return True
        # 3) 메인 윈도우의 img2img_panel 상태 직접 조회.
        #    settings 가 비어 있는 미리보기/Estimated Tokens 경로에서도 Comic Panel
        #    이 활성이면 동일하게 트리거되도록 한다.
        try:
            mw = getattr(self.app_context, 'main_window', None) if self.app_context else None
            panel = getattr(mw, 'img2img_panel', None) if mw else None
            if panel is not None and getattr(panel, '_comic_panel_mode', False):
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _already_present(context) -> bool:
        target_lc = _TARGET_TAG.lower()
        for bag_name in ('prefix_tags', 'main_tags', 'postfix_tags'):
            bag = getattr(context, bag_name, None) or []
            for t in bag:
                if isinstance(t, str) and target_lc in t.lower():
                    return True
        return False

    @staticmethod
    def _inject_after_first_person_tag(context) -> None:
        # 1순위: main_tags 첫 person 직후
        main_tags = getattr(context, 'main_tags', None)
        if isinstance(main_tags, list):
            for i, tag in enumerate(main_tags):
                if isinstance(tag, str) and tag in _PERSON_TAGS:
                    main_tags.insert(i + 1, _TARGET_TAG)
                    return
        # 2순위: prefix_tags 첫 person 직후 (캐릭터 모듈 등이 prefix 에 1girl 주입한 경우)
        prefix_tags = getattr(context, 'prefix_tags', None)
        if isinstance(prefix_tags, list):
            for i, tag in enumerate(prefix_tags):
                if isinstance(tag, str) and tag in _PERSON_TAGS:
                    prefix_tags.insert(i + 1, _TARGET_TAG)
                    return
        # 3순위: 폴백 — main_tags 시작
        if isinstance(main_tags, list):
            main_tags.insert(0, _TARGET_TAG)
        elif isinstance(prefix_tags, list):
            prefix_tags.insert(0, _TARGET_TAG)
