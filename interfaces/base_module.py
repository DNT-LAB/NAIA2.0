from abc import ABC, abstractmethod
from PyQt6.QtWidgets import QWidget
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import AppContext
    from core.prompt_context import PromptContext

class BaseMiddleModule(ABC):
    """왼쪽 중간 패널에 동적으로 로드될 모든 모듈의 기반 추상 클래스"""

    def __init__(self):
        self.context = None

    def initialize_with_context(self, context: 'AppContext'):
        """모듈에 AppContext를 주입합니다."""
        self.context = context

    @abstractmethod
    def get_title(self) -> str:
        """모듈의 제목(CollapsibleBox의 제목)을 반환합니다."""
        pass

    @abstractmethod
    def create_widget(self, parent: QWidget) -> QWidget:
        """모듈의 UI 위젯을 생성하여 반환합니다."""
        pass

    def get_parameters(self) -> Dict[str, Any]:
        """이미지 생성 시 필요한 파라미터를 반환합니다."""
        return {}

    def get_order(self) -> int:
        """모듈이 UI에 표시될 순서를 반환합니다. 숫자가 낮을수록 위에 표시됩니다."""
        return 999

    # --- [신규] 파이프라인 훅 관련 메서드 ---

    def get_pipeline_hook_info(self) -> Optional[Dict[str, Any]]:
        """
        모듈이 파이프라인 훅으로 동작할 경우, 관련 메타데이터를 반환합니다.
        훅 기능이 없는 모듈은 None을 반환합니다. (기본값)
        """
        return None

    def execute_pipeline_hook(self, context: Any) -> Any:
        """
        파이프라인 훅 로직을 실행합니다.
        데이터 컨텍스트를 받아 수정한 뒤, 그대로 다시 반환해야 합니다.
        """
        # 훅 기능이 있는 모듈은 이 메서드를 오버라이드해야 함
        return context
    
    def on_initialize(self):
        print(f"✅ {self.get_title()} 초기화 완료")
    