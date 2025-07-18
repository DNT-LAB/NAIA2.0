"""
ComfyUI API 연동을 위한 유틸리티 클래스
"""
import requests
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

class ComfyUIAPIUtils:
    """ComfyUI API와의 통신을 위한 유틸리티 클래스"""
    
    @staticmethod
    def test_connection(url: str) -> bool:
        """ComfyUI 서버 연결 테스트"""
        try:
            # URL 정규화
            if not url.startswith(('http://', 'https://')):
                url = f"http://{url}"
            
            # /system_stats 엔드포인트로 연결 테스트
            response = requests.get(f"{url}/system_stats", timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"❌ ComfyUI 연결 테스트 실패: {e}")
            return False
    
    @staticmethod
    def get_system_info(url: str) -> Optional[Dict[str, Any]]:
        """ComfyUI 시스템 정보 조회"""
        try:
            if not url.startswith(('http://', 'https://')):
                url = f"http://{url}"
            
            response = requests.get(f"{url}/system_stats", timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"❌ ComfyUI 시스템 정보 조회 실패: {e}")
            return None
    
    @staticmethod
    def get_object_info(url: str) -> Optional[Dict[str, Any]]:
        """ComfyUI 노드 정보 조회 (/object_info)"""
        try:
            if not url.startswith(('http://', 'https://')):
                url = f"http://{url}"
            
            response = requests.get(f"{url}/object_info", timeout=15)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"❌ ComfyUI 객체 정보 조회 실패: {e}")
            return None
    
    @staticmethod
    def get_model_list(url: str) -> List[str]:
        """CheckpointLoaderSimple에서 모델 목록 추출"""
        try:
            object_info = ComfyUIAPIUtils.get_object_info(url)
            if not object_info:
                return []
            
            # CheckpointLoaderSimple 노드에서 ckpt_name 옵션 추출
            checkpoint_loader = object_info.get('CheckpointLoaderSimple', {})
            input_info = checkpoint_loader.get('input', {})
            ckpt_name_info = input_info.get('required', {}).get('ckpt_name', [])
            
            if isinstance(ckpt_name_info, list) and len(ckpt_name_info) > 0:
                # 첫 번째 요소가 모델 목록
                models = ckpt_name_info[0]
                if isinstance(models, list):
                    return models
            
            return []
        except Exception as e:
            print(f"❌ ComfyUI 모델 목록 조회 실패: {e}")
            return []
    
    @staticmethod
    def get_sampler_list(url: str) -> List[str]:
        """KSampler에서 sampler_name 옵션 추출"""
        try:
            object_info = ComfyUIAPIUtils.get_object_info(url)
            if not object_info:
                return []
            
            # KSampler 노드에서 sampler_name 옵션 추출
            ksampler = object_info.get('KSampler', {})
            input_info = ksampler.get('input', {})
            sampler_info = input_info.get('required', {}).get('sampler_name', [])
            
            if isinstance(sampler_info, list) and len(sampler_info) > 0:
                samplers = sampler_info[0]
                if isinstance(samplers, list):
                    return samplers
            
            # 기본 샘플러 목록 반환
            return ["euler", "euler_ancestral", "heun", "dpm_2", "dpm_2_ancestral", 
                   "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral", 
                   "dpmpp_sde", "dpmpp_2m", "ddim", "plms"]
        except Exception as e:
            print(f"❌ ComfyUI 샘플러 목록 조회 실패: {e}")
            return ["euler", "euler_ancestral", "heun", "dpm_2"]
    
    @staticmethod
    def get_scheduler_list(url: str) -> List[str]:
        """KSampler에서 scheduler 옵션 추출"""
        try:
            object_info = ComfyUIAPIUtils.get_object_info(url)
            if not object_info:
                return []
            
            # KSampler 노드에서 scheduler 옵션 추출
            ksampler = object_info.get('KSampler', {})
            input_info = ksampler.get('input', {})
            scheduler_info = input_info.get('required', {}).get('scheduler', [])
            
            if isinstance(scheduler_info, list) and len(scheduler_info) > 0:
                schedulers = scheduler_info[0]
                if isinstance(schedulers, list):
                    return schedulers
            
            # 기본 스케줄러 목록 반환
            return ["normal", "karras", "exponential", "simple", "ddim_uniform"]
        except Exception as e:
            print(f"❌ ComfyUI 스케줄러 목록 조회 실패: {e}")
            return ["normal", "karras", "exponential", "simple"]
    
    @staticmethod
    def get_sampling_modes() -> List[str]:
        """ModelSamplingDiscrete에서 지원하는 샘플링 모드 목록"""
        return ["eps", "v_prediction"]
    
    @staticmethod
    def validate_url(url: str) -> str:
        """URL 유효성 검사 및 정규화"""
        if not url:
            raise ValueError("URL이 비어있습니다.")
        
        # 프로토콜 추가 (필요시)
        if not url.startswith(('http://', 'https://')):
            url = f"http://{url}"
        
        # 기본 포트 확인 (ComfyUI 기본 포트: 8188)
        if ':' not in url.replace('http://', '').replace('https://', ''):
            url = f"{url}:8188"
        
        return url
    
    @staticmethod
    def get_queue_info(url: str) -> Optional[Dict[str, Any]]:
        """ComfyUI 큐 정보 조회"""
        try:
            if not url.startswith(('http://', 'https://')):
                url = f"http://{url}"
            
            response = requests.get(f"{url}/queue", timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"❌ ComfyUI 큐 정보 조회 실패: {e}")
            return None
    
    @staticmethod
    def get_history(url: str, limit: int = 10) -> Optional[Dict[str, Any]]:
        """ComfyUI 생성 히스토리 조회"""
        try:
            if not url.startswith(('http://', 'https://')):
                url = f"http://{url}"
            
            response = requests.get(f"{url}/history?limit={limit}", timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"❌ ComfyUI 히스토리 조회 실패: {e}")
            return None
    
    @staticmethod
    def clear_queue(url: str) -> bool:
        """ComfyUI 큐 비우기"""
        try:
            if not url.startswith(('http://', 'https://')):
                url = f"http://{url}"
            
            response = requests.post(f"{url}/queue", 
                                   json={"clear": True}, 
                                   timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"❌ ComfyUI 큐 정리 실패: {e}")
            return False