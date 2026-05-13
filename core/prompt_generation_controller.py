from PyQt6.QtCore import QObject, pyqtSignal
import pandas as pd
from core.search_result_model import SearchResultModel
from core.prompt_processor import PromptProcessor
from core.context import AppContext
from core.prompt_context import PromptContext
from core.wildcard_processor import split_tags_smart

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
        
        # 🔧 [수정] 기존 컨텍스트의 순차 카운터 보존
        existing_sequential_counters = {}
        existing_wildcard_state = {}
        if (hasattr(self.app_context, 'current_prompt_context') and 
            self.app_context.current_prompt_context):
            existing_sequential_counters = self.app_context.current_prompt_context.sequential_counters.copy()
            existing_wildcard_state = self.app_context.current_prompt_context.wildcard_state.copy()
        
        context = PromptContext(source_row=source_row, settings=settings)
        
        # 기존 순차 카운터와 상태 복원
        context.sequential_counters = existing_sequential_counters
        context.wildcard_state = existing_wildcard_state
        
        general_str = source_row.get('general', '')
        if pd.notna(general_str) and isinstance(general_str, str):
            context.main_tags = split_tags_smart(general_str)
        return context

    def _handle_processed_context(self, context):
        """처리된 컨텍스트를 받아 시그널과 이벤트를 발생시키는 공통 핸들러"""
        if context:
            final_prompt = str(context.final_prompt or "")
            if (
                not final_prompt.strip(" ,\n\r\t")
                and not context.settings.get('wildcard_standalone', False)
            ):
                self.generation_error.emit("생성된 프롬프트가 비어 있습니다. 다른 검색 결과를 사용해 주세요.")
                return

            # 해상도 자동 맞춤 결과가 있다면 시그널 발생
            if 'detected_resolution' in context.metadata:
                width, height = context.metadata['detected_resolution']
                self.resolution_detected.emit(width, height)
            elif context.settings.get('auto_fit_resolution', False):
                # 해상도 미감지 → 이전 사이클의 감지 플래그를 리셋
                # (랜덤 해상도 등 후속 처리가 올바르게 작동하도록)
                main_window = self.app_context.main_window
                if hasattr(main_window, 'resolution_is_detected'):
                    main_window.resolution_is_detected = False
            
            # 최종 프롬프트 시그널 발생
            self.prompt_generated.emit(final_prompt)
            
            # ✅ 와일드카드 상태 뷰를 위한 이벤트 발행
            self.app_context.publish("prompt_generated", context)
        
    def generate_instant_source_silent(self, instant_row: dict, settings: dict) -> str | None:
        """태그를 프롬프트로 정제하여 반환 (시그널 미발행, app_context 상태 복원)"""
        saved_source = self.app_context.current_source_row
        saved_context = self.app_context.current_prompt_context
        try:
            processed = {}
            for key, value in instant_row.items():
                if isinstance(value, list):
                    processed[key] = ', '.join(map(str, value))
                else:
                    processed[key] = value
            series = pd.Series(processed)
            self.app_context.current_source_row = series
            self.app_context.current_prompt_context = self._create_initial_context(series, settings)
            final_context = self.processor.process()
            return final_context.final_prompt if final_context else None
        except Exception as e:
            print(f"[TagInterrogation] Silent generation error: {e}")
            return None
        finally:
            self.app_context.current_source_row = saved_source
            self.app_context.current_prompt_context = saved_context

    def generate_instant_source(self, instant_row: dict | pd.Series, settings: dict):
        """즉시 생성 요청을 처리합니다. (단순화)"""
        if isinstance(instant_row, dict):
            processed_dict = {}
            for key, value in instant_row.items():
                if isinstance(value, list):
                    # 리스트의 모든 요소를 문자열로 변환하여 join
                    # ✅ 언더바는 제거하지 않음 (EZ Mode 등에서 정확한 태그 전달을 위해)
                    processed_dict[key] = ', '.join(map(str, value))
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

    def generate_next_prompt(self, search_results: SearchResultModel, settings: dict,
                             active_ratings: set = None, source_row_override: pd.Series = None):
        """다음 프롬프트를 생성합니다. (단순화)
        active_ratings: Rating 필터 (None이면 전체에서 추출)
        source_row_override: 외부에서 직접 주입하는 source_row (tag filter 등). pop 없이 사용.
        """
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
        elif source_row_override is not None:
            # 외부 주입 (Remote tag filter): search_results에서 pop하지 않음
            source_row = source_row_override
            self.prompt_popped.emit(search_results.get_count())
        else:
            # 기존 로직: 검색 결과에서 프롬프트를 가져옵니다.
            source_row = search_results.pop_random_row(active_ratings)
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
