"""
NAIA Main Controller
메인 윈도우의 이벤트 핸들러와 비즈니스 로직을 담당하는 컨트롤러
"""

import os
import json
import pandas as pd
import requests
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QMenu
from PyQt6.QtCore import QThread, QTimer, Qt
from PyQt6.QtGui import QTextCursor, QAction, QShortcut, QKeySequence
from PIL import Image
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size
from core.search_result_model import SearchResultModel
from utils.load_generation_params import GenerationParamsManager


class MainController:
    """메인 윈도우의 비즈니스 로직과 이벤트 핸들링을 담당하는 컨트롤러"""
    
    def __init__(self, main_window):
        """
        Args:
            main_window: ModernMainWindow 인스턴스
        """
        self.main_window = main_window
    
    # === 신호 연결 메서드 ===
    
    def connect_signals(self):
        """신호들을 연결"""
        mw = self.main_window  # 축약형
        
        mw.search_btn.clicked.connect(mw.trigger_search)
        mw.save_settings_btn.clicked.connect(self.save_all_current_settings)
        # restore_btn은 이제 메뉴를 가지고 있으므로 개별 액션들이 connect됨
        mw.deep_search_btn.clicked.connect(mw.open_depth_search_tab)
        mw.random_prompt_btn.clicked.connect(mw.trigger_random_prompt)
        mw.image_window.instant_generation_requested.connect(self.on_instant_generation_requested)
        # 🆕 큐 지원을 위해 wrapper 함수로 연결
        mw.generate_button_main.clicked.connect(lambda: self.trigger_generation(priority=0))

        # 🆕 생성 버튼에 우클릭 컨텍스트 메뉴 설정
        self._setup_generation_button_context_menu()

        # 🆕 키보드 단축키 설정
        self._setup_keyboard_shortcuts()

        mw.prompt_gen_controller.prompt_generated.connect(self.on_prompt_generated)
        mw.prompt_gen_controller.generation_error.connect(self.on_generation_error)
        mw.prompt_gen_controller.prompt_popped.connect(self.on_prompt_popped)
        mw.prompt_gen_controller.resolution_detected.connect(self.on_resolution_detected)
        mw.image_window.load_prompt_to_main_ui.connect(mw.set_positive_prompt)
        mw.image_window.instant_generation_requested.connect(self.on_instant_generation_requested)
        
        # 검색 컨트롤러 시그널 연결
        mw.search_controller.search_progress.connect(self.update_search_progress)
        mw.search_controller.partial_search_result.connect(self.on_partial_search_result)
        mw.search_controller.search_complete.connect(self.on_search_complete)
        mw.search_controller.search_error.connect(self.on_search_error)
        
        self.connect_checkbox_signals()
        mw.workflow_load_btn.clicked.connect(self._load_custom_workflow_from_image)
        mw.workflow_default_btn.clicked.connect(self._on_workflow_type_changed)
        mw.image_window.instant_generation_requested.connect(self.on_instant_generation_requested)
        if hasattr(mw.image_window, 'generate_with_image_requested'):
            mw.image_window.generate_with_image_requested.connect(self.on_generate_with_image_requested)
            print("✅ generate_with_image_requested 시그널이 연결되었습니다.")
        else:
            print("⚠️ generate_with_image_requested 시그널을 찾을 수 없습니다.")
        if hasattr(mw.image_window, 'send_to_inpaint_requested'):
            mw.image_window.send_to_inpaint_requested.connect(self.on_send_to_inpaint_requested)
        if hasattr(mw.image_window, 'send_to_img2img_requested'):
            mw.image_window.send_to_img2img_requested.connect(self.on_send_to_img2img_requested)
        if hasattr(mw.image_window, 'instant_outpaint_requested'):
            mw.image_window.instant_outpaint_requested.connect(self.on_instant_outpaint_requested)
        if hasattr(mw.image_window, 'send_to_outpaint_requested'):
            mw.image_window.send_to_outpaint_requested.connect(self.on_send_to_outpaint_requested)
        if hasattr(mw.image_window, 'use_as_outpaint_base_requested'):
            mw.image_window.use_as_outpaint_base_requested.connect(self.on_use_as_outpaint_base_requested)

        # 🆕 리모트 이벤트 저장 시그널 연결
        if hasattr(mw.image_window, 'save_to_remote_event_requested'):
            mw.image_window.save_to_remote_event_requested.connect(self.on_save_to_remote_event_requested)
            print("✅ save_to_remote_event_requested 시그널이 연결되었습니다.")

        # 🆕 큐 이벤트 구독
        self.connect_queue_signals()

    def connect_queue_signals(self):
        """큐 이벤트 구독"""
        if hasattr(self.main_window, 'app_context') and self.main_window.app_context:
            # 큐 재개 이벤트 구독
            self.main_window.app_context.subscribe("queue_queue_resumed", self.on_queue_resumed)
            # 큐 일시정지 이벤트 구독
            self.main_window.app_context.subscribe("queue_queue_paused", self.on_queue_paused)
            print("✅ [QUEUE] 큐 이벤트 구독 완료")

    def connect_automation_signals(self):
        """자동화 모듈과의 시그널 연결"""
        # 자동화 모듈 찾기
        if self.main_window.middle_section_controller:
            for module in self.main_window.middle_section_controller.module_instances:
                if hasattr(module, 'automation_controller'):
                    self.main_window.automation_module = module
                    break
        
        # NAIA_cold_v4.py에서 이미 콜백을 연결하므로 여기서는 모듈 참조만 설정
        if hasattr(self.main_window, 'automation_module') and self.main_window.automation_module:
            print("✅ 자동화 모듈 참조 설정 완료")
        else:
            if os.environ.get("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW") == "1":
                print("ℹ️ Web Session: 자동화 모듈 참조는 필요 시 지연 로드됩니다.")
                return
            print("⚠️ 자동화 모듈을 찾을 수 없습니다.")
    
    def connect_e621_event_signals(self):
        """E621 이벤트 모듈과의 시그널 연결"""
        # E621EventModuleV2 찾기
        if self.main_window.middle_section_controller:
            for module in self.main_window.middle_section_controller.module_instances:
                if module.__class__.__name__ == 'E621EventModuleV2':
                    # generation_requested 시그널 연결
                    if hasattr(module, 'signals') and hasattr(module.signals, 'generation_requested'):
                        module.signals.generation_requested.connect(self.on_generate_with_image_requested)
                        print("✅ E621EventModuleV2 generation_requested 시그널 연결 완료")
                    break
        
    def connect_checkbox_signals(self):
        """체크박스 시그널을 연결하는 메서드 (init에서 호출)"""
        try:
            prompt_fixed_checkbox = self.main_window.generation_checkboxes.get("프롬프트 고정")
            if prompt_fixed_checkbox:
                prompt_fixed_checkbox.toggled.connect(self.update_random_prompt_button_state)
                
            # 초기 상태 설정
            self.update_random_prompt_button_state()
            
        except Exception as e:
            print(f"❌ 체크박스 시그널 연결 오류: {e}")

    # === 🆕 Generation Queue Methods ===

    def trigger_generation(self, priority: int = 0):
        """
        생성 요청을 트리거합니다 (큐 지원 포함)

        Args:
            priority: 우선순위 (0=일반, 100=긁급)
        """
        # auto_generation_requested 플래그 리셋 (수동 생성)
        self.main_window.prompt_gen_controller.auto_generation_requested = False

        # GenerationController의 execute_generation_pipeline 호출
        self.main_window.generation_controller.execute_generation_pipeline(priority=priority)

    def on_queue_resumed(self, data: dict):
        """
        큐 재개 이벤트 핸들러

        재개 시 생성 중이 아니고 큐가 비어있지 않으면 자동으로 다음 요청 처리
        """
        queue_size = data.get('queue_size', 0)
        print(f"[QUEUE] 큐 재개됨: {queue_size}개 대기 중")

        # 버튼 텍스트 업데이트
        self.main_window.generation_controller._update_button_with_queue_size()

        # ⚡ 간단한 플래그 체크 후 즉시 처리
        if queue_size > 0 and not self.main_window.generation_controller.is_generating:
            print(f"[QUEUE] 자동 재시작: 다음 요청 처리 중...")
            # 최소한의 지연 (50ms면 충분)
            QTimer.singleShot(50, self.main_window.generation_controller._process_next_queue_request)
        elif queue_size > 0:
            print(f"[QUEUE] 생성 중이므로 대기... (완료 후 자동 처리됨)")

    def on_queue_paused(self, data: dict):
        """
        큐 일시정지 이벤트 핸들러

        일시정지 시 버튼 텍스트 업데이트
        """
        queue_size = data.get('queue_size', 0)
        print(f"[QUEUE] 큐 일시정지됨: {queue_size}개 대기 중")

        # 버튼 텍스트 업데이트
        self.main_window.generation_controller._update_button_with_queue_size()

    def _setup_generation_button_context_menu(self):
        """생성 버튼에 우클릭 컨텍스트 메뉴를 설정합니다."""
        mw = self.main_window

        # 생성 버튼에 컨텍스트 메뉴 정책 설정
        mw.generate_button_main.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        mw.generate_button_main.customContextMenuRequested.connect(self._show_queue_context_menu)

        print("[QUEUE] 생성 버튼 컨텍스트 메뉴 설정 완료")

    def _show_queue_context_menu(self, position):
        """생성 버튼 우클릭 시 큐 제어 메뉴 표시"""
        mw = self.main_window
        queue_manager = mw.app_context.generation_queue_manager

        menu = QMenu(mw)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 5px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QMenu::item {{
                padding: 8px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QMenu::item:disabled {{
                color: {DARK_COLORS['text_disabled']};
            }}
        """)

        # 큐 상태 표시 (비활성화, 정보 표시용)
        queue_size = queue_manager.get_queue_size()
        status_action = QAction(f"📊 대기 중: {queue_size}개", mw)
        status_action.setEnabled(False)
        menu.addAction(status_action)

        menu.addSeparator()

        # 일시정지/재개 액션
        if queue_manager.is_paused():
            pause_action = QAction("▶️ 큐 재개", mw)
            pause_action.triggered.connect(queue_manager.resume_queue)
        else:
            pause_action = QAction("⏸️ 큐 일시정지", mw)
            pause_action.triggered.connect(queue_manager.pause_queue)
        menu.addAction(pause_action)

        # 큐 비우기 액션
        clear_action = QAction("🗑️ 큐 비우기", mw)
        clear_action.triggered.connect(self._clear_queue_with_confirmation)
        clear_action.setEnabled(queue_size > 0)  # 큐가 비어있으면 비활성화
        menu.addAction(clear_action)

        # 메뉴 표시
        global_pos = mw.generate_button_main.mapToGlobal(position)
        menu.exec(global_pos)

    def _clear_queue_with_confirmation(self):
        """큐 비우기 (확인 대화상자 포함)"""
        queue_manager = self.main_window.app_context.generation_queue_manager
        queue_size = queue_manager.get_queue_size()

        if queue_size == 0:
            return

        # 확인 대화상자
        reply = QMessageBox.question(
            self.main_window,
            '큐 비우기 확인',
            f'대기 중인 {queue_size}개의 요청을 모두 제거하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            queue_manager.clear_queue()
            self.main_window.status_bar.showMessage(f"🗑️ {queue_size}개의 대기 요청이 제거되었습니다.")
            print(f"[QUEUE] 사용자가 {queue_size}개의 요청을 제거했습니다.")

    def _setup_keyboard_shortcuts(self):
        """키보드 단축키를 설정합니다."""
        mw = self.main_window

        # Ctrl+Enter: 일반 생성 (우선순위 0)
        ctrl_enter = QShortcut(QKeySequence(Qt.Modifier.CTRL.value | Qt.Key.Key_Return.value), mw)
        ctrl_enter.activated.connect(lambda: self.trigger_generation(priority=0))

        # Shift+Enter: 긴급 생성 (우선순위 100)
        shift_enter = QShortcut(QKeySequence(Qt.Modifier.SHIFT.value | Qt.Key.Key_Return.value), mw)
        shift_enter.activated.connect(lambda: self.trigger_generation(priority=100))

        print("[QUEUE] 키보드 단축키 설정 완료:")
        print("  - Ctrl+Enter: 일반 생성")
        print("  - Shift+Enter: 긴급 생성")

    # === Helper Methods ===
    
    def get_auto_generate_status(self) -> bool:
        """현재 자동 생성 체크박스 상태를 반환"""
        try:
            auto_generate_checkbox = self.main_window.generation_checkboxes.get("자동 생성")
            if auto_generate_checkbox:
                return auto_generate_checkbox.isChecked()
            return False
        except Exception as e:
            print(f"⚠️ 자동 생성 상태 확인 실패: {e}")
            return False

    def update_random_prompt_button_state(self):
        """generation_checkboxes 상태에 따라 random_prompt_btn을 활성화/비활성화"""
        try:
            # "프롬프트 고정" 체크박스가 체크되어 있으면 버튼 비활성화
            prompt_fixed_checkbox = self.main_window.generation_checkboxes.get("프롬프트 고정")
            
            if prompt_fixed_checkbox and prompt_fixed_checkbox.isChecked():
                self.main_window.random_prompt_btn.setEnabled(False)
                self.main_window.random_prompt_btn.setText("프롬프트 고정됨")
            else:
                self.main_window.random_prompt_btn.setEnabled(True)
                self.main_window.random_prompt_btn.setText("랜덤/다음 프롬프트")
                
        except Exception as e:
            print(f"❌ 버튼 상태 업데이트 오류: {e}")
    
    # === 검색 관련 이벤트 핸들러 ===
    
    def update_search_progress(self, completed: int, total: int):
        """검색 진행률에 따라 UI 업데이트"""
        percentage = int((completed / total) * 100) if total > 0 else 0
        self.main_window.progress_label.setText(f"{completed}/{total}")
        self.main_window.search_btn.setText(f"검색 중 ({percentage}%)")
        
    def on_partial_search_result(self, partial_df: pd.DataFrame):
        """부분 검색 결과를 받아 UI에 즉시 반영"""
        self.main_window.search_results.append_dataframe(partial_df)
        self.main_window.result_label1.setText(f"검색: {self.main_window.search_results.get_count()}")
        self.main_window.result_label2.setText(f"남음: {self.main_window.search_results.get_count()}")
        
    def on_search_complete(self, total_count: int):
        """검색 완료 시 호출되는 슬롯, 결과 파일 저장"""
        self.main_window.search_btn.setEnabled(True)
        self.main_window.search_btn.setText("검색")
        self.main_window.progress_label.setVisible(False)
        self.main_window.search_mode_2411.setVisible(True)
        self.main_window.search_mode_2509.setVisible(True)
        self.main_window.search_mode_1109.setVisible(True)
        self.main_window.status_bar.showMessage(f"✅ 검색 완료! {total_count}개의 결과를 찾았습니다.", 5000)

        # [신규] 검색 결과 Parquet 파일로 저장
        if not self.main_window.search_results.is_empty():
            try:
                self.main_window.search_results.get_dataframe().to_parquet('naia_temp_rows.parquet')
            except Exception as e:
                self.main_window.status_bar.showMessage(f"⚠️ 결과 파일 저장 실패: {e}", 5000)
        
    def on_search_error(self, error_message: str):
        """검색 오류 발생 시 호출되는 슬롯"""
        self.main_window.search_btn.setEnabled(True)
        self.main_window.search_btn.setText("검색")
        self.main_window.progress_label.setVisible(False)
        self.main_window.search_mode_2411.setVisible(True)
        self.main_window.search_mode_2509.setVisible(True)
        self.main_window.search_mode_1109.setVisible(True)
        self.main_window.status_bar.showMessage(f"❌ 검색 오류: {error_message}", 5000)
        
    # === 생성 관련 이벤트 핸들러 ===
    
    def on_prompt_generated(self, prompt_text: str):
        """프롬프트 생성 완료 처리"""
        # MainWindow의 실제 구현 호출
        self.main_window.on_prompt_generated(prompt_text)
        
    def on_generation_error(self, error_message: str):
        """생성 오류 처리"""
        # MainWindow의 실제 구현 호출
        self.main_window.on_generation_error(error_message)
        
    def on_instant_generation_requested(self, tags_dict):
        """즉시 생성 요청 처리"""
        # MainWindow의 실제 구현 호출 (있는 경우)
        if hasattr(self.main_window, 'on_instant_generation_requested'):
            self.main_window.on_instant_generation_requested(tags_dict)
    
    # === 설정 관리 메서드 ===
    
    def load_generation_parameters(self):
        """생성 파라미터 로드"""
        # 기존 방식 대신 모드별 로드
        current_mode = self.main_window.app_context.get_api_mode()
        self.main_window.generation_params_manager.load_mode_settings(current_mode)
        
    def save_generation_parameters(self):
        """생성 파라미터 저장"""
        # 기존 방식 대신 모드별 저장
        current_mode = self.main_window.app_context.get_api_mode()
        self.main_window.generation_params_manager.save_mode_settings(current_mode)
        
    def save_all_current_settings(self):
        """모든 현재 설정 저장"""
        try:
            current_mode = self.main_window.app_context.get_api_mode()
            
            # 버튼 상태 변경 (저장 중 표시)
            self.main_window.save_settings_btn.setText("💾 저장 중...")
            self.main_window.save_settings_btn.setEnabled(False)
            
            saved_items = []
            failed_items = []
            
            # 1. 메인 생성 파라미터 저장
            try:
                self.main_window.generation_params_manager.save_mode_settings(current_mode)
                saved_items.append("메인 생성 파라미터")
            except Exception as e:
                failed_items.append(f"메인 생성 파라미터: {str(e)}")
            
            # 2. 모든 ModeAware 모듈 설정 저장
            if self.main_window.app_context and self.main_window.app_context.mode_manager:
                try:
                    self.main_window.app_context.mode_manager.save_all_current_mode()
                    
                    # 저장된 모듈 수 계산
                    mode_aware_count = len(self.main_window.app_context.mode_manager.registered_modules)
                    if mode_aware_count > 0:
                        saved_items.append(f"모드 인식 모듈 ({mode_aware_count}개)")
                    
                except Exception as e:
                    failed_items.append(f"모드 인식 모듈: {str(e)}")
               
            # 결과 메시지 생성
            if saved_items and not failed_items:
                # 모든 저장 성공
                message = f"✅ 설정 저장 완료 ({current_mode} 모드)\n저장된 항목: {', '.join(saved_items)}"
                self.main_window.status_bar.showMessage(f"✅ 모든 설정이 저장되었습니다 ({current_mode} 모드)", 4000)
                
            elif saved_items and failed_items:
                # 일부 저장 성공, 일부 실패
                message = f"⚠️ 설정 부분 저장 완료 ({current_mode} 모드)\n✅ 저장됨: {', '.join(saved_items)}\n❌ 실패: {', '.join(failed_items)}"
                self.main_window.status_bar.showMessage(f"⚠️ 일부 설정 저장 실패", 4000)
                
            else:
                # 모든 저장 실패
                message = f"❌ 설정 저장 실패 ({current_mode} 모드)\n실패 항목: {', '.join(failed_items)}"
                self.main_window.status_bar.showMessage("❌ 설정 저장 실패", 4000)
            
            print(message)
            
            # 성공한 항목이 있으면 토스트 메시지도 표시
            if saved_items:
                # QMessageBox로 간단한 알림 표시 (자동으로 사라지지 않음, 사용자가 확인 필요)
                # TODO(web-dialog): 원래 QMessageBox(Information) "설정 저장 완료" — 3초 자동 닫기 타이머 포함.
                # Web Shell 토스트(short, auto-dismiss 3s)로 재구현 권장.
                # blocking dialog 가 메인 스레드를 잡으면 web shell 페인트도 정지하므로 콘솔 출력으로 대체.
                details = f"저장된 항목:\n• " + "\n• ".join(saved_items)
                if failed_items:
                    details += f"\n\n실패한 항목:\n• " + "\n• ".join(failed_items)
                print(f"[Dialog/INFO] 설정 저장 완료: 현재 모드({current_mode})의 설정이 저장되었습니다.\n{details}")
            
        except Exception as e:
            error_message = f"❌ 설정 저장 중 예외 발생: {str(e)}"
            print(error_message)
            self.main_window.status_bar.showMessage("❌ 설정 저장 중 오류 발생", 4000)
            
        finally:
            # 버튼 상태 복원
            self.main_window.save_settings_btn.setText("💾 설정 저장")
            self.main_window.save_settings_btn.setEnabled(True)
    
    # === API 테스트 메서드 ===
    
    def test_webui(self, url):
        """WebUI 연결 테스트 함수"""
        import requests
        # ignore http or https, check both.
        url = url.replace('http://', '').replace('https://', '').rstrip('/')
        # just checking connection, so any api is okay.
        try:
            if "127.0" not in url: res = requests.get(f"https://{url}/sdapi/v1/progress?skip_current_image=true", timeout=1)
            else: res = requests.get(f"http://{url}/sdapi/v1/progress?skip_current_image=true", timeout=1)
            if res.status_code == 200 and 'progress' in res.json():
                return f'https://{url}'
            else:
                raise Exception('invalid status')
        except Exception:
            try:
                res = requests.get(f"http://{url}/sdapi/v1/progress?skip_current_image=true", timeout=1)
                if res.status_code == 200 and 'progress' in res.json():
                    return f'http://{url}'
                else:
                    raise Exception('invalid status')
            except Exception:
                pass
        return None
        
    def test_comfyui(self, url):
        """ComfyUI 연결 테스트 함수 (test_webui와 유사한 패턴)"""
        import requests
        import json
        
        # URL 테스트 전략: 사용자 입력 → 기본 포트들 (8000, 8188)
        test_urls = []
        original_url = url.strip().rstrip('/')

        # 1. 사용자가 입력한 URL을 그대로 먼저 시도
        if original_url.startswith('http://') or original_url.startswith('https://'):
            test_urls.append(original_url)
        else:
            # 프로토콜이 없으면 http와 https 모두 시도
            test_urls.append(f"http://{original_url}")
            test_urls.append(f"https://{original_url}")

        # 2. 포트가 없는 경우, 기본 포트들을 추가해서 재시도
        clean_url = original_url.replace('https://', '').replace('http://', '')
        has_port = ':' in clean_url.split('/')[0]  # 경로 제외하고 호스트:포트 부분만 체크

        if not has_port:
            # 원격 터널 서비스 감지 (포트 불필요)
            remote_tunnel_services = [
                'trycloudflare.com',  # Cloudflare Tunnel
                'ngrok',              # ngrok (ngrok.io, ngrok-free.app 등)
                'gradio.live',        # Gradio Share
                'serveo.net',         # Serveo
                'localhost.run',      # localhost.run
                'tunnelto.dev',       # Tunnelto
                'localtunnel.me',     # Localtunnel
            ]

            is_remote_tunnel = any(service in clean_url for service in remote_tunnel_services)

            if not is_remote_tunnel:
                # 로컬 서버: 기본 포트들 시도 (8000, 8188)
                for port in [8000, 8188]:
                    test_urls.append(f"http://{clean_url}:{port}")
                    test_urls.append(f"https://{clean_url}:{port}")
        
        for test_url in test_urls:
            try:
                print(f"🔍 ComfyUI 연결 테스트: {test_url}")
                
                # /system_stats 엔드포인트로 연결 테스트
                response = requests.get(f"{test_url}/system_stats", timeout=8)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        # ComfyUI 응답 구조 확인
                        if 'system' in data or 'devices' in data:
                            print(f"✅ ComfyUI 연결 성공: {test_url}")
                            return test_url
                    except json.JSONDecodeError:
                        continue
                
            except requests.exceptions.ConnectTimeout:
                print(f"⏰ ComfyUI 연결 시간 초과: {test_url}")
                continue
            except requests.exceptions.ConnectionError:
                print(f"❌ ComfyUI 연결 실패: {test_url}")
                continue
            except Exception as e:
                print(f"❌ ComfyUI 테스트 중 예외: {test_url} - {e}")
                continue
        
        print(f"❌ 모든 ComfyUI 연결 시도 실패: {url}")
        return None
    
    # === 기타 이벤트 핸들러 메서드 ===
    
    def on_prompt_popped(self, remaining_count: int):
        """프롬프트 팝 이벤트 처리"""
        # 메인 윈도우에 위임
        if hasattr(self.main_window, 'on_prompt_popped'):
            self.main_window.on_prompt_popped(remaining_count)
        
    def on_resolution_detected(self, width: int, height: int):
        """해상도 감지 이벤트 처리"""
        # 메인 윈도우에 위임
        if hasattr(self.main_window, 'on_resolution_detected'):
            self.main_window.on_resolution_detected(width, height)
            
    def on_generate_with_image_requested(self, tags_dict):
        """이미지와 함께 생성 요청 처리"""
        # 메인 윈도우에 위임
        if hasattr(self.main_window, 'on_generate_with_image_requested'):
            self.main_window.on_generate_with_image_requested(tags_dict)
            
    def on_send_to_inpaint_requested(self, history_item):
        """인페인트 전송 요청 처리"""
        if hasattr(self.main_window, 'on_send_to_inpaint_requested'):
            self.main_window.on_send_to_inpaint_requested(history_item)

    def on_send_to_img2img_requested(self, history_item):
        """img2img 전송 요청 처리"""
        if hasattr(self.main_window, 'on_send_to_img2img_requested'):
            self.main_window.on_send_to_img2img_requested(history_item)

    def on_instant_outpaint_requested(self, history_item):
        """즉시 아웃페인팅 요청 처리"""
        if hasattr(self.main_window, 'on_instant_outpaint_requested'):
            self.main_window.on_instant_outpaint_requested(history_item)

    def on_send_to_outpaint_requested(self, history_item):
        """아웃페인팅 전송 요청 처리"""
        if hasattr(self.main_window, 'on_send_to_outpaint_requested'):
            self.main_window.on_send_to_outpaint_requested(history_item)

    def on_use_as_outpaint_base_requested(self, history_item):
        """코믹 패널 아웃페인팅 베이스 요청 처리"""
        if hasattr(self.main_window, 'on_use_as_outpaint_base_requested'):
            self.main_window.on_use_as_outpaint_base_requested(history_item)

    def on_save_to_remote_event_requested(self, history_item):
        """🆕 리모트 이벤트 저장 요청 처리"""
        # 메인 윈도우에 위임
        if hasattr(self.main_window, 'on_save_to_remote_event_requested'):
            self.main_window.on_save_to_remote_event_requested(history_item)

    def _load_custom_workflow_from_image(self):
        """이미지에서 커스텀 워크플로우 로드"""
        # 메인 윈도우에 위임
        if hasattr(self.main_window, '_load_custom_workflow_from_image'):
            self.main_window._load_custom_workflow_from_image()
            
    def _on_workflow_type_changed(self):
        """워크플로우 타입 변경 처리"""
        # 메인 윈도우에 위임
        if hasattr(self.main_window, '_on_workflow_type_changed'):
            self.main_window._on_workflow_type_changed()
