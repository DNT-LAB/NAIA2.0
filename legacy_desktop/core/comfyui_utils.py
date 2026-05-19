"""
ComfyUI API 연동을 위한 유틸리티 클래스
"""
import requests
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QGroupBox, QTextEdit, QLabel
)
from ui.theme import DARK_COLORS, DARK_STYLES

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
        """CheckpointLoaderSimple + UNETLoader에서 모델 목록 추출 (중복 제거)"""
        try:
            object_info = ComfyUIAPIUtils.get_object_info(url)
            if not object_info:
                return []

            all_models = set()  # 중복 제거를 위한 set

            # 1. CheckpointLoaderSimple 모델 수집
            checkpoint_loader = object_info.get('CheckpointLoaderSimple', {})
            ckpt_input = checkpoint_loader.get('input', {}).get('required', {})
            ckpt_info = ckpt_input.get('ckpt_name', [])

            if isinstance(ckpt_info, list) and len(ckpt_info) > 0:
                checkpoint_models = ckpt_info[0]
                if isinstance(checkpoint_models, list):
                    all_models.update(checkpoint_models)

            # 2. UNETLoader 모델 수집
            unet_loader = object_info.get('UNETLoader', {})
            unet_input = unet_loader.get('input', {}).get('required', {})
            unet_info = unet_input.get('unet_name', [])

            if isinstance(unet_info, list) and len(unet_info) > 0:
                unet_models = unet_info[0]
                if isinstance(unet_models, list):
                    all_models.update(unet_models)

            # 3. 정렬하여 반환
            if all_models:
                return sorted(list(all_models))

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
        
class WorkflowValidationDialog(QDialog):
    """워크플로우 검증 결과를 표시하는 팝업 다이얼로그"""

    def __init__(self, validation_result: dict, parent=None):
        super().__init__(parent)
        self.result = validation_result
        self.setWindowTitle("워크플로우 검증 결과")
        self.setMinimumSize(500, 600)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']}; color: {DARK_COLORS['text_primary']};")
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # [179.5] 모델 호환성 상태 라벨 (native_* / locked_unknown)
        self.compat_label = QLabel()
        self.compat_label.setWordWrap(True)
        self.compat_label.setStyleSheet(
            f"padding: 10px; border-radius: 6px; font-size: 13px; "
            f"background-color: {DARK_COLORS['bg_secondary']}; "
            f"color: {DARK_COLORS['text_primary']};"
        )
        layout.addWidget(self.compat_label)

        # 필수 노드 그룹
        required_group = QGroupBox("[필수 노드]")
        required_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 16px; }")
        required_layout = QVBoxLayout()
        self.required_text_edit = QTextEdit()
        self.required_text_edit.setReadOnly(True)
        self.required_text_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        required_layout.addWidget(self.required_text_edit)
        required_group.setLayout(required_layout)

        # 커스텀 노드 그룹
        custom_group = QGroupBox("[커스텀 노드]")
        custom_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 16px; }")
        custom_layout = QVBoxLayout()
        self.custom_text_edit = QTextEdit()
        self.custom_text_edit.setReadOnly(True)
        self.custom_text_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        custom_layout.addWidget(self.custom_text_edit)
        custom_group.setLayout(custom_layout)

        # 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.setStyleSheet(DARK_STYLES['secondary_button'])
        close_button.clicked.connect(self.accept)

        layout.addWidget(required_group)
        layout.addWidget(custom_group)
        layout.addWidget(close_button)

        self.populate_data()

    def populate_data(self):
        # [179.5] 모델 호환성 상태 표시
        compat = self.result.get('model_compat')
        if compat == "native_checkpoint":
            self.compat_label.setText(
                f"<b style='color:{DARK_COLORS['success']};'>✓ 표준 체크포인트 로더</b> "
                "— CheckpointLoaderSimple. 모델 변경 가능."
            )
        elif compat == "native_unet":
            self.compat_label.setText(
                f"<b style='color:{DARK_COLORS['success']};'>✓ 표준 UNET 로더</b> "
                "— UNETLoader + CLIPLoader. 모델 변경 가능."
            )
        elif compat == "locked_unknown":
            loader = self.result.get('locked_loader_class') or "Custom Loader"
            display = self.result.get('locked_model_display') or "(파일명 미검출)"
            self.compat_label.setText(
                f"<b style='color:{DARK_COLORS['warning']};'>🔒 커스텀 체크포인트 로더 — 모델 변경 잠금</b><br>"
                f"<span style='color:{DARK_COLORS['text_secondary']};'>"
                f"로더: {loader}<br>"
                f"원본 모델: {display}<br>"
                f"이 워크플로우의 프롬프트·시드·해상도·샘플러는 변경 가능하지만, "
                f"체크포인트는 워크플로우 내장값을 유지합니다."
                f"</span>"
            )
        else:
            self.compat_label.setText(
                f"<span style='color:{DARK_COLORS['text_secondary']};'>"
                "모델 호환성 정보 없음"
                "</span>"
            )

        # 필수 노드 결과 표시
        required_text = ""
        for status, class_name in sorted(self.result['required']):
            color = DARK_COLORS['success'] if status == "PASS" else DARK_COLORS['error']
            required_text += f'<span style="color: {color};">{status}</span> | {class_name}<br>'
        self.required_text_edit.setHtml(required_text)

        # 커스텀 노드 목록 표시
        custom_text = "\n".join(sorted(list(set(self.result['custom']))))
        self.custom_text_edit.setText(custom_text if custom_text else "감지된 커스텀 노드 없음")