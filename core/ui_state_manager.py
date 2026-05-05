# core/ui_state_manager.py
# 프로그램 종료 시 UI 레이아웃 상태를 저장하고, 시작 시 복원하는 매니저

import base64
import json
import os
from pathlib import Path
from PyQt6.QtCore import QByteArray, QTimer


class UIStateManager:
    """UI 레이아웃 상태 저장/복원 매니저.

    저장 항목:
    - window_geometry: 창 위치/크기
    - main_splitter: 좌/우 패널 비율
    - prompt_section_height: 프롬프트 FixedBox 높이
    - params_expanded: 생성 파라미터 패널 펼침 여부
    - left_scroll_position: 좌측 스크롤 위치
    """

    STATE_FILE = Path("save/ui_state.json")

    def __init__(self):
        self._state = {}

    def save_state(self, main_window) -> None:
        """MainWindow에서 현재 UI 상태를 수집하여 파일로 저장"""
        state = {}

        # 0. 창 위치/크기
        raw_geo = main_window.saveGeometry()
        state['window_geometry'] = base64.b64encode(bytes(raw_geo)).decode('ascii')
        state['window_maximized'] = (
            main_window.isMaximized()
            or bool(getattr(main_window, '_pending_ui_state_show_maximized', False))
        )

        # 1. 스플리터 위치
        if hasattr(main_window, 'main_splitter'):
            splitter = main_window.main_splitter
            raw = splitter.saveState()
            state['splitter_state'] = base64.b64encode(bytes(raw)).decode('ascii')
            state['splitter_sizes'] = splitter.sizes()

        # 2. 프롬프트 섹션 높이
        if hasattr(main_window, 'prompt_fixed_box'):
            state['prompt_section_height'] = main_window.prompt_fixed_box.get_height()

        # 3. 생성 파라미터 패널 펼침 여부
        if hasattr(main_window, 'params_expanded'):
            state['params_expanded'] = main_window.params_expanded

        # 4. 좌측 패널 스크롤 위치
        if hasattr(main_window, 'left_panel_scroll_area'):
            scrollbar = main_window.left_panel_scroll_area.verticalScrollBar()
            state['left_scroll_position'] = scrollbar.value()

        # 5. 모듈 상태 저장 (MiddleSectionController에 위임)
        if hasattr(main_window, 'middle_section_controller') and main_window.middle_section_controller:
            main_window.middle_section_controller.save_module_states()

        # 파일 저장
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            print(f"💾 [UI STATE] UI 레이아웃 상태 저장 완료")
        except Exception as e:
            print(f"❌ [UI STATE] UI 상태 저장 실패: {e}")

    def load_state(self) -> dict:
        """저장된 UI 상태를 파일에서 로드"""
        if not self.STATE_FILE.exists():
            print(f"ℹ️ [UI STATE] 저장된 UI 상태 파일 없음")
            return {}

        try:
            with open(self.STATE_FILE, 'r', encoding='utf-8') as f:
                self._state = json.load(f)
            print(f"✅ [UI STATE] UI 상태 로드 완료")
            return self._state
        except Exception as e:
            print(f"❌ [UI STATE] UI 상태 로드 실패: {e}")
            return {}

    def restore_state(self, main_window) -> None:
        """로드된 상태를 MainWindow에 적용"""
        state = self.load_state()
        if not state:
            return

        # 0. 창 위치/크기 복원
        if 'window_geometry' in state:
            try:
                raw = base64.b64decode(state['window_geometry'])
                main_window.restoreGeometry(QByteArray(raw))
                # 최대화 상태였다면 최대화 복원
                if state.get('window_maximized', False):
                    if self._should_defer_window_show(main_window):
                        setattr(main_window, '_pending_ui_state_show_maximized', True)
                    else:
                        main_window.showMaximized()
            except Exception as e:
                print(f"⚠️ [UI STATE] 창 크기 복원 시 오류: {e}")

        # 1. 스플리터 위치 복원
        if 'splitter_state' in state and hasattr(main_window, 'main_splitter'):
            try:
                raw = base64.b64decode(state['splitter_state'])
                main_window.main_splitter.restoreState(QByteArray(raw))
            except Exception as e:
                # fallback: sizes로 복원
                if 'splitter_sizes' in state:
                    try:
                        main_window.main_splitter.setSizes(state['splitter_sizes'])
                    except Exception:
                        pass
                print(f"⚠️ [UI STATE] 스플리터 상태 복원 시 오류: {e}")

        # 2. 프롬프트 섹션 높이 복원
        if 'prompt_section_height' in state and hasattr(main_window, 'prompt_fixed_box'):
            height = state['prompt_section_height']
            if isinstance(height, (int, float)) and height > 0:
                main_window.prompt_fixed_box.set_height(int(height))

        # 3. 생성 파라미터 패널 상태 복원
        if 'params_expanded' in state and hasattr(main_window, 'params_area'):
            if state['params_expanded']:
                main_window.params_area.setVisible(True)
                main_window.params_toggle_button.setText("▼ 생성 파라미터 닫기")
                main_window.params_expanded = True
            # False인 경우 기본값이므로 별도 처리 불필요

        # 4. 좌측 패널 스크롤 위치 복원 (약간 지연 필요)
        if 'left_scroll_position' in state and hasattr(main_window, 'left_panel_scroll_area'):
            scroll_pos = state['left_scroll_position']
            QTimer.singleShot(200, lambda: self._restore_scroll(main_window, scroll_pos))

        # 5. 모듈 상태 복원 (MiddleSectionController에 위임)
        if hasattr(main_window, 'middle_section_controller') and main_window.middle_section_controller:
            main_window.middle_section_controller.load_module_states()

    def _restore_scroll(self, main_window, position: int):
        """스크롤 위치 복원 (QTimer 콜백)"""
        try:
            scrollbar = main_window.left_panel_scroll_area.verticalScrollBar()
            scrollbar.setValue(position)
        except Exception:
            pass

    def _should_defer_window_show(self, main_window) -> bool:
        """Return True when startup must stay hidden until Web Shell requests show."""
        if os.environ.get('NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW') != '1':
            return False
        if os.environ.get('NAIA_CLI_DESKTOP') == '1':
            return False
        return not (main_window.isVisible() and not main_window.isHidden())
