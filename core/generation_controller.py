from core.context import AppContext
from core.generation_request import GenerationRequest
from core.sequence_parser import SequenceParser
from core.vibe_cluster_resolver import VibeClusterPromptError, apply_vibe_cluster_prompt_override
from core.wildcard_processor import split_tags_smart
from core.resolution_utils import (
    anima_resolution_preset_candidates,
    anima_resolution_preset_labels,
    anima_resolution_preset_square_label,
    parse_resolution_pair,
)
from PIL import Image
import piexif
import piexif.helper
import copy
import json
import re, random
from pathlib import Path
from PyQt6.QtCore import QThread, QObject, pyqtSignal, QTimer, QCoreApplication, QThreadPool
import pandas as pd
import gc
import requests
from utils.comfyui_png_metadata import enrich_comfyui_png_bytes
from utils.webui_generation_info import extract_webui_infotext, extract_webui_seed

def _force_cleanup_all_threads():
    """
    모든 종류의 스레드 풀과 연결을 강제로 정리하는 함수

    ✅ 크로스 스레드 타이머 문제 해결:
    - QTimer.singleShot + lambda 제거 (타이머 충돌 원인)
    - 직접 processEvents() 호출로 대체
    """
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

        # 5. Qt 이벤트 루프 강제 처리 (직접 호출)
        # ✅ 수정: QTimer.singleShot 제거 → 타이머 충돌 해결
        for _ in range(5):
            QCoreApplication.processEvents()

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
        self._is_running = False  # 🆕 실행 상태 추적
        self._pending_progress_data = None  # 🔧 스레드 안전한 진행률 데이터 전달용
        self._main_prompt_text = ''  # 🔧 메인 스레드에서 캡처한 프롬프트 텍스트
        self._character_prompts = []  # 🔧 메인 스레드에서 캡처한 캐릭터 프롬프트
        self._scoped_wildcard_history = {}  # 📌 메인 스레드에서 캡처한 scoped 와일드카드 히스토리
        
    def set_generation_params(self, params: dict, source_row):
        """생성 파라미터와 소스 행을 설정합니다."""
        self.params = params
        self.source_row = source_row
        
    def run_generation(self):
        """별도 스레드에서 실행될 생성 작업"""
        self._is_running = True  # 🆕 실행 시작 표시
        try:
            self.generation_started.emit()
            self.generation_progress.emit("API 호출 중...")

            # 🔧 FIX: 스레드 안전한 진행률 콜백 (시그널 emit은 Qt에서 크로스 스레드 안전)
            def _progress_callback(message, current, total, percent):
                self.generation_progress.emit(message)
                self._pending_progress_data = {"current": current, "total": total, "percent": percent}

            # API 호출 (이 부분이 시간이 오래 걸림)
            api_result = self.context.api_service.call_generation_api(self.params, progress_callback=_progress_callback)
            
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
                self._embed_comfyui_result_metadata(processed_result)
                if self.params.get('api_mode') == 'COMFYUI' and processed_result.get('image'):
                    processed_result['info'] = self._extract_info_from_image(processed_result['image'])
            
            self.generation_finished.emit(processed_result)

        except Exception as e:
            self.generation_error.emit(str(e))
        finally:
            self._is_running = False  # 🆕 실행 완료 표시
    
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
                prompt_text = self.params.get('input') or image.info.get('Description', '')
                # NAI 형식에 맞춰 문자열 재구성
                info_string = (
                    f"{prompt_text}\n"
                    f"Negative prompt: {comment_data.get('uc', '')}\n"
                    f"Steps: {comment_data.get('steps', 'N/A')}, Sampler: {comment_data.get('sampler', 'N/A')}, "
                    f"CFG scale: {comment_data.get('scale', 'N/A')}, Seed: {comment_data.get('seed', 'N/A')}"
                )
                return info_string
            except (json.JSONDecodeError, KeyError) as e:
                print(f"NovelAI 메타데이터 파싱 오류: {e}")
                # 실패 시 다른 방법으로 계속 진행

        # 2. ComfyUI/NAIA ComfyUI 메타데이터 처리
        if any(key in image.info for key in ('prompt', 'workflow', 'workflow_api', 'naia_generation_params')):
            try:
                from utils.image_info import ImageMetadataExtractor

                metadata = ImageMetadataExtractor.extract_metadata(image) or {}
                if metadata.get('type') == 'comfyui':
                    params = metadata.get('parameters', {}) or {}
                    prompt = metadata.get('prompt', '')
                    negative = metadata.get('negative_prompt') or metadata.get('negative', '')
                    parts = [f"[ComfyUI] Prompt: {prompt}"]
                    if negative:
                        parts.append(f"Negative prompt: {negative}")
                    if params:
                        parts.append(
                            "Steps: {steps}, Sampler: {sampler}, CFG: {cfg}, Seed: {seed}".format(
                                steps=params.get('steps', 'N/A'),
                                sampler=params.get('sampler') or params.get('sampler_name', 'N/A'),
                                cfg=params.get('cfg_scale') or params.get('cfg', 'N/A'),
                                seed=params.get('seed', 'N/A'),
                            )
                        )
                    return "\n".join(parts)
            except Exception as e:
                print(f"ComfyUI 메타데이터 파싱 오류: {e}")

        # 3. A1111 등 표준 'parameters' 메타데이터 처리
        if 'parameters' in image.info and isinstance(image.info['parameters'], str):
            return image.info['parameters']
            
        # 4. EXIF 데이터에서 UserComment 추출 시도
        if 'exif' in image.info:
            try:
                exif_data = image.info['exif']
                exif_dict = piexif.load(exif_data)
                user_comment_bytes = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment, b'')
                
                if user_comment_bytes:
                    return piexif.helper.UserComment.load(user_comment_bytes)
            except Exception as e:
                print(f"EXIF UserComment 추출 오류: {e}")

        # 5. 기타 'Comment' 또는 'comment' 필드 확인
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
            params_copy.pop('_comfyui_workflow_ui', None)  # PNG workflow 청크에 별도 저장

            webui_seed = None
            if params_copy.get('api_mode') == 'WEBUI':
                webui_info = result.get('generation_info') or result.get('info')
                webui_seed = extract_webui_seed(webui_info)
                if webui_seed is not None:
                    params_copy['seed'] = webui_seed
                    params_copy['seed_fixed'] = True
                webui_infotext = extract_webui_infotext(webui_info)
                current_info = str(result.get('info') or '')
                if webui_infotext and "Seed:" not in current_info:
                    result['info'] = webui_infotext
            
            result['generation_params'] = params_copy
            
            # 🔧 FIX: 메인 스레드에서 캡처한 텍스트 사용 (크로스 스레드 UI 접근 방지)
            main_prompt_raw = getattr(self, '_main_prompt_text', '')
            
            # 프롬프트 컨텍스트 정보
            scoped_wh = getattr(self, '_scoped_wildcard_history', {})
            result['prompt_context'] = {
                'original_input': self.params.get('input', ''),
                'processed_input': self.params.get('input', ''),  # 필요시 파이프라인 처리 후 값으로 교체
                'negative_prompt': self.params.get('negative_prompt', ''),
                'main_prompt': main_prompt_raw,  # 🆕 UI에서 가져온 원본 프롬프트 (\n\n 포함)
                'character_prompts': getattr(self, '_character_prompts', []),
                'source_tags': self.source_row.to_dict() if self.source_row is not None else {},
                'wildcard_resolved': self.source_row is not None,
                'scoped_wildcard_history': scoped_wh  # 📌 scope에 등록된 와일드카드의 선택 결과
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
            if webui_seed is not None:
                result['api_metadata']['webui_seed'] = webui_seed
            
            # 생성 시각과 백엔드 타입
            result['creation_timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
            result['backend_type'] = self.params.get('api_mode', 'NAI')

            if params_copy.get('result_enhance_request'):
                image = result.get('image')
                result_size = getattr(image, 'size', None)
                source_size = params_copy.get('result_enhance_source_size') or []
                enhance_backend = params_copy.get('result_enhance_backend') or result['backend_type']
                enhance_upscale = params_copy.get('result_enhance_upscale', params_copy.get('hr_scale', 2.0))
                enhance_strength = params_copy.get(
                    'result_enhance_strength',
                    params_copy.get('denoising_strength', 0.5),
                )
                try:
                    enhance_upscale_text = f"{float(enhance_upscale):g}"
                except (TypeError, ValueError):
                    enhance_upscale_text = str(enhance_upscale)
                try:
                    enhance_strength_text = f"{float(enhance_strength):g}"
                except (TypeError, ValueError):
                    enhance_strength_text = str(enhance_strength)
                if not isinstance(source_size, (list, tuple)):
                    source_size = []
                result['api_metadata'].update({
                    'enhanced': True,
                    'enhance_backend': enhance_backend,
                    'enhance_upscale': enhance_upscale,
                    'enhance_strength': enhance_strength,
                    'enhance_hr_upscaler': params_copy.get('result_enhance_hr_upscaler', params_copy.get('hr_upscaler', '')),
                    'enhance_hires_steps': params_copy.get('result_enhance_hires_steps', params_copy.get('hires_steps', 10)),
                    'enhance_hr_cfg': params_copy.get('result_enhance_hr_cfg', params_copy.get('hr_cfg', 7.0)),
                    'source_size': tuple(source_size[:2]) if len(source_size) >= 2 else None,
                    'result_size': tuple(result_size) if result_size else None,
                })
                info_text = result.get('info', '') or ''
                suffix = (
                    f"\nEnhanced: x{enhance_upscale_text}, "
                    f"denoise={enhance_strength_text}, "
                    f"upscaler={params_copy.get('result_enhance_hr_upscaler', params_copy.get('hr_upscaler', ''))} "
                )
                if result_size:
                    suffix += f"({result_size[0]}x{result_size[1]})"
                result['info'] = info_text + suffix
            
            print(f"✅ 확장된 메타데이터 수집 완료: {result['backend_type']}")
            
        except Exception as e:
            print(f"⚠️ 메타데이터 수집 중 오류: {e}")
            # 기본값으로 설정
            result.setdefault('generation_params', {})
            result.setdefault('prompt_context', {})
            result.setdefault('api_metadata', {})
            result.setdefault('creation_timestamp', time.strftime('%Y-%m-%d %H:%M:%S'))
            result.setdefault('backend_type', 'NAI')

    def _embed_comfyui_result_metadata(self, result: dict):
        """ComfyUI 결과 PNG에 ComfyUI/NAIA 복원용 tEXt 청크를 보강합니다."""
        if self.params.get('api_mode') != 'COMFYUI':
            return

        workflow_api = self.params.get('workflow')
        if not workflow_api:
            return

        try:
            enriched_bytes, enriched_image, changed = enrich_comfyui_png_bytes(
                result.get('raw_bytes'),
                result.get('image'),
                workflow_api=workflow_api,
                workflow_ui=self.params.get('_comfyui_workflow_ui'),
                generation_params=result.get('generation_params', {}),
                prompt_context=result.get('prompt_context', {}),
                api_metadata=result.get('api_metadata', {}),
            )
            result['raw_bytes'] = enriched_bytes
            result['image'] = enriched_image
            if changed:
                print("✅ ComfyUI PNG 메타데이터 보강 완료")
        except Exception as e:
            print(f"⚠️ ComfyUI PNG 메타데이터 보강 실패: {e}")

class GenerationController:
    def __init__(self, context: 'AppContext', module_instances: list):
        self.context = context
        self.module_instances = module_instances
        self.workflow_manager = self.context.comfyui_workflow_manager # AppContext에서 참조

        # 스레드 관련 초기화
        self.generation_thread = None
        self.generation_worker = None
        self.is_generating = False
        self.current_generation_params = None  # 🆕 현재 생성 중인 파라미터 (에러 처리용)
        # arbitration flags between queue and auto-generation
        self.queue_hold_auto_gen = False
        self.auto_retry_pending = False

        # 🆕 자동 생성 재시도 관련 추가
        self.auto_retry_count = 0
        self.max_auto_retries = 2  # 자동 생성 시 최대 재시도 횟수 (API 자체에서 5회 재시도 하므로 줄임)
        self.retry_delay_ms = 3000  # 재시도 간격 (밀리초) - 3초로 증가

        # 🆕 스레드 안전 관리를 위한 추가 변수
        self._thread_cleanup_in_progress = False  # 스레드 정리 중 여부
        self._pending_thread_refs = []  # 정리 대기 중인 스레드 참조

    def _apply_webui_hiresfix_assist_defaults(self, params: dict) -> None:
        if str(params.get('api_mode') or '').upper() != "WEBUI":
            return
        bridge = getattr(self.context, "remote_bridge", None)
        getter = getattr(bridge, "get_webui_hiresfix_assist_params", None)
        if not callable(getter):
            return
        try:
            defaults = getter()
        except Exception as e:
            print(f"⚠️ WEBUI Hiresfix Assist 설정 읽기 실패: {e}")
            return
        if not isinstance(defaults, dict):
            return
        if "webui_hiresfix_assist" in defaults:
            params.setdefault("webui_hiresfix_assist", defaults["webui_hiresfix_assist"])
        if "webui_hiresfix_assist_target" in defaults:
            params.setdefault("webui_hiresfix_assist_target", defaults["webui_hiresfix_assist_target"])

    def _should_apply_remote_web_hires_preset_swap_default(self, params: dict) -> bool:
        if "hires_preset_swap" in params:
            return False
        if bool(params.get("_remote_web_session_params")):
            return True
        if str(params.get("_remote_queue_source") or "") == "Web":
            return True

        prompt_settings = {}
        try:
            prompt_context = getattr(self.context, "current_prompt_context", None)
            prompt_settings = getattr(prompt_context, "settings", {}) or {}
        except Exception:
            prompt_settings = {}
        is_auto_generate_prompt = bool(params.get("auto_generate")) or bool(
            prompt_settings.get("auto_generate")
        )
        if not is_auto_generate_prompt:
            return False

        bridge = getattr(self.context, "remote_bridge", None)
        getter = getattr(bridge, "is_remote_auto_generate_enabled", None)
        if not callable(getter):
            return False
        try:
            return bool(getter())
        except Exception:
            return False

    def _apply_remote_web_hires_preset_swap_default(self, params: dict) -> None:
        if str(params.get('api_mode') or '').upper() != "WEBUI":
            return
        if not self._should_apply_remote_web_hires_preset_swap_default(params):
            return
        bridge = getattr(self.context, "remote_bridge", None)
        swap_getter = getattr(bridge, "get_webui_hires_preset_swap_params", None)
        if not callable(swap_getter):
            return
        try:
            swap_defaults = swap_getter()
        except Exception as e:
            print(f"⚠️ WEBUI Hires Preset Swap 설정 읽기 실패: {e}")
            return
        if not isinstance(swap_defaults, dict):
            return
        if "hires_preset_swap" in swap_defaults:
            params.setdefault("hires_preset_swap", swap_defaults["hires_preset_swap"])

    def _should_apply_remote_web_resolution_preset_default(self, params: dict) -> bool:
        if "resolution_preset_enabled" in params or "resolution_preset" in params:
            return False
        api_mode = str(params.get('api_mode') or '').upper()
        if api_mode not in {"WEBUI", "COMFYUI"}:
            return False
        if bool(params.get("_remote_web_session_params")):
            return True

        prompt_settings = {}
        try:
            prompt_context = getattr(self.context, "current_prompt_context", None)
            prompt_settings = getattr(prompt_context, "settings", {}) or {}
        except Exception:
            prompt_settings = {}
        is_auto_generate_prompt = bool(params.get("auto_generate")) or bool(
            prompt_settings.get("auto_generate")
        )
        if not is_auto_generate_prompt:
            return False

        bridge = getattr(self.context, "remote_bridge", None)
        getter = getattr(bridge, "is_remote_auto_generate_enabled", None)
        if not callable(getter):
            return False
        try:
            return bool(getter())
        except Exception:
            return False

    def _apply_remote_web_resolution_preset_default(self, params: dict) -> None:
        if not self._should_apply_remote_web_resolution_preset_default(params):
            return
        bridge = getattr(self.context, "remote_bridge", None)
        preset_getter = getattr(bridge, "get_resolution_preset_params", None)
        if not callable(preset_getter):
            return
        try:
            defaults = preset_getter(params.get("api_mode"))
        except Exception as e:
            print(f"⚠️ Remote Web 해상도 프리셋 설정 읽기 실패: {e}")
            return
        if not isinstance(defaults, dict):
            return
        if not defaults.get("resolution_preset_enabled"):
            return
        params.setdefault("resolution_preset_enabled", True)
        if "resolution_preset" in defaults:
            params.setdefault("resolution_preset", defaults["resolution_preset"])

    def _resolution_preset_labels_for_params(self, params: dict) -> list[str]:
        api_mode = str(params.get("api_mode") or "").strip().upper()
        if api_mode not in {"WEBUI", "COMFYUI"}:
            return []
        if not bool(params.get("resolution_preset_enabled")):
            return []
        return list(anima_resolution_preset_labels(params.get("resolution_preset")))

    def _apply_resolution_label_to_params(self, params: dict, label: str, *, update_combo: bool = False) -> bool:
        pair = parse_resolution_pair(label)
        if not pair:
            return False
        width, height = pair
        params["resolution"] = f"{width} x {height}"
        params["width"] = width
        params["height"] = height
        if update_combo:
            combo = getattr(self.context.main_window, "resolution_combo", None)
            if combo is not None:
                index = combo.findText(params["resolution"])
                if index >= 0:
                    combo.setCurrentIndex(index)
        return True

    def _has_active_detected_resolution(self, params: dict) -> bool:
        if not bool(params.get("auto_fit_resolution")):
            return False
        main_window = getattr(self.context, "main_window", None)
        if not bool(getattr(main_window, "resolution_is_detected", False)):
            return False
        detected = getattr(main_window, "detected_resolution_override", None)
        if not detected:
            return False
        try:
            width_raw, height_raw = detected
            width, height = int(width_raw), int(height_raw)
        except (TypeError, ValueError):
            return False
        return width > 0 and height > 0

    def _apply_resolution_preset_default(self, params: dict) -> None:
        if params.get("random_resolution") or self._has_active_detected_resolution(params):
            return
        if not self._resolution_preset_labels_for_params(params):
            return
        current_pair = parse_resolution_pair(params.get("resolution"))
        if current_pair in anima_resolution_preset_candidates(params.get("resolution_preset")):
            self._apply_resolution_label_to_params(params, f"{current_pair[0]} x {current_pair[1]}")
            return
        label = anima_resolution_preset_square_label(params.get("resolution_preset"))
        self._apply_resolution_label_to_params(params, label)

    def _apply_random_resolution(self, params: dict) -> None:
        if not params.get('random_resolution', False) or self._has_active_detected_resolution(params):
            return
        preset_labels = self._resolution_preset_labels_for_params(params)
        if preset_labels:
            selected_value = random.choice(preset_labels)
        else:
            random_index = random.randint(0, self.context.main_window.resolution_combo.count() - 1)
            self.context.main_window.resolution_combo.setCurrentIndex(random_index)
            selected_value = self.context.main_window.resolution_combo.currentText()
        if self._apply_resolution_label_to_params(params, selected_value):
            print(f"랜덤 해상도 설정: {params['width']}x{params['height']}")

    def _prepare_comfyui_workflow_with_wildcards(self, params: dict) -> bool:
        """
        🌉 ComfyUI 전용 브릿지: 와일드카드 확장 → 워크플로우 생성

        ComfyUI는 워크플로우에 프롬프트가 직접 삽입되므로,
        와일드카드 확장을 먼저 수행한 후 워크플로우를 생성해야 합니다.

        Args:
            params: 생성 파라미터 딕셔너리 (in-place 수정됨)

        Returns:
            bool: 성공 여부
        """
        try:
            # 1️⃣ 와일드카드 확장 (워크플로우 생성 전)
            if 'input' in params and params['input']:
                negative_prompt = params.get('negative_prompt', '')
                expanded_input, processed_negative_prompt = self._expand_wildcards_in_input(
                    params['input'],
                    negative_prompt
                )
                params['input'] = expanded_input
                params['negative_prompt'] = processed_negative_prompt

                print(f"🎲 [ComfyUI Bridge] 와일드카드 확장: '{params['input'][:50]}{'...' if len(params['input']) > 50 else ''}'")
                if processed_negative_prompt != negative_prompt:
                    print(f"➖ [ComfyUI Bridge] Negative prompt 업데이트: '{processed_negative_prompt[:50]}{'...' if len(processed_negative_prompt) > 50 else ''}'")

            # 2️⃣ 워크플로우 생성 (확장된 프롬프트 사용)
            final_workflow = self.workflow_manager.apply_params_to_workflow(params)
            if not final_workflow:
                self.context.main_window.status_bar.showMessage("❌ 워크플로우 생성에 실패했습니다. 로그를 확인하세요.")
                return False

            params['workflow'] = final_workflow
            workflow_ui = self.workflow_manager.get_last_applied_workflow_ui()
            if workflow_ui:
                params['_comfyui_workflow_ui'] = workflow_ui
            print(f"✅ [ComfyUI Bridge] 워크플로우 생성 완료 (와일드카드 확장 적용됨)")
            return True

        except Exception as e:
            print(f"❌ [ComfyUI Bridge] 오류 발생: {e}")
            self.context.main_window.status_bar.showMessage(f"❌ ComfyUI 워크플로우 준비 실패: {e}")
            return False

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
                sequence_overrides = overrides
                if overrides and overrides.get('_remote_web_session_params') and overrides.get('input'):
                    main_prompt_text = str(overrides.get('input') or '')
                    sequence_overrides = dict(overrides)
                    # _handle_sequence_generation injects each parsed prompt into
                    # params['input']; do not let the original Web prompt override it.
                    sequence_overrides.pop('input', None)
                    sequence_overrides.pop('_raw_input', None)
                    if not sequence_overrides.get('seed_fixed', False):
                        sequence_overrides.pop('seed', None)
                else:
                    main_prompt_text = self.context.main_window.main_prompt_textedit.toPlainText()

                if SequenceParser.is_sequence_prompt(main_prompt_text):
                    print("[SEQUENCE] 시퀀스 프롬프트 감지됨. 시퀀스 모드로 전환합니다.")
                    self._handle_sequence_generation(main_prompt_text, sequence_overrides, priority)
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
                event_stream = getattr(self.context, "event_stream_runtime", None)
                char_module = self.context.middle_section_controller.get_module_instance("CharacterModule")
                if (char_module and 
                    char_module.activate_checkbox.isChecked() and 
                    char_module.reroll_on_generate_checkbox.isChecked() and
                    not (event_stream and event_stream.should_freeze_character_prompts())):
                    
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

            self._apply_webui_hiresfix_assist_defaults(params)
            self._apply_remote_web_hires_preset_swap_default(params)
            self._apply_remote_web_resolution_preset_default(params)

            if overrides:
                print(f"🔄 Workshop 파라미터로 덮어쓰기: {list(overrides.keys())}")
                params.update(overrides)

            is_result_enhance_request = bool(params.get('result_enhance_request'))
            if not is_result_enhance_request:
                self._apply_resolution_preset_default(params)
                self._apply_random_resolution(params)

            # 자동 해상도 관리 해제
            self.context.main_window.resolution_is_detected = False

            img2img_params = {}
            if not is_result_enhance_request:
                img2img_params = self.context.main_window.img2img_panel.get_parameters()
            if img2img_params:
                print("🖼️ Img2Img 패널 활성화됨. 파라미터를 추가합니다.")
                params.update(img2img_params)

            is_valid, error_msg = self.validate_parameters(params)
            if not is_valid:
                self.context.main_window.status_bar.showMessage(f"⚠️ 유효성 검사 실패: {error_msg}")
                return

            # --- ComfyUI vs NAI/WEBUI 처리 분기 ---
            if api_mode == "COMFYUI":
                # Studio 요청 시 ComfyUI 파라미터 디버그 로깅
                if params.get('studio_request'):
                    print(f"🎬 [Studio+ComfyUI] 파라미터 덤프:")
                    print(f"   - prompt: {params.get('input', '')[:80]}...")
                    print(f"   - negative: {params.get('negative_prompt', '')[:60]}...")
                    print(f"   - model: {params.get('model')}")
                    print(f"   - sampling_mode: {params.get('sampling_mode', 'NOT SET')}")
                    print(f"   - workflow_type: {params.get('workflow_type', 'NOT SET')}")
                    print(f"   - steps: {params.get('steps')}, cfg: {params.get('cfg_scale')}")
                    print(f"   - sampler: {params.get('sampler')}, scheduler: {params.get('scheduler')}")
                    print(f"   - resolution: {params.get('width')}x{params.get('height')}")
                    print(f"   - seed: {params.get('seed')}")
                    print(f"   - user_workflow active: {bool(self.workflow_manager.user_workflow)}")

                # 🌉 ComfyUI: 브릿지 사용 (와일드카드 확장 → 워크플로우 생성)
                if not self._prepare_comfyui_workflow_with_wildcards(params):
                    return  # 실패 시 조기 종료
            else:
                # 🎲 NAI/WEBUI: 와일드카드 확장만 수행
                if 'input' in params and params['input']:
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

            # --- 🆕 FR-3: 임시 창 프롬프트 엔지니어링 훅 수동 실행 (모든 모드 공통) ---
            if 'input' in params and 'temp_window_prompt_engineering_tab' in params:
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

                    # tags 파싱 (쉼표로 분리, <...> 블록 보존)
                    input_tags = split_tags_smart(params['input'])

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

            if not self._apply_vibe_cluster_prompt_override(params):
                return

            # 와일드카드 상태 모듈 업데이트를 위한 이벤트 발행
            if self.context.current_prompt_context:
                self.context.publish("prompt_generated", self.context.current_prompt_context)

            # --- 5. 스레드에서 API 호출 시작 ---
            self._start_threaded_generation(params, source_row)

        except Exception as e:
            self.context.main_window.status_bar.showMessage(f"❌ 생성 준비 오류: {e}")
            print(f"오류 발생: {e}")

            # Studio 요청 실패 시 프레임 매니저에 알림
            if overrides and overrides.get('studio_request'):
                error_data = {
                    "message": str(e),
                    "studio_request": True,
                    "studio_frame_index": overrides.get('studio_frame_index', 0)
                }
                self.context.publish("generation_error_for_studio", error_data)

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

            self._apply_resolution_preset_default(params)
            self._apply_random_resolution(params)

            if not self._apply_vibe_cluster_prompt_override(params):
                return

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
        if self.generation_thread is not None:
            try:
                if self.generation_thread.isRunning():
                    print("[QUEUE] 이미 생성 중입니다. 디스패처 대기.")
                    return
            except RuntimeError:
                # 스레드 객체가 이미 삭제된 경우 - 참조 정리 후 계속
                self.generation_thread = None

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
        self.context.publish("queue_request_started", {
            "request_id": next_request.request_id,
            "priority": next_request.priority,
            "queue_size": queue_manager.get_queue_size()
        })

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
        # 🆕 안전장치 0: 앱 종료 중이면 새 생성 차단
        if self._thread_cleanup_in_progress:
            print("⚠️ [THREAD] 앱 종료 중입니다. 새 생성이 차단됩니다.")
            return

        # 🆕 안전장치 1: 이전 스레드가 아직 실행 중인지 확인
        if self.generation_thread is not None:
            if self.generation_thread.isRunning():
                print("⚠️ [THREAD] 이전 스레드가 아직 실행 중입니다. 안전하게 종료를 기다립니다...")
                # 최대 5초 대기 (긴급 상황에서 무한 대기 방지)
                if not self.generation_thread.wait(5000):
                    print("❌ [THREAD] 이전 스레드 종료 대기 시간 초과. 강제 종료 시도...")
                    self.generation_thread.terminate()
                    self.generation_thread.wait(1000)

            # 🆕 안전장치 2: 이전 참조를 정리 대기 목록에 추가 (GC가 나중에 정리)
            if self.generation_thread is not None:
                self._pending_thread_refs.append(self.generation_thread)
            if self.generation_worker is not None:
                self._pending_thread_refs.append(self.generation_worker)

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
        # 🆕 안전장치 3: finished 시그널에서 먼저 _on_thread_finished를 호출하고, 그 후에 deleteLater 처리
        self.generation_thread.finished.connect(self._on_thread_finished)
        # deleteLater는 _on_thread_finished 내부에서 지연 호출로 처리 (아래 참조 해제 후)

        # 파라미터 설정 및 스레드 시작
        self.current_generation_params = params  # 🆕 현재 생성 파라미터 저장
        self.generation_worker.set_generation_params(params, source_row)

        # 🔧 FIX: 메인 스레드에서 main_prompt 텍스트 캡처 (워커에서 크로스 스레드 UI 접근 방지)
        # Per-request overrides로 주입된 프롬프트는 _raw_input에 원본 보존
        try:
            raw_input = params.pop('_raw_input', None)
            if raw_input is not None:
                self.generation_worker._main_prompt_text = raw_input
            elif hasattr(self.context, 'main_window') and hasattr(self.context.main_window, 'main_prompt_textedit'):
                self.generation_worker._main_prompt_text = self.context.main_window.main_prompt_textedit.toPlainText()
        except Exception:
            pass

        # 🔧 메인 스레드에서 캐릭터 프롬프트 캡처 (NAI 모드, 결과 메타데이터용)
        try:
            if params.get('api_mode') == 'NAI':
                char_prompts = []
                if params.get('sketchbook_character_prompts'):
                    # Sketchbook/Img2ImgWindow 오버라이드 (tuple 또는 dict)
                    for item in params['sketchbook_character_prompts']:
                        if isinstance(item, tuple):
                            char_prompts.append({'prompt': item[0], 'uc': item[1]})
                        elif isinstance(item, dict):
                            char_prompts.append(item)
                elif params.get('characters'):
                    # Saved Params (Enhance 등 재사용)
                    p_ucs = params.get('uc', [])
                    for i, p in enumerate(params['characters']):
                        char_prompts.append({'prompt': p, 'uc': p_ucs[i] if i < len(p_ucs) else ''})
                elif hasattr(self.context, 'main_window') and hasattr(self.context.main_window, 'middle_section_controller'):
                    # 메인 UI CharacterModule (Late Binding)
                    char_module = self.context.main_window.middle_section_controller.get_module_instance("CharacterModule")
                    if char_module and hasattr(char_module, 'character_widgets'):
                        for w in char_module.character_widgets:
                            if w.active_checkbox.isChecked():
                                char_prompts.append({
                                    'prompt': w.prompt_textbox.toPlainText(),
                                    'uc': w.uc_textbox.toPlainText(),
                                })
                self.generation_worker._character_prompts = char_prompts
        except Exception:
            pass

        # 📌 메인 스레드에서 scoped wildcard history 캡처 (최대 1개)
        # 안전장치: 재귀 와일드카드 등으로 최종 프롬프트에 없는 값은 skip
        try:
            ctx = self.context.current_prompt_context
            scoped_key = self.context.scoped_wildcard
            if ctx and ctx.wildcard_history and scoped_key and scoped_key in ctx.wildcard_history:
                value = ctx.wildcard_history[scoped_key][-1]
                final_prompt = params.get('input', '')
                char_prompts_str = ' '.join(params.get('characters', []))
                if value in final_prompt or value in char_prompts_str:
                    self.generation_worker._scoped_wildcard_history = {scoped_key: value}
                else:
                    self.generation_worker._scoped_wildcard_history = {}
            else:
                self.generation_worker._scoped_wildcard_history = {}
        except Exception:
            self.generation_worker._scoped_wildcard_history = {}

        # 📌 메인 스레드에서 WEBUI Hires Preset Swap 사전 계산.
        # 워커 스레드의 api_service 는 결과 문자열만 읽어 payload 에 통과시키므로
        # 파이프라인 훅의 UI 위젯 접근을 메인 스레드로 한정한다.
        try:
            self._apply_hires_preset_swap(params)
        except Exception as e:
            print(f"⚠️ [HIRES SWAP] 사전 계산 중 예외 — 스왑 없이 진행: {e}")

        self.generation_thread.start()

    # ------------------------------------------------------------
    # WEBUI Hires Preset Swap
    # ------------------------------------------------------------
    @staticmethod
    def _sanitize_prompt_for_api(text: str) -> str:
        """
        파이프라인 산출물의 `\\n\\n` 구분자 마커 / `#` 주석 토큰을 제거하고
        콤마-스페이스 단일 구분자로 정규화한다.

        `core.api_service.call_generation_api()` 가 메인 `parameters['input']` 에
        대해 수행하는 정리와 동일한 규칙. `hr_prompt` / `hr_negative_prompt` 는
        api_service 의 정리 경로를 타지 않으므로 호출부(여기)에서 직접 적용한다.
        """
        if not isinstance(text, str):
            return ''
        cleaned: list[str] = []
        for raw_tag in text.split(','):
            tag = raw_tag.replace('\n', '').strip()
            if not tag or tag.startswith('#'):
                continue
            cleaned.append(tag)
        return ', '.join(cleaned)

    def _apply_hires_preset_swap(self, params: dict) -> None:
        """
        WEBUI Hires.fix 단계에서만 사용될 hr_prompt / hr_negative_prompt 를
        메인 패스와 동일한 source_row + 동일한 와일드카드 선택값으로 다른 프리셋을
        적용해 사전 생성한다. 워커는 결과 문자열만 payload 에 실어 보낸다.

        스왑 적용 조건:
            - WEBUI 모드 + enable_hr + img2img 아님 + hires_preset_swap 비어있지 않음
            - current_prompt_context 가 살아있고 wildcard_history 가 캡처되어 있음
            - PyQt-free prompt_generation_service 접근 가능
            - 프리셋 파일 존재
        """
        swap_name = str(params.get('hires_preset_swap') or '').strip()
        if not swap_name:
            return
        if str(params.get('api_mode') or '').upper() != 'WEBUI':
            return
        if not bool(params.get('enable_hr')):
            return
        if params.get('image_bytes'):
            # img2img / inpaint 는 Hires 비대상.
            return

        ctx = getattr(self.context, 'current_prompt_context', None)
        if ctx is None or ctx.source_row is None:
            print("⚠️ [HIRES SWAP] current_prompt_context 미존재 — 스왑 스킵")
            return

        prompt_gen = getattr(self.context, 'prompt_generation_service', None)
        if prompt_gen is None:
            try:
                from core.prompt_generation_service import PromptGenerationService
                prompt_gen = PromptGenerationService(self.context)
                self.context.prompt_generation_service = prompt_gen
            except Exception as e:
                print(f"⚠️ [HIRES SWAP] prompt_generation_service 접근 불가 — 스왑 스킵 ({e})")
                return

        api_mode = self.context.get_api_mode() or 'WEBUI'
        preset_path = Path('save') / 'presets' / api_mode / f"{swap_name}.json"
        if not preset_path.exists():
            print(f"⚠️ [HIRES SWAP] 프리셋 파일 없음: {preset_path}")
            return

        try:
            preset_data = json.loads(preset_path.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"⚠️ [HIRES SWAP] 프리셋 파싱 실패 ({swap_name}): {e}")
            return

        module_settings = preset_data.get('module_settings') or {}
        main_settings = preset_data.get('main_settings') or {}

        # session_p_eng_override 페이로드 — prompt_engineering_module 의 훅이 UI 대신 읽음.
        peng_payload = {
            'pre_prompt': module_settings.get('pre_prompt', ''),
            'post_prompt': module_settings.get('post_prompt', ''),
            'auto_hide': module_settings.get('auto_hide_prompt', ''),
            'preprocessing_options': dict(module_settings.get('preprocessing_options') or {}),
        }

        # 네거티브는 파이프라인 외부값. 프리셋의 main_settings 에서 추출 (sidecar 가 덮어쓸 수 있음).
        preset_negative = main_settings.get('negative') or main_settings.get('negative_prompt') or ''

        # Hires overlay sidecar — `<preset>.hires.json` 이 있으면 prefix/postfix/negative 3 필드를 갈음.
        # 의미: sidecar 존재 = 사용자가 명시적으로 편집한 것. 빈 문자열도 의도된 값.
        # 부재 = 원본 프리셋 그대로.
        sidecar_path = preset_path.with_suffix('.hires.json')
        if sidecar_path.exists():
            try:
                overlay = json.loads(sidecar_path.read_text(encoding='utf-8'))
                if isinstance(overlay, dict):
                    peng_payload['pre_prompt'] = str(overlay.get('prefix_prompt', ''))
                    peng_payload['post_prompt'] = str(overlay.get('postfix_prompt', ''))
                    preset_negative = str(overlay.get('negative_prompt', ''))
                    print(f"🧩 [HIRES SWAP] '{swap_name}' overlay 적용 ({sidecar_path.name})")
            except Exception as e:
                print(f"⚠️ [HIRES SWAP] overlay 파싱 실패 ({sidecar_path.name}): {e}")

        # wildcard_override (list-consumable) — 메인 패스의 선택값을 그대로 재현.
        wc_override_payload = {
            key: list(values)
            for key, values in (ctx.wildcard_history or {}).items()
            if values
        }

        saved_peng = getattr(self.context, 'session_p_eng_override', None)
        saved_wco = copy.deepcopy(getattr(self.context, 'wildcard_override', {}) or {})
        try:
            self.context.session_p_eng_override = peng_payload
            self.context.wildcard_override = wc_override_payload

            silent_settings = dict(ctx.settings or {})
            silent_settings.setdefault('api_mode', api_mode)

            source_row_dict = ctx.source_row.to_dict()
            silent_prompt = prompt_gen.generate_instant_source_silent(source_row_dict, silent_settings)

            if isinstance(silent_prompt, str) and silent_prompt.strip():
                sanitized = self._sanitize_prompt_for_api(silent_prompt)
                if sanitized:
                    params['hr_prompt'] = sanitized
                    print(
                        f"🧩 [HIRES SWAP] '{swap_name}' 프리셋으로 hr_prompt 생성 "
                        f"({len(silent_prompt)} → {len(sanitized)} chars, sanitized)"
                    )
                else:
                    print(f"⚠️ [HIRES SWAP] sanitize 후 빈 문자열 — hr_prompt 미설정")
            else:
                print(f"⚠️ [HIRES SWAP] silent 생성 결과 비어있음 — hr_prompt 미설정")

            # 네거티브는 파이프라인 외부값. 비어있지 않을 때만 통과. `\n\n` 마커가
            # 끼어들 가능성은 낮지만, 사용자가 textarea 줄바꿈으로 작성했을 수 있으므로
            # 동일 cleanup 으로 정규화한다.
            if isinstance(preset_negative, str) and preset_negative.strip():
                sanitized_neg = self._sanitize_prompt_for_api(preset_negative)
                if sanitized_neg:
                    params['hr_negative_prompt'] = sanitized_neg
        finally:
            self.context.session_p_eng_override = saved_peng
            self.context.wildcard_override = saved_wco

    def _on_generation_started(self):
        """생성 시작 시 호출되는 슬롯"""
        self.is_generating = True
        self.context.publish("generation_started", {})
        # 🆕 버튼 비활성화 제거 - 큐에 추가할 수 있도록 활성 상태 유지
        # self.context.main_window.generate_button_main.setEnabled(False)

        # 🆕 큐 크기를 반영한 버튼 텍스트 업데이트
        self._update_button_with_queue_size()

        self.context.main_window.status_bar.showMessage("🚀 생성 시작...")
    
    def _on_generation_progress(self, message: str):
        """생성 진행 상황 업데이트 슬롯 (메인 스레드에서 실행)"""
        self.context.main_window.status_bar.showMessage(message)

        # 🔧 메인 스레드에서 안전하게 generation_progress 이벤트 발행 (Interactive Mode 등)
        if self.generation_worker and hasattr(self.generation_worker, '_pending_progress_data'):
            data = self.generation_worker._pending_progress_data
            if data:
                self.context.publish("generation_progress", data)
    
    def _on_generation_finished(self, result: dict):
        """생성 완료 시 호출되는 슬롯"""
        # 🆕 성공 시 재시도 카운터 리셋
        self.auto_retry_count = 0
        if isinstance(self.current_generation_params, dict):
            current_request = self.current_generation_params.get("_generation_request")
            if current_request:
                current_request.mark_completed()
                self.context.publish("queue_request_completed", {
                    "request_id": current_request.request_id,
                    "priority": current_request.priority
                })
        # 🆕 현재 생성 파라미터 정리
        self.current_generation_params = None
        # Per-request P.Eng/Conditional 오버라이드 정리
        self.context.session_p_eng_override = None
        self.context.session_cond_override = None

        self.context.publish("generation_finished", result)

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
        self.context.publish("generation_failed", {"message": error_message})
        if isinstance(self.current_generation_params, dict):
            current_request = self.current_generation_params.get("_generation_request")
            if current_request:
                current_request.mark_failed(error_message)
                self.context.publish("queue_request_failed", {
                    "request_id": current_request.request_id,
                    "priority": current_request.priority,
                    "error": error_message
                })
        # Per-request P.Eng/Conditional 오버라이드 정리
        self.context.session_p_eng_override = None
        self.context.session_cond_override = None

        # 특수 요청 에러 라우팅
        if self.current_generation_params:
            is_result_enhance = self.current_generation_params.get("result_enhance_request", False)
            if is_result_enhance:
                print("📈 Result Enhance 에러 감지 - 전용 에러 이벤트 발행")
                self.context.publish("generation_error", {
                    "message": error_message,
                    "result_enhance_request": True,
                    "result_enhance_request_id": str(
                        self.current_generation_params.get("result_enhance_request_id") or ""
                    ),
                })
                self.current_generation_params = None
                return

            # Composite Remote Preset 요청인 경우 전용 에러 이벤트 발행
            is_remote_preset = self.current_generation_params.get("remote_preset_request", False)
            if is_remote_preset:
                print(f"📋 Remote Preset 에러 감지 - 전용 에러 이벤트 발행")
                remote_preset_axes = self.current_generation_params.get("remote_preset_axes") or []
                if isinstance(remote_preset_axes, str):
                    remote_preset_axes = [item.strip() for item in remote_preset_axes.split(",") if item.strip()]
                error_data = {
                    "message": error_message,
                    "remote_preset_request": True,
                    "remote_preset_request_id": str(
                        self.current_generation_params.get("remote_preset_request_id") or ""
                    ),
                    "remote_preset_axes": list(remote_preset_axes),
                }
                self.context.publish("generation_error", error_data)
                self.current_generation_params = None
                return

            # Event Preset 요청인 경우 전용 에러 이벤트 발행
            is_event_preset = self.current_generation_params.get("event_preset_request", False)
            if is_event_preset:
                print(f"📋 Event Preset 에러 감지 - 전용 에러 이벤트 발행")
                error_data = {
                    "message": error_message,
                    "event_preset_request": True,
                    "event_preset_request_id": str(
                        self.current_generation_params.get("event_preset_request_id") or ""
                    ),
                }
                self.context.publish("generation_error", error_data)
                self.current_generation_params = None
                return

            # Clothes Preset 요청인 경우 전용 에러 이벤트 발행
            is_clothes_preset = self.current_generation_params.get("clothes_preset_request", False)
            if is_clothes_preset:
                print(f"👗 Clothes Preset 에러 감지 - 전용 에러 이벤트 발행")
                error_data = {
                    "message": error_message,
                    "clothes_preset_request": True
                }
                self.context.publish("generation_error", error_data)
                self.current_generation_params = None
                return

            # Character Viewer 요청인 경우 전용 에러 이벤트 발행
            is_character_viewer = self.current_generation_params.get("character_viewer_request", False)
            if is_character_viewer:
                print(f"🔍 Character Viewer 에러 감지 - 전용 에러 이벤트 발행")
                error_data = {
                    "message": error_message,
                    "character_viewer_request": True
                }
                self.context.publish("generation_error", error_data)
                self.current_generation_params = None
                return

            # Interactive Mode 요청인 경우 전용 에러 이벤트 발행
            is_interactive_mode = self.current_generation_params.get("interactive_mode_request", False)
            if is_interactive_mode:
                print(f"🎨 Interactive Mode 에러 감지 - 전용 에러 이벤트 발행")
                error_data = {
                    "message": error_message,
                    "interactive_mode_request": True
                }
                self.context.publish("generation_error", error_data)
                # Interactive Mode 요청은 재시도 없이 종료
                self.current_generation_params = None
                return

            # 🆕 Turbo Sequence 요청인 경우 전용 에러 이벤트 발행
            is_turbo_sequence = self.current_generation_params.get("turbo_sequence_request", False)
            if is_turbo_sequence:
                turbo_index = self.current_generation_params.get("turbo_sequence_index", 0)
                print(f"🚀 Turbo Sequence 에러 감지 - 전용 에러 이벤트 발행 (index: {turbo_index})")
                # 🆕 에러 이벤트 데이터 구성
                error_data = {
                    "message": error_message,
                    "turbo_sequence_request": True,
                    "turbo_sequence_index": turbo_index
                }
                # 인페인트 다이얼로그에서 온 요청인 경우 식별자 추가
                if self.current_generation_params.get("sequence_inpaint_dialog"):
                    error_data["sequence_inpaint_dialog"] = True
                    error_data["sequence_inpaint_request_id"] = self.current_generation_params.get("sequence_inpaint_request_id")
                self.context.publish("generation_error", error_data)
                # Turbo Sequence 요청은 자동 재시도 없이 종료
                self.current_generation_params = None
                return

            # Character Asset 요청인 경우 전용 에러 이벤트 발행
            is_character_asset_request = self.current_generation_params.get("character_asset_request", False)
            if is_character_asset_request:
                request_id = self.current_generation_params.get("character_asset_request_id")
                print(f"🧷 Character Asset 에러 감지 - 전용 에러 이벤트 발행 (request_id: {request_id})")
                error_data = {
                    "message": error_message,
                    "character_asset_request": True,
                    "character_asset_request_id": request_id,
                }
                self.context.publish("generation_error", error_data)
                self.current_generation_params = None
                return


            # Studio 요청인 경우: 프레임 매니저에 실패 알림
            is_studio_request = self.current_generation_params.get("studio_request", False)
            if is_studio_request:
                studio_frame_index = self.current_generation_params.get("studio_frame_index", 0)
                print(f"🎬 Studio 에러 감지 - 프레임 #{studio_frame_index + 1} 실패 알림")
                error_data = {
                    "message": error_message,
                    "studio_request": True,
                    "studio_frame_index": studio_frame_index
                }
                self.context.publish("generation_error_for_studio", error_data)
                self.current_generation_params = None
                return

            # Img2Img 요청 에러 처리
            is_img2img_batch = self.current_generation_params.get("img2img_batch_request", False)
            img2img_window_id = self.current_generation_params.get("img2img_batch_window_id")
            if is_img2img_batch:
                print(f"🔄 Img2Img Batch 에러 (window #{img2img_window_id}) - 배치 계속 진행")
                main_window = self.context.main_window
                if hasattr(main_window, 'img2img_window_manager'):
                    main_window.img2img_window_manager.on_batch_generation_completed(img2img_window_id)
                self.current_generation_params = None
                return
            elif img2img_window_id is not None:
                # 단일 img2img 에러 → 버튼 복원 (이후 일반 에러 처리 계속)
                main_window = self.context.main_window
                if hasattr(main_window, 'img2img_window_manager'):
                    main_window.img2img_window_manager.on_single_generation_completed(img2img_window_id)

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

            self.context.publish("generation_error", {"message": error_message})
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
                # 🔧 ComfyUI 샘플링 모드 감지 (라디오 버튼에서 직접 읽기)
                main_win = self.context.main_window
                comfyui_sampling_mode = "eps"  # 기본값
                if hasattr(main_win, 'anima_radio') and main_win.anima_radio.isChecked():
                    comfyui_sampling_mode = "anima"
                elif hasattr(main_win, 'v_pred_radio') and main_win.v_pred_radio.isChecked():
                    comfyui_sampling_mode = "v_prediction"
                elif hasattr(main_win, 'eps_radio') and main_win.eps_radio.isChecked():
                    comfyui_sampling_mode = "eps"

                settings = {
                    'prompt_fixed': False,
                    'auto_generate': True,
                    'turbo_mode': self.context.main_window.generation_checkboxes["터보 옵션"].isChecked(),
                    'wildcard_standalone': self.context.main_window.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
                    "auto_fit_resolution": self.context.main_window.auto_fit_resolution_checkbox.isChecked(),
                    'api_mode': self.context.get_api_mode(),  # 🆕 ANIMA 모드 감지를 위해 추가
                    'comfyui_sampling_mode': comfyui_sampling_mode  # 🔧 라디오 버튼에서 직접 읽기
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
        """스레드 완료 시 정리 작업 - 🆕 안전한 스레드 정리 로직"""
        # 🆕 안전한 스레드 정리: 참조를 먼저 로컬 변수에 저장
        thread_to_cleanup = self.generation_thread
        worker_to_cleanup = self.generation_worker

        # 🆕 참조 해제를 먼저 수행 (새 스레드 생성에 영향 없도록)
        self.generation_thread = None
        self.generation_worker = None

        # 🔧 스레드 정리 함수 (지연 실행) - 별도 플래그 없이 안전하게 처리
        def _safe_cleanup():
            try:
                # 워커 정리
                if worker_to_cleanup is not None:
                    try:
                        # 워커가 아직 실행 중인지 확인
                        if hasattr(worker_to_cleanup, '_is_running') and worker_to_cleanup._is_running:
                            print("⚠️ [THREAD] 워커가 아직 실행 중입니다. 대기...")
                            QCoreApplication.processEvents()
                        worker_to_cleanup.deleteLater()
                    except RuntimeError as e:
                        # "wrapped C/C++ object has been deleted" 오류 무시
                        print(f"[THREAD] 워커 이미 삭제됨: {e}")
                    except Exception as e:
                        print(f"[THREAD] 워커 정리 오류: {e}")

                # 스레드 정리
                if thread_to_cleanup is not None:
                    try:
                        # 스레드가 아직 실행 중인지 확인
                        if thread_to_cleanup.isRunning():
                            print("⚠️ [THREAD] 스레드가 아직 실행 중입니다. 대기...")
                            thread_to_cleanup.wait(500)  # 최대 500ms 대기
                        thread_to_cleanup.deleteLater()
                    except RuntimeError as e:
                        print(f"[THREAD] 스레드 이미 삭제됨: {e}")
                    except Exception as e:
                        print(f"[THREAD] 스레드 정리 오류: {e}")

                # 정리 대기 목록에서 오래된 참조 제거 (최대 10개 유지)
                while len(self._pending_thread_refs) > 10:
                    old_ref = self._pending_thread_refs.pop(0)
                    try:
                        if hasattr(old_ref, 'deleteLater'):
                            old_ref.deleteLater()
                    except Exception:
                        pass

                # 강력한 스레드 정리 실행
                _force_cleanup_all_threads()

            except Exception as e:
                print(f"[THREAD] 정리 중 예외 발생: {e}")

        # 🆕 안전장치: 지연 실행으로 이벤트 루프에서 안전하게 처리
        QTimer.singleShot(100, _safe_cleanup)

        # Per-request P.Eng/Conditional 오버라이드 안전망 (cancel 등으로 finished/error 콜백 누락 시)
        if getattr(self.context, 'session_p_eng_override', None) is not None:
            self.context.session_p_eng_override = None
        if getattr(self.context, 'session_cond_override', None) is not None:
            self.context.session_cond_override = None

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
                was_holding = self.queue_hold_auto_gen
                if was_holding:
                    print("[QUEUE] 큐 비었음. 자동생성 보류 해제.")
                self.queue_hold_auto_gen = False

                # 보류 중인 자동 재시도 수행 (에러 후 재시도)
                if self.auto_retry_pending:
                    self.auto_retry_pending = False
                    print("[AUTO] 보류된 자동 재시도 실행.")
                    QTimer.singleShot(0, self._retry_auto_generation)
                elif was_holding:
                    # 큐 처리 완료 후 자동생성 복귀: 자동생성이 켜져 있으면 재개
                    auto_gen_cb = self.context.main_window.generation_checkboxes.get("자동 생성")
                    if auto_gen_cb and auto_gen_cb.isChecked():
                        print("[AUTO] 큐 처리 완료. 자동생성 복귀.")
                        QTimer.singleShot(0, self.context.main_window._check_and_trigger_auto_generation)

            # UI 상태 업데이트
            self._update_button_with_queue_size()
            self.context.publish("queue_state_changed", {"reason": "thread_finished"})

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

            for tag in split_tags_smart(input_text):
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

            input_tags = self._expand_preset_tokens_in_tags(cleaned_tags, prompt_context)

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

    def _expand_preset_tokens_in_tags(self, tags: list[str], prompt_context) -> list[str]:
        """Expand preset shortcut tokens before the regular wildcard pass."""
        if not tags:
            return tags
        expanded: list[str] = []
        bridge = getattr(self, "_preset_input_bridge", None)
        service_key = None
        service_kwargs = {}
        preset_context = None
        try:
            from core.preset_input_bridge import preset_context_from_prompt, preset_service_kwargs

            service_kwargs = preset_service_kwargs(self.context)
            service_key = tuple(id(service_kwargs.get(key)) for key in ("event_service", "clothes_service", "expression_service"))
            preset_context = preset_context_from_prompt(self.context, prompt_context, tags=tags)
        except Exception as exc:
            print(f"⚠️ Preset context 계산 실패: {exc}")

        if bridge is None or (
            service_key is not None
            and getattr(self, "_preset_bridge_service_key", service_key) != service_key
        ):
            try:
                from core.preset_input_bridge import PresetInputBridge

                bridge = PresetInputBridge(
                    Path(__file__).resolve().parent.parent,
                    **service_kwargs,
                    context=preset_context,
                )
                self._preset_input_bridge = bridge
                self._preset_bridge_service_key = service_key
            except Exception as exc:
                print(f"⚠️ Preset token bridge 초기화 실패: {exc}")
                return tags
        elif preset_context is not None and hasattr(bridge, "set_context"):
            bridge.set_context(preset_context)

        for tag in tags:
            token = str(tag or "").strip()
            if not token.lower().startswith("preset:"):
                expanded.append(tag)
                continue
            try:
                result = bridge.resolve_prompt_token(token)
                if hasattr(prompt_context, "metadata"):
                    prompt_context.metadata.setdefault("preset_prompt_resolutions", []).append(result)
                if result.get("applied"):
                    expanded.extend(str(item).strip() for item in result.get("tags") or [] if str(item).strip())
                else:
                    expanded.append(tag)
            except Exception as exc:
                print(f"⚠️ Preset token 확장 실패 ({token}): {exc}")
                expanded.append(tag)
        return expanded

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
            
            # 입력 문자열을 태그 리스트로 분해 (<...> 블록 보존)
            input_tags = split_tags_smart(input_text)
            
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

            # 4. 해상도 결정
            fixed_resolution = self._determine_fixed_resolution(prompt_sets[0])
            print(f"[SEQUENCE] 고정 해상도: {fixed_resolution[0]}x{fixed_resolution[1]}")

            # 5. 공통 구간 와일드카드 고정
            base_params = self._collect_generation_params()
            if overrides and 'negative_prompt' in overrides:
                base_params['negative_prompt'] = overrides['negative_prompt']
            parsed = self._expand_sequence_static_sections(parsed, base_params)
            prompt_sets = SequenceParser.generate_prompt_sets(parsed)

            # 디버깅: 실제 큐에 들어갈 프롬프트 출력
            for i, prompt in enumerate(prompt_sets, 1):
                print(f"[SEQUENCE] #{i}: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")

            # 6. 큐에 일괄 추가
            print("[SEQUENCE] 큐에 요청 추가 중...")
            self._enqueue_sequence_requests(prompt_sets, fixed_resolution, overrides, priority, base_params)

            # 7. 상태바 업데이트
            self.context.main_window.status_bar.showMessage(
                f"✅ 시퀀스 생성: {len(prompt_sets)}개 요청이 큐에 추가되었습니다."
            )

            # 8. 큐 처리 시작
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

    def _expand_sequence_static_sections(self, parsed: dict, base_params: dict) -> dict:
        """
        시퀀스 공통 구간(prefix/begin/end)의 와일드카드를 큐 등록 전에 한 번만 확장합니다.

        :seq 내부 와일드카드는 각 프레임에서 의도적으로 바뀔 수 있도록 남겨둡니다.
        """
        expanded = dict(parsed)
        negative_prompt = base_params.get('negative_prompt', '')

        for section in ("prefix", "begin", "end"):
            text = expanded.get(section, "")
            if not text:
                continue
            expanded_text, negative_prompt = self._expand_wildcards_in_input(text, negative_prompt)
            expanded[section] = expanded_text

        base_params['negative_prompt'] = negative_prompt
        return expanded

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
        priority: int = 0,
        base_params: dict = None
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
        if base_params is None:
            base_params = self._collect_generation_params()

        # 🆕 API 모드 확인 (시드 처리 분기용)
        api_mode = base_params.get('api_mode', 'NAI')
        if overrides and 'seed_fixed' in overrides:
            seed_is_fixed = bool(overrides.get('seed_fixed'))
        else:
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

                # TODO: 시퀀스 생성에서도 cfg_scale:, cfg_rescale:, sampler:, scheduler: 인라인 파라미터 지원 예정
                # 참고: api_service.py의 call_generation_api()에 구현된 파싱 로직 참조

                # 해상도 설정 (고정)
                params['width'] = fixed_resolution[0]
                params['height'] = fixed_resolution[1]

                # 덮어쓰기 적용
                sequence_input = prompt
                sequence_negative_prompt = params.get('negative_prompt')
                if overrides:
                    params.update(overrides)
                params['input'] = sequence_input
                if sequence_negative_prompt is not None:
                    params['negative_prompt'] = sequence_negative_prompt

                if not self._apply_vibe_cluster_prompt_override(params):
                    continue

                # ✅ Phase 2: 프롬프트별 NAI 데이터 추출 (vibe:name override 포함)
                nai_characters, nai_vibe_transfer, nai_character_reference = self._extract_nai_data(params)

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
            event_stream = getattr(self.context, "event_stream_runtime", None)
            char_module = self.context.middle_section_controller.get_module_instance("CharacterModule")
            if (char_module and
                char_module.activate_checkbox.isChecked() and
                char_module.reroll_on_generate_checkbox.isChecked() and
                not (event_stream and event_stream.should_freeze_character_prompts())):
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

        self._apply_webui_hiresfix_assist_defaults(params)
        self._apply_remote_web_hires_preset_swap_default(params)
        self._apply_remote_web_resolution_preset_default(params)

        self._apply_resolution_preset_default(params)
        self._apply_random_resolution(params)

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
                workflow_ui = self.workflow_manager.get_last_applied_workflow_ui()
                if workflow_ui:
                    params['_comfyui_workflow_ui'] = workflow_ui

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
                try:
                    nai_vibe_transfer = NAIVibeTransferData.from_params(params)
                    if nai_vibe_transfer:
                        print(f"✅ [EarlyBinding] Vibe Transfer Data 캡처: {len(nai_vibe_transfer.reference_image_multiple)}개")
                except ValueError as e:
                    if params.get('_vibe_cluster_override'):
                        print(f"⚠️ [EarlyBinding] Vibe cluster는 API 단계에서 직접 적용: {e}")
                    else:
                        raise

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

    def _apply_vibe_cluster_prompt_override(self, params: dict) -> bool:
        try:
            result = apply_vibe_cluster_prompt_override(params)
        except VibeClusterPromptError as e:
            message = str(e)
            print(f"⚠️ [VibeCluster] {message}")
            self.context.main_window.status_bar.showMessage(f"❌ {message}")
            return False
        except Exception as e:
            message = f"Vibe cluster override failed: {e}"
            print(f"❌ [VibeCluster] {message}")
            self.context.main_window.status_bar.showMessage(f"❌ {message}")
            return False
        if result.applied:
            print(f"✅ [VibeCluster] prompt override: {result.cluster_name} ({result.frame_count} frame(s))")
        return True

    def safe_shutdown(self, timeout_ms: int = 5000):
        """
        🆕 앱 종료 시 안전하게 스레드를 정리합니다.

        Args:
            timeout_ms: 스레드 종료 대기 시간 (밀리초)
        """
        print("[THREAD] 안전 종료 시작...")

        # 1. 생성 플래그 해제
        self.is_generating = False
        self._thread_cleanup_in_progress = True  # 새 작업 방지

        # 2. 현재 스레드 종료 대기
        if self.generation_thread is not None:
            try:
                if self.generation_thread.isRunning():
                    print(f"[THREAD] 실행 중인 스레드 종료 대기 중... (최대 {timeout_ms}ms)")
                    self.generation_thread.quit()
                    if not self.generation_thread.wait(timeout_ms):
                        print("⚠️ [THREAD] 스레드 정상 종료 실패. 강제 종료 시도...")
                        self.generation_thread.terminate()
                        self.generation_thread.wait(1000)
                print("[THREAD] 스레드 종료 완료")
            except RuntimeError as e:
                print(f"[THREAD] 스레드 이미 삭제됨: {e}")
            except Exception as e:
                print(f"[THREAD] 스레드 종료 중 오류: {e}")

        # 3. 참조 정리
        self.generation_thread = None
        self.generation_worker = None

        # 4. 대기 중인 참조 정리
        for ref in self._pending_thread_refs:
            try:
                if hasattr(ref, 'isRunning') and ref.isRunning():
                    ref.quit()
                    ref.wait(500)
                if hasattr(ref, 'deleteLater'):
                    ref.deleteLater()
            except Exception:
                pass
        self._pending_thread_refs.clear()

        # 5. 강력한 정리
        _force_cleanup_all_threads()

        self._thread_cleanup_in_progress = False
        print("[THREAD] 안전 종료 완료")
