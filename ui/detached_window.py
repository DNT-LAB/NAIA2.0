# ui/detached_window.py (완전 독립 창 버전)

from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QMessageBox, QMenuBar, QMenu, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QCloseEvent, QAction, QKeySequence, QIcon
from ui.theme import DARK_COLORS, DARK_STYLES

class DetachedWindow(QMainWindow):
    """완전히 독립적인 분리 창 (부모 관계 없음)"""
    
    # 창이 닫힐 때 발생하는 시그널 (tab_index, widget)
    window_closed = pyqtSignal(int, object)
    
    def __init__(self, widget: QWidget, title: str, tab_index: int, parent_container=None):
        # ✅ 핵심 변경: parent=None으로 설정하여 완전히 독립적인 창 생성
        super().__init__(parent=None)  # parent 제거!
        
        self.original_widget = widget
        self.tab_title = title
        self.tab_index = tab_index
        self.parent_container = parent_container  # 참조만 저장 (부모 관계 아님)
        
        # ✅ 완전히 독립적인 윈도우 플래그 설정
        self.setWindowFlags(
            Qt.WindowType.Window |  # 독립 창
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint
        )
        
        # ✅ 태스크바에 별도 아이콘으로 표시되도록 설정
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowIcon(self.get_window_icon())
        
        print(f"🔧 독립 DetachedWindow 초기화: {title}")
        print(f"   - 부모 관계: 없음 (완전 독립)")
        print(f"   - 원본 위젯: {widget}")
        print(f"   - 위젯 타입: {type(widget).__name__}")
        
        self.init_ui()
        self.setup_widget()
        self.setup_window_controls()
        
    def get_window_icon(self):
        """창 아이콘 설정 (독립 창임을 시각적으로 표시)"""
        try:
            # NAIA 메인 아이콘이 있다면 사용, 없으면 기본 아이콘
            app = QApplication.instance()
            if app and not app.windowIcon().isNull():
                return app.windowIcon()
        except:
            pass
        return QIcon()  # 기본 아이콘
        
    def init_ui(self):
        """독립 창 UI 초기화"""
        # ✅ 창 제목에 독립 창임을 명시
        self.setWindowTitle(f"NAIA - {self.tab_title} (독립 창)")
        # self.setMinimumSize(800, 600)
        # self.resize(1200, 800)
        
        # 어두운 테마 적용
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        # 메인 위젯 설정
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # 레이아웃 생성
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(0)
        
    def setup_window_controls(self):
        """윈도우 제어 기능 설정"""
        # 메뉴 바 생성
        menubar = self.menuBar()
        menubar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border-bottom: 1px solid {DARK_COLORS['border']};
                padding: 4px;
            }}
            QMenuBar::item {{
                background-color: transparent;
                padding: 4px 8px;
                border-radius: 4px;
            }}
            QMenuBar::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        
        # 윈도우 메뉴
        window_menu = menubar.addMenu("창 (&W)")
        window_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 12px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        
        # ✅ Z-order 제어 액션들 (독립 창 전용)
        always_on_top_action = QAction("항상 위에 표시 (&T)", self)
        always_on_top_action.setCheckable(True)
        always_on_top_action.setChecked(False)
        always_on_top_action.triggered.connect(self.toggle_always_on_top)
        always_on_top_action.setShortcut(QKeySequence("Ctrl+T"))
        window_menu.addAction(always_on_top_action)
        
        window_menu.addSeparator()
        
        # ✅ 독립 창 전용 제어 (메인 UI에 영향 없음)
        bring_to_front_action = QAction("이 창만 앞으로 (&F)", self)
        bring_to_front_action.triggered.connect(self.bring_to_front)
        bring_to_front_action.setShortcut(QKeySequence("Ctrl+F"))
        window_menu.addAction(bring_to_front_action)
        
        minimize_action = QAction("이 창 최소화 (&M)", self)
        minimize_action.triggered.connect(self.showMinimized)
        minimize_action.setShortcut(QKeySequence("Ctrl+M"))
        window_menu.addAction(minimize_action)
        
        window_menu.addSeparator()
        
        # 메인 UI 제어 (독립적)
        show_main_ui_action = QAction("메인 UI 활성화 (&S)", self)
        show_main_ui_action.triggered.connect(self.activate_main_ui)
        show_main_ui_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
        window_menu.addAction(show_main_ui_action)
        
        window_menu.addSeparator()
        
        # 복귀 액션
        return_to_tab_action = QAction("탭으로 복귀 (&R)", self)
        return_to_tab_action.triggered.connect(self.close)
        return_to_tab_action.setShortcut(QKeySequence("Ctrl+R"))
        window_menu.addAction(return_to_tab_action)
        
        # 멤버 변수로 저장
        self.always_on_top_action = always_on_top_action
        
    def activate_main_ui(self):
        """메인 UI를 독립적으로 활성화"""
        try:
            if self.parent_container:
                # parent_container를 통해 메인 윈도우 찾기
                main_window = None
                if hasattr(self.parent_container, 'main_window'):
                    main_window = self.parent_container.main_window
                elif hasattr(self.parent_container, 'app_context'):
                    main_window = self.parent_container.app_context.main_window
                
                if main_window:
                    main_window.raise_()
                    main_window.activateWindow()
                    main_window.setFocus()
                    print(f"🎯 메인 UI 활성화 완료 (독립 창에서 요청)")
                    return
            
            # 폴백: QApplication을 통해 메인 윈도우 찾기
            app = QApplication.instance()
            if app:
                for widget in app.topLevelWidgets():
                    if isinstance(widget, QMainWindow) and widget != self:
                        if "NAIA" in widget.windowTitle() and "독립 창" not in widget.windowTitle():
                            widget.raise_()
                            widget.activateWindow()
                            widget.setFocus()
                            print(f"🎯 메인 UI 활성화 완료 (자동 검색)")
                            return
                            
        except Exception as e:
            print(f"⚠️ 메인 UI 활성화 실패: {e}")
        
    def toggle_always_on_top(self, checked: bool):
        """항상 위에 표시 토글 (이 창만 영향)"""
        current_flags = self.windowFlags()
        
        if checked:
            new_flags = current_flags | Qt.WindowType.WindowStaysOnTopHint
            print(f"🔝 '{self.tab_title}': 이 창만 항상 위에 표시")
        else:
            new_flags = current_flags & ~Qt.WindowType.WindowStaysOnTopHint
            print(f"📍 '{self.tab_title}': 항상 위에 표시 해제")
        
        self.setWindowFlags(new_flags)
        self.show()
        
    def bring_to_front(self):
        """이 창만 앞으로 가져오기 (메인 UI에 영향 없음)"""
        self.raise_()
        self.activateWindow()
        self.setFocus()
        print(f"⬆️ '{self.tab_title}': 이 창만 앞으로 가져옴")
        
    def setup_widget(self):
        """원본 위젯을 독립 창으로 이동"""
        if not self.original_widget:
            print("❌ DetachedWindow: original_widget이 None입니다.")
            return
            
        try:
            print(f"🔧 위젯 설정 시작...")
            
            # 1. 위젯 상태 확인
            print(f"   - 위젯 크기: {self.original_widget.size()}")
            print(f"   - 위젯 가시성: {self.original_widget.isVisible()}")
            print(f"   - 위젯 레이아웃: {self.original_widget.layout()}")
            
            # 2. 부모 관계 안전하게 변경
            if self.original_widget.parent():
                print(f"   - 기존 부모에서 분리: {self.original_widget.parent()}")
                
            # 3. 위젯을 독립 창으로 이동
            self.original_widget.setParent(self.central_widget)
            self.main_layout.addWidget(self.original_widget)
            
            # 4. 위젯 강제 표시
            self.original_widget.show()
            self.original_widget.setVisible(True)
            
            # 5. 레이아웃 새로고침
            self.main_layout.update()
            self.central_widget.update()
            self.update()
            
            print(f"✅ 독립 창 위젯 설정 완료")
            
        except RuntimeError as e:
            print(f"❌ DetachedWindow: 위젯 설정 실패 (RuntimeError) - {e}")
            self.show_error_placeholder()
        except Exception as e:
            print(f"❌ DetachedWindow: 예상치 못한 오류 - {e}")
            import traceback
            traceback.print_exc()
            self.show_error_placeholder()
    
    def show_error_placeholder(self):
        """오류 발생 시 플레이스홀더 표시"""
        from PyQt6.QtWidgets import QLabel
        
        error_label = QLabel("❌ 위젯을 표시할 수 없습니다.\n창을 닫고 다시 시도해주세요.")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: 16px;
                padding: 50px;
            }}
        """)
        
        self.main_layout.addWidget(error_label)
    
    def showEvent(self, event):
        """창이 표시될 때 호출"""
        super().showEvent(event)
        
        # ✅ 독립 창이므로 특별한 포커스 처리 불필요
        print(f"🪟 독립 창 '{self.tab_title}' 표시됨")
            
    def closeEvent(self, event: QCloseEvent):
        """창이 닫힐 때 위젯을 원래 위치로 되돌림"""
        try:
            print(f"🔄 독립 창 닫기: {self.tab_title}")
            
            # 위젯을 원래 위치로 되돌리기 위한 시그널 발송
            self.window_closed.emit(self.tab_index, self.original_widget)
            event.accept()
            
        except Exception as e:
            print(f"❌ 독립 창 닫기 오류: {e}")
            event.accept()
            
    def get_original_widget(self):
        """원본 위젯 반환"""
        return self.original_widget
        
    # ✅ 독립 창 전용 추가 기능들
    def is_always_on_top(self) -> bool:
        """현재 항상 위에 표시 상태인지 확인"""
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    
    def toggle_fullscreen(self):
        """전체화면 토글"""
        if self.isFullScreen():
            self.showNormal()
            print(f"🖼️ '{self.tab_title}': 창 모드로 전환")
        else:
            self.showFullScreen()
            print(f"🖥️ '{self.tab_title}': 전체화면 모드로 전환")
    
    def keyPressEvent(self, event):
        """키보드 단축키 처리"""
        # F11: 전체화면 토글
        if event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            event.accept()
        # Esc: 전체화면에서 나가기
        elif event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            event.accept()
        # Ctrl+Shift+M: 메인 UI 활성화
        elif event.key() == Qt.Key.Key_M and event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            self.activate_main_ui()
            event.accept()
        else:
            super().keyPressEvent(event)