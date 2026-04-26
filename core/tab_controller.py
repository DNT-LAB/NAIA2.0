import os
import glob
import importlib.util
import traceback
from pathlib import Path
from typing import Type, List, Dict, Optional

from PyQt6.QtWidgets import QTabWidget, QWidget, QPushButton, QTabBar, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal

from interfaces.base_tab_module import BaseTabModule
from core.context import AppContext
from ui.theme import DARK_COLORS


REMOVED_TAB_MODULES = {
    'HookerTabModule',
    'StorytellerTabModule',
    'AssetsTabModule',
}

REMOVED_TAB_FILES = {
    'hooker_view',
    'storyteller_tab',
    'assets_tab',
}


TAB_MODULE_SPECS = {
    'ImageViewerModule': {
        'file': 'image_window',
        'title': '🖼️ 생성 결과',
        'order': 1,
        'tab_type': 'core',
        'lazy': False,
    },
    'BrowserTabModule': {
        'file': 'web_view',
        'title': '📦 Danbooru',
        'order': 2,
        'tab_type': 'core',
        'lazy': True,
    },
    'PngInfoTabModule': {
        'file': 'png_info_tab',
        'title': '📝 PNG Info',
        'order': 3,
        'tab_type': 'core',
        'lazy': True,
    },
    'ThumbnailsTabModule': {
        'file': 'thumbnails_tab',
        'title': '🖼️ Thumb',
        'order': 8,
        'tab_type': 'core',
        'lazy': True,
    },
    'ArtistThumbModule': {
        'file': 'artist_thumb_tab',
        'title': '🎨 Artists',
        'order': 50,
        'tab_type': 'core',
        'lazy': True,
    },
    'StudioTab': {
        'file': 'studio_tab',
        'title': 'Studio',
        'order': 60,
        'tab_type': 'core',
        'lazy': True,
    },
    'SettingsTabModule': {
        'file': 'setting_tabs',
        'title': '⚙️ Settings',
        'order': 999,
        'tab_type': 'core',
        'lazy': False,
    },
    'APIManagementTabModule': {
        'file': 'api_management_window',
        'title': '⚙️ API 관리',
        'order': 1000,
        'tab_type': 'closable',
        'lazy': True,
    },
    'DepthSearchTabModule': {
        'file': 'depth_search_window',
        'title': '🔬 심층 검색',
        'order': 1000,
        'tab_type': 'closable',
        'lazy': True,
    },
    'Img2ImgTabModule': {
        'file': 'img2img_tab',
        'title': '🖼️ Img2Img',
        'order': 1000,
        'tab_type': 'closable',
        'lazy': True,
    },
    'SimpleWebViewTabModule': {
        'file': 'simple_web_view',
        'title': '🌐 API 웹뷰',
        'order': 1000,
        'tab_type': 'dynamic',
        'lazy': True,
    },
    'TurboEventSequenceTabModule': {
        'file': 'turbo_event_sequence_tab',
        'title': '🚀 Turbo Sequence',
        'order': 1000,
        'tab_type': 'closable',
        'lazy': True,
    },
}


STARTUP_SKIPPED_TAB_FILES = REMOVED_TAB_FILES | {
    spec['file']
    for spec in TAB_MODULE_SPECS.values()
    if spec.get('lazy') or spec.get('tab_type') != 'core'
}


class TabController(QWidget):
    """
    RightView의 탭들을 동적으로 로드, 생성 및 관리하는 컨트롤러.
    MiddleSectionController와 유사한 패턴으로 작동합니다.
    """
    
    # 탭 추가/제거 시 다른 컴포넌트에 알리기 위한 시그널
    tab_added = pyqtSignal(str, object)  # tab_id, instance
    tab_removed = pyqtSignal(str) # tab_id

    def __init__(self, tabs_dir: str, app_context: AppContext, tab_widget: QTabWidget, parent: QWidget = None):
        super().__init__(parent)
        self.tabs_dir = tabs_dir
        self.app_context = app_context
        self.tab_widget = tab_widget  # UI 제어를 위해 RightView의 QTabWidget을 직접 참조

        self.module_classes: List[Type[BaseTabModule]] = []
        self.module_instances: Dict[str, BaseTabModule] = {}
        self.tab_index_map: Dict[str, int] = {}  # tab_id -> index 매핑
        self.lazy_tab_specs: Dict[str, dict] = {}
        self._module_class_by_name: Dict[str, Type[BaseTabModule]] = {}

        if not os.path.exists(tabs_dir):
            os.makedirs(tabs_dir)
            print(f"📁 탭 모듈 디렉토리 생성: {tabs_dir}")

    def initialize_tabs(self):
        """모든 탭 모듈을 로드하고 UI를 구성하는 메인 메서드"""
        self._load_tab_modules()

        startup_entries = []
        for cls in self.module_classes:
            try:
                temp_instance = cls()
                if temp_instance.get_tab_type() == 'core':
                    startup_entries.append({
                        'kind': 'class',
                        'class': cls,
                        'order': temp_instance.get_tab_order(),
                    })
                else:
                    print(f"  -> 동적 탭 '{temp_instance.get_tab_title()}'은 시작 시 로드하지 않습니다.")
            except Exception as e:
                print(f"❌ 탭 '{cls.__name__}' 검사 중 오류 발생: {e}")
                traceback.print_exc()

        for class_name, spec in TAB_MODULE_SPECS.items():
            if spec.get('tab_type') == 'core' and spec.get('lazy') and self._tab_file_exists(spec):
                startup_entries.append({
                    'kind': 'lazy',
                    'class_name': class_name,
                    'spec': spec,
                    'order': spec['order'],
                })

        for entry in sorted(startup_entries, key=lambda item: item['order']):
            try:
                if entry['kind'] == 'lazy':
                    self._add_lazy_tab(entry['class_name'], entry['spec'])
                    continue

                # 1. 모듈 인스턴스 생성
                cls = entry['class']
                instance = cls()
                tab_id = instance.tab_id

                # 2. 컨텍스트 주입
                instance.initialize_with_context(self.app_context)
                
                # 3. UI 위젯 생성
                widget = instance.create_widget(parent=self.tab_widget)
                
                # 4. 탭 위젯에 추가
                tab_index = self.tab_widget.addTab(widget, instance.get_tab_title())

                # 5. 인스턴스 및 정보 저장
                self.module_instances[tab_id] = instance
                self.tab_index_map[tab_id] = tab_index
                
                # 6. 닫기 가능한 탭에 닫기 버튼 추가
                if instance.can_close_tab():
                    self._add_close_button_to_tab(tab_index, tab_id)
                
                # 7. 초기화 완료 후 on_initialize 호출
                instance.on_initialize()
                
                self.tab_added.emit(tab_id, instance)
                print(f"✅ 탭 '{instance.get_tab_title()}' UI 생성 및 초기화 완료.")

            except Exception as e:
                class_name = entry.get('class_name') or entry.get('class', object).__name__
                print(f"❌ 탭 '{class_name}' 생성 중 오류 발생: {e}")
                traceback.print_exc()

    def _load_tab_modules(self):
        """'tabs/' 디렉토리에서 *.py 파일들을 찾아 클래스를 로드합니다."""
        print(f"🔍 탭 모듈 로드 시작: {self.tabs_dir}")
        pattern = os.path.join(self.tabs_dir, "*.py")
        module_files = glob.glob(pattern)

        for path in module_files:
            name = Path(path).stem
            if name in STARTUP_SKIPPED_TAB_FILES:
                print(f"  -> 시작 시 탭 파일 import 건너뜀: {name}.py")
                continue

            try:
                self._load_module_classes_from_path(name, path)
            except Exception as e:
                print(f"❌ 탭 모듈 로드 실패 ({name}): {e}")
                traceback.print_exc()

    def _load_module_classes_from_path(self, name: str, path: str) -> List[Type[BaseTabModule]]:
        loaded_classes = []
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for attr in dir(module):
                obj = getattr(module, attr)
                if isinstance(obj, type) and issubclass(obj, BaseTabModule) and obj is not BaseTabModule:
                    if obj.__name__ in REMOVED_TAB_MODULES:
                        print(f"  -> 제거된 탭 클래스 건너뜀: {obj.__name__}")
                        continue
                    if obj.__name__ not in self._module_class_by_name:
                        self.module_classes.append(obj)
                        self._module_class_by_name[obj.__name__] = obj
                        print(f"  -> 탭 모듈 클래스 발견: {obj.__name__}")
                    loaded_classes.append(obj)
        return loaded_classes

    def _tab_file_exists(self, spec: dict) -> bool:
        return os.path.exists(os.path.join(self.tabs_dir, f"{spec['file']}.py"))

    def _add_lazy_tab(self, class_name: str, spec: dict):
        if class_name in self.tab_index_map:
            return

        tab_id = class_name
        placeholder = self._create_lazy_placeholder(spec['title'])
        tab_index = self.tab_widget.addTab(placeholder, spec['title'])
        self.tab_index_map[tab_id] = tab_index
        self.lazy_tab_specs[tab_id] = spec
        print(f"⏳ 탭 '{spec['title']}'은 선택 시 지연 로드됩니다.")

    def _create_lazy_placeholder(self, title: str) -> QWidget:
        placeholder = QWidget(self.tab_widget)
        layout = QVBoxLayout(placeholder)
        label = QLabel(f"{title}\n선택하면 로드됩니다.")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: 14px;")
        layout.addWidget(label)
        return placeholder

    def _get_module_class(self, module_class_name: str) -> Optional[Type[BaseTabModule]]:
        if module_class_name in self._module_class_by_name:
            return self._module_class_by_name[module_class_name]

        spec = TAB_MODULE_SPECS.get(module_class_name)
        if not spec:
            return None

        path = os.path.join(self.tabs_dir, f"{spec['file']}.py")
        if not os.path.exists(path):
            return None

        self._load_module_classes_from_path(spec['file'], path)
        return self._module_class_by_name.get(module_class_name)

    def ensure_tab_loaded_by_index(self, index: int) -> Optional[BaseTabModule]:
        for tab_id, tab_index in list(self.tab_index_map.items()):
            if tab_index == index:
                return self.ensure_tab_loaded(tab_id)
        return None

    def ensure_tab_loaded(self, tab_id: str) -> Optional[BaseTabModule]:
        if tab_id in self.module_instances:
            return self.module_instances[tab_id]

        spec = self.lazy_tab_specs.get(tab_id)
        if not spec:
            return None

        TargetModuleClass = self._get_module_class(tab_id)
        if not TargetModuleClass:
            print(f"❌ 지연 탭 '{tab_id}' 클래스를 찾을 수 없습니다.")
            return None

        tab_index = self.tab_index_map[tab_id]
        placeholder = self.tab_widget.widget(tab_index)
        was_visible = self.tab_widget.isTabVisible(tab_index)

        try:
            instance = TargetModuleClass()
            instance.initialize_with_context(self.app_context)
            widget = instance.create_widget(self.tab_widget)

            self.tab_widget.removeTab(tab_index)
            self.tab_widget.insertTab(tab_index, widget, instance.get_tab_title())
            self.tab_widget.setTabVisible(tab_index, was_visible)
            if placeholder:
                placeholder.deleteLater()

            self.module_instances[tab_id] = instance
            self.tab_index_map[tab_id] = tab_index
            self.lazy_tab_specs.pop(tab_id, None)

            if instance.can_close_tab():
                self._add_close_button_to_tab(tab_index, tab_id)

            instance.on_initialize()
            self.tab_added.emit(tab_id, instance)
            self.tab_widget.setCurrentIndex(tab_index)
            print(f"✅ 지연 탭 '{instance.get_tab_title()}' 로드 완료.")
            return instance

        except Exception as e:
            print(f"❌ 지연 탭 '{tab_id}' 생성 중 오류: {e}")
            traceback.print_exc()
            return None

    def _add_close_button_to_tab(self, tab_index: int, tab_id: str):
        """특정 탭에 닫기 버튼을 추가합니다."""
        close_button = QPushButton("✕")
        close_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 9px;
                font-family: Arial, sans-serif;
                font-weight: bold;
                font-size: 14px;
                color: #B0B0B0;
                padding: 0px 4px;
            }
            QPushButton:hover {
                background-color: #F44336;
                color: white;
            }
        """)
        close_button.setFixedSize(18, 18)
        close_button.setToolTip("탭 닫기")
        close_button.clicked.connect(lambda: self.close_tab(tab_id))
        
        self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.RightSide, close_button)

    def close_tab(self, tab_id: str):
        """탭 ID를 기반으로 탭을 닫습니다."""
        if tab_id not in self.module_instances:
            return
        
        instance = self.module_instances[tab_id]
        if not instance.on_tab_closing(): # 닫기 전 확인
            return
            
        # 탭 위젯에서 해당 위젯 찾아서 닫기
        tab_index = self.tab_index_map[tab_id]
        widget = self.tab_widget.widget(tab_index)
        self.tab_widget.removeTab(tab_index)
        
        # 정리 작업
        instance.cleanup()
        widget.deleteLater()
        
        # 매핑 정보 제거
        del self.module_instances[tab_id]
        del self.tab_index_map[tab_id]
        
        # 인덱스 매핑 재조정
        self._rebuild_index_mapping()
        
        self.tab_removed.emit(tab_id)
        print(f"✅ 탭 '{instance.get_tab_title()}' 제거 완료.")

    def _rebuild_index_mapping(self):
        """탭 인덱스 매핑을 재구축합니다."""
        self.tab_index_map.clear()
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            for tab_id, instance in self.module_instances.items():
                if hasattr(instance, 'widget') and instance.widget == widget:
                    self.tab_index_map[tab_id] = i
                    break

    def get_tab_instance(self, tab_id: str) -> Optional[BaseTabModule]:
        """탭 ID로 탭 인스턴스를 반환합니다."""
        return self.module_instances.get(tab_id)

    def get_tab_title(self, tab_id: str) -> str:
        """로드 여부와 관계없이 탭 제목을 반환합니다."""
        instance = self.module_instances.get(tab_id)
        if instance:
            return instance.get_tab_title()

        spec = self.lazy_tab_specs.get(tab_id) or TAB_MODULE_SPECS.get(tab_id)
        if spec:
            return spec['title']

        return tab_id
    
    def add_tab_by_name(self, module_class_name: str, **kwargs):
        """
        클래스 이름을 기반으로 탭을 동적으로 추가하고 활성화합니다.
        이미 탭이 열려있으면 해당 탭으로 전환합니다.
        """
        if module_class_name in REMOVED_TAB_MODULES:
            print(f"⚠️ 제거된 탭 '{module_class_name}'은 추가할 수 없습니다.")
            return

        # 1. 이미 해당 모듈의 인스턴스가 있는지 확인
        for instance in self.module_instances.values():
            if instance.__class__.__name__ == module_class_name:
                print(f"✅ 이미 열려있는 탭 '{instance.get_tab_title()}'으로 전환합니다.")
                self.switch_to_tab(instance.tab_id)
                return

        # 2. 로드된 클래스 목록에서 해당 클래스 찾기
        TargetModuleClass = self._get_module_class(module_class_name)

        if not TargetModuleClass:
            print(f"❌ '{module_class_name}'에 해당하는 탭 모듈 클래스를 찾을 수 없습니다.")
            return

        # 3. 새 탭 추가 (기존 add_tab_from_class 로직 재사용)
        try:
            instance = TargetModuleClass()
            instance.initialize_with_context(self.app_context)
            
            # 동적 데이터가 필요한 경우 setup 메서드 호출
            if hasattr(instance, 'setup'):
                instance.setup(**kwargs)

            widget = instance.create_widget(self.tab_widget)
            tab_index = self.tab_widget.addTab(widget, instance.get_tab_title())

            self.module_instances[instance.tab_id] = instance
            self.tab_index_map[instance.tab_id] = tab_index
            
            if instance.can_close_tab():
                self._add_close_button_to_tab(tab_index, instance.tab_id)
            
            instance.on_initialize()
            self.tab_widget.setCurrentIndex(tab_index) # 새로 추가된 탭으로 즉시 전환
            self.tab_added.emit(instance.tab_id, instance)
            print(f"✅ 동적 탭 '{instance.get_tab_title()}' 추가 완료.")

        except Exception as e:
            print(f"❌ 동적 탭 '{module_class_name}' 생성 중 오류: {e}")
            traceback.print_exc()

    def switch_to_tab(self, tab_id: str):
        """탭 ID를 기반으로 해당 탭으로 전환합니다."""
        if tab_id in self.tab_index_map:
            self.tab_widget.setCurrentIndex(self.tab_index_map[tab_id])
