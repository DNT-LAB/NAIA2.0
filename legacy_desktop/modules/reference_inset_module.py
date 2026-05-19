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
from core.reference_inset_service import (
    REFERENCE_INSET_HOOK_INFO,
    apply_reference_inset_to_prompt_context,
)
from legacy_desktop.ui.theme import DARK_STYLES
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

if TYPE_CHECKING:
    from core.prompt_context import PromptContext


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
        return dict(REFERENCE_INSET_HOOK_INFO)

    def execute_pipeline_hook(self, context: 'PromptContext') -> 'PromptContext':
        try:
            if not self._is_enabled():
                return context
            return apply_reference_inset_to_prompt_context(context, app_context=self.app_context)
        except Exception as e:
            print(f"⚠️ ReferenceInsetAutoInjectModule hook 실패: {e}")
        return context

    # ─── 헬퍼 ────────────────────────────────────────────────────
    def _is_enabled(self) -> bool:
        if self._enabled_checkbox is None:
            return True
        return bool(self._enabled_checkbox.isChecked())
