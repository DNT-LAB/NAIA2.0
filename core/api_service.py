import requests
import zipfile
import io, time
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
        api_mode = parameters.get('api_mode', 'NAI') # 기본값은 NAI
        print(f"🛰️ APIService: '{api_mode}' 모드로 API 호출을 시작합니다.")
        print(f"   📋 주요 파라미터: {parameters.get('width', 'N/A')}x{parameters.get('height', 'N/A')}, "
            f"모델: {parameters.get('model', 'N/A')}, 샘플러: {parameters.get('sampler', 'N/A')}")

        max_retries = 5
        last_exception = None

        for attempt in range(1, max_retries + 1):
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
            
            # V4 특화 설정
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

                # AppContext를 통해 CharacterModule 인스턴스를 찾습니다.
                char_module: 'CharacterModule' = self.app_context.middle_section_controller.get_module_instance("CharacterModule")

                if char_module and char_module.activate_checkbox.isChecked():
                    print("✅ 캐릭터 모듈 활성화됨. 파라미터를 가져옵니다.")
                    # 캐릭터 모듈에서 처리된 파라미터를 가져옵니다.
                    # get_parameters는 와일드카드 처리까지 완료된 결과를 반환합니다.
                    char_params = char_module.get_parameters()
                    
                    if char_params and char_params.get("characters"):
                        characters = char_params["characters"]
                        ucs = char_params["uc"]
                        
                        # API 페이로드에 맞게 데이터 가공
                        for i, prompt in enumerate(characters):
                            api_parameters['v4_prompt']['caption']['char_captions'].append({
                                'char_caption': prompt,
                                'centers': [{"x": 0.5, "y": 0.5}] # TODO: 좌표 시스템 연동 필요
                            })
                            api_parameters['v4_negative_prompt']['caption']['char_captions'].append({
                                'char_caption': ucs[i] if i < len(ucs) else "",
                                'centers': [{"x": 0.5, "y": 0.5}]
                            })
            
            # 최종 페이로드 구성
            payload = {
                "input": params.get('input', ''),
                "model": model_name,
                "action": "generate",
                "parameters": api_parameters
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            print("📤 NAI API 요청 페이로드:", payload)
            
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
                webui_url = f"https://{webui_url}"
            
            # WEBUI API 엔드포인트 URL 구성
            api_endpoint = f"{webui_url}/sdapi/v1/txt2img"
            
            # WEBUI API 페이로드 구성
            payload = {
                "prompt": params.get('input', ''),
                "negative_prompt": params.get('negative_prompt', ''),
                "width": params.get('width', 1024),
                "height": params.get('height', 1216),
                "steps": params.get('steps', 28),
                "cfg_scale": params.get('cfg_scale', 5.0),
                "seed": params.get('seed', -1),  # WEBUI는 -1이 랜덤 시드
                "sampler_name": params.get('sampler', 'Euler a'),
                "scheduler": params.get('scheduler', 'SGM Uniform'),
                "n_iter": 1,  # 배치 수
                "batch_size": 1,  # 배치 크기
                "restore_faces": False,
                "tiling": False,
                "enable_hr": params.get('enable_hr', False),
                "denoising_strength": params.get('denoising_strength', 0.5),
                "save_images": True,
                "send_images": True,
                "do_not_save_samples": False,
                "do_not_save_grid": True
            }
            
            # Hires-fix 관련 파라미터 (enable_hr이 True인 경우에만)
            if payload["enable_hr"]:
                payload.update({
                    "hr_scale": params.get('hr_scale', 1.5),
                    "hr_upscaler": params.get('hr_upscaler', 'Lanczos'),
                    "hr_second_pass_steps": params.get('steps', 28) // 2,  # 일반적으로 절반
                    "hr_resize_x": int(payload["width"] * params.get('hr_scale', 1.5)),
                    "hr_resize_y": int(payload["height"] * params.get('hr_scale', 1.5))
                })
            
            # Custom API 파라미터 병합 (있는 경우)
            if params.get('use_custom_api_params', False):
                custom_params_text = params.get('custom_api_params', '')
                if custom_params_text.strip():
                    try:
                        import json
                        custom_params = json.loads(custom_params_text)
                        if isinstance(custom_params, dict):
                            payload.update(custom_params)
                            print(f"✅ Custom API 파라미터 적용됨: {len(custom_params)}개")
                    except json.JSONDecodeError as e:
                        print(f"⚠️ Custom API 파라미터 JSON 파싱 실패: {e}")
            
            print(f"📤 WEBUI API 요청 페이로드 요약:")
            print(f"   - 엔드포인트: {api_endpoint}")
            print(f"   - 해상도: {payload['width']}x{payload['height']}")
            print(f"   - 샘플러: {payload['sampler_name']}")
            print(f"   - 스케줄러: {payload['scheduler']}")
            print(f"   - Steps: {payload['steps']}, CFG: {payload['cfg_scale']}")
            print(f"   - Hires-fix: {payload['enable_hr']}")
            
            # API 요청 전송
            headers = {
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                api_endpoint,
                headers=headers,
                json=payload,
                timeout=300  # WEBUI는 생성 시간이 더 오래 걸릴 수 있음
            )
            response.raise_for_status()
            
            # 응답 처리
            result = response.json()
            
            if 'images' in result and len(result['images']) > 0:
                # 첫 번째 이미지 데이터 추출
                image_b64 = result['images'][0]
                
                # Base64 디코딩
                import base64
                from io import BytesIO
                from PIL import Image
                
                image_data = base64.b64decode(image_b64)
                image = Image.open(BytesIO(image_data))
                
                # 생성 정보 추출 (있는 경우)
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
        
        except requests.exceptions.HTTPError as e:
            error_message = f"WEBUI API 오류 (HTTP {e.response.status_code})"
            if e.response.text:
                try:
                    error_data = e.response.json()
                    if 'detail' in error_data:
                        error_message += f": {error_data['detail']}"
                    elif 'error' in error_data:
                        error_message += f": {error_data['error']}"
                    else:
                        error_message += f": {e.response.text}"
                except:
                    error_message += f": {e.response.text}"
            
            print(f"❌ {error_message}")
            return {'status': 'error', 'message': error_message}
            
        except requests.exceptions.Timeout:
            error_message = "WEBUI API 요청 시간 초과 (5분)"
            print(f"❌ {error_message}")
            return {'status': 'error', 'message': error_message}
            
        except Exception as e:
            print(f"❌ WEBUI API 호출 중 예외 발생: {e}")
            return {'status': 'error', 'message': str(e)}

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
            workflow = self.workflow_manager.create_workflow_from_params(params)
            
            # 5. 워크플로우 유효성 검사
            if not self.workflow_manager.validate_workflow(workflow):
                raise Exception("워크플로우 유효성 검사 실패")
            
            # 디버그 정보 출력
            model_sampling = workflow.get('8', {}).get('inputs', {})
            sampling_mode = model_sampling.get('sampling', 'eps')
            zsnr = model_sampling.get('zsnr', False)
            
            print(f"📤 ComfyUI 워크플로우 생성 완료:")
            print(f"   - 해상도: {workflow['5']['inputs']['width']}x{workflow['5']['inputs']['height']}")
            print(f"   - 모델: {workflow['1']['inputs']['ckpt_name']}")
            print(f"   - 샘플러: {workflow['4']['inputs']['sampler_name']}")
            print(f"   - 스텝: {workflow['4']['inputs']['steps']}, CFG: {workflow['4']['inputs']['cfg']}")
            print(f"   - 샘플링 모드: {sampling_mode}, ZSNR: {zsnr}")
            
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