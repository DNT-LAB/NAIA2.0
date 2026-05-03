# utils/image_info.py
"""이미지 메타데이터 추출 및 처리 유틸리티"""

import json
import gzip
import re
import io
from typing import Dict, Any, List, Optional, Set, Union
from PIL import Image
from pathlib import Path
try:
    import piexif
    import piexif.helper
    PIEXIF_AVAILABLE = True
except ImportError:
    PIEXIF_AVAILABLE = False
    print("Warning: piexif not available, EXIF metadata extraction limited")


class ImageMetadataExtractor:
    """이미지에서 AI 생성 메타데이터를 추출하는 클래스"""
    
    @staticmethod
    def has_metadata(image_path: Union[str, Path, Image.Image]) -> bool:
        """이미지에 메타데이터가 있는지 확인"""
        try:
            if isinstance(image_path, (str, Path)):
                img = Image.open(image_path)
            else:
                img = image_path

            info = img.info or {}

            # 여러 메타데이터 소스 확인
            if 'Comment' in info:
                print("✅ has_metadata: Comment 필드 발견")
                return True
            if 'parameters' in info:
                print("✅ has_metadata: parameters 필드 발견")
                return True
            if any(key in info for key in ('prompt', 'workflow', 'workflow_api')):
                print("ComfyUI metadata detected")
                return True
            if any(key in info for key in ('naia_generation_params', 'naia_prompt_context', 'naia_api_metadata')):
                print("NAIA metadata detected")
                return True
            if hasattr(img, 'getexif') and img.getexif():
                print("✅ has_metadata: EXIF 데이터 발견")
                return True

            # Stealth PNG 확인 (RGBA만)
            if img.mode == 'RGBA':
                print(f"🔍 has_metadata: RGBA 이미지 감지, stealth PNG 확인 시작...")
                stealth_data = ImageMetadataExtractor._read_stealth_pnginfo(img)
                if stealth_data:
                    print(f"✅ has_metadata: Stealth PNG 데이터 발견 (길이: {len(stealth_data)})")
                    return True
                else:
                    print("❌ has_metadata: Stealth PNG 데이터 없음")
            else:
                print(f"ℹ️ has_metadata: 이미지 모드 {img.mode}, stealth PNG 확인 스킵")

            print("❌ has_metadata: 메타데이터 없음")
            return False

        except Exception as e:
            print(f"❌ 메타데이터 확인 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    @staticmethod
    def extract_metadata(image_path: Union[str, Path, Image.Image]) -> Optional[Dict[str, Any]]:
        """이미지에서 메타데이터 추출"""
        try:
            if isinstance(image_path, (str, Path)):
                img = Image.open(image_path)
            else:
                img = image_path

            # NovelAI 메타데이터도 포함
            result = {}
            info = img.info or {}

            # img.info의 모든 필드를 먼저 수집
            if hasattr(img, 'info') and info:
                result.update(info)
            
            # 1. parameters 필드 확인 (Stable Diffusion WebUI) - 우선순위 높음
            if any(key in info for key in ('prompt', 'workflow', 'workflow_api')):
                parsed = ImageMetadataExtractor._parse_comfyui_metadata(info, img)
                if parsed:
                    result.update(parsed)

            if any(key in info for key in ('naia_generation_params', 'naia_prompt_context', 'naia_api_metadata')):
                parsed = ImageMetadataExtractor._parse_naia_metadata(info, img)
                if parsed:
                    result.update(parsed)

            if 'parameters' in info:
                parsed = ImageMetadataExtractor._parse_parameters(info['parameters'])
                if parsed:
                    result.update(parsed)
            
            # 2. EXIF 데이터 확인 (WebUI JPEG/PNG)
            if 'exif' in info or hasattr(img, 'getexif'):
                exif_data = ImageMetadataExtractor._extract_from_exif(img)
                if exif_data:
                    result.update(exif_data)
            
            # 3. Comment 필드 확인 (NovelAI 등)
            if 'Comment' in info:
                parsed = ImageMetadataExtractor._parse_comment(info['Comment'])
                if parsed:
                    result.update(parsed)
            
            # 4. GIF comment field
            if 'comment' in info:
                comment = info['comment']
                if isinstance(comment, bytes):
                    comment = comment.decode('utf8', errors="ignore")
                if comment:
                    parsed = ImageMetadataExtractor._parse_parameters(comment)
                    if parsed:
                        result.update(parsed)
            
            # 5. Stealth PNG 확인
            if img.mode == 'RGBA':
                stealth_data = ImageMetadataExtractor._read_stealth_pnginfo(img)
                if stealth_data:
                    parsed = ImageMetadataExtractor._parse_stealth_data(stealth_data)
                    if parsed:
                        result.update(parsed)

            return result if result else None
            
        except Exception as e:
            print(f"메타데이터 추출 중 오류: {e}")
            return None
    
    @staticmethod
    def _parse_comment(comment: str) -> Optional[Dict[str, Any]]:
        """Comment 필드 파싱"""
        try:
            # JSON 형식 시도
            if comment.strip().startswith('{'):
                comment_data = json.loads(comment)
                return ImageMetadataExtractor._normalize_nai_comment_data(comment_data)

            # NAI 형식 파싱
            return ImageMetadataExtractor._parse_nai_format(comment)

        except Exception:
            # 일반 텍스트로 반환
            return {'type': 'text', 'content': comment}

    @staticmethod
    def _normalize_nai_comment_data(comment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize NovelAI Comment JSON into the common metadata shape."""
        result = dict(comment_data)
        result['Comment'] = comment_data
        result.setdefault('type', 'nai')
        result.setdefault('prompt', comment_data.get('prompt', ''))
        result.setdefault('uc', comment_data.get('uc', ''))

        parameters = result.get('parameters')
        if not isinstance(parameters, dict):
            parameters = {}

        for key in ['steps', 'scale', 'uncond_scale', 'cfg_rescale', 'seed',
                    'sampler', 'sm', 'sm_dyn', 'noise_schedule']:
            if key in comment_data:
                parameters[key] = comment_data[key]
        result['parameters'] = parameters

        characters = ImageMetadataExtractor._extract_char_captions_from_dict(
            comment_data.get('v4_prompt', {}),
        )
        characters_uc = ImageMetadataExtractor._extract_char_captions_from_dict(
            comment_data.get('v4_negative_prompt', {}),
        )

        if characters:
            result['characters'] = characters
        if characters_uc:
            result['characters_uc'] = characters_uc

        return result

    @staticmethod
    def _parse_comfyui_metadata(
        metadata: Dict[str, Any],
        image: Optional[Image.Image] = None,
    ) -> Optional[Dict[str, Any]]:
        """Normalize ComfyUI prompt/workflow metadata into the common metadata shape."""
        raw_prompt = metadata.get('prompt')
        raw_workflow = metadata.get('workflow')
        raw_workflow_api = metadata.get('workflow_api')

        prompt_api = ImageMetadataExtractor._load_json_data(raw_prompt)
        workflow_data = ImageMetadataExtractor._load_json_data(raw_workflow)
        workflow_api_data = ImageMetadataExtractor._load_json_data(raw_workflow_api)

        if not prompt_api and not workflow_data and not workflow_api_data:
            return None

        nodes_by_id: Dict[str, Dict[str, Any]] = {}
        for data in (prompt_api, workflow_data, workflow_api_data):
            if ImageMetadataExtractor._looks_like_comfyui_prompt_api(data):
                nodes_by_id = {str(node_id): node for node_id, node in data.items()}
                break
            if ImageMetadataExtractor._looks_like_comfyui_workflow_ui(data):
                nodes_by_id = ImageMetadataExtractor._convert_workflow_ui_to_api_nodes(data)
                break

        result: Dict[str, Any] = {
            'type': 'comfyui',
            'parameters': {},
        }

        if raw_prompt is not None:
            result['prompt_api'] = raw_prompt
        elif prompt_api is not None:
            result['prompt_api'] = prompt_api

        if raw_workflow is not None:
            result['workflow'] = raw_workflow
        if raw_workflow_api is not None:
            result['workflow_api'] = raw_workflow_api
        elif workflow_api_data is not None:
            result['workflow_api'] = workflow_api_data

        if not nodes_by_id:
            if image:
                result['parameters']['width'] = image.width
                result['parameters']['height'] = image.height
            return result

        sampler_node_id = ImageMetadataExtractor._find_primary_comfyui_sampler(nodes_by_id)
        sampler_node = nodes_by_id.get(sampler_node_id, {})
        sampler_inputs = sampler_node.get('inputs', {})
        parameters = result['parameters']

        positive_node_id = ImageMetadataExtractor._extract_node_reference(sampler_inputs.get('positive'))
        negative_node_id = ImageMetadataExtractor._extract_node_reference(sampler_inputs.get('negative'))
        latent_node_id = ImageMetadataExtractor._extract_node_reference(sampler_inputs.get('latent_image'))
        model_node_id = ImageMetadataExtractor._extract_node_reference(sampler_inputs.get('model'))

        positive_node = nodes_by_id.get(positive_node_id, {})
        negative_node = nodes_by_id.get(negative_node_id, {})
        latent_node = nodes_by_id.get(latent_node_id, {})

        prompt_text = ImageMetadataExtractor._extract_prompt_text_from_node(positive_node)
        negative_text = ImageMetadataExtractor._extract_prompt_text_from_node(negative_node)

        if prompt_text:
            result['prompt'] = prompt_text
        if negative_text:
            result['negative'] = negative_text
            result['negative_prompt'] = negative_text

        sampler_fields = {
            'steps': 'steps',
            'seed': 'seed',
            'cfg': 'cfg_scale',
            'sampler_name': 'sampler',
            'scheduler': 'scheduler',
            'denoise': 'denoising_strength',
        }
        for source_key, target_key in sampler_fields.items():
            value = sampler_inputs.get(source_key)
            if value is not None:
                parameters[target_key] = value

        if latent_node:
            latent_inputs = latent_node.get('inputs', {})
            for key in ('width', 'height', 'batch_size'):
                value = latent_inputs.get(key)
                if value is not None:
                    parameters[key] = value

        if 'width' not in parameters and image:
            parameters['width'] = image.width
        if 'height' not in parameters and image:
            parameters['height'] = image.height

        decode_node_id = ImageMetadataExtractor._find_primary_comfyui_decode(nodes_by_id)
        decode_node = nodes_by_id.get(decode_node_id, {})
        vae_source_id = ImageMetadataExtractor._extract_node_reference(
            decode_node.get('inputs', {}).get('vae'),
        )

        loader_node_id = ImageMetadataExtractor._find_upstream_node(
            nodes_by_id,
            model_node_id,
            {'CheckpointLoaderSimple', 'UNETLoader'},
        )
        loader_node = nodes_by_id.get(loader_node_id, {})
        loader_type = loader_node.get('class_type')
        loader_inputs = loader_node.get('inputs', {})
        if loader_type == 'CheckpointLoaderSimple':
            parameters['model'] = loader_inputs.get('ckpt_name')
            parameters['workflow_type'] = 'checkpoint'
        elif loader_type == 'UNETLoader':
            parameters['model'] = loader_inputs.get('unet_name')
            parameters['workflow_type'] = 'unet'
            if loader_inputs.get('weight_dtype') is not None:
                parameters['weight_dtype'] = loader_inputs.get('weight_dtype')

        clip_source_id = ImageMetadataExtractor._extract_node_reference(
            positive_node.get('inputs', {}).get('clip'),
        ) or ImageMetadataExtractor._extract_node_reference(
            negative_node.get('inputs', {}).get('clip'),
        )
        clip_loader_id = ImageMetadataExtractor._find_upstream_node(
            nodes_by_id,
            clip_source_id,
            {'CLIPLoader', 'CheckpointLoaderSimple'},
        )
        clip_loader = nodes_by_id.get(clip_loader_id, {})
        clip_loader_type = clip_loader.get('class_type')
        clip_loader_inputs = clip_loader.get('inputs', {})
        if clip_loader_type == 'CLIPLoader':
            if clip_loader_inputs.get('clip_name') is not None:
                parameters['clip_model'] = clip_loader_inputs.get('clip_name')
            if clip_loader_inputs.get('type') is not None:
                parameters['clip_type'] = clip_loader_inputs.get('type')
            if clip_loader_inputs.get('device') is not None:
                parameters['clip_device'] = clip_loader_inputs.get('device')

        vae_loader_id = ImageMetadataExtractor._find_upstream_node(
            nodes_by_id,
            vae_source_id,
            {'VAELoader', 'CheckpointLoaderSimple'},
        )
        vae_loader = nodes_by_id.get(vae_loader_id, {})
        vae_loader_type = vae_loader.get('class_type')
        vae_loader_inputs = vae_loader.get('inputs', {})
        if vae_loader_type == 'VAELoader' and vae_loader_inputs.get('vae_name') is not None:
            parameters['vae'] = vae_loader_inputs.get('vae_name')

        rescale_node_id = ImageMetadataExtractor._find_upstream_node(
            nodes_by_id,
            model_node_id,
            {'RescaleCFG'},
        )
        rescale_node = nodes_by_id.get(rescale_node_id, {})
        if rescale_node.get('inputs', {}).get('multiplier') is not None:
            parameters['cfg_rescale'] = rescale_node['inputs'].get('multiplier')

        model_sampling_node_id = ImageMetadataExtractor._find_upstream_node(
            nodes_by_id,
            model_node_id,
            {'ModelSamplingDiscrete'},
        )
        model_sampling_node = nodes_by_id.get(model_sampling_node_id, {})
        model_sampling_inputs = model_sampling_node.get('inputs', {})
        if model_sampling_inputs.get('sampling') is not None:
            parameters['sampling_mode'] = model_sampling_inputs.get('sampling')
        if model_sampling_inputs.get('zsnr') is not None:
            parameters['zsnr'] = model_sampling_inputs.get('zsnr')

        if parameters.get('workflow_type') is not None:
            result['workflow_type'] = parameters['workflow_type']
        if parameters.get('model') is not None:
            result['model'] = parameters['model']
        if parameters.get('clip_model') is not None:
            result['clip_model'] = parameters['clip_model']
        if parameters.get('vae') is not None:
            result['vae'] = parameters['vae']

        result['workflow_nodes'] = len(nodes_by_id)
        return result

    @staticmethod
    def _parse_naia_metadata(
        metadata: Dict[str, Any],
        image: Optional[Image.Image] = None,
    ) -> Optional[Dict[str, Any]]:
        """Normalize NAIA-specific PNG chunks written for generated results."""
        generation_params = ImageMetadataExtractor._load_json_data(metadata.get('naia_generation_params')) or {}
        prompt_context = ImageMetadataExtractor._load_json_data(metadata.get('naia_prompt_context')) or {}
        api_metadata = ImageMetadataExtractor._load_json_data(metadata.get('naia_api_metadata')) or {}

        if not generation_params and not prompt_context and not api_metadata:
            return None

        api_mode = (
            generation_params.get('api_mode')
            or api_metadata.get('backend')
            or api_metadata.get('api_mode')
            or ''
        )
        prompt = (
            prompt_context.get('main_prompt')
            or prompt_context.get('processed_input')
            or prompt_context.get('original_input')
            or generation_params.get('input')
            or ''
        )
        negative = (
            prompt_context.get('negative_prompt')
            or generation_params.get('negative_prompt')
            or ''
        )

        params: Dict[str, Any] = {}
        for key in (
            'steps',
            'seed',
            'cfg_scale',
            'cfg',
            'sampler',
            'sampler_name',
            'scheduler',
            'denoise',
            'model',
            'width',
            'height',
            'sampling_mode',
            'workflow_type',
            'rescale_cfg',
            'anima_weight',
        ):
            if key in generation_params and generation_params[key] not in (None, ''):
                params[key] = generation_params[key]

        if image is not None:
            params.setdefault('width', getattr(image, 'width', None))
            params.setdefault('height', getattr(image, 'height', None))

        result: Dict[str, Any] = {
            'type': 'comfyui' if str(api_mode).upper() == 'COMFYUI' else 'naia',
            'generation_params': generation_params,
            'prompt_context': prompt_context,
            'api_metadata': api_metadata,
            'parameters': params,
        }
        if prompt:
            result['prompt'] = prompt
        if negative:
            result['negative_prompt'] = negative
            result['negative'] = negative
        return result

    @staticmethod
    def _load_json_data(value: Any) -> Optional[Dict[str, Any]]:
        """Load JSON metadata when it is stored as a text chunk."""
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None

        text = value.strip()
        if not text:
            return None

        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    @staticmethod
    def _looks_like_comfyui_prompt_api(data: Any) -> bool:
        """Check whether data matches the ComfyUI prompt API node map format."""
        if not isinstance(data, dict) or not data:
            return False
        sample = next(iter(data.values()))
        return isinstance(sample, dict) and 'class_type' in sample

    @staticmethod
    def _looks_like_comfyui_workflow_ui(data: Any) -> bool:
        """Check whether data matches the ComfyUI workflow UI format."""
        return isinstance(data, dict) and isinstance(data.get('nodes'), list)

    @staticmethod
    def _convert_workflow_ui_to_api_nodes(workflow: Dict[str, Any]) -> Dict[str, Any]:
        """Convert the UI workflow format into a node map close to the prompt API format."""
        links = {
            link[0]: link
            for link in workflow.get('links', [])
            if isinstance(link, list) and len(link) >= 6
        }

        widget_mappings = {
            'CheckpointLoaderSimple': ['ckpt_name'],
            'CLIPTextEncode': ['text'],
            'KSampler': ['seed', None, 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise'],
            'EmptyLatentImage': ['width', 'height', 'batch_size'],
            'UNETLoader': ['unet_name', 'weight_dtype'],
            'CLIPLoader': ['clip_name', 'type', 'device'],
            'VAELoader': ['vae_name'],
            'RescaleCFG': ['multiplier'],
            'ModelSamplingDiscrete': ['sampling', 'zsnr'],
        }

        node_map: Dict[str, Any] = {}
        for node in workflow.get('nodes', []):
            node_id = str(node.get('id'))
            class_type = node.get('type')
            inputs: Dict[str, Any] = {}

            for input_slot in node.get('inputs', []):
                slot_name = input_slot.get('name')
                link_id = input_slot.get('link')
                if not slot_name or link_id not in links:
                    continue
                link = links[link_id]
                inputs[slot_name] = [str(link[1]), link[2]]

            mapping = widget_mappings.get(class_type, [])
            widgets = node.get('widgets_values', [])
            for index, key in enumerate(mapping):
                if not key or index >= len(widgets):
                    continue
                inputs[key] = widgets[index]

            node_map[node_id] = {
                'class_type': class_type,
                'inputs': inputs,
                '_meta': {
                    'title': node.get('title') or node.get('properties', {}).get('Node name for S&R', ''),
                },
            }

        return node_map

    @staticmethod
    def _extract_node_reference(value: Any) -> Optional[str]:
        """Extract the upstream node id from a ComfyUI input reference."""
        if isinstance(value, (list, tuple)) and value:
            return str(value[0])
        return None

    @staticmethod
    def _get_node_sort_key(node_id: str) -> tuple:
        """Sort node ids numerically when possible."""
        if isinstance(node_id, str) and node_id.isdigit():
            return (0, int(node_id))
        return (1, str(node_id))

    @staticmethod
    def _find_primary_comfyui_sampler(nodes_by_id: Dict[str, Dict[str, Any]]) -> Optional[str]:
        """Find the sampler that feeds the main decode/output chain."""
        output_types = {'PreviewImage', 'SaveImage'}
        sampler_types = {'KSampler', 'SamplerCustom'}

        for output_type in output_types:
            for node in nodes_by_id.values():
                if node.get('class_type') != output_type:
                    continue
                image_source_id = ImageMetadataExtractor._extract_node_reference(
                    node.get('inputs', {}).get('images'),
                )
                decode_node = nodes_by_id.get(image_source_id, {})
                if decode_node.get('class_type') != 'VAEDecode':
                    continue
                sampler_id = ImageMetadataExtractor._extract_node_reference(
                    decode_node.get('inputs', {}).get('samples'),
                )
                if sampler_id and nodes_by_id.get(sampler_id, {}).get('class_type') in sampler_types:
                    return sampler_id

        sampler_ids = [
            node_id
            for node_id, node in nodes_by_id.items()
            if node.get('class_type') in sampler_types
        ]
        if not sampler_ids:
            return None
        return sorted(sampler_ids, key=ImageMetadataExtractor._get_node_sort_key)[0]

    @staticmethod
    def _find_primary_comfyui_decode(nodes_by_id: Dict[str, Dict[str, Any]]) -> Optional[str]:
        """Find the VAE decode node connected to the main output."""
        for output_type in ('PreviewImage', 'SaveImage'):
            for node in nodes_by_id.values():
                if node.get('class_type') != output_type:
                    continue
                decode_node_id = ImageMetadataExtractor._extract_node_reference(
                    node.get('inputs', {}).get('images'),
                )
                if decode_node_id and nodes_by_id.get(decode_node_id, {}).get('class_type') == 'VAEDecode':
                    return decode_node_id

        decode_ids = [
            node_id
            for node_id, node in nodes_by_id.items()
            if node.get('class_type') == 'VAEDecode'
        ]
        if not decode_ids:
            return None
        return sorted(decode_ids, key=ImageMetadataExtractor._get_node_sort_key)[0]

    @staticmethod
    def _find_upstream_node(
        nodes_by_id: Dict[str, Dict[str, Any]],
        start_node_id: Optional[str],
        target_types: Set[str],
    ) -> Optional[str]:
        """Walk upstream through model/prompt chains until a matching node type is found."""
        if not start_node_id:
            return None

        queue: List[str] = [str(start_node_id)]
        visited: Set[str] = set()

        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            node = nodes_by_id.get(node_id)
            if not node:
                continue

            if node.get('class_type') in target_types:
                return node_id

            for value in node.get('inputs', {}).values():
                upstream_id = ImageMetadataExtractor._extract_node_reference(value)
                if upstream_id and upstream_id not in visited:
                    queue.append(upstream_id)

        return None

    @staticmethod
    def _extract_prompt_text_from_node(node: Dict[str, Any]) -> str:
        """Extract the prompt text from a CLIPTextEncode node."""
        if not isinstance(node, dict):
            return ''
        text = node.get('inputs', {}).get('text')
        return text if isinstance(text, str) else ''
    
    @staticmethod
    def _parse_parameters(params: str) -> Dict[str, Any]:
        """Stable Diffusion WebUI parameters 파싱"""
        result = {
            'type': 'webui',
            'prompt': '',
            'negative': '',
            'parameters': {}
        }
        
        # Negative prompt 분리
        if 'Negative prompt:' in params:
            parts = params.split('Negative prompt:')
            result['prompt'] = parts[0].strip()
            
            # 나머지 파라미터 파싱
            if '\n' in parts[1]:
                neg_parts = parts[1].split('\n', 1)
                result['negative'] = neg_parts[0].strip()
                if len(neg_parts) > 1:
                    result['parameters'] = ImageMetadataExtractor._parse_webui_params(neg_parts[1])
            else:
                result['negative'] = parts[1].strip()
        else:
            # Negative prompt가 없는 경우
            if '\n' in params:
                parts = params.split('\n', 1)
                result['prompt'] = parts[0].strip()
                if len(parts) > 1:
                    result['parameters'] = ImageMetadataExtractor._parse_webui_params(parts[1])
            else:
                result['prompt'] = params.strip()
        
        return result
    
    @staticmethod
    def _parse_webui_params(param_str: str) -> Dict[str, Any]:
        """WebUI 파라미터 문자열 파싱"""
        params = {}
        
        # Steps: 20, Sampler: Euler a, CFG scale: 7.0 형식 파싱
        param_pattern = r'(\w+(?:\s+\w+)*?):\s*([^,]+)'
        matches = re.findall(param_pattern, param_str)
        
        for key, value in matches:
            key = key.strip().lower().replace(' ', '_')
            value = value.strip()
            
            # 숫자 변환 시도
            try:
                if '.' in value:
                    params[key] = float(value)
                else:
                    params[key] = int(value)
            except ValueError:
                params[key] = value
        
        return params
    
    @staticmethod
    def _parse_nai_format(text: str) -> Dict[str, Any]:
        """NovelAI 형식 메타데이터 파싱"""
        result = {
            'type': 'nai',
            'prompt': '',
            'uc': '',
            'parameters': {}
        }
        
        # prompt 추출
        prompt_match = re.search(r'"prompt"\s*:\s*"([^"]*)"', text)
        if prompt_match:
            result['prompt'] = prompt_match.group(1)
        
        # negative prompt (uc) 추출
        uc_match = re.search(r'"uc"\s*:\s*"([^"]*)"', text)
        if uc_match:
            result['uc'] = uc_match.group(1)
        
        # 기타 파라미터 추출
        param_keys = ['steps', 'scale', 'uncond_scale', 'cfg_rescale', 'seed', 
                     'sampler', 'sm', 'sm_dyn', 'noise_schedule']
        
        for key in param_keys:
            pattern = r'"{}":\s*([^,\}}]+)'.format(key)
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                try:
                    if value.lower() == 'true':
                        result['parameters'][key] = True
                    elif value.lower() == 'false':
                        result['parameters'][key] = False
                    elif '.' in value:
                        result['parameters'][key] = float(value)
                    else:
                        result['parameters'][key] = int(value)
                except ValueError:
                    result['parameters'][key] = value.strip('"')
        
        # 캐릭터 프롬프트 추출
        result['characters'] = ImageMetadataExtractor._extract_char_captions(text)
        result['characters_uc'] = ImageMetadataExtractor._extract_char_captions(text, negative=True)
        
        return result
    
    @staticmethod
    def _extract_char_captions(text: str, negative: bool = False) -> list:
        """캐릭터 캡션 추출"""
        captions = []
        
        if negative:
            # negative prompt 섹션 찾기
            neg_marker = '"v4_negative_prompt"'
            neg_start = text.find(neg_marker)
            if neg_start != -1:
                text = text[neg_start:]
        
        # char_caption 추출
        pattern = r'"char_caption"\s*:\s*"([^"]*)"'
        matches = re.findall(pattern, text)
        captions.extend(matches)

        return captions

    @staticmethod
    def _extract_char_captions_from_dict(prompt_data: Dict[str, Any]) -> list:
        """Extract v4 char_captions from an already-parsed NovelAI dict."""
        captions = []
        caption_data = prompt_data.get('caption', {}) if isinstance(prompt_data, dict) else {}
        char_captions = caption_data.get('char_captions', [])

        if not isinstance(char_captions, list):
            return captions

        for item in char_captions:
            if isinstance(item, dict):
                char_caption = item.get('char_caption', '')
                if char_caption:
                    captions.append(char_caption)
            elif isinstance(item, str) and item:
                captions.append(item)

        return captions
    
    @staticmethod
    def _extract_from_exif(img: Image.Image) -> Optional[Dict[str, Any]]:
        """EXIF 데이터에서 메타데이터 추출 - WebUI 호환"""
        try:
            # WebUI style EXIF extraction
            if PIEXIF_AVAILABLE and hasattr(img, 'info') and 'exif' in img.info:
                exif_data = img.info['exif']
                try:
                    exif = piexif.load(exif_data)
                    user_comment = (exif or {}).get("Exif", {}).get(piexif.ExifIFD.UserComment, b'')
                    
                    if user_comment:
                        geninfo = None
                        try:
                            # Try piexif.helper first (AUTOMATIC1111 standard)
                            geninfo = piexif.helper.UserComment.load(user_comment)
                        except ValueError:
                            # Fallback: UTF-8 decoding
                            try:
                                geninfo = user_comment.decode('utf8', errors="ignore")
                            except:
                                # Last resort: UTF-16 decoding
                                if user_comment.startswith(b'UNICODE\x00\x00'):
                                    utf16_data = user_comment[9:]
                                    geninfo = utf16_data.decode('utf-16le', errors='ignore')
                        
                        if geninfo:
                            # Parse WebUI format parameters
                            return ImageMetadataExtractor._parse_parameters(geninfo)
                            
                except Exception as e:
                    print(f"EXIF piexif parsing error: {e}")
            
            # Fallback to standard getexif
            exif = img.getexif()
            if exif:
                # Check for UserComment tag (37510)
                if 37510 in exif:
                    user_comment = exif[37510]
                    if isinstance(user_comment, (bytes, str)):
                        try:
                            if isinstance(user_comment, bytes):
                                if PIEXIF_AVAILABLE:
                                    comment_text = piexif.helper.UserComment.load(user_comment)
                                else:
                                    comment_text = user_comment.decode('utf-8', errors='ignore')
                            else:
                                comment_text = user_comment
                            
                            if comment_text and comment_text.strip():
                                return ImageMetadataExtractor._parse_parameters(comment_text)
                        except Exception as e:
                            print(f"EXIF UserComment extraction failed: {e}")
                
                # Check other EXIF tags
                for tag_id, value in exif.items():
                    if isinstance(value, bytes):
                        try:
                            decoded = value.decode('utf-8', errors='ignore')
                            if 'prompt' in decoded.lower() or 'negative' in decoded.lower():
                                return ImageMetadataExtractor._parse_parameters(decoded)
                        except:
                            continue
            
            return None
            
        except Exception as e:
            print(f"EXIF extraction error: {e}")
            return None
    
    @staticmethod
    def _read_stealth_pnginfo(image: Image.Image) -> Optional[str]:
        """Stealth PNG 정보 읽기"""
        if image.mode != 'RGBA':
            print(f"_read_stealth_pnginfo: image mode {image.mode}, not RGBA")
            return None

        width, height = image.size
        print(f"_read_stealth_pnginfo: image size {width}x{height}")
        pixels = image.load()

        binary_data = ''
        buffer_a = ''
        index_a = 0
        confirming_signature = True
        reading_param_len = False
        reading_param = False
        read_end = False

        for x in range(width):
            for y in range(height):
                r, g, b, a = pixels[x, y]
                buffer_a += str(a & 1)
                index_a += 1

                if confirming_signature and x == 0:
                    if y == 119:  # index_a == len('stealth_pngcomp') * 8 == 120
                        decoded_sig = bytearray(
                            int(buffer_a[i:i + 8], 2)
                            for i in range(0, len(buffer_a), 8)
                        ).decode('utf-8', errors='ignore')

                        print(f"_read_stealth_pnginfo: signature check '{decoded_sig}'")
                        if decoded_sig == 'stealth_pngcomp':
                            print("_read_stealth_pnginfo: stealth PNG signature matched")
                            confirming_signature = False
                            reading_param_len = True
                            buffer_a = ''
                            index_a = 0
                        else:
                            print("_read_stealth_pnginfo: signature mismatch (expected 'stealth_pngcomp')")
                            return None

                elif reading_param_len:
                    if index_a == 32:  # 32 bits for length
                        param_len = int(buffer_a, 2)
                        print(f"_read_stealth_pnginfo: data length {param_len} bits")
                        reading_param_len = False
                        reading_param = True
                        buffer_a = ''
                        index_a = 0

                elif reading_param:
                    if index_a == param_len:
                        binary_data = buffer_a
                        print(f"_read_stealth_pnginfo: binary payload read complete ({param_len} bits)")
                        read_end = True
                        break
                else:
                    read_end = True
                    break

            if read_end:
                break

        if binary_data:
            try:
                byte_data = bytearray(
                    int(binary_data[i:i + 8], 2)
                    for i in range(0, len(binary_data), 8)
                )
                print(f"_read_stealth_pnginfo: trying gzip decode ({len(byte_data)} bytes)")
                decoded_data = gzip.decompress(bytes(byte_data)).decode('utf-8')
                print(f"_read_stealth_pnginfo: extracted data length {len(decoded_data)}")
                return decoded_data
            except Exception as e:
                print(f"_read_stealth_pnginfo: gzip decode failed - {e}")
                pass

        print("_read_stealth_pnginfo: no binary payload found")
        return None
    
    @staticmethod
    def _parse_stealth_data(data: str) -> Optional[Dict[str, Any]]:
        """Stealth PNG 데이터 파싱"""
        try:
            # JSON 직접 파싱 시도
            if data.strip().startswith('{'):
                try:
                    # 먼저 그대로 파싱 시도
                    parsed = json.loads(data)
                    # Comment 필드가 있으면 이것도 JSON 파싱 시도
                    if 'Comment' in parsed and isinstance(parsed['Comment'], str):
                        try:
                            parsed['Comment'] = json.loads(parsed['Comment'])
                        except:
                            pass  # Comment가 JSON이 아니면 그대로 유지
                    return parsed
                except json.JSONDecodeError:
                    # 실패하면 백슬래시 제거 후 재시도 (구형 호환성)
                    try:
                        return json.loads(data.replace("\\", ""))
                    except:
                        pass
        except Exception as e:
            print(f"Stealth data parsing error: {e}")

        # NAI 형식으로 파싱 시도
        return ImageMetadataExtractor._parse_nai_format(data)
    
    @staticmethod
    def detect_software(metadata: Dict[str, Any]) -> str:
        """메타데이터에서 소프트웨어 타입 감지"""
        if not metadata:
            return 'unknown'
        
        meta_type = metadata.get('type', '')
        if meta_type:
            return meta_type
        
        # NovelAI 특징 확인
        if 'sm' in metadata.get('parameters', {}):
            return 'nai'
        
        # WebUI 특징 확인
        if 'sampler' in metadata.get('parameters', {}):
            return 'webui'

        if 'workflow' in metadata or 'workflow_api' in metadata or 'prompt_api' in metadata:
            return 'comfyui'

        return 'unknown'
