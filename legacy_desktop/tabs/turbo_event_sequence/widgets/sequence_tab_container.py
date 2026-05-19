"""
Sequence Tab Container Widget

시퀀스 미리보기 및 수정 탭을 포함하는 탭 컨테이너
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt6.QtCore import pyqtSignal

from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

from .sequence_preview_widget import SequencePreviewWidget
from .sequence_edit_widget import SequenceEditWidget

# 자동 삽입 태그 (Child에만 적용)
AUTO_INSERT_TAGS = ["2koma", "comic", "split screen"]
# 인원 태그 키워드
PERSON_KEYWORDS = ["boy", "girl", "other"]


class SequenceTabContainer(QWidget):
    """시퀀스 탭 컨테이너 위젯"""

    # 시그널 (브리징)
    sequence_confirmed = pyqtSignal(list)  # 시퀀스 확정 시그널
    prompts_updated = pyqtSignal(list)  # 프롬프트 수정 시그널
    prompt_engineering_toggled = pyqtSignal(bool)  # 프롬프트 엔지니어링 토글 시그널
    quick_first_page_requested = pyqtSignal(list)  # 🆕 결정 + 첫 페이지 생성
    quick_all_pages_requested = pyqtSignal(list)  # 🆕 결정 + 전체 생성
    close_editing_requested = pyqtSignal()  # 🆕 편집 모드 종료 요청

    # 탭 인덱스 상수
    TAB_PREVIEW = 0
    TAB_EDIT = 1

    def __init__(self, app_context=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 탭 위젯
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QTabBar::tab {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-bottom: none;
                border-top-left-radius: {get_scaled_size(4)}px;
                border-top-right-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                margin-right: {get_scaled_size(2)}px;
                font-size: {get_scaled_font_size(13) + 3}px;
            }}
            QTabBar::tab:selected {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)

        # 수정 탭 (먼저 생성하여 prompt_processor로 사용)
        self.edit_widget = SequenceEditWidget(app_context=self.app_context)
        self.edit_widget.prompts_updated.connect(self._on_prompts_updated)
        self.edit_widget.prompt_engineering_toggled.connect(self._on_prompt_engineering_toggled)
        self.edit_widget.close_editing_requested.connect(self._on_close_editing_requested)

        # 미리보기 탭 (edit_widget.apply_prompt_engineering을 prompt_processor로 전달)
        self.preview_widget = SequencePreviewWidget(
            app_context=self.app_context,
            prompt_processor=self.edit_widget.apply_prompt_engineering
        )
        self.preview_widget.sequence_confirmed.connect(self._on_sequence_confirmed)
        self.preview_widget.quick_first_page_requested.connect(self._on_quick_first_page)
        self.preview_widget.quick_all_pages_requested.connect(self._on_quick_all_pages)
        self.tab_widget.addTab(self.preview_widget, "📋 미리보기")
        self.tab_widget.addTab(self.edit_widget, "✏️ 수정")

        layout.addWidget(self.tab_widget)

    def set_sequence(self, sequence_df):
        """시퀀스 설정 (미리보기 탭에)"""
        self.preview_widget.set_sequence(sequence_df)
        # 자동으로 미리보기 탭으로 이동
        self.tab_widget.setCurrentIndex(self.TAB_PREVIEW)

    def _on_sequence_confirmed(self, prompts: list):
        """시퀀스 확정 시"""
        # Child에만 자동 삽입 태그 적용 (Parent 제외)
        processed_prompts = self._preprocess_prompts(prompts)
        # 수정 탭에 프롬프트 설정
        self.edit_widget.set_prompts(processed_prompts)
        # 자동으로 수정 탭으로 이동
        self.tab_widget.setCurrentIndex(self.TAB_EDIT)
        # 시그널 브리징
        self.sequence_confirmed.emit(processed_prompts)

    def _on_quick_first_page(self, prompts: list):
        """🆕 ⏩ 버튼 - 결정 + 첫 페이지 생성"""
        processed_prompts = self._preprocess_prompts(prompts)
        self.edit_widget.set_prompts(processed_prompts)
        self.tab_widget.setCurrentIndex(self.TAB_EDIT)
        # 빠른 생성 시그널 발생
        self.quick_first_page_requested.emit(processed_prompts)

    def _on_quick_all_pages(self, prompts: list):
        """🆕 ⏭ 버튼 - 결정 + 전체 생성"""
        processed_prompts = self._preprocess_prompts(prompts)
        self.edit_widget.set_prompts(processed_prompts)
        self.tab_widget.setCurrentIndex(self.TAB_EDIT)
        # 빠른 생성 시그널 발생
        self.quick_all_pages_requested.emit(processed_prompts)

    def confirm_current_sequence(self) -> bool:
        """미리보기 탭의 현재 프롬프트를 확정 처리"""
        prompts = self.preview_widget.get_prompts()
        if not prompts:
            return False
        self._on_sequence_confirmed(prompts)
        return True

    def _preprocess_prompts(self, prompts: list) -> list:
        """프롬프트 전처리 - Child에만 자동 삽입 태그 적용

        Parent(index 0)는 제외하고, Child들에만 인원 태그 뒤에
        "2koma, comic, variant set" 을 삽입합니다.
        """
        processed = []

        for i, prompt_data in enumerate(prompts):
            prompt_copy = prompt_data.copy()

            # Parent(index 0)는 건너뜀
            if prompt_data.get('is_parent', False) or i == 0:
                prompt_copy['auto_inserted_tags'] = set()
                processed.append(prompt_copy)
                continue

            # Child 처리
            general_text = prompt_data.get('general', '')
            tags = [t.strip() for t in general_text.split(',')]

            # 첫 3개 태그에서 인원 태그 위치 찾기
            last_person_idx = -1
            for idx in range(min(3, len(tags))):
                tag_lower = tags[idx].lower()
                for keyword in PERSON_KEYWORDS:
                    if keyword in tag_lower:
                        last_person_idx = idx
                        break

            # 인원 태그 뒤에 자동 삽입 태그 추가
            if last_person_idx >= 0:
                # 이미 존재하는 태그는 제외
                existing_tags = set(t.strip().lower() for t in tags)
                tags_to_insert = [t for t in AUTO_INSERT_TAGS
                                  if t.lower() not in existing_tags]

                if tags_to_insert:
                    # 삽입 위치 계산
                    insert_pos = last_person_idx + 1
                    new_tags = tags[:insert_pos] + tags_to_insert + tags[insert_pos:]
                    prompt_copy['general'] = ', '.join(new_tags)
                    prompt_copy['auto_inserted_tags'] = set(tags_to_insert)
                else:
                    prompt_copy['auto_inserted_tags'] = set()
            else:
                prompt_copy['auto_inserted_tags'] = set()

            processed.append(prompt_copy)

        return processed

    def _on_prompts_updated(self, prompts: list):
        """프롬프트 수정 시"""
        self.prompts_updated.emit(prompts)

    def _on_prompt_engineering_toggled(self, checked: bool):
        """프롬프트 엔지니어링 토글 시"""
        self.prompt_engineering_toggled.emit(checked)

    def _on_close_editing_requested(self):
        """편집 모드 종료 요청 시"""
        print("[SequenceTabContainer] 편집 모드 종료 요청 - 상위로 시그널 전달")
        self.close_editing_requested.emit()

    def switch_to_preview(self):
        """미리보기 탭으로 전환"""
        self.tab_widget.setCurrentIndex(self.TAB_PREVIEW)

    def switch_to_edit(self):
        """수정 탭으로 전환"""
        self.tab_widget.setCurrentIndex(self.TAB_EDIT)

    def set_highlight_index(self, index: int):
        """현재 생성 중인 인덱스 하이라이트"""
        self.edit_widget.set_highlight_index(index)

    def clear_highlight(self):
        """하이라이트 제거"""
        self.edit_widget.clear_highlight()

    def get_prompts(self) -> list:
        """현재 프롬프트 목록 반환"""
        return self.edit_widget.get_prompts()

    def get_preview_prompts(self) -> list:
        """미리보기 위젯의 프롬프트 목록 반환"""
        return self.preview_widget.get_prompts()

    def expand_prompt_editors(self):
        """프롬프트 편집기를 확대 모드로 전환 (편집 모드)"""
        print("[SequenceTabContainer] 프롬프트 편집기 확대 모드 활성화")
        self.edit_widget.set_expanded_mode(True)

    def restore_prompt_editors(self):
        """프롬프트 편집기를 원래 크기로 복원 (검색 모드)"""
        print("[SequenceTabContainer] 프롬프트 편집기 일반 모드 복원")
        self.edit_widget.set_expanded_mode(False)
