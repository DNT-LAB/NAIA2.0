import os
import glob
import importlib.util
import traceback
from pathlib import Path
from typing import Type, List, Dict, Optional
from PyQt6.QtWidgets import QTabWidget, QWidget, QPushButton, QTabBar
from PyQt6.QtCore import QObject, pyqtSignal
from interfaces.base_tab_module import BaseTabModule
from core.context import AppContext
from ui.theme import DARK_STYLES

class TabController(QObject):
    """
    오른쪽 패널의 탭들을 동적으로 로드하고 관리하는 컨트롤러
    """
    tab_added = pyqtSignal(str)  # tab_id
    tab_removed = pyqtSignal(str)  # tab_id
    
    def __init__(self, tabs_dir: str, app_context: AppContext, parent: QWidget = None):
        super().__init__()
        self.tabs_dir = tabs_dir
        self.app_context = app_context
        self.parent_widget = parent
        self.tab_widget = None
        
        self.module_classes: List[Type[BaseTabModule]] = []
        self.module_instances: Dict[str, BaseTabModule] = {}
        self.tab_index_map: Dict[str, int] = {}  # tab_id -> index 매핑
        
        if not os.path.exists(tabs_dir):
            os.makedirs(tabs_dir)
            print(f"📁 탭 모듈 디렉토리 생성: {tabs_dir}")

    def load_tab_modules(self) -> None:
        """탭 디렉토리에서 *_tab.py 파일들을 로드"""
        print(f"🔍 탭 모듈 로드 시작: {self.tabs_dir}")
        
        pattern = os.path.join(self.tabs_dir, "*_tab.py")
        module_files = glob.glob(pattern)
        
        if not module_files:
            print("❌ 탭 모듈 파일이 없습니다.")
            print("💡 다음 파일들을 tab_modules/ 디렉토리에 복사하세요:")
            expected_tabs = [
                'image_display_tab.py',
                'png_info_tab.py',
                'browser_tab.py',
                'api_management_tab.py'
            ]
            for tab in expected_tabs:
                print(f"  - {tab}")
            return
        
        print(f"📋 발견된 탭 파일: {[os.path.basename(f) for f in module_files]}")
        
        for path in module_files:
            name = Path(path).stem
            try:
                spec = importlib.util.spec_from_file_location(name, path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # 모듈에서 BaseTabModule을 상속한 클래스 찾기
                    for attr in dir(module):
                        obj = getattr(module, attr)
                        if (isinstance(obj, type) and 
                            issubclass(obj, BaseTabModule) and 
                            obj is not BaseTabModule):
                            self.module_classes.append(obj)
                            print(f"✅ 탭 모듈 로드 성공: {name} -> {obj.__name__}")
                            
            except Exception as e:
                print(f"❌ 탭 모듈 로드 실패 ({name}): {e}")
                traceback.print_exc()
                continue

    def setup_tab_widget(self) -> QTabWidget:
        """탭 위젯을 생성하고 모든 탭을 배치합니다."""
        if not self.module_classes:
            self.load_tab_modules()
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(DARK_STYLES['dark_tabs'])
        
        # 탭들을 order 순서대로 정렬
        sorted_classes = sorted(self.module_classes, key=lambda c: c().get_tab_order())
        
        for cls in sorted_classes:
            try:
                self.add_tab_from_class(cls)
            except Exception as e:
                print(f"탭 '{cls.__name__}' 생성 중 오류: {e}")
        
        # 모든 탭 초기화
        for instance in self.module_instances.values():
            try:
                instance.on_initialize()
            except Exception as e:
                print(f"⚠️ 탭 초기화 오류 ({instance.__class__.__name__}): {e}")
        
        return self.tab_widget

    def add_tab_from_class(self, cls: Type[BaseTabModule]):
        """클래스로부터 탭 인스턴스를 생성하고 탭 위젯에 추가합니다."""
        instance = cls()
        instance.initialize_with_context(self.app_context)
        
        widget = instance.create_widget(self.parent_widget)
        tab_index = self.tab_widget.addTab(widget, instance.get_tab_title())
        
        # 인스턴스와 인덱스 저장
        self.module_instances[instance.tab_id] = instance
        self.tab_index_map[instance.tab_id] = tab_index
        
        # 닫기 가능한 탭에 닫기 버튼 추가
        if instance.can_close_tab():
            self.add_close_button(tab_index, instance.tab_id)
        
        self.tab_added.emit(instance.tab_id)
        print(f"✅ 탭 추가 완료: {instance.get_tab_title()}")

    def add_close_button(self, tab_index: int, tab_id: str):
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
        
        self.tab_widget.tabBar().setTabButton(
            tab_index, QTabBar.ButtonPosition.RightSide, close_button
        )

    def close_tab(self, tab_id: str):
        """탭을 닫습니다."""
        if tab_id not in self.module_instances:
            return
        
        instance = self.module_instances[tab_id]
        
        # 닫기 전 확인
        if not instance.on_tab_closing():
            return
        
        # 탭 제거
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
        print(f"✅ 탭 제거 완료: {instance.get_tab_title()}")

    def _rebuild_index_mapping(self):
        """탭 인덱스 매핑을 재구축합니다."""
        self.tab_index_map.clear()
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            for tab_id, instance in self.module_instances.items():
                if instance.create_widget(None) == widget:
                    self.tab_index_map[tab_id] = i
                    break

    def get_tab_instance(self, tab_id: str) -> Optional[BaseTabModule]:
        """탭 ID로 탭 인스턴스를 반환합니다."""
        return self.module_instances.get(tab_id)

    def switch_to_tab(self, tab_id: str):
        """특정 탭으로 전환합니다."""
        if tab_id in self.tab_index_map:
            self.tab_widget.setCurrentIndex(self.tab_index_map[tab_id])

    def save_all_tab_settings(self):
        """모든 탭의 설정을 저장합니다."""
        print("🔧 모든 탭의 설정 저장을 시도합니다...")
        for instance in self.module_instances.values():
            if hasattr(instance, 'save_settings') and callable(getattr(instance, 'save_settings')):
                try:
                    instance.save_settings()
                    print(f"  - {instance.get_tab_title()} 설정 저장 완료.")
                except Exception as e:
                    print(f"  - ❌ {instance.get_tab_title()} 설정 저장 실패: {e}")