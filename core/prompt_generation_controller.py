from PyQt6.QtCore import QObject, pyqtSignal
import pandas as pd
from core.search_result_model import SearchResultModel
from core.context import AppContext
from core.prompt_generation_service import PromptGenerationResult, PromptGenerationService

class PromptGenerationController(QObject):
    """UI와 PromptProcessor를 중재하고 프롬프트 생성을 관리 (단순화됨)"""
    prompt_generated = pyqtSignal(str)
    generation_error = pyqtSignal(str)
    prompt_popped = pyqtSignal(int)
    resolution_detected = pyqtSignal(int, int)

    def __init__(self, app_context: AppContext):
        super().__init__()
        self.app_context = app_context
        self.service = PromptGenerationService(self.app_context)
        self.app_context.prompt_generation_service = self.service
        self.auto_generation_requested = False
        # 비동기 처리가 필요하다면 Worker/Thread 로직은 유지할 수 있습니다.

    def _create_initial_context(self, source_row: pd.Series, settings: dict):
        """Backward-compatible proxy for callers that still use the controller."""
        return self.service._create_initial_context(source_row, settings)

    def _emit_result(self, result: PromptGenerationResult):
        """처리된 컨텍스트를 받아 시그널과 이벤트를 발생시키는 공통 핸들러"""
        if not result or not result.context:
            return

        if result.error:
            self.generation_error.emit(result.error)
            return

        if result.detected_resolution:
            width, height = result.detected_resolution
            self.resolution_detected.emit(width, height)
        elif result.reset_resolution_detected:
            # 해상도 미감지 → 이전 사이클의 감지 플래그를 리셋
            # (랜덤 해상도 등 후속 처리가 올바르게 작동하도록)
            main_window = self.app_context.main_window
            if hasattr(main_window, 'resolution_is_detected'):
                main_window.resolution_is_detected = False

        # 최종 프롬프트 시그널 발생
        self.prompt_generated.emit(result.final_prompt or "")

        # ✅ 와일드카드 상태 뷰를 위한 이벤트 발행
        self.app_context.publish("prompt_generated", result.context)

    def _handle_processed_context(self, context):
        self._emit_result(self.service.build_result(context))

    def generate_instant_source_silent(self, instant_row: dict, settings: dict) -> str | None:
        """태그를 프롬프트로 정제하여 반환 (시그널 미발행, app_context 상태 복원)"""
        return self.service.generate_instant_source_silent(instant_row, settings)

    def generate_instant_source(self, instant_row: dict | pd.Series, settings: dict):
        """즉시 생성 요청을 처리합니다. (단순화)"""
        source_row_series = self.service.normalize_instant_source(instant_row)
        if source_row_series is None:
            self.generation_error.emit("지원되지 않는 즉시 생성 데이터 타입입니다.")
            return

        self.service.set_current_context(source_row_series, settings)

        try:
            # ✅ 이제 processor는 AppContext를 통해 공유된 context를 사용하게 됩니다.
            self._emit_result(self.service.process_current_context())
        except Exception as e:
            self.generation_error.emit(f"프롬프트 생성 중 오류: {e}")

    def generate_next_prompt(self, search_results: SearchResultModel, settings: dict,
                             active_ratings: set = None, source_row_override: pd.Series = None):
        """다음 프롬프트를 생성합니다. (단순화)
        active_ratings: Rating 필터 (None이면 전체에서 추출)
        source_row_override: 외부에서 직접 주입하는 source_row (tag filter 등). pop 없이 사용.
        """
        preparation = self.service.prepare_next_source(
            search_results,
            settings,
            active_ratings=active_ratings,
            source_row_override=source_row_override,
        )
        if preparation.error:
            self.generation_error.emit(preparation.error)
            return
        if preparation.remaining_count is not None:
            self.prompt_popped.emit(preparation.remaining_count)
        source_row = preparation.source_row

        self.service.set_current_context(source_row, settings)

        self.prompt_popped.emit(search_results.get_count())

        try:
            # ✅ 이제 processor는 AppContext를 통해 공유된 context를 사용하게 됩니다.
            self._emit_result(self.service.process_current_context())
        except Exception as e:
            self.generation_error.emit(f"프롬프트 생성 중 오류: {e}")
