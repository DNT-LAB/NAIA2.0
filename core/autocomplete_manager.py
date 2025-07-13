import re
from PyQt6.QtCore import QObject, QEvent, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QListWidget, QWidget, QLineEdit, QTextEdit
from PyQt6.QtGui import QTextCursor, QKeyEvent

class AutoCompleteManager(QObject):
    """
    애플리케이션 전체의 텍스트 입력 위젯에 대한 자동완성 기능을 관리하는 싱글턴 클래스.
    이벤트 필터를 사용하여 모든 QLineEdit, QTextEdit의 입력을 감지하고,
    TagDataManager와 WildcardManager를 통해 추천 목록을 제공합니다.
    
    자동완성을 비활성화하려면:
    1. 위젯에 속성 설정: widget.setProperty("autocomplete_ignore", True)
    2. 위젯 이름을 ignored_widget_names에 추가
    3. 부모 위젯 이름을 ignored_parent_names에 추가
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, main_window=None):
        super().__init__()

        if hasattr(self, '_initialized'):
            return
        
        if not main_window:
            return

        self.main_window = main_window
        self.popup = self._create_popup()
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.show_completions)
        
        self.current_widget = None
        self.active_token_info = {}

        # 🆕 자동완성 제외 설정
        self.ignored_widget_names = {
            "password_input", 
            "api_key_input", 
            "login_field",
            "secret_input"
        }
        
        self.ignored_parent_names = {
            "login_dialog",
            "settings_panel", 
            "api_management_tab",
            "password_dialog"
        }

        QApplication.instance().installEventFilter(self)
        self._initialized = True
        print("✅ AutoCompleteManager initialized and installed event filter.")

    def _create_popup(self) -> QListWidget:
        """자동완성 목록을 보여줄 팝업 위젯 생성"""
        list_widget = QListWidget()
        list_widget.setWindowFlags(Qt.WindowType.ToolTip)
        
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
        # 감시 대상이 QLineEdit 또는 QTextEdit인지 확인
        if not isinstance(watched, (QLineEdit, QTextEdit)):
            return super().eventFilter(watched, event)
        
        # 🆕 자동완성 제외 위젯 확인
        if self._should_ignore_widget(watched):
            return super().eventFilter(watched, event)
        
        # 팝업이 보이는 경우, 키보드 네비게이션을 최우선으로 처리
        if self.popup.isVisible() and event.type() == QEvent.Type.KeyPress:
            if self.handle_popup_navigation(event):
                return True # 이벤트 소비

        # 이벤트 타입에 따라 처리
        if event.type() == QEvent.Type.KeyRelease:
            self.on_key_release(watched, event)
        elif event.type() == QEvent.Type.FocusOut:
            # 약간의 지연을 주어, 팝업 클릭 시 바로 닫히지 않도록 함
            QTimer.singleShot(100, lambda: self.popup.hide() if not self.popup.hasFocus() else None)

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
        parent = widget.parent()
        while parent:
            parent_name = parent.objectName() if hasattr(parent, 'objectName') else None
            if parent_name and parent_name in self.ignored_parent_names:
                return True
            parent = parent.parent()
        
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

    def on_key_release(self, widget: QWidget, event: QKeyEvent):
        """키 입력이 끝나면 타이머를 시작하여 자동완성 팝업을 띄울 준비"""
        nav_keys = [Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Escape]
        if event.key() not in nav_keys:
            self.current_widget = widget
            self.timer.start(200)

    def show_completions(self):
        """자동완성 목록을 표시하는 메서드"""
        if not self.current_widget: 
            return
            
        # 현재 활성 토큰 정보 가져오기
        token_info = self._get_active_token_info(self.current_widget)
        if not token_info or len(token_info['stripped_text']) < 1:
            self.popup.hide()
            return
            
        self.active_token_info = token_info
        
        # 🔥 핵심 수정: 실제 토큰 텍스트를 전달
        target_text = token_info['stripped_text']
        
        # wildcard_manager가 있다면 추가 와일드카드도 전달
        additional_wildcards = None
        if hasattr(self.main_window, 'wildcard_manager') and self.main_window.wildcard_manager:
            additional_wildcards = getattr(self.main_window.wildcard_manager, 'wildcard_dict_tree', None)
        
        # TagDataManager를 통해 매칭 결과 가져오기
        try:
            matches = self.main_window.tag_data_manager.find_top_matches(
                target_text, 
                additional_wildcards=additional_wildcards
            )
        except Exception as e:
            print(f"⚠️ 자동완성 검색 중 오류: {e}")
            self.popup.hide()
            return
        
        # 매칭 결과가 없으면 팝업 숨기기
        if not matches:
            self.popup.hide()
            return
            
        # 🆕 팝업에 결과 표시 (태그명 + count 포함)
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
            # 충분한 공간을 확보하기 위해 패딩 조정
            display_text = f"{tag:<40} {count_text:>8}"
            
            item = QListWidgetItem(display_text)
            
            # 실제 태그명만 별도로 저장 (완성 시 사용)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            
            # 텍스트 색상 설정 (count 부분을 회색으로)
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
        
        # 괄호 구조 복원
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
        
        self.popup.hide()
        widget.setFocus() # 텍스트 완성 후 원래 위젯으로 포커스 복귀

    def handle_popup_navigation(self, event: QKeyEvent) -> bool:
        """팝업에서의 키보드 네비게이션 처리"""
        key = event.key()
        if key in [Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab]:
            current_item = self.popup.currentItem()
            if current_item:
                # UserRole에서 실제 태그명 가져오기
                actual_tag = current_item.data(Qt.ItemDataRole.UserRole)
                if actual_tag:
                    self.complete_text(actual_tag)
                else:
                    # 폴백: 텍스트에서 태그명 추출
                    display_text = current_item.text()
                    tag_name = display_text.split()[0] if display_text else ""
                    self.complete_text(tag_name)
            else:
                self.popup.hide()
            return True
        elif key == Qt.Key.Key_Up:
            self.popup.setCurrentRow(max(0, self.popup.currentRow() - 1))
            return True
        elif key == Qt.Key.Key_Down:
            self.popup.setCurrentRow(min(self.popup.count() - 1, self.popup.currentRow() + 1))
            return True
        elif key == Qt.Key.Key_Escape:
            self.popup.hide()
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
        """단어 앞뒤의 괄호를 분리합니다. 입력값이 문자열이 아닐 경우를 대비합니다."""
        # 입력값이 문자열이 아닐 경우를 대비한 안전장치
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