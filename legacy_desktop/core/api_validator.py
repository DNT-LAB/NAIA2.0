"""
Qt 시그널 어댑터 — 순수 검증 로직은 `core/api_verification.py` 참조.

이 모듈은 기존 데스크톱 API 관리 창(`tabs/api_management_window.py`)과
호환성 유지를 위한 QObject 래퍼. 새 사용처는 `api_verification` 을 직접 import.
"""
from typing import List, Tuple
from PyQt6.QtCore import QObject, pyqtSignal

from core import api_verification as verify


class APIValidator(QObject):
    """API 검증을 백그라운드 스레드에서 실행하고 결과를 시그널로 보내는 워커."""

    # (성공여부, 저장할 값, 메시지, 메시지 타입)
    nai_validation_finished = pyqtSignal(bool, str, str, str)
    webui_validation_finished = pyqtSignal(bool, str, str, str)
    comfyui_validation_finished = pyqtSignal(bool, str, str, str)
    comfyui_models_loaded = pyqtSignal(bool, list, str)

    def run_nai_validation(self, token: str):
        r = verify.verify_nai_token(token)
        self.nai_validation_finished.emit(r.success, r.value or token, r.message, r.message_type)

    def run_webui_validation(self, url: str):
        r = verify.verify_webui_url(url)
        self.webui_validation_finished.emit(r.success, r.value if r.success else url,
                                            r.message, r.message_type)

    def run_comfyui_validation(self, url: str):
        r = verify.verify_comfyui_url(url)
        self.comfyui_validation_finished.emit(r.success, r.value if r.success else url,
                                              r.message, r.message_type)

    def get_comfyui_models(self, url: str):
        r = verify.fetch_comfyui_models(url)
        self.comfyui_models_loaded.emit(r.success, r.extra.get("models", []), r.message)

    # --- 동기식 편의 메서드 (기존 호출처 호환) ---

    def test_comfyui_connection_sync(self, url: str) -> bool:
        return verify.test_comfyui_connection(url)

    def get_comfyui_models_sync(self, url: str) -> List[str]:
        r = verify.fetch_comfyui_models(url)
        return r.extra.get("models", []) if r.success else []
