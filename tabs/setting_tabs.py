from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QCheckBox, QLineEdit, QFileDialog, QGroupBox,
    QScrollArea, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, QTimer
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaling_manager
from ui.scaling_settings_dialog import ScalingSettingsDialog
import json
import os
from pathlib import Path
from typing import Dict, Any

class SettingsTabModule(BaseTabModule):
    """Settings 탭을 관리하는 모듈"""
    
    # 설정 변경 시그널들
    autocomplete_toggled = pyqtSignal(bool)
    save_directory_changed = pyqtSignal(str)
    module_visibility_changed = pyqtSignal(str, bool)  # module_id, visible
    tab_visibility_changed = pyqtSignal(str, bool)     # tab_id, visible
    
    def __init__(self):
        super().__init__()
        self.settings_widget = None
        self.settings_data = {}
        self.settings_file = "app_settings.json"
        
    def get_tab_title(self) -> str:
        return "⚙️ Settings"
        
    def get_tab_order(self) -> int:
        return 999  # 가장 오른쪽에 위치
        
    def get_tab_type(self) -> str:
        return 'core'  # 항상 로드되는 핵심 탭
        
    def can_close_tab(self) -> bool:
        return False  # 설정 탭은 닫을 수 없음

    def create_widget(self, parent: QWidget) -> QWidget:
        if self.settings_widget is None:
            self.settings_widget = SettingsWidget(self.app_context, self)
        return self.settings_widget
        
    def on_initialize(self):
        """탭 초기화 완료 시 설정 로드"""
        self.load_settings()
        if self.settings_widget:
            self.settings_widget.update_ui_from_settings()
    
    def load_settings(self):
        """설정 파일에서 설정 로드"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    self.settings_data = json.load(f)
            else:
                self.settings_data = self._get_default_settings()
        except Exception as e:
            print(f"Settings load failed: {e}")
            self.settings_data = self._get_default_settings()
    
    def save_settings(self):
        """설정을 파일에 저장"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings_data, f, indent=2, ensure_ascii=False)
            print("Settings saved successfully.")
        except Exception as e:
            print(f"Settings save failed: {e}")
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """기본 설정값 반환"""
        return {
            "autocomplete": {
                "enabled": True
            },
            "save_directory": {
                "base_path": "./output"
            },
            "module_visibility": {},
            "tab_visibility": {},
            "ui": {
                "theme": "dark",
                "auto_save": True
            }
        }
    
    def get_setting(self, key_path: str, default=None):
        """점 표기법으로 설정값 가져오기 (예: 'autocomplete.enabled')"""
        keys = key_path.split('.')
        value = self.settings_data
        try:
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value
        except (KeyError, TypeError, AttributeError):
            return default
    
    def set_setting(self, key_path: str, value):
        """점 표기법으로 설정값 설정하기"""
        keys = key_path.split('.')
        data = self.settings_data
        for key in keys[:-1]:
            if key not in data:
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value
        self.save_settings()


class SettingsWidget(QWidget):
    """Settings UI 위젯"""
    
    def __init__(self, app_context, settings_module: SettingsTabModule):
        super().__init__()
        self.app_context = app_context
        self.settings_module = settings_module
        self.init_ui()
        
    def init_ui(self):
        """UI 초기화"""
        # 메인 위젯 배경을 검은색으로 설정
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #333333;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(16)
        
        # 스크롤 영역 생성
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(20)
        
        # 각 설정 섹션 추가
        scroll_layout.addWidget(self._create_autocomplete_section())
        scroll_layout.addWidget(self._create_save_directory_section())
        scroll_layout.addWidget(self._create_module_management_section())
        scroll_layout.addWidget(self._create_tab_management_section())
        scroll_layout.addWidget(self._create_ui_settings_section())
        
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        # 하단 버튼들
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        reset_btn = QPushButton("기본값으로 리셋")
        reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        reset_btn.clicked.connect(self.reset_to_defaults)
        
        export_btn = QPushButton("설정 내보내기")
        export_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        export_btn.clicked.connect(self.export_settings)
        
        import_btn = QPushButton("설정 가져오기")
        import_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        import_btn.clicked.connect(self.import_settings)
        
        button_layout.addWidget(reset_btn)
        button_layout.addWidget(export_btn)
        button_layout.addWidget(import_btn)
        
        main_layout.addLayout(button_layout)
    
    def _create_section_frame(self, title: str) -> tuple[QGroupBox, QVBoxLayout]:
        """섹션 프레임 생성 헬퍼"""
        group_box = QGroupBox(title)
        group_box.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                border: 2px solid {DARK_COLORS['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)
        
        layout = QVBoxLayout(group_box)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 20, 16, 16)
        
        return group_box, layout
    
    def _create_autocomplete_section(self) -> QWidget:
        """자동완성 설정 섹션"""
        section, layout = self._create_section_frame("🔍 자동완성 설정")
        
        # 자동완성 활성화
        self.autocomplete_checkbox = QCheckBox("자동완성 기능 활성화")
        self.autocomplete_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.autocomplete_checkbox.toggled.connect(self._on_autocomplete_toggled)
        layout.addWidget(self.autocomplete_checkbox)
        
        return section
    
    def _create_save_directory_section(self) -> QWidget:
        """저장 디렉토리 설정 섹션"""
        section, layout = self._create_section_frame("💾 저장 디렉토리 설정")
        
        # 기본 저장 경로
        path_layout = QHBoxLayout()
        path_label = QLabel("기본 저장 경로:")
        path_label.setStyleSheet(DARK_STYLES['label_style'])
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.save_path_edit.textChanged.connect(self._on_save_path_changed)
        
        browse_btn = QPushButton("찾아보기")
        browse_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        browse_btn.clicked.connect(self._browse_save_path)
        
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.save_path_edit, 1)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)
        
        # TODO: 자동 분류 기능 구현 예정
        # self.classification_checkbox = QCheckBox("자동 분류 활성화 (모드/날짜별 하위폴더)")
        # self.classification_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        # self.classification_checkbox.toggled.connect(self._on_classification_toggled)
        # layout.addWidget(self.classification_checkbox)
        
        # TODO: 하위폴더 형식 기능 구현 예정
        # subfolder_layout = QHBoxLayout()
        # subfolder_label = QLabel("하위폴더 형식:")
        # subfolder_label.setStyleSheet(DARK_STYLES['label_style'])
        # self.subfolder_edit = QLineEdit()
        # self.subfolder_edit.setStyleSheet(DARK_STYLES['compact_lineedit'])
        # self.subfolder_edit.setPlaceholderText("{mode}/{date} 또는 {mode}/{timestamp}")
        # self.subfolder_edit.textChanged.connect(self._on_subfolder_format_changed)        
        # subfolder_layout.addWidget(subfolder_label)
        # subfolder_layout.addWidget(self.subfolder_edit)
        # layout.addLayout(subfolder_layout)
        
        return section
    
    def _create_module_management_section(self) -> QWidget:
        """모듈 관리 섹션"""
        section, layout = self._create_section_frame("🧩 모듈 가시성 관리")
        
        # 모듈 목록 컨테이너 (일반 박스)
        self.module_container = QWidget()
        self.module_container.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        self.module_layout = QVBoxLayout(self.module_container)
        self.module_layout.setSpacing(4)
        self.module_layout.setContentsMargins(8, 8, 8, 8)
        
        layout.addWidget(self.module_container)
        
        # 새로고침 버튼
        refresh_modules_btn = QPushButton("모듈 목록 새로고침")
        refresh_modules_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        refresh_modules_btn.clicked.connect(self._refresh_module_list)
        layout.addWidget(refresh_modules_btn)
        
        return section
    
    def _create_tab_management_section(self) -> QWidget:
        """탭 관리 섹션"""
        section, layout = self._create_section_frame("📑 탭 가시성 관리")
        
        # 탭 목록 컨테이너 (일반 박스)
        self.tab_container = QWidget()
        self.tab_container.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        self.tab_layout = QVBoxLayout(self.tab_container)
        self.tab_layout.setSpacing(4)
        self.tab_layout.setContentsMargins(8, 8, 8, 8)
        
        layout.addWidget(self.tab_container)
        
        # 새로고침 버튼
        refresh_tabs_btn = QPushButton("탭 목록 새로고침")
        refresh_tabs_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        refresh_tabs_btn.clicked.connect(self._refresh_tab_list)
        layout.addWidget(refresh_tabs_btn)
        
        return section
    
    def _create_ui_settings_section(self) -> QWidget:
        """UI 설정 섹션"""
        section, layout = self._create_section_frame("🎨 UI 설정")
        
        # UI 스케일링 설정
        scaling_layout = QHBoxLayout()
        
        # 현재 스케일링 정보 표시
        scaling_manager = get_scaling_manager()
        current_scale = scaling_manager.get_scale_factor()
        auto_scaling = scaling_manager.is_auto_scaling_enabled()
        user_scale = scaling_manager.get_user_scale_factor()
        
        if auto_scaling:
            scale_text = f"자동 스케일링 ({current_scale:.1f}x)"
        else:
            scale_text = f"수동 스케일링 ({user_scale:.1f}x)"
            
        self.ui_scale_label = QLabel(f"UI 크기: {scale_text}")
        dynamic_styles = get_dynamic_styles()
        self.ui_scale_label.setStyleSheet(dynamic_styles['label_style'])
        
        # UI 크기 설정 버튼
        ui_scale_btn = QPushButton("UI 크기 설정")
        ui_scale_btn.setStyleSheet(dynamic_styles['secondary_button'])
        ui_scale_btn.clicked.connect(self._open_scaling_settings)
        ui_scale_btn.setToolTip("화면 해상도에 맞는 UI 크기를 설정합니다")
        
        scaling_layout.addWidget(self.ui_scale_label)
        scaling_layout.addStretch()
        scaling_layout.addWidget(ui_scale_btn)
        layout.addLayout(scaling_layout)
        
        # 자동 저장
        self.auto_save_checkbox = QCheckBox("설정 자동 저장")
        self.auto_save_checkbox.setStyleSheet(dynamic_styles['dark_checkbox'])
        self.auto_save_checkbox.toggled.connect(self._on_auto_save_toggled)
        layout.addWidget(self.auto_save_checkbox)
        
        return section
    
    # =========================
    # 이벤트 핸들러들
    # =========================
    
    def _on_autocomplete_toggled(self, checked: bool):
        """자동완성 토글"""
        self.settings_module.set_setting('autocomplete.enabled', checked)
        self.settings_module.autocomplete_toggled.emit(checked)
        
        # 실제 자동완성 시스템에 반영
        if hasattr(self.app_context, 'main_window'):
            main_window = self.app_context.main_window
            if hasattr(main_window, 'autocomplete_manager'):
                if checked:
                    main_window.autocomplete_manager.enable()
                else:
                    main_window.autocomplete_manager.disable()
    
    # TODO: 자동완성 세부 설정 기능들 (제거됨)
    # def _on_min_chars_changed(self, value: int):
    #     """최소 문자수 변경"""
    #     self.settings_module.set_setting('autocomplete.min_chars', value)
    
    # def _on_max_suggestions_changed(self, value: int):
    #     """최대 제안수 변경"""
    #     self.settings_module.set_setting('autocomplete.max_suggestions', value)
    
    def _on_save_path_changed(self, text: str):
        """저장 경로 변경"""
        self.settings_module.set_setting('save_directory.base_path', text)
        self.settings_module.save_directory_changed.emit(text)
        
        # AppContext를 통해 저장 경로 변경
        if self.app_context and hasattr(self.app_context, 'set_base_save_directory'):
            self.app_context.set_base_save_directory(text)
    
    def _browse_save_path(self):
        """저장 경로 찾아보기"""
        current_path = self.settings_module.get_setting('save_directory.base_path', './output')
        new_path = QFileDialog.getExistingDirectory(
            self, "저장 디렉토리 선택", current_path
        )
        if new_path:
            self.save_path_edit.setText(new_path)
    
    # TODO: 자동 분류 기능 구현 예정
    # def _on_classification_toggled(self, checked: bool):
    #     """자동 분류 토글"""
    #     self.settings_module.set_setting('save_directory.classification_enabled', checked)
    
    # def _on_subfolder_format_changed(self, text: str):
    #     """하위폴더 형식 변경"""
    #     self.settings_module.set_setting('save_directory.subfolder_format', text)
    
    # TODO: 폰트 크기 변경 기능 구현 예정
    # def _on_font_size_changed(self, value: int):
    #     """폰트 크기 변경"""
    #     self.settings_module.set_setting('ui.font_size', value)
    #     # 실제 UI에 적용 (전역 폰트 변경 로직 필요)
    
    def _on_auto_save_toggled(self, checked: bool):
        """자동 저장 토글"""
        self.settings_module.set_setting('ui.auto_save', checked)
    
    def _refresh_module_list(self):
        """모듈 목록 새로고침"""
        # 기존 체크박스들 제거
        for i in reversed(range(self.module_layout.count())):
            child = self.module_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        if (hasattr(self.app_context, 'middle_section_controller') and 
            self.app_context.middle_section_controller):
            
            controller = self.app_context.middle_section_controller
            for module in controller.module_instances:
                checkbox = QCheckBox(module.get_title())
                checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
                
                # 현재 가시성 상태 확인
                module_id = module.__class__.__name__
                is_visible = self.settings_module.get_setting(f'module_visibility.{module_id}', True)
                checkbox.setChecked(is_visible)
                
                # 체크박스 토글 시 이벤트 연결
                checkbox.toggled.connect(
                    lambda checked, mid=module_id: self._on_module_visibility_changed(mid, checked)
                )
                
                self.module_layout.addWidget(checkbox)
    
    def _refresh_tab_list(self):
        """탭 목록 새로고침"""
        # 기존 체크박스들 제거
        for i in reversed(range(self.tab_layout.count())):
            child = self.tab_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        # 숨길 수 있는 탭들만 허용
        hideable_tabs = ['BrowserTabModule', 'PNGInfoTabModule', 'HookerTabModule', 'StorytellerTabModule', 'AssetsTabModule']
        
        # RightView의 TabController에서 탭 정보 가져오기
        if (hasattr(self.app_context, 'main_window') and 
            hasattr(self.app_context.main_window, 'image_window') and
            hasattr(self.app_context.main_window.image_window, 'tab_controller')):
            
            tab_controller = self.app_context.main_window.image_window.tab_controller
            for tab_id, instance in tab_controller.module_instances.items():
                # 숨길 수 있는 탭인지 확인
                if instance.__class__.__name__ in hideable_tabs:
                    checkbox = QCheckBox(instance.get_tab_title())
                    checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
                    
                    # 현재 가시성 상태 확인
                    is_visible = self.settings_module.get_setting(f'tab_visibility.{tab_id}', True)
                    checkbox.setChecked(is_visible)
                    
                    # 체크박스 토글 시 이벤트 연결
                    checkbox.toggled.connect(
                        lambda checked, tid=tab_id: self._on_tab_visibility_changed(tid, checked)
                    )
                    
                    self.tab_layout.addWidget(checkbox)
    
    def _on_module_visibility_changed(self, module_id: str, visible: bool):
        """모듈 가시성 변경"""
        self.settings_module.set_setting(f'module_visibility.{module_id}', visible)
        self.settings_module.module_visibility_changed.emit(module_id, visible)
        
        # 실제 모듈 가시성 적용
        if (hasattr(self.app_context, 'middle_section_controller') and 
            self.app_context.middle_section_controller):
            
            controller = self.app_context.middle_section_controller
            # module_instances에서 해당 모듈 찾기
            for module in controller.module_instances:
                if module.__class__.__name__ == module_id:
                    module_title = module.get_title()
                    # module_boxes에서 해당 박스 찾아서 가시성 조절
                    if module_title in controller.module_boxes:
                        box = controller.module_boxes[module_title]
                        box.setVisible(visible)
                        print(f"Module '{module_title}' visibility changed to {visible}")
                    break
    
    def _on_tab_visibility_changed(self, tab_id: str, visible: bool):
        """탭 가시성 변경"""
        self.settings_module.set_setting(f'tab_visibility.{tab_id}', visible)
        self.settings_module.tab_visibility_changed.emit(tab_id, visible)
        
        # 실제 탭 가시성 적용 (탭 숨기기/표시하기)
        if (hasattr(self.app_context, 'main_window') and 
            hasattr(self.app_context.main_window, 'image_window') and
            hasattr(self.app_context.main_window.image_window, 'tab_controller')):
            
            tab_controller = self.app_context.main_window.image_window.tab_controller
            if tab_id in tab_controller.tab_index_map:
                tab_index = tab_controller.tab_index_map[tab_id]
                tab_controller.tab_widget.setTabVisible(tab_index, visible)
    
    def update_ui_from_settings(self):
        """저장된 설정으로 UI 업데이트"""
        # 자동완성 설정
        self.autocomplete_checkbox.setChecked(
            self.settings_module.get_setting('autocomplete.enabled', True)
        )
        
        # 저장 디렉토리 설정
        self.save_path_edit.setText(
            self.settings_module.get_setting('save_directory.base_path', './output')
        )
        
        # UI 설정
        self.auto_save_checkbox.setChecked(
            self.settings_module.get_setting('ui.auto_save', True)
        )
        
        # 모듈 및 탭 목록 새로고침
        QTimer.singleShot(100, self._refresh_module_list)
        QTimer.singleShot(100, self._refresh_tab_list)
        
        # 저장된 모듈 가시성 설정 적용
        QTimer.singleShot(200, self._apply_saved_module_visibility)
        
        # 저장된 탭 가시성 설정 적용
        QTimer.singleShot(300, self._apply_saved_tab_visibility)
        
        # 저장된 자동완성 및 UI 설정 적용
        QTimer.singleShot(400, self._apply_saved_autocomplete_settings)
        QTimer.singleShot(500, self._apply_saved_ui_settings)
    
    def _apply_saved_module_visibility(self):
        """저장된 모듈 가시성 설정을 실제 UI에 적용"""
        if (hasattr(self.app_context, 'middle_section_controller') and 
            self.app_context.middle_section_controller):
            
            controller = self.app_context.middle_section_controller
            for module in controller.module_instances:
                module_id = module.__class__.__name__
                # 저장된 가시성 설정 가져오기 (기본값은 True)
                is_visible = self.settings_module.get_setting(f'module_visibility.{module_id}', True)
                
                # 가시성이 False인 경우에만 숨기기
                if not is_visible:
                    module_title = module.get_title()
                    if module_title in controller.module_boxes:
                        box = controller.module_boxes[module_title]
                        box.setVisible(False)
                        print(f"Module '{module_title}' hidden on startup")
    
    def _apply_saved_tab_visibility(self):
        """저장된 탭 가시성 설정을 실제 UI에 적용"""
        if (hasattr(self.app_context, 'main_window') and 
            hasattr(self.app_context.main_window, 'image_window') and 
            hasattr(self.app_context.main_window.image_window, 'tab_controller')):
            
            tab_controller = self.app_context.main_window.image_window.tab_controller
            
            # 숨길 수 있는 탭들
            hideable_tabs = [
                'BrowserTabModule',      # 📦 Danbooru
                'PNGInfoTabModule',      # 📝 PNG Info
                'HookerTabModule',       # 🔍 Hooker
                'StorytellerTabModule',  # Storyteller 탭
                'AssetsTabModule'        # 🎨 Assets
            ]
            
            for tab_id in hideable_tabs:
                if tab_id in tab_controller.tab_index_map:
                    # 저장된 가시성 설정 가져오기 (기본값은 True)
                    is_visible = self.settings_module.get_setting(f'tab_visibility.{tab_id}', True)
                    
                    # 탭 가시성 적용
                    tab_index = tab_controller.tab_index_map[tab_id]
                    tab_controller.tab_widget.setTabVisible(tab_index, is_visible)
                    
                    if not is_visible:
                        print(f"📑 Tab '{tab_id}' hidden on startup based on saved settings")
    
    def _apply_saved_autocomplete_settings(self):
        """저장된 자동완성 설정을 실제로 적용"""
        # 저장된 자동완성 설정 가져오기
        autocomplete_enabled = self.settings_module.get_setting('autocomplete.enabled', True)
        
        # 실제 자동완성 시스템에 반영
        if hasattr(self.app_context, 'main_window'):
            main_window = self.app_context.main_window
            if hasattr(main_window, 'autocomplete_manager'):
                # AutoCompleteManager의 enable/disable 메서드 사용
                if autocomplete_enabled:
                    main_window.autocomplete_manager.enable()
                else:
                    main_window.autocomplete_manager.disable()
                print(f"🔍 Autocomplete {'enabled' if autocomplete_enabled else 'disabled'} on startup")
    
    def _apply_saved_ui_settings(self):
        """저장된 UI 설정을 실제로 적용"""
        # UI 스케일링 설정 적용
        if hasattr(self.app_context, 'main_window'):
            main_window = self.app_context.main_window
            
            # 스케일링 매니저 가져오기
            if hasattr(main_window, 'scaling_manager'):
                scaling_manager = main_window.scaling_manager
                
                # 저장된 UI 설정 가져오기
                auto_scaling = self.settings_module.get_setting('ui.auto_scaling', True)
                user_scale = self.settings_module.get_setting('ui.user_scale_factor', 1.0)
                
                # 설정 적용
                scaling_manager.set_auto_scaling_enabled(auto_scaling)
                if not auto_scaling:
                    scaling_manager.set_user_scale_factor(user_scale)
                    
                print(f"🎨 UI scaling applied on startup: auto={auto_scaling}, scale={user_scale}")
    
    def reset_to_defaults(self):
        """설정을 기본값으로 리셋"""
        reply = QMessageBox.question(
            self, "설정 리셋", 
            "모든 설정을 기본값으로 되돌리시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.settings_module.settings_data = self.settings_module._get_default_settings()
            self.settings_module.save_settings()
            self.update_ui_from_settings()
            QMessageBox.information(self, "완료", "설정이 기본값으로 초기화되었습니다.")
    
    def export_settings(self):
        """설정 내보내기"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "설정 내보내기", "naia_settings.json", "JSON Files (*.json)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.settings_module.settings_data, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "완료", f"설정이 {file_path}로 내보내졌습니다.")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 내보내기 실패: {e}")
    
    def import_settings(self):
        """설정 가져오기"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "설정 가져오기", "", "JSON Files (*.json)"
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    imported_settings = json.load(f)
                
                # 설정 유효성 검사
                if self._validate_settings(imported_settings):
                    self.settings_module.settings_data = imported_settings
                    self.settings_module.save_settings()
                    self.update_ui_from_settings()
                    QMessageBox.information(self, "완료", "설정이 성공적으로 가져와졌습니다.")
                else:
                    QMessageBox.warning(self, "오류", "유효하지 않은 설정 파일입니다.")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 가져오기 실패: {e}")
    
    def _validate_settings(self, settings: dict) -> bool:
        """설정 데이터 유효성 검사"""
        required_keys = ['autocomplete', 'save_directory', 'ui']
        return all(key in settings for key in required_keys)
    
    def _open_scaling_settings(self):
        """UI 스케일링 설정 다이얼로그 열기"""
        dialog = ScalingSettingsDialog(self)
        dialog.scaling_changed.connect(self._on_scaling_changed)
        dialog.exec()
    
    def _on_scaling_changed(self, new_scale: float):
        """스케일링 변경 시 호출"""
        # 라벨 텍스트 업데이트
        scaling_manager = get_scaling_manager()
        auto_scaling = scaling_manager.is_auto_scaling_enabled()
        user_scale = scaling_manager.get_user_scale_factor()
        current_scale = scaling_manager.get_scale_factor()
        
        if auto_scaling:
            scale_text = f"자동 스케일링 ({current_scale:.1f}x)"
        else:
            scale_text = f"수동 스케일링 ({user_scale:.1f}x)"
            
        self.ui_scale_label.setText(f"UI 크기: {scale_text}")
        
        # 메인 윈도우의 스케일링 변경 이벤트 호출
        if (hasattr(self.app_context, 'main_window') and 
            hasattr(self.app_context.main_window, 'on_scaling_changed')):
            self.app_context.main_window.on_scaling_changed(new_scale)