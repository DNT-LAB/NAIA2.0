# core/comfyui_workflow_manager.py
import json
import copy
import uuid
from typing import Dict, Any, List, Optional
from pathlib import Path

class ComfyUIWorkflowManager:
    """ComfyUI 워크플로우를 관리하고 파라미터를 치환하는 클래스"""
    
    def __init__(self):
        self.base_workflow = self._load_base_workflow()
        self.custom_workflows = {}
        
    def _load_base_workflow(self) -> Dict[str, Any]:
        """기본 txt2img 워크플로우 로드 (ModelSamplingDiscrete 포함)"""
        return {
            "1": {
                "inputs": {
                    "ckpt_name": "v1-5-pruned-emaonly.ckpt"
                },
                "class_type": "CheckpointLoaderSimple",
                "_meta": {"title": "Load Checkpoint"}
            },
            "2": {
                "inputs": {
                    "text": "beautiful scenery nature glass bottle landscape, purple galaxy bottle",
                    "clip": ["1", 1]
                },
                "class_type": "CLIPTextEncode",
                "_meta": {"title": "CLIP Text Encode (Prompt)"}
            },
            "3": {
                "inputs": {
                    "text": "text, watermark",
                    "clip": ["1", 1]
                },
                "class_type": "CLIPTextEncode",
                "_meta": {"title": "CLIP Text Encode (Negative)"}
            },
            "4": {
                "inputs": {
                    "seed": 156680208750013,
                    "steps": 20,
                    "cfg": 8.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["8", 0],  # ModelSamplingDiscrete 출력으로 변경
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["5", 0]
                },
                "class_type": "KSampler",
                "_meta": {"title": "KSampler"}
            },
            "5": {
                "inputs": {
                    "width": 512,
                    "height": 512,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage",
                "_meta": {"title": "Empty Latent Image"}
            },
            "6": {
                "inputs": {
                    "samples": ["4", 0],
                    "vae": ["1", 2]
                },
                "class_type": "VAEDecode",
                "_meta": {"title": "VAE Decode"}
            },
            "7": {
                "inputs": {
                    "images": ["6", 0]
                },
                "class_type": "PreviewImage",
                "_meta": {"title": "Preview Image"} 
            },
            "8": {
                "inputs": {
                    "sampling": "eps",  # 기본값: eps (v_prediction도 가능)
                    "zsnr": False,
                    "model": ["1", 0]  # CheckpointLoader에서 모델 입력
                },
                "class_type": "ModelSamplingDiscrete",
                "_meta": {"title": "ModelSamplingDiscrete"}
            }
        }
    
    def create_workflow_from_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """NAIA 파라미터를 ComfyUI 워크플로우로 변환"""
        workflow = copy.deepcopy(self.base_workflow)
        
        # 1. 체크포인트 모델 설정
        if 'model' in params:
            workflow["1"]["inputs"]["ckpt_name"] = params['model']
        
        # 2. 프롬프트 설정
        if 'input' in params:
            workflow["2"]["inputs"]["text"] = params['input']
        
        # 3. 네거티브 프롬프트 설정
        if 'negative_prompt' in params:
            workflow["3"]["inputs"]["text"] = params['negative_prompt']
        
        # 4. KSampler 파라미터 설정
        ksampler = workflow["4"]["inputs"]
        
        # 시드 설정
        if 'seed' in params:
            if params['seed'] == -1:
                ksampler["seed"] = self._generate_random_seed()
            else:
                ksampler["seed"] = params['seed']
        
        # 샘플링 파라미터
        if 'steps' in params:
            ksampler["steps"] = params['steps']
        
        if 'cfg_scale' in params:
            ksampler["cfg"] = params['cfg_scale']
        
        if 'sampler' in params:
            ksampler["sampler_name"] = self._map_sampler(params['sampler'])
        
        if 'scheduler' in params:
            ksampler["scheduler"] = self._map_scheduler(params['scheduler'])
        
        # 5. 해상도 설정
        latent_image = workflow["5"]["inputs"]
        if 'width' in params:
            latent_image["width"] = params['width']
        if 'height' in params:
            latent_image["height"] = params['height']
        
        # 6. 파일명 접두사 설정
        if 'filename_prefix' in params:
            workflow["7"]["inputs"]["filename_prefix"] = params['filename_prefix']
        
        # 7. ModelSamplingDiscrete 설정 (v-prediction 지원)
        model_sampling = workflow["8"]["inputs"]
        
        # v-prediction 모드 설정
        if 'sampling_mode' in params:
            sampling_mode = params['sampling_mode'].lower()
            if sampling_mode in ['eps', 'v_prediction']:
                model_sampling["sampling"] = sampling_mode
        
        # ZSNR (Zero Signal-to-Noise Ratio) 설정
        if 'zsnr' in params:
            model_sampling["zsnr"] = bool(params['zsnr'])
        
        return workflow
    
    def _generate_random_seed(self) -> int:
        """랜덤 시드 생성"""
        import random
        return random.randint(0, 2**32 - 1)
    
    def _map_sampler(self, naia_sampler: str) -> str:
        """NAIA 샘플러를 ComfyUI 샘플러로 매핑"""
        mapping = {
            "k_euler": "euler",
            "k_euler_ancestral": "euler_ancestral",
            "k_heun": "heun",
            "k_dpm_2": "dpm_2",
            "k_dpm_2_ancestral": "dpm_2_ancestral",
            "k_lms": "lms",
            "k_dpm_fast": "dpm_fast",
            "k_dpm_adaptive": "dpm_adaptive",
            "k_dpmpp_2s_ancestral": "dpmpp_2s_ancestral",
            "k_dpmpp_sde": "dpmpp_sde",
            "k_dpmpp_2m": "dpmpp_2m",
            "ddim": "ddim",
            "plms": "plms"
        }
        return mapping.get(naia_sampler, "euler")  # 기본값: euler
    
    def _map_scheduler(self, naia_scheduler: str) -> str:
        """NAIA 스케줄러를 ComfyUI 스케줄러로 매핑"""
        mapping = {
            "normal": "normal",
            "karras": "karras",
            "exponential": "exponential",
            "simple": "simple",
            "ddim_uniform": "ddim_uniform"
        }
        return mapping.get(naia_scheduler, "normal")  # 기본값: normal
    
    def validate_workflow(self, workflow: Dict[str, Any]) -> bool:
        """워크플로우 유효성 검사"""
        required_nodes = ["1", "2", "3", "4", "5", "6", "7", "8"]  # 노드 8 추가
        
        for node_id in required_nodes:
            if node_id not in workflow:
                print(f"❌ 필수 노드 누락: {node_id}")
                return False
            
            node = workflow[node_id]
            if "class_type" not in node:
                print(f"❌ 노드 {node_id}에 class_type 누락")
                return False
            
            if "inputs" not in node:
                print(f"❌ 노드 {node_id}에 inputs 누락")
                return False
        
        # ModelSamplingDiscrete 노드 특별 검증
        model_sampling_node = workflow["8"]
        if model_sampling_node["class_type"] != "ModelSamplingDiscrete":
            print("❌ 노드 8은 ModelSamplingDiscrete여야 함")
            return False
        
        sampling_value = model_sampling_node["inputs"].get("sampling")
        if sampling_value not in ["eps", "v_prediction"]:
            print(f"❌ 잘못된 sampling 값: {sampling_value}")
            return False
        
        return True
    
    def create_v_prediction_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """v-prediction 전용 워크플로우 생성 (편의 메서드)"""
        params_copy = params.copy()
        params_copy['sampling_mode'] = 'v_prediction'
        return self.create_workflow_from_params(params_copy)
    
    def create_eps_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """eps 전용 워크플로우 생성 (편의 메서드)"""
        params_copy = params.copy()
        params_copy['sampling_mode'] = 'eps'
        return self.create_workflow_from_params(params_copy)
    
    def get_sampling_modes(self) -> List[str]:
        """지원하는 샘플링 모드 목록 반환"""
        return ["eps", "v_prediction"]
    
    def save_workflow(self, workflow: Dict[str, Any], filepath: str):
        """워크플로우를 파일로 저장"""
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(workflow, f, indent=2, ensure_ascii=False)
            print(f"✅ 워크플로우 저장 완료: {filepath}")
        except Exception as e:
            print(f"❌ 워크플로우 저장 실패: {e}")
    
    def load_workflow(self, filepath: str) -> Optional[Dict[str, Any]]:
        """파일에서 워크플로우 로드"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                workflow = json.load(f)
            
            if self.validate_workflow(workflow):
                print(f"✅ 워크플로우 로드 완료: {filepath}")
                return workflow
            else:
                print(f"❌ 워크플로우 유효성 검사 실패: {filepath}")
                return None
        except Exception as e:
            print(f"❌ 워크플로우 로드 실패: {e}")
            return None
    
    def get_workflow_preview(self, workflow: Dict[str, Any]) -> str:
        """워크플로우 미리보기 텍스트 생성"""
        try:
            prompt = workflow["2"]["inputs"]["text"][:50] + "..."
            negative = workflow["3"]["inputs"]["text"][:30] + "..."
            
            ksampler = workflow["4"]["inputs"]
            steps = ksampler["steps"]
            cfg = ksampler["cfg"]
            sampler = ksampler["sampler_name"]
            
            latent = workflow["5"]["inputs"]
            width = latent["width"]
            height = latent["height"]
            
            # ModelSamplingDiscrete 정보 추가
            model_sampling = workflow["8"]["inputs"]
            sampling_mode = model_sampling["sampling"]
            zsnr = model_sampling["zsnr"]
            
            return f"""프롬프트: {prompt}
네거티브: {negative}
해상도: {width}x{height}
스텝: {steps}, CFG: {cfg}, 샘플러: {sampler}
샘플링 모드: {sampling_mode}, ZSNR: {zsnr}"""
        except Exception as e:
            return f"미리보기 생성 실패: {e}"