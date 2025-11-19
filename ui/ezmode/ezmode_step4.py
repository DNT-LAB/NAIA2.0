"""
EZ Mode STEP 4: General Tags Recommendation

Co-occurrence Matrix 기반 태그 추천 및 선택
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QScrollArea, QPushButton, QLineEdit, QFrame, QGridLayout,
                              QLayout, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QSize, QPoint
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS, DARK_STYLES
import numpy as np
import pandas as pd
import json
from pathlib import Path
from typing import List, Tuple, Set


class FlowLayout(QLayout):
    """너비 기반 동적 줄바꿈을 지원하는 Flow Layout"""

    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._item_list = []
        self._spacing = spacing

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self._do_layout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        margin = self.contentsMargins().left()
        size += QSize(2 * margin, 2 * margin)
        return size

    def _do_layout(self, rect, test_only):
        """레이아웃 계산 및 적용"""
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._item_list:
            widget = item.widget()
            space_x = spacing
            space_y = spacing

            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y()

    def spacing(self):
        if self._spacing >= 0:
            return self._spacing
        else:
            return self.parent().style().layoutSpacing(
                QSizePolicy.ControlType.PushButton,
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Horizontal
            )


class EZModeStep4(QWidget):
    """STEP 4: General Tags 추천 및 선택 위젯"""

    general_tags_selected = pyqtSignal(list)  # general_tags: List[str]

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.current_category_id = None
        self.current_matrices = None
        self.selected_tags = []  # 사용자가 선택한 태그들
        self.wildcard_tags = set()  # 와일드카드 태그 (매트릭스에 없는 태그)
        self.tag_buttons = {}  # tag -> QPushButton

        # KR_tags 데이터 로드 (툴팁용)
        self.kr_tags_df = pd.DataFrame()
        self._load_kr_tags()

        # 카테고리 그룹 데이터 로드
        self.category_groups = {}  # {"그룹명": [tags]}
        self.category_group_buttons = {}  # {"그룹명": QPushButton}
        self._load_category_groups()

        self.init_ui()
        self.setEnabled(False)  # STEP 3 완료 전까지 비활성화

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(8),
            get_scaled_size(6),
            get_scaled_size(8),
            get_scaled_size(6)
        )
        layout.setSpacing(get_scaled_size(4))

        # 제목
        title_label = QLabel("STEP 4: 태그 선택 및 추천")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(20)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(title_label)

        # 검색 바
        search_layout = QHBoxLayout()
        search_layout.setSpacing(get_scaled_size(8))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("태그 검색... (Enter로 추가)")
        self.search_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.search_input.returnPressed.connect(self._on_search_enter)

        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # 선택된 태그 영역 (복원)
        selected_frame = QFrame()
        selected_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        selected_frame_layout = QVBoxLayout(selected_frame)
        selected_frame_layout.setContentsMargins(
            get_scaled_size(8),
            get_scaled_size(8),
            get_scaled_size(8),
            get_scaled_size(8)
        )
        selected_frame_layout.setSpacing(get_scaled_size(4))

        selected_header = QLabel("선택된 태그:")
        selected_header.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: #F0E68C;
                font-weight: bold;
            }}
        """)
        selected_frame_layout.addWidget(selected_header)

        # 선택된 태그 스크롤 영역 (고정 높이)
        self.selected_scroll = QScrollArea()
        self.selected_scroll.setWidgetResizable(True)
        self.selected_scroll.setFixedHeight(get_scaled_size(150))
        self.selected_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selected_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.selected_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        self.selected_widget = QWidget()
        # FlowLayout 사용 (너비 기반 동적 줄바꿈)
        self.selected_layout = FlowLayout(self.selected_widget, margin=0, spacing=get_scaled_size(4))

        self.selected_scroll.setWidget(self.selected_widget)
        selected_frame_layout.addWidget(self.selected_scroll)

        layout.addWidget(selected_frame)

        # 🆕 카테고리 필터 섹션 추가
        self.category_filter_frame = self._create_category_filter_section()
        layout.addWidget(self.category_filter_frame)

        # 추천 태그 영역
        self.recommend_label = QLabel("추천 태그 (인기 태그):")
        self.recommend_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(self.recommend_label)

        # 추천 태그 스크롤 영역 (고정 높이, 3열 그리드)
        self.recommend_scroll = QScrollArea()
        self.recommend_scroll.setWidgetResizable(True)
        self.recommend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recommend_scroll.setFixedHeight(get_scaled_size(600))  # 16줄 * 30px + spacing
        self.recommend_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        self.recommend_widget = QWidget()
        self.recommend_layout = QGridLayout(self.recommend_widget)  # VBoxLayout → GridLayout
        self.recommend_layout.setSpacing(get_scaled_size(4))
        self.recommend_layout.setContentsMargins(0, 0, 0, 0)

        self.recommend_scroll.setWidget(self.recommend_widget)
        layout.addWidget(self.recommend_scroll)

    def set_context(self, rating: str, person_type: str, person_count: dict, special_tags: list):
        """STEP 3에서 호출: 컨텍스트 설정 및 매트릭스 로드"""
        # STEP 1~3 정보 저장 (추천 시 제외할 태그 추출용)
        self.current_rating = rating
        self.current_person_type = person_type
        self.current_person_count = person_count
        self.current_special_tags = special_tags

        # 카테고리 ID 생성
        category_id = self.data_manager.build_category_id(
            rating, person_type, person_count, special_tags
        )

        self.current_category_id = category_id

        # 매트릭스 로드
        self.current_matrices = self.data_manager.load_matrices(category_id)

        if not self.current_matrices:
            print(f"[ERROR] Failed to load matrices for category: {category_id}")
            self.setEnabled(False)
            return

        # UI 활성화
        self.setEnabled(True)

        # 선택 초기화
        self.selected_tags = []
        self.wildcard_tags.clear()

        # Rating에 따른 자동 와일드카드 태그 추가 (가장 앞에 위치)
        if rating == 'g':
            # General: rating:general
            self.selected_tags.insert(0, 'rating:general')
            self.wildcard_tags.add('rating:general')
            print(f"[OK] Auto-added wildcard tag: rating:general")
        elif rating == 's':
            # Sensitive: rating:sensitive
            self.selected_tags.insert(0, 'rating:sensitive')
            self.wildcard_tags.add('rating:sensitive')
            print(f"[OK] Auto-added wildcard tag: rating:sensitive")
        elif rating == 'q':
            # Questionable: rating:questionable, nsfw (순서대로)
            self.selected_tags.insert(0, 'nsfw')
            self.selected_tags.insert(0, 'rating:questionable')
            self.wildcard_tags.add('rating:questionable')
            self.wildcard_tags.add('nsfw')
            print(f"[OK] Auto-added wildcard tags: rating:questionable, nsfw")
        elif rating == 'e':
            # Explicit: rating:explicit, nsfw (순서대로)
            self.selected_tags.insert(0, 'nsfw')
            self.selected_tags.insert(0, 'rating:explicit')
            self.wildcard_tags.add('rating:explicit')
            self.wildcard_tags.add('nsfw')
            print(f"[OK] Auto-added wildcard tags: rating:explicit, nsfw")

        self._update_selected_tags_display()

        # 초기 추천 (빈 선택 기반)
        self._update_recommendations()

        print(f"[OK] STEP 4 context set: {category_id}")

    def reset_step4_tags(self):
        """STEP4에서 선택한 태그만 초기화하고 rating 기반 자동 태그만 다시 추가"""
        # STEP4 태그 제거
        self.selected_tags = []
        self.wildcard_tags.clear()

        # Rating에 따른 자동 와일드카드 태그만 다시 추가
        rating = self.current_rating if hasattr(self, 'current_rating') else None

        if rating == 'g':
            self.selected_tags.insert(0, 'rating:general')
            self.wildcard_tags.add('rating:general')
        elif rating == 's':
            self.selected_tags.insert(0, 'rating:sensitive')
            self.wildcard_tags.add('rating:sensitive')
        elif rating == 'q':
            self.selected_tags.insert(0, 'nsfw')
            self.selected_tags.insert(0, 'rating:questionable')
            self.wildcard_tags.add('rating:questionable')
            self.wildcard_tags.add('nsfw')
        elif rating == 'e':
            self.selected_tags.insert(0, 'nsfw')
            self.selected_tags.insert(0, 'rating:explicit')
            self.wildcard_tags.add('rating:explicit')
            self.wildcard_tags.add('nsfw')

        # UI 업데이트
        self._update_selected_tags_display()
        self._update_recommendations()
        self.general_tags_selected.emit(self.selected_tags)

        print(f"[OK] STEP 4 tags reset to initial state (rating: {rating})")

    def _on_search_enter(self):
        """검색 입력 Enter 이벤트 (와일드카드 태그 지원)"""
        search_text = self.search_input.text().strip()

        if not search_text:
            return

        # 이미 선택되어 있는지 확인
        if search_text in self.selected_tags:
            print(f"[WARN] Tag already selected: {search_text}")
            self.search_input.clear()
            return

        # 태그 존재 확인
        if search_text in self.data_manager.tag_index:
            # 매트릭스에 존재하는 정상 태그
            self.selected_tags.append(search_text)
            print(f"[OK] Tag added: {search_text}")
        else:
            # 매트릭스에 없는 와일드카드 태그
            self.selected_tags.append(search_text)
            self.wildcard_tags.add(search_text)
            print(f"[OK] Wildcard tag added: {search_text} (not in matrix)")

        # UI 업데이트
        self._update_selected_tags_display()
        self._update_recommendations()
        self.general_tags_selected.emit(self.selected_tags)

        # 검색창 초기화
        self.search_input.clear()

    def _update_selected_tags_display(self):
        """선택된 태그 표시 업데이트 (FlowLayout으로 동적 줄바꿈)"""
        # 기존 위젯 제거
        while self.selected_layout.count():
            item = self.selected_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 태그 버튼 생성 (FlowLayout이 자동으로 너비 기반 줄바꿈 처리)
        for tag in self.selected_tags:
            tag_btn = QPushButton(f"✕ {tag}")
            tag_btn.setProperty('tag', tag)

            # 와일드카드 태그는 보라색 배경으로 표시
            if tag in self.wildcard_tags:
                bg_color = "#9B59B6"  # 보라색 (와일드카드)
            else:
                bg_color = DARK_COLORS['accent_blue']  # 파란색 (일반 태그)

            tag_btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(16)}px;
                    background-color: {bg_color};
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(3)}px;
                    padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['error']};
                }}
            """)
            tag_btn.clicked.connect(self._on_remove_tag)

            # 툴팁 설정 (KR_tags 정보 기반)
            self._set_tag_tooltip(tag_btn, tag)

            self.selected_layout.addWidget(tag_btn)

    def _on_remove_tag(self):
        """선택된 태그 제거 (와일드카드 태그도 함께 제거)"""
        button = self.sender()
        tag = button.property('tag')

        if tag in self.selected_tags:
            self.selected_tags.remove(tag)

            # 와일드카드 태그 세트에서도 제거
            if tag in self.wildcard_tags:
                self.wildcard_tags.remove(tag)
                print(f"[OK] Wildcard tag removed: {tag}")
            else:
                print(f"[OK] Tag removed: {tag}")

            self._update_selected_tags_display()
            self._update_recommendations()
            self.general_tags_selected.emit(self.selected_tags)

    def _update_recommendations(self):
        """추천 태그 업데이트 (3열 그리드 레이아웃)"""
        # 레이블 업데이트
        if self.selected_tags:
            self.recommend_label.setText("추천 태그 (CoOccur + CondProb + PMI) - 0~99:")
        else:
            self.recommend_label.setText("추천 태그 (인기 태그 - Co-occurrence 기반):")

        # 기존 위젯 제거
        while self.recommend_layout.count():
            item = self.recommend_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 추천 태그 계산 (48개)
        recommended_tags = self._get_recommended_tags(top_n=48)

        if not recommended_tags:
            no_recommend_label = QLabel("추천 태그가 없습니다.")
            no_recommend_label.setStyleSheet(f"""
                QLabel {{
                    font-size: {get_scaled_font_size(14)}px;
                    color: {DARK_COLORS['text_secondary']};
                    padding: {get_scaled_size(10)}px;
                }}
            """)
            self.recommend_layout.addWidget(no_recommend_label, 0, 0, 1, 3)  # Span 3 columns
            return

        # 추천 태그 버튼 생성 (3열 그리드)
        row = 0
        col = 0
        max_cols = 3

        for item in recommended_tags:
            # 4-tuple unpacking: (tag, score, cooccur_count, is_boosted)
            if len(item) == 4:
                tag, score, cooccur_count, is_boosted = item
            elif len(item) == 3:
                # fallback for old format (3-tuple)
                tag, score, cooccur_count = item
                is_boosted = False
            else:
                # fallback for legacy format (2-tuple)
                tag, score = item[:2]
                cooccur_count = 0.0
                is_boosted = False

            # 점수 형식 (0-99 정수)
            # ✅ FIX: 0점일 때는 점수 표시 안 함
            int_score = int(score)
            if int_score == 0:
                score_text = ""
            else:
                score_text = f"({int_score})"

            # 점수 기반 색상 결정 (카테고리 부스트 > 고득점 > 일반 > 저득점)
            if is_boosted:
                # 카테고리 부스트된 태그: 연하늘색
                text_color = "#87CEEB"
            elif self.selected_tags and int_score >= 55:
                # Hybrid 모드: 55점 이상 연노랑
                text_color = "#F0E68C"
            elif int_score < 10:
                # ✅ FIX: 0-9점 태그: 회색 (text_secondary)
                text_color = DARK_COLORS['text_secondary']
            else:
                # 일반 태그: 기본 색상
                text_color = DARK_COLORS['text_primary']

            # 버튼 텍스트 생성 (점수가 0이면 공백 없이)
            button_text = f"{tag} {score_text}".strip()
            tag_btn = QPushButton(button_text)
            tag_btn.setProperty('tag', tag)
            tag_btn.setMinimumHeight(get_scaled_size(30))
            tag_btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(18)}px;
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {text_color};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(3)}px;
                    padding: {get_scaled_size(4)}px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                    border-color: {DARK_COLORS['accent_blue']};
                }}
            """)
            tag_btn.clicked.connect(self._on_add_recommended_tag)

            # 툴팁 설정 (KR_tags 정보 기반)
            self._set_tag_tooltip(tag_btn, tag)

            self.recommend_layout.addWidget(tag_btn, row, col)

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def _on_add_recommended_tag(self):
        """추천 태그 클릭 시 선택 목록에 추가"""
        button = self.sender()
        tag = button.property('tag')

        if tag not in self.selected_tags:
            self.selected_tags.append(tag)
            self._update_selected_tags_display()
            self._update_recommendations()
            self.general_tags_selected.emit(self.selected_tags)

            print(f"[OK] Recommended tag added: {tag}")

    def _normalize_tag(self, tag: str) -> List[str]:
        """태그를 정규화하여 언더스코어/공백 양쪽 버전 반환

        Args:
            tag: 원본 태그 (예: 'large_breasts' 또는 'large breasts')

        Returns:
            List[str]: [언더스코어 버전, 공백 버전]
        """
        variants = []
        # 원본 추가
        variants.append(tag)
        # 언더스코어 → 공백
        if '_' in tag:
            variants.append(tag.replace('_', ' '))
        # 공백 → 언더스코어
        if ' ' in tag:
            variants.append(tag.replace(' ', '_'))
        return list(set(variants))  # 중복 제거

    def _extract_tags_from_steps123(self) -> List[str]:
        """STEP 1~3에서 이미 선택된 태그들 추출

        Returns:
            List[str]: 제외할 태그 목록 (person_count, solo, rating, nsfw, special_tags)
                      언더스코어/공백 양쪽 버전 포함
        """
        excluded_tags = []

        # 1. Person Count 태그 (예: '1girl', '2boys', etc.)
        if hasattr(self, 'current_person_count') and self.current_person_count:
            for tag in self.current_person_count.keys():
                excluded_tags.extend(self._normalize_tag(tag))

        # 2. Solo 태그
        if hasattr(self, 'current_person_type') and self.current_person_type == 'solo':
            excluded_tags.extend(self._normalize_tag('solo'))

        # 3. Rating 태그
        if hasattr(self, 'current_rating') and self.current_rating:
            rating_map = {
                'g': 'rating:safe',
                's': 'rating:sensitive',
                'q': 'rating:questionable',
                'e': 'rating:explicit'
            }
            if self.current_rating in rating_map:
                excluded_tags.extend(self._normalize_tag(rating_map[self.current_rating]))

            # NSFW 태그 (rating이 q 또는 e인 경우)
            if self.current_rating in ['q', 'e']:
                excluded_tags.extend(self._normalize_tag('nsfw'))

        # 4. Special Tags (언더스코어/공백 양쪽 버전)
        if hasattr(self, 'current_special_tags') and self.current_special_tags:
            for tag in self.current_special_tags:
                excluded_tags.extend(self._normalize_tag(tag))

        # 중복 제거
        return list(set(excluded_tags))

    def _get_recommended_tags(self, top_n: int = 48) -> List[Tuple[str, float]]:
        """추천 태그 계산 (Hybrid: PMI + Conditional Probability + Co-occurrence)"""
        if not self.current_matrices:
            return []

        tag_index = self.data_manager.tag_index
        index_tag = self.data_manager.index_tag

        # STEP 1~3에서 이미 선택된 태그들 추출
        excluded_tags_from_steps = self._extract_tags_from_steps123()

        # 디버깅: 제외될 태그 출력
        if excluded_tags_from_steps:
            print(f"[DEBUG] Excluded tags from STEP 1~3: {excluded_tags_from_steps}")

        # ✅ FIX: STEP 4 태그가 없어도 STEP 3 태그를 기반으로 Hybrid 추천 계산
        # (기존에는 global popularity만 사용하여 노란색 태그가 없었음)
        # 단, STEP 3 태그도 없으면 인기 태그 반환
        if not self.selected_tags and not excluded_tags_from_steps:
            return self._get_popular_tags(top_n, excluded_tags_from_steps)

        pmi_matrix = self.current_matrices['pmi']
        cond_prob_matrix = self.current_matrices['condprob']  # Key is 'condprob', not 'cond_prob'
        cooccur_matrix = self.current_matrices['cooccur']

        # 선택된 태그들의 인덱스 (STEP 4에서 선택한 태그 + STEP 1~3 태그)
        # 와일드카드 태그는 매트릭스에 없으므로 추천 계산에서 제외
        normal_tags = [tag for tag in self.selected_tags if tag not in self.wildcard_tags]
        all_selected_tags = normal_tags + excluded_tags_from_steps

        # 디버깅: 와일드카드 태그 제외 확인
        if self.wildcard_tags:
            print(f"[DEBUG] Wildcard tags excluded from recommendation: {list(self.wildcard_tags)}")

        selected_indices = []
        not_found_tags = []

        for tag in all_selected_tags:
            # 원본 태그 시도
            if tag in tag_index:
                selected_indices.append(tag_index[tag])
            else:
                # 정규화된 버전 시도
                found = False
                for variant in self._normalize_tag(tag):
                    if variant in tag_index:
                        selected_indices.append(tag_index[variant])
                        found = True
                        break
                if not found:
                    not_found_tags.append(tag)

        # 디버깅: 찾지 못한 태그 출력
        if not_found_tags:
            print(f"[WARNING] Tags not found in index: {not_found_tags}")

        print(f"[DEBUG] Selected indices count: {len(selected_indices)} from {len(all_selected_tags)} tags")

        if not selected_indices:
            print(f"[WARNING] No valid tag indices found, falling back to popular tags")
            return self._get_popular_tags(top_n, excluded_tags_from_steps)

        # Hybrid Score 계산 (개선된 버전)
        # 가중치 재조정: CoOccur 우선 (60%), CondProb (30%), PMI (10%)
        # Co-occurrence가 실제 공동 출현 빈도이므로 가장 신뢰할 수 있음
        alpha_cooccur = 0.70
        alpha_cond = 0.10
        alpha_pmi = 0.20

        # 1. Co-occurrence 점수 (공동 출현 빈도) - 가장 중요
        cooccur_scores = np.zeros(cooccur_matrix.shape[0])
        for idx in selected_indices:
            cooccur_scores += cooccur_matrix[idx, :].toarray().flatten()
        cooccur_scores /= len(selected_indices)

        # 2. Conditional Probability 점수 (조건부 확률)
        cond_scores = np.zeros(cond_prob_matrix.shape[0])
        for idx in selected_indices:
            cond_scores += cond_prob_matrix[idx, :].toarray().flatten()
        cond_scores /= len(selected_indices)

        # 3. PMI 점수 (연관성) - 보조 지표로만 사용
        pmi_scores = np.zeros(pmi_matrix.shape[0])
        for idx in selected_indices:
            pmi_scores += pmi_matrix[idx, :].toarray().flatten()
        pmi_scores /= len(selected_indices)

        # 개선된 정규화: Min-Max Scaling (이상치 영향 감소)
        # Co-occurrence는 최소 빈도 필터링 적용
        min_cooccur_threshold = 2  # 최소 2번 이상 공동 출현한 태그만 고려

        # Co-occurrence 필터링 및 정규화
        cooccur_filtered = cooccur_scores.copy()
        cooccur_filtered[cooccur_filtered < min_cooccur_threshold] = 0
        cooccur_max = cooccur_filtered.max() if cooccur_filtered.max() > 0 else 1.0
        cooccur_min = cooccur_filtered.min()
        cooccur_normalized = (cooccur_filtered - cooccur_min) / (cooccur_max - cooccur_min + 1e-8)

        # Conditional Probability 정규화
        cond_max = cond_scores.max() if cond_scores.max() > 0 else 1.0
        cond_min = cond_scores.min()
        cond_normalized = (cond_scores - cond_min) / (cond_max - cond_min + 1e-8)

        # PMI 정규화 (양수만 고려)
        pmi_positive = np.maximum(pmi_scores, 0)
        pmi_max = pmi_positive.max() if pmi_positive.max() > 0 else 1.0
        pmi_normalized = pmi_positive / (pmi_max + 1e-8)

        # 디버깅: 점수 확인
        print(f"[DEBUG] CoOccur: max={cooccur_max:.2f}, non-zero={np.count_nonzero(cooccur_filtered)}")
        print(f"[DEBUG] CondProb: max={cond_max:.4f}, non-zero={np.count_nonzero(cond_scores)}")
        print(f"[DEBUG] PMI: max={pmi_max:.4f}, non-zero={np.count_nonzero(pmi_positive)}")

        # Hybrid Score (Co-occurrence 중심)
        hybrid_scores = (
            alpha_cooccur * cooccur_normalized +
            alpha_cond * cond_normalized +
            alpha_pmi * pmi_normalized
        )

        # 🆕 3안: 카테고리 필터 가중치 부스트 (1.5x)
        selected_group_tags = self._get_selected_group_tags()
        if selected_group_tags:
            boost_count = 0
            for idx, tag in index_tag.items():
                # 태그 및 정규화 버전 확인
                tag_variants = self._normalize_tag(tag)
                if any(variant in selected_group_tags for variant in tag_variants):
                    hybrid_scores[idx] *= 7.0
                    boost_count += 1

            print(f"[DEBUG] Category filter boost applied to {boost_count} tags")

        # 이미 선택된 태그 제외
        for idx in selected_indices:
            hybrid_scores[idx] = -np.inf

        # 상위 N개 추출
        top_indices = np.argsort(hybrid_scores)[-top_n:][::-1]

        # 디버깅: 상위 태그의 점수 확인
        print(f"[DEBUG] Top 5 hybrid scores: {[f'{hybrid_scores[idx]:.4f}' for idx in top_indices[:5]]}")
        print(f"[DEBUG] Top 5 CoOccur scores: {[f'{cooccur_scores[idx]:.2f}' for idx in top_indices[:5]]}")
        print(f"[DEBUG] Top 5 CondProb scores: {[f'{cond_scores[idx]:.4f}' for idx in top_indices[:5]]}")

        # 태그와 점수 반환 (0-99 스케일 점수)
        # STEP 1~3 태그는 추천에서 제외
        recommended = []
        valid_scores = []

        for idx in top_indices:
            if idx in index_tag and hybrid_scores[idx] > 0:
                tag = index_tag[idx]

                # ✅ FIX: 언더바가 포함된 태그 제외
                if '_' in tag:
                    continue

                # STEP 1~3 태그가 아닌 경우에만 추가 (정규화 버전도 체크)
                tag_variants = self._normalize_tag(tag)
                is_excluded = any(variant in excluded_tags_from_steps for variant in tag_variants)

                if not is_excluded:
                    score = hybrid_scores[idx]
                    cooccur_count = cooccur_scores[idx]

                    # 부스트 여부 체크 (연하늘색 표시용)
                    is_boosted = False
                    if selected_group_tags:
                        is_boosted = any(variant in selected_group_tags for variant in tag_variants)

                    recommended.append((tag, score, cooccur_count, is_boosted))
                    valid_scores.append(score)

        # 점수를 0-99 정수로 변환
        if valid_scores:
            min_score = min(valid_scores)
            max_score = max(valid_scores)
            score_range = max_score - min_score

            # 0-99로 스케일링
            recommended_scaled = []
            for tag, score, cooccur_count, is_boosted in recommended:
                if score_range > 0:
                    scaled_score = int(((score - min_score) / score_range) * 99)
                else:
                    scaled_score = 99  # 모두 같은 점수면 99
                recommended_scaled.append((tag, scaled_score, cooccur_count, is_boosted))

            recommended = recommended_scaled

        print(f"[DEBUG] Final recommended count: {len(recommended)} / {top_n}")

        return recommended

    def _get_popular_tags(self, top_n: int = 20, excluded_tags: List[str] = None) -> List[Tuple[str, float]]:
        """인기 태그 반환 (co-occurrence 합계 기반)

        Args:
            top_n: 반환할 태그 수
            excluded_tags: 제외할 태그 목록 (STEP 1~3에서 이미 선택된 태그)
        """
        if not self.current_matrices:
            return []

        if excluded_tags is None:
            excluded_tags = []

        tag_index = self.data_manager.tag_index
        cooccur_matrix = self.current_matrices['cooccur']
        index_tag = self.data_manager.index_tag

        # Co-occurrence 행 합계 계산 (각 태그가 다른 태그들과 얼마나 자주 등장하는지)
        tag_popularity = np.array(cooccur_matrix.sum(axis=1)).flatten()

        # float 타입으로 변환 (정수 배열에 -inf 할당 불가)
        tag_popularity = tag_popularity.astype(np.float64)

        # 제외할 태그들의 인덱스를 -inf로 설정 (정규화 버전 모두 체크)
        for tag in excluded_tags:
            for variant in self._normalize_tag(tag):
                if variant in tag_index:
                    idx = tag_index[variant]
                    tag_popularity[idx] = -np.inf

        # 상위 N개 추출
        top_indices = np.argsort(tag_popularity)[-top_n:][::-1]

        # 태그와 인기도 반환 (3-tuple for consistency: tag, popularity, pmi=0.0)
        popular = []
        for idx in top_indices:
            if idx in index_tag and tag_popularity[idx] > 0:
                tag = index_tag[idx]
                popularity = tag_popularity[idx]

                # ✅ FIX: 언더바가 포함된 태그 제외
                if '_' in tag:
                    continue

                # 제외 태그가 아닌 경우에만 추가 (정규화 버전도 체크)
                tag_variants = self._normalize_tag(tag)
                is_excluded = any(variant in excluded_tags for variant in tag_variants)

                if not is_excluded:
                    popular.append((tag, popularity, 0.0))  # PMI 없으므로 0.0

        print(f"[DEBUG] Popular tags count: {len(popular)} / {top_n}")

        return popular

    def get_selected_tags(self) -> list:
        """현재 선택된 General Tags 반환"""
        return self.selected_tags

    def reset(self):
        """선택 초기화"""
        self.selected_tags = []
        self.current_category_id = None
        self.current_matrices = None
        self._update_selected_tags_display()
        self._update_recommendations()
        self.setEnabled(False)

    def _load_kr_tags(self):
        """KR_tags.parquet 로드 (툴팁용)"""
        try:
            kr_tags_path = Path("data/KR_tags.parquet")
            if kr_tags_path.exists():
                self.kr_tags_df = pd.read_parquet(kr_tags_path)
                print(f"[OK] KR_tags 로드 완료: {len(self.kr_tags_df)} 태그")
            else:
                print("[WARN] KR_tags.parquet 파일을 찾을 수 없습니다.")
        except Exception as e:
            print(f"[ERROR] KR_tags 로드 실패: {e}")

    def _set_tag_tooltip(self, button: QPushButton, tag: str):
        """태그 버튼에 KR_tags 정보 기반 툴팁 설정

        Args:
            button: 툴팁을 설정할 QPushButton
            tag: 태그 이름
        """
        if self.kr_tags_df.empty:
            return

        # Parquet에서 태그 정보 조회
        matching_rows = self.kr_tags_df[self.kr_tags_df['tag'] == tag]

        if not matching_rows.empty:
            data = matching_rows.iloc[0]

            # 툴팁 텍스트 생성
            tooltip_lines = []

            # 아이템 2: 카테고리
            category_text = data.get('category')
            if pd.notna(category_text) and category_text:
                tooltip_lines.append(f"Category: {category_text}")

            # 아이템 3: 설명
            desc_text = data.get('desc')
            if pd.notna(desc_text) and desc_text:
                tooltip_lines.append(f"{desc_text}")

            # 아이템 4: 키워드
            keywords_text = data.get('keywords')
            if pd.notna(keywords_text) and keywords_text:
                tooltip_lines.append(f"Keywords: {keywords_text}")

            # 툴팁 설정
            if tooltip_lines:
                tooltip = '\n'.join(tooltip_lines)
                button.setToolTip(tooltip)

    def _load_category_groups(self):
        """카테고리 그룹 데이터 로드"""
        try:
            category_path = Path("data/ezmode/category_tags_merged.json")
            if category_path.exists():
                with open(category_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.category_groups = data.get("index", {})
                    print(f"[OK] Category groups loaded: {len(self.category_groups)} groups")
            else:
                print("[WARN] category_tags_merged.json not found, filter disabled")
                self.category_groups = {}
        except Exception as e:
            print(f"[ERROR] Failed to load category groups: {e}")
            self.category_groups = {}

    def _create_category_filter_section(self) -> QWidget:
        """카테고리 필터 섹션 생성 (선택된 태그 공간의 절반 높이)"""
        if not self.category_groups:
            # 데이터 없으면 빈 위젯 반환
            return QWidget()

        filter_frame = QFrame()
        # 선택된 태그 공간(150px)의 절반 = 75px → 95px로 증가 (글씨 잘림 방지)
        filter_frame.setFixedHeight(get_scaled_size(95))
        filter_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-top: 1px solid {DARK_COLORS['border']};
                border-bottom: 1px solid {DARK_COLORS['border']};
            }}
        """)

        layout = QVBoxLayout(filter_frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # 라벨
        label = QLabel("카테고리 부스트:")
        label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        layout.addWidget(label)

        # 2층 구조 레이아웃
        rows_widget = QWidget()
        rows_layout = QVBoxLayout(rows_widget)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(4)

        # 그룹 목록 정렬 (태그 개수 내림차순)
        sorted_groups = sorted(
            self.category_groups.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )

        # 1층: 상위 6개
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(4)
        row1_layout.setContentsMargins(0, 0, 0, 0)

        for i, (group_name, tags) in enumerate(sorted_groups[:6]):
            btn = self._create_category_filter_button(group_name, len(tags))
            row1_layout.addWidget(btn)
            self.category_group_buttons[group_name] = btn

        row1_layout.addStretch()
        rows_layout.addLayout(row1_layout)

        # 2층: 나머지 5개
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(4)
        row2_layout.setContentsMargins(0, 0, 0, 0)

        for i, (group_name, tags) in enumerate(sorted_groups[6:11]):
            btn = self._create_category_filter_button(group_name, len(tags))
            row2_layout.addWidget(btn)
            self.category_group_buttons[group_name] = btn

        row2_layout.addStretch()
        rows_layout.addLayout(row2_layout)

        layout.addWidget(rows_widget)

        return filter_frame

    def _create_category_filter_button(self, group_name: str, tag_count: int) -> QPushButton:
        """카테고리 필터 버튼 생성 (single-select 토글)"""
        btn = QPushButton(f"{group_name} ({tag_count})")
        btn.setCheckable(True)
        btn.setChecked(False)  # 초기: 모두 해제 (전체 표시)
        btn.setFixedHeight(get_scaled_size(26))
        btn.clicked.connect(lambda checked: self._on_category_filter_toggled(group_name, checked))

        # 스타일
        btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(15)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(10)}px;
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border-color: {DARK_COLORS['accent_blue']};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['border_light']};
            }}
            QPushButton:checked:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)

        return btn

    def _on_category_filter_toggled(self, group_name: str, checked: bool):
        """카테고리 필터 토글 이벤트 (라디오 버튼 방식: 한 번에 하나만 선택)"""
        if checked:
            # 체크된 경우: 다른 모든 버튼을 해제
            for other_group, other_btn in self.category_group_buttons.items():
                if other_group != group_name and other_btn.isChecked():
                    other_btn.setChecked(False)
            print(f"[DEBUG] Category filter selected: {group_name}")
        else:
            # 해제된 경우: 모두 해제 (전체 표시)
            print(f"[DEBUG] Category filter cleared: {group_name} (showing all)")

        # 추천 태그 갱신 (필터 적용)
        self._update_recommendations()

    def _get_active_category_filters(self) -> List[str]:
        """현재 활성화된 카테고리 필터 반환"""
        active_filters = []
        for group_name, btn in self.category_group_buttons.items():
            if btn.isChecked():
                active_filters.append(group_name)

        return active_filters

    def _get_selected_group_tags(self) -> Set[str]:
        """선택된 그룹들의 모든 태그를 Set으로 반환"""
        active_filters = self._get_active_category_filters()

        if not active_filters:
            return set()  # 필터 없음 = 전체

        # 선택된 그룹들의 태그 병합
        all_tags = set()
        for group_name in active_filters:
            if group_name in self.category_groups:
                all_tags.update(self.category_groups[group_name])

        return all_tags
