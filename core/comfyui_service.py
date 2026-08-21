# core/comfyui_service.py
import uuid
import requests
import time
from typing import Dict, Any, Optional, Callable, List
from PIL import Image
from io import BytesIO

# combo 선택지 추출은 legacy/V3 두 스키마를 아는 이 헬퍼 하나로 모은다.
from core.headless_api_option_service import extract_combo_options

class ComfyUIService:
    """
    ComfyUI API 통신을 담당하는 서비스 클래스

    🔧 완전한 스레드 안전 구현:
    - WebSocket 완전 제거 (타이머 충돌 원인)
    - 순수 HTTP 폴링만 사용
    - QObject::killTimer 오류 완전 해결
    """

    def __init__(self, server_url: str = "127.0.0.1:8188"):
        self.server_url = server_url.rstrip('/')
        if not self.server_url.startswith('http'):
            self.server_url = f"http://{self.server_url}"

        self.client_id = str(uuid.uuid4())
        self.progress_callback: Optional[Callable] = None
    
    def set_progress_callback(self, callback: Callable[[int, int], None]):
        """진행률 콜백 함수 설정"""
        self.progress_callback = callback
    
    def test_connection(self) -> bool:
        """ComfyUI 서버 연결 테스트"""
        try:
            response = requests.get(f"{self.server_url}/system_stats", timeout=5)
            if response.status_code == 200:
                print("✅ ComfyUI 서버 연결 성공")
                return True
            else:
                print(f"❌ ComfyUI 서버 응답 오류: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ ComfyUI 서버 연결 실패: {e}")
            return False
    
    def queue_workflow(self, workflow: Dict[str, Any], extra_pnginfo: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """워크플로우를 실행 큐에 추가"""
        try:
            payload = {
                "prompt": workflow,
                "client_id": self.client_id
            }
            if extra_pnginfo:
                payload["extra_data"] = {"extra_pnginfo": extra_pnginfo}
            
            headers = {'Content-Type': 'application/json'}
            response = requests.post(
                f"{self.server_url}/prompt",
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                prompt_id = result.get('prompt_id')
                if prompt_id:
                    print(f"✅ 워크플로우 큐 등록 성공: {prompt_id}")
                    return prompt_id
                else:
                    print("❌ 응답에서 prompt_id를 찾을 수 없음")
                    return None
            else:
                print(f"❌ 워크플로우 큐 등록 실패: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ 워크플로우 큐 등록 중 예외 발생: {e}")
            return None
    
    def wait_for_completion(self, prompt_id: str, timeout: int = 300) -> bool:
        """워크플로우 완료 대기 (순수 HTTP 폴링)"""
        print(f"🔄 워크플로우 완료 대기 시작 (HTTP 폴링): {prompt_id}")

        start_time = time.time()
        last_progress = 0
        last_poll_time = 0

        try:
            while time.time() - start_time < timeout:
                current_time = time.time()

                # HTTP 폴링으로 완료 상태 확인 (0.5초마다)
                if current_time - last_poll_time >= 0.5:
                    last_poll_time = current_time

                    try:
                        response = requests.get(f"{self.server_url}/history/{prompt_id}", timeout=5)

                        if response.status_code == 200:
                            history = response.json()

                            if prompt_id in history:
                                result = history[prompt_id]
                                status = result.get('status', {})

                                # 완료 상태 확인
                                if status.get('status_str') == 'success':
                                    print("✅ 워크플로우 실행 완료 (HTTP 폴링)")
                                    if self.progress_callback:
                                        self.progress_callback(100, 100)
                                    return True
                                elif status.get('status_str') == 'error':
                                    print(f"❌ 워크플로우 실행 실패: {status}")
                                    return False

                                # 진행률 추정 (실행 시간 기반)
                                if self.progress_callback:
                                    elapsed = current_time - start_time
                                    estimated_progress = min(int((elapsed / 60) * 100), 95)  # 최대 95%까지
                                    if estimated_progress > last_progress:
                                        self.progress_callback(estimated_progress, 100)
                                        last_progress = estimated_progress

                    except Exception as poll_e:
                        print(f"⚠️ 폴링 체크 실패: {poll_e}")

                # 0.1초 대기
                time.sleep(0.1)

            print("❌ 워크플로우 완료 대기 시간 초과")
            return False

        except Exception as e:
            print(f"❌ 워크플로우 완료 대기 중 예외 발생: {e}")
            return False
    
    @staticmethod
    def _node_sort_key(node_id: Any):
        try:
            return (1, int(str(node_id)))
        except Exception:
            return (0, str(node_id))

    _SAVE_OUTPUT_NODE_TYPES = {"SaveImage", "SaveAnimatedWEBP"}
    _NAIA_OUTPUT_HINTS = {"naia_output", "naia output", "final_output", "final output"}

    @staticmethod
    def _node_display_name(node: Dict[str, Any]) -> str:
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        for value in (
            node.get("title"),
            meta.get("title"),
            properties.get("Node name for S&R"),
            node.get("type"),
            node.get("class_type"),
        ):
            if value:
                return str(value)
        return ""

    @staticmethod
    def _label_has_output_hint(label: str) -> bool:
        normalized = str(label or "").strip().lower()
        compact = "".join(ch for ch in normalized if ch.isalnum())
        spaced = " ".join("".join(ch if ch.isalnum() else " " for ch in normalized).split())
        for hint in ComfyUIService._NAIA_OUTPUT_HINTS:
            hint_compact = "".join(ch for ch in hint.lower() if ch.isalnum())
            hint_spaced = " ".join("".join(ch if ch.isalnum() else " " for ch in hint.lower()).split())
            if hint_compact and hint_compact in compact:
                return True
            if hint_spaced and hint_spaced in spaced:
                return True
        return False

    def get_generation_result(
        self,
        prompt_id: str,
        workflow: Optional[Dict[str, Any]] = None,
        preferred_output_node_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        생성 결과를 조회하고, SaveImage/output 결과를 우선하여 반환합니다.
        """
        image_results = []
        try:
            response = requests.get(f"{self.server_url}/history/{prompt_id}", timeout=10)
            
            if response.status_code != 200:
                print(f"❌ 생성 결과 조회 실패: {response.status_code}")
                return []

            history = response.json()
            if prompt_id not in history:
                return []

            result = history[prompt_id]
            outputs = result.get('outputs', {})
            
            node_types = {}
            node_output_hints = {}
            if isinstance(workflow, dict):
                for node_id, node in workflow.items():
                    if isinstance(node, dict):
                        node_id_text = str(node_id)
                        node_types[node_id_text] = node.get("class_type") or node.get("type") or ""
                        node_output_hints[node_id_text] = self._label_has_output_hint(self._node_display_name(node))

            # 1. 이미지를 실제로 생성한 노드들만 후보로 수집합니다.
            candidates = []
            for node_id, node_output in outputs.items():
                if 'images' in node_output and isinstance(node_output['images'], list):
                    node_type = node_types.get(str(node_id), "")
                    for image_info in node_output['images']:
                        candidates.append({
                            'filename': image_info.get('filename'),
                            'subfolder': image_info.get('subfolder', ''),
                            'type': image_info.get('type', 'output'),
                            'source_node_id': str(node_id),
                            'source_node_type': node_type,
                        })
            
            if not candidates:
                print("❌ 생성 결과에서 이미지 정보를 찾을 수 없음")
                return []

            def candidate_score(info: Dict[str, Any]):
                source_node_id = str(info.get('source_node_id') or '')
                node_type = str(info.get('source_node_type') or '')
                image_type = str(info.get('type') or '')
                return (
                    1 if preferred_output_node_id and source_node_id == str(preferred_output_node_id) else 0,
                    1 if node_output_hints.get(source_node_id) else 0,
                    1 if node_type in self._SAVE_OUTPUT_NODE_TYPES else 0,
                    1 if image_type == "output" else 0,
                    0 if image_type == "temp" else 1,
                    self._node_sort_key(info.get('source_node_id')),
                )

            best = max(candidates, key=candidate_score)
            selected_node_id = best['source_node_id']
            image_results = [item for item in candidates if item['source_node_id'] == selected_node_id]

            print(
                f"✅ 최종 이미지 노드(ID: {selected_node_id}, type: {best.get('source_node_type') or 'unknown'})"
                f"에서 {len(image_results)}개의 결과를 찾았습니다."
            )
            return image_results

        except Exception as e:
            print(f"❌ 생성 결과 조회 중 예외 발생: {e}")
            return []
    
    def download_image(self, filename: str, subfolder: str = '', image_type: str = 'output') -> Optional[Image.Image]:
        """
        [수정] 생성된 이미지를 다운로드하고, PIL 객체와 원본 바이트를 함께 반환합니다.
        """
        try:
            params = {
                'filename': filename,
                'type': image_type
            }
            
            if subfolder:
                params['subfolder'] = subfolder
            
            response = requests.get(
                f"{self.server_url}/view",
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                image = Image.open(BytesIO(response.content))
                raw_bytes = response.content
                print(f"✅ 이미지 다운로드 성공: {filename}")
                return image, raw_bytes
            else:
                print(f"❌ 이미지 다운로드 실패: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ 이미지 다운로드 중 예외 발생: {e}")
            return None
    
    def generate_image(
        self,
        workflow: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
        extra_pnginfo: Optional[Dict[str, Any]] = None,
        preferred_output_node_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """완전한 이미지 생성 파이프라인"""
        if progress_callback:
            self.set_progress_callback(progress_callback)
        
        print("🚀 ComfyUI 이미지 생성 시작")
        
        # 1. 워크플로우 큐에 추가
        prompt_id = self.queue_workflow(workflow, extra_pnginfo=extra_pnginfo)
        if not prompt_id:
            return {'status': 'error', 'message': '워크플로우 큐 등록 실패'}
        
        # 2. 실행 완료 대기
        if not self.wait_for_completion(prompt_id, timeout=180):
            return {'status': 'error', 'message': '워크플로우 실행 실패 또는 시간 초과'}
        
        # 3. 결과 조회 (이제 리스트를 반환받음)
        # [수정] 변수명을 복수형(result_infos)으로 변경하여 리스트임을 명시
        result_infos = self.get_generation_result(
            prompt_id,
            workflow=workflow,
            preferred_output_node_id=preferred_output_node_id,
        )
        if not result_infos:
            return {'status': 'error', 'message': '생성 결과 조회 실패'}
        
        # [핵심 수정] 반환된 리스트에서 첫 번째 결과(딕셔너리)를 선택합니다.
        first_image_info = result_infos[0]
        
        # 4. 이미지 다운로드 (선택된 딕셔너리를 사용)
        download_result = self.download_image(
            first_image_info['filename'],
            first_image_info.get('subfolder', ''),
            first_image_info.get('type', 'output')
        )
        
        if download_result:
            image, raw_image_bytes = download_result
            
            return {
                'status': 'success',
                'image': image,
                'raw_bytes': raw_image_bytes,
                'prompt_id': prompt_id,
                'filename': first_image_info['filename'],
                'source_node_id': first_image_info.get('source_node_id'),
                'source_node_type': first_image_info.get('source_node_type'),
            }
        else:
            return {'status': 'error', 'message': '이미지 다운로드 실패'}
    
    def get_available_models(self) -> List[str]:
        """
        사용 가능한 모델 목록 조회 (CheckpointLoader + UNETLoader 합침)

        CheckpointLoader와 UNETLoader의 모델을 모두 가져와서
        set으로 중복 제거 후 정렬하여 반환

        Returns:
            모델 파일명 리스트 (중복 제거됨)
        """
        try:
            response = requests.get(f"{self.server_url}/object_info", timeout=10)

            if response.status_code == 200:
                object_info = response.json()
                all_models = set()  # 중복 제거를 위한 set

                # CheckpointLoaderSimple + UNETLoader 모델 수집.
                # 선택지 추출은 legacy/V3 스키마를 모두 아는 단일 헬퍼에 위임한다.
                #
                # ⚠️ 예전에는 `spec[0]` 을 그대로 `set.update()` 에 넣었다. V3 스펙에서는
                # 그게 문자열 "COMBO" 라, set 이 **글자 단위로 쪼개** 모델 이름 C/O/M/B
                # 를 만들었다(같은 버그의 더 나쁜 형태).
                for node_name, key in (
                    ('CheckpointLoaderSimple', 'ckpt_name'),
                    ('UNETLoader', 'unet_name'),
                ):
                    node = object_info.get(node_name) or {}
                    spec = (node.get('input') or {}).get('required', {}).get(key)
                    found = [
                        str(value).strip()
                        for value in extract_combo_options(spec)
                        if not isinstance(value, (dict, list)) and str(value or "").strip()
                    ]
                    all_models.update(found)
                    print(f"[ComfyUI] {node_name}: {len(found)} models")

                # 3. 정렬하여 반환
                if all_models:
                    sorted_models = sorted(list(all_models))
                    print(f"✅ 총 {len(sorted_models)}개 모델 (중복 제거됨): {sorted_models[:3]}{'...' if len(sorted_models) > 3 else ''}")
                    return sorted_models

            print("❌ 모델 리스트 조회 실패")
            return []

        except Exception as e:
            print(f"❌ 모델 리스트 조회 중 예외 발생: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_system_stats(self) -> Optional[Dict[str, Any]]:
        """시스템 상태 조회"""
        try:
            response = requests.get(f"{self.server_url}/system_stats", timeout=5)
            
            if response.status_code == 200:
                return response.json()
            else:
                return None
                
        except Exception as e:
            print(f"❌ 시스템 상태 조회 실패: {e}")
            return None
