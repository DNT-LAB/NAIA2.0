from PyQt6.QtCore import QObject, pyqtSignal
import pandas as pd
from core.search_result_model import SearchResultModel
from core.prompt_processor import PromptProcessor
from core.context import AppContext
from core.prompt_context import PromptContext

class PromptGenerationController(QObject):
    """UI와 PromptProcessor를 중재하고 프롬프트 생성을 관리 (단순화됨)"""
    prompt_generated = pyqtSignal(str)
    generation_error = pyqtSignal(str)
    prompt_popped = pyqtSignal(int)
    resolution_detected = pyqtSignal(int, int)

    def __init__(self, app_context: AppContext):
        super().__init__()
        self.app_context = app_context
        self.processor = PromptProcessor(self.app_context)
        # 비동기 처리가 필요하다면 Worker/Thread 로직은 유지할 수 있습니다.

    def _create_initial_context(self, source_row: pd.Series, settings: dict) -> PromptContext:
        """[신규] PromptContext를 생성하고 초기 태그를 설정하는 헬퍼 메소드"""
        context = PromptContext(source_row=source_row, settings=settings)
        general_str = source_row.get('general', '')
        if pd.notna(general_str) and isinstance(general_str, str):
            context.main_tags = [tag.strip() for tag in general_str.split(',')]
        return context

    def _handle_processed_context(self, context):
        """처리된 컨텍스트를 받아 시그널과 이벤트를 발생시키는 공통 핸들러"""
        if context:
            # 해상도 자동 맞춤 결과가 있다면 시그널 발생
            if 'detected_resolution' in context.metadata:
                width, height = context.metadata['detected_resolution']
                self.resolution_detected.emit(width, height)
            
            # 최종 프롬프트 시그널 발생
            self.prompt_generated.emit(context.final_prompt)
            
            # ✅ 와일드카드 상태 뷰를 위한 이벤트 발행
            self.app_context.publish("prompt_generated", context)
        
    def generate_instant_source(self, instant_row: dict | pd.Series, settings: dict):
        """즉시 생성 요청을 처리합니다. (단순화)"""
        if isinstance(instant_row, dict):
            processed_dict = {}
            for key, value in instant_row.items():
                if isinstance(value, list):
                    # 리스트의 모든 요소를 문자열로 변환하여 join
                    processed_dict[key] = ', '.join(map(str, value)).replace('_', ' ')
                else:
                    processed_dict[key] = value
            instant_row = processed_dict
            source_row_series = pd.Series(instant_row)
        elif isinstance(instant_row, pd.Series):
            source_row_series = instant_row
        else:
            self.generation_error.emit("지원되지 않는 즉시 생성 데이터 타입입니다.")
            return

        self.app_context.current_source_row = source_row_series
        self.app_context.current_prompt_context = self._create_initial_context(source_row_series, settings)
        
        try:
            # ✅ 이제 processor는 AppContext를 통해 공유된 context를 사용하게 됩니다.
            final_context = self.processor.process()
            self._handle_processed_context(final_context)
        except Exception as e:
            self.generation_error.emit(f"프롬프트 생성 중 오류: {e}")

    def generate_next_prompt(self, search_results: SearchResultModel, settings: dict):
        """다음 프롬프트를 생성합니다. (단순화)"""
        if settings.get('wildcard_standalone', False):
            # 단독 모드일 경우, 비어있는 source_row를 새로 생성합니다.
            empty_data = {
                'general': None,
                'character': None,
                'copyright': None,
                'artist': None,
                'meta': None
            }
            source_row = pd.Series(empty_data, name="wildcard_standalone")
            self.prompt_popped.emit(search_results.get_count()) # 남은 행 개수는 그대로 표시
        else:
            # 기존 로직: 검색 결과에서 프롬프트를 가져옵니다.
            source_row = search_results.pop_random_row()
            if source_row is None:
                self.generation_error.emit("처리할 프롬프트가 더 이상 없습니다.")
                return
            self.prompt_popped.emit(search_results.get_count())
        
        self.app_context.current_source_row = source_row
        self.app_context.current_prompt_context = self._create_initial_context(source_row, settings)
        
        self.prompt_popped.emit(search_results.get_count())

        try:
            # ✅ 이제 processor는 AppContext를 통해 공유된 context를 사용하게 됩니다.
            final_context = self.processor.process()
            self._handle_processed_context(final_context)
        except Exception as e:
            self.generation_error.emit(f"프롬프트 생성 중 오류: {e}")