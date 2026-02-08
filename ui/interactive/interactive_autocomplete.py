import re
import json
from pathlib import Path
from PyQt6.QtCore import QObject, QEvent, Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QListWidget, QWidget, QLineEdit, QTextEdit, QHBoxLayout, QTextBrowser, QLabel, QVBoxLayout
from PyQt6.QtGui import QTextCursor, QKeyEvent, QPixmap
from utils.translator import korean_to_english


class TranslationWorker(QThread):
    """번역을 백그라운드 스레드에서 수행하는 워커 (재사용 가능)"""
    translation_completed = pyqtSignal(str, str)  # 원문, 번역문
    translation_failed = pyqtSignal()
    request_translation = pyqtSignal(str)  # 번역 요청 시그널

    def __init__(self):
        super().__init__()
        self.korean_text = ""
        self.is_running = True

    def set_text(self, text):
        """번역할 텍스트 설정"""
        self.korean_text = text

    def run(self):
        """스레드 메인 루프 - 계속 실행됨"""
        while self.is_running:
            if self.korean_text:
                try:
                    # 번역 수행
                    translated = korean_to_english(self.korean_text)
                    if translated:
                        self.translation_completed.emit(self.korean_text, translated)
                    else:
                        self.translation_failed.emit()
                except Exception as e:
                    print(f"번역 오류: {e}")
                    self.translation_failed.emit()

                # 번역 완료 후 텍스트 초기화
                self.korean_text = ""

            # CPU 사용률을 낮추기 위해 짧은 대기
            self.msleep(50)

    def stop(self):
        """스레드 종료"""
        self.is_running = False


class InteractiveAutocompleteManager(QObject):
    """
    Interactive Mode의 텍스트 입력 위젯에 대한 자동완성 기능을 관리하는 클래스.

    ✅ tags_unified.json 기반 자동완성 (분류, 관계, 설명 정보 포함)
    ✅ 위젯별로 다른 데이터셋 지원 (property 기반)

    사용 방법:
        # InteractiveWindow에서 생성
        self.autocomplete_manager = InteractiveAutocompleteManager(parent_window=self)

        # 블록에서 위젯 등록
        self.autocomplete_manager.register_widget(
            widget=my_textedit,
            dataset_id="clothing"  # 또는 "general", "artist" 등
        )

        # 또는 property로 지정 후 자동 감지
        my_textedit.setProperty("autocomplete_dataset", "clothing")

    자동완성을 비활성화하려면:
    2. 위젯 이름을 ignored_widget_names에 추가
    """

    # 🆕 시그널: 데이터 로딩 완료 시 발생
    data_loaded = pyqtSignal()

    def __init__(self, parent_window):
        """
        Args:
            parent_window: InteractiveWindow 인스턴스
        """
        super().__init__(parent=parent_window)

        self.parent_window = parent_window

        # 데이터셋 딕셔너리 (dataset_id -> tags_data)
        # TODO: tags_unified.json 기반으로 로딩
        self.datasets = {}

        # 위젯별 데이터셋 매핑 (widget -> dataset_id)
        self.widget_dataset_map = {}

        # 등록된 위젯 목록 (이벤트 필터 설치된 위젯들)
        self.registered_widgets = set()

        # 🆕 초기화 지연 (메인 윈도우가 완전히 준비된 후)
        self._initialized = False

        # 자동완성 리스트 위젯 (지연 생성)
        self.suggestion_list = None

        # 인스턴트 와일드카드용 값 표시 위젯
        self.value_display = None
        self.value_container = None
        self.image_container = None  # 이미지 표시용 별도 컨테이너
        self.image_label = None  # 이미지 표시용 라벨

        # 현재 활성 위젯
        self.current_widget = None
        self.current_suggestions = []

        # 인스턴트 와일드카드 딕셔너리 캐시
        self.instant_wildcards = {}
        self.instant_wildcards_tree = {}

        # 아티스트 이미지 캐시 (중복 처리 방지)
        self.last_processed_img_data = None
        self.last_processed_pixmap = None

        # 번역 관련 변수
        self.translation_timer = QTimer()
        self.translation_timer.setSingleShot(True)
        self.translation_timer.timeout.connect(self._perform_translation)
        self.last_translation_text = ""
        self.pending_translation_text = ""

        # 번역 워커 생성 (한 번만 생성하고 재사용)
        self.translation_worker = TranslationWorker()
        self.translation_worker.translation_completed.connect(self._on_translation_completed)
        self.translation_worker.translation_failed.connect(self._on_translation_failed)
        self.translation_worker.start()  # 스레드 시작 (프로그램 종료까지 계속 실행)

        # 설정
        self.min_chars = 2
        self.max_suggestions = 10

        self.popup = None
        self.tag_viewer = None  # TagViewer 위젯 (MainPromptBlock용)

        # 무시할 위젯 이름들
        self.ignored_widget_names = {
            "search_input", "exclude_input", "negative_prompt",
            "delay_input", "repeat_input", "timer_input", "count_input"
        }

        # 자동완성 활성화 상태
        self.enabled = True

        # 🆕 지연 초기화 타이머
        self.init_timer = QTimer()
        self.init_timer.setSingleShot(True)
        self.init_timer.timeout.connect(self._delayed_initialize)
        self.init_timer.start(1000)  # 1초 후 초기화

    def _delayed_initialize(self):
        """지연 초기화 - 윈도우가 완전히 준비된 후 실행"""
        try:
            if not self._initialized:
                self.timer = QTimer()
                self.timer.setSingleShot(True)
                self._load_datasets()
                self._discover_widgets()
                self.timer.timeout.connect(self.show_completions)
                self._initialized = True
                print(f"✅ InteractiveAutocompleteManager 초기화 완료 (등록된 위젯: {len(self.registered_widgets)}개)")
        except Exception as e:
            print(f"❌ InteractiveAutocompleteManager 초기화 실패: {e}")

    def _load_datasets(self):
        """데이터셋 로딩 - tags_unified.json 기반 (확장자 없는 'interactive' 파일)"""
        try:
            # 확장자 없는 파일명 (보안을 위해)
            json_path = Path(__file__).parent / "interactive"

            if not json_path.exists():
                print(f"⚠️ 태그 데이터 파일을 찾을 수 없습니다: {json_path}")
                self.datasets = {"general": {}}
                return

            # JSON 로딩 (확장자는 없지만 JSON 형식)
            with open(json_path, 'r', encoding='utf-8') as f:
                all_tags = json.load(f)

            print(f"📁 tags_unified.json 로딩 완료: {len(all_tags)}개 태그")

            # 분류별 데이터셋 생성 (올바른 group 이름 사용)
            self.datasets = {
                "general": all_tags,  # 전체 태그
                "clothing": self._filter_by_group(all_tags, "Clothing_Wear"),  # ✅ 수정
                "body": self._filter_by_multiple_groups(all_tags, [
                    "Person_Body", "Creatures", "NSFW", "Composition_Meta"
                ]),  # 🆕 다중 그룹 (캐릭터 외형)
                "food_object": self._filter_by_group(all_tags, "Food_Object"),
                "composition": self._filter_by_group(all_tags, "Composition_Meta"),
                "expression": self._filter_by_multiple_groups(all_tags, [
                    "Expression_Action", "Clothing_Wear", "Food_Object", "Culture_Misc", "NSFW"
                ]),  # 🆕 다중 그룹 (표정/행위 + 의상 etc + 음식/사물 + 문화 memes + NSFW 성행위)
                "creatures": self._filter_by_group(all_tags, "Creatures"),  # ✅ 수정 (복수형)
                "location": self._filter_by_group(all_tags, "Location_Background"),  # ✅ 수정
                "nsfw": self._filter_by_group(all_tags, "NSFW"),
                "culture": self._filter_by_group(all_tags, "Culture_Misc"),  # ✅ 수정
                "quality": self._create_quality_dataset(all_tags),  # 🆕 퀄리티 태그 데이터셋
                "character": self._create_character_dataset(),  # 🆕 캐릭터/작품 태그 데이터셋 (TagDataManager 기반)
            }

            # 데이터셋 크기 출력
            for dataset_id, tags in self.datasets.items():
                print(f"  - {dataset_id}: {len(tags)}개 태그")

            # 🆕 데이터 로딩 완료 시그널 발생
            self.data_loaded.emit()
            print("✅ InteractiveAutocompleteManager 데이터 로딩 완료 시그널 발생")

        except Exception as e:
            print(f"⚠️ 데이터셋 로딩 실패: {e}")
            import traceback
            traceback.print_exc()
            self.datasets = {"general": {}}
            
    @property
    def tags_data(self):
        """
        InteractiveWindow 등 외부에서 전체 태그 메타데이터에 접근하기 위한 프로퍼티
        """
        return self.datasets.get("general", {})

    def _filter_by_group(self, all_tags: dict, group_name: str) -> dict:
        """특정 group에 속하는 태그만 필터링"""
        return {
            tag: data for tag, data in all_tags.items()
            if data.get("group") == group_name
        }

    def _filter_by_multiple_groups(self, all_tags: dict, group_names: list) -> dict:
        """여러 group에 속하는 태그 필터링"""
        return {
            tag: data for tag, data in all_tags.items()
            if data.get("group") in group_names
        }

    def _filter_by_subgroups(self, all_tags: dict, group_name: str, subgroup_names: list) -> dict:
        """특정 그룹의 특정 서브그룹들만 필터링"""
        return {
            tag: data for tag, data in all_tags.items()
            if data.get("group") == group_name and data.get("subgroup") in subgroup_names
        }

    def _create_quality_dataset(self, all_tags: dict) -> dict:
        """
        퀄리티 태그 데이터셋 생성

        포함 항목:
        1. Composition_Meta 그룹의 lighting, scan 서브그룹 태그
        2. 하드코딩된 퀄리티 관련 태그 리스트

        Returns:
            dict: {tag: tag_data} 형식의 데이터셋
        """
        # 1. Composition_Meta의 lighting, scan 서브그룹 필터링
        quality_dataset = self._filter_by_subgroups(
            all_tags,
            "Composition_Meta",
            ["lighting", "scan"]
        )

        # 2. 하드코딩된 퀄리티 태그 리스트
        quality_autocomplete = [
            "best quality", "amazing quality", "great quality", "normal quality",
            "bad quality", "worst quality",
            "masterpiece", "top aesthetic", "very aesthetic", "aesthetic",
            "displeasing", "very displeasing",
            "location", "no text", "absurdres", "-0.8::feet::",
            "traditional media", "faux traditional media", "mixed media",
            "unconventional media",
            "acrylic paint (medium)", "ballpoint pen (medium)", "calligraphy brush (medium)",
            "colored pencil (medium)", "graphite (medium)", "ink (medium)",
            "marker (medium)", "millipen (medium)", "nib pen (medium)",
            "oil painting (medium)", "painting (medium)", "pastel (medium)",
            "pen (medium)", "watercolor (medium)", "watercolor pencil (medium)",
            "3d", "blender (medium)", "ai-generated", "ai-assisted",
            "anime screencap", "pixel art",
            "abstract", "surreal", "art nouveau", "impressionism", "ligne claire",
            "nihonga", "ukiyo-e", "realistic", "photorealistic", "retro artstyle",
            "painterly", "sketch", "lineart", "no lineart", "jaggy lines",
            "outline", "vector trace", "color trace", "production art",
            "animation paper", "game cg", "official art", "shikishi",
            "oekaki", "tegaki",
            "year 2014", "year 2015", "year 2016", "year 2017", "year 2018",
            "year 2019", "year 2020", "year 2021", "year 2022", "year 2023",
            "year 2024", "year 2025",
            "anime coloring", "colorful", "dark", "limited palette",
            "partially colored", "spot color", "monochrome", "greyscale",
            "muted color", "pale color", "pastel colors", "flat color",
            "high contrast", "sepia",
            "aqua theme", "black theme", "blue theme", "brown theme",
            "green theme", "grey theme", "orange theme", "pink theme",
            "purple theme", "red theme", "white theme", "yellow theme",
            "backlighting", "bloom", "bokeh", "chromatic aberration",
            "depth of field", "diffraction spikes", "dithering", "drop shadow",
            "emphasis lines", "speed lines", "motion lines", "glitch",
            "halftone", "lens flare", "motion blur", "soft focus",
        ]

        # 3. 하드코딩 리스트를 딕셔너리로 변환하여 병합 (중복 방지)
        for tag in quality_autocomplete:
            if tag not in quality_dataset:  # 이미 JSON에 있으면 스킵 (JSON 우선)
                quality_dataset[tag] = {
                    "group": "Composition_Meta",
                    "subgroup": "quality",
                    "freq": 5000,  # 높은 빈도로 설정 (우선 표시)
                    "description": "",  # 설명 없음
                    "keywords_kr": []   # 한글 키워드 없음
                }

        return quality_dataset

    def _create_character_dataset(self) -> dict:
        """
        캐릭터/작품 태그 데이터셋 생성 (TagDataManager 기반)

        TagDataManager의 copyright_dict와 character_dict_count를 사용하여
        캐릭터 및 작품 태그만 포함하는 데이터셋을 생성합니다.

        Returns:
            dict: {tag: tag_data} 형식의 데이터셋
        """
        character_dataset = {}

        try:
            # parent_window를 통해 app_context 접근
            app_context = getattr(self.parent_window, 'app_context', None)
            if not app_context:
                print("⚠️ app_context를 찾을 수 없습니다. character 데이터셋을 빈 상태로 생성합니다.")
                return character_dataset

            # TagDataManager 접근
            tag_data_manager = getattr(app_context, 'tag_data_manager', None)
            if not tag_data_manager:
                print("⚠️ TagDataManager를 찾을 수 없습니다. character 데이터셋을 빈 상태로 생성합니다.")
                return character_dataset

            # 1. copyright_dict (작품 태그)
            copyright_dict = getattr(tag_data_manager, 'copyright_dict', {})
            for tag, count in copyright_dict.items():
                character_dataset[tag] = {
                    "group": "Character",
                    "subgroup": "copyright",
                    "freq": count,
                    "description": "작품명",
                    "keywords_kr": []
                }

            # 2. character_dict_count (캐릭터 태그)
            character_dict_count = getattr(tag_data_manager, 'character_dict_count', {})
            for tag, count in character_dict_count.items():
                character_dataset[tag] = {
                    "group": "Character",
                    "subgroup": "character",
                    "freq": count,
                    "description": "캐릭터명",
                    "keywords_kr": []
                }

            print(f"✅ character 데이터셋 생성 완료: {len(character_dataset)}개 태그")

        except Exception as e:
            print(f"⚠️ character 데이터셋 생성 실패: {e}")
            import traceback
            traceback.print_exc()

        return character_dataset

    def _search_tags(self, query: str, dataset: dict) -> list:
        """
        태그 검색 엔진

        Args:
            query: 검색어 (영문 또는 한글)
            dataset: 검색 대상 데이터셋 (tag -> tag_data)

        Returns:
            [(tag, tag_data), ...] 형태의 결과 리스트 (최대 max_suggestions개)
            tag_data 포함 정보:
                - freq: 빈도수
                - group: 대분류 (예: "Clothing", "Body")
                - subgroup: 소분류 (예: "upper_body", "lower_body")
                - description: 한글 설명
                - keywords_kr: 한글 키워드
                - relations: 연관 태그 (siblings, parent, children, word_match)
                - source: 출처 (예: "KR_tags")
        """
        if not query or len(query) < self.min_chars:
            return []

        query_lower = query.lower()

        # 결과 분류 (우선순위별)
        exact_matches = []      # 정확한 태그명 일치
        starts_with = []        # 태그명 시작 일치
        keyword_matches = []    # 한글 키워드 일치
        contains = []           # 태그명 포함
        description_matches = []  # 설명 포함

        for tag, data in dataset.items():
            tag_lower = tag.lower()

            # 1. 정확한 태그명 일치
            if tag_lower == query_lower:
                exact_matches.append((tag, data))

            # 2. 태그명 시작 일치
            elif tag_lower.startswith(query_lower):
                starts_with.append((tag, data))

            # 3. 한글 키워드 일치
            elif self._match_korean_keywords(query, data.get("keywords_kr", "")):
                keyword_matches.append((tag, data))

            # 4. 태그명 포함
            elif query_lower in tag_lower:
                contains.append((tag, data))

            # 5. 설명 포함 (한글 검색인 경우만)
            elif self._is_korean(query) and query in data.get("description", ""):
                description_matches.append((tag, data))

        # 각 그룹 내에서 freq 기준 내림차순 정렬
        exact_matches.sort(key=lambda x: x[1].get("freq", 0), reverse=True)
        starts_with.sort(key=lambda x: x[1].get("freq", 0), reverse=True)
        keyword_matches.sort(key=lambda x: x[1].get("freq", 0), reverse=True)
        contains.sort(key=lambda x: x[1].get("freq", 0), reverse=True)
        description_matches.sort(key=lambda x: x[1].get("freq", 0), reverse=True)

        # 우선순위 순서로 결합
        results = exact_matches + starts_with + keyword_matches + contains + description_matches

        # max_suggestions 제한
        return results[:self.max_suggestions]

    def _match_korean_keywords(self, query: str, keywords_kr: str) -> bool:
        """
        한글 키워드 매칭

        Args:
            query: 검색어
            keywords_kr: 키워드 문자열 (예: "<인원>, 남자 1명, 남성 한명")

        Returns:
            매칭 여부
        """
        if not keywords_kr:
            return False

        # 쉼표로 분리된 키워드들
        keywords = [kw.strip() for kw in keywords_kr.split(',')]

        for keyword in keywords:
            # <태그> 형태 제거
            keyword_clean = keyword.replace('<', '').replace('>', '')

            # 부분 일치
            if query in keyword_clean:
                return True

        return False

    def _is_korean(self, text: str) -> bool:
        """텍스트에 한글이 포함되어 있는지 확인"""
        return any('\uac00' <= char <= '\ud7a3' for char in text)

    def _discover_widgets(self):
        """parent_window의 위젯들을 자동 발견하여 등록"""
        if not self.parent_window:
            return

        discovered_count = 0
        for widget in self.parent_window.findChildren((QTextEdit, QLineEdit)):
            # autocomplete_dataset 또는 autocomplete_filter property가 있는 위젯만 자동 등록
            dataset_id = widget.property("autocomplete_dataset") or widget.property("autocomplete_filter")
            if dataset_id:
                self.register_widget(widget, dataset_id)
                discovered_count += 1

        if discovered_count > 0:
            print(f"🔍 자동 발견: {discovered_count}개 위젯 등록")

    def register_widget(self, widget, dataset_id="general"):
        """
        위젯을 자동완성 매니저에 등록합니다.

        Args:
            widget: QTextEdit 또는 QLineEdit 인스턴스
            dataset_id: 사용할 데이터셋 ID (예: "general", "clothing", "artist")

        Example:
            # 블록에서 호출
            parent_window = self.window()
            if hasattr(parent_window, 'autocomplete_manager'):
                parent_window.autocomplete_manager.register_widget(
                    self.my_textedit,
                    dataset_id="clothing"
                )
        """
        if not isinstance(widget, (QTextEdit, QLineEdit)):
            print(f"⚠️ 등록 실패: {widget}은(는) QTextEdit/QLineEdit이 아닙니다")
            return

        if self._should_ignore_widget(widget):
            return

        # 위젯에 데이터셋 매핑 저장
        self.widget_dataset_map[widget] = dataset_id

        # 이벤트 필터 설치
        if widget not in self.registered_widgets:
            widget.installEventFilter(self)
            self.registered_widgets.add(widget)
            print(f"✅ 위젯 등록: {widget.objectName() or type(widget).__name__} → 데이터셋: {dataset_id}")

    def unregister_widget(self, widget):
        """위젯 등록 해제"""
        if widget in self.registered_widgets:
            widget.removeEventFilter(self)
            self.registered_widgets.discard(widget)
            if widget in self.widget_dataset_map:
                del self.widget_dataset_map[widget]
            print(f"🗑️ 위젯 등록 해제: {widget.objectName() or type(widget).__name__}")

    def _create_popup(self) -> QListWidget:
        """자동완성 목록을 보여줄 팝업 위젯 생성"""
        list_widget = QListWidget()
        list_widget.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        list_widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # 팝업 크기 설정
        list_widget.setMinimumWidth(350)  # 최소 너비
        list_widget.setMaximumWidth(500)  # 최대 너비
        list_widget.setMinimumHeight(200) # 최소 높이
        list_widget.setMaximumHeight(400) # 최대 높이

        list_widget.setStyleSheet("""
            QListWidget {
                border: 1px solid #444;
                background-color: #2B2B2B;
                color: #FFFFFF;
                font-size: 16px;
                padding: 8px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #3A3A3A;
                min-height: 20px;
            }
            QListWidget::item:hover {
                background-color: #4A4A4A;
            }
            QListWidget::item:selected {
                background-color: #1976D2;
            }
        """)
        list_widget.itemClicked.connect(self.on_item_clicked)

        # 아이템 포커스 변경 이벤트 연결 (키보드 탐색 시 아티스트 이미지 표시)
        list_widget.currentItemChanged.connect(self._on_item_focused)

        return list_widget

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """이벤트 필터: 텍스트 입력 위젯에서 자동완성 트리거"""
        if not self._initialized:
            return False

        # 팝업 외부 클릭 감지 (모든 위젯에서 마우스 클릭 감시)
        if event.type() == QEvent.Type.MouseButtonPress:
            if self.popup and self.popup.isVisible():
                if self._is_click_outside_popups(event):
                    self._hide_all_popups()

        # 감시 대상이 QLineEdit 또는 QTextEdit인지 확인
        if not isinstance(watched, (QLineEdit, QTextEdit)):
            # 다른 위젯으로 포커스 이동 시 팝업 닫기
            if event.type() == QEvent.Type.FocusIn:
                self._hide_all_popups()
            return super().eventFilter(watched, event)

        # 자동완성 제외 위젯 확인
        if self._should_ignore_widget(watched):
            return super().eventFilter(watched, event)

        # 팝업이 보이는 경우, 키보드 네비게이션을 최우선으로 처리
        if self.popup is not None and self.popup.isVisible() and event.type() == QEvent.Type.KeyPress:
            if self.handle_popup_navigation(event):
                return True # 이벤트 소비

        # 이벤트 타입에 따라 처리
        if event.type() == QEvent.Type.KeyRelease:
            self.on_key_release(watched, event)
        elif event.type() == QEvent.Type.FocusIn:
            # 다른 텍스트 위젯으로 포커스 이동 시 팝업 닫기 및 위젯 변경
            if self.current_widget and self.current_widget != watched:
                self._hide_all_popups()
            self.current_widget = watched

            # [USER REQUEST] 태그 뷰어 동적 관리 제거
            pass
        elif event.type() == QEvent.Type.FocusOut:
            # 약간의 지연을 주어, 팝업 클릭 시 바로 닫히지 않도록 함
            QTimer.singleShot(100, self._hide_popups_if_not_focused)
        elif event.type() == QEvent.Type.MouseButtonPress:
            # 마우스 클릭 시 커서 위치 변경 감지하여 팝업 닫기
            if self.popup and self.popup.isVisible():
                # 클릭 후 커서 위치 체크를 위해 지연 실행
                QTimer.singleShot(50, lambda: self._check_cursor_position_and_close(watched))

        return super().eventFilter(watched, event)

    def _should_ignore_widget(self, widget: QWidget) -> bool:
        """위젯이 자동완성을 무시해야 하는지 확인"""
        # # 1. 위젯 속성으로 직접 설정된 경우
        # if widget.property("autocomplete_ignore"):
        #     return True

        # 2. 위젯 이름이 제외 목록에 있는 경우
        widget_name = widget.objectName()
        if widget_name and widget_name in self.ignored_widget_names:
            return True

        # 3. 부모 위젯들 중 제외 목록에 있는 경우
        # parent = widget.parent()
        # while parent:
        #     parent_name = parent.objectName() if hasattr(parent, 'objectName') else None
        #     if parent_name and parent_name in self.ignored_parent_names:
        #         return True
        #     parent = parent.parent()

        # 4. 위젯이 비밀번호 입력 모드인 경우
        if isinstance(widget, QLineEdit) and widget.echoMode() == QLineEdit.EchoMode.Password:
            return True

        return False

    def add_ignored_widget_name(self, widget_name: str):
        """무시할 위젯 이름을 동적으로 추가"""
        self.ignored_widget_names.add(widget_name)
        print(f"✅ '{widget_name}' 위젯이 자동완성 제외 목록에 추가되었습니다.")

    def remove_ignored_widget_name(self, widget_name: str):
        """무시할 위젯 이름을 제거"""
        self.ignored_widget_names.discard(widget_name)
        print(f"✅ '{widget_name}' 위젯이 자동완성 제외 목록에서 제거되었습니다.")

    def add_ignored_parent_name(self, parent_name: str):
        """무시할 부모 위젯 이름을 동적으로 추가"""
        self.ignored_parent_names.add(parent_name)
        print(f"✅ '{parent_name}' 부모 위젯이 자동완성 제외 목록에 추가되었습니다.")

    def enable(self):
        """자동완성 기능을 활성화합니다."""
        if not hasattr(self, 'enabled'):
            self.enabled = True
        self.enabled = True
        print("Interactive Autocomplete enabled.")

    def disable(self):
        """자동완성 기능을 비활성화합니다."""
        if not hasattr(self, 'enabled'):
            self.enabled = False
        self.enabled = False
        self._hide_all_popups()
        print("Interactive Autocomplete disabled.")

    def on_key_release(self, widget: QWidget, event: QKeyEvent):
        """키 입력이 끝나면 타이머를 시작하여 자동완성 팝업을 띄울 준비"""
        nav_keys = [Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Escape]

        # 방향키(좌우)로 커서가 이동한 경우 팝업 닫기 체크
        if event.key() in [Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End]:
            if self.popup and self.popup.isVisible():
                self._check_cursor_position_and_close(widget)
        # 콤마 입력 시 즉시 팝업 닫기 (새 토큰 시작)
        elif event.key() == Qt.Key.Key_Comma:
            self._hide_popup()  # ✅ TagViewer는 유지
        elif event.key() not in nav_keys:
            self.current_widget = widget
            self.timer.start(200)

    def show_completions(self):
        """
        자동완성 목록을 표시하는 메서드 (타이핑 시 호출)

        ✅ 타이핑 시에는 무조건 일반 팝업만 표시 (가벼움)
        ✅ TagViewer는 FocusIn 이벤트에서만 표시 (eventFilter 참조)
        """
        if not self.current_widget or not self.enabled:
            return

        # 등록된 위젯이 아니면 무시
        if self.current_widget not in self.registered_widgets:
            return

        # 일반 팝업 생성 (지연 초기화)
        if self.popup is None:
            self.popup = self._create_popup()

        # 현재 활성 토큰 정보 가져오기
        try:
            token_info = self._get_active_token_info(self.current_widget)
        except:
            token_info = None
            return
        if not token_info or len(token_info['stripped_text']) < 1:
            self._hide_popup()  # ✅ TagViewer는 건드리지 않음
            return

        # NAI :: 가중치 값을 편집 중인 경우 자동완성 무시
        # 예: "0.7::pixel art" 에서 0.7을 편집할 때는 자동완성 안 함
        if token_info.get('is_weight_value', False):
            self._hide_popup()  # ✅ TagViewer는 건드리지 않음
            return

        self.active_token_info = token_info
        target_text = token_info['stripped_text']

        # % 로 시작하는 경우 번역 처리
        if target_text.startswith('%'):
            translation_text = target_text[1:]  # % 제거

            # 툴팁이 이미 표시 중이 아니고, 텍스트가 있고, 이전과 다른 경우에만 처리
            is_tooltip_showing = (self.popup and self.popup.isVisible()) or (self.value_container and self.value_container.isVisible())

            if translation_text and (not is_tooltip_showing or translation_text != self.last_translation_text):
                self.pending_translation_text = translation_text
                self.translation_timer.stop()

                # 마지막 문자가 '.' 또는 ' '인 경우 즉시 번역
                if translation_text.endswith('.') or translation_text.endswith(' '):
                    self._perform_translation()  # 즉시 번역 수행
                else:
                    # 그 외의 경우 0.5초 후에 번역 수행
                    self.translation_timer.start(500)
            elif not translation_text:
                self._hide_popup()  # ✅ TagViewer는 건드리지 않음
            return

        # $ 로 시작하는 경우 인스턴트 와일드카드 처리
        if target_text.startswith('$'):
            self._show_instant_wildcard_completions(target_text[1:])  # $ 제거하고 전달
            return

        # 인스턴트 와일드카드가 아닌 경우 값 표시 패널 숨기기
        if self.value_container:
            self.value_container.hide()

        # 일반 자동완성일 때 팝업 크기를 원래대로 복구
        if self.popup:
            self.popup.setMinimumWidth(350)
            self.popup.setMaximumWidth(500)

        # 현재 위젯의 데이터셋 가져오기
        # widget_dataset_map에서 먼저 확인하고, 없으면 property에서 확인
        dataset_id = self.widget_dataset_map.get(self.current_widget)
        if not dataset_id:
            dataset_id = self.current_widget.property("autocomplete_dataset") or self.current_widget.property("autocomplete_filter") or "general"
        current_dataset = self.datasets.get(dataset_id, {})

        if not current_dataset:
            # print(f"⚠️ 데이터셋 '{dataset_id}'이(가) 비어있습니다")
            self._hide_popup()  # ✅ TagViewer는 건드리지 않음
            return

        # 검색 실행
        matches = self._search_tags(target_text, current_dataset)

        # 매칭 결과가 없으면 팝업 숨기기
        if not matches:
            self._hide_popup()  # ✅ TagViewer는 건드리지 않음
            return

        # ✅ 타이핑 시에는 무조건 일반 팝업만 표시 (TagViewer 분기 제거)
        self.popup.clear()
        self._populate_popup_with_counts(matches)
        self.popup_at_cursor()

    def popup_at_cursor(self):
        """커서 위치에 팝업을 표시 (블록 위치에 따라 좌/우 배치)"""
        if not self.current_widget:
            return

        cursor_rect = self.current_widget.cursorRect()
        cursor_pos_global = self.current_widget.mapToGlobal(cursor_rect.bottomLeft())

        # 팝업 기본 위치
        popup_x = cursor_pos_global.x()
        popup_y = cursor_pos_global.y()

        # 위젯의 중앙 X 좌표 (글로벌)
        widget_rect = self.current_widget.rect()
        widget_center_global = self.current_widget.mapToGlobal(widget_rect.center())
        widget_center_x = widget_center_global.x()

        # 창의 중앙 X 좌표 계산
        if self.parent_window:
            window_center_x = self.parent_window.x() + self.parent_window.width() // 2

            # 팝업 너비 (기본값 또는 실제 크기)
            popup_width = self.popup.sizeHint().width()
            if popup_width < 300:  # 최소 너비 보장
                popup_width = 400

            # 위젯이 창 중앙보다 왼쪽에 있으면
            if widget_center_x < window_center_x:
                # 팝업을 위젯 우측에 배치 (커서 오른쪽 + 간격)
                popup_x = cursor_pos_global.x() + 20
            else:
                # 팝업을 위젯 좌측에 배치 (커서 왼쪽 - 팝업 너비 - 간격)
                popup_x = cursor_pos_global.x() - popup_width - 20

        self.popup.move(popup_x, popup_y)
        self.popup.setCurrentRow(0)
        self.popup.show()

    def _populate_popup_with_counts(self, matches):
        """매칭 결과를 count와 함께 팝업에 표시"""
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtCore import Qt

        for tag, tag_data in matches:
            # tag_data에서 freq 추출
            count = tag_data.get("freq", 0)

            # count를 포맷팅 (천 단위 구분자 추가)
            if count >= 1000000:
                count_text = f"{count/1000000:.1f}M"
            elif count >= 1000:
                count_text = f"{count/1000:.0f}k"
            else:
                count_text = str(count)

            # 아이템 텍스트 구성: 태그명은 왼쪽, count는 오른쪽
            display_text = f"{tag:<40} {count_text:>8}"

            item = QListWidgetItem(display_text)

            # 실제 태그명만 별도로 저장 (완성 시 사용)
            item.setData(Qt.ItemDataRole.UserRole, tag)

            # 툴팁 설정 - 메타데이터 포함
            tooltip_parts = [f"태그: {tag}", f"사용 횟수: {count:,}"]

            # 분류 정보 추가
            group = tag_data.get("group", "")
            subgroup = tag_data.get("subgroup", "")
            if group:
                group_kr = {
                    "Clothing_Wear": "의상/착용",
                    "Person_Body": "인체/신체",
                    "Food_Object": "음식/사물",
                    "Composition_Meta": "구도/메타",
                    "Expression_Action": "표정/행동",
                    "Creatures": "생물/종족",
                    "Location_Background": "장소/배경",
                    "NSFW": "NSFW",
                    "Culture_Misc": "문화/기타"
                }.get(group, group)
                tooltip_parts.append(f"분류: {group_kr}")
                if subgroup:
                    tooltip_parts.append(f"세부: {subgroup}")

            # 설명 추가
            description = tag_data.get("description", "")
            if description:
                tooltip_parts.append(f"설명: {description}")

            # 한글 키워드 추가
            keywords_kr = tag_data.get("keywords_kr", "")
            if keywords_kr:
                tooltip_parts.append(f"키워드: {keywords_kr}")

            item.setToolTip("\n".join(tooltip_parts))

            self.popup.addItem(item)

            # TODO: 아티스트 이미지 표시 기능 추가 예정

    def _on_item_focused(self, current, previous):
        """아이템 포커스 변경 시 (키보드 탐색) 아티스트 이미지 표시"""
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
        import base64
        import io
        from PIL import Image

        if not current:
            if self.image_container:
                self.image_container.hide()
            return

        item = current

        # UserRole + 2에서 아티스트 데이터 확인
        artist_data = item.data(Qt.ItemDataRole.UserRole + 2)

        # artist_data는 list 형태이고, [0]번 인덱스에 이미지 데이터가 있음
        if artist_data and isinstance(artist_data, list) and len(artist_data) > 0:
            # 이미지 데이터 추출 (첫 번째 요소)
            img_data_list = artist_data[0] if artist_data[0] else None

            if img_data_list:
                try:
                    # 이미지 컨테이너가 없으면 생성
                    if not self.image_container:
                        self._create_artist_image_container()

                    # 이전에 처리한 이미지와 동일한지 확인 (캐시 체크)
                    if img_data_list == self.last_processed_img_data and self.last_processed_pixmap:
                        pixmap = self.last_processed_pixmap
                    else:
                        # base64 디코딩 (img_data_list가 직접 base64 문자열임)
                        img_bytes = base64.b64decode(img_data_list)

                        # PIL 이미지로 변환
                        img = Image.open(io.BytesIO(img_bytes))

                        # 좌우 85픽셀씩 잘라내기 (검은색 썸네일 영역 제거)
                        width, height = img.size
                        if width > 170:  # 최소 170픽셀 이상일 때만 크롭
                            img = img.crop((85, 0, width - 85, height))

                        # 높이를 384px로 제한하면서 비율 유지
                        width, height = img.size
                        if height > 384:
                            new_height = 384
                            new_width = int(width * (384 / height))
                            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                        # QPixmap으로 변환
                        img_bytes = io.BytesIO()
                        img.save(img_bytes, format='PNG')
                        img_bytes.seek(0)

                        pixmap = QPixmap()
                        pixmap.loadFromData(img_bytes.read())

                        # 캐시에 저장
                        self.last_processed_img_data = img_data_list
                        self.last_processed_pixmap = pixmap

                    # 이미지 레이블에 설정
                    self.image_label.setPixmap(pixmap)

                    # 이미지 컨테이너를 팝업 옆에 표시
                    if self.popup.isVisible():
                        popup_rect = self.popup.geometry()
                        # 팝업의 오른쪽에 이미지 표시
                        image_pos = QPoint(popup_rect.right() + 5, popup_rect.top())
                        self.image_container.move(image_pos)
                        self.image_container.adjustSize()
                        self.image_container.show()

                except Exception as e:
                    print(f"아티스트 이미지 표시 오류: {e}")
                    if self.image_container:
                        self.image_container.hide()
            else:
                # 이미지 데이터가 없으면 컨테이너 숨김
                if self.image_container:
                    self.image_container.hide()
        else:
            # 아티스트 데이터가 없으면 컨테이너 숨김
            if self.image_container:
                self.image_container.hide()

    def _create_artist_image_container(self):
        """아티스트 이미지 표시용 컨테이너 생성"""
        from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
        from PyQt6.QtCore import Qt

        self.image_container = QWidget()
        self.image_container.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.image_container.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        image_layout = QVBoxLayout(self.image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)

        self.image_label = QLabel()
        self.image_label.setStyleSheet("""
            QLabel {
                border: 1px solid #444;
                background-color: #1E1E1E;
                padding: 4px;
            }
        """)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumWidth(150)
        self.image_label.setMaximumWidth(400)  # 너비 제한 증가
        self.image_label.setMaximumHeight(512)  # 높이 제한

        image_layout.addWidget(self.image_label)

    def on_item_clicked(self, item):
        """팝업 아이템 클릭 시 텍스트 완성 - 실제 태그명만 사용"""
        # UserRole에 저장된 실제 태그명 사용
        actual_tag = item.data(Qt.ItemDataRole.UserRole)
        if actual_tag:
            self.complete_text(actual_tag)
        else:
            # 폴백: 텍스트에서 태그명 추출
            display_text = item.text()
            tag_name = display_text.split()[0] if display_text else ""
            self.complete_text(tag_name)

    def complete_text(self, completion_text: str):
        """활성 토큰을 선택된 텍스트로 교체 (⚠️ 복잡한 로직 - 절대 수정하지 마세요)"""
        if not self.current_widget or not self.active_token_info:
            return

        widget = self.current_widget
        info = self.active_token_info

        # 그룹 아이템 선택 여부 확인 ($groupname: 형태)
        is_group_selection = completion_text.startswith('$') and completion_text.endswith(':')

        # 원본 텍스트의 뒤 공백/줄바꿈 추출 (모든 모드에서 동일하게 처리)
        original_text = info['text']
        trailing_whitespace = ''
        # 원본의 뒤쪽 공백/줄바꿈 찾기
        for i in range(len(original_text) - 1, -1, -1):
            if original_text[i] in ' \n\t\r':
                trailing_whitespace = original_text[i] + trailing_whitespace
            else:
                break

        # 인스턴트 와일드카드인 경우 값이 그대로 삽입됨 ($ 없이)
        if info['stripped_text'].startswith('$'):
            # completion_text는 이미 값이므로 그대로 사용
            pass
        else:
            # 일반 태그인 경우 괄호 구조 복원
            # Interactive Mode는 항상 NAI 모드이므로 괄호 이스케이프 불필요
            pass

        # 가중치 접두사/접미사가 있으면 추가 (예: "1.0::text ::")
        weight_prefix = info.get('weight_prefix', '')
        weight_suffix = info.get('weight_suffix', '')
        if weight_prefix:
            completion_text = weight_prefix + completion_text
        if weight_suffix:
            # NAI 권장: 태그와 :: 사이에 공백 추가 (예: "white background ::")
            completion_text = completion_text + ' ' + weight_suffix.lstrip()

        # 괄호 복원 후 뒤 공백 추가 (모든 모드에서 동일하게)
        final_text = self._restore_brackets(completion_text, info['prefix'], info['suffix'])

        # 자동 쉼표 추가 (trailing_whitespace가 없거나 줄바꿈인 경우)
        # QLineEdit인 경우 쉼표를 추가하지 않음
        # $로 시작하는 instant wildcard인 경우에도 쉼표를 추가하지 않음
        # 줄바꿈이 있는 경우에도 쉼표를 추가하고 그 뒤에 줄바꿈을 유지
        is_instant_wildcard = info['stripped_text'].startswith('$')

        if isinstance(widget, QLineEdit):
            # QLineEdit인 경우 쉼표 추가 안함
            final_text = final_text + trailing_whitespace
            added_comma_space = False
        elif is_instant_wildcard:
            # $로 시작하는 instant wildcard인 경우 쉼표 추가 안함
            final_text = final_text + trailing_whitespace
            added_comma_space = False
        elif not trailing_whitespace:
            final_text = final_text + ", "
            added_comma_space = True
        elif '\n' in trailing_whitespace:
            # 줄바꿈이 있는 경우: 쉼표 추가 후 줄바꿈 유지
            final_text = final_text + ", " + trailing_whitespace
            added_comma_space = True
        else:
            # 일반 공백만 있는 경우: 기존대로 유지
            final_text = final_text + trailing_whitespace
            added_comma_space = False

        # 가중치가 있는 경우 시작/끝 위치를 조정 (weight 부분도 교체하기 위해)
        start_pos = info['start']
        end_pos = info['end']
        if weight_prefix:
            # weight_prefix 길이만큼 시작 위치를 앞으로 이동
            start_pos = info['start'] - len(weight_prefix)
        if weight_suffix:
            # weight_suffix 길이만큼 끝 위치를 뒤로 이동
            end_pos = info['end'] + len(weight_suffix)

        if isinstance(widget, QTextEdit):
            cursor = widget.textCursor()
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(final_text)

            # 커서 위치 설정
            if trailing_whitespace and not added_comma_space:
                # 일반 공백만 있는 경우: 공백 이전 위치로
                new_cursor_pos = cursor.position() - len(trailing_whitespace)
                cursor.setPosition(new_cursor_pos)
            elif '\n' in trailing_whitespace:
                # 줄바꿈이 있는 경우: 쉼표와 공백 뒤, 줄바꿈 이전 위치로
                new_cursor_pos = cursor.position() - len(trailing_whitespace)
                cursor.setPosition(new_cursor_pos)
            # 그 외의 경우(쉼표 추가된 경우)는 커서가 이미 올바른 위치에 있음
            widget.setTextCursor(cursor)
        else: # QLineEdit
            current_text = widget.text()
            new_text = current_text[:start_pos] + final_text + current_text[end_pos:]
            widget.setText(new_text)

            # 커서 위치 설정
            if trailing_whitespace and not added_comma_space:
                # 일반 공백만 있는 경우: 공백 이전 위치로
                new_cursor_pos = start_pos + len(final_text) - len(trailing_whitespace)
                widget.setCursorPosition(new_cursor_pos)
            elif '\n' in trailing_whitespace:
                # 줄바꿈이 있는 경우: 쉼표와 공백 뒤, 줄바꿈 이전 위치로
                new_cursor_pos = start_pos + len(final_text) - len(trailing_whitespace)
                widget.setCursorPosition(new_cursor_pos)
            else:
                # 쉼표와 공백을 추가한 경우: 텍스트 끝(공백 뒤)으로
                new_cursor_pos = start_pos + len(final_text)
                widget.setCursorPosition(new_cursor_pos)

        self._hide_popup()  # ✅ TagViewer는 유지 (입력 필드에 여전히 포커스)
        widget.setFocus() # 텍스트 완성 후 원래 위젯으로 포커스 복귀

        # 그룹 아이템을 선택한 경우, 자동으로 해당 그룹의 아이템들을 표시
        if is_group_selection:
            # 약간의 지연을 주어 텍스트 삽입이 완료된 후 실행
            QTimer.singleShot(50, self.show_completions)

    def handle_popup_navigation(self, event: QKeyEvent) -> bool:
        """팝업에서의 키보드 네비게이션 처리 (⚠️ 복잡한 로직 - 절대 수정하지 마세요)"""
        key = event.key()
        if key in [Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab]:
            current_item = self.popup.currentItem()

            # 엔터를 누르는 시점에 토큰 정보를 다시 가져옴
            # (타이핑 중에 저장된 active_token_info가 현재 텍스트와 다를 수 있음)
            if self.current_widget:
                fresh_token_info = self._get_active_token_info(self.current_widget)
                if fresh_token_info:
                    self.active_token_info = fresh_token_info

            if current_item:
                # UserRole에서 실제 값/태그명 가져오기
                # 인스턴트 와일드카드의 경우 값이, 일반 태그의 경우 태그명이 저장됨
                actual_value = current_item.data(Qt.ItemDataRole.UserRole)
                if actual_value:
                    self.complete_text(actual_value)
                else:
                    # 폴백: 텍스트에서 태그명 추출
                    display_text = current_item.text()
                    tag_name = display_text.split()[0] if display_text else ""
                    self.complete_text(tag_name)
            else:
                self._hide_popup()  # ✅ TagViewer는 유지 (입력 필드에 여전히 포커스)
            return True
        elif key == Qt.Key.Key_Up:
            self.popup.setCurrentRow(max(0, self.popup.currentRow() - 1))
            return True
        elif key == Qt.Key.Key_Down:
            self.popup.setCurrentRow(min(self.popup.count() - 1, self.popup.currentRow() + 1))
            return True
        elif key == Qt.Key.Key_Escape:
            self._hide_popup()  # ✅ TagViewer는 유지 (입력 필드에 여전히 포커스)
            return True
        return False

    def _get_active_token_info(self, widget: QWidget) -> dict:
        """현재 커서 위치의 단어(토큰), 괄호, 시작/끝 위치를 반환 (⚠️ 복잡한 로직 - 절대 수정하지 마세요)"""
        text = widget.toPlainText() if isinstance(widget, QTextEdit) else widget.text()
        pos = widget.textCursor().position() if isinstance(widget, QTextEdit) else widget.cursorPosition()

        # 왼쪽 경계(콤마 또는 시작) 찾기
        start_pos = text.rfind(',', 0, pos)
        start_pos = 0 if start_pos == -1 else start_pos + 1

        # 오른쪽 경계(콤마 또는 끝) 찾기
        end_pos = text.find(',', pos)
        if end_pos == -1:
            end_pos = len(text)

        # 커서가 콤마 바로 뒤에 있을 때, 빈 토큰으로 인식하도록 보정
        if pos > start_pos and text[pos-1] in ', ':
            start_pos = pos

        # 앞뒤 공백 제거
        while start_pos < end_pos and text[start_pos].isspace():
            start_pos += 1

        token = text[start_pos:end_pos]

        # NAI :: 문법 처리 - 커서 위치에 따라 검색 범위 조정
        weight_prefix = ""  # 가중치 부분을 저장할 변수
        if '::' in token:
            # 커서 위치 기준으로 가장 가까운 :: 찾기
            # 예: "1.0:: text ::" 에서 커서가 text 위치에 있으면
            # 왼쪽 ::와 오른쪽 :: 모두 찾아서 커서 위치 기준으로 처리

            cursor_offset = pos - start_pos  # 토큰 내에서의 커서 위치

            # 커서 왼쪽에서 가장 가까운 :: 찾기
            left_double_colon = token.rfind('::', 0, cursor_offset)
            # 커서 오른쪽에서 가장 가까운 :: 찾기
            right_double_colon = token.find('::', cursor_offset)

            # 뒤쪽 :: 이후 부분을 suffix로 저장할 변수
            weight_suffix = ""

            if left_double_colon != -1 and right_double_colon != -1:
                # 양쪽 모두 ::가 있는 경우 (예: "1.0:: text ::")
                # 커서가 두 :: 사이에 있으므로, 왼쪽 :: 이후부터 오른쪽 :: 이전까지가 검색 범위
                weight_prefix = token[:left_double_colon + 2]  # "1.0::" 부분 저장
                weight_suffix = token[right_double_colon:]  # "::" 또는 "::1.0" 부분 저장
                token = token[left_double_colon + 2:right_double_colon]  # 중간 텍스트만 검색
                start_pos = start_pos + left_double_colon + 2
                end_pos = start_pos + len(token)
            elif left_double_colon != -1:
                # 커서 왼쪽에만 ::가 있는 경우 (예: "0.5::arti")
                # weight 부분은 유지하고 그 이후 텍스트로 검색
                weight_prefix = token[:left_double_colon + 2]  # "0.5::" 부분 저장
                token = token[left_double_colon + 2:]  # "arti" 부분만 검색
                start_pos = start_pos + left_double_colon + 2
            elif right_double_colon != -1:
                # 커서 오른쪽에만 ::가 있는 경우 (예: "tag::")
                # NAI에서는 "1.0::tag::" 형태가 일반적이므로 이 케이스는 드묾
                # :: 이후를 suffix로 보존하여 자동완성 후에도 유지
                weight_suffix = token[right_double_colon:]  # "::" 부분 저장
                token = token[:right_double_colon]
                end_pos = start_pos + right_double_colon
        else:
            weight_suffix = ""

        stripped_token, prefix, suffix = self._strip_brackets(token)

        # NAI :: 가중치 값을 편집 중인 경우 자동완성 무시
        # 예: "0.7::pixel art" 에서 0.7을 편집할 때
        # weight_suffix가 있고 (:: 로 시작) stripped_token이 숫자 형태인 경우
        is_weight_value = False
        if weight_suffix and weight_suffix.startswith('::'):
            # 숫자 형태인지 확인 (정수, 소수, 음수 모두 포함)
            stripped_check = stripped_token.strip()
            if stripped_check:
                try:
                    float(stripped_check)
                    is_weight_value = True
                except ValueError:
                    pass

        return {
            'text': token,
            'stripped_text': stripped_token.strip(),  # 모든 모드에서 동일하게 strip() 사용
            'prefix': prefix,
            'suffix': suffix,
            'start': start_pos,
            'end': end_pos,
            'weight_prefix': weight_prefix,  # 가중치 접두사 (예: "1.0::")
            'weight_suffix': weight_suffix,  # 가중치 접미사 (예: "::" 또는 "::1.0")
            'is_weight_value': is_weight_value  # 가중치 값 편집 중 여부
        }

    def _strip_brackets(self, keyword: str) -> tuple[str, str, str]:
        """단어 앞뒤의 괄호, NAI :: 가중치 문법, 그리고 - prefix를 분리합니다. (⚠️ 복잡한 로직 - 절대 수정하지 마세요)

        중요: 괄호는 쌍을 이루는 경우에만 prefix/suffix로 처리합니다.
        예: "(tag)" -> prefix="(", suffix=")", stripped="tag"
        예: "blade (galaxist)" -> prefix="", suffix="", stripped="blade (galaxist)"
             (내부 괄호는 태그의 일부이므로 분리하지 않음)
        """
        if not isinstance(keyword, str):
            return "", "", ""

        keyword_stripped = keyword.strip()

        # NAI :: 가중치 문법 처리
        # :: 이후 부분은 suffix로 처리하여 자동완성 후에도 유지
        double_colon_suffix = ""
        if '::' in keyword_stripped:
            parts = keyword_stripped.split('::', 1)
            keyword_stripped = parts[0]
            if len(parts) > 1:
                double_colon_suffix = '::' + parts[1]

        # - prefix 처리 (항상 적용)
        # 예: "-tw" -> prefix="-", stripped="tw"
        minus_prefix = ""
        if keyword_stripped.startswith('-'):
            minus_prefix = '-'
            keyword_stripped = keyword_stripped[1:]  # '-' 제거

        # 괄호 처리 - 쌍을 이루는 괄호만 prefix/suffix로 처리
        # 괄호 쌍 정의
        bracket_pairs = {'(': ')', '[': ']', '{': '}'}

        prefix = ''
        suffix = ''

        # 앞쪽 여는 괄호 찾기
        prefix_match = re.match(r'^[\{\[\(]+', keyword_stripped)
        if prefix_match:
            potential_prefix = prefix_match.group(0)
            # 뒤쪽에서 매칭되는 닫는 괄호 찾기
            suffix_match = re.search(r'[\}\]\)]+$', keyword_stripped)
            if suffix_match:
                potential_suffix = suffix_match.group(0)

                # 괄호 쌍이 올바르게 매칭되는지 확인
                # 예: "((tag))" -> prefix="((", suffix="))"
                # 예: "(tag" -> prefix="", suffix="" (쌍이 안 맞음)
                matched_prefix = ''
                matched_suffix = ''

                # 앞에서부터 여는 괄호, 뒤에서부터 닫는 괄호를 매칭
                suffix_reversed = potential_suffix[::-1]  # 뒤집어서 앞에서부터 비교
                for i, open_bracket in enumerate(potential_prefix):
                    if i < len(suffix_reversed):
                        close_bracket = suffix_reversed[i]
                        # 괄호 쌍이 맞는지 확인
                        if bracket_pairs.get(open_bracket) == close_bracket:
                            matched_prefix += open_bracket
                            matched_suffix = close_bracket + matched_suffix
                        else:
                            break
                    else:
                        break

                prefix = matched_prefix
                suffix = matched_suffix

        # prefix에 minus_prefix 추가
        prefix = minus_prefix + prefix

        # :: 가중치를 suffix에 추가
        suffix = suffix + double_colon_suffix

        # stripped_keyword 계산
        start_idx = len(prefix) - len(minus_prefix)  # minus_prefix는 이미 제거됨
        end_idx = len(keyword_stripped) - (len(suffix) - len(double_colon_suffix))

        if start_idx >= end_idx:
            # 괄호만 있는 경우 등 예외 처리
            return keyword_stripped, minus_prefix, double_colon_suffix

        stripped_keyword = keyword_stripped[start_idx:end_idx]
        return stripped_keyword, prefix, suffix

    def _restore_brackets(self, keyword, prefix, suffix):
        """분리했던 괄호를 다시 합칩니다."""
        return f"{prefix}{keyword}{suffix}"

    def _check_cursor_position_and_close(self, widget: QWidget):
        """커서 위치가 현재 편집 중인 토큰을 벗어났는지 확인하고 팝업을 닫습니다."""
        if not self.popup or not self.popup.isVisible():
            return

        # 현재 커서 위치의 토큰 정보 가져오기
        current_token_info = self._get_active_token_info(widget)

        # 이전에 저장된 토큰 정보와 비교
        if hasattr(self, 'active_token_info') and self.active_token_info:
            # 커서가 다른 토큰으로 이동했거나 토큰 범위를 벗어난 경우
            if (not current_token_info or
                current_token_info['start'] != self.active_token_info['start'] or
                current_token_info['end'] != self.active_token_info['end']):
                self._hide_popup()  # ✅ TagViewer는 유지 (입력 필드에 여전히 포커스)
                self.active_token_info = None

    def _hide_popups_if_not_focused(self):
        """포커스가 없으면 모든 팝업을 숨깁니다."""
        # 팝업이나 TagViewer에 포커스가 있으면 숨기지 않음
        has_popup_focus = self.popup and self.popup.hasFocus()
        has_viewer_focus = False
        focused_widget = None  # 초기화 추가

        # TagViewer 또는 그 자식 위젯들이 포커스를 가지고 있는지 확인
        if self.tag_viewer and self.tag_viewer.isVisible():
            from PyQt6.QtWidgets import QApplication
            focused_widget = QApplication.focusWidget()
            if focused_widget:
                # 포커스된 위젯이 TagViewer의 자식인지 확인
                parent = focused_widget
                while parent:
                    if parent == self.tag_viewer:
                        has_viewer_focus = True
                        break
                    parent = parent.parent()

        if not has_popup_focus and not has_viewer_focus:
            # 현재 입력 위젯이 포커스를 가지고 있으면 닫지 않음
            if focused_widget and focused_widget == self.current_widget:
                return

            self._hide_all_popups()

    def _is_click_outside_popups(self, event) -> bool:
        """클릭 위치가 팝업 관련 위젯들 외부인지 확인합니다."""
        try:
            # PyQt6에서 마우스 이벤트의 전역 위치 가져오기
            if hasattr(event, 'globalPosition'):
                click_pos = event.globalPosition().toPoint()
            elif hasattr(event, 'globalPos'):
                click_pos = event.globalPos()
            else:
                return False

            # 각 팝업 위젯의 geometry를 체크
            is_inside_popup = (
                self.popup and
                self.popup.isVisible() and
                self.popup.geometry().contains(click_pos)
            )
            is_inside_value = (
                self.value_container and
                self.value_container.isVisible() and
                self.value_container.geometry().contains(click_pos)
            )
            is_inside_image = (
                self.image_container and
                self.image_container.isVisible() and
                self.image_container.geometry().contains(click_pos)
            )
            is_inside_viewer = (
                self.tag_viewer and
                self.tag_viewer.isVisible() and
                self.tag_viewer.geometry().contains(click_pos)
            )
            
            # 현재 입력 중인 위젯 내부 클릭인지 확인
            is_inside_current_widget = (
                self.current_widget and
                self.current_widget.isVisible() and
                self.current_widget.rect().contains(self.current_widget.mapFromGlobal(click_pos))
            )

            # 모든 팝업 위젯 외부 클릭이고, 현재 입력 위젯 외부 클릭이면 True
            return not (is_inside_popup or is_inside_value or is_inside_image or is_inside_viewer or is_inside_current_widget)
        except Exception:
            return False

    def _hide_popup(self):
        """일반 자동완성 팝업만 숨깁니다 (타이핑 시 사용)"""
        if self.popup:
            self.popup.hide()
        if self.value_container:
            self.value_container.hide()
        if self.image_container:
            self.image_container.hide()
        # 번역 타이머도 중지
        if hasattr(self, 'translation_timer'):
            self.translation_timer.stop()

    def _hide_tag_viewer(self):
        """TagViewer만 숨깁니다 (FocusOut 시 사용)"""
        if self.tag_viewer:
            self.tag_viewer.hide()

    def _hide_all_popups(self):
        """모든 팝업을 숨깁니다 (전체 비활성화 시 사용)"""
        self._hide_popup()
        self._hide_tag_viewer()

    def cleanup(self):
        """프로그램 종료 시 리소스 정리"""
        # TagViewer 정리
        if hasattr(self, 'tag_viewer') and self.tag_viewer:
            self.tag_viewer.hide()
            self.tag_viewer.deleteLater()
            self.tag_viewer = None

        # 번역 워커 종료
        if hasattr(self, 'translation_worker') and self.translation_worker:
            self.translation_worker.stop()  # 플래그 설정
            self.translation_worker.quit()   # 이벤트 루프 종료
            self.translation_worker.wait(1000)  # 최대 1초 대기
            self.translation_worker.deleteLater()

    def _get_instant_wildcards(self):
        """인스턴트 와일드카드 딕셔너리와 트리를 가져옵니다.

        다른 모듈에서 instant_wildcards_tree에 접근하는 방법:

        1. middle_section_controller를 통해 직접 접근:
           instant_module = self.app_context.middle_section_controller.get_module_instance("InstantWildcardModule")
           if instant_module:
               dict_data, tree_data = instant_module.get_wildcards()

        2. WildcardManager를 통해 접근 (캐시된 데이터):
           wildcard_manager = self.app_context.wildcard_manager
           dict_data, tree_data = wildcard_manager.get_instant_wildcards()
           # 또는 개별적으로:
           tree_data = wildcard_manager.get_instant_wildcard_tree()
           dict_data = wildcard_manager.get_instant_wildcard_dict()
        """
        try:
            # middle_section_controller를 통해 InstantWildcardModule 접근
            if self.main_window and hasattr(self.main_window, 'middle_section_controller'):
                instant_module = self.main_window.middle_section_controller.get_module_instance("InstantWildcardModule")
                if instant_module:
                    result = instant_module.get_wildcards()
                    # 튜플로 반환되는 경우 처리
                    if isinstance(result, tuple) and len(result) == 2:
                        return result  # (dict, tree)
                    else:
                        # 이전 버전 호환성 - 딕셔너리만 반환하는 경우
                        return result, {}
        except Exception as e:
            print(f"⚠️ 인스턴트 와일드카드 가져오기 실패: {e}")
        return {}, {}

    def _get_artist_data(self):
        """ArtistThumbModule의 artist_data를 가져옵니다.

        사용 방법:
        artist_data = self._get_artist_data()
        # artist_data는 아티스트 이름을 키로 하는 딕셔너리
        # 각 값은 아티스트 정보 (스타일, 설명 등)를 포함

        다른 모듈에서 ArtistThumbModule에 접근하는 방법:

        1. TabController를 통한 직접 접근 (app_context 사용):
           right_view = self.app_context.main_window.image_window
           artist_module = right_view.tab_controller.get_tab_instance('ArtistThumbModule')
           if artist_module:
               artist_data = artist_module.get_artist_data()
               artist_list = artist_module.get_artist_list()

        2. MainWindow를 통한 접근:
           if self.main_window and hasattr(self.main_window, 'image_window'):
               right_view = self.main_window.image_window
               artist_module = right_view.tab_controller.get_tab_instance('ArtistThumbModule')
               if artist_module:
                   artist_data = artist_module.get_artist_data()
        """
        try:
            # main_window의 image_window (RightView)를 통해 TabController 접근
            if self.main_window and hasattr(self.main_window, 'image_window'):
                right_view = self.main_window.image_window
                if hasattr(right_view, 'tab_controller'):
                    artist_module = right_view.tab_controller.get_tab_instance('ArtistThumbModule')
                    if artist_module:
                        return artist_module.get_artist_data()
        except Exception as e:
            print(f"⚠️ ArtistThumbModule 데이터 가져오기 실패: {e}")
        return {}

    def _get_artist_list(self):
        """ArtistThumbModule의 artist_list를 가져옵니다.

        사용 방법:
        artist_list = self._get_artist_list()
        # artist_list는 아티스트 이름 리스트
        """
        try:
            # main_window의 image_window (RightView)를 통해 TabController 접근
            if self.main_window and hasattr(self.main_window, 'image_window'):
                right_view = self.main_window.image_window
                if hasattr(right_view, 'tab_controller'):
                    artist_module = right_view.tab_controller.get_tab_instance('ArtistThumbModule')
                    if artist_module:
                        return artist_module.get_artist_list()
        except Exception as e:
            print(f"⚠️ ArtistThumbModule 리스트 가져오기 실패: {e}")
        return []

    def _apply_filter(self, matches: list, filter_category: str) -> list:
        """필터 카테고리에 따라 태그 목록을 필터링합니다.

        위젯에서 사용 방법:
        ```python
        # 작가태그만 표시
        artist_input = QTextEdit()
        artist_input.setProperty("autocomplete_filter", "artist")

        # 일반 태그만 표시 (작가태그 제외)
        general_input = QTextEdit()
        general_input.setProperty("autocomplete_filter", "general")
        ```

        Args:
            matches: [(tag, count), ...] 형태의 매칭 결과
            filter_category: "artist" 또는 "general"

        Returns:
            필터링된 매칭 결과
        """
        if not filter_category or filter_category == "all":
            return matches

        # 아티스트 리스트 가져오기
        artist_list = self._get_artist_list()

        filtered = []

        for tag, count in matches:
            if filter_category == "artist":
                # artist: 접두사가 있거나 artist_list에 있는 태그만
                if tag.startswith("artist:") or tag in artist_list:
                    filtered.append((tag, count))

            elif filter_category == "general":
                # 일반 태그 (artist: 제외, artist_list에 없는 태그만)
                if not tag.startswith("artist:") and tag not in artist_list:
                    filtered.append((tag, count))

        return filtered

    def _perform_translation(self):
        """번역을 백그라운드 스레드에서 수행합니다."""
        if not self.pending_translation_text:
            return

        # 워커에 새 텍스트 설정 (스레드는 이미 실행 중)
        if self.translation_worker:
            self.translation_worker.set_text(self.pending_translation_text)
            # 현재 텍스트를 마지막 번역 텍스트로 저장
            self.last_translation_text = self.pending_translation_text

    def _on_translation_completed(self, korean_text: str, english_text: str):
        """번역이 완료되면 호출됩니다."""
        self._show_translation_tooltip(korean_text, english_text)
        # 워커는 계속 유지 (재사용을 위해)

    def _on_translation_failed(self):
        """번역이 실패하면 호출됩니다."""
        self._hide_popup()  # ✅ TagViewer는 유지 (입력 필드에 여전히 포커스)
        # 워커는 계속 유지 (재사용을 위해)

    def _show_translation_tooltip(self, korean_text: str, english_text: str):
        """번역 결과를 툴팁으로 표시합니다."""
        # 팝업이 없으면 생성
        if self.popup is None:
            self.popup = self._create_popup()

        # 번역 팝업은 더 작은 너비 설정
        self.popup.setMinimumWidth(150)
        self.popup.setMaximumWidth(200)

        # 팝업 초기화
        self.popup.clear()

        # Accept 항목만 추가 (영문 텍스트 제외)
        accept_item = "✅ Accept"
        item = self.popup.addItem(accept_item)
        self.popup.item(0).setData(Qt.ItemDataRole.UserRole, english_text)
        self.popup.item(0).setToolTip(f"클릭하여 영문 번역을 삽입합니다.")

        # 값 표시 컨테이너 생성 및 업데이트
        if not self.value_container:
            self._create_value_display()

        # 번역용으로 더 넓은 너비 설정
        self.value_display.setMinimumWidth(450)
        self.value_display.setMaximumWidth(550)

        # 한글 원문을 값 표시 패널에 표시
        self.value_display.clear()
        html_content = f"""
        <div style="color: #E0E0E0; font-size: 14px;">
            <div style="color: #90CAF9; margin-bottom: 8px;">📝 원문 (한글):</div>
            <div style="background-color: #263238; padding: 8px; border-radius: 4px; margin-bottom: 12px;">
                {korean_text}
            </div>
            <div style="color: #A5D6A7; margin-bottom: 8px;">🔤 번역 (영어):</div>
            <div style="background-color: #263238; padding: 8px; border-radius: 4px;">
                {english_text}
            </div>
        </div>
        """
        self.value_display.setHtml(html_content)

        # 팝업과 값 패널 표시
        self.popup_at_cursor_with_value()

    def _show_instant_wildcard_completions(self, search_text: str):
        """인스턴트 와일드카드 자동완성을 표시합니다."""
        # 인스턴트 와일드카드 딕셔너리와 트리 가져오기
        self.instant_wildcards, self.instant_wildcards_tree = self._get_instant_wildcards()

        if not self.instant_wildcards and not self.instant_wildcards_tree:
            self._hide_popup()  # ✅ TagViewer는 유지 (입력 필드에 여전히 포커스)
            return

        matching_keys = []
        search_lower = search_text.lower() if search_text else ""

        # $filename: 형태의 그룹 검색 확인
        is_group_search = False
        group_name = None
        group_search_text = search_lower

        if not (search_text.startswith("artist")) and ":" in search_text:
            # $filename: 형태 - 해당 그룹 내에서만 검색
            parts = search_text.split(":", 1)
            group_name = parts[0]  # $ 제거
            group_search_text = parts[1].lower() if len(parts) > 1 else ""
            is_group_search = True

        # 그룹 검색인 경우
        if is_group_search and group_name in self.instant_wildcards_tree:
            # 특정 그룹 내에서만 검색
            group_items = self.instant_wildcards_tree[group_name]

            exact_matches = []
            starts_with = []
            word_starts = []
            contains = []

            for key in group_items.keys():
                key_lower = key.lower()

                if not group_search_text:
                    # 그룹 내 모든 키
                    contains.append(key)  # matching_keys가 아닌 contains에 추가
                elif key_lower == group_search_text:
                    exact_matches.append(key)
                elif key_lower.startswith(group_search_text):
                    starts_with.append(key)
                else:
                    import re
                    words = re.split(r'[\s_\-]+', key_lower)
                    word_found = False
                    for word in words:
                        if word.startswith(group_search_text):
                            word_starts.append(key)
                            word_found = True
                            break

                    if not word_found and group_search_text in key_lower:
                        contains.append(key)

            matching_keys = exact_matches + starts_with + word_starts + contains

        else:
            # 일반 검색 - 그룹명을 1순위로, 그 다음 개별 키
            group_matches = []  # 그룹명 매칭
            exact_matches = []
            starts_with = []
            word_starts = []
            contains = []

            # 1. 그룹명(파일명) 검색
            for group_name in self.instant_wildcards_tree.keys():
                group_lower = group_name.lower()

                if not search_text:
                    # 검색어가 없으면 모든 그룹 추가
                    group_matches.append(f"${group_name}")
                elif group_lower == search_lower:
                    group_matches.insert(0, f"${group_name}")  # 정확한 일치는 맨 앞에
                elif group_lower.startswith(search_lower):
                    group_matches.append(f"${group_name}")
                elif search_lower in group_lower:
                    group_matches.append(f"${group_name}")

            # 2. 개별 와일드카드 키 검색
            for key in self.instant_wildcards.keys():
                key_lower = key.lower()

                if not search_text:
                    contains.append(key)  # matching_keys가 아닌 contains에 추가
                elif key_lower == search_lower:
                    exact_matches.append(key)
                elif key_lower.startswith(search_lower):
                    starts_with.append(key)
                else:
                    import re
                    words = re.split(r'[\s_\-]+', key_lower)
                    word_found = False
                    for word in words:
                        if word.startswith(search_lower):
                            word_starts.append(key)
                            word_found = True
                            break

                    if not word_found and search_lower in key_lower:
                        contains.append(key)

            # 그룹을 최우선으로, 그 다음 개별 키
            matching_keys = group_matches + exact_matches + starts_with + word_starts + contains

        # 중복 제거 (순서 유지)
        seen = set()
        unique_keys = []
        for key in matching_keys:
            if key not in seen:
                seen.add(key)
                unique_keys.append(key)
        matching_keys = unique_keys

        if not matching_keys:
            self._hide_popup()  # ✅ TagViewer는 유지 (입력 필드에 여전히 포커스)
            return

        # 최대 10개까지만 표시
        matching_keys = matching_keys[:self.max_suggestions]

        # 팝업에 키 목록 표시
        self.popup.clear()
        self._populate_instant_wildcard_popup(matching_keys)

        # 값 표시 패널 생성 및 업데이트
        if not self.value_container:
            self._create_value_display()

        # 인스턴트 와일드카드용 너비로 복구 (번역용보다 좁게)
        self.value_display.setMinimumWidth(300)
        self.value_display.setMaximumWidth(400)

        # 일반 팝업 크기로 복구
        if self.popup:
            self.popup.setMinimumWidth(350)
            self.popup.setMaximumWidth(500)

        # 첫 번째 항목의 값 표시
        if matching_keys:
            self._update_value_display(matching_keys[0])

        # 팝업과 값 패널 위치 조정
        self.popup_at_cursor_with_value()

    def _create_value_display(self):
        """인스턴트 와일드카드 값을 표시할 패널을 생성합니다."""
        # 텍스트 값 표시 컨테이너
        self.value_container = QWidget()
        self.value_container.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.value_container.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QHBoxLayout(self.value_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.value_display = QTextBrowser()
        self.value_display.setReadOnly(True)
        self.value_display.setMinimumWidth(300)
        self.value_display.setMaximumWidth(400)

        self.value_display.setStyleSheet("""
            QTextBrowser {
                border: 1px solid #444;
                background-color: #1E1E1E;
                color: #CCCCCC;
                font-size: 14px;
                padding: 12px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
        """)

        layout.addWidget(self.value_display)

        # 이미지 표시용 별도 컨테이너
        self.image_container = QWidget()
        self.image_container.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.image_container.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        image_layout = QVBoxLayout(self.image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)

        self.image_label = QLabel()
        self.image_label.setStyleSheet("""
            QLabel {
                border: 1px solid #444;
                background-color: #1E1E1E;
                padding: 4px;
            }
        """)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumWidth(150)
        self.image_label.setMaximumWidth(250)

        image_layout.addWidget(self.image_label)

    def _populate_instant_wildcard_popup(self, keys):
        """인스턴트 와일드카드 키를 팝업에 표시합니다."""
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtCore import Qt

        for key in keys:
            display_text = key
            item = QListWidgetItem(display_text)

            # 그룹 아이템인지 확인
            is_group = key.startswith("$")

            if is_group:
                # 그룹 아이템 처리
                group_name = key[1:]  # $ 제거

                # UserRole에는 그룹 선택 시 삽입될 텍스트 저장
                item.setData(Qt.ItemDataRole.UserRole, f"${group_name}:")

                # UserRole + 1에는 표시용 키 저장
                item.setData(Qt.ItemDataRole.UserRole + 1, key)

                # 그룹의 하위 키들을 툴팁으로 표시 (최대 5개)
                if group_name in self.instant_wildcards_tree:
                    sub_keys = list(self.instant_wildcards_tree[group_name].keys())[:5]
                    sub_keys_text = ", ".join(sub_keys)
                    if len(self.instant_wildcards_tree[group_name]) > 5:
                        sub_keys_text += f", ... (+{len(self.instant_wildcards_tree[group_name]) - 5}개)"
                    item.setToolTip(f"📁 그룹: {group_name}\n하위 항목: {sub_keys_text}")
                else:
                    item.setToolTip(f"📁 그룹: {group_name}")
            else:
                # 일반 와일드카드 아이템 처리
                value = self.instant_wildcards.get(key, "")
                item.setData(Qt.ItemDataRole.UserRole, value)

                # 키 정보는 UserRole + 1에 저장 (값 표시용)
                item.setData(Qt.ItemDataRole.UserRole + 1, key)

                # 툴팁 설정 (값의 미리보기)
                preview = value[:100] + "..." if len(value) > 100 else value
                item.setToolTip(f"키: ${key}\n값: {preview}")

            self.popup.addItem(item)

        # 선택 변경 시 값 표시 업데이트
        if not hasattr(self, '_wildcard_selection_connected'):
            self.popup.currentRowChanged.connect(self._on_wildcard_selection_changed)
            self._wildcard_selection_connected = True

    def _on_wildcard_selection_changed(self, row):
        """와일드카드 선택이 변경될 때 값 표시를 업데이트합니다."""
        if row >= 0 and row < self.popup.count():
            item = self.popup.item(row)
            # UserRole + 1에서 키 정보 가져오기
            key = item.data(Qt.ItemDataRole.UserRole + 1)
            if key:
                self._update_value_display(key)

    def _update_value_display(self, key: str):
        """선택된 와일드카드의 값과 이미지를 표시합니다."""
        if not self.value_display:
            return

        # 그룹 아이템인지 확인
        if key.startswith("$"):
            # 그룹 표시
            group_name = key[1:]  # $ 제거

            if group_name in self.instant_wildcards_tree:
                # 그룹의 하위 항목들 표시
                sub_items = self.instant_wildcards_tree[group_name]
                items_html = ""
                for sub_key, sub_value in list(sub_items.items())[:10]:  # 최대 10개 표시
                    preview = sub_value[:50] + "..." if len(sub_value) > 50 else sub_value
                    items_html += f"<div style='margin-bottom: 4px;'><span style='color: #9CDCFE;'>{sub_key}:</span> <span style='color: #999;'>{preview}</span></div>"

                if len(sub_items) > 10:
                    items_html += f"<div style='color: #666; font-style: italic;'>... 그 외 {len(sub_items) - 10}개 항목</div>"

                html_content = f"""<div style="color: #CCCCCC; font-family: 'Consolas', 'Courier New', monospace; margin: 0; padding: 0;">
<div style="color: #569CD6; font-weight: bold; margin-bottom: 8px;">📁 {group_name} 그룹</div>
<div style="border-top: 1px solid #444; padding-top: 8px;">{items_html}</div>
</div>"""
            else:
                html_content = f"""<div style="color: #CCCCCC; font-family: 'Consolas', 'Courier New', monospace; margin: 0; padding: 0;">
<div style="color: #569CD6; font-weight: bold;">📁 {group_name} 그룹</div>
</div>"""
        else:
            # 일반 와일드카드 표시
            value = self.instant_wildcards.get(key, "")

            # HTML 포맷팅으로 가독성 향상 (공백 제거)
            html_content = f"""<div style="color: #CCCCCC; font-family: 'Consolas', 'Courier New', monospace; margin: 0; padding: 0;">
<div style="color: #569CD6; font-weight: bold; margin-bottom: 8px;">${key}</div>
<div style="border-top: 1px solid #444; padding-top: 8px; white-space: pre-wrap;">{value}</div>
</div>"""

        self.value_display.setHtml(html_content)

        # 이미지 업데이트
        self._update_image_display(key)

    def _update_image_display(self, key: str):
        """와일드카드에 연결된 이미지를 표시합니다."""
        if not self.image_label or not self.image_container:
            return

        # 그룹 아이템인 경우 이미지 표시 안함
        if key.startswith("$"):
            self.image_container.hide()
            return

        # 현재 파일 찾기 (default.json 등)
        current_file = None
        for filename, data in self._get_instant_wildcard_files().items():
            if key in data:
                current_file = filename.replace('.json', '')
                break

        if not current_file:
            self.image_container.hide()
            return

        # 이미지 경로 확인
        image_path = Path("save") / "instant_wildcard" / "images" / current_file / f"{key}.png"

        if image_path.exists():
            try:
                pixmap = QPixmap(str(image_path))
                if not pixmap.isNull():
                    # 높이에 맞춰 스케일링 (비율 유지)
                    max_height = self.popup.height() if self.popup else 200
                    scaled_pixmap = pixmap.scaledToHeight(
                        max_height,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.image_label.setPixmap(scaled_pixmap)

                    # 이미지 컨테이너 위치 설정 및 표시
                    if self.current_widget and self.value_container and self.value_container.isVisible():
                        # 값 패널 오른쪽에 이미지 표시
                        value_pos = self.value_container.pos()
                        image_pos = value_pos
                        image_pos.setX(value_pos.x() + self.value_container.width() + 5)
                        self.image_container.move(image_pos)
                        self.image_container.show()
                else:
                    self.image_container.hide()
            except Exception as e:
                print(f"⚠️ 이미지 로드 실패: {e}")
                self.image_container.hide()
        else:
            self.image_container.hide()

    def _get_instant_wildcard_files(self) -> dict:
        """인스턴트 와일드카드 JSON 파일들을 로드합니다."""
        wildcard_files = {}
        wildcard_dir = Path("save") / "instant_wildcard"

        if wildcard_dir.exists():
            for json_file in wildcard_dir.glob("*.json"):
                try:
                    import json
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        wildcard_files[json_file.name] = data
                except Exception as e:
                    print(f"⚠️ 와일드카드 파일 로드 실패 {json_file.name}: {e}")

        return wildcard_files

    def popup_at_cursor_with_value(self):
        """커서 위치에 팝업과 값 표시 패널을 나란히 표시합니다."""
        if not self.current_widget:
            return

        cursor_rect = self.current_widget.cursorRect()
        cursor_pos_global = self.current_widget.mapToGlobal(cursor_rect.bottomLeft())

        # 팝업 표시
        self.popup.move(cursor_pos_global)
        self.popup.setCurrentRow(0)
        self.popup.show()

        # 값 패널을 팝업 오른쪽에 표시
        if self.value_container:
            # 팝업 높이에 맞춰서 값 패널 높이 조정
            self.value_display.setMinimumHeight(self.popup.height())
            self.value_display.setMaximumHeight(self.popup.height())

            # 팝업 오른쪽에 위치
            value_pos = cursor_pos_global
            value_pos.setX(value_pos.x() + self.popup.width() + 5)
            self.value_container.move(value_pos)
            self.value_container.show()

            # 이미지 컨테이너 높이 조정 (있는 경우)
            if self.image_label:
                self.image_label.setMaximumHeight(self.popup.height())

            # 첫 번째 항목의 이미지 업데이트 (있는 경우)
            if self.popup.count() > 0:
                item = self.popup.item(0)
                key = item.data(Qt.ItemDataRole.UserRole + 1)
                if key:
                    self._update_image_display(key)

    # ==================== TagViewer 관련 메서드 (MainPromptBlock용) ====================

    def _create_tag_viewer(self):
        """
        TagViewer 위젯 생성 (3단 구조)

        current_widget의 allowed_groups/allowed_subgroups 속성을 읽어서
        필터링된 TagViewer를 생성합니다.
        """
        from ui.interactive.tag_viewer_widget import TagViewerWidget

        # current_widget에서 allowed_groups/allowed_subgroups 속성 읽기
        allowed_groups = None
        allowed_subgroups = None

        if self.current_widget:
            # QVariant to Python list/dict 변환
            groups_prop = self.current_widget.property("allowed_groups")
            subgroups_prop = self.current_widget.property("allowed_subgroups")

            # QVariant가 None이 아니고 리스트인 경우 사용
            if groups_prop is not None:
                allowed_groups = groups_prop if isinstance(groups_prop, list) else None

            if subgroups_prop is not None:
                # list 또는 dict 형태 허용
                allowed_subgroups = subgroups_prop if isinstance(subgroups_prop, (list, dict)) else None

        # 필터링 적용된 TagViewer 생성
        tag_viewer = TagViewerWidget(
            parent=None,
            allowed_groups=allowed_groups,
            allowed_subgroups=allowed_subgroups
        )

        # 태그 선택 시그널 연결
        tag_viewer.tag_selected.connect(self._on_tag_viewer_selection)

        # 퀵 서치 요청 시그널 연결
        tag_viewer.quick_search_requested.connect(self._on_quick_search_requested)

        return tag_viewer

    def _show_tag_viewer_results(self, tags_data: dict):
        """
        TagViewer에 태그 데이터 표시

        Args:
            tags_data: {tag: tag_data} 형태의 전체 데이터셋
        """
        if not self.tag_viewer or not self.current_widget:
            return

        # 닫기 예외 처리할 타겟 위젯 설정 (입력창 클릭 시 닫히지 않도록)
        self.tag_viewer.set_target_widget(self.current_widget)

        # TagViewer에 데이터 설정
        self.tag_viewer.set_tags_data(tags_data)

        # 위젯의 글로벌 위치 계산
        widget_rect = self.current_widget.rect()

        # 위젯의 우측 상단 좌표 (글로벌)
        widget_top_right = self.current_widget.mapToGlobal(widget_rect.topRight())

        # 위젯의 좌측 상단 좌표 (글로벌)
        widget_top_left = self.current_widget.mapToGlobal(widget_rect.topLeft())

        # 위젯의 중앙 X 좌표 (글로벌)
        widget_center_global = self.current_widget.mapToGlobal(widget_rect.center())
        widget_center_x = widget_center_global.x()

        # 기본 Y 위치 (위젯 상단)
        popup_y = widget_top_right.y()

        # 창의 중앙 X 좌표 계산
        if self.parent_window:
            window_center_x = self.parent_window.x() + self.parent_window.width() // 2

            # TagViewer 크기
            from ui.scaling_manager import get_scaled_size
            viewer_width = get_scaled_size(800)
            viewer_height = get_scaled_size(600)

            # 위젯이 창 중앙보다 왼쪽에 있으면
            if widget_center_x < window_center_x:
                # TagViewer를 위젯 우측에 배치 (위젯 우측 상단 + 간격)
                popup_x = widget_top_right.x() + get_scaled_size(20)
            else:
                # TagViewer를 위젯 좌측에 배치 (위젯 좌측 상단 - 뷰어 너비 - 간격)
                popup_x = widget_top_left.x() - viewer_width - get_scaled_size(20)

            # === 윈도우 경계 클램핑 ===
            # 윈도우의 절대 좌표 가져오기
            window_geometry = self.parent_window.geometry()
            window_left = window_geometry.x()
            window_right = window_geometry.x() + window_geometry.width()
            window_top = window_geometry.y()
            window_bottom = window_geometry.y() + window_geometry.height()

            # X 좌표 클램핑 (좌우 경계)
            if popup_x < window_left:
                popup_x = window_left + get_scaled_size(10)  # 왼쪽 경계에서 10px 간격
            elif popup_x + viewer_width > window_right:
                popup_x = window_right - viewer_width - get_scaled_size(10)  # 오른쪽 경계에서 10px 간격

            # Y 좌표 클램핑 (상하 경계)
            if popup_y < window_top:
                popup_y = window_top + get_scaled_size(10)  # 상단 경계에서 10px 간격
            elif popup_y + viewer_height > window_bottom:
                popup_y = window_bottom - viewer_height - get_scaled_size(10)  # 하단 경계에서 10px 간격

        else:
            # parent_window가 없으면 우측에 배치
            from ui.scaling_manager import get_scaled_size
            popup_x = widget_top_right.x() + get_scaled_size(20)

        # TagViewer 표시 (위치 고정)
        self.tag_viewer.show_at_position(popup_x, popup_y)

    def _on_tag_viewer_selection(self, tag: str):
        """
        TagViewer에서 태그 선택 시 호출

        Args:
            tag: 선택된 태그명
        """
        if not self.current_widget:
            return

        # complete_text 메서드 재사용
        self.complete_text(tag)

        # TagViewer 숨기기
        self.tag_viewer.hide()

    def _on_quick_search_requested(self, tag: str):
        """TagViewer에서 퀵 서치 요청 시 호출"""
        print(f"[Autocomplete] Quick Search Requested: {tag}")
        
        if not self.parent_window:
             return
             
        # 1. QuickSearchBlock 강제 검색
        if hasattr(self.parent_window, 'quick_search_block'):
            self.parent_window.quick_search_block.force_single_search(tag)
            
        # 2. MainPromptBlock 랜덤 생성 요청
        if hasattr(self.parent_window, 'main_prompt_block'):
            self.parent_window.main_prompt_block._on_random_clicked()
        if self.tag_viewer:
            self.tag_viewer.hide()
