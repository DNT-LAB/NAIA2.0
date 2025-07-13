from abc import ABC, abstractmethod
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import pyqtSignal
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import AppContext

class BaseTabModule(ABC):
    """오른쪽 패널의 탭으로 동적 로드될 모든 모듈의 기반 추상 클래스"""
    
    # 탭 간 통신을 위한 공통 시그널들
    parameters_extracted = pyqtSignal(dict)
    instant_generation_requested = pyqtSignal(dict)
    tab_status_changed = pyqtSignal(str, str)  # tab_id, status_message

    def __init__(self):
        super().__init__()
        self.app_context = None
        self.tab_id = self.__class__.__name__  # 고유 식별자

    def initialize_with_context(self, app_context: 'AppContext'):
        """모듈에 AppContext를 주입합니다."""
        self.app_context = app_context

    @abstractmethod
    def get_tab_title(self) -> str:
        """탭의 제목을 반환합니다 (이모지 포함 가능)."""
        pass

    @abstractmethod
    def create_widget(self, parent: QWidget) -> QWidget:
        """탭의 UI 위젯을 생성하여 반환합니다."""
        pass

    def get_tab_order(self) -> int:
        """탭이 표시될 순서를 반환합니다. 숫자가 낮을수록 왼쪽에 표시됩니다."""
        return 999

    def get_tab_type(self) -> str:
        """탭의 유형을 반환합니다 ('core', 'closable', 'permanent')"""
        return 'core'  # 기본값: 핵심 탭 (닫을 수 없음)

    def can_close_tab(self) -> bool:
        """탭이 닫힐 수 있는지 여부를 반환합니다."""
        return self.get_tab_type() in ['closable']

    def on_tab_activated(self):
        """탭이 활성화될 때 호출되는 메서드 (선택사항)"""
        pass

    def on_tab_deactivated(self):
        """탭이 비활성화될 때 호출되는 메서드 (선택사항)"""
        pass

    def on_tab_closing(self) -> bool:
        """탭이 닫히기 전에 호출되는 메서드. False 반환 시 닫기 취소됩니다."""
        return True

    def cleanup(self):
        """탭이 제거될 때 정리 작업을 수행합니다."""
        pass

    # --- 설정 저장/로드 (선택사항) ---
    def save_settings(self):
        """탭의 설정을 저장합니다 (구현 선택사항)"""
        pass

    def load_settings(self):
        """탭의 설정을 로드합니다 (구현 선택사항)"""
        pass

    def on_initialize(self):
        """탭 초기화 완료 시 호출됩니다."""
        print(f"✅ {self.get_tab_title()} 탭 초기화 완료")