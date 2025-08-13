import requests
import zipfile
import io, time, re, json
import base64
from PIL import Image
from typing import Dict, Any, TYPE_CHECKING, List
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

    def call_generation_api(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        파라미터의 'api_mode'에 따라 적절한 API 호출 메서드로 분기합니다.
        최대 5회까지 예외 발생 시 재시도합니다.
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
                print(f"🧹 APIService: 주석/개행문자 제거 후 프롬프트: '{cleaned_prompt[:100]}...'")
        
        api_mode = parameters.get('api_mode', 'NAI') # 기본값은 NAI
        print(f"🛰️ APIService: '{api_mode}' 모드로 API 호출을 시작합니다.")
        print(f"   📋 주요 파라미터: {parameters.get('width', 'N/A')}x{parameters.get('height', 'N/A')}, "
            f"모델: {parameters.get('model', 'N/A')}, 샘플러: {parameters.get('sampler', 'N/A')}")

        max_retries = 5
        last_exception = None

        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                print(f"🔄 재시도 {attempt}/{max_retries}...")
            try:
                if api_mode == "NAI":
                    return self._call_nai_api(parameters)
                elif api_mode == "WEBUI":
                    return self._call_webui_api(parameters)
                elif api_mode == "COMFYUI":  # 🆕 새로 추가
                    return self._call_comfyui_api(parameters)
                else:
                    return {'status': 'error', 'message': f"지원하지 않는 API 모드: {api_mode}"}
            except Exception as e:
                print(f"⚠️ API 호출 실패 (시도 {attempt}/{max_retries}): {e}")
                last_exception = e
                if attempt < max_retries:
                    time.sleep(1)  # 1초 대기 후 재시도 (필요에 따라 시간 조정 가능)
                else:
                    # 마지막 시도에서도 실패하면 에러 반환
                    return {'status': 'error', 'message': f"API 호출 실패 (최대 재시도 {max_retries}회 초과): {e}"}


    def _call_nai_api(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """NovelAI 이미지 생성 API를 호출합니다."""
        try:
            token = params.get('credential')
            if not token:
                raise ValueError("NAI 토큰이 제공되지 않았습니다.")

            model_mapping = {
                "NAID4.5F": 'nai-diffusion-4-5-full',
                "NAID4.5C": 'nai-diffusion-4-5-curated',
                "NAID4.0F": 'nai-diffusion-4-full',
                "NAID4.0C": 'nai-diffusion-4-curated',
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

                # 캐릭터 모듈 처리 - Sketchbook character prompts take priority
                if params.get('sketchbook_character_prompts'):
                    # Use sketchbook character prompts instead of character module
                    print("📝 Using Sketchbook character prompts instead of Character Module")
                    sketchbook_prompts = params['sketchbook_character_prompts']
                    
                    for prompt, uc in sketchbook_prompts:
                        api_parameters['v4_prompt']['caption']['char_captions'].append({
                            'char_caption': prompt,
                            'centers': [{"x": 0.5, "y": 0.5}]
                        })
                        api_parameters['v4_negative_prompt']['caption']['char_captions'].append({
                            'char_caption': uc or "",
                            'centers': [{"x": 0.5, "y": 0.5}]
                        })
                    
                    print(f"✅ Added {len(sketchbook_prompts)} Sketchbook character prompts")
                else:
                    # Fall back to regular character module
                    char_module = self.app_context.middle_section_controller.get_module_instance("CharacterModule")
                    if char_module and char_module.activate_checkbox.isChecked():
                        print("✅ 캐릭터 모듈 활성화됨. 파라미터를 가져옵니다.")
                        char_params = char_module.get_parameters()
                        
                        if char_params and char_params.get("characters"):
                            characters = char_params["characters"]
                            ucs = char_params["uc"]
                            
                            for i, prompt in enumerate(characters):
                                api_parameters['v4_prompt']['caption']['char_captions'].append({
                                    'char_caption': prompt,
                                    'centers': [{"x": 0.5, "y": 0.5}]
                                })
                                api_parameters['v4_negative_prompt']['caption']['char_captions'].append({
                                    'char_caption': ucs[i] if i < len(ucs) else "",
                                    'centers': [{"x": 0.5, "y": 0.5}]
                                })
            
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
            
            print("📤 NAI API 요청 페이로드:", payload)
            
            # API payload를 안전하게 저장
            self.app_context.store_api_payload(payload, "NAI")
            
            response = requests.post(
                self.NAI_V3_API_URL,
                headers=headers,
                json=payload,
                timeout=180
            )
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
        """Stable Diffusion WebUI API를 호출합니다."""
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

                if is_inpaint:
                    mask_bytes = params['mask_bytes']
                    processed_mask = self._process_mask_data(mask_bytes, is_nai=False)
                    payload["mask"] = processed_mask
                    payload["inpainting_fill"] = 1
                    payload["inpaint_full_res"] = True
                    payload["inpaint_full_res_padding"] = 32
            
            if payload["enable_hr"]:
                payload.update({
                    "hr_scale": params.get('hr_scale', 1.5),
                    "hr_upscaler": params.get('hr_upscaler', 'Lanczos'),
                    "hr_second_pass_steps": params.get('steps', 28) // 2,
                    "hr_resize_x": int(payload["width"] * params.get('hr_scale', 1.5)),
                    "hr_resize_y": int(payload["height"] * params.get('hr_scale', 1.5))
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
            response = requests.post(api_endpoint, headers=headers, json=payload, timeout=300)
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

    def _call_comfyui_api(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
            def progress_callback(current: int, total: int):
                # 메인 윈도우에 진행률 업데이트 (필요시 구현)
                progress_percent = int((current / total) * 100) if total > 0 else 0
                print(f"🔄 ComfyUI 생성 진행률: {progress_percent}% ({current}/{total})")
            
            # 7. 이미지 생성 실행
            result = self.comfyui_service.generate_image(workflow, progress_callback)
            
            if result and result['status'] == 'success':
                print(f"✅ ComfyUI 이미지 생성 완료: {result['filename']}")
                return result
            else:
                error_msg = result.get('message', '알 수 없는 오류') if result else 'API 호출 실패'
                raise Exception(error_msg)
                
        except Exception as e:
            print(f"❌ ComfyUI API 호출 중 예외 발생: {e}")
            return {'status': 'error', 'message': str(e)}
        finally:
            # WebSocket 연결 정리
            if self.comfyui_service:
                self.comfyui_service.disconnect_websocket()

    def _process_mask_data(self, mask_bytes: bytes, is_nai: bool = True) -> str:
        """
        Base64 인코딩된 이미지 또는 파일에서 이진 마스크를 생성하고 확대합니다.
        
        Args:
            mask_bytes (bytes): 마스크 바이너리 데이터
            is_nai (bool): NAI API 여부 (기본값: True)
        
        Returns:
            str: Base64로 인코딩된 처리된 마스크 문자열
        """
        import numpy as np
        
        try:
            # 이미지 데이터 가져오기
            base64_string = base64.b64encode(mask_bytes).decode('utf-8')
            
            # Base64 디코딩
            image_data = base64.b64decode(base64_string)
            img = Image.open(io.BytesIO(image_data))
            
            # 1. 그레이스케일로 변환
            img_gray = img.convert('L')
            
            # 2. 이진화 적용 (임계값 기준으로 흑백으로 변환)
            threshold = 128
            img_binary = img_gray.point(lambda x: 255 if x > threshold else 0, '1')
            
            # 3. 원본 크기 저장
            original_width, original_height = img_binary.size
            
            # 4. 새 크기 계산 (정수로 변환)
            scale_factor = 8
            new_width = int(original_width * scale_factor)
            new_height = int(original_height * scale_factor)
            
            # 5. 이진 이미지 확대 - nearest neighbor 사용하여 픽셀화된 경계 유지
            img_resized = img_binary.resize((new_width, new_height), Image.NEAREST)
            
            # 6. 다시 RGB 모드로 변환 (필요한 경우)
            img_final = img_resized.convert('RGB')

            buffer = io.BytesIO()
            img_final.save(buffer, format='PNG')
            new_base64_string = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            print(f"✅ 마스크 처리 완료: {original_width}x{original_height} → {new_width}x{new_height}")
            return new_base64_string
            
        except Exception as e:
            print(f"❌ 마스크 데이터 처리 실패: {e}")
            # 폴백: 원본 데이터를 그대로 base64 인코딩
            return base64.b64encode(mask_bytes).decode()