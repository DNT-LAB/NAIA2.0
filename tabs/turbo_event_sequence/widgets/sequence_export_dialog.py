"""
Sequence Export Dialog

이미지 시퀀스를 외부 API (ComfyUI, Ollama)로 전송하기 위한 다이얼로그.
- Border line 제거 및 이미지 전처리
- 프롬프트 탭: NAI / Ollama / 구글 번역
- API 컨트롤 패널: ComfyUI / Ollama 연동
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QScrollArea,
    QPushButton, QTabWidget, QTextEdit, QWidget, QSplitter, QGroupBox,
    QLineEdit, QComboBox, QMessageBox, QProgressDialog, QApplication,
    QButtonGroup, QRadioButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QPixmap
from PIL import Image
from PIL.ImageQt import ImageQt
from pathlib import Path
from typing import List, Optional, Dict, TYPE_CHECKING
import numpy as np
import requests
import subprocess
import importlib.util
import sys

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

if TYPE_CHECKING:
    from core.context import AppContext

# ollama 패키지 설치 확인 (동적 import로 처리)
HAS_OLLAMA = False

# Ollama 프롬프트 파일 경로
OLLAMA_PROMPT_PATH = Path(__file__).parent.parent.parent.parent / "workflows" / "Ollama_prompt.txt"


# === QMessageBox 스타일링 헬퍼 함수 ===

def _create_styled_messagebox(parent, icon, title, text, buttons=None):
    """하얀색 텍스트를 가진 스타일링된 QMessageBox 생성

    Args:
        parent: 부모 위젯
        icon: QMessageBox.Icon (Information, Warning, Critical, Question)
        title: 제목
        text: 메시지 텍스트
        buttons: QMessageBox.StandardButton (기본값: Ok)

    Returns:
        QMessageBox 인스턴스
    """
    msg = QMessageBox(parent)
    msg.setIcon(icon)
    msg.setWindowTitle(title)
    msg.setText(text)

    if buttons:
        msg.setStandardButtons(buttons)
    else:
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)

    # 하얀색 텍스트 스타일 적용
    msg.setStyleSheet(f"""
        QMessageBox {{
            background-color: {DARK_COLORS['bg_primary']};
            color: #FFFFFF;
        }}
        QMessageBox QLabel {{
            color: #FFFFFF;
            font-size: {get_scaled_font_size(12)}px;
        }}
        QPushButton {{
            background-color: {DARK_COLORS['accent_blue']};
            color: #FFFFFF;
            border: none;
            border-radius: {get_scaled_size(4)}px;
            padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
            font-size: {get_scaled_font_size(11)}px;
            min-width: {get_scaled_size(70)}px;
        }}
        QPushButton:hover {{
            background-color: {DARK_COLORS['accent_blue_hover']};
        }}
        QPushButton:pressed {{
            background-color: {DARK_COLORS['accent_blue']};
        }}
    """)

    return msg


# === 콘솔 로그 윈도우 ===

class ConsoleLogWindow(QDialog):
    """API 통신 및 진행 상황을 표시하는 콘솔 윈도우"""

    # 시그널
    stop_requested = pyqtSignal()  # 중단 요청 시그널

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🖥️ API 통신 로그")
        # WindowStaysOnTopHint 제거 (항상 위에 오지 않도록)
        self.setWindowFlags(Qt.WindowType.Tool)
        self.resize(get_scaled_size(600), get_scaled_size(400))

        # 다크 테마 배경
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        # 레이아웃
        layout = QVBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10),
                                 get_scaled_size(10), get_scaled_size(10))
        layout.setSpacing(get_scaled_size(8))

        # 상태 표시 라벨 (폰트 13 -> 17)
        self.status_label = QLabel("⏳ 대기 중...")
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: #FFFFFF;
                font-size: {get_scaled_font_size(17)}px;
                font-weight: bold;
                padding: {get_scaled_size(6)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        layout.addWidget(self.status_label)

        # 예상 시간 라벨 (폰트 11 -> 15)
        self.eta_label = QLabel("예상 시간: --:--")
        self.eta_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(15)}px;
                padding: {get_scaled_size(4)}px;
            }}
        """)
        layout.addWidget(self.eta_label)

        # 로그 텍스트 영역 (폰트 10 -> 14)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: #1A1A1A;
                color: #00FF00;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: {get_scaled_font_size(14)}px;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
            }}
        """)
        layout.addWidget(self.log_text)

        # 하단 버튼
        btn_layout = QHBoxLayout()

        # 중단 버튼 (빨간색)
        self.stop_btn = QPushButton("⏹️ 작업 중단")
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #D32F2F;
                color: #FFFFFF;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                font-size: {get_scaled_font_size(12)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #F44336;
            }}
            QPushButton:pressed {{
                background-color: #B71C1C;
            }}
            QPushButton:disabled {{
                background-color: #555555;
                color: #888888;
            }}
        """)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setEnabled(False)  # 기본적으로 비활성화
        btn_layout.addWidget(self.stop_btn)

        btn_layout.addStretch()

        # 로그 지우기 버튼
        self.clear_btn = QPushButton("🗑️ 로그 지우기")
        self.clear_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.clear_btn.clicked.connect(self.log_text.clear)
        btn_layout.addWidget(self.clear_btn)

        # 닫기 버튼
        self.close_btn = QPushButton("❌ 닫기")
        self.close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.close_btn.clicked.connect(self.hide)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

        # 타임스탬프 시작 시간
        from datetime import datetime
        self.start_time = datetime.now()

        # 도킹을 위한 오프셋 저장
        self.dock_offset = None

    def _on_stop_clicked(self):
        """중단 버튼 클릭 시"""
        self.append_log("사용자가 작업 중단을 요청했습니다.", "WARNING")
        self.stop_btn.setEnabled(False)
        self.stop_requested.emit()

    def enable_stop_button(self, enabled: bool = True):
        """중단 버튼 활성화/비활성화"""
        self.stop_btn.setEnabled(enabled)

    def update_docked_position(self):
        """부모 윈도우 위치에 따라 도킹된 위치 업데이트"""
        if self.parent() and self.dock_offset is not None:
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.x() + parent_geo.width() + self.dock_offset[0],
                parent_geo.y() + self.dock_offset[1]
            )

    def append_log(self, message: str, prefix: str = "INFO"):
        """로그 메시지 추가 (타임스탬프 포함)"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 색상 코드
        color_map = {
            "INFO": "#00FF00",      # 녹색
            "WARNING": "#FFAA00",   # 주황색
            "ERROR": "#FF0000",     # 빨간색
            "SUCCESS": "#00FFFF",   # 청록색
            "OLLAMA": "#FF00FF",    # 마젠타
            "COMFY": "#00AAFF"      # 파란색
        }
        color = color_map.get(prefix, "#00FF00")

        formatted_msg = f'<span style="color: #888888;">[{timestamp}]</span> ' \
                       f'<span style="color: {color};">[{prefix}]</span> ' \
                       f'<span style="color: #CCCCCC;">{message}</span>'

        self.log_text.append(formatted_msg)

        # 자동 스크롤
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_status(self, status: str):
        """상태 라벨 업데이트"""
        self.status_label.setText(status)

    def set_eta(self, eta_text: str):
        """예상 시간 업데이트"""
        self.eta_label.setText(f"예상 시간: {eta_text}")

    def closeEvent(self, event):
        """닫기 대신 숨김"""
        event.ignore()
        self.hide()


class ComfyGenerationWorker(QThread):
    """ComfyUI 동영상 생성을 위한 워커 스레드 (완전 비동기)"""
    progress = pyqtSignal(str)  # 진행 상황 메시지
    finished = pyqtSignal(str)  # 완료 (MP4 파일 경로)
    error = pyqtSignal(str)  # 오류 메시지

    def __init__(
        self,
        saved_paths: List[Path],
        comfyui_url: str,
        workflow_data: dict,
        width: int,
        height: int,
        segment_length: int,
        fps: int,
        image_prompt_widgets: list
    ):
        super().__init__()
        self.saved_paths = saved_paths
        self.comfyui_url = comfyui_url
        self.workflow_data = workflow_data
        self.width = width
        self.height = height
        self.segment_length = segment_length
        self.fps = fps
        self.image_prompt_widgets = image_prompt_widgets
        self._cancelled = False

    def cancel(self):
        """작업 취소"""
        self._cancelled = True

    def run(self):
        """백그라운드에서 실행되는 메인 로직"""
        try:
            import copy
            import json
            import uuid
            import time

            # 이미지 업로드
            self.progress.emit("이미지 업로드 중...")

            def _upload_image(path: Path) -> tuple[str, str]:
                with open(path, "rb") as f:
                    files = {"image": (path.name, f, "image/png")}
                    data = {"type": "input", "subfolder": "", "overwrite": "true"}
                    resp = requests.post(f"{self.comfyui_url}/upload/image", files=files, data=data, timeout=30)
                resp.raise_for_status()
                info = resp.json()
                return info.get("name", path.name), info.get("subfolder", "")

            uploaded_cache = {}

            def _upload_cached(path: Path) -> tuple[str, str]:
                key = str(path)
                if key not in uploaded_cache:
                    if self._cancelled:
                        raise RuntimeError("작업이 취소되었습니다.")
                    uploaded_cache[key] = _upload_image(path)
                return uploaded_cache[key]

            # Start, Middle, End 이미지 업로드
            start_path = self.saved_paths[0]
            num_imgs = len(self.saved_paths)

            start_name, start_sub = _upload_cached(start_path)

            if self._cancelled:
                return

            # 워크플로우 구성
            self.progress.emit("워크플로우 구성 중...")
            workflow = copy.deepcopy(self.workflow_data)

            # 해상도/프레임 설정
            val_259 = self.segment_length + 1
            val_397 = (self.segment_length * num_imgs) + 1

            if "159" in workflow:
                workflow["159"]["inputs"]["value"] = self.width
            if "160" in workflow:
                workflow["160"]["inputs"]["value"] = self.height
            if "259" in workflow:
                workflow["259"]["inputs"]["value"] = val_259
            if "397" in workflow:
                workflow["397"]["inputs"]["value"] = val_397
            if "451" in workflow and "inputs" in workflow["451"]:
                workflow["451"]["inputs"]["frame_rate"] = self.fps

            # 프롬프트 반영
            prompt_text = ""
            ollama_prompts = []
            for widget in self.image_prompt_widgets:
                p = widget.get_ollama_prompt().strip()
                if not p:
                    p = widget.get_nai_prompt().strip()
                if p:
                    ollama_prompts.append(p)

            if ollama_prompts:
                prompt_text = "\n\n".join(ollama_prompts)

            if prompt_text and "410" in workflow:
                workflow["410"]["inputs"]["prompt"] = prompt_text

            # 이미지 입력 반영
            if "10" in workflow:
                workflow["10"]["inputs"]["image"] = f"{start_sub}/{start_name}" if start_sub else start_name

            # Middle images
            if "445" in workflow:
                middle_data = []
                if num_imgs >= 3:
                    for i in range(1, num_imgs - 1):
                        if self._cancelled:
                            return
                        m_path = self.saved_paths[i]
                        m_name, m_sub = _upload_cached(m_path)
                        middle_data.append({
                            "name": m_name,
                            "type": "input",
                            "subfolder": m_sub or ""
                        })
                workflow["445"]["inputs"]["images_data"] = json.dumps(middle_data)

            # End image
            if "447" in workflow:
                end_data = []
                if num_imgs >= 2:
                    if self._cancelled:
                        return
                    end_path = self.saved_paths[-1]
                    end_name, end_sub = _upload_cached(end_path)
                    end_data.append({
                        "name": end_name,
                        "type": "input",
                        "subfolder": end_sub or ""
                    })
                workflow["447"]["inputs"]["images_data"] = json.dumps(end_data)

            if self._cancelled:
                return

            # 생성 요청
            self.progress.emit("ComfyUI 생성 요청 전송 중...")
            payload = {"prompt": workflow, "client_id": uuid.uuid4().hex}
            response = requests.post(f"{self.comfyui_url}/prompt", json=payload, timeout=30)
            response.raise_for_status()
            prompt_id = response.json().get("prompt_id")
            if not prompt_id:
                raise RuntimeError("ComfyUI 응답에 prompt_id가 없습니다.")

            # 폴링 (진행 상황 업데이트)
            self.progress.emit("ComfyUI 생성 중... (폴링 시작)")
            history_entry = None
            deadline = time.time() + 600  # 10분 타임아웃
            poll_count = 0

            while time.time() < deadline:
                if self._cancelled:
                    self.error.emit("작업이 취소되었습니다.")
                    return

                poll_count += 1
                if poll_count % 10 == 0:  # 5초마다 진행 상황 업데이트
                    elapsed = int(time.time() - (deadline - 600))
                    self.progress.emit(f"ComfyUI 생성 중... ({elapsed}초 경과)")

                hist_resp = requests.get(f"{self.comfyui_url}/history/{prompt_id}", timeout=10)
                if hist_resp.status_code == 200:
                    history = hist_resp.json()
                    entry = history.get(prompt_id)
                    if entry:
                        status = entry.get("status", {}).get("status_str")
                        if status == "success":
                            history_entry = entry
                            break
                        if status == "error":
                            raise RuntimeError("ComfyUI 생성 실패")

                time.sleep(0.5)

            if not history_entry:
                raise TimeoutError("ComfyUI 생성 시간 초과 (10분)")

            # 결과 다운로드
            self.progress.emit("결과 다운로드 중...")
            output_item = None
            outputs = history_entry.get("outputs", {})
            for node_output in outputs.values():
                for key in ("videos", "gifs", "images"):
                    items = node_output.get(key)
                    if isinstance(items, list):
                        for item in items:
                            filename = str(item.get("filename", ""))
                            if filename.lower().endswith(".mp4"):
                                output_item = item
                                break
                        if output_item:
                            break
                        if items and not output_item:
                            output_item = items[0]
                    if output_item:
                        break
                if output_item:
                    break

            if not output_item:
                raise RuntimeError("ComfyUI 결과를 찾을 수 없습니다.")

            filename = output_item.get("filename")
            subfolder = output_item.get("subfolder", "")
            file_type = output_item.get("type", "output")

            params = {"filename": filename, "subfolder": subfolder, "type": file_type}
            view_url = f"{self.comfyui_url}/view?" + "&".join(f"{k}={v}" for k, v in params.items())
            file_resp = requests.get(view_url, timeout=1200)
            file_resp.raise_for_status()

            output_dir = Path("output/comfyui_videos")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / filename

            with open(output_path, "wb") as f:
                f.write(file_resp.content)

            self.progress.emit(f"✅ 동영상 생성 완료: {output_path.name}")
            self.finished.emit(str(output_path))

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.error.emit(error_msg)


class TranslationWorker(QThread):
    """번역 작업을 위한 워커 스레드"""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, text: str, mode='en_to_ko'):
        super().__init__()
        self.text = text
        self.mode = mode

    def run(self):
        try:
            from utils.translator import english_to_korean, korean_to_english
            
            if self.mode == 'en_to_ko':
                result = english_to_korean(self.text)
            else:
                result = korean_to_english(self.text)
                
            if result:
                self.finished.emit(result)
            else:
                self.error.emit("번역 실패")
        except Exception as e:
            self.error.emit(str(e))


class ImagePromptWidget(QWidget):
    """이미지 + 프롬프트 탭 위젯"""

    # 시그널
    prompt_changed = pyqtSignal(int, str, str)  # index, tab_name, new_text
    translation_requested = pyqtSignal(int, str) # index, text_to_translate

    def __init__(self, index: int, image: Image.Image, prompt_data: dict, parent=None):
        """
        Args:
            index: 이미지 인덱스
            image: PIL 이미지
            prompt_data: 프롬프트 데이터 (general, is_parent 등)
        """
        super().__init__(parent)
        self.index = index
        self.image = image
        self.prompt_data = prompt_data

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # 왼쪽: 이미지 썸네일
        image_frame = QFrame()
        image_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        image_frame.setFixedSize(get_scaled_size(240), get_scaled_size(240))

        image_layout = QVBoxLayout(image_frame)
        image_layout.setContentsMargins(4, 4, 4, 4)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_image_thumbnail()
        image_layout.addWidget(self.image_label)

        # 이미지 인덱스 표시
        is_parent = self.prompt_data.get('is_parent', False)
        label_text = f"Parent" if is_parent else f"#{self.index}"
        index_label = QLabel(label_text)
        index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        image_layout.addWidget(index_label)

        layout.addWidget(image_frame)

        # 오른쪽: 프롬프트 탭
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(DARK_STYLES['dark_tabs'])
        self.tab_widget.setFixedHeight(get_scaled_size(240))  # 이미지와 같은 높이

        # NAI 프롬프트 탭
        self.nai_edit = self._create_prompt_edit()
        self.nai_edit.setPlainText(self.prompt_data.get('general', ''))
        self.nai_edit.textChanged.connect(lambda: self._on_text_changed('nai'))
        self.tab_widget.addTab(self.nai_edit, "📝 NAI")

        # Ollama 프롬프트 탭  
        self.ollama_edit = self._create_prompt_edit()
        self.ollama_edit.setPlaceholderText("Ollama API로 자동 생성 예정...")
        self.ollama_edit.textChanged.connect(lambda: self._on_text_changed('ollama'))
        self.tab_widget.addTab(self.ollama_edit, "🤖 Ollama")

        # 구글 번역 탭
        translate_tab_widget = QWidget()
        translate_layout = QVBoxLayout(translate_tab_widget)
        translate_layout.setContentsMargins(0, 0, 0, 0)
        translate_layout.setSpacing(4)

        # 번역 재시도 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.retry_trans_btn = QPushButton("🔄 재번역")
        self.retry_trans_btn.setFixedSize(get_scaled_size(100), get_scaled_size(24))
        self.retry_trans_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.retry_trans_btn.clicked.connect(self._on_retry_translation)
        #btn_layout.addWidget(self.retry_trans_btn)
        #translate_layout.addLayout(btn_layout)

        self.translate_edit = self._create_prompt_edit()
        self.translate_edit.setPlaceholderText("구글 번역 결과...")
        translate_layout.addWidget(self.translate_edit)
        
        self.tab_widget.addTab(translate_tab_widget, "🌐 번역")

        layout.addWidget(self.tab_widget)

        # 위젯 전체 고정 높이 설정 (스크롤 가능하도록)
        self.setFixedHeight(get_scaled_size(250))

    def _set_image_thumbnail(self):
        """이미지 썸네일 설정"""
        thumb_size = get_scaled_size(224)
        thumb = self.image.copy()
        thumb.thumbnail((thumb_size, thumb_size), Image.Resampling.LANCZOS)
        pixmap = QPixmap.fromImage(ImageQt(thumb.convert("RGBA")))
        self.image_label.setPixmap(pixmap.scaled(
            thumb_size, thumb_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))

    def _create_prompt_edit(self) -> QTextEdit:
        """프롬프트 편집 위젯 생성"""
        edit = QTextEdit()

        # QFont 객체로 폰트 명시적 설정
        from PyQt6.QtGui import QFont
        font = QFont("Consolas", get_scaled_font_size(17))
        font.setStyleHint(QFont.StyleHint.Monospace)
        edit.setFont(font)

        edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(17)}px;
                font-family: 'Consolas', monospace;
            }}
            QTextEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_primary']};
                width: {get_scaled_size(10)}px;
                border-radius: {get_scaled_size(5)}px;
                margin: {get_scaled_size(2)}px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(5)}px;
                min-height: {get_scaled_size(20)}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        # 고정 높이 제거: 탭 위젯 내에서 자동으로 늘어나도록 함
        return edit

    def _on_text_changed(self, tab_name: str):
        """텍스트 변경 시"""
        if tab_name == 'nai':
            new_text = self.nai_edit.toPlainText()
        elif tab_name == 'ollama':
            new_text = self.ollama_edit.toPlainText()
        else:  # translate
            new_text = self.translate_edit.toPlainText()

        self.prompt_changed.emit(self.index, tab_name, new_text)

    def _on_retry_translation(self):
        """번역 재시도"""
        text = self.ollama_edit.toPlainText()
        if text:
            self.translation_requested.emit(self.index, text)

    def get_nai_prompt(self) -> str:
        """NAI 프롬프트 반환"""
        return self.nai_edit.toPlainText()

    def get_ollama_prompt(self) -> str:
        """Ollama 프롬프트 반환"""
        return self.ollama_edit.toPlainText()

    def set_ollama_prompt(self, text: str):
        """Ollama 프롬프트 설정 (자동 생성 시 사용)"""
        self.ollama_edit.setReadOnly(False)
        self.ollama_edit.setPlainText(text)

    def set_translation(self, text: str):
        """번역 텍스트 설정"""
        self.translate_edit.setPlainText(text)


class APIControlPanel(QWidget):
    """API 컨트롤 패널 (우측)"""

    # 시그널
    comfyui_test_requested = pyqtSignal()
    ollama_test_requested = pyqtSignal()
    generate_prompts_requested = pyqtSignal()  # Ollama 자동 프롬프트 생성
    generate_video_requested = pyqtSignal()  # ComfyUI 동영상 생성

    def __init__(self, parent=None):
        super().__init__(parent)

        # ComfyUI 연결 상태
        self.comfyui_connected = False
        self.comfyui_url = "http://127.0.0.1:8188"

        # Ollama 설치 상태
        self.ollama_installed = False
        self.ollama_selected_model = "huihui_ai/qwen3-vl-abliterated:8b-instruct"

        # 해상도 설정 (동영상 생성용)
        self.selected_video_width = 0
        self.selected_video_height = 0
        self.resolution_options = []  # [(width, height, total_pixels, label), ...]

        # 동영상 생성 파라미터
        self.selected_segment_length = 20  # 기본값: 20 (실제 사용 시 +1하여 21)
        self.fps = 16  # 고정값

        # 워크플로우
        self.workflow_data = None

        # 버튼 원래 텍스트 저장 (진행 상황 표시용)
        self._original_generate_prompts_text = "🤖 Ollama 프롬프트 자동 생성"
        self._original_generate_video_text = "🎬 ComfyUI 동영상 생성"

        # Ollama 생성 중 플래그
        self.is_generating_prompts = False

        self._init_ui()

        # 초기 확인
        self._check_comfyui_on_startup()
        self._check_ollama_installed()
        self._load_workflow()

        # 설정 로드
        self._load_settings()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # ComfyUI 설정 그룹
        comfyui_group = self._create_comfyui_group()
        layout.addWidget(comfyui_group)

        # Ollama 설정 그룹
        ollama_group = self._create_ollama_group()
        layout.addWidget(ollama_group)

        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(separator)

        # 실행 버튼
        actions_group = self._create_actions_group()
        layout.addWidget(actions_group)

        # 해상도 설정
        resolution_group = self._create_resolution_group()
        layout.addWidget(resolution_group)

        # 프레임 수 설정
        frame_group = self._create_frame_settings_group()
        layout.addWidget(frame_group)

        layout.addStretch()

    def _create_comfyui_group(self) -> QGroupBox:
        """ComfyUI 설정 그룹"""
        group = QGroupBox("🎬 ComfyUI API")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding-top: {get_scaled_size(12)}px;
                margin-top: {get_scaled_size(8)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(8)}px;
                padding: 0 {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 1행: 서버 상태 표시
        self.comfyui_status = QLabel("⚪ 확인 중...")
        self.comfyui_status.setStyleSheet(f"""
            font-size: {get_scaled_font_size(12)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        layout.addWidget(self.comfyui_status)

        # 워크플로우 상태 표시
        self.workflow_status = QLabel("📋 워크플로우: 로드 중...")
        self.workflow_status.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11)}px;
            color: {DARK_COLORS['text_secondary']};
            margin-left: {get_scaled_size(4)}px;
        """)
        layout.addWidget(self.workflow_status)

        # 워크플로우 파일 열기 버튼
        workflow_btn_layout = QHBoxLayout()
        workflow_btn_layout.setSpacing(4)

        self.open_workflow_btn = QPushButton("📂 워크플로우 파일 열기")
        self.open_workflow_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.open_workflow_btn.setToolTip("ComfyUI에서 이 파일을 로드하여 필요한 노드를 설치하세요")
        self.open_workflow_btn.clicked.connect(self._open_workflow_file)
        workflow_btn_layout.addWidget(self.open_workflow_btn)

        layout.addLayout(workflow_btn_layout)

        # 2행: URL 입력 + 검증 버튼
        url_layout = QHBoxLayout()
        url_layout.setSpacing(4)

        self.comfyui_url_input = QLineEdit(self.comfyui_url)
        self.comfyui_url_input.setPlaceholderText("http://127.0.0.1:8188")
        self.comfyui_url_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(11)}px;
            }}
            QLineEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        url_layout.addWidget(self.comfyui_url_input, stretch=1)

        verify_btn = QPushButton("🔍 검증")
        verify_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        verify_btn.setFixedWidth(get_scaled_size(120))
        verify_btn.clicked.connect(self._verify_comfyui)
        url_layout.addWidget(verify_btn)

        layout.addLayout(url_layout)

        return group

    def _create_ollama_group(self) -> QGroupBox:
        """Ollama 설정 그룹"""
        group = QGroupBox("🤖 Ollama API")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding-top: {get_scaled_size(12)}px;
                margin-top: {get_scaled_size(8)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(8)}px;
                padding: 0 {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 3행: Ollama 설치 상태
        self.ollama_status = QLabel("⚪ 확인 중...")
        self.ollama_status.setStyleSheet(f"""
            font-size: {get_scaled_font_size(12)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        layout.addWidget(self.ollama_status)

        # 4행: 모델 선택 콤보박스
        model_layout = QHBoxLayout()
        model_layout.setSpacing(4)

        model_label = QLabel("모델:")
        model_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        model_label.setFixedWidth(get_scaled_size(40))
        model_layout.addWidget(model_label)

        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.addItems([
            "huihui_ai/qwen3-vl-abliterated:8b-instruct",
            "huihui_ai/qwen3-vl-abliterated:4b-instruct"
        ])
        self.ollama_model_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(11)}px;
            }}
            QComboBox:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid {DARK_COLORS['text_secondary']};
                margin-right: {get_scaled_size(6)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.ollama_model_combo.currentTextChanged.connect(self._on_model_changed)
        model_layout.addWidget(self.ollama_model_combo, stretch=1)

        layout.addLayout(model_layout)

        return group

    def _create_actions_group(self) -> QGroupBox:
        """실행 액션 그룹"""
        group = QGroupBox("⚡ 실행")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding-top: {get_scaled_size(12)}px;
                margin-top: {get_scaled_size(8)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(8)}px;
                padding: 0 {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 5행: Ollama 프롬프트 자동 생성 버튼
        self.generate_prompts_btn = QPushButton("🤖 Ollama 프롬프트 자동 생성")
        self.generate_prompts_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_prompts_btn.clicked.connect(self._on_generate_prompts_clicked)
        self.generate_prompts_btn.setEnabled(False)  # 초기에는 비활성화
        layout.addWidget(self.generate_prompts_btn)

        # ComfyUI 동영상 생성 버튼
        self.generate_video_btn = QPushButton("🎬 ComfyUI 동영상 생성")
        self.generate_video_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_video_btn.clicked.connect(self.generate_video_requested.emit)
        self.generate_video_btn.setEnabled(False)  # 초기에는 비활성화
        layout.addWidget(self.generate_video_btn)

        return group

    def _create_resolution_group(self) -> QGroupBox:
        """해상도 설정 그룹"""
        group = QGroupBox("📐 동영상 해상도")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding-top: {get_scaled_size(12)}px;
                margin-top: {get_scaled_size(8)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(8)}px;
                padding: 0 {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 해상도 안내 레이블
        info_label = QLabel("이미지 비율에 맞춰 동영상 해상도를 선택하세요:")
        info_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        layout.addWidget(info_label)

        # 라디오 버튼 그룹
        self.resolution_radio_group = QButtonGroup(self)

        # 3개의 라디오 버튼 플레이스홀더 (이미지 로드 후 갱신됨)
        self.resolution_radio_low = QRadioButton("저해상도 (계산 중...)")
        self.resolution_radio_mid = QRadioButton("중해상도 (계산 중...)")
        self.resolution_radio_high = QRadioButton("고해상도 (계산 중...)")

        radio_style = f"""
            QRadioButton {{
                font-size: {get_scaled_font_size(12)}px;
                color: {DARK_COLORS['text_primary']};
                spacing: {get_scaled_size(6)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
            QRadioButton::indicator:unchecked {{
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(8)}px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(8)}px;
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """

        self.resolution_radio_low.setStyleSheet(radio_style)
        self.resolution_radio_mid.setStyleSheet(radio_style)
        self.resolution_radio_high.setStyleSheet(radio_style)

        # 기본 선택: 저해상도 (262144)
        self.resolution_radio_low.setChecked(True)

        # 라디오 그룹에 추가
        self.resolution_radio_group.addButton(self.resolution_radio_low, 0)
        self.resolution_radio_group.addButton(self.resolution_radio_mid, 1)
        self.resolution_radio_group.addButton(self.resolution_radio_high, 2)

        # 레이아웃에 추가
        layout.addWidget(self.resolution_radio_low)
        layout.addWidget(self.resolution_radio_mid)
        layout.addWidget(self.resolution_radio_high)

        # 라디오 버튼 변경 시 선택 업데이트 및 저장
        self.resolution_radio_group.buttonClicked.connect(self._on_resolution_changed)
        self.resolution_radio_group.buttonClicked.connect(self._save_settings)

        return group

    def _create_frame_settings_group(self) -> QGroupBox:
        """프레임 수 설정 그룹"""
        group = QGroupBox("🎞️ 동영상 프레임 설정")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding-top: {get_scaled_size(12)}px;
                margin-top: {get_scaled_size(8)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(8)}px;
                padding: 0 {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 안내 레이블
        info_label = QLabel("이미지당 프레임 수 (실제: 선택값+1):")
        info_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        layout.addWidget(info_label)

        # 라디오 버튼 그룹
        self.frame_radio_group = QButtonGroup(self)

        # 2개의 라디오 버튼
        self.frame_radio_20 = QRadioButton("20 프레임 (실제: 21)")
        self.frame_radio_40 = QRadioButton("40 프레임 (실제: 41)")

        radio_style = f"""
            QRadioButton {{
                font-size: {get_scaled_font_size(12)}px;
                color: {DARK_COLORS['text_primary']};
                spacing: {get_scaled_size(6)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
            QRadioButton::indicator:unchecked {{
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(8)}px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(8)}px;
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """

        self.frame_radio_20.setStyleSheet(radio_style)
        self.frame_radio_40.setStyleSheet(radio_style)

        # 기본 선택: 20 프레임
        self.frame_radio_20.setChecked(True)

        # 라디오 그룹에 추가
        self.frame_radio_group.addButton(self.frame_radio_20, 0)
        self.frame_radio_group.addButton(self.frame_radio_40, 1)

        # 레이아웃에 추가
        layout.addWidget(self.frame_radio_20)
        layout.addWidget(self.frame_radio_40)

        # FPS 표시 (동적 변경 가능)
        self.fps_label = QLabel(f"FPS: {self.fps}")
        self.fps_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11)}px;
            color: {DARK_COLORS['text_secondary']};
            margin-top: {get_scaled_size(4)}px;
        """)
        layout.addWidget(self.fps_label)

        # 라디오 버튼 변경 시 선택 업데이트 및 저장
        self.frame_radio_group.buttonClicked.connect(self._on_frame_setting_changed)
        self.frame_radio_group.buttonClicked.connect(self._save_settings)

        return group

    # === 초기 확인 메서드 ===

    def _check_comfyui_on_startup(self):
        """윈도우 열릴 때 ComfyUI 서버 자동 확인"""
        url = self.comfyui_url_input.text().strip()
        if not url:
            self.comfyui_status.setText("⚪ URL 미입력")
            return

        try:
            response = requests.get(f"{url}/object_info", timeout=2)
            if response.status_code == 200:
                self.comfyui_connected = True
                self.comfyui_status.setText(f"🟢 연결됨")
                self.generate_video_btn.setEnabled(True)
                print(f"[ComfyUI] 연결 성공: {url}")
            else:
                self.comfyui_connected = False
                self.comfyui_status.setText(f"🔴 연결 실패 (HTTP {response.status_code})")
                self.generate_video_btn.setEnabled(False)
        except requests.exceptions.Timeout:
            self.comfyui_connected = False
            self.comfyui_status.setText("🔴 타임아웃")
            self.generate_video_btn.setEnabled(False)
        except requests.exceptions.ConnectionError:
            self.comfyui_connected = False
            self.comfyui_status.setText("🔴 서버 미실행")
            self.generate_video_btn.setEnabled(False)
        except Exception as e:
            self.comfyui_connected = False
            self.comfyui_status.setText(f"🔴 오류: {str(e)[:20]}")
            self.generate_video_btn.setEnabled(False)

    def _verify_comfyui(self):
        """ComfyUI 연결 검증 (버튼 클릭 시)"""
        url = self.comfyui_url_input.text().strip()
        if not url:
            msg = _create_styled_messagebox(self, QMessageBox.Icon.Warning, "입력 오류", "ComfyUI URL을 입력하세요.")
            msg.exec()
            return

        self.comfyui_url = url
        self.comfyui_status.setText("⚪ 확인 중...")
        QApplication.processEvents()

        self._check_comfyui_on_startup()

        # 연결 성공 시 안내 메시지
        if self.comfyui_connected:
            msg = _create_styled_messagebox(
                self,
                QMessageBox.Icon.Information,
                "ComfyUI 연결 성공",
                "ComfyUI 서버에 연결되었습니다!\n\n"
                "아래 '워크플로우 파일 열기' 버튼을 눌러\n"
                "Autoharmonica.json 파일을 ComfyUI에 직접 로드하고\n"
                "필요한 노드들을 설치하세요."
            )
            msg.exec()

    def _check_ollama_installed(self):
        """Ollama 설치 여부 확인 (subprocess)"""
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            if result.returncode == 0:
                version = result.stdout.strip()
                self.ollama_installed = True
                
                # Python 패키지 확인
                if self._check_ollama_package():
                    self.ollama_status.setText(f"🟢 설치됨: {version}")
                else:
                    self.ollama_status.setText(f"🟡 서버O / 패키지X")
                
                # 서버가 있으면 버튼 활성화 (클릭 시 패키지 설치 유도)
                self.generate_prompts_btn.setEnabled(True)
                print(f"[Ollama] 설치 확인: {version}")
            else:
                self.ollama_installed = False
                self.ollama_status.setText("🔴 미설치")
                self.generate_prompts_btn.setEnabled(False)
        except FileNotFoundError:
            self.ollama_installed = False
            self.ollama_status.setText("🔴 미설치")
            self.generate_prompts_btn.setEnabled(False)
        except subprocess.TimeoutExpired:
            self.ollama_installed = False
            self.ollama_status.setText("🔴 타임아웃")
            self.generate_prompts_btn.setEnabled(False)
        except Exception as e:
            self.ollama_installed = False
            self.ollama_status.setText(f"🔴 오류: {str(e)[:20]}")
            self.generate_prompts_btn.setEnabled(False)

    def _on_model_changed(self, model_name: str):
        """모델 선택 변경 시"""
        self.ollama_selected_model = model_name
        print(f"[Ollama] 모델 선택: {model_name}")

        # 설정 저장
        self._save_settings()

        # Ollama API로 모델이 로컬에 있는지 확인
        from core.ollama_service import OllamaService
        service = OllamaService()
        
        # 서버가 실행 중인 경우 모델 목록을 가져와 확인
        if service.is_server_running():
            if service.check_model_exists(model_name):
                print(f"[Ollama] 모델 설치 확인됨: {model_name}")
                # 기존 설치 정보를 유지하면서 모델 확인됨 표시 (선택 사항)
                if "미설치" in self.ollama_status.text() or "모델" in self.ollama_status.text():
                    self._check_ollama_installed() # 상태 정보 갱신
            else:
                print(f"[Ollama] 경고: 모델이 로컬에 없습니다: {model_name}")
                self.ollama_status.setText(f"🟡 모델 미설치: {model_name}")
        else:
            # 서버가 꺼져있으면 확인 불가
            print(f"[Ollama] 서버가 꺼져있어 모델 '{model_name}' 확인을 건너뜁니다.")

    # === Ollama 프롬프트 생성 버튼 클릭 ===

    def _on_generate_prompts_clicked(self):
        """Ollama 프롬프트 자동 생성 버튼 클릭 (시작/중단 토글)"""
        # 생성 중이라면 중단
        if self.is_generating_prompts:
            self._stop_prompt_generation()
            return

        # 1. Ollama 설치 확인
        if not self.ollama_installed:
            msg = _create_styled_messagebox(
                self,
                QMessageBox.Icon.Warning,
                "Ollama 미설치",
                "Ollama가 설치되어 있지 않습니다.\n\nhttps://ollama.com 에서 설치해주세요."
            )
            msg.exec()
            return

        # 2. Python ollama 패키지 확인
        if not self._check_ollama_package():
            # 설치 다이얼로그 표시
            self._install_ollama_package()
            return

        # 3. 모델 확인 (TODO)
        # TODO: ollama list로 모델이 로컬에 있는지 확인
        # 없으면 ollama pull 안내

        # 4. 프롬프트 생성 요청 시그널 발생
        self.generate_prompts_requested.emit()

    def _stop_prompt_generation(self):
        """Ollama 프롬프트 생성 중단"""
        print("[APIControlPanel] 프롬프트 생성 중단 요청됨")
        # 부모 다이얼로그의 _stop_all_workers 호출
        parent = self.parent()
        while parent:
            if hasattr(parent, '_stop_all_workers'):
                parent._stop_all_workers()
                break
            parent = parent.parent()

    def set_generating_state(self, is_generating: bool, progress_text: str = ""):
        """프롬프트 생성 중 상태 설정 (버튼 스타일 변경)

        Args:
            is_generating: True면 생성 중 (빨간색), False면 대기 중 (파란색)
            progress_text: 진행 상황 텍스트 (예: "⏳ 프롬프트 생성 중... (1/3)")
        """
        self.is_generating_prompts = is_generating

        if is_generating:
            # 빨간색 스타일 (중단 버튼)
            self.generate_prompts_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #D32F2F;
                    color: #FFFFFF;
                    border: none;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                    font-size: {get_scaled_font_size(13)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #F44336;
                }}
                QPushButton:pressed {{
                    background-color: #B71C1C;
                }}
            """)
            # 텍스트 설정 (중단 안내 포함)
            if progress_text:
                self.generate_prompts_btn.setText(f"{progress_text} [클릭하여 중단]")
            else:
                self.generate_prompts_btn.setText("🛑 생성 중단")
            self.generate_prompts_btn.setEnabled(True)  # 클릭 가능하게
        else:
            # 원래 스타일 복원 (파란색)
            self.generate_prompts_btn.setStyleSheet(DARK_STYLES['primary_button'])
            self.generate_prompts_btn.setText(self._original_generate_prompts_text)
            # 활성화 상태는 Ollama 설치 여부에 따라 결정됨
            if self.ollama_installed:
                self.generate_prompts_btn.setEnabled(True)
            else:
                self.generate_prompts_btn.setEnabled(False)

    def _check_ollama_package(self) -> bool:
        """Python ollama 패키지 설치 여부 확인"""
        global HAS_OLLAMA
        if HAS_OLLAMA:
            return True

        try:
            spec = importlib.util.find_spec('ollama')
            if spec:
                HAS_OLLAMA = True
                return True
            return False
        except Exception:
            return False

    def _install_ollama_package(self):
        """ollama 패키지 설치"""
        # 가상환경 확인
        venv_active = hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
        if not venv_active:
            msg = _create_styled_messagebox(
                self,
                QMessageBox.Icon.Warning,
                "설치 불가",
                "가상환경에서만 패키지를 설치할 수 있습니다.\n\n"
                "터미널에서 직접 설치해주세요:\npip install ollama"
            )
            msg.exec()
            return

        # 설치 확인 다이얼로그
        reply_msg = _create_styled_messagebox(
            self,
            QMessageBox.Icon.Question,
            "패키지 설치",
            "Python ollama 패키지가 필요합니다.\n\n지금 설치하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        reply = reply_msg.exec()

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 진행 다이얼로그
        progress = QProgressDialog("ollama 패키지 설치 중...", "취소", 0, 0, self)
        progress.setWindowTitle("패키지 설치")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setStyleSheet(f"""
            QProgressDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QLabel {{ color: {DARK_COLORS['text_primary']}; }}
            QProgressBar {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{ background-color: {DARK_COLORS['accent_blue']}; }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        progress.show()
        QApplication.processEvents()

        try:
            # pip install 실행
            pip_cmd = [sys.executable, '-m', 'pip', 'install', 'ollama']
            print(f"🔧 실행: {' '.join(pip_cmd)}")

            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            progress.close()

            if result.returncode == 0:
                print("✅ ollama 패키지 설치 완료")
                msg = _create_styled_messagebox(
                    self,
                    QMessageBox.Icon.Information,
                    "설치 완료",
                    "ollama 패키지가 설치되었습니다.\n\n이제 Ollama 프롬프트 생성을 사용할 수 있습니다."
                )
                msg.exec()

                # 전역 변수 업데이트 및 버튼 활성화
                global HAS_OLLAMA
                HAS_OLLAMA = True
                self.generate_prompts_btn.setEnabled(True)

                # 다시 생성 요청
                self._on_generate_prompts_clicked()
            else:
                error_msg = result.stderr if result.stderr else "Unknown error"
                print(f"❌ ollama 설치 실패: {error_msg}")
                msg = _create_styled_messagebox(
                    self,
                    QMessageBox.Icon.Critical,
                    "설치 실패",
                    f"패키지 설치에 실패했습니다.\n\n{error_msg[:200]}"
                )
                msg.exec()
        except subprocess.TimeoutExpired:
            progress.close()
            msg = _create_styled_messagebox(self, QMessageBox.Icon.Critical, "설치 실패", "설치 시간이 초과되었습니다.")
            msg.exec()
        except Exception as e:
            progress.close()
            print(f"❌ ollama 설치 오류: {e}")
            msg = _create_styled_messagebox(self, QMessageBox.Icon.Critical, "설치 오류", f"설치 중 오류가 발생했습니다.\n\n{str(e)}")
            msg.exec()

    # === 상태 설정 메서드 (하위 호환성) ===

    def set_comfyui_status(self, connected: bool, message: str = ""):
        """ComfyUI 연결 상태 설정 (외부 호출용)"""
        self.comfyui_connected = connected
        if connected:
            self.comfyui_status.setText(f"🟢 연결됨 {message}")
            self.generate_video_btn.setEnabled(True)
        else:
            self.comfyui_status.setText(f"🔴 미연결 {message}")
            self.generate_video_btn.setEnabled(False)

    def set_ollama_status(self, connected: bool, message: str = ""):
        """Ollama 연결 상태 설정 (외부 호출용)"""
        self.ollama_installed = connected
        if connected:
            self.ollama_status.setText(f"🟢 연결됨 {message}")
            # Python 패키지도 확인 필요
            if self._check_ollama_package():
                self.generate_prompts_btn.setEnabled(True)
        else:
            self.ollama_status.setText(f"🔴 미연결 {message}")
            self.generate_prompts_btn.setEnabled(False)

    # === 해상도 계산 메서드 ===

    def calculate_resolution_options(self, image_size: tuple) -> List[tuple]:
        """
        이미지 크기를 기반으로 동영상 해상도 옵션 계산

        Args:
            image_size: (width, height) 튜플

        Returns:
            [(width, height, total_pixels, label), ...] 리스트
            - 262144 픽셀 (저해상도)
            - 409600 픽셀 (중해상도)
            - 589824 픽셀 (고해상도)
        """
        orig_width, orig_height = image_size

        # 8로 나눠 나머지 버림 (floor division)
        width_div8 = (orig_width // 8) * 8
        height_div8 = (orig_height // 8) * 8

        # 비율 계산 (GCD로 단순화)
        from math import gcd
        divisor = gcd(width_div8, height_div8)
        aspect_w = width_div8 // divisor
        aspect_h = height_div8 // divisor

        print(f"[Resolution] 원본: {orig_width}x{orig_height}")
        print(f"[Resolution] 8정렬: {width_div8}x{height_div8}")
        print(f"[Resolution] 비율: {aspect_w}:{aspect_h}")

        # 3개의 목표 픽셀 수
        target_pixels = [262144, 409600, 589824]
        labels = ["저해상도", "중해상도", "고해상도"]

        options = []
        for i, total_px in enumerate(target_pixels):
            # 비율을 유지하면서 총 픽셀 수에 맞는 width, height 계산
            # width * height = total_px
            # width / height = aspect_w / aspect_h
            # => width = sqrt(total_px * aspect_w / aspect_h)

            import math
            width_f = math.sqrt(total_px * aspect_w / aspect_h)
            height_f = math.sqrt(total_px * aspect_h / aspect_w)

            # 8의 배수로 반올림
            width = round(width_f / 8) * 8
            height = round(height_f / 8) * 8

            # 실제 픽셀 수 (약간 다를 수 있음)
            actual_px = width * height

            label = f"{labels[i]} ({width}x{height}, {actual_px:,}px)"
            options.append((width, height, actual_px, label))

            print(f"[Resolution] {labels[i]}: {width}x{height} ({actual_px:,}px)")

        return options

    def update_resolution_ui(self, processed_images: List[Image.Image]):
        """
        이미지 크기를 읽어 해상도 옵션 계산 및 UI 업데이트

        Args:
            processed_images: 전처리된 이미지 리스트 (모두 동일한 크기)
        """
        if not processed_images:
            print("[Resolution] 이미지가 없어 해상도를 계산할 수 없습니다.")
            return

        # 첫 번째 이미지 크기 사용 (모두 균일함)
        image_size = processed_images[0].size

        # 해상도 옵션 계산
        self.resolution_options = self.calculate_resolution_options(image_size)

        # 라디오 버튼 텍스트 업데이트
        if len(self.resolution_options) >= 3:
            self.resolution_radio_low.setText(self.resolution_options[0][3])
            self.resolution_radio_mid.setText(self.resolution_options[1][3])
            self.resolution_radio_high.setText(self.resolution_options[2][3])

            # 기본 선택값 적용 (저해상도)
            self._on_resolution_changed()

    def _on_resolution_changed(self):
        """해상도 라디오 버튼 선택 변경 시 호출"""
        selected_id = self.resolution_radio_group.checkedId()

        if selected_id >= 0 and selected_id < len(self.resolution_options):
            width, height, total_px, _ = self.resolution_options[selected_id]
            self.selected_video_width = width
            self.selected_video_height = height
            print(f"[Resolution] 선택됨: {width}x{height} ({total_px:,}px)")
        else:
            # 옵션이 아직 계산되지 않은 경우
            self.selected_video_width = 0
            self.selected_video_height = 0

    def _on_frame_setting_changed(self):
        """프레임 설정 라디오 버튼 선택 변경 시 호출"""
        selected_id = self.frame_radio_group.checkedId()

        if selected_id == 0:
            self.selected_segment_length = 20
            # 20프레임 선택 시 FPS를 12로 변경
            self.fps = 12
            self.fps_label.setText(f"FPS: {self.fps}")
            print(f"[FrameSettings] 선택됨: 20 프레임 (실제: 21), FPS: 12")
        elif selected_id == 1:
            self.selected_segment_length = 40
            # 40프레임 선택 시 FPS를 16으로 복원
            self.fps = 16
            self.fps_label.setText(f"FPS: {self.fps}")
            print(f"[FrameSettings] 선택됨: 40 프레임 (실제: 41), FPS: 16")

    # === 워크플로우 관리 메서드 ===

    def _load_workflow(self):
        """Autoharmonica 워크플로우 로드"""
        workflow_path = Path(__file__).parent.parent.parent.parent / "workflows" / "Autoharmonica.json"

        if not workflow_path.exists():
            print(f"[Workflow] 워크플로우 파일을 찾을 수 없습니다: {workflow_path}")
            self.workflow_status.setText("📋 워크플로우: ❌ 파일 없음")
            self.workflow_status.setStyleSheet(f"""
                font-size: {get_scaled_font_size(11)}px;
                color: #F44336;
                margin-left: {get_scaled_size(4)}px;
            """)
            return

        try:
            import json
            with open(workflow_path, 'r', encoding='utf-8') as f:
                self.workflow_data = json.load(f)
            print(f"[Workflow] 워크플로우 로드 성공: {len(self.workflow_data)} 노드")
            self.workflow_status.setText(f"📋 워크플로우: ✅ 로드됨 ({len(self.workflow_data)} 노드)")
            self.workflow_status.setStyleSheet(f"""
                font-size: {get_scaled_font_size(11)}px;
                color: #4CAF50;
                margin-left: {get_scaled_size(4)}px;
            """)
        except Exception as e:
            print(f"[Workflow] 워크플로우 로드 실패: {e}")
            self.workflow_data = None
            self.workflow_status.setText(f"📋 워크플로우: ❌ 로드 실패")
            self.workflow_status.setStyleSheet(f"""
                font-size: {get_scaled_font_size(11)}px;
                color: #F44336;
                margin-left: {get_scaled_size(4)}px;
            """)

    # === 설정 저장/로드 메서드 ===

    def _save_settings(self):
        """현재 설정을 JSON 파일로 저장"""
        settings = {
            "resolution_index": self.resolution_radio_group.checkedId(),
            "frame_index": self.frame_radio_group.checkedId(),
            "ollama_model": self.ollama_selected_model
        }

        settings_path = Path("save") / "sequence_export_settings.json"
        settings_path.parent.mkdir(exist_ok=True)

        try:
            import json
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            print(f"[Settings] 설정 저장됨: {settings}")
        except Exception as e:
            print(f"[Settings] 설정 저장 실패: {e}")

    def _load_settings(self):
        """저장된 설정 로드"""
        settings_path = Path("save") / "sequence_export_settings.json"

        if not settings_path.exists():
            print("[Settings] 저장된 설정 파일 없음 - 기본값 사용")
            return

        try:
            import json
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            print(f"[Settings] 설정 로드됨: {settings}")

            # 시그널 일시 차단 (로드 중 불필요한 저장 방지)
            self.resolution_radio_group.blockSignals(True)
            self.frame_radio_group.blockSignals(True)
            self.ollama_model_combo.blockSignals(True)

            # 해상도 설정 복원
            resolution_index = settings.get("resolution_index", 0)
            if resolution_index in [0, 1, 2]:
                button = self.resolution_radio_group.button(resolution_index)
                if button:
                    button.setChecked(True)
                    self._on_resolution_changed()  # 설정 적용

            # 프레임 설정 복원
            frame_index = settings.get("frame_index", 0)
            if frame_index in [0, 1]:
                button = self.frame_radio_group.button(frame_index)
                if button:
                    button.setChecked(True)
                    self._on_frame_setting_changed()  # 설정 적용

            # Ollama 모델 설정 복원
            ollama_model = settings.get("ollama_model")
            if ollama_model:
                index = self.ollama_model_combo.findText(ollama_model)
                if index >= 0:
                    self.ollama_model_combo.setCurrentIndex(index)
                    self.ollama_selected_model = ollama_model

            # 시그널 차단 해제
            self.resolution_radio_group.blockSignals(False)
            self.frame_radio_group.blockSignals(False)
            self.ollama_model_combo.blockSignals(False)

        except Exception as e:
            print(f"[Settings] 설정 로드 실패: {e}")
            # 오류 시에도 시그널 차단 해제
            self.resolution_radio_group.blockSignals(False)
            self.frame_radio_group.blockSignals(False)
            self.ollama_model_combo.blockSignals(False)

    def _open_workflow_file(self):
        """워크플로우 파일을 파일 탐색기에서 열기"""
        workflow_path = Path(__file__).parent.parent.parent.parent / "workflows" / "Autoharmonica.json"

        if not workflow_path.exists():
            msg = _create_styled_messagebox(
                self,
                QMessageBox.Icon.Warning,
                "파일 없음",
                f"워크플로우 파일을 찾을 수 없습니다:\n{workflow_path}\n\n"
                "workflows/Autoharmonica.json 파일이 존재하는지 확인하세요."
            )
            msg.exec()
            return

        # 플랫폼별 파일 탐색기 열기
        import sys
        import subprocess

        try:
            if sys.platform == 'win32':
                # Windows: 파일 선택 상태로 탐색기 열기
                subprocess.run(['explorer', '/select,', str(workflow_path)], check=True)
            elif sys.platform == 'darwin':
                # macOS: Finder에서 파일 선택
                subprocess.run(['open', '-R', str(workflow_path)], check=True)
            else:
                # Linux: 파일이 있는 폴더 열기
                subprocess.run(['xdg-open', str(workflow_path.parent)], check=True)

            print(f"[Workflow] 파일 탐색기에서 열림: {workflow_path}")

        except Exception as e:
            print(f"[Workflow] 파일 탐색기 열기 실패: {e}")
            msg = _create_styled_messagebox(
                self,
                QMessageBox.Icon.Warning,
                "열기 실패",
                f"파일 탐색기를 열 수 없습니다.\n\n경로: {workflow_path}\n\n"
                "수동으로 위 경로의 파일을 ComfyUI에 로드하세요."
            )
            msg.exec()


from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import QUrl

class SimpleVideoPlayer(QDialog):
    """간단한 비디오 플레이어 팝업"""
    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎥 비디오 미리보기")
        self.resize(800, 600)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        
        # 윈도우 플래그 (일반 창처럼 동작)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMinMaxButtonsHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 비디오 위젯
        self.video_widget = QVideoWidget()
        layout.addWidget(self.video_widget)

        # 컨트롤 바
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(10, 5, 10, 10)
        
        self.play_btn = QPushButton("⏸️ 일시정지")
        self.play_btn.setFixedSize(get_scaled_size(80), get_scaled_size(30))
        self.play_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.play_btn.clicked.connect(self._toggle_playback)
        controls_layout.addWidget(self.play_btn)
        
        self.close_btn = QPushButton("닫기")
        self.close_btn.setFixedSize(get_scaled_size(60), get_scaled_size(30))
        self.close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.close_btn.clicked.connect(self.close)
        controls_layout.addWidget(self.close_btn)
        
        layout.addLayout(controls_layout)

        # 미디어 플레이어 설정
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.setSource(QUrl.fromLocalFile(video_path))
        
        # 반복 재생 설정 (mediaStatusChanged 시그널 연결)
        self.media_player.mediaStatusChanged.connect(self._check_loop)
        
        # 재생 시작
        self.media_player.play()
        self.is_playing = True

    def _check_loop(self, status):
        """동영상 종료 시 다시 처음부터 재생"""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.media_player.play()

    def _toggle_playback(self):
        if self.is_playing:
            self.media_player.pause()
            self.play_btn.setText("▶️ 재생")
        else:
            self.media_player.play()
            self.play_btn.setText("⏸️ 일시정지")
        self.is_playing = not self.is_playing

    def closeEvent(self, event):
        self.media_player.stop()
        super().closeEvent(event)


class SequenceExportDialog(QDialog):
    """시퀀스 외부 API 전송 다이얼로그"""

    # 시그널
    images_exported = pyqtSignal(list)  # List[Path] - 내보낸 이미지 경로들
    video_generated = pyqtSignal(str)  # MP4 파일 경로

    def __init__(
        self,
        images: List[Image.Image],
        prompts: List[Dict],
        app_context: Optional['AppContext'] = None,
        parent=None
    ):
        """
        Args:
            images: PIL 이미지 리스트 (border line 포함)
            prompts: 프롬프트 데이터 리스트
            app_context: AppContext (선택)
        """
        super().__init__(parent)
        self.original_images = images
        # 프롬프트 전처리: 시퀀스 관련 단어 제거
        self.prompts = self._clean_prompts(prompts)
        self.app_context = app_context

        self.image_prompt_widgets: List[ImagePromptWidget] = []

        # ⚡ 이미지 전처리 (UI 초기화 전에 실행)
        print("[SequenceExportDialog] 이미지 전처리 시작...")
        self.processed_images = self._preprocess_images()
        print(f"[SequenceExportDialog] 전처리 완료: {len(self.processed_images)}개 이미지")

        self._init_ui()
        self._populate_widgets()

        # 해상도 옵션 계산 및 UI 업데이트
        self.api_panel.update_resolution_ui(self.processed_images)

        # 콘솔 로그 윈도우 생성 및 표시
        self.console_window = ConsoleLogWindow(self)
        self.console_window.append_log("시퀀스 내보내기 다이얼로그 초기화 완료", "INFO")

        # 중단 시그널 연결
        self.console_window.stop_requested.connect(self._stop_all_workers)

        # 도킹 오프셋 설정 (부모 윈도우 오른쪽에 10px 간격)
        self.console_window.dock_offset = (10, 0)

        # 기본적으로 숨김 (사용자가 "로그 열기" 버튼으로 열 수 있음)

    def _init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("🚀 시퀀스 외부 API 전송")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        
        # 윈도우 플래그 설정: 항상 위(WindowStaysOnTopHint) 제거하고 일반 대화상자로 설정
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 헤더
        header = self._create_header()
        layout.addWidget(header)

        # 메인 컨텐츠 (2열)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 좌측: 이미지 + 프롬프트 스크롤 영역
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)

        # 우측: API 컨트롤 패널
        self.api_panel = APIControlPanel()
        self.api_panel.comfyui_test_requested.connect(self._on_comfyui_test)
        self.api_panel.ollama_test_requested.connect(self._on_ollama_test)
        self.api_panel.generate_prompts_requested.connect(self._on_generate_prompts)
        self.api_panel.generate_video_requested.connect(self._on_generate_video)

        right_container = QFrame()
        right_container.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        right_container.setFixedWidth(get_scaled_size(300))
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.api_panel)
        splitter.addWidget(right_container)

        # 비율 설정 (좌측이 더 넓게)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, stretch=1)

        # 하단 버튼
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        # 로그 열기 버튼
        self.show_log_btn = QPushButton("📋 로그 열기")
        self.show_log_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.show_log_btn.clicked.connect(self._show_console_log)
        bottom_layout.addWidget(self.show_log_btn)

        close_btn = QPushButton("✕ 닫기")
        close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        close_btn.clicked.connect(self.close)
        bottom_layout.addWidget(close_btn)

        layout.addLayout(bottom_layout)

    def _create_header(self) -> QFrame:
        """헤더 생성"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel("🚀 NAIA Auto-harmonica")
        title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(18)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(title)

        self.status_label = QLabel(f"총 {len(self.processed_images)}개 이미지 (Border 제거 완료)")
        self.status_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        layout.addWidget(self.status_label)

        layout.addStretch()

        return frame

    def _create_left_panel(self) -> QWidget:
        """좌측 패널 (스크롤 영역)"""
        container = QFrame()
        container.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_secondary']};
                width: {get_scaled_size(12)}px;
                border-radius: {get_scaled_size(6)}px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(6)}px;
                min-height: {get_scaled_size(30)}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)

        # 스크롤 컨테이너
        self.scroll_container = QWidget()
        self.scroll_container.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.scroll_layout = QVBoxLayout(self.scroll_container)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.setContentsMargins(4, 4, 4, 4)

        scroll.setWidget(self.scroll_container)
        layout.addWidget(scroll)

        return container

    def _stop_all_workers(self):
        """모든 활성 워커 및 백엔드 서버 중단"""
        if hasattr(self, 'current_ollama_worker') and self.current_ollama_worker and self.current_ollama_worker.isRunning():
            self.current_ollama_worker.terminate()
            self.current_ollama_worker.wait()
            self.current_ollama_worker = None
            print("[SequenceExportDialog] Ollama Worker 중단됨")

        if hasattr(self, 'current_trans_worker') and self.current_trans_worker and self.current_trans_worker.isRunning():
            self.current_trans_worker.terminate()
            self.current_trans_worker.wait()
            self.current_trans_worker = None
            print("[SequenceExportDialog] Translation Worker 중단됨")

        # ComfyUI 워커 중단
        if hasattr(self, 'current_comfy_worker') and self.current_comfy_worker and self.current_comfy_worker.isRunning():
            self.current_comfy_worker.cancel()
            self.current_comfy_worker.wait()
            self.current_comfy_worker = None
            print("[SequenceExportDialog] ComfyUI Worker 중단됨")

        # Ollama 서버 프로세스 종료 (VRAM 해제)
        from core.ollama_service import OllamaService
        OllamaService().stop_server()
        print("[SequenceExportDialog] Ollama 서버 프로세스 종료됨")

        # 큐 비우기
        if hasattr(self, 'ollama_queue'):
            self.ollama_queue.clear()

        # 버튼 상태 복원 (파란색)
        if hasattr(self, 'api_panel'):
            self.api_panel.set_generating_state(False)
            self.api_panel.generate_prompts_btn.setEnabled(True)
            self.api_panel.generate_video_btn.setEnabled(True)

        # 상태 메시지 업데이트
        if hasattr(self, 'status_label'):
            self.status_label.setText("⚠️ 작업이 중단되었습니다.")

        # 콘솔 로그 및 중단 버튼 비활성화
        if hasattr(self, 'console_window') and self.console_window:
            self.console_window.append_log("모든 작업이 중단되었습니다.", "WARNING")
            self.console_window.enable_stop_button(False)
            self.console_window.set_status("⚠️ 중단됨")

    def closeEvent(self, event):
        """다이얼로그 닫힐 때 워커 정리"""
        print("[SequenceExportDialog] 다이얼로그 닫힘 - 워커 정리 중...")
        self._stop_all_workers()
        event.accept()

    def _populate_widgets(self):
        """이미지 + 프롬프트 위젯 채우기"""
        for i, (image, prompt_data) in enumerate(zip(self.processed_images, self.prompts)):
            widget = ImagePromptWidget(i, image, prompt_data)
            widget.prompt_changed.connect(self._on_prompt_changed)
            widget.translation_requested.connect(self._on_single_translation_requested)
            self.image_prompt_widgets.append(widget)
            self.scroll_layout.addWidget(widget)

    def _on_single_translation_requested(self, index: int, text: str):
        """단일 항목 번역 요청 처리 (재번역)"""
        # 기존 진행중인 작업이 있다면 중단하지 않고, 별도의 워커로 실행하거나
        # 간단하게 TranslationWorker를 로컬 변수로 실행 (GC되지 않도록 리스트에 보관 필요)
        # 여기서는 self.trans_workers 리스트를 사용하여 관리
        if not hasattr(self, 'trans_workers'):
            self.trans_workers = []
            
        worker = TranslationWorker(text, mode='en_to_ko')
        worker.finished.connect(lambda res: self._on_single_translation_finished(index, res, worker))
        worker.error.connect(lambda err: self._on_single_translation_error(index, err, worker))
        
        self.trans_workers.append(worker)
        worker.start()
        
        self.status_label.setText(f"재번역 중... (#{index})")

    def _on_single_translation_finished(self, index: int, result: str, worker):
        if index < len(self.image_prompt_widgets):
            self.image_prompt_widgets[index].set_translation(result)
        self.status_label.setText(f"재번역 완료 (#{index})")
        if worker in self.trans_workers:
            self.trans_workers.remove(worker)

    def _on_single_translation_error(self, index: int, error: str, worker):
        print(f"[Translation] Error at #{index}: {error}")
        self.status_label.setText(f"재번역 실패 (#{index})")
        if worker in self.trans_workers:
            self.trans_workers.remove(worker)

    def _on_prompt_changed(self, index: int, tab_name: str, new_text: str):
        """프롬프트 변경 시"""
        # TODO: 프롬프트 데이터 업데이트
        print(f"[SequenceExportDialog] Prompt changed: #{index}, {tab_name}, {new_text[:30]}...")

    # === API 컨트롤 슬롯 ===

    def _on_comfyui_test(self):
        """ComfyUI 연결 테스트"""
        from core.comfyui_service import ComfyUIService
        
        url = self.api_panel.comfyui_url_input.text().strip() or "127.0.0.1:8188"
        self.status_label.setText(f"ComfyUI 연결 테스트 중... ({url})")
        QApplication.processEvents()
        
        service = ComfyUIService(server_url=url)
        if service.test_connection():
            self.api_panel.set_comfyui_status(True)
            self.status_label.setText("✅ ComfyUI 연결 성공")
            
            # 모델 목록 가져오기 시도
            models = service.get_available_models()
            if models:
                print(f"[ComfyUI] {len(models)}개 모델 발견")
        else:
            self.api_panel.set_comfyui_status(False)
            self.status_label.setText("❌ ComfyUI 연결 실패 (URL 및 서버 상태를 확인하세요)")

    def _on_ollama_test(self):
        """Ollama 연결 테스트"""
        from core.ollama_service import OllamaService
        
        self.status_label.setText("Ollama 연결 테스트 중...")
        QApplication.processEvents()
        
        service = OllamaService()
        if service.check_connection():
            models = service.get_models()
            model_info = f" ({models[0]})" if models else ""
            self.api_panel.set_ollama_status(True, model_info)
            self.status_label.setText(f"✅ Ollama 연결 성공{model_info}")
            
            # 모델 목록이 있으면 콤보박스 갱신 시도
            if models and hasattr(self.api_panel, 'ollama_model_combo'):
                self.api_panel.ollama_model_combo.clear()
                self.api_panel.ollama_model_combo.addItems(models)
        else:
            self.api_panel.set_ollama_status(False)
            self.status_label.setText("❌ Ollama 연결 실패 (서버가 실행 중인지 확인하세요)")

    def _on_generate_prompts(self):
        """Ollama 프롬프트 자동 생성 (순차 처리)"""
        # 1. Ollama 서버 상태 확인 및 시작
        from core.ollama_service import OllamaService
        self.ollama_service = OllamaService()
        
        if not self.ollama_service.is_server_running():
            self.status_label.setText("Ollama 서버 시작 중...")
            QApplication.processEvents()
            if not self.ollama_service.start_server():
                msg = _create_styled_messagebox(
                    self,
                    QMessageBox.Icon.Critical,
                    "Ollama 시작 실패",
                    "Ollama 서버를 시작할 수 없습니다. 수동으로 Ollama를 실행해주세요."
                )
                msg.exec()
                return

        # 1.5 선택한 모델 확인
        selected_model = self.api_panel.ollama_selected_model
        if not self.ollama_service.check_model_exists(selected_model):
            # 모델 미설치 -> 설치 유도
            msg = _create_styled_messagebox(
                self,
                QMessageBox.Icon.Question,
                "모델 미설치",
                f"선택한 모델 '{selected_model}'이 로컬에 없습니다.\n지금 다운로드(pull) 하시겠습니까?\n(시간이 다소 걸릴 수 있습니다)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            reply = msg.exec()
            
            if reply == QMessageBox.StandardButton.Yes:
                # 다운로드 진행 (터미널 실행)
                try:
                    if sys.platform == 'win32':
                        subprocess.Popen(f'start cmd /k "ollama pull {selected_model}"', shell=True)
                    else:
                        # Mac/Linux (단순 예시)
                        subprocess.Popen(['x-terminal-emulator', '-e', f'ollama pull {selected_model}'])
                    
                    _create_styled_messagebox(
                        self,
                        QMessageBox.Icon.Information,
                        "다운로드 시작",
                        "터미널에서 다운로드가 시작되었습니다.\n완료 후 다시 시도해주세요."
                    ).exec()
                except Exception as e:
                    _create_styled_messagebox(
                        self,
                        QMessageBox.Icon.Critical,
                        "오류",
                        f"터미널 실행 실패: {e}"
                    ).exec()
            return
        else:
            print(f"[Ollama] 모델 확인됨: {selected_model}")

        # 2. 큐 생성 (인덱스 리스트)
        self.ollama_queue = []
        self.ollama_retry_counts = {}  # 🆕 재시도 횟수 추적용
        self.ollama_queue_total = 0  # 전체 개수 저장
        for i, widget in enumerate(self.image_prompt_widgets):
            # NAI 탭에 내용이 있는 경우만 추가
            if widget.get_nai_prompt().strip():
                self.ollama_queue.append(i)

        if not self.ollama_queue:
            msg = _create_styled_messagebox(self, QMessageBox.Icon.Information, "알림", "처리할 NAI 프롬프트가 없습니다.")
            msg.exec()
            return

        self.ollama_queue_total = len(self.ollama_queue)
        self.status_label.setText(f"Ollama 프롬프트 생성 시작 (총 {self.ollama_queue_total}개)...")

        # 버튼을 빨간색 중단 버튼으로 변경
        self.api_panel.set_generating_state(True, f"⏳ 생성 중... (0/{self.ollama_queue_total})")
        self.api_panel.generate_video_btn.setEnabled(False) # 생성 중에는 비디오 생성 차단

        # 콘솔 중단 버튼 활성화
        self.console_window.enable_stop_button(True)

        # 첫 번째 작업 시작
        self._process_next_ollama_task()

    def _process_next_ollama_task(self):
        """다음 Ollama 작업 처리"""
        if not hasattr(self, 'ollama_queue') or not self.ollama_queue:
            self.status_label.setText("✅ Ollama 프롬프트 생성 및 번역 완료")
            # 버튼 상태 복원 (파란색)
            self.api_panel.set_generating_state(False)
            self.api_panel.generate_prompts_btn.setEnabled(True)
            self.api_panel.generate_video_btn.setEnabled(True)
            return

        index = self.ollama_queue[0] # 큐에서 제거하지 않고 참조만 (완료 시 제거)
        widget = self.image_prompt_widgets[index]
        nai_prompt = widget.get_nai_prompt()

        # 진행 상황 계산
        completed = self.ollama_queue_total - len(self.ollama_queue)
        total = self.ollama_queue_total

        # 버튼 텍스트 업데이트 (빨간색 상태 유지)
        self.api_panel.set_generating_state(True, f"⏳ 생성 중... ({completed}/{total})")

        # 시스템 프롬프트 설정 (파일 로드)
        system_prompt = "You are a creative writer. Convert these image tags into a detailed and natural scene description for a video generation prompt."

        if OLLAMA_PROMPT_PATH.exists():
            try:
                system_prompt = OLLAMA_PROMPT_PATH.read_text(encoding='utf-8')
                print(f"[Ollama] 시스템 프롬프트 로드됨: {OLLAMA_PROMPT_PATH}")
            except Exception as e:
                print(f"[Ollama] 시스템 프롬프트 파일 로드 실패: {e}")

        model = self.api_panel.ollama_selected_model

        self.status_label.setText(f"Ollama 생성 중... (#{index+1} / {total})")

        # 이미지 데이터를 bytes로 변환
        import io
        image_bytes = None
        if widget.image:
            try:
                # PIL Image -> Bytes
                with io.BytesIO() as bio:
                    widget.image.save(bio, format="PNG")
                    image_bytes = bio.getvalue()
                print(f"[Ollama] 이미지 데이터 준비 완료 ({len(image_bytes)} bytes)")
            except Exception as e:
                print(f"[Ollama] 이미지 변환 실패: {e}")

        # 사용자 메시지 구성 (태그를 힌트로 전달)
        user_message = (
            f"Here are the user hints/tags for this image: [{nai_prompt}]\n\n"
            "Using the image and these hints, write a detailed, natural language description for a video generation prompt. "
            "Focus on the visual details, actions, and atmosphere. "
            "Ensure the output is a single coherent paragraph, NOT a list of tags."
        )

        # Ollama 워커 생성 및 시작 (이미지 포함)
        from core.ollama_service import OllamaWorker
        self.current_ollama_worker = OllamaWorker(
            user_message,
            model=model,
            system_prompt=system_prompt,
            image_data=image_bytes
        )
        self.current_ollama_worker.finished.connect(lambda res: self._on_ollama_finished(index, res))
        self.current_ollama_worker.error.connect(lambda err: self._on_ollama_error(index, err))

        # 콘솔 로그 연결
        self.console_window.append_log(f"Ollama 생성 시작 (#{index+1}/{total}): {model}", "OLLAMA")
        self.console_window.set_status(f"⏳ Ollama 프롬프트 생성 중... ({completed}/{total})")

        self.current_ollama_worker.start()

    def _on_ollama_finished(self, index: int, result: str):
        """Ollama 생성 완료 처리"""
        # 콘솔 로그
        self.console_window.append_log(f"Ollama 생성 완료 (#{index+1}): {len(result)} 글자", "SUCCESS")

        # 🆕 재시도 로직: 텍스트가 너무 길면 (폭주 의심) 다시 생성 시도
        if len(result) > 2000:
            retry_count = self.ollama_retry_counts.get(index, 0)
            if retry_count < 2:  # 최대 2회 재시도
                self.ollama_retry_counts[index] = retry_count + 1
                self.console_window.append_log(f"⚠️ 결과 너무 김 ({len(result)}자) -> 재시도 중... ({retry_count+1}/2)", "WARNING")
                print(f"[Ollama] Result too long ({len(result)} chars), retrying index {index} (attempt {retry_count+1})...")
                
                # 잠깐 대기 후 다시 시도 (서버 부하 조절)
                QTimer.singleShot(1000, self._process_next_ollama_task)
                return
            else:
                self.console_window.append_log(f"⚠️ 재시도 횟수 초과. 긴 텍스트를 그대로 사용합니다.", "WARNING")

        # 결과 설정
        if index < len(self.image_prompt_widgets):
            widget = self.image_prompt_widgets[index]
            widget.set_ollama_prompt(result)

            # 번역 시작
            self.status_label.setText(f"번역 중... (#{index})")
            self._start_translation(index, result)
        else:
            # 위젯이 없을 경우 (예외적)
            self._finish_current_ollama_task()

    def _on_ollama_error(self, index: int, error: str):
        """Ollama 생성 오류 처리"""
        print(f"[Ollama] Error at #{index}: {error}")

        # 콘솔 로그
        self.console_window.append_log(f"Ollama 오류 (#{index+1}): {error}", "ERROR")

        if index < len(self.image_prompt_widgets):
            widget = self.image_prompt_widgets[index]
            widget.ollama_edit.setPlaceholderText(f"오류 발생: {error}")
        
        # 치명적인 오류(연결 실패)인 경우 전체 작업 중단
        if "연결할 수 없습니다" in error or "Failed to connect" in error or "ConnectionError" in error:
            print("[Ollama] 치명적인 오류 발생. 작업 중단.")
            self.status_label.setText(f"❌ 작업 중단: Ollama 서버 연결 실패")
            self.ollama_queue.clear() # 남은 큐 비우기
            
            msg = _create_styled_messagebox(
                self, 
                QMessageBox.Icon.Critical, 
                "Ollama 연결 실패", 
                "Ollama 서버에 연결할 수 없어 작업을 중단합니다.\nOllama가 실행 중인지 확인해주세요."
            )
            msg.exec()
        
        # 현재 작업 정리 및 (큐가 남았다면) 다음 작업 진행
        self._finish_current_ollama_task()

    def _start_translation(self, index: int, text: str):
        """번역 작업 시작"""
        # 진행 상황 계산
        completed = self.ollama_queue_total - len(self.ollama_queue)
        total = self.ollama_queue_total

        # 버튼 텍스트 업데이트 (번역 중, 빨간색 상태 유지)
        self.api_panel.set_generating_state(True, f"🌐 번역 중... ({completed}/{total})")
        self.status_label.setText(f"번역 중... (#{index+1} / {total})")

        # 콘솔 로그
        self.console_window.append_log(f"번역 시작 (#{index+1}/{total}): {len(text)} 글자", "INFO")
        self.console_window.set_status(f"🌐 번역 중... ({completed}/{total})")

        self.current_trans_worker = TranslationWorker(text, mode='en_to_ko')
        self.current_trans_worker.finished.connect(lambda res: self._on_translation_finished(index, res))
        self.current_trans_worker.error.connect(lambda err: self._on_translation_error(index, err))
        self.current_trans_worker.start()

    def _on_translation_finished(self, index: int, result: str):
        """번역 완료 처리"""
        # 콘솔 로그
        self.console_window.append_log(f"번역 완료 (#{index+1}): {len(result)} 글자", "SUCCESS")

        if index < len(self.image_prompt_widgets):
            widget = self.image_prompt_widgets[index]
            widget.set_translation(result)

        self._finish_current_ollama_task()

    def _on_translation_error(self, index: int, error: str):
        """번역 오류 처리"""
        print(f"[Translation] Error at #{index}: {error}")

        # 콘솔 로그
        self.console_window.append_log(f"번역 오류 (#{index+1}): {error}", "ERROR")

        self._finish_current_ollama_task()

    def _finish_current_ollama_task(self):
        """현재 작업 완료 및 다음 작업으로 이동"""
        if hasattr(self, 'ollama_queue') and self.ollama_queue:
            self.ollama_queue.pop(0)
        
        # 워커 정리
        self.current_ollama_worker = None
        self.current_trans_worker = None
        
        # 다음 작업
        self._process_next_ollama_task()

    def _on_generate_video(self):
        """ComfyUI 동영상 생성 (비동기 워커 사용)"""
        # 실행 중인 Ollama/번역 작업 중단
        self._stop_all_workers()

        print("[SequenceExportDialog] ComfyUI 동영상 생성 시작")
        self.status_label.setText("이미지 저장 중...")

        # 1. 전처리된 이미지를 임시 폴더에 저장
        saved_paths = self._remove_border_and_export_images()
        print(f"[SequenceExportDialog] {len(saved_paths)}개 이미지 저장 완료")

        self.status_label.setText(f"✅ {len(saved_paths)}개 이미지 저장 완료")

        # 검증
        if not saved_paths:
            msg = _create_styled_messagebox(self, QMessageBox.Icon.Warning, "내보내기 실패", "저장된 이미지가 없습니다.")
            msg.exec()
            return

        comfyui_url = self.api_panel.comfyui_url_input.text().strip() or self.api_panel.comfyui_url
        if not comfyui_url:
            msg = _create_styled_messagebox(self, QMessageBox.Icon.Warning, "입력 오류", "ComfyUI URL을 입력하세요.")
            msg.exec()
            return
        if not comfyui_url.startswith(("http://", "https://")):
            comfyui_url = f"http://{comfyui_url}"

        if not self.api_panel.workflow_data:
            msg = _create_styled_messagebox(self, QMessageBox.Icon.Warning, "워크플로우 없음", "워크플로우가 로드되지 않았습니다.")
            msg.exec()
            return

        # 파라미터 준비
        width = self.api_panel.selected_video_width or self.processed_images[0].size[0]
        height = self.api_panel.selected_video_height or self.processed_images[0].size[1]
        segment_length = int(self.api_panel.selected_segment_length)
        fps = int(self.api_panel.fps)

        # 버튼 비활성화
        self.api_panel.generate_video_btn.setEnabled(False)
        self.api_panel.generate_prompts_btn.setEnabled(False)

        # ComfyGenerationWorker 생성 및 시작
        self.current_comfy_worker = ComfyGenerationWorker(
            saved_paths=saved_paths,
            comfyui_url=comfyui_url,
            workflow_data=self.api_panel.workflow_data,
            width=width,
            height=height,
            segment_length=segment_length,
            fps=fps,
            image_prompt_widgets=self.image_prompt_widgets
        )

        # 시그널 연결
        self.current_comfy_worker.progress.connect(self._on_comfy_progress)
        self.current_comfy_worker.finished.connect(self._on_comfy_finished)
        self.current_comfy_worker.error.connect(self._on_comfy_error)

        # 콘솔 로그
        self.console_window.append_log(
            f"ComfyUI 동영상 생성 시작 ({width}x{height}, {segment_length}프레임, {fps}fps)",
            "COMFY"
        )
        self.console_window.set_status("🎬 ComfyUI 동영상 생성 중...")

        # 콘솔 중단 버튼 활성화
        self.console_window.enable_stop_button(True)

        # 워커 시작 (백그라운드 스레드에서 실행)
        self.current_comfy_worker.start()
        print("[ComfyWorker] 워커 시작됨 - UI는 논블로킹 상태")

    def _on_comfy_progress(self, message: str):
        """ComfyWorker 진행 상황 업데이트"""
        self.status_label.setText(message)

        # 콘솔 로그
        self.console_window.append_log(message, "COMFY")

    def _on_comfy_finished(self, output_path: str):
        self.status_label.setText(f"✅ 생성 완료: {Path(output_path).name}")
        self.api_panel.generate_video_btn.setEnabled(True)
        self.api_panel.generate_prompts_btn.setEnabled(True)

        # 콘솔 중단 버튼 비활성화
        self.console_window.enable_stop_button(False)

        self.video_generated.emit(output_path)

        # 완료 메시지 및 파일 열기 질문 (폰트 크기 증가)
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("생성 완료")
        msg.setText(f"동영상이 생성되었습니다.\n저장 경로: {output_path}\n\n지금 재생하시겠습니까?")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        # 스타일 적용 (폰트 크기 +4px)
        font_size = get_scaled_font_size(16)  # 기본 12 + 4
        btn_font_size = get_scaled_font_size(15) # 기본 11 + 4
        
        msg.setStyleSheet(f"""
            QMessageBox {{
                background-color: {DARK_COLORS['bg_primary']};
                color: #FFFFFF;
            }}
            QMessageBox QLabel {{
                color: #FFFFFF;
                font-size: {font_size}px;
            }}
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: #FFFFFF;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                font-size: {btn_font_size}px;
                min-width: {get_scaled_size(80)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        
        reply = msg.exec()
        
        if reply == QMessageBox.StandardButton.Yes:
            # 내장 플레이어로 재생
            player = SimpleVideoPlayer(output_path, self)
            player.exec()
        else:
            # 아니오 누르면 폴더 열기
            try:
                import os
                folder_path = os.path.dirname(output_path)
                if sys.platform == 'win32':
                    os.startfile(folder_path)
                elif sys.platform == 'darwin':
                    subprocess.run(['open', folder_path])
                else:
                    subprocess.run(['xdg-open', folder_path])
            except Exception as e:
                print(f"폴더 열기 실패: {e}")
    def _on_comfy_error(self, error_msg: str):
        """ComfyWorker 오류 처리"""
        print(f"[ComfyWorker] 오류: {error_msg}")
        self.status_label.setText("❌ ComfyUI 동영상 생성 실패")

        # 콘솔 로그
        self.console_window.append_log(f"ComfyUI 오류: {error_msg[:200]}", "ERROR")
        self.console_window.set_status("❌ 오류 발생")

        # 버튼 활성화
        self.api_panel.generate_video_btn.setEnabled(True)
        self.api_panel.generate_prompts_btn.setEnabled(True)

        # 콘솔 중단 버튼 비활성화
        self.console_window.enable_stop_button(False)

        # 오류 메시지 표시
        msg = _create_styled_messagebox(
            self,
            QMessageBox.Icon.Critical,
            "ComfyUI 오류",
            f"동영상 생성 중 오류가 발생했습니다:\n\n{error_msg[:500]}"
        )
        msg.exec()

        # 워커 정리
        self.current_comfy_worker = None

    # === 유틸리티 메서드 ===

    def _clean_prompts(self, prompts: List[Dict]) -> List[Dict]:
        """
        프롬프트에서 시퀀스 관련 단어 제거

        제거 대상: 2koma, comic, split screen (대소문자 무시)

        Args:
            prompts: 원본 프롬프트 딕셔너리 리스트

        Returns:
            정리된 프롬프트 딕셔너리 리스트
        """
        import re

        # 제거할 단어 패턴 (단어 경계 포함, 대소문자 무시)
        remove_patterns = [
            r'\b2koma\b',
            r'\bcomic\b',
            r'\bsplit\s+screen\b'
        ]

        cleaned_prompts = []
        for prompt_data in prompts:
            # 딕셔너리 복사
            cleaned_data = prompt_data.copy()

            # 'general' 필드 처리
            if 'general' in cleaned_data and cleaned_data['general']:
                text = cleaned_data['general']

                # 각 패턴 제거
                for pattern in remove_patterns:
                    text = re.sub(pattern, '', text, flags=re.IGNORECASE)

                # 중복 쉼표/공백 정리
                text = re.sub(r',\s*,', ',', text)  # 연속된 쉼표 제거
                text = re.sub(r'\s+', ' ', text)     # 중복 공백 제거
                text = text.strip(', ')              # 앞뒤 쉼표/공백 제거

                cleaned_data['general'] = text

            cleaned_prompts.append(cleaned_data)

        print(f"[SequenceExportDialog] 프롬프트 정리 완료: {len(cleaned_prompts)}개")
        return cleaned_prompts

    def _preprocess_images(self) -> List[Image.Image]:
        """
        이미지 전처리: Border line 감지 및 제거

        Returns:
            처리된 이미지 리스트 (border 제거됨)
        """
        processed = []

        for i, (image, prompt_data) in enumerate(zip(self.original_images, self.prompts)):
            is_parent = prompt_data.get('is_parent', False)

            if is_parent or i == 0:
                # Parent는 border 없이 그대로 사용
                processed.append(image)
                print(f"  [#{i}] Parent 이미지 - border 제거 없음 ({image.size})")
            else:
                # Child 이미지: border 감지 및 제거
                cleaned = self._remove_border_from_image(image, i)
                processed.append(cleaned)

        # 모든 이미지를 동일한 크기로 통일 (선택적)
        processed = self._unify_image_sizes(processed)

        return processed

    def _remove_border_from_image(self, image: Image.Image, index: int) -> Image.Image:
        """
        단일 이미지에서 검정색 border line 제거

        Args:
            image: 원본 이미지
            index: 이미지 인덱스 (로그용)

        Returns:
            border가 제거된 이미지
        """
        w, h = image.size
        img_array = np.array(image.convert('RGB'))

        # 가로 방향 스캔: 검정색 수평선 찾기
        horizontal_border = self._find_horizontal_border(img_array)

        # 세로 방향 스캔: 검정색 수직선 찾기
        vertical_border = self._find_vertical_border(img_array)

        if horizontal_border is not None:
            # 가로 방향 border 발견: 상단/하단으로 분할
            y_start, y_end = horizontal_border
            print(f"  [#{index}] 가로 border 발견: y={y_start}~{y_end}")

            # 하단 영역 추출 (일반적으로 하단이 현재 Child 이미지)
            # 또는 상단/하단 중 더 큰 영역 선택
            top_height = y_start
            bottom_height = h - y_end

            if bottom_height >= top_height:
                # 하단 영역 사용
                cropped = image.crop((0, y_end, w, h))
                print(f"      → 하단 영역 추출: {cropped.size}")
            else:
                # 상단 영역 사용
                cropped = image.crop((0, 0, w, y_start))
                print(f"      → 상단 영역 추출: {cropped.size}")

            return cropped

        elif vertical_border is not None:
            # 세로 방향 border 발견: 좌측/우측으로 분할
            x_start, x_end = vertical_border
            print(f"  [#{index}] 세로 border 발견: x={x_start}~{x_end}")

            # 우측 영역 추출 (일반적으로 우측이 현재 Child 이미지)
            left_width = x_start
            right_width = w - x_end

            if right_width >= left_width:
                # 우측 영역 사용
                cropped = image.crop((x_end, 0, w, h))
                print(f"      → 우측 영역 추출: {cropped.size}")
            else:
                # 좌측 영역 사용
                cropped = image.crop((0, 0, x_start, h))
                print(f"      → 좌측 영역 추출: {cropped.size}")

            return cropped

        else:
            # Border 없음 - 그대로 반환
            print(f"  [#{index}] Border 없음 - 원본 사용 ({image.size})")
            return image

    def _find_horizontal_border(self, img_array: np.ndarray, threshold: int = 10) -> Optional[tuple]:
        """
        가로 방향 검정색 border line 찾기

        Args:
            img_array: numpy 이미지 배열 (H, W, 3)
            threshold: 검정색 판정 임계값 (0~255)

        Returns:
            (y_start, y_end) 또는 None
        """
        h, w, _ = img_array.shape

        # 각 행의 평균 밝기 계산
        row_means = np.mean(img_array, axis=(1, 2))  # (H,)

        # 검정색 영역 찾기 (연속된 어두운 행)
        black_rows = row_means < threshold
        black_regions = self._find_consecutive_regions(black_rows, min_length=4)

        if black_regions:
            # 가장 긴 검정 영역 선택
            longest = max(black_regions, key=lambda r: r[1] - r[0])
            return longest

        return None

    def _find_vertical_border(self, img_array: np.ndarray, threshold: int = 10) -> Optional[tuple]:
        """
        세로 방향 검정색 border line 찾기

        Args:
            img_array: numpy 이미지 배열 (H, W, 3)
            threshold: 검정색 판정 임계값 (0~255)

        Returns:
            (x_start, x_end) 또는 None
        """
        h, w, _ = img_array.shape

        # 각 열의 평균 밝기 계산
        col_means = np.mean(img_array, axis=(0, 2))  # (W,)

        # 검정색 영역 찾기 (연속된 어두운 열)
        black_cols = col_means < threshold
        black_regions = self._find_consecutive_regions(black_cols, min_length=4)

        if black_regions:
            # 가장 긴 검정 영역 선택
            longest = max(black_regions, key=lambda r: r[1] - r[0])
            return longest

        return None

    def _find_consecutive_regions(self, bool_array: np.ndarray, min_length: int = 4) -> List[tuple]:
        """
        연속된 True 영역 찾기

        Args:
            bool_array: boolean 배열
            min_length: 최소 연속 길이

        Returns:
            [(start, end), ...] 리스트
        """
        regions = []
        start = None

        for i, val in enumerate(bool_array):
            if val:
                if start is None:
                    start = i
            else:
                if start is not None:
                    if i - start >= min_length:
                        regions.append((start, i))
                    start = None

        # 마지막 영역 처리
        if start is not None and len(bool_array) - start >= min_length:
            regions.append((start, len(bool_array)))

        return regions

    def _unify_image_sizes(self, images: List[Image.Image]) -> List[Image.Image]:
        """
        모든 이미지를 동일한 크기로 통일

        Args:
            images: 이미지 리스트

        Returns:
            통일된 크기의 이미지 리스트
        """
        if not images:
            return images

        # 모든 이미지 크기 수집
        sizes = [img.size for img in images]
        widths = [s[0] for s in sizes]
        heights = [s[1] for s in sizes]

        # 가장 작은 크기 찾기 (또는 중간값 사용)
        target_width = min(widths)
        target_height = min(heights)

        print(f"\n[크기 통일] 목표 크기: {target_width}x{target_height}")

        unified = []
        for i, img in enumerate(images):
            if img.size == (target_width, target_height):
                # 이미 목표 크기
                unified.append(img)
            else:
                # 리사이즈 필요
                resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                print(f"  [#{i}] {img.size} → {resized.size}")
                unified.append(resized)

        return unified

    def _remove_border_and_export_images(self) -> List[Path]:
        """
        처리된 이미지를 임시 폴더에 저장

        Returns:
            저장된 이미지 경로 리스트
        """
        # 임시 폴더 생성
        temp_dir = Path('temp/sequence_export')
        temp_dir.mkdir(parents=True, exist_ok=True)

        saved_paths = []

        for i, image in enumerate(self.processed_images):
            # 파일명: {index:03d}.png
            filename = f"{i:03d}.png"
            filepath = temp_dir / filename

            # 저장
            image.save(filepath, format='PNG')
            saved_paths.append(filepath)
            print(f"[저장] {filepath} ({image.size})")

        return saved_paths

    def get_all_prompts(self) -> List[Dict]:
        """
        모든 프롬프트 데이터 반환

        Returns:
            [{'nai': str, 'ollama': str, 'translate': str}, ...]
        """
        result = []
        for widget in self.image_prompt_widgets:
            result.append({
                'nai': widget.get_nai_prompt(),
                'ollama': widget.get_ollama_prompt(),
                'translate': widget.translate_edit.toPlainText()
            })
        return result

    def closeEvent(self, event):
        """다이얼로그 닫기"""
        print("[SequenceExportDialog] Closing...")

        # 1. 실행 중인 워커 중단
        self._stop_all_workers()

        # 2. 콘솔 윈도우 닫기
        if hasattr(self, 'console_window') and self.console_window:
            self.console_window.deleteLater()

        # 3. 임시 파일 정리 (TODO)

        # 4. 부모에게 닫힘 알림 (참조 제거용)
        # SequenceExportDialog는 deleteLater를 통해 스스로 정리되지만,
        # 부모가 관리하는 리스트(_export_dialogs)에서는 명시적으로 제거되어야 함.
        # 이를 위해 parent의 메서드를 호출하거나 시그널을 보낼 수 있음.
        # 여기서는 parent(TurboEventSequenceTab)가 closeEvent를 감지하거나
        # finished 시그널을 사용하도록 유도.

        # QDialog의 finished 시그널은 이미 존재함 (result code와 함께)
        # 추가적인 cleanup 로직이 필요하면 여기서 수행

        super().closeEvent(event)

    def showEvent(self, event):
        """다이얼로그 표시 시 콘솔 윈도우 도킹 위치 초기화"""
        super().showEvent(event)
        if hasattr(self, 'console_window') and self.console_window:
            self.console_window.update_docked_position()

    def moveEvent(self, event):
        """다이얼로그 이동 시 콘솔 윈도우도 함께 이동 (도킹)"""
        super().moveEvent(event)
        if hasattr(self, 'console_window') and self.console_window and self.console_window.isVisible():
            self.console_window.update_docked_position()

    def _show_console_log(self):
        """콘솔 로그 창 표시"""
        if hasattr(self, 'console_window') and self.console_window:
            self.console_window.show()
            self.console_window.update_docked_position()
            self.console_window.raise_()
            self.console_window.activateWindow()

    def keyPressEvent(self, event):
        """키보드 이벤트"""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
