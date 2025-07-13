import requests
from PyQt6.QtCore import QObject, pyqtSignal

class APIValidator(QObject):
    """API 검증을 백그라운드에서 실행하고 결과를 시그널로 보내는 워커"""

    # 시그널 정의: (성공여부, 저장할 값, 메시지, 메시지 타입)
    nai_validation_finished = pyqtSignal(bool, str, str, str)
    webui_validation_finished = pyqtSignal(bool, str, str, str)

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