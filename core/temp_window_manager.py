# core/temp_window_manager.py
"""
임시 생성 창 관리자 (Temporary Window Manager)

여러 개의 TempGenerationWindow를 중앙에서 관리하며, 생명주기와 이벤트를 처리합니다.
메인 UI를 오염시키지 않고 독립적인 프롬프트 생성 및 이미지 생성을 지원합니다.
"""

from typing import Dict, Optional
from PyQt6.QtCore import QObject


class TempWindowManager(QObject):
    """
    임시 생성 창 관리자

    주요 역할:
    1. 여러 개의 TempGenerationWindow 추적 (window_id 기반)
    2. 각 창의 시그널 연결 및 처리
    3. 독립적인 프롬프트 생성 (메인 UI 오염 방지)
    4. GenerationController와 통합하여 이미지 생성 처리
    5. 창 생명주기 관리 (생성, 업데이트, 종료)
    """

    def __init__(self, main_window, app_context):
        """
        Args:
            main_window: ModernMainWindow 인스턴스 (프롬프트 생성에 필요)
            app_context: AppContext 인스턴스
        """
        super().__init__()

        self.main_window = main_window
        self.app_context = app_context

        # 임시 창 추적 딕셔너리 {window_id: TempGenerationWindow}
        self.temp_windows: Dict[int, 'TempGenerationWindow'] = {}

        # 다음 창 ID (자동 증가)
        self._next_window_id = 1

        print("[TempWindowManager] 초기화 완료")

    def create_temp_window(self) -> 'TempGenerationWindow':
        """
        새 임시 생성 창을 생성하고 등록합니다.

        Returns:
            TempGenerationWindow: 생성된 임시 창 인스턴스
        """
        from ui.temp_generation_window import TempGenerationWindow

        # 고유 창 ID 할당
        window_id = self._next_window_id
        self._next_window_id += 1

        print(f"[TempWindowManager] 임시 창 #{window_id} 생성 중...")

        # TempGenerationWindow 생성
        temp_window = TempGenerationWindow(
            window_id=window_id,
            app_context=self.app_context,
            parent=None  # 완전 독립 창
        )

        # 시그널 연결
        temp_window.generate_requested.connect(self.handle_generation_request)
        temp_window.params_update_requested.connect(self.handle_params_update_request)
        temp_window.random_prompt_requested.connect(self.handle_random_prompt_request)
        temp_window.window_closing.connect(self.handle_window_closing)

        # 메인 UI 프롬프트 복사
        main_prompt = self.main_window.main_prompt_edit.toPlainText()
        negative_prompt = self.main_window.negative_prompt_edit.toPlainText()
        temp_window.set_prompts(main_prompt, negative_prompt)

        # 메인 UI 생성 파라미터 복사
        temp_window.set_initial_params(self.main_window)

        # 🆕 메인 UI 모듈 상태 복사 (Issue 2 Fix)
        temp_window.initialize_from_main_modules(self.main_window)

        # 현재 API 모드에 맞게 UI 업데이트
        current_mode = self.app_context.get_api_mode()
        nai_model = None
        if current_mode == "NAI" and hasattr(self.main_window, 'model_combo'):
            nai_model = self.main_window.model_combo.currentText()
        temp_window.update_params_ui_for_mode(current_mode, nai_model)

        # 추적 딕셔너리에 등록
        self.temp_windows[window_id] = temp_window

        print(f"[TempWindowManager] 임시 창 #{window_id} 생성 완료 (총 {len(self.temp_windows)}개)")

        # 창 표시
        temp_window.show()
        temp_window.raise_()
        temp_window.activateWindow()

        return temp_window

    def handle_generation_request(self, window_id: int, params: dict):
        """
        임시 창에서 이미지 생성 요청 처리

        Args:
            window_id: 요청한 창의 ID
            params: 생성 파라미터 딕셔너리 (prompt, negative_prompt, steps, scale 등)
        """
        print(f"[TempWindowManager] 임시 창 #{window_id}에서 생성 요청 수신")

        # GenerationController에 전달
        if hasattr(self.main_window, 'handle_temp_window_generation'):
            self.main_window.handle_temp_window_generation(params)
        else:
            print(f"⚠️ [TempWindowManager] MainWindow에 handle_temp_window_generation 메서드가 없습니다")

    def handle_params_update_request(self, params: dict):
        """
        임시 창에서 메인 UI 파라미터 업데이트 요청 처리

        Args:
            params: 업데이트할 파라미터 딕셔너리
        """
        print(f"[TempWindowManager] 메인 UI 파라미터 업데이트 요청 수신")

        # 메인 UI에 프롬프트 적용
        if 'input' in params:
            self.main_window.main_prompt_edit.setPlainText(params['input'])
        if 'negative_prompt' in params:
            self.main_window.negative_prompt_edit.setPlainText(params['negative_prompt'])

        # 생성 파라미터 적용 (메인 윈도우의 메서드 활용)
        if hasattr(self.main_window, 'apply_params_from_temp_window'):
            self.main_window.apply_params_from_temp_window(params)
        else:
            print(f"⚠️ [TempWindowManager] MainWindow에 apply_params_from_temp_window 메서드가 없습니다")

    def handle_random_prompt_request(self, window_id: int):
        """
        🆕 Issue 1 Fix: 임시 창에서 Random/Next Prompt 요청 처리

        메인 UI를 오염시키지 않고 독립적으로 프롬프트를 생성하여 임시 창에 반영합니다.

        Args:
            window_id: 요청한 창의 ID
        """
        print(f"[TempWindowManager] 임시 창 #{window_id}에서 Random/Next Prompt 요청 수신")

        # 임시 창 확인
        temp_window = self.temp_windows.get(window_id)
        if not temp_window:
            print(f"⚠️ [TempWindowManager] 임시 창 #{window_id}를 찾을 수 없습니다")
            return

        # 프롬프트 고정 체크박스 상태 확인
        is_fixed = temp_window.prompt_fixed_checkbox.isChecked()

        # 독립적인 프롬프트 생성 (메인 UI 메서드 사용하되 결과만 가져옴)
        # 메인 UI의 프롬프트를 임시 저장
        original_main_prompt = self.main_window.main_prompt_edit.toPlainText()
        original_negative_prompt = self.main_window.negative_prompt_edit.toPlainText()

        try:
            # 메인 UI의 프롬프트 생성 메서드 호출
            # (프롬프트 고정 여부와 무관하게 동일한 메서드 사용 - 내부에서 처리됨)
            if hasattr(self.main_window, 'trigger_random_prompt'):
                self.main_window.trigger_random_prompt()
            else:
                print(f"⚠️ [TempWindowManager] MainWindow에 trigger_random_prompt 메서드가 없습니다")
                return

            # 생성된 프롬프트 가져오기
            new_main_prompt = self.main_window.main_prompt_edit.toPlainText()
            new_negative_prompt = self.main_window.negative_prompt_edit.toPlainText()

            # 임시 창에 프롬프트 업데이트
            temp_window.update_prompts(new_main_prompt, new_negative_prompt)

        finally:
            # 메인 UI 프롬프트 복원 (오염 방지)
            self.main_window.main_prompt_edit.setPlainText(original_main_prompt)
            self.main_window.negative_prompt_edit.setPlainText(original_negative_prompt)

            print(f"[TempWindowManager] 메인 UI 프롬프트 복원 완료 (오염 방지)")

    def handle_window_closing(self, window_id: int):
        """
        임시 창이 닫힐 때 정리 작업 수행

        Args:
            window_id: 닫힌 창의 ID
        """
        print(f"[TempWindowManager] 임시 창 #{window_id} 닫힘 처리 중...")

        if window_id in self.temp_windows:
            temp_window = self.temp_windows[window_id]

            # 시그널 연결 해제
            try:
                temp_window.generate_requested.disconnect()
                temp_window.params_update_requested.disconnect()
                temp_window.random_prompt_requested.disconnect()
                temp_window.window_closing.disconnect()
            except (TypeError, RuntimeError):
                pass  # 이미 연결 해제된 경우 무시

            # 추적 딕셔너리에서 제거
            del self.temp_windows[window_id]

            print(f"[TempWindowManager] 임시 창 #{window_id} 정리 완료 (남은 창: {len(self.temp_windows)}개)")
        else:
            print(f"⚠️ [TempWindowManager] 임시 창 #{window_id}를 찾을 수 없습니다 (이미 정리됨?)")

    def close_all_windows(self):
        """
        모든 임시 창을 닫고 정리합니다.

        앱 종료 시 호출되어야 합니다.
        """
        print(f"[TempWindowManager] 모든 임시 창 닫기 중... (총 {len(self.temp_windows)}개)")

        # 모든 창 닫기
        for window_id, temp_window in list(self.temp_windows.items()):
            try:
                temp_window.close()
            except:
                pass  # 이미 닫힌 창 무시

        # 추적 딕셔너리 초기화
        self.temp_windows.clear()

        print("[TempWindowManager] 모든 임시 창 정리 완료")

    def get_window_count(self) -> int:
        """
        현재 열린 임시 창 개수를 반환합니다.

        Returns:
            int: 열린 임시 창 개수
        """
        return len(self.temp_windows)

    def get_window(self, window_id: int) -> Optional['TempGenerationWindow']:
        """
        특정 창을 가져옵니다.

        Args:
            window_id: 창 ID

        Returns:
            TempGenerationWindow 또는 None
        """
        return self.temp_windows.get(window_id)
