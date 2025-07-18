import requests
from PyQt6.QtCore import QObject, pyqtSignal
from typing import List, Tuple

class APIValidator(QObject):
    """API 검증을 백그라운드에서 실행하고 결과를 시그널로 보내는 워커"""

    # 기존 시그널 정의: (성공여부, 저장할 값, 메시지, 메시지 타입)
    nai_validation_finished = pyqtSignal(bool, str, str, str)
    webui_validation_finished = pyqtSignal(bool, str, str, str)
    
    # 🆕 ComfyUI 관련 시그널 추가
    comfyui_validation_finished = pyqtSignal(bool, str, str, str)  # success, value, message, message_type
    comfyui_models_loaded = pyqtSignal(bool, list, str)  # success, models_list, message

    def run_nai_validation(self, token: str):
        """(스레드에서 실행) NAI API 요청 및 검증 로직"""
        result_message, result_type, success = "", "error", False
        try:
            response = requests.get(
                "https://api.novelai.net/user/subscription",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            if data.get('perks', {}).get('unlimitedMaxPriority', False):
                result_message, result_type, success = "✅ Opus 등급 구독이 확인되었습니다.", "info", True
            else:
                result_message, result_type = "⚠️ 유효한 토큰이나 Opus 등급 구독이 아닙니다.", "warning"
        except requests.exceptions.HTTPError as e:
            result_message = f"인증 실패 (HTTP {e.response.status_code}): 유효하지 않은 토큰일 수 있습니다." if e.response.status_code == 401 else f"HTTP 오류: {e.response.status_code}"
        except requests.exceptions.RequestException as e:
            result_message = f"네트워크 오류: API 서버에 연결할 수 없습니다. ({e})"
        except Exception as e:
            result_message = f"알 수 없는 오류: {e}"
        
        # 작업 완료 후 시그널 발생
        self.nai_validation_finished.emit(success, token, result_message, result_type)

    def run_webui_validation(self, url: str):
        """(스레드에서 실행) WebUI 연결 테스트 로직"""
        result_message, result_type, success, valid_url = "", "error", False, None
        
        clean_url = url.replace('http://', '').replace('https://', '').rstrip('/')
        protocols = [f"https://{clean_url}", f"http://{clean_url}"]
        
        for base_url in protocols:
            try:
                res = requests.get(f"{base_url}/sdapi/v1/progress?skip_current_image=true", timeout=3)
                if res.status_code == 200 and 'progress' in res.json():
                    result_message, result_type, success, valid_url = "✅ WebUI 연결에 성공했습니다.", "info", True, clean_url
                    break
            except requests.exceptions.RequestException:
                continue
        
        if not success:
            result_message = f"❌ WebUI 연결 실패: '{url}' 주소를 확인해주세요."

        # 작업 완료 후 시그널 발생
        self.webui_validation_finished.emit(success, valid_url if success else url, result_message, result_type)

    def run_comfyui_validation(self, url: str):
        """🆕 (스레드에서 실행) ComfyUI 연결 테스트 로직"""
        result_message, result_type, success, valid_url = "", "error", False, None
        
        # URL 정규화
        clean_url = url.replace('http://', '').replace('https://', '').rstrip('/')
        protocols = [f"http://{clean_url}", f"https://{clean_url}"]  # ComfyUI는 일반적으로 http
        
        for base_url in protocols:
            try:
                # ComfyUI system_stats 엔드포인트 테스트
                response = requests.get(f"{base_url}/system_stats", timeout=5)
                if response.status_code == 200:
                    stats = response.json()
                    # 시스템 정보 확인
                    device_info = stats.get('system', {})
                    gpu_name = device_info.get('gpu_name', 'Unknown GPU')
                    ram_total = device_info.get('ram_total', 0)
                    
                    ram_gb = ram_total / (1024**3) if ram_total > 0 else 0
                    result_message = f"✅ ComfyUI 연결 성공!\nGPU: {gpu_name}\nRAM: {ram_gb:.1f}GB"
                    result_type, success, valid_url = "info", True, clean_url
                    break
            except requests.exceptions.RequestException:
                continue
        
        if not success:
            result_message = f"❌ ComfyUI 연결 실패: '{url}' 주소를 확인하고 서버가 실행 중인지 확인해주세요."

        # 작업 완료 후 시그널 발생
        self.comfyui_validation_finished.emit(success, valid_url if success else url, result_message, result_type)

    def get_comfyui_models(self, url: str):
        """🆕 (스레드에서 실행) ComfyUI 모델 목록 가져오기"""
        try:
            success, models, message = self._fetch_comfyui_models(url)
            self.comfyui_models_loaded.emit(success, models, message)
        except Exception as e:
            self.comfyui_models_loaded.emit(False, [], f"모델 목록 로드 중 오류 발생: {str(e)}")

    def _fetch_comfyui_models(self, url: str) -> Tuple[bool, List[str], str]:
        """🆕 ComfyUI 서버에서 사용 가능한 모델 목록을 가져옴"""
        # URL 정규화
        clean_url = url.replace('http://', '').replace('https://', '').rstrip('/')
        normalized_url = f"http://{clean_url}"  # ComfyUI는 일반적으로 http
        
        try:
            # ComfyUI object_info 엔드포인트에서 체크포인트 정보 가져오기
            response = requests.get(f"{normalized_url}/object_info", timeout=10)
            
            if response.status_code == 200:
                object_info = response.json()
                
                # CheckpointLoaderSimple 노드에서 모델 목록 추출
                checkpoint_loader = object_info.get('CheckpointLoaderSimple', {})
                input_info = checkpoint_loader.get('input', {})
                required_info = input_info.get('required', {})
                ckpt_name_info = required_info.get('ckpt_name', [])
                
                if isinstance(ckpt_name_info, list) and len(ckpt_name_info) > 0:
                    models = ckpt_name_info[0]  # 첫 번째 요소가 모델 리스트
                    if isinstance(models, list) and len(models) > 0:
                        return True, models, f"모델 {len(models)}개 발견"
                    else:
                        return False, [], "사용 가능한 모델이 없습니다."
                else:
                    return False, [], "모델 정보를 찾을 수 없습니다."
            else:
                return False, [], f"API 응답 오류 (HTTP {response.status_code})"
                
        except requests.exceptions.Timeout:
            return False, [], "모델 목록 로드 시간 초과"
        except requests.exceptions.ConnectionError:
            return False, [], "ComfyUI 서버 연결 실패"
        except Exception as e:
            return False, [], f"모델 목록 로드 실패: {str(e)}"

    # 🆕 동기식 메서드들 (다른 클래스에서 사용하기 위해)
    def test_comfyui_connection_sync(self, url: str) -> bool:
        """동기식 ComfyUI 연결 테스트"""
        try:
            clean_url = url.replace('http://', '').replace('https://', '').rstrip('/')
            normalized_url = f"http://{clean_url}"
            response = requests.get(f"{normalized_url}/system_stats", timeout=5)
            return response.status_code == 200
        except:
            return False

    def get_comfyui_models_sync(self, url: str) -> List[str]:
        """동기식 ComfyUI 모델 목록 가져오기"""
        try:
            success, models, _ = self._fetch_comfyui_models(url)
            return models if success else []
        except:
            return []