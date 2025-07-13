import requests
import zipfile
import io
from PIL import Image
from typing import Dict, Any, TYPE_CHECKING

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
    NAI_V3_API_URL = "https://image.novelai.net/ai/generate-image"
    
    def call_generation_api(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        파라미터의 'api_mode'에 따라 적절한 API 호출 메서드로 분기합니다.
        """
        api_mode = parameters.get('api_mode', 'NAI') # 기본값은 NAI
        
        print(f"🛰️ APIService: '{api_mode}' 모드로 API 호출을 시작합니다.")

        if api_mode == "NAI":
            return self._call_nai_api(parameters)
        elif api_mode == "WEBUI":
            return self._call_webui_api(parameters)
        else:
            return {'status': 'error', 'message': f"지원하지 않는 API 모드: {api_mode}"}

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
        """Stable Diffusion WebUI API를 호출합니다. (TODO)"""
        print("🚧 WebUI API 호출 기능은 아직 구현되지 않았습니다.")
        # TODO: WebUI API 페이로드 구성 및 요청 로직 구현
        # url = params.get('credential')
        # response = requests.post(f"{url}/sdapi/v1/txt2img", json=webui_payload)
        return {'status': 'error', 'message': 'WebUI API 기능은 미구현 상태입니다.'}

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