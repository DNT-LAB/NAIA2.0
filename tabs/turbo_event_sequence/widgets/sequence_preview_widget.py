"""
Sequence Preview Widget

선택된 Parent의 시퀀스 미리보기 및 Tag diff 표시
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QScrollArea, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class SequencePreviewWidget(QWidget):
    """시퀀스 미리보기 위젯"""

    # 시그널
    sequence_confirmed = pyqtSignal(list)  # List of prompt dicts

    def __init__(self, app_context=None, prompt_processor=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.prompt_processor = prompt_processor  # 프롬프트 전처리 콜백
        self.sequence_df = None
        self.prompts = []

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 메인 카드
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(6)

        # 타이틀 + 확정 버튼
        title_layout = QHBoxLayout()
        title = QLabel("📋 시퀀스 미리보기")
        title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16) + 3}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        title_layout.addWidget(title)

        self.info_label = QLabel("시퀀스를 선택하세요")
        self.info_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13) + 3}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        title_layout.addWidget(self.info_label)

        title_layout.addStretch()

        # 확정 버튼 (타이틀 행에 배치)
        self.confirm_btn = QPushButton("✅ 시퀀스 확정")
        self.confirm_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.confirm_btn.clicked.connect(self._on_confirm_clicked)
        self.confirm_btn.setEnabled(False)
        title_layout.addWidget(self.confirm_btn)

        card_layout.addLayout(title_layout)

        # 시퀀스 트리 영역 (스크롤) - 세로 스크롤만, 가로 스크롤 비활성화
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_primary']};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self.tree_container = QWidget()
        self.tree_container.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.tree_layout = QVBoxLayout(self.tree_container)
        self.tree_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tree_layout.setSpacing(4)
        self.tree_layout.setContentsMargins(4, 4, 4, 4)

        # 플레이스홀더
        self.placeholder = QLabel("검색 결과에서 Parent를 선택하면\n시퀀스가 여기에 표시됩니다.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(f"""
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(14) + 3}px;
            padding: {get_scaled_size(20)}px;
            background-color: {DARK_COLORS['bg_primary']};
        """)
        self.tree_layout.addWidget(self.placeholder)

        scroll.setWidget(self.tree_container)
        card_layout.addWidget(scroll, stretch=1)

        layout.addWidget(card)

    def set_sequence(self, sequence_df):
        """시퀀스 설정"""
        self.sequence_df = sequence_df
        self.prompts = []

        # 기존 위젯 클리어
        self._clear_tree()

        if sequence_df is None or len(sequence_df) == 0:
            self.placeholder.show()
            self.info_label.setText("시퀀스를 선택하세요")
            self.confirm_btn.setEnabled(False)
            return

        self.placeholder.hide()

        # Parent 찾기
        parent_row = sequence_df[sequence_df['has_children'] == True]
        if len(parent_row) == 0:
            return

        parent = parent_row.iloc[0]
        parent_tags = set(str(parent.get('general', '')).split(', '))

        # Parent 위젯 추가
        parent_widget = self._create_event_widget(
            event_id=int(parent['id']),
            tags=str(parent.get('general', '')),
            rating=str(parent.get('rating', '')),
            is_parent=True,
            added_tags=None,
            removed_tags=None
        )
        self.tree_layout.addWidget(parent_widget)

        # 프롬프트 추가 (Parent에도 prompt_processor 적용)
        parent_general = str(parent.get('general', ''))
        if self.prompt_processor:
            parent_general = self.prompt_processor(parent_general)
        self.prompts.append({
            'index': 0,
            'id': int(parent['id']),
            'general': parent_general,
            'rating': str(parent.get('rating', '')),  # 🆕 rating 추가
            'is_parent': True
        })

        # Children 찾기 및 표시
        children = sequence_df[sequence_df['has_children'] == False].sort_values('id')
        prev_tags = parent_tags

        for idx, (_, child) in enumerate(children.iterrows()):
            child_tags_str = str(child.get('general', ''))
            child_tags = set(child_tags_str.split(', '))

            # Tag diff 계산
            added = child_tags - prev_tags
            removed = prev_tags - child_tags

            child_widget = self._create_event_widget(
                event_id=int(child['id']),
                tags=child_tags_str,
                rating=str(child.get('rating', '')),
                is_parent=False,
                added_tags=added,
                removed_tags=removed,
                child_index=idx + 1
            )
            self.tree_layout.addWidget(child_widget)

            # 프롬프트 추가 (Child는 prompt_processor 적용)
            processed_tags = child_tags_str
            if self.prompt_processor:
                processed_tags = self.prompt_processor(child_tags_str)

            self.prompts.append({
                'index': idx + 1,
                'id': int(child['id']),
                'general': processed_tags,
                'rating': str(child.get('rating', '')),  # 🆕 rating 추가
                'is_parent': False
            })

            prev_tags = child_tags

        # 정보 업데이트
        self.info_label.setText(f"Parent + {len(children)} Children")
        self.confirm_btn.setEnabled(True)

    def _clear_tree(self):
        """트리 클리어"""
        while self.tree_layout.count():
            item = self.tree_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 플레이스홀더 재추가
        self.placeholder = QLabel("검색 결과에서 Parent를 선택하면\n시퀀스가 여기에 표시됩니다.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(f"""
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(14) + 3}px;
            padding: {get_scaled_size(20)}px;
            background-color: {DARK_COLORS['bg_primary']};
        """)
        self.tree_layout.addWidget(self.placeholder)

    def _create_event_widget(self, event_id, tags, rating, is_parent,
                             added_tags, removed_tags, child_index=None) -> QFrame:
        """이벤트 위젯 생성"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary'] if is_parent else DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['accent_blue'] if is_parent else DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setSpacing(2)
        layout.setContentsMargins(6, 4, 6, 4)

        # 헤더
        header_layout = QHBoxLayout()

        if is_parent:
            prefix = "📌 Parent"
        else:
            prefix = f"└→ Child {child_index}"

        header_label = QLabel(f"{prefix} (ID: {event_id})")
        header_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13) + 3}px;
            font-weight: bold;
            color: {DARK_COLORS['accent_blue'] if is_parent else DARK_COLORS['text_primary']};
        """)
        header_layout.addWidget(header_label)

        rating_label = QLabel(f"[{rating}]")
        rating_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(12) + 3}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        header_layout.addStretch()
        header_layout.addWidget(rating_label)

        layout.addLayout(header_layout)

        # Tag diff (Children만)
        if not is_parent and (added_tags or removed_tags):
            diff_layout = QVBoxLayout()
            diff_layout.setSpacing(2)

            if added_tags:
                added_str = ", ".join(list(added_tags)[:8])
                if len(added_tags) > 8:
                    added_str += f" (+{len(added_tags) - 8})"
                added_label = QLabel(f"+ {added_str}")
                added_label.setWordWrap(True)
                added_label.setStyleSheet(f"""
                    font-size: {get_scaled_font_size(12) + 3}px;
                    color: #4CAF50;
                """)
                diff_layout.addWidget(added_label)

            if removed_tags:
                removed_str = ", ".join(list(removed_tags)[:5])
                if len(removed_tags) > 5:
                    removed_str += f" (+{len(removed_tags) - 5})"
                removed_label = QLabel(f"- {removed_str}")
                removed_label.setWordWrap(True)
                removed_label.setStyleSheet(f"""
                    font-size: {get_scaled_font_size(12) + 3}px;
                    color: #f44336;
                """)
                diff_layout.addWidget(removed_label)

            layout.addLayout(diff_layout)

        # 태그 미리보기 (축약)
        tags_preview = tags[:100] + "..." if len(tags) > 100 else tags
        tags_label = QLabel(tags_preview)
        tags_label.setWordWrap(True)
        tags_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(12) + 3}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        layout.addWidget(tags_label)

        return frame

    def _on_confirm_clicked(self):
        """확정 버튼 클릭"""
        if self.prompts:
            self.sequence_confirmed.emit(self.prompts)

    def get_prompts(self) -> list:
        """현재 프롬프트 목록 반환"""
        return self.prompts
