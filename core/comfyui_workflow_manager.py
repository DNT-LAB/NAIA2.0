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
        self.user_workflow: Optional[Dict[str, Any]] = None
        self.user_workflow_ui: Optional[Dict[str, Any]] = None # [추가] UI 형식 워크플로우 저장
        self.user_workflow_node_map: Optional[Dict[str, str]] = None # 검증 후 생성된 노드 맵

        
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
        
        # 2. 프롬프트 설정 (주석 및 개행문자 처리)
        if 'input' in params:
            cleaned_input = self._clean_prompt(params['input'])
            workflow["2"]["inputs"]["text"] = cleaned_input
        
        # 3. 네거티브 프롬프트 설정 (주석 및 개행문자 처리)
        if 'negative_prompt' in params:
            cleaned_negative = self._clean_prompt(params['negative_prompt'])
            workflow["3"]["inputs"]["text"] = cleaned_negative
        
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
            ksampler["sampler_name"] = params['sampler']
        
        if 'scheduler' in params:
            ksampler["scheduler"] = params['scheduler']
        
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

    def clear_user_workflow(self):
        """저장된 사용자 워크플로우를 제거하고 기본 워크플로우로 되돌립니다."""
        self.user_workflow = None
        self.user_workflow_ui = None
        self.user_workflow_node_map = None
        print("🔄 사용자 워크플로우가 초기화되었습니다. 기본 워크플로우를 사용합니다.")


    def load_workflow_from_metadata(self, comfyui_metadata: Dict[str, Any]) -> bool:
        """
        이미지 메타데이터에서 workflow와 prompt API를 추출하고 유효성을 검사합니다.
        성공 시, 해당 워크플로우를 클래스 내에 저장합니다.
        """
        try:
            workflow_str = comfyui_metadata.get('workflow') or comfyui_metadata.get('workflow_api')
            prompt_str = comfyui_metadata.get('prompt')

            if not workflow_str or not prompt_str:
                print("⚠️ 메타데이터에 'workflow' 또는 'prompt' 정보가 없습니다.")
                return False

            workflow = json.loads(workflow_str)
            prompt_api = json.loads(prompt_str)

            # 워크플로우 유효성 검사 및 노드 맵 생성
            is_valid, node_map = self.validate_and_map_workflow(workflow)

            if not is_valid:
                print(f"❌ 불러온 워크플로우가 유효하지 않습니다: {node_map}")
                self.clear_user_workflow() # 유효하지 않으면 초기화
                return False

            # [핵심] 워크플로우 형식에 따라 저장
            if 'nodes' in workflow: # UI 형식
                self.user_workflow_ui = workflow
                self.user_workflow = prompt_api # API 형식
            else: # API 형식
                self.user_workflow = workflow
                self.user_workflow_ui = None # UI 형식 정보 없음

            self.user_workflow_node_map = node_map
            
            print("✅ 사용자 워크플로우를 성공적으로 로드하고 검증했습니다.")
            print(f"   - 노드 맵: {node_map}")
            return True

        except (json.JSONDecodeError, TypeError) as e:
            print(f"❌ 메타데이터 파싱 실패: {e}")
            self.clear_user_workflow()
            return False

    def _generate_random_seed(self) -> int:
        """랜덤 시드 생성"""
        import random
        return random.randint(0, 2**32 - 1)
    
    def _clean_prompt(self, prompt: str) -> str:
        """입력 프롬프트에서 주석 및 개행문자 제거 (api_service.py와 동일한 로직)"""
        if not isinstance(prompt, str):
            return prompt
            
        cleaned_tags = []
        for tag in prompt.split(','):
            processed_tag = tag.replace('\n', '').strip()
            if processed_tag and not processed_tag.startswith('#'):
                cleaned_tags.append(processed_tag)
        
        cleaned_prompt = ', '.join(cleaned_tags)
        if prompt != cleaned_prompt:
            print(f"[CLEAN] ComfyUIWorkflowManager: 주석/개행문자 제거 후 프롬프트: '{cleaned_prompt[:100]}...'")
        
        return cleaned_prompt

    def validate_and_map_workflow(self, workflow: Dict[str, Any]) -> tuple[bool, Dict[str, Any]]:
        """
        워크플로우의 필수 노드들을 class_type으로 찾아 ID를 매핑합니다.
        [수정] UI 형식('nodes' 리스트)과 API 형식(노드 딕셔너리)을 모두 처리하도록 개선되었습니다.
        """
        nodes_by_id = {}
        links_data = None
        is_ui_format = False

        # --- [핵심] 1. 워크플로우 형식 감지 및 데이터 정규화 ---
        if 'nodes' in workflow and isinstance(workflow.get('nodes'), list):
            # A. UI 형식일 경우: nodes 리스트를 ID를 키로 하는 딕셔너리로 변환
            is_ui_format = True
            nodes_by_id = {str(node['id']): node for node in workflow['nodes']}
            links_data = workflow.get('links', [])
        else:
            # B. API/기본 형식일 경우: workflow 자체가 노드 딕셔너리임
            is_ui_format = False
            nodes_by_id = workflow

        if not nodes_by_id:
            return False, {"error": "분석할 노드 데이터를 찾을 수 없습니다."}

        node_map = {}
        # [수정] KSampler 외에 다른 커스텀 샘플러도 인식하도록 리스트 사용
        recognized_sampler_types = ["KSampler", "SamplerCustom"]
        
        required_nodes = {
            "CheckpointLoaderSimple": "checkpoint_loader",
            "CLIPTextEncode": "prompt",
            # "KSampler": "sampler", # 특정 샘플러 대신 리스트 사용
            "EmptyLatentImage": "latent_image",
            "VAEDecode": "vae_decode",
            "SaveImage": "save_image",
            "PreviewImage": "preview_image",
            "ModelSamplingDiscrete" : "model_sampler",
            "AlignYourStepsScheduler": "ays_scheduler" # [추가]
        }
        
        found_nodes = {key: [] for key in required_nodes.keys()}
        found_sampler_nodes = []

        # --- 2. 노드 순회 및 분류 ---
        for node_id, node_data in nodes_by_id.items():
            class_type = node_data.get("type") or node_data.get("class_type")
            
            if class_type in required_nodes:
                found_nodes[class_type].append(node_id)
            
            # [핵심 수정] 인식 가능한 샘플러 타입인지 확인
            if class_type in recognized_sampler_types:
                found_sampler_nodes.append(node_id)

        # --- 3. 필수 노드 존재 여부 확인 ---
        if not found_nodes["CheckpointLoaderSimple"]: return False, {"error": "CheckpointLoaderSimple 노드를 찾을 수 없습니다."}
        if len(found_nodes["CLIPTextEncode"]) < 2: return False, {"error": "CLIPTextEncode 노드가 2개 미만입니다 (Prompt/Negative)."}
        
        # [핵심 수정] KSampler 대신 인식된 샘플러가 있는지 확인
        if not found_sampler_nodes:
            return False, {"error": f"필수 샘플러 노드({'/'.join(recognized_sampler_types)})를 찾을 수 없습니다."}
            
        if not found_nodes["ModelSamplingDiscrete"]: return False, {"error": "ModelSamplingDiscrete 노드를 찾을 수 없습니다."}
        
        node_map["checkpoint_loader"] = found_nodes["CheckpointLoaderSimple"][0]
        
        # --- 4. 샘플러에 연결된 프롬프트 노드 찾기 ---
        # [핵심 수정] 발견된 첫 번째 샘플러를 기준으로 삼음
        sampler_node_id = found_sampler_nodes[0]
        sampler_inputs = nodes_by_id[sampler_node_id]["inputs"]
        
        if is_ui_format:
            # UI 형식의 링크 처리
            positive_link_id = next((slot.get("link") for slot in sampler_inputs if slot.get("name") == "positive"), None)
            negative_link_id = next((slot.get("link") for slot in sampler_inputs if slot.get("name") == "negative"), None)
            
            links_by_id = {link[0]: link for link in links_data}
            if positive_link_id in links_by_id:
                node_map["positive_prompt"] = str(links_by_id[positive_link_id][1])
            if negative_link_id in links_by_id:
                node_map["negative_prompt"] = str(links_by_id[negative_link_id][1])
        else:
            # API/기본 형식의 링크 처리 (더 직접적)
            if isinstance(sampler_inputs.get("positive"), list):
                node_map["positive_prompt"] = sampler_inputs["positive"][0]
            if isinstance(sampler_inputs.get("negative"), list):
                node_map["negative_prompt"] = sampler_inputs["negative"][0]

        if "positive_prompt" not in node_map or "negative_prompt" not in node_map:
            return False, {"error": "샘플러에 연결된 Prompt/Negative 노드를 특정할 수 없습니다."}

        node_map["sampler"] = sampler_node_id
        if found_nodes["EmptyLatentImage"]:
            node_map["latent_image"] = found_nodes["EmptyLatentImage"][0]

        # [추가] AlignYourStepsScheduler 노드 ID 저장
        if found_nodes.get("AlignYourStepsScheduler"):
            node_map["ays_scheduler"] = found_nodes["AlignYourStepsScheduler"][0]

        node_map["model_sampler"] = found_nodes["ModelSamplingDiscrete"][0]
        
        return True, node_map

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
    
    def apply_params_to_workflow(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        현재 활성화된 워크플로우(사용자 또는 기본)에 UI 파라미터를 적용합니다.
        """
        if self.user_workflow and self.user_workflow_node_map:
            workflow = copy.deepcopy(self.user_workflow)
            node_map = self.user_workflow_node_map
            workflow_ui = copy.deepcopy(self.user_workflow_ui)
        else:
            # 기본 워크플로우 사용 시, 맵을 즉석에서 생성
            is_valid, node_map = self.validate_and_map_workflow(self.base_workflow)
            if not is_valid: 
                print("❌ 기본 워크플로우가 유효하지 않습니다.")
                return None
            workflow = copy.deepcopy(self.base_workflow)
            workflow_ui = None # 기본 워크플로우는 UI 형식이 없음

        try:
            # 1. 모델 설정
            workflow[node_map["checkpoint_loader"]]["inputs"]["ckpt_name"] = params['model']
            
            # 2. 프롬프트 설정 (주석 및 개행문자 처리)
            # 입력 프롬프트 클리닝
            cleaned_input = self._clean_prompt(params['input'])
            workflow[node_map["positive_prompt"]]["inputs"]["text"] = cleaned_input
            
            # 네거티브 프롬프트 클리닝
            cleaned_negative = self._clean_prompt(params['negative_prompt'])
            workflow[node_map["negative_prompt"]]["inputs"]["text"] = cleaned_negative

            # 3. 샘플러 설정 (KSampler와 SamplerCustom 분기 처리)
            sampler_node_id = node_map["sampler"]
            sampler_node_api = workflow[sampler_node_id]
            
            # UI 형식의 노드 찾기 (workflow_ui가 있을 경우)
            sampler_node_ui = None
            if workflow_ui and 'nodes' in workflow_ui:
                for node in workflow_ui['nodes']:
                    if str(node.get('id')) == sampler_node_id:
                        sampler_node_ui = node
                        break
            
            sampler_class_type = sampler_node_api.get("class_type")

            if sampler_class_type == "KSampler":
                sampler_inputs = sampler_node_api["inputs"]
                sampler_inputs["seed"] = params['seed'] if params['seed'] != -1 else self._generate_random_seed()
                sampler_inputs["steps"] = params['steps']
                sampler_inputs["cfg"] = params['cfg_scale']
                sampler_inputs["sampler_name"] = params['sampler']
                sampler_inputs["scheduler"] = params['scheduler']

            elif sampler_class_type == "SamplerCustom" and sampler_node_ui:
                # SamplerCustom은 widgets_values를 통해 파라미터를 제어
                # [add_noise, seed, control_after_generate, cfg]
                widgets = sampler_node_ui.get('widgets_values', [])
                if len(widgets) >= 4:
                    original_seed = widgets[1]
                    original_cfg = widgets[3]
                    
                    new_seed = params['seed'] if params['seed'] != -1 else self._generate_random_seed()
                    new_cfg = params['cfg_scale']

                    # API 워크플로우에서 원래 값들을 찾아 새 값으로 교체
                    # 이 방식은 input의 키 이름을 몰라도 값을 기반으로 교체 가능
                    for key, value in sampler_node_api["inputs"].items():
                        if value == original_seed:
                            sampler_node_api["inputs"][key] = new_seed
                            print(f"✅ SamplerCustom 시드 변경: {original_seed} -> {new_seed}")
                        elif value == original_cfg:
                            sampler_node_api["inputs"][key] = new_cfg
                            print(f"✅ SamplerCustom CFG 변경: {original_cfg} -> {new_cfg}")
                else:
                    print(f"⚠️ SamplerCustom (ID: {sampler_node_id})의 위젯 값이 예상과 다릅니다.")

            # 4. AlignYourStepsScheduler의 Steps 설정 (존재하는 경우)
            if "ays_scheduler" in node_map:
                ays_node_id = node_map["ays_scheduler"]
                ays_node_api = workflow[ays_node_id]
                
                ays_node_ui = None
                if workflow_ui and 'nodes' in workflow_ui:
                    for node in workflow_ui['nodes']:
                        if str(node.get('id')) == ays_node_id:
                            ays_node_ui = node
                            break
                
                if ays_node_ui:
                    widgets = ays_node_ui.get('widgets_values', [])
                    if len(widgets) >= 2:
                        original_steps = widgets[1]
                        new_steps = params['steps']
                        
                        for key, value in ays_node_api["inputs"].items():
                            if value == original_steps:
                                ays_node_api["inputs"][key] = new_steps
                                print(f"✅ AlignYourStepsScheduler Steps 변경: {original_steps} -> {new_steps}")
                                break # 첫 번째 일치 항목만 변경

            # 5. 해상도 설정
            if "latent_image" in node_map:
                 workflow[node_map["latent_image"]]["inputs"]["width"] = params['width']
                 workflow[node_map["latent_image"]]["inputs"]["height"] = params['height']

            # 6. ModelSamplingDiscrete 설정 추가 ---
            if "model_sampler" in node_map:
                model_sampler_node = workflow[node_map["model_sampler"]]["inputs"]
                
                # sampling_mode가 params에 있으면 그 값을 사용, 없으면 기존 값 유지
                if 'sampling_mode' in params:
                    model_sampler_node["sampling"] = params['sampling_mode']
                
                # zsnr이 params에 있으면 그 값을 사용, 없으면 기존 값 유지
                if 'zsnr' in params:
                    model_sampler_node["zsnr"] = params['zsnr']
            
            return workflow
            
        except KeyError as e:
            print(f"❌ 워크플로우에 파라미터 적용 실패. 누락된 노드 또는 맵 키: {e}")
            return None
    
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
        

    def analyze_workflow_for_ui(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        워크플로우를 상세히 분석하여 UI에 표시할 검증 결과를 반환합니다.
        'workflow'(UI 형식)와 'prompt'(API 형식) JSON을 모두 처리할 수 있도록 개선되었습니다.
        """
        result = {
            "success": False,
            "required": [],
            "custom": [],
            "error_message": ""
        }
        # [수정] KSampler 외 커스텀 샘플러 지원
        recognized_sampler_types = {"KSampler", "SamplerCustom"}
        required_node_types = {
            "CheckpointLoaderSimple", "CLIPTextEncode", 
            "EmptyLatentImage", "VAEDecode", "SaveImage", "PreviewImage"
        }
        
        try:
            workflow_str = metadata.get('workflow') or metadata.get('workflow_api')
            prompt_str = metadata.get('prompt')
            
            all_nodes = []
            is_ui_format = False

            # 1. 워크플로우 데이터 소스 결정 및 노드 리스트 생성
            if workflow_str:
                parsed_workflow = json.loads(workflow_str)
                if 'nodes' in parsed_workflow and isinstance(parsed_workflow['nodes'], list):
                    all_nodes = parsed_workflow['nodes']
                    is_ui_format = True
            
            if not all_nodes and prompt_str:
                parsed_prompt = json.loads(prompt_str)
                # API 형식의 딕셔너리를 UI 형식의 리스트로 변환
                all_nodes = list(parsed_prompt.values())
                is_ui_format = False

            if not all_nodes:
                result['error_message'] = "분석할 워크플로우 데이터를 찾을 수 없습니다."
                return result

            # 2. 노드 분석
            found_required = set()
            found_sampler = None
            
            # class_type 키 이름 결정
            type_key = "type" if is_ui_format else "class_type"

            for node in all_nodes:
                class_type = node.get(type_key)
                if class_type in required_node_types:
                    result['required'].append(("PASS", class_type))
                    found_required.add(class_type)
                elif class_type in recognized_sampler_types:
                    # 여러 샘플러가 있을 경우 첫 번째 것만 인정
                    if not found_sampler:
                        found_sampler = class_type
                else:
                    result['custom'].append(class_type)

            # 3. 최종 유효성 검사
            # SaveImage 또는 PreviewImage 둘 중 하나만 있으면 됨
            if "SaveImage" in found_required or "PreviewImage" in found_required:
                required_node_types.discard("SaveImage")
                required_node_types.discard("PreviewImage")

            missing_nodes = required_node_types - found_required
            
            # 샘플러 노드 검증
            if found_sampler:
                result['required'].append(("PASS", found_sampler))
            else:
                result['required'].append(("FAIL", " / ".join(recognized_sampler_types)))
                result['success'] = False
                # 샘플러가 없으면 더 이상 진행하지 않고 결과 반환
                for missing in missing_nodes:
                    result['required'].append(("FAIL", missing))
                return result

            # 나머지 필수 노드 검증
            for missing in missing_nodes:
                result['required'].append(("FAIL", missing))
            
            result['success'] = not bool(missing_nodes)

        except json.JSONDecodeError:
            result['error_message'] = "워크플로우 JSON 데이터가 손상되었습니다."
        except Exception as e:
            result['error_message'] = str(e)

        return result