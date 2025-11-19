"""
EZ Mode Controller

좌측 컨트롤러 패널 - STEP 1~4를 포함
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QFrame, QPushButton
from PyQt6.QtCore import pyqtSignal, Qt
from ui.theme import get_dynamic_styles, DARK_COLORS
from ui.scaling_manager import get_scaled_size, get_scaled_font_size
from ui.ezmode.ezmode_step1 import EZModeStep1
from ui.ezmode.ezmode_step2 import EZModeStep2
from ui.ezmode.ezmode_step3 import EZModeStep3
from ui.ezmode.ezmode_step4 import EZModeStep4
import pandas as pd


class EZModeController(QWidget):
    """EZ Mode 좌측 컨트롤러 패널"""

    tags_updated = pyqtSignal(dict)  # 전체 선택된 태그 정보
    instant_generation_requested = pyqtSignal(object)  # 즉시 생성 요청: pandas.Series (virtual row)

    def __init__(self, data_manager, app_context, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.app_context = app_context

        # 현재 상태
        self.current_rating = None
        self.current_person_type = None
        self.current_person_count = {}
        self.current_special_tags = []
        self.current_general_tags = []

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        # 메인 레이아웃
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(get_scaled_size(5), get_scaled_size(5),
                                       get_scaled_size(5), get_scaled_size(5))
        main_layout.setSpacing(0)

        # 스크롤 영역 (STEP3 자동 스크롤을 위해 참조 저장)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 스크롤 컨텐츠
        scroll_content = QWidget()
        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setSpacing(get_scaled_size(2))  # 여백 축소 (8 → 2)

        # STEP 1: Rating 선택
        self.step1 = EZModeStep1()
        self.step1.rating_selected.connect(self._on_rating_selected)
        self.content_layout.addWidget(self.step1)

        # 구분선
        separator1 = self._create_separator()
        self.content_layout.addWidget(separator1)

        # STEP 2: Person Count 선택
        self.step2 = EZModeStep2(self.data_manager)
        self.step2.person_count_selected.connect(self._on_person_count_selected)
        self.content_layout.addWidget(self.step2)

        # 구분선
        separator2 = self._create_separator()
        self.content_layout.addWidget(separator2)

        # STEP 3: Special Tags 선택
        self.step3 = EZModeStep3(self.data_manager)
        self.step3.special_tags_selected.connect(self._on_special_tags_selected)
        self.content_layout.addWidget(self.step3)

        # 구분선
        separator3 = self._create_separator()
        self.content_layout.addWidget(separator3)

        # STEP 4: General Tags 추천 (자동 높이)
        self.step4 = EZModeStep4(self.data_manager)
        self.step4.general_tags_selected.connect(self._on_general_tags_selected)
        self.content_layout.addWidget(self.step4)

        # addStretch 제거 - STEP 4가 자동 높이를 가짐

        self.scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self.scroll_area)

        # 하단 고정 프레임 (항상 표시)
        bottom_frame = QFrame()
        bottom_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-top: 2px solid {DARK_COLORS['border']};
            }}
        """)
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(
            get_scaled_size(8),
            get_scaled_size(8),
            get_scaled_size(8),
            get_scaled_size(8)
        )
        bottom_layout.setSpacing(get_scaled_size(8))

        # 선택된 태그 수 라벨
        self.selected_count_label = QLabel("선택된 태그: 0개")
        self.selected_count_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: #F0E68C;
                font-weight: bold;
            }}
        """)
        bottom_layout.addWidget(self.selected_count_label)

        bottom_layout.addStretch()

        # 초기화 버튼
        self.reset_step4_btn = QPushButton("초기화")
        self.reset_step4_btn.setMinimumHeight(get_scaled_size(40))
        self.reset_step4_btn.setEnabled(False)  # 초기 비활성화
        self.reset_step4_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(16)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.reset_step4_btn.clicked.connect(self._on_reset_step4)
        bottom_layout.addWidget(self.reset_step4_btn)

        # 즉시 생성 버튼
        self.instant_generate_btn = QPushButton("즉시 생성")
        self.instant_generate_btn.setMinimumHeight(get_scaled_size(40))
        self.instant_generate_btn.setEnabled(False)  # 초기 비활성화
        self.instant_generate_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                background-color: {DARK_COLORS['warning']};
                color: white;
                border: none;
                border-radius: {get_scaled_size(5)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(20)}px;
            }}
            QPushButton:hover {{
                background-color: #FFA500;
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.instant_generate_btn.clicked.connect(self._on_instant_generate)
        bottom_layout.addWidget(self.instant_generate_btn)

        main_layout.addWidget(bottom_frame)

        # 스타일 적용
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #2a2a2a;
            }}
            QScrollArea {{
                border: none;
                background-color: #2a2a2a;
            }}
        """)

    def _create_separator(self) -> QWidget:
        """구분선 생성"""
        separator = QWidget()
        separator.setFixedHeight(get_scaled_size(1))
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        return separator

    def _create_placeholder(self, text: str) -> QLabel:
        """플레이스홀더 레이블 생성"""
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(18)}px;
                color: {DARK_COLORS['text_disabled']};
                padding: {get_scaled_size(20)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        return label

    def _scroll_to_step3(self):
        """STEP3의 레이블이 최대한 위로 오도록 자동 스크롤"""
        if not hasattr(self, 'scroll_area') or not hasattr(self, 'step3'):
            return

        # STEP3 위젯의 y 위치 계산
        step3_y = self.step3.mapTo(self.scroll_area.widget(), self.step3.rect().topLeft()).y()

        # 스크롤 바의 현재 위치를 STEP3의 y 위치로 설정
        # 약간의 오프셋을 빼서 STEP3 레이블이 최대한 위로 오도록 함
        self.scroll_area.verticalScrollBar().setValue(step3_y - get_scaled_size(10))

        print(f"[DEBUG] Scrolled to STEP3 (y={step3_y})")

    def _on_rating_selected(self, rating: str):
        """STEP 1: Rating 선택 이벤트"""
        # STEP4가 활성화된 상태에서 rating이 변경되면 초기화 확인
        if hasattr(self, 'current_rating') and self.current_rating and self.current_rating != rating:
            if hasattr(self, 'step4') and self.step4.isEnabled():
                from PyQt6.QtWidgets import QMessageBox

                # 확인 다이얼로그
                reply = QMessageBox.question(
                    self,
                    "Rating 변경 확인",
                    f"Rating을 변경하면 STEP 2~4의 모든 선택이 초기화됩니다.\n\n"
                    f"현재: {self.current_rating.upper()} → 변경: {rating.upper()}\n\n"
                    f"계속하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )

                if reply == QMessageBox.StandardButton.No:
                    # 취소 - STEP1의 선택을 이전 rating으로 되돌림 (시그널 발행 없이)
                    self.step1.set_rating(self.current_rating)
                    print(f"[Controller] Rating change cancelled, reverted to {self.current_rating}")
                    return

                # 확인 - STEP 2, 3, 4 초기화
                print(f"[Controller] Rating changed: {self.current_rating} → {rating}, resetting STEP 2~4")
                self._reset_steps_234()

        self.current_rating = rating

        # STEP 2 활성화
        self.step2.set_rating(rating)

        # 태그 업데이트 발행
        self.emit_tags_update()

        print(f"[Controller] Rating selected: {rating}, STEP 2 activated")

    def _on_person_count_selected(self, person_type: str, person_count: dict):
        """STEP 2: Person Count 선택 이벤트"""
        self.current_person_type = person_type
        self.current_person_count = person_count

        # 태그 업데이트 발행
        self.emit_tags_update()

        print(f"[Controller] Person count selected: {person_type}, {person_count}")

        # STEP 3 활성화
        self.step3.set_context(self.current_rating, self.current_person_type, self.current_person_count)

    def _on_special_tags_selected(self, special_tags: list):
        """STEP 3: Special Tags 선택 이벤트"""
        self.current_special_tags = special_tags

        # 태그 업데이트 발행
        self.emit_tags_update()

        print(f"[Controller] Special tags selected: {special_tags}")

        # 🆕 STEP3의 레이블이 최대한 위로 오도록 자동 스크롤
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._scroll_to_step3())

        # STEP 4 활성화
        self.step4.set_context(
            self.current_rating,
            self.current_person_type,
            self.current_person_count,
            self.current_special_tags
        )

        # 초기화 버튼 활성화
        self.reset_step4_btn.setEnabled(True)

    def _on_general_tags_selected(self, general_tags: list):
        """STEP 4: General Tags 선택 이벤트"""
        self.current_general_tags = general_tags

        # 🔍 디버깅: 태그 저장 확인
        print(f"[DEBUG] _on_general_tags_selected 호출:")
        print(f"  - 받은 태그 개수: {len(general_tags)}")
        print(f"  - self.current_general_tags 저장 완료: {len(self.current_general_tags)}개")
        print(f"  - id(general_tags): {id(general_tags)}")
        print(f"  - id(self.current_general_tags): {id(self.current_general_tags)}")

        # 하단 라벨 업데이트
        count = len(general_tags)
        self.selected_count_label.setText(f"선택된 태그: {count}개")

        # 즉시 생성 버튼 활성화 상태 업데이트
        self.instant_generate_btn.setEnabled(count > 0)

        # 태그 업데이트 발행
        self.emit_tags_update()

        print(f"[Controller] General tags selected: {general_tags}")

    def _on_instant_generate(self):
        """즉시 생성 버튼 클릭 - 가상 row 생성하여 Main UI에 태그 할당"""
        if not self.current_general_tags:
            print("[WARN] No tags selected for instant generation")
            return

        # 🔍 디버깅: 즉시 생성 버튼 클릭 시점 확인
        print(f"[DEBUG] _on_instant_generate 호출:")
        print(f"  - self.current_general_tags: {len(self.current_general_tags)}개 태그")
        print(f"  - id(self.current_general_tags): {id(self.current_general_tags)}")
        print(f"  - 전체 리스트: {self.current_general_tags}")

        # 🆕 PromptEngineeringModule Auto Hide만 일시적으로 비활성화 (선행/후행 프롬프트는 유지)
        if self.app_context:
            self.app_context.skip_prompt_engineering_auto_hide = True
            print(f"[EZ Mode] ✅ skip_prompt_engineering_auto_hide = True 설정 (Auto Hide만 무효화, 고정 프롬프트 유지)")

        # 가상 row (pandas Series) 생성
        virtual_row = self._create_virtual_row()

        # 상위로 시그널 전달 (MainWindow로)
        print(f"🚀 [Controller] Instant generation requested with virtual row")
        self.instant_generation_requested.emit(virtual_row)

    def _create_virtual_row(self) -> pd.Series:
        """EZ Mode에서 선택된 태그들로 가상 pandas Series 생성

        Returns:
            pd.Series: Web View와 동일한 형식의 가상 row
        """
        # 🔍 디버깅: 현재 저장된 태그 확인
        print(f"[DEBUG] _create_virtual_row 시작:")
        print(f"  - current_general_tags: {self.current_general_tags}")
        print(f"  - current_special_tags: {self.current_special_tags}")
        print(f"  - current_person_count: {self.current_person_count}")

        # 모든 선택된 태그 수집
        all_tags = []

        # STEP 2: Person Count 태그
        if self.current_person_count:
            all_tags.extend(self.current_person_count.keys())

        # STEP 3: Special Tags
        if self.current_special_tags:
            all_tags.extend(self.current_special_tags)

        # STEP 4: General Tags
        if self.current_general_tags:
            all_tags.extend(self.current_general_tags)

        # 쉼표로 구분된 태그 문자열 생성
        tags_string = ', '.join(all_tags)

        # 🔍 디버깅: 생성된 태그 문자열 확인
        print(f"[DEBUG] tags_string 생성:")
        print(f"  - all_tags 개수: {len(all_tags)}")
        print(f"  - tags_string: '{tags_string}'")

        # Rating 매핑 (g/s/q/e → rating:safe/sensitive/questionable/explicit)
        rating_map = {
            'g': 'rating:safe',
            's': 'rating:sensitive',
            'q': 'rating:questionable',
            'e': 'rating:explicit'
        }
        rating_tag = rating_map.get(self.current_rating, '')

        # pandas Series 생성 (Web View와 동일한 구조)
        virtual_row = pd.Series({
            'general': tags_string,  # 모든 태그
            'character': '',  # EZ Mode에서는 character 따로 분리하지 않음
            'meta': rating_tag,  # rating 태그
            'copyright': '',
            'artist': '',
            'rating': self.current_rating if self.current_rating else 'g',  # g/s/q/e
            'id': 0,  # 가상 ID
            'created_at': '',
            'uploader_id': 0,
            'score': 0,
            'source': 'EZ Mode',  # 출처 표시
            'md5': '',
            'file_ext': '',
            'file_size': 0,
            'image_width': 0,
            'image_height': 0,
            'parent_id': None,
            'has_children': False,
            'is_deleted': False,
            'is_banned': False,
            'pixiv_id': None,
            'has_active_children': False,
            'bit_flags': 0,
            'has_large': False,
            'has_visible_children': False,
            'is_favorited': False,
            'tag_string': tags_string,
            'pool_string': '',
            'up_score': 0,
            'down_score': 0,
            'is_pending': False,
            'is_flagged': False,
            'is_note_locked': False,
            'is_rating_locked': False,
            'is_status_locked': False,
            'approver_id': None,
            'tag_count_general': len(self.current_general_tags) if self.current_general_tags else 0,
            'tag_count_artist': 0,
            'tag_count_character': 0,
            'tag_count_copyright': 0,
            'tag_count_meta': 1 if rating_tag else 0,
            'file_url': '',
            'large_file_url': '',
            'preview_file_url': ''
        })

        print(f"[DEBUG] Virtual row created:")
        print(f"  - Rating: {self.current_rating}")
        print(f"  - Person Count: {list(self.current_person_count.keys()) if self.current_person_count else []}")
        print(f"  - Special Tags: {self.current_special_tags}")
        print(f"  - General Tags ({len(self.current_general_tags)}): {self.current_general_tags[:5]}...")
        print(f"  - Total tags: {len(all_tags)}")
        print(f"  - 🔍 Virtual Row general 필드: '{virtual_row['general']}'")

        return virtual_row

    def _on_reset_step4(self):
        """초기화 버튼 클릭 - STEP4 태그만 초기화"""
        if not hasattr(self, 'step4'):
            return

        # STEP4 태그 초기화
        self.step4.reset_step4_tags()

        # current_general_tags도 초기화 (rating 기반 자동 태그만 남김)
        self.current_general_tags = self.step4.selected_tags.copy()

        # 하단 라벨 업데이트
        count = len(self.current_general_tags)
        self.selected_count_label.setText(f"선택된 태그: {count}개")

        # 즉시 생성 버튼 활성화 상태 업데이트
        self.instant_generate_btn.setEnabled(count > 0)

        print(f"[Controller] STEP 4 tags reset, remaining: {count}개")

    def _reset_steps_234(self):
        """STEP 2, 3, 4 모두 초기화"""
        # STEP 2 비활성화
        if hasattr(self, 'step2'):
            self.step2.setEnabled(False)
            self.current_person_type = None
            self.current_person_count = {}

        # STEP 3 비활성화
        if hasattr(self, 'step3'):
            self.step3.setEnabled(False)
            self.current_special_tags = []

        # STEP 4 비활성화
        if hasattr(self, 'step4'):
            self.step4.setEnabled(False)
            self.current_general_tags = []

        # 하단 프레임 초기화
        self.selected_count_label.setText("선택된 태그: 0개")
        self.instant_generate_btn.setEnabled(False)
        self.reset_step4_btn.setEnabled(False)

        print("[Controller] STEP 2~4 reset completed")

    def emit_tags_update(self):
        """선택된 모든 태그 정보를 발행"""
        tags_info = {
            'rating': self.current_rating,
            'person_type': self.current_person_type,
            'person_count': self.current_person_count,
            'special_tags': self.current_special_tags,
            'general_tags': self.current_general_tags
        }

        self.tags_updated.emit(tags_info)
