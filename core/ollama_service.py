# core/ollama_service.py
import requests
import json
import subprocess
import sys
import os
import time
import importlib.util
from PyQt6.QtCore import QObject, pyqtSignal, QThread

# Global flag for ollama package availability
HAS_OLLAMA_PACKAGE = False

def check_ollama_package() -> bool:
    """Python ollama 패키지 설치 여부 확인"""
    global HAS_OLLAMA_PACKAGE
    if HAS_OLLAMA_PACKAGE:
        return True
    
    spec = importlib.util.find_spec('ollama')
    if spec is not None:
        HAS_OLLAMA_PACKAGE = True
        return True
    return False

class OllamaWorker(QThread):
    """Ollama API 호출을 위한 워커 스레드"""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, prompt, model="llama3", system_prompt=None, image_data=None):
        super().__init__()
        self.prompt = prompt
        self.model = model
        self.system_prompt = system_prompt
        self.image_data = image_data # bytes

    def run(self):
        # Python ollama 패키지가 설치되어 있어야 함 (기존 로직 유지하되 요청 방식 정제)
        if not check_ollama_package():
            self.error.emit("Ollama Python 패키지가 설치되어 있지 않습니다.")
            return

        try:
            import ollama
            
            # 이미지 데이터가 있으면 리스트로 전달
            images = [self.image_data] if self.image_data else None
            
            # keep_alive: 0 을 설정하여 작업 완료 후 즉시 VRAM에서 모델 언로드 유도
            # num_predict: 1024로 설정하여 최대 생성 토큰 수 제한 (폭주 방지)
            response = ollama.generate(
                model=self.model,
                prompt=self.prompt,
                system=self.system_prompt or "",
                images=images,
                stream=False,
                options={
                    "keep_alive": 0,
                    "num_predict": 1024
                }
            )
            self.finished.emit(response.get('response', ''))
        except Exception as e:
            self.error.emit(f"Ollama 실행 중 오류: {str(e)}")

class OllamaService(QObject):
    """Ollama 서비스 관리자"""
    
    _server_process = None

    def __init__(self):
        super().__init__()
        self.available_models = []

    def is_installed(self) -> bool:
        """Ollama가 시스템에 설치되어 있는지 확인"""
        try:
            result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=2, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            return result.returncode == 0
        except:
            return False

    def is_server_running(self) -> bool:
        """Ollama 서버가 실행 중인지 확인 (포트 체크)"""
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=1)
            return response.status_code == 200
        except:
            return False

    def start_server(self) -> bool:
        """Ollama 서버 시작 (이미 실행 중이면 True 반환)"""
        if self.is_server_running():
            return True
        
        try:
            # ollama serve 실행
            # Windows에서 창 숨기기 위해 CREATE_NO_WINDOW 사용
            print("[Ollama] 서버 시작 시도...")
            self.__class__._server_process = subprocess.Popen(
                ["ollama", "serve"],
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # 서버가 뜰 때까지 잠시 대기
            for _ in range(10):
                time.sleep(1)
                if self.is_server_running():
                    print("[Ollama] 서버 연결 성공")
                    return True
            return False
        except Exception as e:
            print(f"[Ollama] 서버 시작 실패: {e}")
            return False

    def stop_server(self):
        """Ollama 서버 종료 (프로세스 종료)"""
        # 1. 관리 중인 프로세스 종료
        if self.__class__._server_process:
            print("[Ollama] 서버 프로세스 종료 시도...")
            self.__class__._server_process.terminate()
            self.__class__._server_process.wait(timeout=2)
            self.__class__._server_process = None
        
        # 2. 강제 종료 (이미 실행 중이던 다른 Ollama 인스턴스도 포함할지 결정 필요)
        # 사용자의 요구사항: "모든 활성 Ollama 서버를 terminate"
        try:
            if sys.platform == 'win32':
                subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.run(["pkill", "-f", "ollama"], capture_output=True)
            print("[Ollama] 모든 Ollama 서버 종료 완료")
        except Exception as e:
            print(f"[Ollama] 서버 강제 종료 중 오류: {e}")

    def check_connection(self):
        """Ollama 서버 연결 확인 및 모델 목록 갱신"""
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code == 200:
                models_data = response.json().get("models", [])
                self.available_models = [m["name"] for m in models_data]
                return True
            return False
        except:
            return False

    def check_model_exists(self, model_name: str) -> bool:
        """특정 모델이 로컬에 존재하는지 확인"""
        if not self.available_models:
            self.check_connection()
        
        # 태그가 없는 경우(latest)와 있는 경우를 모두 고려
        for m in self.available_models:
            if m == model_name or m.split(':')[0] == model_name:
                return True
        return False

    def get_models(self):
        if not self.available_models:
            self.check_connection()
        return self.available_models

    def install_package(self):
        """ollama 패키지 설치 시도"""
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "ollama"])
            global HAS_OLLAMA_PACKAGE
            HAS_OLLAMA_PACKAGE = True
            return True
        except:
            return False
