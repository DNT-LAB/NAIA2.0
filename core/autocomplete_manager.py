import re
from pathlib import Path
from PyQt6.QtCore import QObject, QEvent, Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QListWidget, QWidget, QLineEdit, QTextEdit, QHBoxLayout, QTextBrowser, QLabel, QVBoxLayout
from PyQt6.QtGui import QTextCursor, QKeyEvent, QPixmap
from utils.translator import korean_to_english

# ✅ 전역 인스턴스 (싱글턴 패턴 대체)
_autocomplete_manager = None

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

# 1. autocomplete_manager.py의 get_autocomplete_manager() 함수 수정

def get_autocomplete_manager(app_context=None, main_window=None):
    """
    AutoCompleteManager의 전역 인스턴스를 반환합니다.
    최초 호출 시에만 인스턴스를 생성하고, 이후로는 동일한 객체를 반환합니다.
    
    Args:
        app_context: AppContext 인스턴스 (새로운 방식)
        main_window: MainWindow 인스턴스 (기존 방식, 폴백용)
    
    Returns:
        AutoCompleteManager: 전역 자동완성 관리자 인스턴스
    """
    global _autocomplete_manager
    
    # 🆕 메인 윈도우가 완전히 초기화된 후에만 생성 (빈 윈도우 방지)
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    
    # 조건을 더 엄격하게: main_window와 app_context 모두 있어야 하고, 메인 윈도우가 표시되어야 함
    if (not app or not main_window or not app_context or 
        not hasattr(main_window, 'isVisible') or not main_window.isVisible()):
        print("⚠️ 메인 윈도우가 완전히 초기화되지 않아 AutoCompleteManager 생성을 건너뜁니다.")
        return None
    
    if _autocomplete_manager is None:
        print("🔍 AutoCompleteManager 전역 인스턴스 생성 중...")
        _autocomplete_manager = AutoCompleteManager(app_context=app_context, main_window=main_window)
    else:
        print("✅ AutoCompleteManager 기존 전역 인스턴스 반환")
    return _autocomplete_manager


def reset_autocomplete_manager():
    """전역 인스턴스를 리셋합니다."""
    global _autocomplete_manager
    if _autocomplete_manager:
        print("🔄 AutoCompleteManager 전역 인스턴스 리셋")
        _autocomplete_manager = None

class AutoCompleteManager(QObject):
    """
    애플리케이션 전체의 텍스트 입력 위젯에 대한 자동완성 기능을 관리하는 클래스.
    ✅ 싱글턴 패턴을 제거하여 Python 3.12 호환성 문제 해결
    이벤트 필터를 사용하여 모든 QLineEdit, QTextEdit의 입력을 감지하고,
    TagDataManager와 WildcardManager를 통해 추천 목록을 제공합니다.
    
    자동완성을 비활성화하려면:
    1. 위젯에 속성 설정: widget.setProperty("autocomplete_ignore", True)
    2. 위젯 이름을 ignored_widget_names에 추가
    3. 부모 위젯 이름을 ignored_parent_names에 추가
    """

    def __init__(self, app_context=None, main_window=None):
        # 🆕 QApplication 체크 추가 (빈 윈도우 방지)
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            print("❌ AutoCompleteManager: QApplication이 없습니다.")
            return
        
        super().__init__()
        
        # 앱 컨텍스트 설정
        self.app_context = app_context
        self.main_window = main_window or (app_context.main_window if app_context else None)
        
        # 데이터 매니저 참조
        self.tag_data_manager = None
        self.wildcard_manager = None
        
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
        
        # 무시할 위젯 이름들
        self.ignored_widget_names = [
            "search_input", "exclude_input", "negative_prompt", 
            "delay_input", "repeat_input", "timer_input", "count_input"
        ]
        
        # 자동완성 활성화 상태
        self.enabled = True
        
        # 🆕 지연 초기화 타이머
        self.init_timer = QTimer()
        self.init_timer.setSingleShot(True)
        self.init_timer.timeout.connect(self._delayed_initialize)
        self.init_timer.start(1000)  # 1초 후 초기화

    def _delayed_initialize(self):
        """🆕 지연 초기화 - 메인 윈도우가 완전히 준비된 후 실행"""
        try:
            if not self._initialized:
                self.timer = QTimer()
                self.timer.setSingleShot(True)
                self._setup_data_managers()
                self._setup_event_filter()
                self.timer.timeout.connect(self.show_completions)
                self._initialized = True
                print("✅ AutoCompleteManager 지연 초기화 완료")
        except Exception as e:
            print(f"❌ AutoCompleteManager 초기화 실패: {e}")
    
    def _setup_data_managers(self):
        """데이터 매니저 설정"""
        try:
            if self.app_context:
                self.tag_data_manager = getattr(self.app_context, 'tag_data_manager', None)
                self.wildcard_manager = getattr(self.app_context, 'wildcard_manager', None)
            elif self.main_window:
                self.tag_data_manager = getattr(self.main_window, 'tag_data_manager', None)
                self.wildcard_manager = getattr(self.main_window, 'wildcard_manager', None)
        except Exception as e:
            print(f"⚠️ AutoCompleteManager 데이터 매니저 설정 실패: {e}")

    def _setup_event_filter(self):
        """🆕 이벤트 필터 설정 - 안전하게 처리"""
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
                print("✅ AutoCompleteManager 이벤트 필터 설치 완료")
        except Exception as e:
            print(f"❌ AutoCompleteManager 이벤트 필터 설치 실패: {e}")

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

        # 감시 대상이 QLineEdit 또는 QTextEdit인지 확인
        if not isinstance(watched, (QLineEdit, QTextEdit)):
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
        # 1. 위젯 속성으로 직접 설정된 경우
        if widget.property("autocomplete_ignore"):
            return True
        
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
        print("Autocomplete enabled.")
    
    def disable(self):
        """자동완성 기능을 비활성화합니다."""
        if not hasattr(self, 'enabled'):
            self.enabled = False
        self.enabled = False
        self._hide_all_popups()
        print("Autocomplete disabled.")

    def on_key_release(self, widget: QWidget, event: QKeyEvent):
        """키 입력이 끝나면 타이머를 시작하여 자동완성 팝업을 띄울 준비"""
        nav_keys = [Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Escape]
        
        # 방향키(좌우)로 커서가 이동한 경우 팝업 닫기 체크
        if event.key() in [Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End]:
            if self.popup and self.popup.isVisible():
                self._check_cursor_position_and_close(widget)
        elif event.key() not in nav_keys:
            self.current_widget = widget
            self.timer.start(200)

    def show_completions(self):
        """자동완성 목록을 표시하는 메서드"""
        if not self.current_widget or not self.enabled: 
            return

        # 💡 [수정] 팝업이 없을 경우에만 생성 (지연 초기화)
        if self.popup is None:
            self.popup = self._create_popup()

        # 현재 활성 토큰 정보 가져오기
        try: token_info = self._get_active_token_info(self.current_widget)
        except: 
            token_info = None
            return
        if not token_info or len(token_info['stripped_text']) < 1:
            self._hide_all_popups()
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
                self._hide_all_popups()
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
        
        # wildcard_manager가 있다면 추가 와일드카드도 전달
        additional_wildcards = None
        if self.wildcard_manager:
            additional_wildcards = getattr(self.wildcard_manager, 'wildcard_dict_tree', None)
        
        # TagDataManager를 통해 매칭 결과 가져오기
        try:
            if not self.tag_data_manager:
                print("⚠️ tag_data_manager가 없습니다")
                self._hide_all_popups()
                return
                
            matches = self.tag_data_manager.find_top_matches(
                target_text, 
                additional_wildcards=additional_wildcards
            )
        except Exception as e:
            print(f"⚠️ 자동완성 검색 중 오류: {e}")
            self._hide_all_popups()
            return
        
        # 매칭 결과가 없으면 팝업 숨기기
        if not matches:
            self._hide_all_popups()
            return
            
        # 팝업에 결과 표시 (태그명 + count 포함)
        self.popup.clear()
        self._populate_popup_with_counts(matches)
        self.popup_at_cursor()

    def popup_at_cursor(self):
        """커서 위치에 팝업을 표시"""
        if not self.current_widget:
            return
            
        cursor_rect = self.current_widget.cursorRect()
        cursor_pos_global = self.current_widget.mapToGlobal(cursor_rect.bottomLeft())
        self.popup.move(cursor_pos_global)
        self.popup.setCurrentRow(0)
        self.popup.show()

    def _populate_popup_with_counts(self, matches):
        """매칭 결과를 count와 함께 팝업에 표시"""
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtCore import Qt
        
        # Artist data 가져오기 (한 번만)
        artist_data = self._get_artist_data()
        artist_list = self._get_artist_list()
        
        for tag, count in matches:
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
            
            # 아티스트 검색 - artist: 접두사 유무와 관계없이 확인
            artist_name = tag.replace("artist:", "").strip() if tag.startswith("artist:") else tag.strip()
            
            # artist_list에서 아티스트 확인 (artist: 접두사 없어도 검색)
            if artist_name in artist_list and artist_name in artist_data:
                # UserRole + 2에 아티스트 이미지 데이터 저장
                item.setData(Qt.ItemDataRole.UserRole + 2, artist_data[artist_name])
                item.setToolTip(f"아티스트: {artist_name}\n사용 횟수: {count:,}\n(키보드로 선택 시 이미지 확인)")
            else:
                # 툴팁 설정
                item.setToolTip(f"태그: {tag}\n사용 횟수: {count:,}")
            
            self.popup.addItem(item)
            
            # NAI 모드이고 아티스트 태그인데 "artist:" 접두사가 없는 경우 "artist:" 버전도 추가
            if (self.app_context and 
                hasattr(self.app_context, 'current_api_mode') and 
                self.app_context.current_api_mode == "NAI" and
                artist_name in artist_list and
                not tag.startswith("artist:")):
                
                artist_tag = f"artist:{tag}"
                artist_display_text = f"{artist_tag:<40} {count_text:>8}"
                
                artist_item = QListWidgetItem(artist_display_text)
                artist_item.setData(Qt.ItemDataRole.UserRole, artist_tag)
                
                # 아티스트 이미지 데이터도 동일하게 설정
                if artist_name in artist_data:
                    artist_item.setData(Qt.ItemDataRole.UserRole + 2, artist_data[artist_name])
                    artist_item.setToolTip(f"아티스트: {artist_name}\n사용 횟수: {count:,}\n(키보드로 선택 시 이미지 확인)")
                else:
                    artist_item.setToolTip(f"태그: {artist_tag}\n사용 횟수: {count:,}")
                
                self.popup.addItem(artist_item)

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
        """활성 토큰을 선택된 텍스트로 교체"""
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
            if not self.app_context.current_api_mode == "NAI":
                completion_text = completion_text.replace('(', r'\(').replace(')', r'\)')
        
        # 가중치 접두사가 있으면 추가 (예: "0.5::")
        weight_prefix = info.get('weight_prefix', '')
        if weight_prefix:
            completion_text = weight_prefix + completion_text
        
        # 괄호 복원 후 뒤 공백 추가 (모든 모드에서 동일하게)
        final_text = self._restore_brackets(completion_text, info['prefix'], info['suffix'])
        
        # 자동 쉼표 추가 (trailing_whitespace가 없거나 줄바꿈인 경우)
        # QLineEdit인 경우 쉼표를 추가하지 않음
        # 줄바꿈이 있는 경우에도 쉼표를 추가하고 그 뒤에 줄바꿈을 유지
        if isinstance(widget, QLineEdit):
            # QLineEdit인 경우 쉼표 추가 안함
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

        # 가중치가 있는 경우 시작 위치를 조정 (weight 부분도 교체하기 위해)
        start_pos = info['start']
        if weight_prefix:
            # weight_prefix 길이만큼 시작 위치를 앞으로 이동
            start_pos = info['start'] - len(weight_prefix)

        if isinstance(widget, QTextEdit):
            cursor = widget.textCursor()
            cursor.setPosition(start_pos)
            cursor.setPosition(info['end'], QTextCursor.MoveMode.KeepAnchor)
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
            new_text = current_text[:start_pos] + final_text + current_text[info['end']:]
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
        
        self._hide_all_popups()
        widget.setFocus() # 텍스트 완성 후 원래 위젯으로 포커스 복귀
        
        # 그룹 아이템을 선택한 경우, 자동으로 해당 그룹의 아이템들을 표시
        if is_group_selection:
            # 약간의 지연을 주어 텍스트 삽입이 완료된 후 실행
            QTimer.singleShot(50, self.show_completions)

    def handle_popup_navigation(self, event: QKeyEvent) -> bool:
        """팝업에서의 키보드 네비게이션 처리"""
        key = event.key()
        if key in [Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab]:
            current_item = self.popup.currentItem()
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
                self._hide_all_popups()
            return True
        elif key == Qt.Key.Key_Up:
            self.popup.setCurrentRow(max(0, self.popup.currentRow() - 1))
            return True
        elif key == Qt.Key.Key_Down:
            self.popup.setCurrentRow(min(self.popup.count() - 1, self.popup.currentRow() + 1))
            return True
        elif key == Qt.Key.Key_Escape:
            self._hide_all_popups()
            return True
        return False
        
    def _get_active_token_info(self, widget: QWidget) -> dict:
        """현재 커서 위치의 단어(토큰), 괄호, 시작/끝 위치를 반환"""
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
        original_token = token  # 원본 토큰 저장
        weight_prefix = ""  # 가중치 부분을 저장할 변수
        if '::' in token:
            # 마지막 :: 위치 찾기 (여러 개의 ::가 있을 수 있음)
            last_double_colon_pos = token.rfind('::')
            absolute_double_colon_pos = start_pos + last_double_colon_pos
            
            # 커서가 :: 의 왼쪽에 있는지 오른쪽에 있는지 확인
            if pos <= absolute_double_colon_pos:
                # 커서가 :: 왼쪽에 있으면 가중치 부분 제거 (:: 이후는 무시)
                token = token[:last_double_colon_pos]
                end_pos = start_pos + last_double_colon_pos
            else:
                # 커서가 :: 오른쪽에 있으면 weight 부분은 유지하고 그 이후 텍스트로 검색
                # 예: "0.5::arti" -> weight_prefix="0.5::", token="arti"
                weight_prefix = token[:last_double_colon_pos + 2]  # "0.5::" 부분 저장
                token = token[last_double_colon_pos + 2:]  # "arti" 부분만 검색
                start_pos = absolute_double_colon_pos + 2  # 검색 시작 위치 조정
        
        stripped_token, prefix, suffix = self._strip_brackets(token)

        return {
            'text': token, 
            'stripped_text': stripped_token.strip(),  # 모든 모드에서 동일하게 strip() 사용
            'prefix': prefix, 
            'suffix': suffix, 
            'start': start_pos, 
            'end': end_pos,
            'weight_prefix': weight_prefix  # 가중치 접두사 추가
        }

    def _strip_brackets(self, keyword: str) -> tuple[str, str, str]:
        """단어 앞뒤의 괄호와 NAI :: 가중치 문법을 분리합니다."""
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
        
        # 괄호 처리
        prefix_match = re.match(r'^[\{\[\(]+', keyword_stripped)
        prefix = prefix_match.group(0) if prefix_match else ''
        suffix_match = re.search(r'[\}\]\)]+$', keyword_stripped)
        suffix = suffix_match.group(0) if suffix_match else ''
        
        # :: 가중치를 suffix에 추가
        suffix = suffix + double_colon_suffix
        
        if len(prefix) + len(suffix) > len(keyword_stripped) + len(double_colon_suffix):
             return keyword_stripped, "", double_colon_suffix

        stripped_keyword = keyword_stripped[len(prefix):len(keyword_stripped) - (len(suffix) - len(double_colon_suffix)) if suffix else len(keyword_stripped)]
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
                self._hide_all_popups()
                self.active_token_info = None
    
    def _hide_popups_if_not_focused(self):
        """포커스가 없으면 모든 팝업을 숨깁니다."""
        if self.popup and not self.popup.hasFocus():
            self._hide_all_popups()
    
    def _hide_all_popups(self):
        """모든 팝업(리스트와 값 표시)을 숨깁니다."""
        if self.popup:
            self.popup.hide()
        if self.value_container:
            self.value_container.hide()
        if self.image_container:
            self.image_container.hide()
        # 번역 타이머도 중지
        if hasattr(self, 'translation_timer'):
            self.translation_timer.stop()
        # 번역 워커는 유지 (재사용을 위해)
    
    def cleanup(self):
        """프로그램 종료 시 리소스 정리"""
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
        self._hide_all_popups()
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
            self._hide_all_popups()
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
            self._hide_all_popups()
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