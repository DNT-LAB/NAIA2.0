from core.api_service import APIService
from typing import TYPE_CHECKING, Optional, Dict, List, Callable
from interfaces.base_module import BaseMiddleModule
from core.filter_data_manager import FilterDataManager
from core.secure_token_manager import SecureTokenManager
from core.wildcard_manager import WildcardManager
from core.prompt_context import PromptContext
import pandas as pd
from datetime import datetime 
from pathlib import Path       

if TYPE_CHECKING:
    from NAIA_cold_v4 import ModernMainWindow
    from core.middle_section_controller import MiddleSectionController

class AppContext:
    """애플리케이션의 공유 자원 및 상태를 관리하는 컨텍스트"""
    def __init__(self, main_window: 'ModernMainWindow', wildcard_manager: WildcardManager):
        from core.api_service import APIService
        
        self.main_window = main_window
        self.wildcard_manager = wildcard_manager
        self.middle_section_controller: Optional['MiddleSectionController'] = None
        self.api_service = APIService(self)
        
        # [신규] 파이프라인 훅을 저장할 레지스트리
        # 구조: { 'PipelineName': { 'HookPoint': [(priority, module_instance), ...] } }
        self.pipeline_hooks = {}
        self.secure_token_manager = SecureTokenManager()
        self.filter_data_manager = FilterDataManager()
        self.current_source_row: Optional[pd.Series] = None
        self.current_prompt_context: Optional[PromptContext] = None
        session_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.session_save_path = Path("output") / session_timestamp
        self.session_save_path.mkdir(parents=True, exist_ok=True)
        self.subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_name: str, callback: Callable):
        """지정된 이벤트에 대한 콜백 함수(구독자)를 등록합니다."""
        # 이벤트 이름에 해당하는 리스트가 없으면 생성하고 콜백 추가
        self.subscribers.setdefault(event_name, []).append(callback)
        print(f"📬 이벤트 구독: '{event_name}' -> {callback.__self__.__class__.__name__}.{callback.__name__}")

    def publish(self, event_name: str, *args, **kwargs):
        """지정된 이벤트의 모든 구독자에게 데이터를 전달하며 콜백을 실행합니다."""
        if event_name in self.subscribers:
            print(f"🚀 이벤트 발행: '{event_name}' (구독자: {len(self.subscribers[event_name])}개)")
            # 해당 이벤트의 모든 콜백 함수를 순회하며 실행
            for callback in self.subscribers[event_name]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    print(f"⚠️ 이벤트 콜백 실행 중 오류 ({callback.__name__}): {e}")

    def register_pipeline_hook(self, hook_info: dict, module_instance: 'BaseMiddleModule'):
        """파이프라인 훅 레지스트리에 모듈을 등록합니다."""
        pipeline_name = hook_info.get('target_pipeline')
        hook_point = hook_info.get('hook_point')
        priority = hook_info.get('priority', 999)

        if not all([pipeline_name, hook_point]):
            return

        # 파이프라인 및 훅 포인트 딕셔너리가 없으면 생성
        self.pipeline_hooks.setdefault(pipeline_name, {}).setdefault(hook_point, [])
        
        # 우선순위와 함께 모듈 인스턴스 추가
        self.pipeline_hooks[pipeline_name][hook_point].append((priority, module_instance))
        
        # 등록 후 우선순위에 따라 정렬
        self.pipeline_hooks[pipeline_name][hook_point].sort(key=lambda x: x[0])
        print(f"훅 등록 완료: [{pipeline_name}/{hook_point}] (priority: {priority}) - {module_instance.get_title()}")

    def get_pipeline_hooks(self, pipeline_name: str, hook_point: str) -> list['BaseMiddleModule']:
        """특정 파이프라인/훅 포인트에 등록된 모듈 인스턴스 목록을 반환합니다."""
        hooks = self.pipeline_hooks.get(pipeline_name, {}).get(hook_point, [])
        # 정렬된 튜플에서 모듈 인스턴스만 추출하여 반환
        return [module_instance for priority, module_instance in hooks]