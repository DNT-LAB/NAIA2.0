from abc import ABC, abstractmethod
from PyQt6.QtWidgets import QWidget
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import AppContext
    from core.prompt_context import PromptContext

class BaseMiddleModule(ABC):
    """중간 패널 모듈의 기본 인터페이스 (호환성 플래그 추가)"""
    
    def __init__(self):
        # 🆕 필수: 모든 모듈은 호환성 플래그를 가져야 함
        self.NAI_compatibility = True    # 기본값: NAI 호환
        self.WEBUI_compatibility = True  # 기본값: WEBUI 호환
        self.COMFYUI_compatibility = True
        
        # 기존 속성들
        self.app_context = None
        self.ignore_save_load = False
    
    @abstractmethod
    def get_title(self) -> str:
        """모듈 제목 반환"""
        pass
    
    @abstractmethod
    def create_widget(self, parent) -> 'QWidget':
        """UI 위젯 생성"""
        pass

    def get_module_name(self):
        return self.get_title
    
    def get_order(self) -> int:
        """UI 순서 (낮을수록 위에 표시)"""
        return 100
    
    def on_initialize(self):
        """모듈 초기화 시 호출"""
        pass
    
    def get_parameters(self) -> dict:
        """생성 파라미터 반환"""
        return {}
    
    def execute_pipeline_hook(self, context) -> 'PromptContext':
        """파이프라인 훅 실행"""
        return context
    
    def get_pipeline_hook_info(self) -> dict:
        """파이프라인 훅 정보 반환"""
        return {}
    
    def is_compatible_with_mode(self, mode: str) -> bool:
        """해당 모드와 호환되는지 확인 (기본 구현)"""
        if mode == "NAI":
            return getattr(self, 'NAI_compatibility', True)
        elif mode == "WEBUI":
            return getattr(self, 'WEBUI_compatibility', True)
        elif mode == "COMFYUI":  # 🆕 ComfyUI 모드 추가
            return getattr(self, 'COMFYUI_compatibility', True)
        return True # 알 수 없는 모드일 경우 기본적으로 표시