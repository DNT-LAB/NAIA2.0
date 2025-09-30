from core.context import AppContext
from PIL import Image
import piexif
import piexif.helper
import json
import re, random
from PyQt6.QtCore import QThread, QObject, pyqtSignal, QTimer, QCoreApplication, QThreadPool
import pandas as pd
import gc
import requests

def _force_cleanup_all_threads():
    """모든 종류의 스레드 풀과 연결을 강제로 정리하는 함수"""
    try:
        # 1. 전역 urllib3 연결 풀 정리
        try:
            from urllib3.util import connection
            from urllib3 import poolmanager
            # 전역 연결 풀 매니저 정리
            if hasattr(poolmanager, '_default_pool'):
                poolmanager._default_pool = None
        except Exception:
            pass

        # 2. requests 세션 정리
        try:
            # requests 모듈의 기본 세션 정리
            if hasattr(requests, 'sessions'):
                if hasattr(requests.sessions, 'Session'):
                    # 기본 어댑터 정리
                    session = requests.Session()
                    session.close()
        except Exception:
            pass

        # 3. Qt 스레드 풀 정리
        try:
            thread_pool = QThreadPool.globalInstance()
            thread_pool.clear()
            thread_pool.waitForDone(1000)  # 1초 대기
        except Exception:
            pass

        # 4. 가비지 컬렉션 강제 실행
        gc.collect()
        
        # 5. Qt 이벤트 루프 강제 처리 (여러 번)
        for i in range(3):
            QCoreApplication.processEvents()
            QTimer.singleShot(10, lambda: QCoreApplication.processEvents())
            
    except Exception:
        pass

class GenerationWorker(QObject):
    """API 호출을 담당하는 워커 클래스"""
    generation_started = pyqtSignal()
    generation_progress = pyqtSignal(str)  # 진행 상황 메시지
    generation_finished = pyqtSignal(dict)  # 최종 결과
    generation_error = pyqtSignal(str)  # 오류 메시지
    
    def __init__(self, context: 'AppContext'):
        super().__init__()
        self.context = context
        self.params = None
        self.source_row = None
        
    def set_generation_params(self, params: dict, source_row):
        """생성 파라미터와 소스 행을 설정합니다."""
        self.params = params
        self.source_row = source_row
        
    def run_generation(self):
        """별도 스레드에서 실행될 생성 작업"""
        try:
            self.generation_started.emit()
            self.generation_progress.emit("API 호출 중...")
            
            # API 호출 (이 부분이 시간이 오래 걸림)
            api_result = self.context.api_service.call_generation_api(self.params)
            
            # 🔧 FIX: API 결과가 error 상태인 경우 에러로 처리
            if api_result.get('status') == 'error':
                error_msg = api_result.get('message', 'Unknown API error')
                print(f"❌ API 호출 실패: {error_msg}")
                self.generation_error.emit(error_msg)
                return
            
            self.generation_progress.emit("결과 처리 중...")
            
            # 후처리
            processed_result = self._post_process(api_result)
            
            if processed_result.get('status') == 'success':
                processed_result['source_row'] = self.source_row.copy()
                
                # 생성된 이미지에서 직접 생성 정보(info) 추출
                generated_image = processed_result.get('image')
                if generated_image:
                    info_text = self._extract_info_from_image(generated_image)
                    processed_result['info'] = info_text
                else:
                    processed_result['info'] = "이미지 객체를 찾을 수 없습니다."
                
                # 🆕 확장된 메타데이터 수집
                self._collect_enhanced_metadata(processed_result)
            
            self.generation_finished.emit(processed_result)
            
        except Exception as e:
            self.generation_error.emit(str(e))
    
    def _post_process(self, result: dict) -> dict:
        """결과 후처리 로직"""
        return result
    
    def _extract_info_from_image(self, image: Image.Image) -> str:
        """
        PIL Image 객체에서 생성 정보를 추출합니다.
        png_info_tab.py의 로직과 제공된 코드를 결합하여 NAI, A1111 등 다양한 포맷을 처리합니다.
        """
        if not image or not hasattr(image, 'info'):
            return "메타데이터를 포함하지 않는 이미지입니다."

        # 1. NovelAI 이미지 메타데이터 처리 (가장 먼저 확인)
        if image.info.get("Software", "") == "NovelAI":
            try:
                comment_data = json.loads(image.info.get("Comment", "{}"))
                # NAI 형식에 맞춰 문자열 재구성
                info_string = (
                    f"{image.info.get('Description', '')}\n"
                    f"Negative prompt: {comment_data.get('uc', '')}\n"
                    f"Steps: {comment_data.get('steps', 'N/A')}, Sampler: {comment_data.get('sampler', 'N/A')}, "
                    f"CFG scale: {comment_data.get('scale', 'N/A')}, Seed: {comment_data.get('seed', 'N/A')}"
                )
                return info_string
            except (json.JSONDecodeError, KeyError) as e:
                print(f"NovelAI 메타데이터 파싱 오류: {e}")
                # 실패 시 다른 방법으로 계속 진행

        # 2. A1111/ComfyUI 등 표준 'parameters' 메타데이터 처리
        if 'parameters' in image.info and isinstance(image.info['parameters'], str):
            return image.info['parameters']
            
        # 3. EXIF 데이터에서 UserComment 추출 시도
        if 'exif' in image.info:
            try:
                exif_data = image.info['exif']
                exif_dict = piexif.load(exif_data)
                user_comment_bytes = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment, b'')
                
                if user_comment_bytes:
                    return piexif.helper.UserComment.load(user_comment_bytes)
            except Exception as e:
                print(f"EXIF UserComment 추출 오류: {e}")

        # 4. 기타 'Comment' 또는 'comment' 필드 확인
        comment = image.info.get("Comment", image.info.get("comment"))
        if comment and isinstance(comment, str):
            return comment
        elif comment and isinstance(comment, bytes):
            return comment.decode('utf-8', errors='ignore')

        return "AI 생성 이미지가 아니거나, 인식할 수 있는 메타데이터가 없습니다."
    
    def _collect_enhanced_metadata(self, result: dict):
        """🆕 확장된 메타데이터를 수집하여 결과에 추가합니다."""
        import time
        try:
            # 생성 파라미터 보존 (민감한 정보 제외)
            params_copy = self.params.copy()
            if 'credential' in params_copy:
                del params_copy['credential']  # 보안을 위해 토큰 제거
            
            result['generation_params'] = params_copy
            
            # 🆕 main_prompt 수집 (UI에서 직접 가져와 \n\n 포함하여 보존)
            main_prompt_raw = ""
            try:
                if hasattr(self.context, 'main_window') and hasattr(self.context.main_window, 'main_prompt_textedit'):
                    main_prompt_raw = self.context.main_window.main_prompt_textedit.toPlainText()
            except Exception as e:
                print(f"⚠️ main_prompt 수집 실패: {e}")
            
            # 프롬프트 컨텍스트 정보
            result['prompt_context'] = {
                'original_input': self.params.get('input', ''),
                'processed_input': self.params.get('input', ''),  # 필요시 파이프라인 처리 후 값으로 교체
                'negative_prompt': self.params.get('negative_prompt', ''),
                'main_prompt': main_prompt_raw,  # 🆕 UI에서 가져온 원본 프롬프트 (\n\n 포함)
                'source_tags': self.source_row.to_dict() if self.source_row is not None else {},
                'wildcard_resolved': self.source_row is not None
            }
            
            # API 메타데이터
            result['api_metadata'] = {
                'backend': self.params.get('api_mode', 'NAI'),
                'model': self.params.get('model', ''),
                'sampler': self.params.get('sampler', ''),
                'response_time': result.get('response_time', 0),
                'api_version': result.get('api_version', ''),
                'generation_timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # 생성 시각과 백엔드 타입
            result['creation_timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
            result['backend_type'] = self.params.get('api_mode', 'NAI')
            
            print(f"✅ 확장된 메타데이터 수집 완료: {result['backend_type']}")
            
        except Exception as e:
            print(f"⚠️ 메타데이터 수집 중 오류: {e}")
            # 기본값으로 설정
            result.setdefault('generation_params', {})
            result.setdefault('prompt_context', {})
            result.setdefault('api_metadata', {})
            result.setdefault('creation_timestamp', time.strftime('%Y-%m-%d %H:%M:%S'))
            result.setdefault('backend_type', 'NAI')

class GenerationController:
    def __init__(self, context: 'AppContext', module_instances: list):
        self.context = context
        self.module_instances = module_instances
        self.workflow_manager = self.context.comfyui_workflow_manager # AppContext에서 참조

        # 스레드 관련 초기화
        self.generation_thread = None
        self.generation_worker = None
        self.is_generating = False
        
        # 🆕 자동 생성 재시도 관련 추가
        self.auto_retry_count = 0
        self.max_auto_retries = 2  # 자동 생성 시 최대 재시도 횟수 (API 자체에서 5회 재시도 하므로 줄임)
        self.retry_delay_ms = 3000  # 재시도 간격 (밀리초) - 3초로 증가
        
    def execute_generation_pipeline(self, overrides: dict = None):
        """7단계 생성 파이프라인을 실행합니다."""
        # 이미 생성 중인 경우 중복 실행 방지
        if self.is_generating:
            self.context.main_window.status_bar.showMessage("⚠️ 이미 생성 중입니다...")
            return
            
        try:
            # --- 1 ~ 4 단계: 파라미터 수집 및 유효성 검사 ---
            api_mode = self.context.main_window.get_current_api_mode()
            if api_mode == "NAI": 
                token = 'nai_token'
                char_module = self.context.middle_section_controller.get_module_instance("CharacterModule")
                if (char_module and 
                    char_module.activate_checkbox.isChecked() and 
                    char_module.reroll_on_generate_checkbox.isChecked()):
                    
                    print("🔄️ 생성 시 Reroll: 캐릭터 와일드카드를 갱신합니다.")
                    char_module.process_and_update_view()
            elif api_mode == "COMFYUI": token = 'comfyui_url'
            else: token = 'webui_url'
            credential = self.context.secure_token_manager.get_token(token)
            if not credential:
                self.context.main_window.status_bar.showMessage(f"❌ {api_mode} 인증 정보가 없습니다.")
                return

            params = self.context.main_window.get_main_parameters()
            params['api_mode'] = api_mode
            params['credential'] = credential

            source_row = self.context.current_source_row
            if source_row is None:
                empty_data = {
                    'general': None,
                    'character': None,
                    'copyright': None,
                    'artist': None,
                    'meta': None
                }
                source_row = pd.Series(empty_data, name="wildcard_standalone")
                self.context.main_window.status_bar.showMessage("빈 source_row를 생성했습니다.")

            for module in self.module_instances:
                module_params = module.get_parameters()
                if module_params: params.update(module_params)

            # 랜덤 해상도 처리
            if params.get('random_resolution', False) and not self.context.main_window.resolution_is_detected:
                random_index = random.randint(0, self.context.main_window.resolution_combo.count() - 1)
                self.context.main_window.resolution_combo.setCurrentIndex(random_index)
                selected_value = self.context.main_window.resolution_combo.currentText()
                width, height = map(int, selected_value.split('x'))
                params['width'] = width
                params['height'] = height
                print(f"랜덤 해상도 설정: {width}x{height}")

            # 자동 해상도 관리 해제
            self.context.main_window.resolution_is_detected = False

            img2img_params = self.context.main_window.img2img_panel.get_parameters()
            if img2img_params:
                print("🖼️ Img2Img 패널 활성화됨. 파라미터를 추가합니다.")
                params.update(img2img_params)

            if overrides:
                print(f"🔄 Workshop 파라미터로 덮어쓰기: {list(overrides.keys())}")
                params.update(overrides)

            is_valid, error_msg = self.validate_parameters(params)
            if not is_valid:
                self.context.main_window.status_bar.showMessage(f"⚠️ 유효성 검사 실패: {error_msg}")
                return
            
            if api_mode == "COMFYUI":
                final_workflow = self.workflow_manager.apply_params_to_workflow(params)
                if not final_workflow:
                    self.context.main_window.status_bar.showMessage("❌ 워크플로우 생성에 실패했습니다. 로그를 확인하세요.")
                    return
                params['workflow'] = final_workflow

            # --- 와일드카드 확장 처리 (API 호출 전) ---
            if 'input' in params and params['input']:
                # negative_prompt도 함께 전달
                negative_prompt = params.get('negative_prompt', '')
                expanded_input, processed_negative_prompt = self._expand_wildcards_in_input(
                    params['input'],
                    negative_prompt
                )
                params['input'] = expanded_input
                params['negative_prompt'] = processed_negative_prompt

                print(f"🎲 와일드카드 확장: '{params['input'][:50]}{'...' if len(params['input']) > 50 else ''}'")
                if processed_negative_prompt != negative_prompt:
                    print(f"➖ Negative prompt 업데이트: '{processed_negative_prompt[:50]}{'...' if len(processed_negative_prompt) > 50 else ''}'")

                # --- 조건부 프롬프트 처리 (와일드카드 확장 후) ---
                # processed_input = self._apply_conditional_prompts(params['input'])
                # if processed_input != params['input']:
                #     params['input'] = processed_input
                #     print(f"🔀 조건부 프롬프트 적용: '{params['input'][:50]}{'...' if len(params['input']) > 50 else ''}'")

                # 와일드카드 상태 모듈 업데이트를 위한 이벤트 발행
                if self.context.current_prompt_context:
                    self.context.publish("prompt_generated", self.context.current_prompt_context)
            
            # --- 5. 스레드에서 API 호출 시작 ---
            self._start_threaded_generation(params, source_row)

        except Exception as e:
            self.context.main_window.status_bar.showMessage(f"❌ 생성 준비 오류: {e}")
            print(f"오류 발생: {e}")
    
    def _start_threaded_generation(self, params: dict, source_row):
        """별도 스레드에서 생성 작업을 시작합니다."""
        # 새 스레드와 워커 생성
        self.generation_thread = QThread()
        self.generation_thread.setObjectName(f"GenThread-{id(self.generation_thread)}")
        self.generation_worker = GenerationWorker(self.context)
        
        # 워커를 스레드로 이동
        self.generation_worker.moveToThread(self.generation_thread)
        
        # 시그널 연결
        self.generation_worker.generation_started.connect(self._on_generation_started)
        self.generation_worker.generation_progress.connect(self._on_generation_progress)
        self.generation_worker.generation_finished.connect(self._on_generation_finished)
        self.generation_worker.generation_error.connect(self._on_generation_error)
        
        # 스레드 시작/종료 연결
        self.generation_thread.started.connect(self.generation_worker.run_generation)
        self.generation_worker.generation_finished.connect(self.generation_thread.quit)
        self.generation_worker.generation_error.connect(self.generation_thread.quit)
        
        # 🔧 올바른 deleteLater 연결 - 스레드 종료 시 해당 객체의 소유 스레드에서 안전하게 삭제
        self.generation_thread.finished.connect(self.generation_worker.deleteLater)
        self.generation_thread.finished.connect(self.generation_thread.deleteLater)
        
        self.generation_thread.finished.connect(self._on_thread_finished)
        
        # 파라미터 설정 및 스레드 시작
        self.generation_worker.set_generation_params(params, source_row)
        self.generation_thread.start()
    
    def _on_generation_started(self):
        """생성 시작 시 호출되는 슬롯"""
        self.is_generating = True
        self.context.main_window.generate_button_main.setEnabled(False)
        self.context.main_window.generate_button_main.setText("🔄 생성 중...")
        # 분리된 버튼도 비활성화
        if hasattr(self.context.main_window, 'detached_generate_btn'):
            self.context.main_window.detached_generate_btn.setEnabled(False)
            self.context.main_window.detached_generate_btn.setText("🔄 생성 중...")
        self.context.main_window.status_bar.showMessage("🚀 생성 시작...")
    
    def _on_generation_progress(self, message: str):
        """생성 진행 상황 업데이트 슬롯"""
        self.context.main_window.status_bar.showMessage(message)
    
    def _on_generation_finished(self, result: dict):
        """생성 완료 시 호출되는 슬롯"""
        # 생성 완료 시 즉시 is_generating을 False로 설정
        self.is_generating = False
        self.context.main_window.generate_button_main.setEnabled(True)
        self.context.main_window.generate_button_main.setText("🎨 이미지 생성 요청")
        # 분리된 버튼도 활성화
        if hasattr(self.context.main_window, 'detached_generate_btn'):
            self.context.main_window.detached_generate_btn.setEnabled(True)
            self.context.main_window.detached_generate_btn.setText("🎨 이미지 생성 요청")
        
        # 🆕 성공 시 재시도 카운터 리셋
        self.auto_retry_count = 0
        
        # UI 업데이트 (update_ui_with_result 내부에서 automation_module 처리)
        self.context.main_window.update_ui_with_result(result)

    def _on_generation_error(self, error_message: str):
        """생성 오류 시 호출되는 슬롯 - 🆕 자동 재시도 로직 추가"""
        # UI 상태 일시적으로 복원
        self.is_generating = False
        self.context.main_window.generate_button_main.setEnabled(True)
        self.context.main_window.generate_button_main.setText("🎨 이미지 생성 요청")
        # 분리된 버튼도 활성화
        if hasattr(self.context.main_window, 'detached_generate_btn'):
            self.context.main_window.detached_generate_btn.setEnabled(True)
            self.context.main_window.detached_generate_btn.setText("🎨 이미지 생성 요청")
        
        print(f"❌ 생성 오류 발생: {error_message}")
        
        # 🆕 자동 생성 모드에서의 재시도 로직
        auto_generate_checkbox = self.context.main_window.generation_checkboxes.get("자동 생성")
        is_auto_generation = auto_generate_checkbox and auto_generate_checkbox.isChecked()
        
        if is_auto_generation and self.auto_retry_count < self.max_auto_retries:
            # 자동 생성 모드에서 재시도 가능한 경우
            self.auto_retry_count += 1
            retry_message = f"🔄 자동 생성 재시도 {self.auto_retry_count}/{self.max_auto_retries} (오류: {error_message[:50]}...)"
            self.context.main_window.status_bar.showMessage(retry_message)
            print(f"🔄 자동 생성 재시도 시작: {self.auto_retry_count}/{self.max_auto_retries}")
            
            # 지연 후 재시도
            QTimer.singleShot(self.retry_delay_ms, self._retry_auto_generation)
            
        else:
            # 재시도 횟수 초과 또는 수동 생성 모드
            if is_auto_generation and self.auto_retry_count >= self.max_auto_retries:
                # 최대 재시도 횟수 초과 시 자동 생성 중단
                final_message = f"❌ 자동 생성 최대 재시도 횟수({self.max_auto_retries})를 초과했습니다. 자동 생성을 중단합니다."
                self.context.main_window.status_bar.showMessage(final_message)
                print(final_message)
                
                # 자동화 모듈이 있다면 중단
                if (hasattr(self.context.main_window, 'automation_module') and 
                    self.context.main_window.automation_module and 
                    self.context.main_window.automation_module.automation_controller.is_running):
                    self.context.main_window.automation_module.stop_automation()
                    
                # 재시도 카운터 리셋
                self.auto_retry_count = 0
                
            else:
                # 수동 생성 모드의 일반적인 오류 처리
                self.context.main_window.status_bar.showMessage(f"❌ 생성 오류: {error_message}")
    
    def _retry_auto_generation(self):
        """🆕 자동 생성 재시도를 실행하는 메서드"""
        try:
            print(f"🔄 자동 생성 재시도 실행 중... ({self.auto_retry_count}/{self.max_auto_retries})")
            
            # 자동 생성이 여전히 활성화되어 있는지 확인
            auto_generate_checkbox = self.context.main_window.generation_checkboxes.get("자동 생성")
            if not (auto_generate_checkbox and auto_generate_checkbox.isChecked()):
                print("⚠️ 자동 생성이 비활성화되어 재시도를 중단합니다.")
                self.auto_retry_count = 0
                return
            
            # 프롬프트 고정 여부 확인
            prompt_fixed_checkbox = self.context.main_window.generation_checkboxes.get("프롬프트 고정")
            is_prompt_fixed = prompt_fixed_checkbox and prompt_fixed_checkbox.isChecked()
            
            if is_prompt_fixed:
                # 프롬프트 고정 모드: 바로 이미지 생성 재시도
                self.context.main_window.status_bar.showMessage(f"🔄 재시도 {self.auto_retry_count}: 동일한 프롬프트로 생성 재시도 중...")
                self.execute_generation_pipeline()
            else:
                # 프롬프트 가변 모드: 새 프롬프트 생성 후 이미지 생성
                self.context.main_window.status_bar.showMessage(f"🔄 재시도 {self.auto_retry_count}: 새 프롬프트 생성 후 재시도 중...")
                
                # 새 프롬프트 생성 요청
                settings = {
                    'prompt_fixed': False,
                    'auto_generate': True,
                    'turbo_mode': self.context.main_window.generation_checkboxes["터보 옵션"].isChecked(),
                    'wildcard_standalone': self.context.main_window.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
                    "auto_fit_resolution": self.context.main_window.auto_fit_resolution_checkbox.isChecked()
                }
                
                # 자동 생성 플래그 설정
                self.context.main_window.prompt_gen_controller.auto_generation_requested = True
                self.context.main_window.prompt_gen_controller.generate_next_prompt(
                    self.context.main_window.search_results, settings
                )
                
        except Exception as e:
            print(f"❌ 자동 생성 재시도 중 오류: {e}")
            self.context.main_window.status_bar.showMessage(f"❌ 재시도 중 오류: {e}")
            self.auto_retry_count = 0

    def _on_thread_finished(self):
        """스레드 완료 시 정리 작업"""
        # 🔧 스레드 종료 처리 및 포인터 정리
        def _cleanup():
            try:
                if self.generation_thread:
                    self.generation_thread.wait(50)  # finished 후 즉시 반환
            except Exception:
                pass
            finally:
                # 포인터 정리 (deleteLater는 이미 signal로 연결됨)
                self.generation_thread = None
                self.generation_worker = None
                
                # 강력한 스레드 정리 실행
                _force_cleanup_all_threads()
        
        _cleanup()

    def _expand_wildcards_in_input(self, input_text: str, negative_prompt: str = "") -> tuple[str, str]:
        """generation_controller 전용 와일드카드 처리 (_expand_recursive와 동일한 기능 지원)

        Returns:
            tuple[str, str]: (expanded_input, processed_negative_prompt)
        """
        if not input_text or not input_text.strip():
            return input_text, negative_prompt

        try:
            # AppContext의 기존 컨텍스트에서 순차 카운터 가져오기 (공유를 위해)
            if self.context.current_prompt_context:
                prompt_context = self.context.current_prompt_context
            else:
                # 컨텍스트가 없으면 새로 생성하여 AppContext에 저장
                from core.prompt_context import PromptContext
                import pandas as pd

                self.context.current_prompt_context = PromptContext(
                    source_row=pd.Series(),
                    settings={}
                )
                prompt_context = self.context.current_prompt_context

            # WildcardProcessor를 사용하여 기존 처리 방식과 동일하게 처리
            from core.wildcard_processor import WildcardProcessor
            wildcard_processor = WildcardProcessor(self.context.wildcard_manager)

            # 1. 전체 문자열을 콤마로 분해하여 태그 리스트 생성 (주석, 개행문자, negative prompt 처리)
            cleaned_tags = []
            processed_negative_prompt = negative_prompt  # 초기값

            for tag in input_text.split(','):
                processed_tag = tag.replace('\n', '').strip()

                # 주석 제거
                if not processed_tag or processed_tag.startswith('#'):
                    continue

                # - prefix 처리 (::가 없는 경우만)
                if processed_tag.startswith('-') and '::' not in processed_tag:
                    # '-'를 제거하고 negative prompt에 추가
                    negative_tag = processed_tag[1:].strip()  # '-' 제거
                    if negative_tag:
                        if processed_negative_prompt:
                            processed_negative_prompt += ', ' + negative_tag
                        else:
                            processed_negative_prompt = negative_tag
                else:
                    # 일반 태그
                    cleaned_tags.append(processed_tag)

            input_tags = cleaned_tags

            # 2. expand_tags 호출하여 완전한 와일드카드 확장 수행 (기존 방식과 동일)
            expanded_tags = wildcard_processor.expand_tags(input_tags, prompt_context)

            # 3. global_append_tags가 있다면 뒤에 추가 (기존 방식과 동일)
            result_parts = expanded_tags.copy()
            if prompt_context.global_append_tags:
                result_parts.extend(prompt_context.global_append_tags)
                # global_append_tags 소비 후 초기화
                prompt_context.global_append_tags.clear()

            # 4. 확장된 태그들을 콤마로 연결하여 단일 문자열로 반환
            expanded_result = ', '.join(result_parts) if result_parts else input_text

            return expanded_result, processed_negative_prompt

        except Exception as e:
            print(f"⚠️ 와일드카드 확장 중 오류 발생: {e}")
            # 오류 발생 시 원본 텍스트 반환
            return input_text, negative_prompt

    def _apply_conditional_prompts(self, input_text: str) -> str:
        """generation_controller 전용 조건부 프롬프트 처리 (와일드카드 확장 후 실행)"""
        try:
            # Conditional Prompt Module 찾기
            conditional_module = None
            for module in self.module_instances:
                if hasattr(module, '__class__') and module.__class__.__name__ == 'PromptListModifierModule':
                    conditional_module = module
                    break
            
            # 모듈이 없거나 비활성화된 경우 원본 반환
            if not conditional_module:
                return input_text
            
            if not hasattr(conditional_module, 'enable_checkbox') or not conditional_module.enable_checkbox.isChecked():
                return input_text
            
            # 규칙 텍스트 가져오기
            if not hasattr(conditional_module, 'rules_textedit'):
                return input_text
            
            rules_text = conditional_module.rules_textedit.toPlainText().strip()
            if not rules_text:
                return input_text
            
            print("🔀 조건부 프롬프트 처리 시작...")
            
            # 입력 문자열을 태그 리스트로 분해
            input_tags = [tag.strip() for tag in input_text.split(',') if tag.strip()]
            
            # prefix, main, postfix 구분 (간소화: 모두 main으로 처리)
            prefix_tags = []
            main_tags = input_tags.copy()
            postfix_tags = []
            
            # 조건부 프롬프트 규칙 적용
            rules = conditional_module._parse_rules(rules_text)
            
            for rule in rules:
                try:
                    condition = rule['condition']
                    action = rule['action']
                    
                    # 조건 확인
                    condition_met = conditional_module._check_condition(condition, prefix_tags, main_tags, postfix_tags)
                    
                    if condition_met:
                        # 액션 실행
                        prefix_tags, main_tags, postfix_tags = conditional_module._execute_action(
                            action, prefix_tags, main_tags, postfix_tags
                        )
                        print(f"  ✅ 규칙 적용: {rule['original']}")
                        
                except Exception as e:
                    print(f"  ⚠️ 규칙 처리 오류: {e}")
                    continue
            
            # 결과를 다시 문자열로 결합
            result_tags = prefix_tags + main_tags + postfix_tags
            result_text = ', '.join(result_tags)
            
            return result_text
            
        except Exception as e:
            print(f"⚠️ 조건부 프롬프트 처리 중 오류: {e}")
            return input_text

    def validate_parameters(self, params: dict) -> tuple[bool, str]:
        """파라미터 유효성 검사 로직"""
        return True, ""
    
    def reset_auto_retry_count(self):
        """🆕 외부에서 재시도 카운터를 리셋할 수 있는 메서드"""
        self.auto_retry_count = 0
        print("🔄 자동 생성 재시도 카운터가 리셋되었습니다.")