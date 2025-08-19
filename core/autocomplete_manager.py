import re
from PyQt6.QtCore import QObject, QEvent, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QListWidget, QWidget, QLineEdit, QTextEdit, QHBoxLayout, QTextBrowser
from PyQt6.QtGui import QTextCursor, QKeyEvent

# ✅ 전역 인스턴스 (싱글턴 패턴 대체)
_autocomplete_manager = None

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
        
        # 현재 활성 위젯
        self.current_widget = None
        self.current_suggestions = []
        
        # 인스턴트 와일드카드 딕셔너리 캐시
        self.instant_wildcards = {}
        
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
        token_info = self._get_active_token_info(self.current_widget)
        if not token_info or len(token_info['stripped_text']) < 1:
            self._hide_all_popups()
            return
            
        self.active_token_info = token_info
        target_text = token_info['stripped_text']
        
        # $ 로 시작하는 경우 인스턴트 와일드카드 처리
        if target_text.startswith('$'):
            self._show_instant_wildcard_completions(target_text[1:])  # $ 제거하고 전달
            return
        
        # 인스턴트 와일드카드가 아닌 경우 값 표시 패널 숨기기
        if self.value_container:
            self.value_container.hide()
        
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
            
            # 툴팁 설정
            item.setToolTip(f"태그: {tag}\n사용 횟수: {count:,}")
            
            self.popup.addItem(item)

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
        
        # 인스턴트 와일드카드인 경우 값이 그대로 삽입됨 ($ 없이)
        if info['stripped_text'].startswith('$'):
            # completion_text는 이미 값이므로 그대로 사용
            pass
        else:
            # 일반 태그인 경우 괄호 구조 복원
            if not self.app_context.current_api_mode == "NAI":
                completion_text = completion_text.replace('(', r'\(').replace(')', r'\)')
        
        final_text = self._restore_brackets(completion_text, info['prefix'], info['suffix'])

        if isinstance(widget, QTextEdit):
            cursor = widget.textCursor()
            cursor.setPosition(info['start'])
            cursor.setPosition(info['end'], QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(final_text)
        else: # QLineEdit
            current_text = widget.text()
            new_text = current_text[:info['start']] + final_text + current_text[info['end']:]
            widget.setText(new_text)
        
        self._hide_all_popups()
        widget.setFocus() # 텍스트 완성 후 원래 위젯으로 포커스 복귀

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
        stripped_token, prefix, suffix = self._strip_brackets(token)

        return {
            'text': token, 
            'stripped_text': stripped_token.strip(), 
            'prefix': prefix, 
            'suffix': suffix, 
            'start': start_pos, 
            'end': end_pos
        }

    def _strip_brackets(self, keyword: str) -> tuple[str, str, str]:
        """단어 앞뒤의 괄호를 분리합니다."""
        if not isinstance(keyword, str):
            return "", "", ""

        keyword_stripped = keyword.strip()
        prefix_match = re.match(r'^[\{\[\(]+', keyword_stripped)
        prefix = prefix_match.group(0) if prefix_match else ''
        suffix_match = re.search(r'[\}\]\)]+$', keyword_stripped)
        suffix = suffix_match.group(0) if suffix_match else ''
        
        if len(prefix) + len(suffix) > len(keyword_stripped):
             return keyword_stripped, "", ""

        stripped_keyword = keyword_stripped[len(prefix):len(keyword_stripped) - len(suffix)]
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
    
    def _get_instant_wildcards(self):
        """인스턴트 와일드카드 딕셔너리를 가져옵니다."""
        try:
            # middle_section_controller를 통해 InstantWildcardModule 접근
            if self.main_window and hasattr(self.main_window, 'middle_section_controller'):
                instant_module = self.main_window.middle_section_controller.get_module_instance("InstantWildcardModule")
                if instant_module:
                    return instant_module.get_wildcards()
        except Exception as e:
            print(f"⚠️ 인스턴트 와일드카드 가져오기 실패: {e}")
        return {}
    
    def _show_instant_wildcard_completions(self, search_text: str):
        """인스턴트 와일드카드 자동완성을 표시합니다."""
        # 인스턴트 와일드카드 딕셔너리 가져오기
        self.instant_wildcards = self._get_instant_wildcards()
        
        if not self.instant_wildcards:
            self._hide_all_popups()
            return
        
        # 검색어와 매칭되는 와일드카드 키 찾기
        matching_keys = []
        for key in self.instant_wildcards.keys():
            if not search_text or key.lower().startswith(search_text.lower()):
                matching_keys.append(key)
        
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
        
        # 첫 번째 항목의 값 표시
        if matching_keys:
            self._update_value_display(matching_keys[0])
        
        # 팝업과 값 패널 위치 조정
        self.popup_at_cursor_with_value()
    
    def _create_value_display(self):
        """인스턴트 와일드카드 값을 표시할 패널을 생성합니다."""
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
    
    def _populate_instant_wildcard_popup(self, keys):
        """인스턴트 와일드카드 키를 팝업에 표시합니다."""
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtCore import Qt
        
        for key in keys:
            # $ 없이 키만 표시
            display_text = key
            item = QListWidgetItem(display_text)
            
            # 실제 값을 UserRole에 저장 (선택 시 값이 삽입됨)
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
        """선택된 와일드카드의 값을 표시합니다."""
        if not self.value_display:
            return
        
        value = self.instant_wildcards.get(key, "")
        
        # HTML 포맷팅으로 가독성 향상 (공백 제거)
        html_content = f"""<div style="color: #CCCCCC; font-family: 'Consolas', 'Courier New', monospace; margin: 0; padding: 0;">
<div style="color: #569CD6; font-weight: bold; margin-bottom: 8px;">${key}</div>
<div style="border-top: 1px solid #444; padding-top: 8px; white-space: pre-wrap;">{value}</div>
</div>"""
        
        self.value_display.setHtml(html_content)
    
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