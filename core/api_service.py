import requests
import zipfile
import io, time, re, json
import base64
import numpy as np
import gc
from PIL import Image
from typing import Dict, Any, TYPE_CHECKING, List
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import QCoreApplication, QThreadPool
from core.comfyui_service import ComfyUIService
from core.comfyui_workflow_manager import ComfyUIWorkflowManager

if TYPE_CHECKING:
    from core.context import AppContext
    from modules.character_module import CharacterModule

class APIService:
    # [추가] 생성자에서 AppContext를 받도록 수정
    def __init__(self, app_context: 'AppContext'):
        self.app_context = app_context
        """
        API 호출을 전담하는 서비스.
        컨트롤러로부터 받은 파라미터를 기반으로 API에 맞는 최종 페이로드를 생성하고,
        네트워크 요청을 보낸 뒤 응답을 처리합니다.
        """
        self.NAI_V3_API_URL = "https://image.novelai.net/ai/generate-image"
        self.comfyui_service = None
        self.workflow_manager = ComfyUIWorkflowManager()
    
    def _cleanup_http_threads(self):
        """HTTP 연결 관련 스레드 정리"""
        try:
            # urllib3 연결 풀 정리
            try:
                from urllib3.util import connection
                from urllib3 import poolmanager
                if hasattr(poolmanager, '_default_pool'):
                    poolmanager._default_pool = None
            except Exception:
                pass
            
            # requests 세션 정리
            try:
                if hasattr(requests, 'sessions'):
                    if hasattr(requests.sessions, 'Session'):
                        session = requests.Session()
                        session.close()
            except Exception:
                pass
            
            # Qt 스레드 풀 정리
            try:
                thread_pool = QThreadPool.globalInstance()
                thread_pool.clear()
                thread_pool.waitForDone(100)
            except Exception:
                pass
            
            # 가비지 컬렉션
            gc.collect()
            
            # Qt 이벤트 루프 처리
            for _ in range(2):
                QCoreApplication.processEvents()
        except Exception:
            pass

    def call_generation_api(self, parameters: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
        """
        파라미터의 'api_mode'에 따라 적절한 API 호출 메서드로 분기합니다.
        최대 5회까지 예외 발생 시 재시도합니다.

        Args:
            parameters: 생성 파라미터
            progress_callback: ComfyUI 진행률 콜백 (message, current, total, percent)
                워커 스레드에서 호출되므로 시그널 emit 등 스레드 안전한 방식으로 전달해야 함
        """
        # 입력 프롬프트에서 주석 및 개행문자 처리
        if 'input' in parameters and isinstance(parameters['input'], str):
            original_prompt = parameters['input']
            cleaned_tags = []
            for tag in original_prompt.split(','):
                processed_tag = tag.replace('\n', '').strip()
                if processed_tag and not processed_tag.startswith('#'):
                    cleaned_tags.append(processed_tag)
            
            cleaned_prompt = ', '.join(cleaned_tags)
            if original_prompt != cleaned_prompt:
                parameters['input'] = cleaned_prompt
                print(f"[CLEAN] APIService: 주석/개행문자 제거 후 프롬프트: '{cleaned_prompt[:100]}...'")
        
        # resolution:, seed:, cfg_scale:, cfg_rescale:, sampler:, scheduler: 파라미터 처리
        if 'input' in parameters and isinstance(parameters['input'], str):
            processed_prompt = parameters['input']
            fix_seed_value = str(parameters.get('seed', 0))
            fix_res_value = [parameters.get('width', 1024), parameters.get('height', 1024)]

            fix_check = processed_prompt.split(', ')
            after_check = fix_check.copy()

            for i, v in enumerate(fix_check):
                if "seed:" in v and v.startswith("seed:"):
                    fix_seed_value = v[5:]  # "seed:" 부분 제거
                    after_check.remove(fix_check[i])
                elif "resolution:" in v and v.startswith("resolution:"):
                    try:
                        fix_res_value = [int(l) for l in v[11:].split('x')]  # "resolution:" 부분 제거
                        if len(fix_res_value) == 2:
                            parameters['width'] = fix_res_value[0]
                            parameters['height'] = fix_res_value[1]
                    except:
                        fix_res_value = [1024, 1024]
                    after_check.remove(fix_check[i])
                elif v.startswith("cfg_scale:"):
                    try:
                        val = float(v[10:])
                        if 1.0 <= val <= 10.0:
                            parameters['cfg_scale'] = val
                    except ValueError:
                        pass
                    after_check.remove(fix_check[i])
                elif v.startswith("cfg_rescale:"):
                    try:
                        val = float(v[12:])
                        if -1.0 <= val <= 1.0:
                            parameters['cfg_rescale'] = val
                    except ValueError:
                        pass
                    after_check.remove(fix_check[i])
                elif v.startswith("sampler:"):
                    val = v[8:]
                    valid_samplers = ["k_euler", "k_euler_ancestral", "k_dpmpp_2m",
                                      "k_dpmpp_2s_ancestral", "k_dpmpp_sde", "k_dpmpp_2m_sde", "ddim_v3"]
                    if val in valid_samplers:
                        parameters['sampler'] = val
                    after_check.remove(fix_check[i])
                elif v.startswith("scheduler:"):
                    val = v[10:]
                    valid_schedulers = ["native", "karras", "exponential", "polyexponential"]
                    if val in valid_schedulers:
                        parameters['scheduler'] = val
                    after_check.remove(fix_check[i])
                elif v.startswith("steps:"):
                    try:
                        val = int(v[6:])
                        if 1 <= val <= 150:
                            parameters['steps'] = val
                    except ValueError:
                        pass
                    after_check.remove(fix_check[i])

            # seed 값 업데이트
            try:
                parameters['seed'] = int(fix_seed_value)
            except:
                parameters['seed'] = 0

            # 처리된 프롬프트 업데이트 (인라인 파라미터 태그 제거)
            cleaned_tags_prompt = ', '.join(after_check)
            if cleaned_tags_prompt != processed_prompt:
                parameters['input'] = cleaned_tags_prompt
                print(f"[PARAM] APIService: 인라인 파라미터 태그 처리 완료")
                print(f"   - Seed: {parameters.get('seed')}")
                print(f"   - Resolution: {parameters.get('width')}x{parameters.get('height')}")
                print(f"   - CFG Scale: {parameters.get('cfg_scale', 'default')}")
                print(f"   - CFG Rescale: {parameters.get('cfg_rescale', 'default')}")
                print(f"   - Sampler: {parameters.get('sampler', 'default')}")
                print(f"   - Scheduler: {parameters.get('scheduler', 'default')}")
                print(f"   - Steps: {parameters.get('steps', 'default')}")
                print(f"   - 정리된 프롬프트: '{cleaned_tags_prompt[:100]}...'")

        api_mode = parameters.get('api_mode', 'NAI') # 기본값은 NAI

        # Auto-Outpainting 인터셉트 (API 모드 분기 전에 처리)
        if parameters.get('type') == 'auto_outpainting':
            print(f"[API] Auto-Outpainting 단일 패스 모드로 전환합니다.")
            return self._single_pass_outpainting(parameters)

        print(f"[API] APIService: '{api_mode}' 모드로 API 호출을 시작합니다.")
        print(f"   [파라미터] 주요 파라미터: {parameters.get('width', 'N/A')}x{parameters.get('height', 'N/A')}, "
            f"모델: {parameters.get('model', 'N/A')}, 샘플러: {parameters.get('sampler', 'N/A')}")

        max_retries = 3  # 5회에서 3회로 줄임
        last_exception = None

        result = None
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                print(f"[RETRY] 재시도 {attempt}/{max_retries}...")
            try:
                if api_mode == "NAI":
                    result = self._call_nai_api(parameters)
                elif api_mode == "WEBUI":
                    result = self._call_webui_api(parameters)
                elif api_mode == "COMFYUI":  # 🆕 새로 추가
                    result = self._call_comfyui_api(parameters, progress_callback=progress_callback)
                else:
                    result = {'status': 'error', 'message': f"지원하지 않는 API 모드: {api_mode}"}
                
                # 🔧 FIX: API 호출 결과가 error인 경우에도 재시도하도록 수정
                if result and result.get('status') == 'error':
                    error_msg = result.get('message', 'Unknown error')
                    print(f"[WARNING] API 오류 응답 (시도 {attempt}/{max_retries}): {error_msg}")
                    
                    # HTTP 520 등 서버 오류는 재시도 가능
                    if 'HTTP 520' in error_msg or 'HTTP 502' in error_msg or 'HTTP 503' in error_msg or 'HTTP 504' in error_msg:
                        if attempt < max_retries:
                            print(f"[WAIT] 서버 오류 감지. {2 * attempt}초 후 재시도합니다...")
                            time.sleep(2 * attempt)  # 점진적으로 대기 시간 증가
                            continue
                    
                    # 재시도할 수 없는 오류는 즉시 반환
                    last_exception = error_msg
                    if attempt < max_retries:
                        time.sleep(1)  # 1초 대기 후 재시도
                        continue
                    else:
                        # 마지막 시도에서도 실패하면 에러 반환
                        return {'status': 'error', 'message': f"API 호출 실패 (최대 재시도 3회 초과): {error_msg}"}
                
                # Check if cropped_image_request is enabled
                if result and result.get('status') == 'success' and parameters.get('cropped_image_request'):
                    print("✂️ Cropped image request enabled, extracting mask area...")
                    result = self._extract_cropped_image(result, parameters)
                
                return result
                
            except Exception as e:
                print(f"[WARNING] API 호출 실패 (시도 {attempt}/{max_retries}): {e}")
                last_exception = e
                if attempt < max_retries:
                    time.sleep(1)  # 1초 대기 후 재시도 (필요에 따라 시간 조정 가능)
                else:
                    # 마지막 시도에서도 실패하면 에러 반환
                    return {'status': 'error', 'message': f"API 호출 실패 (최대 재시도 3회 초과): {e}"}


    def _get_active_nai_token(self) -> str:
        """
        🆕 멀티 계정 지원: 라운드 로빈 모드에 따라 활성 NAI 토큰을 반환합니다.

        Returns:
            str: 활성 NAI 토큰 (메인 또는 추가 계정)
        """
        try:
            import json
            from pathlib import Path

            # save/nai_accounts.json 로드
            accounts_file = Path("save/nai_accounts.json")

            if not accounts_file.exists():
                # 계정 파일이 없으면 메인 토큰 반환
                main_token = self.app_context.secure_token_manager.get_token('nai_token')
                return main_token

            with open(accounts_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            accounts = data.get('accounts', [])
            round_robin_enabled = data.get('round_robin_enabled', False)
            main_account_enabled = data.get('main_account_enabled', True)  # 🆕 메인 계정 활성화 여부

            # 활성화된 계정 목록 생성 (메인 + 추가 계정)
            active_tokens = []

            # 1. 메인 토큰 추가 (활성화된 경우만)
            main_token = self.app_context.secure_token_manager.get_token('nai_token')
            if main_token and main_account_enabled:
                active_tokens.append(('nai_token', main_token))

            # 2. 활성화된 추가 계정 추가
            for account in accounts:
                if account.get('enabled', False):
                    account_id = account.get('id')
                    token = self.app_context.secure_token_manager.get_token(account_id)
                    if token:
                        active_tokens.append((account_id, token))

            # 활성화된 토큰이 없으면 메인 토큰 반환
            if not active_tokens:
                return main_token if main_token else ""

            # 라운드 로빈 모드 확인
            if round_robin_enabled and len(active_tokens) > 1:
                # 카운터 기반 라운드 로빈
                counter = self.app_context.image_crud_controller.get_counter()
                index = counter % len(active_tokens)

                selected_id, selected_token = active_tokens[index]
                print(f"🔄 [Round-Robin] 카운터: {counter}, 계정 인덱스: {index}/{len(active_tokens)}, 선택된 계정: {selected_id}")

                return selected_token
            else:
                # 라운드 로빈 비활성화: 첫 번째 활성 토큰 사용
                first_id, first_token = active_tokens[0]
                print(f"✅ [Single Account] 선택된 계정: {first_id}")

                return first_token

        except Exception as e:
            print(f"⚠️ 멀티 계정 토큰 선택 오류: {e}. 메인 토큰으로 폴백합니다.")
            # 에러 발생 시 메인 토큰으로 폴백
            main_token = self.app_context.secure_token_manager.get_token('nai_token')
            return main_token if main_token else ""

    def _call_nai_api(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """NovelAI 이미지 생성 API를 호출합니다."""
        try:
            # 🆕 멀티 계정 지원: 라운드 로빈 토큰 선택
            token = self._get_active_nai_token()
            if not token:
                raise ValueError("NAI 토큰이 제공되지 않았습니다.")

            model_mapping = {
                "NAID4.5F": 'nai-diffusion-4-5-full',
                "NAID4.5C": 'nai-diffusion-4-5-curated',
                "NAID4.0F": 'nai-diffusion-4-full',
                "NAID4.0C": 'nai-diffusion-4-curated-preview',
                "NAID3": 'nai-diffusion-3'
            }
            
            # 모델 이름 가져오기 및 매핑
            model_key = params.get('model', 'NAID4.5F')
            model_name = model_mapping.get(model_key, 'nai-diffusion-4-5-full')

            # ✅ Img2Img 분기 처리
            is_img2img = 'image_bytes' in params and params['image_bytes'] is not None
            action_type = "generate"
            if is_img2img:
                action_type = "infill" if params.get('type') == 'inpaint' else "img2img"
            if params.get('type') == 'inpaint':
                model_name += "-inpainting"

            # API가 요구하는 파라미터 구조 생성
            api_parameters = {
                "width": params.get('width', 832),
                "height": params.get('height', 1216),
                "n_samples": 1,
                "seed": params.get('seed', 0),
                "extra_noise_seed": params.get('seed', 0),
                "sampler": params.get('sampler', 'k_euler_ancestral'),
                "steps": params.get('steps', 28),
                "scale": params.get('cfg_scale', 5.0),
                "negative_prompt": params.get('negative_prompt', ''),
                "cfg_rescale": params.get('cfg_rescale', 0.4),
                "noise_schedule": params.get('scheduler', 'native'),
                # NAI V3 (Anlas) 전용 파라미터
                "params_version": 3,
                "legacy": False,
                "legacy_v3_extend": False,
            }
            
            # skip_cfg_above_sigma 처리 (VAR+ 파라미터에 따라)
            if params.get('VAR+', False):
                # VAR+가 True일 때 모델에 따라 다른 값 설정
                if model_name in ['nai-diffusion-4-5-full', 'nai-diffusion-4-5-curated']:
                    api_parameters["skip_cfg_above_sigma"] = 58
                elif model_name in ['nai-diffusion-4-full', 'nai-diffusion-4-curated', 'nai-diffusion-3']:
                    api_parameters["skip_cfg_above_sigma"] = 19
                # inpainting 모델도 동일하게 처리
                elif model_name in ['nai-diffusion-4-5-full-inpainting', 'nai-diffusion-4-5-curated-inpainting']:
                    api_parameters["skip_cfg_above_sigma"] = 58
                elif model_name in ['nai-diffusion-4-full-inpainting', 'nai-diffusion-4-curated-inpainting', 'nai-diffusion-3-inpainting']:
                    api_parameters["skip_cfg_above_sigma"] = 19
            else:
                # VAR+가 False일 때는 null (Python에서는 None이지만 JSON 전송 시 제외됨)
                api_parameters["skip_cfg_above_sigma"] = None

            if is_img2img:
                api_parameters["image"] = base64.b64encode(params['image_bytes']).decode()
                
                if action_type == "infill":
                    # 🔥 핵심 수정: 마스크 데이터 처리 개선
                    mask_bytes = params['mask_bytes']
                    
                    # 마스크 데이터 형식 확인 및 변환
                    processed_mask = self._process_mask_data(mask_bytes, is_nai=True)
                    api_parameters["mask"] = processed_mask
                    
                    api_parameters["add_original_image"] = True
                    api_parameters["inpaintImg2ImgStrength"] = params.get('strength', 0.7)
                    api_parameters["noise"] = 0
                    api_parameters["deliberate_euler_ancestral_bug"] = False
                    api_parameters["controlnet_strength"] = 1
                    api_parameters["request_type"] = "NativeInfillingRequest"
                else: # img2img
                    api_parameters["strength"] = params.get('strength', 0.5)
                    api_parameters["noise"] = params.get('noise', 0.05)
            
            # V4 특화 설정 (기존과 동일)
            if 'nai-diffusion-4' in model_name:
                main_prompt = params.get('input', '')
                negative_prompt = params.get('negative_prompt', '')
                
                api_parameters.update({
                    'params_version': 3,
                    'add_original_image': True,
                    'legacy': False,
                    'legacy_uc': False,
                    'autoSmea': True,
                    'prefer_brownian': True,
                    'ucPreset': 0,
                    'use_coords': False,
                    'v4_negative_prompt': {
                        'caption': {
                            'base_caption': negative_prompt,
                            'char_captions': []
                        },
                        'legacy_uc': False
                    },
                    'v4_prompt': {
                        'caption': {
                            'base_caption': main_prompt,
                            'char_captions': []
                        },
                        'use_coords': False,
                        'use_order': True
                    }
                })

                # 캐릭터 모듈 처리 — 소스별 정규화 후 공통 적용
                # 정규화 형식: characters=[str], ucs=[str], positions=[{'x','y'}]
                char_source = None
                characters, ucs, character_positions = [], [], []

                if params.get('sketchbook_character_prompts'):
                    # 1) Sketchbook / Img2ImgWindow 오버라이드
                    char_source = "Sketchbook"
                    for item in params['sketchbook_character_prompts']:
                        if isinstance(item, tuple):
                            characters.append(item[0])
                            ucs.append(item[1] or "")
                        elif isinstance(item, dict):
                            characters.append(item.get('prompt', ''))
                            ucs.append(item.get('uc', ''))
                        # Sketchbook은 위치 미지원 → 기본값(0.5, 0.5)

                else:
                    generation_request = params.get('_generation_request')

                    if generation_request and generation_request.nai_characters:
                        # 2) Early Binding — GenerationRequest (큐)
                        char_source = "EarlyBinding"
                        nai_char_data = generation_request.nai_characters
                        characters = list(nai_char_data.characters)
                        ucs = list(nai_char_data.uc)
                        character_positions = [pos.to_dict() for pos in nai_char_data.character_positions]

                    elif self.app_context.temp_window_mode and self.app_context.temp_window_character_tab:
                        # 3) Temporary Window — VirtualCharacterTab
                        char_module = self.app_context.temp_window_character_tab
                        if hasattr(char_module, 'activate_checkbox') and char_module.activate_checkbox.isChecked():
                            char_params = char_module.get_parameters()
                            if char_params and char_params.get("characters"):
                                char_source = "TempWindow"
                                characters = char_params["characters"]
                                ucs = char_params["uc"]
                                character_positions = char_params.get("character_positions", [])

                    elif params.get('characters'):
                        # 4) Saved Params — Enhance 등 저장된 generation_params 재사용
                        char_source = "SavedParams"
                        characters = params['characters']
                        ucs = params.get('uc', [])
                        character_positions = params.get('character_positions', [])

                    else:
                        # 5) Late Binding — 메인 UI CharacterModule (직접 생성)
                        char_module = self.app_context.middle_section_controller.get_module_instance("CharacterModule")
                        if char_module and hasattr(char_module, 'activate_checkbox') and char_module.activate_checkbox.isChecked():
                            char_params = char_module.get_parameters()
                            if char_params and char_params.get("characters"):
                                char_source = "LateBind"
                                characters = char_params["characters"]
                                ucs = char_params["uc"]
                                character_positions = char_params.get("character_positions", [])

                # 공통 적용: 정규화된 캐릭터 데이터를 v4_prompt에 추가
                if characters:
                    default_center = {"x": 0.5, "y": 0.5}
                    for i, prompt in enumerate(characters):
                        centers = [character_positions[i]] if i < len(character_positions) else [default_center]
                        api_parameters['v4_prompt']['caption']['char_captions'].append({
                            'char_caption': prompt,
                            'centers': centers
                        })
                        api_parameters['v4_negative_prompt']['caption']['char_captions'].append({
                            'char_caption': ucs[i] if i < len(ucs) else "",
                            'centers': centers
                        })
                    print(f"✅ [{char_source}] {len(characters)} character(s) added"
                          f"{' (positions: ' + str(character_positions) + ')' if character_positions else ''}")
            
            # ✅ Phase 3: Early Binding - GenerationRequest에서 NAI Vibe Transfer 데이터 가져오기
            generation_request = params.get('_generation_request')
            if generation_request and generation_request.nai_vibe_transfer:
                print("✅ [EarlyBinding] Vibe Transfer Data from GenerationRequest")
                nai_vibe_data = generation_request.nai_vibe_transfer

                # Update api_parameters with vibe transfer data
                api_parameters['normalize_reference_strength_multiple'] = nai_vibe_data.normalize
                api_parameters['reference_image_multiple'] = nai_vibe_data.reference_image_multiple
                api_parameters['reference_strength_multiple'] = nai_vibe_data.reference_strength_multiple

                # Add NAID3-specific parameter if present
                if nai_vibe_data.reference_information_extracted_multiple:
                    api_parameters['reference_information_extracted_multiple'] = nai_vibe_data.reference_information_extracted_multiple
                    print(f"  - NAID3 IE values: {nai_vibe_data.reference_information_extracted_multiple}")

                print(f"  - {len(nai_vibe_data.reference_image_multiple)} vibe(s) added")
                print(f"  - Normalization: {nai_vibe_data.normalize}")
                print(f"  - Strengths: {nai_vibe_data.reference_strength_multiple}")
            else:
                # 🔄 Late Binding fallback for direct generation (non-queue)
                vibe_module = self.app_context.middle_section_controller.get_module_instance("VibeTransferModule")
                if vibe_module:
                    vibe_data = vibe_module.get_vibe_transfer_multiple_data()
                    if vibe_data and vibe_data.get('reference_image_multiple'):
                        print("🔄 [LateBinding] Vibe Transfer from module (direct generation)")

                        # Update api_parameters with vibe transfer data
                        api_parameters['normalize_reference_strength_multiple'] = vibe_data['normalize_reference_strength_multiple']
                        api_parameters['reference_image_multiple'] = vibe_data['reference_image_multiple']
                        api_parameters['reference_strength_multiple'] = vibe_data['reference_strength_multiple']

                        # Add NAID3-specific parameter if present
                        if 'reference_information_extracted_multiple' in vibe_data:
                            api_parameters['reference_information_extracted_multiple'] = vibe_data['reference_information_extracted_multiple']

                        print(f"  - {len(vibe_data['reference_image_multiple'])} vibe(s) added")

            # ✅ Phase 3: Early Binding - GenerationRequest에서 NAI Character Reference 데이터 가져오기 - NAID4.5 전용
            if model_name in ['nai-diffusion-4-5-full', 'nai-diffusion-4-5-curated', 'nai-diffusion-4-5-full-inpainting', 'nai-diffusion-4-5-curated-inpainting']: # 다음 모델 제외: 
                generation_request = params.get('_generation_request')
                if generation_request and generation_request.nai_character_reference:
                    print("✅ [EarlyBinding] Character Reference Data from GenerationRequest")
                    nai_ref_data = generation_request.nai_character_reference

                    # Director 파라미터 추가
                    api_parameters['director_reference_descriptions'] = nai_ref_data.director_reference_descriptions
                    api_parameters['director_reference_images'] = nai_ref_data.director_reference_images
                    api_parameters['director_reference_information_extracted'] = nai_ref_data.director_reference_information_extracted
                    api_parameters['director_reference_secondary_strength_values'] = nai_ref_data.director_reference_secondary_strength_values
                    api_parameters['director_reference_strength_values'] = nai_ref_data.director_reference_strength_values

                    # Character Reference 활성화 시 skip_cfg_above_sigma 제거
                    if 'skip_cfg_above_sigma' in api_parameters:
                        del api_parameters['skip_cfg_above_sigma']
                        print("  - skip_cfg_above_sigma 파라미터 제거됨 (Character Reference 활성화)")

                    # Character Reference Module에서 추가된 파라미터들
                    api_parameters['controlnet_strength'] = nai_ref_data.controlnet_strength
                    api_parameters['inpaintImg2ImgStrength'] = nai_ref_data.inpaint_img2img_strength
                    api_parameters['normalize_reference_strength_multiple'] = nai_ref_data.normalize_reference_strength_multiple

                    print(f"  - Director images: {len(nai_ref_data.director_reference_images)}")
                    print(f"  - Director strengths: {nai_ref_data.director_reference_strength_values}")
                    print(f"  - Fidelity values: {nai_ref_data.director_reference_secondary_strength_values}")
                elif params.get('director_reference_descriptions'):
                    # 🔄 Late Binding fallback for direct generation (non-queue)
                    print("🔄 [LateBinding] Character Reference from params (direct generation)")

                    # Director 파라미터 추가
                    api_parameters['director_reference_descriptions'] = params['director_reference_descriptions']
                    api_parameters['director_reference_images'] = params['director_reference_images']
                    api_parameters['director_reference_information_extracted'] = params['director_reference_information_extracted']
                    api_parameters['director_reference_secondary_strength_values'] = params['director_reference_secondary_strength_values']
                    api_parameters['director_reference_strength_values'] = params['director_reference_strength_values']

                    # Character Reference 활성화 시 skip_cfg_above_sigma 제거
                    if 'skip_cfg_above_sigma' in api_parameters:
                        del api_parameters['skip_cfg_above_sigma']
                        print("  - skip_cfg_above_sigma 파라미터 제거됨 (Character Reference 활성화)")

                    # Character Reference Module에서 추가된 파라미터들
                    if 'controlnet_strength' in params:
                        api_parameters['controlnet_strength'] = params['controlnet_strength']
                    if 'inpaintImg2ImgStrength' in params:
                        api_parameters['inpaintImg2ImgStrength'] = params['inpaintImg2ImgStrength']
                    if 'normalize_reference_strength_multiple' in params:
                        api_parameters['normalize_reference_strength_multiple'] = params['normalize_reference_strength_multiple']

                    print(f"  - Director images: {len(params['director_reference_images'])}")
            
            # 🔥 개선된 커스텀 파라미터 처리 (NAI용)
            if params.get('use_custom_api_params', False):
                self._apply_custom_nai_params(api_parameters, params)
            
            # 최종 페이로드 구성
            payload = {
                "input": params.get('input', ''),
                "model": model_name,
                "action": action_type,
                "parameters": api_parameters
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            # print("📤 NAI API 요청 페이로드:", payload)
            
            # API payload를 안전하게 저장
            self.app_context.store_api_payload(payload, "NAI")
            
            # HTTP 세션을 사용하여 연결 정리
            with requests.Session() as session:
                response = session.post(
                    self.NAI_V3_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=180
                )
                # 세션 정리
                session.close()
                if hasattr(session, 'adapters'):
                    for adapter in session.adapters.values():
                        if hasattr(adapter, 'poolmanager') and adapter.poolmanager:
                            adapter.poolmanager.clear()
            
            # HTTP 스레드 정리
            self._cleanup_http_threads()
            response.raise_for_status()
            
            # 이미지 처리
            image_data = self._process_nai_response(response.content)
            if image_data:
                return {'status': 'success', 'image': image_data['image'], 'raw_bytes': image_data['raw_bytes']}
            else:
                raise Exception("응답에서 이미지를 처리할 수 없습니다.")

        except requests.exceptions.HTTPError as e:
            error_message = f"API 오류 (HTTP {e.response.status_code}): {e.response.text}"
            print(f"❌ {error_message}")
            return {'status': 'error', 'message': error_message}
        except Exception as e:
            print(f"❌ NAI API 호출 중 예외 발생: {e}")
            return {'status': 'error', 'message': str(e)}

    def _call_webui_api(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stable Diffusion WebUI API를 호출합니다.

        ⚠️ Inpaint 모드:
        - NAI 사양의 작은 마스크(152x104 등)를 전달하면 자동으로 원본 이미지 크기로 변환됩니다.
        - mask_bytes에 NAI 사양 마스크를 그대로 전달해도 WebUI에서 정상 작동합니다.
        """
        try:
            webui_url = params.get('credential')
            if not webui_url:
                raise ValueError("WEBUI URL이 제공되지 않았습니다.")
            if not webui_url.startswith("http"):
                if "127.0" not in webui_url:
                    webui_url = f"https://{webui_url}"
                else:
                    webui_url = f"http://{webui_url}"

            is_img2img = 'image_bytes' in params and params['image_bytes'] is not None
            is_inpaint = is_img2img and params.get('type') == 'inpaint'
            api_endpoint = f"{webui_url}/sdapi/v1/img2img" if is_img2img else f"{webui_url}/sdapi/v1/txt2img"

            # WEBUI API 페이로드 구성
            payload = {
                "prompt": params.get('input', ''),
                "negative_prompt": params.get('negative_prompt', ''),
                "width": params.get('width', 1024),
                "height": params.get('height', 1216),
                "steps": params.get('steps', 28),
                "cfg_scale": params.get('cfg_scale', 5.0),
                "seed": params.get('seed', -1),
                "sampler_name": params.get('sampler', 'Euler a'),
                "scheduler": params.get('scheduler', 'SGM Uniform'),
                "n_iter": 1,
                "batch_size": 1,
                "restore_faces": False,
                "tiling": False,
                "enable_hr": params.get('enable_hr', False),
                "denoising_strength": params.get('denoising_strength', 0.5),
                "save_images": True,
                "send_images": True,
                "do_not_save_samples": False,
                "do_not_save_grid": True
            }

            if is_img2img:
                payload["init_images"] = [base64.b64encode(params['image_bytes']).decode()]
                payload["denoising_strength"] = params.get('strength', 0.5)
                # 🔥 중요: img2img API에 필수 파라미터 추가
                payload["include_init_images"] = True

                if is_inpaint:
                    # 마스크 데이터 처리
                    mask_bytes = params.get('mask_bytes')
                    if not mask_bytes:
                        raise ValueError("Inpaint 모드에서는 mask_bytes가 필수입니다.")

                    # 마스크를 원본 이미지 크기로 변환 (NAI 작은 마스크 → WebUI 큰 마스크)
                    target_width = params.get('width', 1024)
                    target_height = params.get('height', 1216)
                    processed_mask = self._process_mask_for_webui(mask_bytes, target_width, target_height)
                    payload["mask"] = processed_mask

                    # 🔥 Inpaint 전용 파라미터 추가
                    payload["mask_blur"] = params.get('mask_blur', 4)
                    payload["inpainting_fill"] = params.get('inpainting_fill', 1)  # 0: fill, 1: original, 2: latent noise, 3: latent nothing
                    payload["inpaint_full_res"] = params.get('inpaint_full_res', True)
                    payload["inpaint_full_res_padding"] = params.get('inpaint_full_res_padding', 32)
                    payload["inpainting_mask_invert"] = params.get('inpainting_mask_invert', 0)  # 0: inpaint masked, 1: inpaint not masked
                    payload["initial_noise_multiplier"] = params.get('initial_noise_multiplier', 1.0)

                    print(f"🎨 [WEBUI Inpaint] 파라미터 설정 완료")
                    print(f"   - 마스크: {target_width}x{target_height} (NAI 작은 마스크 자동 변환 지원)")
                    print(f"   - mask_blur: {payload['mask_blur']}")
                    print(f"   - inpainting_fill: {payload['inpainting_fill']}")
                    print(f"   - inpaint_full_res: {payload['inpaint_full_res']}")
                    print(f"   - inpaint_full_res_padding: {payload['inpaint_full_res_padding']}")
                    print(f"   - inpainting_mask_invert: {payload['inpainting_mask_invert']}")
            
            if payload["enable_hr"]:
                payload.update({
                    "hr_scale": params.get('hr_scale', 1.5),
                    "hr_upscaler": params.get('hr_upscaler', 'Lanczos'),
                    "hr_second_pass_steps": params.get('steps', 28) // 2,
                    "hr_resize_x": int(payload["width"] * params.get('hr_scale', 1.5)),
                    "hr_resize_y": int(payload["height"] * params.get('hr_scale', 1.5)),
                    "hr_cfg": params.get('hr_cfg', 0)  # hr_cfg 추가, 기본값 0
                })
            
            # 🔥 개선된 커스텀 파라미터 처리
            if params.get('use_custom_api_params', False):
                self._apply_custom_api_params(payload, params)
            
            print(f"📤 WEBUI API 요청 페이로드 요약:")
            print(f"   - 엔드포인트: {api_endpoint}")
            print(f"   - 해상도: {payload['width']}x{payload['height']}")
            print(f"   - 커스텀 스크립트: {len(payload.get('alwayson_scripts', {}))}개")
            
            self.app_context.store_api_payload(payload, "WEBUI")
            
            headers = {"Content-Type": "application/json"}
            # HTTP 세션을 사용하여 연결 정리
            with requests.Session() as session:
                response = session.post(api_endpoint, headers=headers, json=payload, timeout=300)
                # 세션 정리
                session.close()
                if hasattr(session, 'adapters'):
                    for adapter in session.adapters.values():
                        if hasattr(adapter, 'poolmanager') and adapter.poolmanager:
                            adapter.poolmanager.clear()
            
            # HTTP 스레드 정리
            self._cleanup_http_threads()
            response.raise_for_status()
            
            result = response.json()
            
            if 'images' in result and len(result['images']) > 0:
                image_b64 = result['images'][0]
                image_data = base64.b64decode(image_b64)
                image = Image.open(io.BytesIO(image_data))
                
                info_text = result.get('info', '')
                if info_text:
                    print(f"📋 WEBUI 생성 정보: {info_text[:100]}...")
                
                return {
                    'status': 'success', 
                    'image': image, 
                    'raw_bytes': image_data,
                    'generation_info': info_text
                }
            else:
                raise Exception("응답에서 이미지를 찾을 수 없습니다.")
        
        except Exception as e:
            print(f"❌ WEBUI API 호출 중 예외 발생: {e}")
            return {'status': 'error', 'message': str(e)}

    def _apply_custom_api_params(self, payload: dict, params: dict) -> None:
        """
        커스텀 API 파라미터를 처리하고 payload에 적용합니다.
        더욱 강력해진 단일 파서 함수를 사용하여 안정성을 높였습니다.
        """
        custom_params_text = params.get('custom_api_params', '').strip()
        if not custom_params_text:
            return

        # alwayson_scripts 초기화
        if 'alwayson_scripts' not in payload:
            payload['alwayson_scripts'] = {}

        try:
            # 1. 원본 텍스트로 바로 파싱 시도
            custom_params = json.loads(custom_params_text)
        except json.JSONDecodeError:
            # 2. 파싱 실패 시, 지능형 자동 수정 함수 호출
            print("⚠️ JSON 파싱 실패. 자동 수정 시도...")
            corrected_text = self._intelligent_json_corrector(custom_params_text)
            try:
                # 수정된 텍스트로 다시 파싱
                custom_params = json.loads(corrected_text)
            except json.JSONDecodeError as e:
                # 최종 실패
                print(f"❌ Custom API 파라미터를 적용할 수 없습니다. 자동 수정 후에도 오류가 발생했습니다.")
                print(f"   오류 내용: {e}")
                print(f"   수정 시도한 텍스트: {corrected_text[:200]}...") # 디버깅을 위해 일부 출력
                return

        # 성공적으로 파싱된 경우 payload에 업데이트
        if isinstance(custom_params, dict):
            payload['alwayson_scripts'].update(custom_params)
            print(f"✅ Custom API 파라미터 적용됨: {len(custom_params)}개 스크립트")

    def _intelligent_json_corrector(self, text: str) -> str:
        """
        비정형적인 JSON 텍스트를 지능적으로 수정하여 유효한 JSON으로 변환합니다.
        - [NEW] placeholder '{…}' 또는 '{...}'를 빈 객체 '{}'로 변환
        - 외부 중괄호 추가
        - "args" 배열 내의 "숫자": 패턴 제거
        - 불필요한 쉼표 제거 (특히 배열 처리 후 발생하는 연속 쉼표)
        """
        corrected = text.strip()

        # 0. Placeholder를 빈 객체로 변환 (가장 먼저 처리)
        # re.DOTALL 플래그는 줄바꿈 문자가 포함된 경우도 처리합니다.
        # '…' (하나의 문자) 또는 '...' (세 개의 마침표)를 모두 찾습니다.
        corrected = re.sub(r'{\s*(?:…|\.{3})\s*}', '{}', corrected, flags=re.DOTALL)

        # 1. 외부 중괄호가 없다면 추가하여 완전한 객체 형태로 만들기
        if not corrected.startswith('{'):
            corrected = '{' + corrected
        if not corrected.endswith('}'):
            corrected = corrected + '}'

        # 2. "args": [...] 블록을 찾아 내부 컨텐츠만 수정 (가장 중요)
        def fix_args_array(match):
            # "args": [ 와 ] 사이의 모든 내용을 가져옴
            content = match.group(1)
            
            # content 내부에서 "숫자": 패턴을 모두 제거
            content_fixed = re.sub(r'"\d+"\s*:\s*', '', content)
            
            # "args": [ 와 수정된 내용을 다시 합쳐서 반환
            return f'"args": [{content_fixed}]'

        # "args" 배열을 찾아 fix_args_array 함수로 처리
        corrected = re.sub(r'"args"\s*:\s*\[(.*)\]', fix_args_array, corrected, flags=re.DOTALL)

        # 3. 전체 텍스트에서 발생할 수 있는 일반적인 오류 수정
        # 예: [ true, , false ] -> [ true, false ]
        corrected = re.sub(r',\s*,', ',', corrected)
        # 예: [ , true ] -> [ true ]
        corrected = re.sub(r'\[\s*,', '[', corrected)
        # 예: { , "key" ] -> { "key" }
        corrected = re.sub(r'{\s*,', '{', corrected)
        # 예: "key": value, } -> "key": value }
        corrected = re.sub(r',(\s*[}\]])', r'\1', corrected)
        
        return corrected

    def _apply_custom_nai_params(self, api_parameters: dict, params: dict) -> None:
        """
        NovelAI API 전용 커스텀 파라미터를 처리하고 api_parameters에 적용합니다.
        NAI는 직접 parameters 객체를 수정하는 방식을 사용합니다.
        """
        custom_params_text = params.get('custom_api_params', '').strip()
        if not custom_params_text:
            return

        try:
            # 1. 원본 텍스트로 바로 파싱 시도
            custom_params = json.loads(custom_params_text)
        except json.JSONDecodeError:
            # 2. 파싱 실패 시, 지능형 자동 수정 함수 호출
            print("Warning: JSON parsing failed. Attempting auto-correction...")
            corrected_text = self._intelligent_json_corrector(custom_params_text)
            try:
                # 수정된 텍스트로 다시 파싱
                custom_params = json.loads(corrected_text)
            except json.JSONDecodeError as e:
                # 최종 실패
                print(f"Error: Custom NAI parameters could not be applied. Error persisted after auto-correction.")
                print(f"   Error details: {e}")
                print(f"   Attempted correction: {corrected_text[:200]}...")
                return

        # 성공적으로 파싱된 경우 api_parameters에 업데이트
        if isinstance(custom_params, dict):
            # NAI API parameters에 직접 병합
            api_parameters.update(custom_params)
            print(f"Custom NAI parameters applied: {len(custom_params)} parameters")
            
            # 적용된 파라미터들을 로그에 출력 (디버깅용)
            for key, value in custom_params.items():
                print(f"   - {key}: {value}")

    def _process_nai_response(self, content: bytes) -> Dict[str, Any] | None:
        """NAI API의 응답(zip)을 처리하여 PIL Image와 원본 바이트를 반환합니다."""
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zipped:
                # zip 파일 내의 첫 번째 파일이 이미지
                image_bytes = zipped.read(zipped.infolist()[0])
                image = Image.open(io.BytesIO(image_bytes))
            return {'image': image, 'raw_bytes': image_bytes}
        except Exception as e:
            print(f"응답 데이터(zip) 처리 실패: {e}")
            return None

    def _call_comfyui_api(self, params: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
        """ComfyUI API를 호출합니다."""
        try:
            # 1. ComfyUI 서버 URL 가져오기
            comfyui_url = params.get('credential')
            if not comfyui_url:
                raise ValueError("ComfyUI 서버 URL이 제공되지 않았습니다.")
            
            # URL 정규화 (http:// 프로토콜 추가)
            if not comfyui_url.startswith("http"):
                comfyui_url = f"http://{comfyui_url}"
            
            # 2. ComfyUI 서비스 초기화
            if not self.comfyui_service or self.comfyui_service.server_url != comfyui_url:
                self.comfyui_service = ComfyUIService(comfyui_url)
            
            # 3. 연결 테스트
            if not self.comfyui_service.test_connection():
                raise Exception("ComfyUI 서버에 연결할 수 없습니다.")
            
            # 4. 워크플로우 생성
            workflow = params['workflow']

            # 6. 진행률 콜백 설정
            # 🔧 FIX: QTimer.singleShot 및 app_context.publish를 워커 스레드에서 직접 호출하지 않음
            # 외부에서 전달된 progress_callback(시그널 emit)을 통해 메인 스레드로 안전하게 전달
            def _comfyui_progress(current: int, total: int):
                if total <= 0:
                    return

                progress_percent = int((current / total) * 100)

                # 5% 단위로 진행 바 생성 (총 20개 박스)
                filled_boxes = int(progress_percent / 5)
                empty_boxes = 20 - filled_boxes
                progress_bar = "■" * filled_boxes + "□" * empty_boxes

                message = f"ComfyUI 생성 : {progress_percent}% ({current}/{total}) [{progress_bar}]"

                # 스레드 안전: 외부 콜백 호출 (GenerationWorker의 시그널 emit)
                if progress_callback:
                    progress_callback(message, current, total, progress_percent)

            # 7. 이미지 생성 실행
            result = self.comfyui_service.generate_image(workflow, _comfyui_progress)
            
            if result and result['status'] == 'success':
                print(f"✅ ComfyUI 이미지 생성 완료: {result['filename']}")
                return result
            else:
                error_msg = result.get('message', '알 수 없는 오류') if result else 'API 호출 실패'
                raise Exception(error_msg)
                
        except Exception as e:
            print(f"❌ ComfyUI API 호출 중 예외 발생: {e}")
            return {'status': 'error', 'message': str(e)}

    def _process_mask_for_webui(self, mask_bytes: bytes, target_width: int, target_height: int) -> str:
        """
        WebUI용 마스크를 처리합니다. NAI 작은 마스크를 원본 이미지 크기로 자동 변환합니다.

        Args:
            mask_bytes (bytes): 마스크 바이너리 데이터 (NAI 작은 마스크 또는 큰 마스크)
            target_width (int): 목표 이미지 너비
            target_height (int): 목표 이미지 높이

        Returns:
            str: Base64로 인코딩된 처리된 마스크 문자열 (원본 이미지 크기)
        """
        try:
            # 이미지 데이터 로드
            img = Image.open(io.BytesIO(mask_bytes))

            # 1. 그레이스케일로 변환
            img_gray = img.convert('L')

            # 2. 이진화 적용 (임계값 기준으로 흑백으로 변환)
            threshold = 128
            img_binary = img_gray.point(lambda x: 255 if x > threshold else 0, '1')

            # 3. 마스크 크기 확인
            mask_width, mask_height = img_binary.size

            # 4. 마스크가 목표 크기보다 작으면 확대 (NAI 작은 마스크 대응)
            if mask_width < target_width or mask_height < target_height:
                print(f"🔍 [WebUI] 작은 마스크 감지: {mask_width}x{mask_height} → {target_width}x{target_height}")
                # NEAREST 보간으로 확대 (픽셀화된 경계 유지)
                img_resized = img_binary.resize((target_width, target_height), Image.NEAREST)
            else:
                # 이미 큰 마스크면 그대로 사용
                img_resized = img_binary
                print(f"✅ [WebUI] 마스크 크기 확인: {mask_width}x{mask_height} (변환 불필요)")

            # 5. RGB 모드로 변환
            img_final = img_resized.convert('RGB')

            # 6. Base64 인코딩
            buffer = io.BytesIO()
            img_final.save(buffer, format='PNG')
            base64_string = base64.b64encode(buffer.getvalue()).decode('utf-8')

            print(f"✅ [WebUI] 마스크 처리 완료: 최종 크기 {img_final.size}")
            return base64_string

        except Exception as e:
            print(f"❌ WebUI 마스크 처리 실패: {e}")
            import traceback
            traceback.print_exc()
            # 폴백: 원본 데이터를 그대로 base64 인코딩
            return base64.b64encode(mask_bytes).decode()

    def _process_mask_data(self, mask_bytes: bytes, is_nai: bool = True) -> str:
        """
        마스크 데이터를 처리하여 Base64 문자열로 반환합니다.

        Args:
            mask_bytes (bytes): 마스크 바이너리 데이터
            is_nai (bool): NAI API 여부 (True: NAI는 8배 확대, False: WebUI는 원본 크기)

        Returns:
            str: Base64로 인코딩된 처리된 마스크 문자열
        """
        import numpy as np

        try:
            # 이미지 데이터 로드
            img = Image.open(io.BytesIO(mask_bytes))

            # 1. 그레이스케일로 변환
            img_gray = img.convert('L')

            # 2. 이진화 적용 (임계값 기준으로 흑백으로 변환)
            threshold = 128
            img_binary = img_gray.point(lambda x: 255 if x > threshold else 0, '1')

            # 3. 원본 크기 저장
            original_width, original_height = img_binary.size

            if is_nai:
                # NAI: 8배 확대 (작은 마스크를 큰 이미지로 확대)
                scale_factor = 8
                new_width = int(original_width * scale_factor)
                new_height = int(original_height * scale_factor)

                # 이진 이미지 확대 - nearest neighbor 사용하여 픽셀화된 경계 유지
                img_resized = img_binary.resize((new_width, new_height), Image.NEAREST)

                # RGB 모드로 변환
                img_final = img_resized.convert('RGB')

                print(f"✅ [NAI] 마스크 처리 완료: {original_width}x{original_height} → {new_width}x{new_height}")
            else:
                # WebUI: 원본 크기 유지, RGB 변환만 수행
                img_final = img_binary.convert('RGB')

                print(f"✅ [WebUI] 마스크 처리 완료: {original_width}x{original_height} (원본 크기 유지)")

            # Base64 인코딩
            buffer = io.BytesIO()
            img_final.save(buffer, format='PNG')
            new_base64_string = base64.b64encode(buffer.getvalue()).decode('utf-8')

            return new_base64_string

        except Exception as e:
            print(f"❌ 마스크 데이터 처리 실패: {e}")
            import traceback
            traceback.print_exc()
            # 폴백: 원본 데이터를 그대로 base64 인코딩
            return base64.b64encode(mask_bytes).decode()
    
    def _extract_cropped_image(self, result: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract only the mask area from the generated image.
        Returns the cropped image without EXIF data.
        
        Args:
            result: Generation result with image bytes
            parameters: Original generation parameters including full_mask_pil
            
        Returns:
            Modified result with cropped image
        """
        try:
            print("✂️ Starting cropped image extraction...")
            
            # 1. Get the generated image
            generated_image = result.get('image')
            if not generated_image:
                print("   ⚠️ No generated image found, returning original result")
                return result
            
            # 2. Get the mask
            mask_image = parameters.get('full_mask_pil')
            if mask_image:
                print(f"   ℹ️ Using provided mask: {mask_image.size}")
                
                # Ensure mask is in grayscale mode
                if mask_image.mode != 'L':
                    mask_image = mask_image.convert('L')
                
                # Find bounding box of the mask (white areas)
                mask_array = np.array(mask_image)
                white_pixels = np.where(mask_array > 127)
                
                if len(white_pixels[0]) > 0:
                    # Get bounding box of the masked area
                    y_min, y_max = white_pixels[0].min(), white_pixels[0].max()
                    x_min, x_max = white_pixels[1].min(), white_pixels[1].max()
                    
                    # Crop the generated image to the mask area
                    cropped_image = generated_image.crop((x_min, y_min, x_max + 1, y_max + 1))
                    print(f"   ✅ Cropped to mask area: {cropped_image.size}")
                    
                    # Replace the original image with cropped one
                    result['image'] = cropped_image
                    
                    # Remove EXIF data by creating a new image
                    clean_image = Image.new(cropped_image.mode, cropped_image.size)
                    clean_image.putdata(list(cropped_image.getdata()))
                    result['image'] = clean_image
                    
                    # Update image bytes for saving
                    buffer = io.BytesIO()
                    clean_image.save(buffer, format='PNG')
                    result['image_bytes'] = buffer.getvalue()
                    
                    print("   ✅ Cropped image extraction completed (EXIF removed)")
                else:
                    print("   ⚠️ No mask area found, returning original image")
            else:
                print("   ⚠️ No mask provided, returning original image")
            
            return result
            
        except Exception as e:
            print(f"❌ Cropped image extraction failed: {e}")
            import traceback
            traceback.print_exc()
            # Return original result on error
            return result
    
    def _single_pass_outpainting(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        단일 패스 Auto-Outpainting을 수행합니다.
        원본 이미지를 직접 캔버스에 배치하고, 마스크를 자동 생성하여 인페인트 요청합니다.

        Args:
            parameters: 생성 파라미터 (image_bytes 포함)

        Returns:
            아웃페인팅 결과 또는 에러
        """
        DEBUG_OUTPAINTING = False

        try:
            # 1. 원본 이미지 로드
            print("🎨 [Outpainting] Step 1: 원본 이미지 로드...")
            source_image = Image.open(io.BytesIO(parameters['image_bytes']))
            src_w, src_h = source_image.size
            print(f"   ✅ 원본 이미지: {src_w}x{src_h}")

            if DEBUG_OUTPAINTING:
                source_image.show()  # DEBUG: 원본 이미지

            # OutpaintWindow에서 미리 준비된 캔버스/마스크가 있는 경우 직접 사용
            if parameters.get('outpaint_canvas_bytes') and parameters.get('outpaint_mask_bytes'):
                print("🎨 [Outpainting] OutpaintWindow 데이터 사용...")
                canvas_bytes = parameters['outpaint_canvas_bytes']
                mask_bytes = parameters['outpaint_mask_bytes']
                canvas_width = parameters.get('outpaint_canvas_width', 1216)
                canvas_height = parameters.get('outpaint_canvas_height', 832)

                if DEBUG_OUTPAINTING:
                    Image.open(io.BytesIO(canvas_bytes)).show()  # DEBUG: 캔버스
                    Image.open(io.BytesIO(mask_bytes)).show()  # DEBUG: 마스크
            else:
                # 2. 기본 캔버스 생성 (가로 이미지 → 1:1, 세로/정사각 → 3:2)
                print("🎨 [Outpainting] Step 2: 캔버스 생성...")
                if src_w > src_h:
                    canvas_width = 1024
                    canvas_height = 1024
                else:
                    canvas_width = 1216
                    canvas_height = 832

                # 이미지를 캔버스에 맞게 스케일 (fit)
                fit_ratio = min(canvas_width / src_w, canvas_height / src_h)
                if fit_ratio < 1.0 or fit_ratio > 1.0:
                    new_w = int(src_w * fit_ratio)
                    new_h = int(src_h * fit_ratio)
                    # 8의 배수로 정렬
                    new_w = max(8, (new_w // 8) * 8)
                    new_h = max(8, (new_h // 8) * 8)
                    source_image = source_image.resize((new_w, new_h), Image.LANCZOS)
                    src_w, src_h = new_w, new_h
                    print(f"   ✅ 이미지 캔버스 맞춤: {new_w}x{new_h} (ratio={fit_ratio:.2f})")

                canvas = Image.new('RGB', (canvas_width, canvas_height), (255, 255, 255))

                # 8px 그리드에 맞춰 중앙 배치
                x_offset = ((canvas_width - src_w) // 2 // 8) * 8
                y_offset = ((canvas_height - src_h) // 2 // 8) * 8

                if source_image.mode == 'RGBA':
                    canvas.paste(source_image, (x_offset, y_offset), source_image)
                else:
                    canvas.paste(source_image, (x_offset, y_offset))

                print(f"   ✅ 캔버스: {canvas_width}x{canvas_height}, 이미지 위치: ({x_offset}, {y_offset})")

                if DEBUG_OUTPAINTING:
                    canvas.show()  # DEBUG: 캔버스 + 이미지

                # 3. 마스크 자동 생성
                print("🎨 [Outpainting] Step 3: 마스크 생성...")
                mask_array = np.full((canvas_height, canvas_width), 255, dtype=np.uint8)
                # 이미지 영역을 검정(보존)으로 설정
                mask_array[y_offset:y_offset + src_h, x_offset:x_offset + src_w] = 0

                # 경계 블렌딩 보더 (이미지 가장자리 8px를 마스크에 포함)
                border = 8
                if src_h > border * 2 and src_w > border * 2:
                    # 상단 가장자리
                    mask_array[y_offset:y_offset + border, x_offset:x_offset + src_w] = 255
                    # 하단 가장자리
                    mask_array[y_offset + src_h - border:y_offset + src_h, x_offset:x_offset + src_w] = 255
                    # 좌측 가장자리
                    mask_array[y_offset:y_offset + src_h, x_offset:x_offset + border] = 255
                    # 우측 가장자리
                    mask_array[y_offset:y_offset + src_h, x_offset + src_w - border:x_offset + src_w] = 255

                mask_full = Image.fromarray(mask_array, mode='L')

                if DEBUG_OUTPAINTING:
                    mask_full.show()  # DEBUG: 풀사이즈 마스크

                # NAI용 1/8 축소 마스크 생성
                api_mode = parameters.get('api_mode', 'NAI')
                if api_mode == "NAI":
                    small_w = canvas_width // 8
                    small_h = canvas_height // 8
                    mask_small = mask_full.resize((small_w, small_h), Image.NEAREST)
                    mask_small_array = np.array(mask_small)
                    mask_small_array = np.where(mask_small_array > 127, 255, 0).astype(np.uint8)

                    # Dilation으로 마진 확장 (블렌딩 개선)
                    margin = 4
                    try:
                        from scipy import ndimage
                        kernel = np.ones((margin * 2 + 1, margin * 2 + 1), dtype=np.uint8)
                        mask_small_array = ndimage.binary_dilation(
                            mask_small_array == 255, kernel
                        ).astype(np.uint8) * 255
                        print(f"   ✅ {margin}px 마진 확장 (scipy)")
                    except ImportError:
                        mask_copy = mask_small_array.copy()
                        for y in range(small_h):
                            for x in range(small_w):
                                if mask_copy[y, x] == 0:
                                    for dy in range(max(0, y - margin), min(small_h, y + margin + 1)):
                                        for dx in range(max(0, x - margin), min(small_w, x + margin + 1)):
                                            if mask_copy[dy, dx] == 255:
                                                mask_small_array[y, x] = 255
                                                break
                                        if mask_small_array[y, x] == 255:
                                            break
                        print(f"   ✅ {margin}px 마진 확장 (numpy)")

                    mask_to_encode = Image.fromarray(mask_small_array, mode='L')
                else:
                    # WebUI/ComfyUI는 풀사이즈 마스크 사용
                    mask_to_encode = mask_full

                # 마스크를 PNG 바이트로 변환
                mask_byte_arr = io.BytesIO()
                mask_to_encode.save(mask_byte_arr, format='PNG', compress_level=0, optimize=False)
                mask_bytes = mask_byte_arr.getvalue()

                # 캔버스를 PNG 바이트로 변환
                canvas_byte_arr = io.BytesIO()
                canvas.save(canvas_byte_arr, format='PNG')
                canvas_bytes = canvas_byte_arr.getvalue()

                print(f"   ✅ 마스크 생성 완료: {mask_to_encode.size}, 값: {np.unique(np.array(mask_to_encode))}")

            # 4. 인페인트 파라미터 구성
            print("🎨 [Outpainting] Step 4: 인페인트 파라미터 구성...")
            new_params = parameters.copy()
            new_params['image_bytes'] = canvas_bytes
            new_params['mask_bytes'] = mask_bytes
            new_params['width'] = canvas_width
            new_params['height'] = canvas_height
            new_params['type'] = 'inpaint'

            # strength 기본값 설정
            if 'strength' not in new_params or new_params['strength'] < 0.5:
                new_params['strength'] = 0.7

            # 무한 재귀 방지
            new_params.pop('auto_outpainting', None)
            new_params.pop('outpaint_canvas_bytes', None)
            new_params.pop('outpaint_mask_bytes', None)
            new_params.pop('outpaint_canvas_width', None)
            new_params.pop('outpaint_canvas_height', None)

            print(f"   ✅ 파라미터: {canvas_width}x{canvas_height}, strength={new_params.get('strength')}")

            # 5. API 호출
            print("🎨 [Outpainting] Step 5: API 호출...")
            result = self.call_generation_api(new_params)

            if result and result.get('status') == 'success':
                print("   ✅ Auto-Outpainting 완료!")
                if DEBUG_OUTPAINTING:
                    if 'image' in result and result['image']:
                        result['image'].show()  # DEBUG: 최종 결과
                    elif 'raw_bytes' in result:
                        Image.open(io.BytesIO(result['raw_bytes'])).show()
                return result
            else:
                print("   ❌ Auto-Outpainting 실패")
                return result or {'status': 'error', 'message': 'Auto-outpainting API 호출 실패'}

        except Exception as e:
            print(f"❌ Auto-Outpainting 오류: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'message': f'Auto-outpainting 실패: {e}'}
    
    def upscale_NAI(self, pixmap: 'QPixmap', token: str = None) -> Dict[str, Any]:
        """
        NovelAI Upscale API를 사용하여 이미지를 2배 업스케일합니다.
        
        Args:
            pixmap: QPixmap 형식의 이미지
            token: NAI 토큰 (선택적, 제공되지 않으면 context에서 가져옴)
        
        Returns:
            Dict with 'status', 'image' (upscaled QPixmap), and 'message'
        """
        import zipfile
        from PyQt6.QtCore import QBuffer, QIODevice
        
        try:
            # 토큰 가져오기
            if not token:
                token = self.app_context.secure_token_manager.get_token('nai_token')
                if not token:
                    return {
                        'status': 'error',
                        'message': 'NAI 토큰이 설정되지 않았습니다.'
                    }
            
            # QPixmap을 bytes로 변환
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "PNG")
            image_bytes = buffer.data().data()
            buffer.close()
            
            # Base64 인코딩
            img_base64 = base64.b64encode(image_bytes).decode()
            
            # 원본 이미지 크기
            width = pixmap.width()
            height = pixmap.height()
            
            # API 요청 데이터
            data = {
                "image": img_base64,
                "width": width,
                "height": height,
                "scale": 2  # 2배 업스케일
            }
            
            # API 호출
            print(f"🔍 NAI Upscale API 호출 중... (원본: {width}x{height})")
            # HTTP 세션을 사용하여 연결 정리
            with requests.Session() as session:
                response = session.post(
                    "https://api.novelai.net/ai/upscale",
                    json=data,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=60
                )
                # 세션 정리
                session.close()
                if hasattr(session, 'adapters'):
                    for adapter in session.adapters.values():
                        if hasattr(adapter, 'poolmanager') and adapter.poolmanager:
                            adapter.poolmanager.clear()
            
            # HTTP 스레드 정리
            self._cleanup_http_threads()
            
            if response.status_code != 200:
                error_msg = f"API 에러 (코드: {response.status_code})"
                try:
                    error_detail = response.json()
                    error_msg = f"{error_msg}: {error_detail.get('message', 'Unknown error')}"
                except:
                    pass
                return {
                    'status': 'error',
                    'message': error_msg
                }
            
            # 응답이 ZIP 파일 형식
            try:
                zipped = zipfile.ZipFile(io.BytesIO(response.content))
                if not zipped.namelist():
                    return {
                        'status': 'error',
                        'message': '업스케일 결과가 비어있습니다.'
                    }
                
                # 첫 번째 이미지 추출
                file_info = zipped.infolist()[0]
                image_bytes = zipped.read(file_info)
                
                # bytes를 QPixmap으로 변환
                upscaled_pixmap = QPixmap()
                upscaled_pixmap.loadFromData(image_bytes)
                
                if upscaled_pixmap.isNull():
                    return {
                        'status': 'error',
                        'message': '업스케일된 이미지를 로드할 수 없습니다.'
                    }
                
                print(f"✅ 업스케일 성공: {upscaled_pixmap.width()}x{upscaled_pixmap.height()}")
                
                return {
                    'status': 'success',
                    'image': upscaled_pixmap,
                    'message': f'이미지가 {upscaled_pixmap.width()}x{upscaled_pixmap.height()}로 업스케일되었습니다.'
                }
                
            except zipfile.BadZipFile:
                return {
                    'status': 'error',
                    'message': '업스케일 응답 형식이 올바르지 않습니다.'
                }
                
        except requests.exceptions.Timeout:
            return {
                'status': 'error',
                'message': 'API 요청 시간 초과 (60초)'
            }
        except requests.exceptions.ConnectionError:
            return {
                'status': 'error',
                'message': '네트워크 연결 오류'
            }
        except Exception as e:
            print(f"❌ 업스케일 실패: {e}")
            import traceback
            traceback.print_exc()
            return {
                'status': 'error',
                'message': f'업스케일 중 오류 발생: {str(e)}'
            }
    
    def get_anlas(self) -> int:
        """NAI 구독의 Anlas 잔액을 가져옵니다."""
        if self.app_context.current_api_mode != "NAI":
            return None
        
        try:
            # NAI 토큰 가져오기 - secure_token_manager 사용
            nai_access_token = self.app_context.secure_token_manager.get_token('nai_token')
            if not nai_access_token:
                return None
            
            # HTTP 세션을 사용하여 연결 정리
            with requests.Session() as session:
                response = session.get(
                    "https://api.novelai.net/user/subscription",
                    headers={"Authorization": f"Bearer {nai_access_token}"},
                    timeout=3
                )
                # 세션 정리
                session.close()
                if hasattr(session, 'adapters'):
                    for adapter in session.adapters.values():
                        if hasattr(adapter, 'poolmanager') and adapter.poolmanager:
                            adapter.poolmanager.clear()
            
            # HTTP 스레드 정리
            self._cleanup_http_threads()
            
            if response.status_code == 200:
                data = response.json()
                training_steps = data.get('trainingStepsLeft', {})
                fixed_steps = int(training_steps.get('fixedTrainingStepsLeft', 0))
                purchased_steps = int(training_steps.get('purchasedTrainingSteps', 0))
                anlas = fixed_steps + purchased_steps
                return anlas
            
        except Exception as e:
            print(f"⚠️ Anlas 조회 실패: {e}")
        
        return None
    
    def nai_bg_removal_pil(self, pil_image: Image.Image, save_counter: int, token: str = None) -> Dict[str, Any]:
        """
        NovelAI BG-Removal API를 사용하여 이미지 배경을 제거합니다 (PIL Image 버전).
        
        Args:
            pil_image: PIL Image 형식의 이미지
            save_counter: 저장 카운터
            token: NAI 토큰 (선택적, 제공되지 않으면 context에서 가져옴)
        
        Returns:
            Dict with 'status', 'selected_image' (3rd QPixmap), and 'message'
        """
        import zipfile
        import io
        import base64
        from pathlib import Path
        from PyQt6.QtGui import QPixmap
        
        try:
            # 토큰 가져오기
            if not token:
                token = self.app_context.secure_token_manager.get_token('nai_token')
                if not token:
                    return {
                        'status': 'error',
                        'message': 'NAI 토큰이 설정되지 않았습니다.'
                    }
            
            # PIL Image를 bytes로 변환
            img_buffer = io.BytesIO()
            pil_image.save(img_buffer, format="PNG")
            image_bytes = img_buffer.getvalue()
            
            # Base64 인코딩
            img_base64 = base64.b64encode(image_bytes).decode()
            
            # 원본 이미지 크기
            width, height = pil_image.size
            
            # API 요청 데이터
            data = {
                "image": img_base64,
                "width": width,
                "height": height,
                "req_type": "bg-removal"
            }
            
            # API 호출
            # HTTP 세션을 사용하여 연결 정리
            with requests.Session() as session:
                response = session.post(
                    "https://image.novelai.net/ai/augment-image",
                    json=data,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=120  # 배경 제거는 시간이 더 걸릴 수 있음
                )
                # 세션 정리
                session.close()
                if hasattr(session, 'adapters'):
                    for adapter in session.adapters.values():
                        if hasattr(adapter, 'poolmanager') and adapter.poolmanager:
                            adapter.poolmanager.clear()
            
            # HTTP 스레드 정리
            self._cleanup_http_threads()
            
            if response.status_code != 200:
                error_msg = f"API 에러 (코드: {response.status_code})"
                try:
                    error_detail = response.json()
                    error_msg = f"{error_msg}: {error_detail.get('message', 'Unknown error')}"
                except:
                    pass
                return {
                    'status': 'error',
                    'message': error_msg
                }
            
            # 응답이 ZIP 파일 형식으로 3개 이미지 포함
            try:
                zipped = zipfile.ZipFile(io.BytesIO(response.content))
                file_list = zipped.namelist()
                
                if not file_list:
                    return {
                        'status': 'error',
                        'message': '배경 제거 결과가 비어있습니다.'
                    }
                
                # bg_removal 폴더 생성
                save_path = self.app_context.session_save_path / "bg_removal"
                save_path.mkdir(parents=True, exist_ok=True)
                
                # 모든 이미지 추출 및 저장
                images = []
                image_bytes_list = []
                suffixes = ["_masked", "_generated", "_blend"]
                
                for idx, file_info in enumerate(zipped.infolist()):
                    img_bytes = zipped.read(file_info)
                    image_bytes_list.append(img_bytes)
                    
                    # bytes를 QPixmap으로 변환
                    temp_pixmap = QPixmap()
                    temp_pixmap.loadFromData(img_bytes)
                    
                    if not temp_pixmap.isNull():
                        images.append(temp_pixmap)
                        
                        # 파일로 저장
                        if idx < len(suffixes):
                            filename = f"{save_counter:05d}{suffixes[idx]}.png"
                            filepath = save_path / filename
                            temp_pixmap.save(str(filepath), "PNG")
                
                # 3번째 이미지 선택 (인덱스 2)
                selected_image = None
                selected_bytes = None
                if len(images) >= 3:
                    selected_image = images[2]  # 3번째 이미지 (blend)
                    selected_bytes = image_bytes_list[2]
                elif images:
                    # 3개 미만인 경우 마지막 이미지 선택
                    selected_image = images[-1]
                    selected_bytes = image_bytes_list[-1]
                
                if not selected_image:
                    return {
                        'status': 'error',
                        'message': '배경 제거된 이미지를 로드할 수 없습니다.'
                    }
                
                return {
                    'status': 'success',
                    'selected_image': selected_image,  # 선택된 3번째 이미지
                    'raw_bytes': selected_bytes,  # 선택된 이미지의 원본 바이트
                    'message': f'배경 제거 완료: {len(images)}개 이미지 생성'
                }
                
            except zipfile.BadZipFile:
                return {
                    'status': 'error',
                    'message': '배경 제거 응답 형식이 올바르지 않습니다.'
                }
                
        except requests.exceptions.Timeout:
            return {
                'status': 'error',
                'message': 'API 요청 시간 초과 (120초)'
            }
        except requests.exceptions.ConnectionError:
            return {
                'status': 'error',
                'message': '네트워크 연결 오류'
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'배경 제거 중 오류 발생: {str(e)}'
            }
    
    def upscale_NAI_from_inpaint(self, pil_image: Image.Image, target_width: int, target_height: int) -> Dict[str, Any]:
        """
        Inpaint 패널에서 PIL 이미지를 업스케일하고 원본 크기로 리사이징합니다.
        
        Args:
            pil_image: 업스케일할 PIL 이미지
            target_width: 최종 리사이징할 너비
            target_height: 최종 리사이징할 높이
        
        Returns:
            Dict with 'status', 'image' (PIL Image), and 'message'
        """
        try:
            # 1. PIL 이미지를 base64로 변환
            buffered = io.BytesIO()
            pil_image.save(buffered, format="PNG")
            image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            # 2. NAI 토큰 가져오기
            token = self.app_context.secure_token_manager.get_token('nai_token')
            if not token:
                return {
                    'status': 'error',
                    'message': 'NAI 토큰이 없습니다.'
                }
            
            # 3. NAI Upscale API 호출
            # 디버깅: 원본 이미지 크기 확인
            print(f"🔍 DEBUG - Original image size: {pil_image.width}x{pil_image.height}")
            print(f"🔍 DEBUG - Target upscale size: {pil_image.width * 2}x{pil_image.height * 2}")
            print(f"🔍 DEBUG - Base64 string length: {len(image_base64)}")
            
            # NAI API는 width/height가 아닌 원본 크기를 받고 scale로 배수를 결정
            data = {
                "image": image_base64,
                "width": pil_image.width,  # 원본 너비
                "height": pil_image.height,  # 원본 높이
                "scale": 2  # 2배 업스케일 (scale 4는 4배를 의미)
            }
            
            # 디버깅: 요청 데이터 확인
            print(f"🔍 DEBUG - Request data keys: {data.keys()}")
            print(f"🔍 DEBUG - Width: {data['width']}, Height: {data['height']}, Scale: {data['scale']}")
            print(f"🔍 DEBUG - Token exists: {bool(token)}")
            print(f"🔍 DEBUG - Token length: {len(token) if token else 0}")
            
            # HTTP 세션을 사용하여 연결 정리
            with requests.Session() as session:
                response = session.post(
                    "https://api.novelai.net/ai/upscale",
                    json=data,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=60
                )
                # 세션 정리
                session.close()
                if hasattr(session, 'adapters'):
                    for adapter in session.adapters.values():
                        if hasattr(adapter, 'poolmanager') and adapter.poolmanager:
                            adapter.poolmanager.clear()
            
            # HTTP 스레드 정리
            self._cleanup_http_threads()
            
            # 디버깅: 응답 상세 정보
            print(f"🔍 DEBUG - Response status code: {response.status_code}")
            print(f"🔍 DEBUG - Response headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                # 디버깅: 에러 응답 내용 확인
                try:
                    error_content = response.text
                    print(f"🔍 DEBUG - Error response content: {error_content}")
                    
                    # JSON 응답인 경우 파싱 시도
                    try:
                        error_json = response.json()
                        print(f"🔍 DEBUG - Error JSON: {error_json}")
                    except:
                        pass
                except:
                    print(f"🔍 DEBUG - Could not read error response")
                
                return {
                    'status': 'error',
                    'message': f'API 오류: {response.status_code}\n응답: {response.text[:500] if response.text else "No response text"}'
                }
            
            # 4. 응답 처리 (ZIP 파일)
            zip_data = io.BytesIO(response.content)
            with zipfile.ZipFile(zip_data, 'r') as zip_file:
                image_data = zip_file.read(zip_file.namelist()[0])
            
            # 5. 업스케일된 이미지를 PIL로 변환
            upscaled_image = Image.open(io.BytesIO(image_data))
            
            # 6. 원본 크기로 리사이징 (LANCZOS)
            resized_image = upscaled_image.resize(
                (target_width, target_height),
                Image.Resampling.LANCZOS
            )
            
            print(f"✅ 업스케일 완료: {pil_image.width}x{pil_image.height} → "
                  f"{upscaled_image.width}x{upscaled_image.height} → "
                  f"{resized_image.width}x{resized_image.height}")
            
            return {
                'status': 'success',
                'image': resized_image,
                'message': '업스케일 성공'
            }
            
        except requests.exceptions.Timeout:
            return {
                'status': 'error',
                'message': '요청 시간 초과'
            }
        except requests.exceptions.ConnectionError:
            return {
                'status': 'error',
                'message': '네트워크 연결 오류'
            }
        except Exception as e:
            print(f"❌ 업스케일 실패: {e}")
            import traceback
            traceback.print_exc()
            return {
                'status': 'error',
                'message': f'업스케일 중 오류 발생: {str(e)}'
            }