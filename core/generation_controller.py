from core.context import AppContext
from core.generation_request import GenerationRequest
from core.sequence_parser import SequenceParser
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

            # 큐가 남아있는 경우 자동 재시도를 보류하고 큐를 먼저 처리
            queue_manager = self.context.generation_queue_manager
            if False and (not queue_manager.is_empty()) and (not queue_manager.is_paused()):
                self.auto_retry_pending = True
                self.queue_hold_auto_gen = True
                print(f"[QUEUE] 큐 우선. 자동 재시도 보류... (남은 큐: {queue_manager.get_queue_size()})")
                # 대기 중이면 즉시 큐 처리 진입
                if not self.is_generating:
                    QTimer.singleShot(0, self._process_next_queue_request)
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
        # arbitration flags between queue and auto-generation
        self.queue_hold_auto_gen = False
        self.auto_retry_pending = False
        
        # 🆕 자동 생성 재시도 관련 추가
        self.auto_retry_count = 0
        self.max_auto_retries = 2  # 자동 생성 시 최대 재시도 횟수 (API 자체에서 5회 재시도 하므로 줄임)
        self.retry_delay_ms = 3000  # 재시도 간격 (밀리초) - 3초로 증가
        
    def execute_generation_pipeline(self, overrides: dict = None, priority: int = 0, from_queue: bool = False):
        """
        7단계 생성 파이프라인을 실행합니다.

        Args:
            overrides: 파라미터 덮어쓰기 딕셔너리
            priority: 우선순위 (0=일반, 100=긴급)
            from_queue: 큐에서 호출되었는지 여부
        """
        # 이미 생성 중인 경우 → 큐에 추가
        if self.is_generating and not from_queue:
            print(f"[QUEUE] 생성 중이므로 요청을 큐에 추가합니다 (우선순위: {priority})")
            self._enqueue_current_request(overrides, priority)
            return

        try:
            # 🆕 시퀀스 프롬프트 감지 (큐에서 호출된 경우 제외)
            if not from_queue:
                main_prompt_text = self.context.main_window.main_prompt_textedit.toPlainText()

                if SequenceParser.is_sequence_prompt(main_prompt_text):
                    print("[SEQUENCE] 시퀀스 프롬프트 감지됨. 시퀀스 모드로 전환합니다.")
                    self._handle_sequence_generation(main_prompt_text, overrides, priority)
                    return

            # --- 1 ~ 4 단계: 파라미터 수집 및 유효성 검사 ---
            # 큐 우선: 대기 상태이고 큐가 있다면 큐를 먼저 처리하고 반환합니다.
            try:
                queue_manager = self.context.generation_queue_manager
                if (not from_queue) and (not self.is_generating) and (not queue_manager.is_empty()) and (not queue_manager.is_paused()):
                    self.queue_hold_auto_gen = True
                    self._update_button_with_queue_size()
                    QTimer.singleShot(0, self._process_next_queue_request)
                    return
            except Exception:
                pass

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

                # --- 🆕 FR-3: 임시 창 프롬프트 엔지니어링 훅 수동 실행 ---
                if 'temp_window_prompt_engineering_tab' in params:
                    prompt_eng_tab = params['temp_window_prompt_engineering_tab']
                    print(f"[TempWindow] 프롬프트 엔지니어링 훅 수동 실행 중...")

                    # PromptContext 생성
                    from core.prompt_context import PromptContext
                    # pd는 이미 파일 상단에서 전역 import됨 (line 10)

                    # source_row 준비 (와일드카드 단독 모드 지원)
                    if params.get('wildcard_standalone', False):
                        # 와일드카드 단독 모드: 빈 데이터로 source_row 생성
                        empty_data = {
                            'general': None,
                            'character': None,
                            'copyright': None,
                            'artist': None,
                            'meta': None
                        }
                        source_row = pd.Series(empty_data, name="wildcard_standalone")
                        print(f"[TempWindow] 와일드카드 단독 모드: 빈 source_row 생성")
                    else:
                        source_row = self.context.current_source_row
                        if source_row is None:
                            source_row = pd.Series({'general': None}, name="temp_window")

                    # tags 파싱 (쉼표로 분리)
                    input_tags = [tag.strip() for tag in params['input'].split(',') if tag.strip()]

                    # PromptContext 초기화
                    temp_context = PromptContext(
                        source_row=source_row,
                        settings=params,
                        prefix_tags=[],
                        main_tags=input_tags,
                        postfix_tags=[]
                    )

                    # 수동 훅 실행
                    try:
                        modified_context = prompt_eng_tab.execute_manual_hook(temp_context)

                        # 수정된 태그를 다시 문자열로 결합
                        all_tags = modified_context.prefix_tags + modified_context.main_tags + modified_context.postfix_tags
                        params['input'] = ', '.join(all_tags)

                        print(f"✅ [TempWindow] 프롬프트 엔지니어링 적용 완료: '{params['input'][:50]}{'...' if len(params['input']) > 50 else ''}'")
                    except Exception as e:
                        print(f"⚠️ [TempWindow] 프롬프트 엔지니어링 훅 실행 오류: {e}")

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

    def _enqueue_current_request(self, overrides: dict = None, priority: int = 0):
        """
        현재 생성 요청을 큐에 추가합니다.

        Phase 2: Early Binding - NAI 데이터를 큐에 추가할 때 캡처

        Args:
            overrides: 파라미터 덮어쓰기 딕셔너리
            priority: 우선순위 (0=일반, 100=긴급)
        """
        try:
            # ✅ Phase 2: 통합된 파라미터 수집 메서드 사용
            params = self._collect_generation_params()

            # 인증 정보 확인
            api_mode = params.get('api_mode', 'NAI')
            if not params.get('credential'):
                self.context.main_window.status_bar.showMessage(f"❌ {api_mode} 인증 정보가 없습니다.")
                return

            # source_row 설정
            source_row = self.context.current_source_row
            if source_row is None:
                empty_data = {'general': None, 'character': None, 'copyright': None, 'artist': None, 'meta': None}
                source_row = pd.Series(empty_data, name="wildcard_standalone")

            # 덮어쓰기 적용
            if overrides:
                params.update(overrides)

            # ✅ Phase 2: NAI 데이터 추출 (Early Binding)
            nai_characters, nai_vibe_transfer, nai_character_reference = self._extract_nai_data(params)

            # GenerationRequest 생성 (NAI 데이터 포함)
            request = GenerationRequest(
                params=params,
                source_row=source_row,
                priority=priority,
                max_retries=0,  # 재시도는 나중에 구현
                nai_characters=nai_characters,
                nai_vibe_transfer=nai_vibe_transfer,
                nai_character_reference=nai_character_reference
            )

            # 큐에 추가 (우선순위에 따라)
            queue_manager = self.context.generation_queue_manager
            if priority > 0:
                request_id = queue_manager.enqueue_with_priority(request)
            else:
                request_id = queue_manager.enqueue_request(request)

            # UI 업데이트 (버튼 텍스트에 큐 크기 표시)
            self._update_button_with_queue_size()

            print(f"✅ [QUEUE] 요청 추가 완료: {request_id[:8]}... (우선순위: {priority})")

        except Exception as e:
            print(f"❌ [QUEUE] 요청 추가 실패: {e}")
            self.context.main_window.status_bar.showMessage(f"❌ 큐 추가 실패: {e}")
            import traceback
            traceback.print_exc()

    def _process_next_queue_request(self):
        """
        큐에서 다음 요청을 가져와 처리합니다.
        """
        queue_manager = self.context.generation_queue_manager
        # 큐가 존재하는 동안 자동생성은 보류
        self.queue_hold_auto_gen = (not queue_manager.is_empty()) and (not queue_manager.is_paused())

        # 추가 안전: 스레드 실행 중이면 대기
        if self.generation_thread and self.generation_thread.isRunning():
            print("[QUEUE] 이미 생성 중입니다. 디스패처 대기.")
            return

        # 🔒 이미 생성 중이면 나중에 재시도 (자동생성이 끼어들었을 수 있음)
        if self.is_generating:
            print("[QUEUE] 이미 생성 중입니다. 디스패처 대기.")
            return

        # 큐가 비어있는지 확인
        if queue_manager.is_empty():
            print("[QUEUE] 큐가 비어있습니다. 대기 종료.")
            return

        # 다음 요청 가져오기
        next_request = queue_manager.dequeue_request()
        if not next_request:
            print("[QUEUE] 큐에서 요청을 가져오지 못했습니다 (일시정지 상태일 수 있음)")
            return

        print(f"[QUEUE] 요청 가져옴: {next_request.request_id[:8]}... "
              f"(남은 큐: {queue_manager.get_queue_size()})")

        # 요청 상태 업데이트
        next_request.mark_processing()

        # context 업데이트
        self.context.current_source_row = next_request.source_row

        # 생성 파이프라인 실행 (from_queue=True로 재귀 방지)
        try:
            # 자동생성 모드일 때, 큐 아이템도 동일 파이프라인으로 처리되도록 플래그 전달
            try:
                auto_checkbox = self.context.main_window.generation_checkboxes.get("자동 생성")
                if auto_checkbox and auto_checkbox.isChecked():
                    if isinstance(next_request.params, dict):
                        next_request.params["auto_generate"] = True
            except Exception:
                pass

            # ✅ Phase 3: GenerationRequest를 params에 추가 (API Service가 NAI 데이터 접근 가능하도록)
            if isinstance(next_request.params, dict):
                next_request.params["_generation_request"] = next_request

            self.execute_generation_pipeline(
                overrides=next_request.params,
                priority=next_request.priority,
                from_queue=True
            )
        except Exception as e:
            print(f"❌ [QUEUE] 큐 요청 처리 실패: {e}")
            next_request.mark_failed(str(e))
            # 다음 요청 처리
            self._process_next_queue_request()

    def _update_button_with_queue_size(self):
        """생성 버튼 텍스트를 큐 크기로 업데이트합니다."""
        queue_manager = self.context.generation_queue_manager
        queue_size = queue_manager.get_queue_size()

        if self.is_generating:
            # 생성 중일 때
            if queue_size > 0:
                btn_text = f"🔄 생성 중... ({queue_size})"
            else:
                btn_text = "🔄 생성 중..."

            self.context.main_window.generate_button_main.setText(btn_text)
            if hasattr(self.context.main_window, 'detached_generate_btn'):
                self.context.main_window.detached_generate_btn.setText(btn_text)
        else:
            # 생성 중이 아닐 때
            if queue_size > 0:
                btn_text = f"🎨 이미지 생성 요청 ({queue_size})"
            else:
                btn_text = "🎨 이미지 생성 요청"

            self.context.main_window.generate_button_main.setText(btn_text)
            if hasattr(self.context.main_window, 'detached_generate_btn'):
                self.context.main_window.detached_generate_btn.setText(btn_text)

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
        # 🆕 버튼 비활성화 제거 - 큐에 추가할 수 있도록 활성 상태 유지
        # self.context.main_window.generate_button_main.setEnabled(False)

        # 🆕 큐 크기를 반영한 버튼 텍스트 업데이트
        self._update_button_with_queue_size()

        self.context.main_window.status_bar.showMessage("🚀 생성 시작...")
    
    def _on_generation_progress(self, message: str):
        """생성 진행 상황 업데이트 슬롯"""
        self.context.main_window.status_bar.showMessage(message)
    
    def _on_generation_finished(self, result: dict):
        """생성 완료 시 호출되는 슬롯"""
        # 🆕 성공 시 재시도 카운터 리셋
        self.auto_retry_count = 0

        # UI 업데이트 (update_ui_with_result 내부에서 automation_module 처리)
        self.context.main_window.update_ui_with_result(result)

        # 🆕 큐에 대기 중인 요청이 있으면 다음 요청 처리
        queue_manager = self.context.generation_queue_manager
        if not queue_manager.is_empty() and not queue_manager.is_paused():
            # 🔒 큐가 있으면 is_generating을 유지하여 자동생성 차단
            print(f"[QUEUE] 생성 완료. 큐 우선 처리... (남은 큐: {queue_manager.get_queue_size()})")
            # ⚡ 즉시 큐 처리 (자동생성이 끼어들 틈 없음)
            # 다음 요청 디스패치는 스레드 종료에서 트리거합니다.
        else:
            # 큐가 비어있거나 일시정지 상태면 is_generating = False로 설정
            # → 자동생성이 지연 없이 즉시 트리거 가능!
            # is_generating 해제는 스레드 종료 핸들러에서 처리
            self._update_button_with_queue_size()
            if queue_manager.is_empty():
                print("[QUEUE] 큐 비어있음. 자동생성 즉시 가능.")
            else:
                print("[QUEUE] 큐가 일시정지 상태입니다.")

    def _on_generation_error(self, error_message: str):
        """생성 오류 시 호출되는 슬롯 - 🆕 자동 재시도 로직 추가"""
        print(f"❌ 생성 오류 발생: {error_message}")

        # 🆕 자동 생성 모드에서의 재시도 로직
        auto_generate_checkbox = self.context.main_window.generation_checkboxes.get("자동 생성")
        is_auto_generation = auto_generate_checkbox and auto_generate_checkbox.isChecked()

        # 큐 확인 (재시도 및 큐 처리 여부 결정)
        queue_manager = self.context.generation_queue_manager
        has_queue = not queue_manager.is_empty() and not queue_manager.is_paused()

        if is_auto_generation and self.auto_retry_count < self.max_auto_retries:
            # 🔒 자동 재시도 중에는 is_generating 유지 (차단)
            self.auto_retry_count += 1
            retry_message = f"🔄 자동 생성 재시도 {self.auto_retry_count}/{self.max_auto_retries} (오류: {error_message[:50]}...)"
            self.context.main_window.status_bar.showMessage(retry_message)
            print(f"🔄 자동 생성 재시도 시작: {self.auto_retry_count}/{self.max_auto_retries}")

            # 지연 후 재시도
            if has_queue:
                # 큐를 먼저 소진하고 자동 재시도를 이어갑니다.
                self.auto_retry_pending = True
                print("[QUEUE] 큐 우선. 자동 재시도 보류.")
            else:
                QTimer.singleShot(self.retry_delay_ms, self._retry_auto_generation)

        elif has_queue:
            # 🔒 큐가 있으면 is_generating 유지하고 즉시 큐 처리
            print(f"[QUEUE] 오류 발생. 큐 우선 처리... (남은 큐: {queue_manager.get_queue_size()})")
            # 스레드 종료 시점에 큐 디스패치 수행

        else:
            # 재시도도 안 하고 큐도 없으면 is_generating = False
            # is_generating 해제는 스레드 종료 핸들러에서 처리
            self.context.main_window.generate_button_main.setEnabled(True)
            self.context.main_window.generate_button_main.setText("🎨 이미지 생성 요청")
            # 분리된 버튼도 활성화
            if hasattr(self.context.main_window, 'detached_generate_btn'):
                self.context.main_window.detached_generate_btn.setEnabled(True)
                self.context.main_window.detached_generate_btn.setText("🎨 이미지 생성 요청")

            # 재시도 횟수 초과 체크
            if is_auto_generation and self.auto_retry_count >= self.max_auto_retries:
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

            print("[QUEUE] 큐 비어있음. 자동생성 가능.")

    def _retry_auto_generation(self):
        """🆕 자동 생성 재시도를 실행하는 메서드"""
        try:
            # 한국어: 큐가 존재하면 자동생성 재시도를 보류하고 먼저 큐를 처리합니다.
            queue_manager = self.context.generation_queue_manager
            if (not queue_manager.is_empty()) and (not queue_manager.is_paused()):
                self.auto_retry_pending = True
                self.queue_hold_auto_gen = True
                print("[QUEUE] 큐 우선. 자동 재시도 보류.")
                QTimer.singleShot(0, self._process_next_queue_request)
                return
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

        # 스레드 종료 시점에서만 is_generating을 False로 전환하고 다음 작업을 결정
        try:
            self.is_generating = False

            queue_manager = self.context.generation_queue_manager
            has_queue = (not queue_manager.is_empty()) and (not queue_manager.is_paused())

            if has_queue:
                # 큐 우선 처리: 자동생성을 보류한 상태에서 다음 요청을 즉시 디스패치
                self.queue_hold_auto_gen = True
                print(f"[QUEUE] 스레드 종료. 큐 디스패치 시작... (남은 큐: {queue_manager.get_queue_size()})")
                QTimer.singleShot(0, self._process_next_queue_request)
            else:
                # 큐가 비면 자동생성 보류 해제
                if self.queue_hold_auto_gen:
                    print("[QUEUE] 큐 비었음. 자동생성 보류 해제.")
                self.queue_hold_auto_gen = False

                # 보류 중인 자동 재시도 수행
                if self.auto_retry_pending:
                    self.auto_retry_pending = False
                    print("[AUTO] 보류된 자동 재시도 실행.")
                    QTimer.singleShot(0, self._retry_auto_generation)

            # UI 상태 업데이트
            self._update_button_with_queue_size()

            # 🆕 FR-2-1: 임시 창 모드 플래그 해제
            if self.context.temp_window_mode:
                print(f"[DEBUG] 생성 완료. 임시 창 모드 플래그 해제")
                self.context.temp_window_mode = False
                self.context.temp_window_character_tab = None

        except Exception as _e:
            print(f"[GEN] thread-finish 후 디스패치 오류: {_e}")

            # 에러 발생 시에도 플래그 해제
            if self.context.temp_window_mode:
                print(f"[DEBUG] 에러 발생. 임시 창 모드 플래그 강제 해제")
                self.context.temp_window_mode = False
                self.context.temp_window_character_tab = None

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
                # pd는 이미 파일 상단에서 전역 import됨 (line 10)

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

    # ==================== 🆕 시퀀스 생성 메서드 ====================

    def _handle_sequence_generation(self, prompt_text: str, overrides: dict = None, priority: int = 0):
        """
        🆕 시퀀스 생성 처리

        Args:
            prompt_text: 원본 프롬프트 텍스트
            overrides: 파라미터 덮어쓰기
            priority: 우선순위
        """
        try:
            # 1. 파싱
            print("[SEQUENCE] 프롬프트 파싱 중...")
            parsed = SequenceParser.parse_prompt(prompt_text)

            # 2. 검증
            is_valid, error_msg = SequenceParser.validate_structure(parsed)
            if not is_valid:
                self.context.main_window.status_bar.showMessage(f"❌ 시퀀스 검증 실패: {error_msg}")
                print(f"[SEQUENCE] 검증 실패: {error_msg}")
                return

            # 3. 프롬프트 세트 생성
            print("[SEQUENCE] 프롬프트 세트 생성 중...")
            prompt_sets = SequenceParser.generate_prompt_sets(parsed)
            print(f"[SEQUENCE] {len(prompt_sets)}개 프롬프트 세트 생성됨")

            # 🔧 FIX MEDIUM-1: 빈 prompt_sets 체크
            if not prompt_sets:
                self.context.main_window.status_bar.showMessage("❌ 프롬프트 세트 생성 실패: 빈 결과")
                print("[SEQUENCE] 오류: 프롬프트 세트가 비어있습니다.")
                return

            # 디버깅: 생성된 프롬프트 출력
            for i, prompt in enumerate(prompt_sets, 1):
                print(f"[SEQUENCE] #{i}: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")

            # 4. 해상도 결정
            fixed_resolution = self._determine_fixed_resolution(prompt_sets[0])
            print(f"[SEQUENCE] 고정 해상도: {fixed_resolution[0]}x{fixed_resolution[1]}")

            # 5. 큐에 일괄 추가
            print("[SEQUENCE] 큐에 요청 추가 중...")
            self._enqueue_sequence_requests(prompt_sets, fixed_resolution, overrides, priority)

            # 6. 상태바 업데이트
            self.context.main_window.status_bar.showMessage(
                f"✅ 시퀀스 생성: {len(prompt_sets)}개 요청이 큐에 추가되었습니다."
            )

            # 7. 큐 처리 시작
            print("[SEQUENCE] 큐 처리 시작...")
            QTimer.singleShot(0, self._process_next_queue_request)

        except ValueError as e:
            # 파싱 오류
            self.context.main_window.status_bar.showMessage(f"❌ 시퀀스 파싱 오류: {e}")
            print(f"[SEQUENCE] 파싱 오류: {e}")
        except Exception as e:
            self.context.main_window.status_bar.showMessage(f"❌ 시퀀스 생성 오류: {e}")
            print(f"[SEQUENCE] 생성 오류: {e}")
            import traceback
            traceback.print_exc()

    def _determine_fixed_resolution(self, first_prompt: str) -> tuple[int, int]:
        """
        🆕 첫 번째 프롬프트에서 해상도 결정

        Args:
            first_prompt: 첫 번째 프롬프트 텍스트

        Returns:
            tuple: (width, height)
        """
        # 1. resolution: 태그 확인
        resolution_match = re.search(r'resolution:(\d+)x(\d+)', first_prompt)
        if resolution_match:
            width = int(resolution_match.group(1))
            height = int(resolution_match.group(2))
            print(f"[SEQUENCE] resolution: 태그에서 해상도 추출: {width}x{height}")
            return (width, height)

        # 2. UI 해상도 콤보박스 값 사용
        try:
            selected_value = self.context.main_window.resolution_combo.currentText()
            width, height = map(int, selected_value.split('x'))
            print(f"[SEQUENCE] UI 콤보박스에서 해상도 추출: {width}x{height}")
            return (width, height)
        except Exception as e:
            print(f"[SEQUENCE] 해상도 추출 실패, 기본값 사용: {e}")
            return (832, 1216)  # 기본값

    def _enqueue_sequence_requests(
        self,
        prompt_sets: list,
        fixed_resolution: tuple[int, int],
        overrides: dict = None,
        priority: int = 0
    ):
        """
        🆕 시퀀스 요청을 큐에 일괄 추가

        Phase 2: Early Binding - NAI 데이터를 시퀀스 전체에 대해 한 번만 캡처

        Args:
            prompt_sets: 프롬프트 리스트
            fixed_resolution: (width, height)
            overrides: 파라미터 덮어쓰기
            priority: 우선순위
        """
        queue_manager = self.context.generation_queue_manager

        # 🔧 FIX HIGH-1: 파라미터를 루프 밖에서 한 번만 수집
        # (캐릭터 리롤이 각 시퀀스마다 반복되지 않도록)
        base_params = self._collect_generation_params()

        # ✅ Phase 2: NAI 데이터를 시퀀스 전체에 대해 한 번만 추출 (Early Binding)
        nai_characters, nai_vibe_transfer, nai_character_reference = self._extract_nai_data(base_params)

        # 🆕 API 모드 확인 (시드 처리 분기용)
        api_mode = base_params.get('api_mode', 'NAI')
        seed_is_fixed = self.context.main_window.seed_fix_checkbox.isChecked()

        for i, prompt in enumerate(prompt_sets):
            try:
                # 각 요청마다 base_params를 복사하여 사용
                params = base_params.copy()

                # seed: 태그 처리 (각 프롬프트마다 독립적)
                # 🔧 FIX MEDIUM-2: seed: 태그를 추출 후 프롬프트에서 제거
                seed_match = re.search(r'seed:(\d+)', prompt)
                if seed_match:
                    params['seed'] = int(seed_match.group(1))
                    print(f"[SEQUENCE] 프롬프트 #{i+1}: seed:{params['seed']} 적용")
                    # 프롬프트에서 seed: 태그 제거
                    prompt = re.sub(r'seed:\d+,?\s*', '', prompt).strip()
                else:
                    # 🆕 seed: 태그가 없는 경우, NAI 모드에서는 랜덤 시드 생성
                    if api_mode == "NAI" and not seed_is_fixed:
                        params['seed'] = random.randint(0, 9999999999)
                        print(f"[SEQUENCE] 프롬프트 #{i+1}: NAI 랜덤 시드 생성 - {params['seed']}")
                    # WEBUI/COMFYUI는 고정 시드 사용 (base_params의 seed 유지)

                # 프롬프트 설정 (메인 프롬프트를 각 시퀀스 프롬프트로 대체)
                params['input'] = prompt

                # 해상도 설정 (고정)
                params['width'] = fixed_resolution[0]
                params['height'] = fixed_resolution[1]

                # 덮어쓰기 적용
                if overrides:
                    params.update(overrides)

                # source_row 설정
                source_row = self.context.current_source_row
                if source_row is None:
                    empty_data = {
                        'general': None,
                        'character': None,
                        'copyright': None,
                        'artist': None,
                        'meta': None
                    }
                    source_row = pd.Series(empty_data, name=f"sequence_{i+1}")

                # GenerationRequest 생성 (NAI 데이터 포함)
                request = GenerationRequest(
                    params=params,
                    source_row=source_row,
                    priority=priority,
                    max_retries=0,
                    nai_characters=nai_characters,
                    nai_vibe_transfer=nai_vibe_transfer,
                    nai_character_reference=nai_character_reference
                )

                # 큐에 추가
                if priority > 0:
                    request_id = queue_manager.enqueue_with_priority(request)
                else:
                    request_id = queue_manager.enqueue_request(request)

                print(f"[SEQUENCE] 요청 {i+1}/{len(prompt_sets)} 추가됨: {request_id[:8]}...")

            except Exception as e:
                print(f"[SEQUENCE] 요청 {i+1} 추가 실패: {e}")
                continue

        # 버튼 텍스트 업데이트
        self._update_button_with_queue_size()

    def _collect_generation_params(self) -> dict:
        """
        🆕 생성 파라미터 수집 (기존 로직 재사용)

        Returns:
            dict: 생성 파라미터
        """
        # API 모드 및 인증 정보
        api_mode = self.context.main_window.get_current_api_mode()

        if api_mode == "NAI":
            token = 'nai_token'
            # NAI 모드에서 캐릭터 리롤 처리
            char_module = self.context.middle_section_controller.get_module_instance("CharacterModule")
            if (char_module and
                char_module.activate_checkbox.isChecked() and
                char_module.reroll_on_generate_checkbox.isChecked()):
                print("🔄️ 생성 시 Reroll: 캐릭터 와일드카드를 갱신합니다.")
                char_module.process_and_update_view()
        elif api_mode == "COMFYUI":
            token = 'comfyui_url'
        else:
            token = 'webui_url'

        credential = self.context.secure_token_manager.get_token(token)

        # 메인 파라미터
        params = self.context.main_window.get_main_parameters()
        params['api_mode'] = api_mode
        params['credential'] = credential

        # 모듈 파라미터 수집
        for module in self.module_instances:
            module_params = module.get_parameters()
            if module_params:
                params.update(module_params)

        # 랜덤 해상도 처리
        if params.get('random_resolution', False) and not self.context.main_window.resolution_is_detected:
            random_index = random.randint(0, self.context.main_window.resolution_combo.count() - 1)
            self.context.main_window.resolution_combo.setCurrentIndex(random_index)
            selected_value = self.context.main_window.resolution_combo.currentText()
            width, height = map(int, selected_value.split('x'))
            params['width'] = width
            params['height'] = height
            print(f"랜덤 해상도 설정: {width}x{height}")

        # Img2Img 파라미터
        img2img_params = self.context.main_window.img2img_panel.get_parameters()
        if img2img_params:
            print("🖼️ Img2Img 패널 활성화됨. 파라미터를 추가합니다.")
            params.update(img2img_params)

        # ComfyUI 워크플로우 처리
        if api_mode == "COMFYUI":
            final_workflow = self.workflow_manager.apply_params_to_workflow(params)
            if final_workflow:
                params['workflow'] = final_workflow

        return params

    def _extract_nai_data(self, params: dict) -> tuple:
        """
        🆕 NAI 전용 데이터를 추출하여 타입 안전한 dataclass로 변환

        Phase 2: Early Binding - 큐에 추가될 때 데이터 캡처

        Args:
            params: 생성 파라미터 (모듈에서 수집된 데이터 포함)

        Returns:
            Tuple of (NAICharacterData | None, NAIVibeTransferData | None, NAICharacterReferenceData | None)
        """
        from core.generation_request import (
            NAICharacterData,
            NAIVibeTransferData,
            NAICharacterReferenceData
        )
        from typing import Optional, Tuple

        nai_characters: Optional[NAICharacterData] = None
        nai_vibe_transfer: Optional[NAIVibeTransferData] = None
        nai_character_reference: Optional[NAICharacterReferenceData] = None

        # API 모드 확인 (NAI가 아니면 모두 None 반환)
        api_mode = params.get('api_mode', 'NAI')
        if api_mode != "NAI":
            return nai_characters, nai_vibe_transfer, nai_character_reference

        try:
            # 1. Character Module (NAID4)
            if 'characters' in params and params['characters']:
                nai_characters = NAICharacterData.from_params(params)
                if nai_characters:
                    print(f"✅ [EarlyBinding] Character Data 캡처: {len(nai_characters.characters)}명")

            # 2. Vibe Transfer Module
            vibe_keys = ['reference_image_multiple', 'reference_strength_multiple']
            if all(key in params for key in vibe_keys):
                nai_vibe_transfer = NAIVibeTransferData.from_params(params)
                if nai_vibe_transfer:
                    print(f"✅ [EarlyBinding] Vibe Transfer Data 캡처: {len(nai_vibe_transfer.reference_image_multiple)}개")

            # 3. Character Reference Module (NAID4.5 Director Tool)
            ref_keys = ['director_reference_descriptions', 'director_reference_images']
            if all(key in params for key in ref_keys):
                nai_character_reference = NAICharacterReferenceData.from_params(params)
                if nai_character_reference:
                    print(f"✅ [EarlyBinding] Character Reference Data 캡처")

        except ValueError as e:
            # 데이터 검증 실패
            print(f"⚠️ [EarlyBinding] NAI 데이터 검증 실패: {e}")
        except Exception as e:
            # 예상치 못한 오류
            print(f"❌ [EarlyBinding] NAI 데이터 추출 오류: {e}")
            import traceback
            traceback.print_exc()

        return nai_characters, nai_vibe_transfer, nai_character_reference
