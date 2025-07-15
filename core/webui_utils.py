# core/webui_utils.py
import requests
from typing import List, Optional

class WebuiAPIUtils:
    """WEBUI API와의 통신을 담당하는 유틸리티 클래스"""
    
    @staticmethod
    def get_current_model(url: str) -> Optional[str]:
        """현재 선택된 모델을 반환합니다."""
        try:
            response = requests.get(f'{url}/sdapi/v1/options', timeout=10)
            response.raise_for_status()
            opt = response.json()
            return opt.get('sd_model_checkpoint', '')
        except Exception as e:
            print(f"❌ 현재 모델 조회 실패: {e}")
            return None

    @staticmethod
    def get_model_list(url: str) -> List[str]:
        """사용 가능한 모델 리스트를 반환합니다."""
        try:
            response = requests.get(f"{url}/sdapi/v1/sd-models", timeout=10)
            response.raise_for_status()
            models_data = response.json()
            
            model_list = []
            for model in models_data:
                if 'title' in model:
                    model_list.append(model['title'])
            
            return model_list
        except Exception as e:
            print(f"❌ 모델 리스트 조회 실패: {e}")
            return []

    @staticmethod
    def get_lora_list(url: str) -> List[str]:
        """사용 가능한 LoRA 리스트를 반환합니다."""
        try:
            response = requests.get(f"{url}/sdapi/v1/loras", timeout=10)
            response.raise_for_status()
            loras_data = response.json()
            
            lora_list = []
            for lora in loras_data:
                if 'name' in lora:
                    lora_list.append(f'<lora:{lora["name"]}:1>')
                    
            return lora_list
        except Exception as e:
            print(f"❌ LoRA 리스트 조회 실패: {e}")
            return []

    @staticmethod
    def get_schedulers_list(url: str) -> List[str]:
        """사용 가능한 스케줄러 리스트를 반환합니다."""
        correction_dict = {
            "automatic": "Automatic",
            "uniform": "Uniform", 
            "exponential": "Exponential",
            "polyexponential": "Polyexponential",
            "sgm_uniform": "SGM Uniform",
            "kl_optimal": "KL Optimal",
            "align_your_steps": "Align Your Steps",
            "simple": "Simple",
            "normal": "Normal",
            "ddim": "DDIM",
            "beta": "Beta"
        }
        
        try:
            response = requests.get(f"{url}/sdapi/v1/schedulers", timeout=10)
            response.raise_for_status()
            schedulers_data = response.json()
            
            schedulers_list = []
            for scheduler in schedulers_data:
                name = scheduler.get("name", "")
                corrected_name = correction_dict.get(name, name)
                schedulers_list.append(corrected_name)
                
            return schedulers_list
        except Exception as e:
            print(f"❌ 스케줄러 리스트 조회 실패: {e}")
            return []

    @staticmethod
    def get_upscaler_list(url: str) -> List[str]:
        """사용 가능한 업스케일러 리스트를 반환합니다."""
        try:
            response = requests.get(f"{url}/sdapi/v1/upscalers", timeout=10)
            response.raise_for_status()
            upscalers_data = response.json()
            
            upscaler_list = []
            for upscaler in upscalers_data:
                if 'name' in upscaler:
                    upscaler_list.append(upscaler['name'])
                    
            return upscaler_list
        except Exception as e:
            print(f"❌ 업스케일러 리스트 조회 실패: {e}")
            return []

    @staticmethod  
    def get_sampler_list(url: str) -> List[str]:
        """사용 가능한 샘플러 리스트를 반환합니다."""
        try:
            response = requests.get(f"{url}/sdapi/v1/samplers", timeout=10)
            response.raise_for_status()
            samplers_data = response.json()
            
            sampler_list = []
            for sampler in samplers_data:
                if 'name' in sampler:
                    sampler_list.append(sampler['name'])
                    
            return sampler_list
        except Exception as e:
            print(f"❌ 샘플러 리스트 조회 실패: {e}")
            return []

    @staticmethod
    def change_model(url: str, title: str) -> bool:
        """모델을 변경합니다."""
        try:
            # 현재 옵션 가져오기
            opt_response = requests.get(f'{url}/sdapi/v1/options', timeout=10)
            opt_response.raise_for_status()
            opt = opt_response.json()
            
            # 모델 변경
            opt['sd_model_checkpoint'] = title
            
            # 옵션 업데이트
            update_response = requests.post(f'{url}/sdapi/v1/options', json=opt, timeout=30)
            update_response.raise_for_status()
            
            # 변경 확인
            verify_response = requests.get(f'{url}/sdapi/v1/options', timeout=10)
            verify_response.raise_for_status()
            verify_opt = verify_response.json()
            
            return verify_opt.get('sd_model_checkpoint') == title
            
        except Exception as e:
            print(f"❌ 모델 변경 실패: {e}")
            return False

    @staticmethod
    def test_connection(url: str) -> bool:
        """WEBUI API 연결을 테스트합니다."""
        try:
            response = requests.get(f"{url}/sdapi/v1/options", timeout=5)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"❌ WEBUI 연결 테스트 실패: {e}")
            return False