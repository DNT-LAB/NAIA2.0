"""
Tag Viewer Widget - 3단 구조의 재사용 가능한 태그 뷰어

특정 대분류/소분류만 표시하도록 필터링 가능합니다.
메인 프롬프트, 캐릭터 프롬프트 등 여러 블록에서 재사용할 수 있습니다.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QLabel,
    QListWidgetItem, QTextEdit, QTextBrowser, QStyle, QStyledItemDelegate,
    QApplication, QLineEdit, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QPoint, QRect, QTimer
from PyQt6.QtGui import QColor, QTextCursor

from legacy_desktop.ui.interactive.interactive_theme import COMMON_STYLES, FONT_FAMILY
from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_size, get_scaled_font_size


class TagListDelegate(QStyledItemDelegate):
    """태그 리스트 커스텀 델리게이트 (우측 정렬 숫자 표시)"""
    def paint(self, painter, option, index):
        painter.save()
        
        # 폰트 설정 (아이템에 설정된 QFont 적용)
        painter.setFont(option.font)
        
        # 1. 배경 그리기
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(COMMON_STYLES['input_focus']))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#3A3A3A"))
            
        rect = option.rect
        # UserRole에 저장된 태그명 사용 (setText된 값과 동일)
        tag = index.data(Qt.ItemDataRole.UserRole)
        # UserRole+2에 저장된 카운트 텍스트
        count_text = index.data(Qt.ItemDataRole.UserRole + 2)
        
        # 2. 텍스트 색상 설정
        if option.state & QStyle.StateFlag.State_Selected:
            text_color = QColor(Qt.GlobalColor.white)
            count_color = QColor(Qt.GlobalColor.white)
        else:
            text_color = QColor(COMMON_STYLES['text_primary'])
            count_color = QColor(COMMON_STYLES['text_secondary']) # 연회색 (덜 거슬리게)
            
        # 3. 태그 그리기 (좌측 정렬)
        painter.setPen(text_color)
        # 좌측 패딩 5px, 우측 패딩 60px (숫자 영역 확보)
        tag_rect = rect.adjusted(get_scaled_size(5), 0, -get_scaled_size(60), 0)
        # 엘리시스 처리 (너무 길면 ...)
        text = painter.fontMetrics().elidedText(tag, Qt.TextElideMode.ElideRight, tag_rect.width())
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        
        # 4. 숫자 그리기 (우측 정렬)
        if count_text:
            painter.setPen(count_color)
            # 우측 패딩 5px
            count_rect = rect.adjusted(0, 0, -get_scaled_size(5), 0)
            painter.drawText(count_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count_text)
            
        painter.restore()

    def sizeHint(self, option, index):
        # 기본 높이보다 조금 더 여유있게
        size = super().sizeHint(option, index)
        size.setHeight(get_scaled_size(24))
        return size


class TagViewerWidget(QWidget):
    """
    메인 프롬프트용 3단 태그 뷰어 (좌우 분할 구조)

    구조:
    ┌─────────────────────────────────┬──────────┐
    │  대분류 │ 소분류 │ 태그          │         │
    ├─────────────────────────────────┤  연관   │
    │          검색 영역                │  태그   │
    ├─────────────────────────────────┤         │
    │          설명 영역                │         │
    └─────────────────────────────────┴──────────┘
    """

    tag_selected = pyqtSignal(str)  # 태그 선택 시그널
    quick_search_requested = pyqtSignal(str) # 퀵 서치 요청 시그널

    # 🆕 소분류 한글 번역 맵 (클래스 상수)
    SUBGROUP_KR_MAP = {
        # ===== Clothing_Wear =====
        "accessories": "액세서리",
        "armor": "갑옷/방어구",
        "attire": "의복",
        "bra": "브라",
        "clothes": "의류",
        "cosmetics": "화장품",
        "costume_props": "코스튬 소품",
        "covering": "가리개",
        "design_elements": "디자인 요소",
        "dress_actions": "의복 상태",
        "eyewear": "안경류",
        "face_accessories": "얼굴 액세서리",
        "fashion_style": "패션 스타일",
        "footwear": "신발류",
        "hair_accessories": "머리 액세서리",
        "handwear": "장갑류",
        "headwear": "모자류",
        "legwear": "다리 착용",
        "mask": "마스크",
        "medical": "의료용품",
        "neck_and_neckwear": "목/넥웨어",
        "panties": "팬티",
        "patterns": "패턴/무늬",
        "piercings": "피어싱",
        "prints": "프린트",
        "sexual_attire": "성적 의복",
        "shoulders": "어깨",
        "sleeves": "소매",
        "states": "상태",
        "tan_marks": "태닝 자국",
        "underwear": "속옷",

        # ===== Composition_Meta =====
        "alternate": "대체/변형",
        "art_style": "아트 스타일",
        "body_meta": "신체 메타",
        "censoring": "검열",
        "clothing_state": "의복 상태",
        "colors": "색상",
        "composition": "구도",
        "count": "인원수",
        "cropping": "크롭",
        "effects": "효과",
        "face_meta": "얼굴 메타",
        "focus": "포커스",
        "focus_tags": "포커스 태그",
        "framing": "프레이밍",
        "image_composition": "이미지 구도",
        "lighting": "조명",
        "meta": "메타",
        "metatags": "메타태그",
        "perspective": "시점",
        "quality": "품질",
        "scan": "스캔",
        "subjective": "주관적",
        "surreal": "초현실",
        "symbols": "기호",
        "text": "텍스트",
        "year_tags": "연도 태그",

        # ===== Creatures =====
        "animal_accessories": "동물 액세서리",
        "animal_features": "동물 특징",
        "animal_interaction": "동물 상호작용",
        "archetype": "캐릭터 유형",
        "birds": "새",
        "cats": "고양이",
        "dogs": "개",
        "fish": "물고기",
        "furry": "퍼리",
        "insects": "곤충",
        "kemonomimi": "수인/케모미미",
        "legendary_creatures": "전설의 생물",
        "other_animals": "기타 동물",
        "plants": "식물",
        "pokemon": "포켓몬",
        "reptiles": "파충류",
        "tentacles": "촉수",

        # ===== Culture_Misc =====
        "artistic_license": "예술적 표현",
        "character_nickname": "캐릭터 별명",
        "culture": "문화",
        "events": "이벤트",
        "family_relationships": "가족 관계",
        "groups": "그룹",
        "history": "역사",
        "holidays_and_celebrations": "명절/축제",
        "jobs": "직업",
        "memes": "밈",
        "music": "음악",
        "occupation": "직업",
        "parody": "패러디",
        "phrases": "문구",
        "relationships": "관계",
        "sports": "스포츠",

        # ===== Expression_Action =====
        "action": "액션",
        "activity": "활동",
        "bondage_state": "속박 상태",
        "clothing_action": "의복 동작",
        "combat_actions": "전투 행동",
        "dances": "춤",
        "emotion": "감정",
        "expression": "표정",
        "gender_expression": "젠더 표현",
        "gesture": "제스처",
        "gestures": "제스처",
        "interaction": "상호작용",
        "interactions": "상호작용",
        "personality": "성격",
        "pose": "포즈",
        "posture": "자세",
        "reaction": "반응",
        "situation": "상황",
        "state": "상태",
        "verbs_and_gerunds": "동사/행위",

        # ===== Food_Object =====
        "art_objects": "예술품",
        "board_games": "보드게임",
        "cards": "카드",
        "containers": "용기",
        "food_tags": "음식",
        "furniture": "가구",
        "instruments": "악기",
        "medical_equipment": "의료 장비",
        "objects": "물체",
        "technology": "기술/전자",
        "tools": "도구",
        "vehicles": "탈것",
        "weapons": "무기",

        # ===== Location_Background =====
        "backgrounds": "배경",
        "fire": "불",
        "landmark": "랜드마크",
        "locations": "장소",
        "nature": "자연",
        "real_world_locations": "실제 장소",
        "time": "시간",
        "water": "물",
        "weather": "날씨",

        # ===== NSFW =====
        "anatomy": "해부학",
        "anticipation": "기대/예고",
        "ass": "엉덩이",
        "body": "신체",
        "body_writing": "신체 글씨",
        "censorship": "검열",
        "dark_content": "다크 콘텐츠",
        "exposure": "노출",
        "fetish": "페티시",
        "fluids": "체액",
        "genitals": "성기",
        "genre": "장르",
        "gore": "고어",
        "groping": "더듬기",
        "implied": "암시",
        "insertion": "삽입",
        "media": "미디어",
        "meme": "밈",
        "meter": "게이지",
        "nudity": "누드",
        "object": "물체",
        "pasties": "니플 커버",
        "pov": "시점",
        "pussy": "음부",
        "self_touch": "자위",
        "sex_act": "성행위",
        "sex_acts": "성행위",
        "sex_objects": "성적 도구",
        "sex_position": "체위",
        "sexual_activity": "성적 활동",
        "sexual_positions": "체위",
        "sexual_situation": "성적 상황",
        "simulated_sex_acts": "유사 성행위",
        "symbol": "기호",
        "taboo": "금기",
        "toys": "장난감",
        "visual": "시각적",

        # ===== Person_Body =====
        "body_functions": "신체 기능",
        "body_marks": "신체 자국",
        "body_modification": "신체 변형",
        "body_parts": "신체 부위",
        "body_type": "체형",
        "breasts_tags": "가슴",
        "ears_tags": "귀",
        "eyes": "눈",
        "eyes_tags": "눈 태그",
        "face": "얼굴",
        "face_tags": "얼굴 태그",
        "hair": "머리카락",
        "hair_color": "머리색",
        "hair_styles": "헤어스타일",
        "hands": "손",
        "mechanical": "기계/사이버",
        "prosthetic": "의수/의족",
        "relationship": "관계",
        "skin_color": "피부색",
        "skin_markings": "피부 문양",
        "tail": "꼬리",
        "tattoo": "문신",
        "wings": "날개",

        # ===== Common =====
        "etc": "기타",
    }

    def __init__(self, parent=None, allowed_groups: list = None, allowed_subgroups = None):
        """
        TagViewer 생성자

        Args:
            parent: 부모 위젯
            allowed_groups: 허용할 대분류 리스트 (예: ["Clothing_Wear", "Person_Body"])
                           None이면 전체 표시 (기본값)
            allowed_subgroups: 허용할 소분류 (list 또는 dict)
                              - list: 모든 대분류에 공통 적용 (예: ["상의", "하의"])
                              - dict: 대분류별 소분류 필터 (예: {"NSFW": ["etc", "nudity"]})
                              - None: 전체 표시 (기본값)

        Example:
            # 전체 표시 (기본)
            viewer = TagViewerWidget()

            # 의상만 표시
            viewer = TagViewerWidget(allowed_groups=["Clothing_Wear"])

            # 의상의 특정 소분류만 표시 (전역)
            viewer = TagViewerWidget(
                allowed_groups=["Clothing_Wear"],
                allowed_subgroups=["상의", "하의"]
            )

            # 대분류별로 다른 소분류 필터 적용
            viewer = TagViewerWidget(
                allowed_groups=["Person_Body", "NSFW"],
                allowed_subgroups={
                    "NSFW": ["etc", "nudity"]  # NSFW는 특정 소분류만
                    # Person_Body는 전체 (딕셔너리에 없으면 전체)
                }
            )
        """
        if parent is None:
            super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            self.is_standalone = True  # 독립 윈도우 모드
        else:
            super().__init__(parent)
            # 자식 위젯일 경우 별도 플래그 없음 (DraggablePanel 내부에서 사용)
            self.is_standalone = False  # 임베디드 모드

        # 위치 고정용
        self.fixed_position = None
        self.is_initialized = False

        # 현재 데이터
        self.all_tags_data = {}  # tag -> tag_data
        self.current_group_tags = {}  # 필터된 태그

        self._target_widget = None # 닫기 예외 처리할 타겟 위젯 (입력창 등)

        # 🆕 필터링 설정
        self.allowed_groups = allowed_groups  # None = 전체, list = 지정된 것만
        self.allowed_subgroups = allowed_subgroups  # None = 전체, list = 지정된 것만

        # 검색 딜레이 타이머
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)  # 300ms 딜레이
        self.search_timer.timeout.connect(self._perform_search)

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        # 전체 크기 설정 (좌우 분할 구조로 너비 증가, 높이 축소)
        total_width = get_scaled_size(1050)  # 950 → 1050 (100px 추가 증가)
        total_height = get_scaled_size(950)  # 850 → 950 (100px 추가 증가)

        # 독립 윈도우일 때만 고정 크기, 임베디드 모드일 때는 유연한 크기
        if self.is_standalone:
            self.setFixedSize(total_width, total_height)
        else:
            # BlockWidget 내부에서 사용될 때는 최소 크기만 설정
            self.setMinimumSize(total_width, get_scaled_size(400))
            self.setMaximumHeight(total_height)

        # 메인 레이아웃
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 좌우 분할 레이아웃 ===
        horizontal_split = QHBoxLayout()
        horizontal_split.setSpacing(0)

        # === 좌측 영역: 3단 리스트 + 검색 + 설명 ===
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # 1. 3단 리스트 (대분류 | 소분류 | 태그)
        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(0)
        lists_layout.setContentsMargins(0, 0, 0, 0)

        self.group_list = self._create_list_widget("대분류")
        lists_layout.addWidget(self.group_list, 2)  # 1 → 2로 증가

        self.subgroup_list = self._create_list_widget("소분류")
        lists_layout.addWidget(self.subgroup_list, 2)

        self.tag_list = self._create_list_widget("태그")
        self.tag_list.setItemDelegate(TagListDelegate(self.tag_list))
        lists_layout.addWidget(self.tag_list, 3)

        left_layout.addLayout(lists_layout, 3)  # 3단 리스트 (비율 3)

        # 2. 검색 바
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색할 태그를 입력하세요...")
        self.search_input.setProperty("autocomplete_ignore", True)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: 0px;
                padding: {get_scaled_size(8)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(19)}px;
                border-left: none;
                border-right: none;
            }}
            QLineEdit:focus {{
                border: 1px solid {COMMON_STYLES['input_focus']};
                background-color: #3A3A3A;
            }}
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        left_layout.addWidget(self.search_input)

        # === 액션 버튼 영역 ===
        action_layout = QHBoxLayout()
        action_layout.setSpacing(1)
        action_layout.setContentsMargins(0, 0, 0, 0)

        # 버튼 스타일
        btn_style = f"""
            QPushButton {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                padding: {get_scaled_size(6)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
        """

        # 1. 프롬프트 삽입
        self.btn_insert = QPushButton("[ 프롬프트 삽입 ]")
        self.btn_insert.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_insert.setStyleSheet(btn_style)
        self.btn_insert.clicked.connect(self._on_insert_clicked)
        action_layout.addWidget(self.btn_insert)

        # 2. 퀵 서치 검색
        self.btn_quick = QPushButton("[ 퀵 서치 검색 ]")
        self.btn_quick.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quick.setStyleSheet(btn_style)
        self.btn_quick.clicked.connect(self._on_quick_search_clicked)
        action_layout.addWidget(self.btn_quick)

        # 3. 복사
        self.btn_copy = QPushButton("[ 복사 ]")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setStyleSheet(btn_style)
        self.btn_copy.clicked.connect(self._on_copy_clicked)
        action_layout.addWidget(self.btn_copy)

        left_layout.addLayout(action_layout)

        # 3. 설명 영역 (기본 정보)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: rgba(0, 0, 0, 0.6);
                color: #FFFFFF;
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: 0px;
                padding: {get_scaled_size(8)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(21)}px;
            }}
        """)
        left_layout.addWidget(self.info_text, 1)  # 설명 영역 (비율 1 - 절반으로 축소)

        horizontal_split.addWidget(left_container, 5)  # 좌측 (비율 5)

        # === 우측 영역: 연관 태그 (전체 높이) ===
        self.relations_text = QTextBrowser()
        self.relations_text.setReadOnly(True)
        self.relations_text.setOpenExternalLinks(False)
        self.relations_text.setOpenLinks(False)
        self.relations_text.setStyleSheet(f"""
            QTextBrowser {{
                background-color: rgba(255, 255, 255, 0.9);
                color: #000000;
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: 0px;
                padding: {get_scaled_size(8)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(20)}px;
            }}
            QTextBrowser a {{
                color: #1565C0;
                text-decoration: none;
            }}
            QTextBrowser a:hover {{
                color: #0D47A1;
                text-decoration: underline;
            }}
        """)
        self.relations_text.anchorClicked.connect(self._on_relation_tag_clicked)
        horizontal_split.addWidget(self.relations_text, 2)  # 우측 (비율 2)

        main_layout.addLayout(horizontal_split)

        # === 닫기 버튼 (우측 상단 고정) - 독립 윈도우 전용 ===
        # 임베디드 모드에서는 DraggablePanel 헤더로 접기/닫기가 가능하므로 불필요
        if self.is_standalone:
            self.btn_close = QPushButton("✕", self)
            self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_close.setFixedSize(get_scaled_size(20), get_scaled_size(20))
            self.btn_close.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(43, 43, 43, 180);
                    color: {COMMON_STYLES['text_secondary']};
                    border: 1px solid {COMMON_STYLES['input_border']};
                    border-radius: {get_scaled_size(3)}px;
                    font-family: {FONT_FAMILY};
                    font-size: {get_scaled_font_size(16)}px;
                    font-weight: bold;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                    color: {COMMON_STYLES['text_primary']};
                    border: 1px solid {COMMON_STYLES['error']};
                }}
                QPushButton:pressed {{
                    background-color: {COMMON_STYLES['error']};
                    color: white;
                }}
            """)
            self.btn_close.clicked.connect(self.hide)
            # 위치는 resizeEvent에서 조정

        # 시그널 연결
        self.group_list.currentItemChanged.connect(self._on_group_changed)
        self.subgroup_list.currentItemChanged.connect(self._on_subgroup_changed)
        self.tag_list.itemClicked.connect(self._on_tag_clicked)
        self.tag_list.itemDoubleClicked.connect(self._on_tag_double_clicked)

        # 전체 스타일 (반투명) - TagViewerWidget에만 적용
        # 임베디드 모드일 때는 더 투명하게 (이미지 위에서 사용)
        if self.is_standalone:
            bg_alpha = 220  # 거의 불투명 (85%)
            window_opacity = 0.95
        else:
            bg_alpha = 180  # 더 투명 (70%)
            window_opacity = 0.88

        self.setStyleSheet(f"""
            TagViewerWidget {{
                background-color: rgba(43, 43, 43, {bg_alpha});  /* 반투명 배경 */
                border: 2px solid {COMMON_STYLES['input_focus']};
                border-radius: {get_scaled_size(8)}px;
            }}
        """)

        # 윈도우 투명도 설정
        self.setWindowOpacity(window_opacity)

    def _create_list_widget(self, title: str) -> QListWidget:
        """리스트 위젯 생성 헬퍼"""
        list_widget = QListWidget()
        list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: 0px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(22)}px;
                padding: {get_scaled_size(4)}px;
                outline: none;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(5)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
            QListWidget::item:hover {{
                background-color: #3A3A3A;
            }}
            QListWidget::item:selected {{
                background-color: {COMMON_STYLES['input_focus']} !important;
                color: white !important;
            }}
            QListWidget::item:selected:hover {{
                background-color: #4A4A4A !important;
                color: white !important;
            }}
        """)
        return list_widget

    def set_tags_data(self, tags_data: dict):
        """
        태그 데이터 설정

        Args:
            tags_data: {tag: tag_data} 형태의 딕셔너리
        """
        self.all_tags_data = tags_data
        self._populate_groups()

        # ✅ 첫 번째 대분류 자동 선택 (미리보기 표시를 위해)
        if self.group_list.count() > 0:
            self.group_list.setCurrentRow(0)

    def _populate_groups(self):
        """대분류 목록 채우기 (allowed_groups 필터 적용)"""
        self.group_list.clear()

        # 대분류 추출 (중복 제거)
        groups = set()
        for tag_data in self.all_tags_data.values():
            group = tag_data.get("group", "")
            if group:
                groups.add(group)

        # 🆕 allowed_groups 필터 적용
        if self.allowed_groups is not None:
            # allowed_groups가 지정되어 있으면 해당 그룹만 필터링
            groups = groups & set(self.allowed_groups)

        # 대분류 한글 매핑
        group_kr_map = {
            "Clothing_Wear": "의상/착용",
            "Person_Body": "인체/신체",
            "Food_Object": "음식/사물",
            "Composition_Meta": "구도/메타",
            "Expression_Action": "표정/행동",
            "Creatures": "생물/종족",
            "Location_Background": "장소/배경",
            "NSFW": "NSFW",
            "Culture_Misc": "문화/기타"
        }

        # 정렬 및 추가
        for group in sorted(groups):
            group_kr = group_kr_map.get(group, group)
            item = QListWidgetItem(group_kr)
            item.setData(Qt.ItemDataRole.UserRole, group)  # 영문 원본 저장
            self.group_list.addItem(item)

    def _on_group_changed(self, current, previous):
        """대분류 선택 변경 (allowed_subgroups 필터 적용)"""
        if not current:
            return

        selected_group = current.data(Qt.ItemDataRole.UserRole)

        # 해당 대분류의 소분류 추출
        self.subgroup_list.clear()
        subgroups = set()

        for tag_data in self.all_tags_data.values():
            if tag_data.get("group") == selected_group:
                subgroup = tag_data.get("subgroup", "")
                if subgroup:
                    subgroups.add(subgroup)

        # 🆕 allowed_subgroups 필터 적용
        if self.allowed_subgroups is not None:
            if isinstance(self.allowed_subgroups, dict):
                # dict 형태: 대분류별 소분류 필터
                # 현재 대분류에 해당하는 필터가 있으면 적용, 없으면 전체 허용
                if selected_group in self.allowed_subgroups:
                    allowed_for_this_group = self.allowed_subgroups[selected_group]
                    subgroups = subgroups & set(allowed_for_this_group)
                # selected_group이 딕셔너리에 없으면 subgroups 그대로 (전체 허용)
            else:
                # list 형태: 전역 필터 (모든 대분류에 공통 적용)
                subgroups = subgroups & set(self.allowed_subgroups)

        # 소분류 추가 (🆕 한글 번역 적용)
        for subgroup in sorted(subgroups):
            # 한글 번역이 있으면 사용, 없으면 원본
            subgroup_kr = self.SUBGROUP_KR_MAP.get(subgroup, subgroup)
            item = QListWidgetItem(subgroup_kr)
            # 원본 영문 subgroup을 UserRole에 저장 (필터링 시 사용)
            item.setData(Qt.ItemDataRole.UserRole, subgroup)
            self.subgroup_list.addItem(item)

        # ✅ 초기 로드 시 (previous가 None) 첫 번째 소분류 자동 선택
        if previous is None and self.subgroup_list.count() > 0:
            self.subgroup_list.setCurrentRow(0)

        # 🆕 소분류 리스트가 업데이트되었으므로 필터 하이라이팅 갱신
        self._update_filter_highlighting()

    def _on_subgroup_changed(self, current, previous):
        """소분류 선택 변경"""
        if not current:
            return

        # 현재 선택된 대분류
        group_item = self.group_list.currentItem()
        if not group_item:
            return

        selected_group = group_item.data(Qt.ItemDataRole.UserRole)
        # 🆕 UserRole에 저장된 원본 영문 subgroup 사용 (한글 표시명이 아닌)
        selected_subgroup = current.data(Qt.ItemDataRole.UserRole)

        # 태그 필터링
        self.tag_list.clear()
        filtered_tags = []

        for tag, tag_data in self.all_tags_data.items():
            if (tag_data.get("group") == selected_group and
                tag_data.get("subgroup") == selected_subgroup):
                filtered_tags.append((tag, tag_data))

        # 빈도순 정렬
        filtered_tags.sort(key=lambda x: x[1].get("freq", 0), reverse=True)

        # 태그 리스트 채우기
        for tag, tag_data in filtered_tags:
            count = tag_data.get("freq", 0)

            # count 포맷팅
            if count >= 1000000:
                count_text = f"{count/1000000:.1f}M"
            elif count >= 1000:
                count_text = f"{count/1000:.0f}k"
            else:
                count_text = str(count)

            # Delegate에서 렌더링하므로 텍스트에는 태그만 설정
            item = QListWidgetItem(tag)
            item.setData(Qt.ItemDataRole.UserRole, tag)  # 실제 태그명
            item.setData(Qt.ItemDataRole.UserRole + 1, tag_data)  # 전체 데이터
            item.setData(Qt.ItemDataRole.UserRole + 2, count_text) # 포맷된 카운트 텍스트

            # 툴팁 설정
            description = tag_data.get("description", "")
            keywords_kr = tag_data.get("keywords_kr", "")

            tooltip_parts = []

            if description:
                tooltip_parts.append(f"설명: {description}")
            if keywords_kr:
                tooltip_parts.append(f"키워드: {keywords_kr}")

            item.setToolTip("\n".join(tooltip_parts))

            self.tag_list.addItem(item)

        # ✅ 초기 로드 시 (previous가 None) 첫 번째 태그 자동 선택 및 미리보기 표시
        if previous is None and self.tag_list.count() > 0:
            self.tag_list.setCurrentRow(0)
            # 첫 번째 태그의 미리보기 자동 표시
            first_item = self.tag_list.item(0)
            if first_item:
                self._on_tag_clicked(first_item)

    def _on_search_text_changed(self, text):
        """검색어 변경 시 타이머 재설정 (디바운싱)"""
        self.search_timer.start()

    def _perform_search(self):
        """실제 검색 수행"""
        text = self.search_input.text().strip().lower()
        
        # 1. 검색어가 없으면 -> 기존 선택된 분류의 태그 목록 복원
        if not text:
            # 현재 선택된 대분류/소분류가 있으면 다시 로드
            current_sub_item = self.subgroup_list.currentItem()
            if current_sub_item:
                # _on_subgroup_changed를 강제로 호출하여 리스트 복원
                self._on_subgroup_changed(current_sub_item, None)
            else:
                self.tag_list.clear() # 선택된게 없으면 클리어
            return

        # 2. 검색어가 있으면 -> 전체 데이터에서 검색 (대분류/소분류 무시)
        self.tag_list.clear()
        
        # 검색 결과 저장을 위한 리스트
        matched_tags = []
        
        # 검색어 공백 분리 (AND 검색 지원 가능하게 하거나, 단순히 통으로 검색하거나)
        # 여기서는 단순 포함 검색 + 한국어 키워드 검색
        
        for tag, tag_data in self.all_tags_data.items():
            # 태그명 검색
            if text in tag.lower():
                matched_tags.append((tag, tag_data))
                continue
                
            # 한국어 키워드 검색
            keywords_kr = tag_data.get("keywords_kr", "")
            if keywords_kr and text in keywords_kr:
                matched_tags.append((tag, tag_data))
                continue
                
            # 별칭(alias) 검색 필요 시 추가 가능
            
        # 빈도순 정렬
        matched_tags.sort(key=lambda x: x[1].get("freq", 0), reverse=True)

        # UI 업데이트
        for tag, tag_data in matched_tags:
            count = tag_data.get("freq", 0)

            # count 포맷팅
            if count >= 1000000:
                count_text = f"{count/1000000:.1f}M"
            elif count >= 1000:
                count_text = f"{count/1000:.0f}k"
            else:
                count_text = str(count)

            item = QListWidgetItem(tag)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            item.setData(Qt.ItemDataRole.UserRole + 1, tag_data)
            item.setData(Qt.ItemDataRole.UserRole + 2, count_text)

            # 툴팁 설정
            description = tag_data.get("description", "")
            keywords_kr = tag_data.get("keywords_kr", "")

            tooltip_parts = []
            if description:
                tooltip_parts.append(f"설명: {description}")
            if keywords_kr:
                tooltip_parts.append(f"키워드: {keywords_kr}")

            item.setToolTip("\n".join(tooltip_parts))

            self.tag_list.addItem(item)
            
        # 대분류/소분류 선택 해제 (검색 모드임을 시각적으로 표현)
        self.group_list.clearSelection()
        self.subgroup_list.clearSelection()

    def _on_tag_clicked(self, item):
        """태그 클릭 시 미리보기 업데이트"""
        if not item:
            return

        tag = item.data(Qt.ItemDataRole.UserRole)
        tag_data = item.data(Qt.ItemDataRole.UserRole + 1)

        # === 좌측: 기본 정보 ===
        info_parts = []

        # # 태그명
        # info_parts.append(f"🏷️ 태그: {tag}")

        # # 빈도
        # freq = tag_data.get('freq', 0)
        # info_parts.append(f"📊 빈도: {freq:,}")

        # # 분류
        # group = tag_data.get("group", "")
        # subgroup = tag_data.get("subgroup", "")
        # if group:
        #     info_parts.append(f"📁 분류: {group} > {subgroup}")

        # 설명
        description = tag_data.get("description", "")
        if description:
            info_parts.append(f"\n📝 설명:\n{description}")

        # 한글 키워드
        keywords_kr = tag_data.get("keywords_kr", "")
        if keywords_kr:
            info_parts.append(f"\n🔍 키워드: {keywords_kr}")

        self.info_text.setPlainText("\n".join(info_parts))

        # === 우측: 연관 태그 (HTML 하이퍼링크) ===
        import html
        relations = tag_data.get("relations", {})

        html_parts = []
        html_parts.append(f"<html><body style='color: #000000; font-family: {FONT_FAMILY}; font-size: 15px;'>")

        if relations:
            # 상위 태그
            parent = relations.get("parent")
            if parent:
                html_parts.append("<p style='margin: 4px 0;'><b>⬆️ 상위 태그:</b><br/>")
                html_parts.append(f"  {self._make_tag_link(parent)}")
                html_parts.append("</p>")

            # 하위 태그 (모두 표시)
            children = relations.get("children", [])
            if children:
                html_parts.append(f"<p style='margin: 8px 0 4px 0;'><b>⬇️ 하위 태그 ({len(children)}개):</b><br/>")
                for child in children:
                    html_parts.append(f"  • {self._make_tag_link(child)}<br/>")
                html_parts.append("</p>")

            # 형제 태그 (모두 표시)
            siblings = relations.get("siblings", [])
            if siblings:
                html_parts.append(f"<p style='margin: 8px 0 4px 0;'><b>🔀 형제 태그 ({len(siblings)}개):</b><br/>")
                for sibling in siblings:
                    html_parts.append(f"  • {self._make_tag_link(sibling)}<br/>")
                html_parts.append("</p>")

            # 관련 태그 (모두 표시)
            word_match = relations.get("word_match", [])
            if word_match:
                html_parts.append(f"<p style='margin: 8px 0 4px 0;'><b>🔗 관련 태그 ({len(word_match)}개):</b><br/>")
                for match in word_match:
                    html_parts.append(f"  • {self._make_tag_link(match)}<br/>")
                html_parts.append("</p>")

        if not relations or (not parent and not children and not siblings and not word_match):
            html_parts.append("<p>연관 태그 정보가 없습니다.</p>")

        html_parts.append("</body></html>")
        self.relations_text.setHtml("".join(html_parts))

    def _make_tag_link(self, tag: str) -> str:
        """
        태그를 하이퍼링크로 변환 (존재하는 태그만, 툴팁 포함)

        Args:
            tag: 태그명

        Returns:
            HTML 링크 또는 일반 텍스트 (툴팁 포함)
        """
        import html
        escaped_tag = html.escape(tag)

        # 태그가 데이터에 존재하는지 확인
        if tag in self.all_tags_data:
            tag_data = self.all_tags_data[tag]

            # 툴팁 생성 (설명 + 키워드)
            tooltip_parts = []
            description = tag_data.get("description", "")
            keywords_kr = tag_data.get("keywords_kr", "")

            if description:
                tooltip_parts.append(f"설명: {description}")
            if keywords_kr:
                tooltip_parts.append(f"키워드: {keywords_kr}")

            # 툴팁이 있으면 title 속성 추가
            if tooltip_parts:
                tooltip_text = "\n".join(tooltip_parts)
                escaped_tooltip = html.escape(tooltip_text)
                return f'<a href="tag:{escaped_tag}" title="{escaped_tooltip}">{escaped_tag}</a>'
            else:
                # 툴팁 없이 기본 링크
                return f'<a href="tag:{escaped_tag}">{escaped_tag}</a>'
        else:
            # 일반 텍스트 (회색으로 표시)
            return f'<span style="color: #888888;">{escaped_tag}</span>'

    def _on_relation_tag_clicked(self, url):
        """
        연관 태그 하이퍼링크 클릭 핸들러

        Args:
            url: QUrl 객체 (형식: "tag:태그명")
        """
        # URL에서 태그명 추출
        tag_name = url.toString().replace("tag:", "")

        if tag_name not in self.all_tags_data:
            print(f"[TagViewer] 태그 '{tag_name}'가 데이터에 없습니다.")
            return

        tag_data = self.all_tags_data[tag_name]
        group = tag_data.get("group", "")
        subgroup = tag_data.get("subgroup", "")

        if not group or not subgroup:
            print(f"[TagViewer] 태그 '{tag_name}'의 분류 정보가 없습니다.")
            return

        # 대분류 한글 매핑
        group_kr_map = {
            "Clothing_Wear": "의상/착용",
            "Person_Body": "인체/신체",
            "Food_Object": "음식/사물",
            "Composition_Meta": "구도/메타",
            "Expression_Action": "표정/행동",
            "Creatures": "생물/종족",
            "Location_Background": "장소/배경",
            "NSFW": "NSFW",
            "Culture_Misc": "문화/기타"
        }
        group_kr = group_kr_map.get(group, group)

        # 1. 대분류 선택
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == group:
                self.group_list.setCurrentItem(item)
                break

        # 2. 소분류 선택 (대분류 선택 후 리스트가 업데이트됨)
        # 소분류 리스트가 업데이트될 때까지 잠시 대기 필요
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._select_subgroup_and_tag(subgroup, tag_name))

    def _select_subgroup_and_tag(self, subgroup: str, tag_name: str):
        """
        소분류 선택 및 태그 포커스

        Args:
            subgroup: 소분류명 (영문)
            tag_name: 태그명
        """
        # 2. 소분류 선택 (🔧 UserRole에 저장된 원본 영문 subgroup과 비교)
        for i in range(self.subgroup_list.count()):
            item = self.subgroup_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == subgroup:
                self.subgroup_list.setCurrentItem(item)
                break

        # 3. 태그 리스트에서 포커스 (클릭은 아님)
        # 소분류 선택 후 태그 리스트가 업데이트될 때까지 대기
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._focus_tag(tag_name))

    def _focus_tag(self, tag_name: str):
        """
        태그 리스트에서 해당 태그에 포커스 (클릭하지 않음)

        Args:
            tag_name: 태그명
        """
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_name:
                # 포커스만 부여 (선택하지 않음, 미리보기 업데이트 안 함)
                self.tag_list.setCurrentItem(item)
                self.tag_list.scrollToItem(item)
                break

    def _on_tag_double_clicked(self, item):
        """태그 더블클릭 시 선택 시그널 발행"""
        if not item:
            return

        tag = item.data(Qt.ItemDataRole.UserRole)
        self.tag_selected.emit(tag)

    def show_at_position(self, x: int, y: int):
        """
        지정된 위치에 표시 (위치 고정)

        Args:
            x, y: 글로벌 좌표
        """
        if not self.is_initialized:
            # 처음 표시될 때만 위치 기억
            self.fixed_position = (x, y)
            self.is_initialized = True

        # 고정된 위치에 표시
        if self.fixed_position:
            self.move(self.fixed_position[0], self.fixed_position[1])
        else:
            self.move(x, y)

        self.show()
        self.raise_()

    def reset_position(self):
        """위치 고정 해제 (숨길 때 호출)"""
        self.is_initialized = False
        self.fixed_position = None

    @property
    def target_widget(self):
        """현재 타겟 위젯 (포커스된 TextEdit)"""
        return self._target_widget

    @target_widget.setter
    def target_widget(self, widget):
        """타겟 위젯 설정 및 필터 하이라이팅 업데이트"""
        self._target_widget = widget
        self._update_filter_highlighting()

    def set_target_widget(self, widget):
        """닫기 예외 처리할 타겟 위젯 설정 (이 위젯 클릭 시에는 닫히지 않음)"""
        self.target_widget = widget

    def _update_filter_highlighting(self):
        """
        포커스된 위젯의 allowed_groups/allowed_subgroups 속성에 따라
        대분류/소분류 리스트의 해당 항목을 노란색으로 강조
        """
        print(f"[TagViewerWidget] _update_filter_highlighting 호출됨")

        # 1. 모든 하이라이팅 초기화
        self._clear_filter_highlighting()

        # 2. 타겟 위젯이 없으면 종료
        if not self._target_widget:
            print(f"  - 타겟 위젯 없음, 종료")
            return

        # 3. 타겟 위젯의 필터 속성 읽기
        widget_allowed_groups = self._target_widget.property("allowed_groups")
        widget_allowed_subgroups = self._target_widget.property("allowed_subgroups")

        print(f"  - 타겟 위젯 필터 속성:")
        print(f"    - allowed_groups: {widget_allowed_groups}")
        print(f"    - allowed_subgroups: {widget_allowed_subgroups}")

        # 4. 대분류 하이라이팅 (선택되지 않은 항목만)
        if widget_allowed_groups and isinstance(widget_allowed_groups, list):
            highlighted_count = 0
            current_row = self.group_list.currentRow()

            for i in range(self.group_list.count()):
                item = self.group_list.item(i)
                # UserRole에 저장된 영문 그룹명과 비교
                group_eng = item.data(Qt.ItemDataRole.UserRole)

                # 허용된 그룹이고 현재 선택되지 않은 항목만 하이라이팅
                if group_eng in widget_allowed_groups and i != current_row:
                    # 진한 금색 배경 + 연한 노란색 텍스트로 강조
                    item.setBackground(QColor("#FFD700"))  # 금색
                    item.setForeground(QColor("#FFF59D"))  # 연한 노란색 텍스트
                    highlighted_count += 1
                    print(f"    - 대분류 하이라이팅: {group_eng}")

            print(f"  - 대분류 하이라이팅 완료: {highlighted_count}개 (선택된 항목 제외)")

        # 5. 소분류 하이라이팅
        if widget_allowed_subgroups:
            # dict 형태: {"NSFW": ["etc", "nudity"], ...}
            # list 형태: ["etc", "accessories", ...]

            # 현재 선택된 대분류 확인
            current_group_item = self.group_list.currentItem()
            if current_group_item:
                current_group = current_group_item.data(Qt.ItemDataRole.UserRole)
                print(f"  - 현재 선택된 대분류: {current_group}")

                subgroup_highlighted_count = 0
                current_subgroup_row = self.subgroup_list.currentRow()

                if isinstance(widget_allowed_subgroups, dict):
                    # dict 형태: 대분류별 소분류 필터
                    print(f"    - 소분류 필터 타입: dict")
                    if current_group in widget_allowed_subgroups:
                        allowed_for_group = widget_allowed_subgroups[current_group]
                        print(f"    - 현재 대분류의 허용 소분류: {allowed_for_group}")
                        for i in range(self.subgroup_list.count()):
                            item = self.subgroup_list.item(i)
                            subgroup_eng = item.data(Qt.ItemDataRole.UserRole)
                            # 허용된 소분류이고 현재 선택되지 않은 항목만 하이라이팅
                            if subgroup_eng in allowed_for_group and i != current_subgroup_row:
                                # 진한 금색 배경 + 연한 노란색 텍스트로 강조
                                item.setBackground(QColor("#FFD700"))  # 금색
                                item.setForeground(QColor("#FFF59D"))  # 연한 노란색 텍스트
                                subgroup_highlighted_count += 1
                                print(f"      - 소분류 하이라이팅: {subgroup_eng}")
                    else:
                        print(f"    - 현재 대분류({current_group})가 필터에 없음")
                elif isinstance(widget_allowed_subgroups, list):
                    # list 형태: 전역 필터
                    print(f"    - 소분류 필터 타입: list, 전역 필터: {widget_allowed_subgroups}")
                    for i in range(self.subgroup_list.count()):
                        item = self.subgroup_list.item(i)
                        subgroup_eng = item.data(Qt.ItemDataRole.UserRole)
                        # 허용된 소분류이고 현재 선택되지 않은 항목만 하이라이팅
                        if subgroup_eng in widget_allowed_subgroups and i != current_subgroup_row:
                            # 진한 금색 배경 + 연한 노란색 텍스트로 강조
                            item.setBackground(QColor("#FFD700"))  # 금색
                            item.setForeground(QColor("#FFF59D"))  # 연한 노란색 텍스트
                            subgroup_highlighted_count += 1
                            print(f"      - 소분류 하이라이팅: {subgroup_eng}")
                print(f"  - 소분류 하이라이팅 완료: {subgroup_highlighted_count}개 (선택된 항목 제외)")

        # UI 강제 갱신 (색상 변경이 즉시 반영되도록)
        self.group_list.viewport().update()
        self.subgroup_list.viewport().update()
        print("[TagViewerWidget] UI 강제 갱신 완료")

    def _clear_filter_highlighting(self):
        """대분류/소분류 리스트의 모든 하이라이팅 제거"""
        # 기본 배경색 (투명)
        default_color = QColor(0, 0, 0, 0)
        default_text = QColor("#FFFFFF")  # 흰색 텍스트

        # 대분류 초기화
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            item.setBackground(default_color)
            item.setForeground(default_text)

        # 소분류 초기화
        for i in range(self.subgroup_list.count()):
            item = self.subgroup_list.item(i)
            item.setBackground(default_color)
            item.setForeground(default_text)

    def showEvent(self, event):
        super().showEvent(event)
        # 독립 윈도우일 때만 전역 클릭 감지 활성화 (임베디드 모드에서는 불필요)
        if self.is_standalone:
            QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        """숨김 이벤트 - 위치 리셋 및 필터 제거"""
        super().hideEvent(event)
        if self.is_standalone:
            self.reset_position()
            QApplication.instance().removeEventFilter(self)

    def eventFilter(self, obj, event):
        """전역 이벤트 필터: 외부 클릭 시 닫기 (단, target_widget 제외) - 독립 윈도우 전용"""
        # 임베디드 모드에서는 이벤트 필터 비활성화
        if not self.is_standalone:
            return super().eventFilter(obj, event)

        if event.type() == QEvent.Type.MouseButtonPress:
            pos = event.globalPosition().toPoint()

            # 1. 내 영역 내부 클릭이면 무시 (닫지 않음)
            if self.geometry().contains(pos):
                return False

            # 2. 타겟 위젯(입력창) 내부 클릭이면 무시 (타이핑 계속)
            if self.target_widget and self.target_widget.isVisible():
                # 글로벌 좌표계로 변환하여 확인
                target_geo = self.target_widget.rect()
                target_top_left = self.target_widget.mapToGlobal(QPoint(0, 0))
                target_rect = QRect(target_top_left, target_geo.size())
                
                if target_rect.contains(pos):
                    return False

            # 3. 그 외 영역 클릭 -> 닫기
            self.hide()
            # 이벤트를 소비하지 않고 흘려보냄 (다른 위젯 동작 허용)
        
        return super().eventFilter(obj, event)

    # ===== 액션 버튼 핸들러 =====

    def _on_insert_clicked(self):
        """[프롬프트 삽입] 버튼 핸들러"""
        current_item = self.tag_list.currentItem()
        if not current_item:
            return
            
        tag = current_item.data(Qt.ItemDataRole.UserRole)
        if not tag:
            return

        if self.target_widget and isinstance(self.target_widget, QTextEdit):
            cursor = self.target_widget.textCursor()
            
            # 현재 커서 위치 이후의 텍스트 검색을 위해 블록 텍스트 가져오기
            text_block = cursor.block().text()
            pos_in_block = cursor.positionInBlock()
            remaining_text = text_block[pos_in_block:]
            
            # 다음 쉼표 찾기
            comma_index = remaining_text.find(',')
            
            if comma_index != -1:
                # 쉼표가 있으면 그 쉼표 직전으로 이동
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, comma_index)
                
                # 삽입 (쉼표는 유지)
                cursor.insertText(f", {tag}")
            else:
                # 쉼표가 없으면? (마지막 태그 뒤 등)
                # 요청사항: "다음에 오는 쉼표를 찾아 그 앞에"
                # 없으면 그냥 현재 위치에 넣거나 맨 뒤에 넣어야 함.
                # " tag1, tag2 | " -> comma 없음.
                # 그냥 입력
                cursor.insertText(f", {tag}")
            
            # 타겟 위젯에 포커스
            self.target_widget.setTextCursor(cursor)
            self.target_widget.setFocus()

    def _on_quick_search_clicked(self):
        """[퀵 서치 검색] 버튼 핸들러"""
        current_item = self.tag_list.currentItem()
        if not current_item:
            return
            
        tag = current_item.data(Qt.ItemDataRole.UserRole)
        if tag:
            # 시그널 발행 -> Manager -> InteractiveWindow -> QuickSearchBlock
            self.quick_search_requested.emit(tag)
            
            # 편의상 뷰어 닫기? 사용자는 명시 안함. 유지하는게 나을듯.

    def _on_copy_clicked(self):
        """[복사] 버튼 핸들러"""
        current_item = self.tag_list.currentItem()
        if not current_item:
            return

        tag = current_item.data(Qt.ItemDataRole.UserRole)
        if tag:
            QApplication.clipboard().setText(tag)
            # 피드백? (버튼 텍스트를 잠시 바꾼다거나..)
            original_text = self.btn_copy.text()
            self.btn_copy.setText("복사됨!")
            QTimer.singleShot(1000, lambda: self.btn_copy.setText(original_text))

    def resizeEvent(self, event):
        """위젯 크기 변경 시 닫기 버튼 위치 조정"""
        super().resizeEvent(event)

        # 닫기 버튼을 우측 상단에 배치 (여백 4px)
        if hasattr(self, 'btn_close'):
            btn_x = self.width() - self.btn_close.width() - get_scaled_size(4)
            btn_y = get_scaled_size(4)
            self.btn_close.move(btn_x, btn_y)
            self.btn_close.raise_()  # 최상위로 표시
