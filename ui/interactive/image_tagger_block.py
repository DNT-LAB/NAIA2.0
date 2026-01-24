
import os
import io
import ssl
import numpy as np
import pandas as pd
from PIL import Image
from dataclasses import dataclass
from typing import Optional, List, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QFileDialog, QFrame, QTextEdit, QApplication, QProgressBar,
    QDialog, QTextBrowser, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QBuffer, QThread, QObject, pyqtSlot
from PyQt6.QtGui import QPixmap, QAction, QGuiApplication, QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QMessageBox, QProgressDialog 
import importlib.util
import sys
import subprocess

# Import necessary libraries for tagging
try:
    import onnxruntime as ort
    HAS_TAGGER_LIBS = True
except ImportError:
    HAS_TAGGER_LIBS = False
    # print("ImageTaggerBlock: Required library (onnxruntime) found.")

from ui.interactive.block_widget import BlockWidget
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.interactive.interactive_theme import (
    COMMON_STYLES,
    get_button_style,
    FONT_FAMILY
)
from ui.scaling_manager import get_scaled_size, get_scaled_font_size

# 상수 정의
# Direct Download URLs
MODEL_URL = "https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/resolve/main/model.onnx"
TAGS_URL = "https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/resolve/main/selected_tags.csv"
IMAGE_SIZE = 448

# SSL 컨텍스트 (e621 모듈 패턴 참고)
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()
    SSL_CONTEXT.check_hostname = False
    SSL_CONTEXT.verify_mode = ssl.CERT_NONE

# 전역 캐시 (모델 세션 및 태그 데이터 재사용)
_TAGGER_CACHE = {
    "session": None,
    "names": None,
    "categories": None,
    "onnx_path": None,
    "csv_path": None
}

# --- 로직 함수들 (User Provided) ---

def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))

def preprocess_image(pil_image: Image.Image) -> np.ndarray:
    """
    이미지를 WD Tagger v3 ONNX 모델 입력 형식으로 전처리합니다.
    참고: https://github.com/phppan/wd-swinv2-tagger-v3-script

    처리 순서:
    1. RGBA 변환 후 흰 배경 합성
    2. 정사각형 패딩 (흰색)
    3. 448x448 리사이즈
    4. BGR 변환 (중요!)
    5. 배치 차원 추가
    """
    # 1. RGBA 변환 후 흰 배경에 합성 (투명 배경 처리)
    image = pil_image.convert("RGBA")
    canvas = Image.new("RGBA", image.size, (255, 255, 255, 255))
    canvas.paste(image, mask=image)
    image = canvas.convert("RGB")

    # 2. 정사각형 패딩 (중앙 정렬, 흰색 패딩)
    max_dim = max(image.size)
    pad_left = (max_dim - image.size[0]) // 2
    pad_top = (max_dim - image.size[1]) // 2

    padded = Image.new("RGB", (max_dim, max_dim), (255, 255, 255))
    padded.paste(image, (pad_left, pad_top))

    # 3. 리사이즈
    padded = padded.resize((IMAGE_SIZE, IMAGE_SIZE), resample=Image.BICUBIC)

    # 4. NumPy 변환 및 BGR 변환
    image_array = np.asarray(padded, dtype=np.float32)
    image_array = image_array[:, :, ::-1]  # RGB → BGR 변환

    # 5. 배치 차원 추가
    x = np.expand_dims(image_array, axis=0)  # (H, W, C) → (1, H, W, C)

    return x

def load_tags(csv_path: str):
    df = pd.read_csv(csv_path)
    if "name" in df.columns:
        names = df["name"].astype(str).tolist()
    elif "tag" in df.columns:
        names = df["tag"].astype(str).tolist()
    else:
        names = df.iloc[:, 0].astype(str).tolist()

    categories = df["category"].tolist() if "category" in df.columns else None
    return names, categories

def download_file(url, save_path, progress_callback=None):
    """
    URL에서 파일을 다운로드합니다. (requests 라이브러리 사용)

    Args:
        url: 다운로드할 URL
        save_path: 저장할 파일 경로
        progress_callback: 진행 상황 콜백 함수 (downloaded_bytes, total_bytes)

    Returns:
        bool: 성공 여부
    """
    import requests

    print(f"[Tagger DL] 시작: {url}")
    print(f"[Tagger DL] 저장: {save_path}")

    try:
        # 브라우저 스타일 헤더
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Connection': 'keep-alive',
        }

        print(f"[Tagger DL] 연결 중...")
        # stream=True로 청크 단위 다운로드
        response = requests.get(url, headers=headers, stream=True, timeout=60, verify=True)
        response.raise_for_status()

        # 리다이렉트된 URL 확인
        if response.url != url:
            print(f"[Tagger DL] 리다이렉트: {response.url}")

        # 파일 크기 확인
        total_size = int(response.headers.get('content-length', 0))
        total_mb = total_size / (1024 * 1024)
        if total_size > 0:
            print(f"[Tagger DL] 파일 크기: {total_mb:.2f} MB")
        else:
            print(f"[Tagger DL] 파일 크기: 알 수 없음")

        # 청크 단위로 다운로드
        block_size = 8192
        downloaded = 0
        last_percent_logged = -1  # 중복 로그 방지

        print(f"[Tagger DL] 다운로드 시작...")
        with open(save_path, 'wb') as out_file:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:  # 빈 청크 필터링
                    downloaded += len(chunk)
                    out_file.write(chunk)

                    # 진행 상황 콜백 (UI 업데이트용)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)

                    # 진행률 표시 (10% 단위) - 중복 방지
                    if total_size > 0:
                        percent = (downloaded * 100) // total_size
                        if percent % 10 == 0 and percent > 0 and percent != last_percent_logged:
                            downloaded_mb = downloaded / (1024 * 1024)
                            print(f"[Tagger DL] 다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)")
                            last_percent_logged = percent

        print(f"[Tagger DL] ✓ 다운로드 완료!")

        # 파일 검증
        if os.path.exists(save_path):
            file_size = os.path.getsize(save_path)
            file_size_mb = file_size / (1024 * 1024)
            print(f"[Tagger DL] 저장 완료: {file_size_mb:.2f} MB")
            return True
        else:
            print(f"[Tagger DL] ✗ 오류: 파일 생성 실패")
            return False

    except requests.exceptions.HTTPError as e:
        print(f"[Tagger DL] ✗ HTTP 오류: {e}")
        return False

    except requests.exceptions.ConnectionError as e:
        print(f"[Tagger DL] ✗ 연결 오류: {e}")
        return False

    except requests.exceptions.Timeout as e:
        print(f"[Tagger DL] ✗ 타임아웃: {e}")
        return False

    except Exception as e:
        import traceback
        print(f"[Tagger DL] ✗ 다운로드 실패: {str(e)}")
        traceback.print_exc()

        # 불완전 파일 삭제
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
                print(f"[Tagger DL] 불완전 파일 삭제: {save_path}")
            except:
                pass

        return False

def download_model_files():
    """모델 파일과 태그 파일을 다운로드하거나 캐시된 경로를 반환합니다."""
    # 캐시 확인
    if _TAGGER_CACHE["onnx_path"] and _TAGGER_CACHE["csv_path"]:
        return _TAGGER_CACHE["onnx_path"], _TAGGER_CACHE["csv_path"]
    
    # 저장 디렉토리 (data/tagger)
    base_dir = os.path.join(os.getcwd(), "data", "tagger")
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
        
    onnx_path = os.path.join(base_dir, "model.onnx")
    csv_path = os.path.join(base_dir, "selected_tags.csv")
    
    # 파일이 없으면 다운로드
    if not os.path.exists(onnx_path):
        if not download_file(MODEL_URL, onnx_path):
            raise Exception("Failed to download model.onnx")
            
    if not os.path.exists(csv_path):
        if not download_file(TAGS_URL, csv_path):
            raise Exception("Failed to download selected_tags.csv")
    
    _TAGGER_CACHE["onnx_path"] = onnx_path
    _TAGGER_CACHE["csv_path"] = csv_path
    return onnx_path, csv_path

def make_session(onnx_path: str):
    if _TAGGER_CACHE["session"]:
        return _TAGGER_CACHE["session"]

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    num_threads = os.cpu_count() or 4
    so.intra_op_num_threads = num_threads
    so.inter_op_num_threads = 1

    sess = ort.InferenceSession(
        onnx_path,
        sess_options=so,
        providers=["CPUExecutionProvider"],
    )
    _TAGGER_CACHE["session"] = sess
    return sess

def ensure_model_loaded():
    """모델 로드 확인 및 로딩"""
    if _TAGGER_CACHE["session"] and _TAGGER_CACHE["names"]:
        return

    onnx_path, csv_path = download_model_files()
    make_session(onnx_path)
    
    if not _TAGGER_CACHE["names"]:
        names, categories = load_tags(csv_path)
        _TAGGER_CACHE["names"] = names
        _TAGGER_CACHE["categories"] = categories

# --- Worker Thread ---

class TaggerDownloadWorker(QThread):
    """모델 파일 다운로드 워커"""
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            base_dir = os.path.join(os.getcwd(), "data", "tagger")
            if not os.path.exists(base_dir):
                os.makedirs(base_dir)
                print(f"[Worker] 디렉토리 생성: {base_dir}")

            onnx_path = os.path.join(base_dir, "model.onnx")
            csv_path = os.path.join(base_dir, "selected_tags.csv")

            # 1. Model Download
            if not os.path.exists(onnx_path):
                print(f"[Worker] 모델 파일 다운로드 시작")
                self.progress.emit(5, "모델 파일 다운로드 중... (model.onnx, ~260MB)")

                def model_progress(downloaded, total):
                    """모델 다운로드 진행 상황 업데이트"""
                    if total > 0:
                        # 0-50% 범위로 매핑
                        pct = int((downloaded / total) * 50)
                        self.progress.emit(
                            pct,
                            f"모델 다운로드 중... ({downloaded/(1024*1024):.1f}/{total/(1024*1024):.1f} MB)"
                        )

                if not download_file(MODEL_URL, onnx_path, progress_callback=model_progress):
                    raise Exception("모델 파일 다운로드 실패 (model.onnx)")

                self.progress.emit(50, "모델 다운로드 완료!")
                print(f"[Worker] 모델 파일 다운로드 완료")
            else:
                print(f"[Worker] 모델 파일 이미 존재: {onnx_path}")
                self.progress.emit(50, "모델 파일 확인 완료 (기존 파일)")

            # 2. Tags Download
            if not os.path.exists(csv_path):
                print(f"[Worker] 태그 데이터 다운로드 시작")
                self.progress.emit(55, "태그 데이터 다운로드 중... (selected_tags.csv)")

                def tags_progress(downloaded, total):
                    """태그 다운로드 진행 상황 업데이트"""
                    if total > 0:
                        # 50-90% 범위로 매핑
                        pct = 50 + int((downloaded / total) * 40)
                        self.progress.emit(
                            pct,
                            f"태그 다운로드 중... ({downloaded/1024:.1f}/{total/1024:.1f} KB)"
                        )

                if not download_file(TAGS_URL, csv_path, progress_callback=tags_progress):
                    raise Exception("태그 데이터 다운로드 실패 (selected_tags.csv)")

                self.progress.emit(90, "태그 다운로드 완료!")
                print(f"[Worker] 태그 데이터 다운로드 완료")
            else:
                print(f"[Worker] 태그 파일 이미 존재: {csv_path}")
                self.progress.emit(90, "태그 파일 확인 완료 (기존 파일)")

            # 캐시 업데이트
            _TAGGER_CACHE["onnx_path"] = onnx_path
            _TAGGER_CACHE["csv_path"] = csv_path

            self.progress.emit(100, "준비 완료!")
            print(f"[Worker] 모든 파일 준비 완료")
            self.finished.emit(True, "설치 및 다운로드 완료")

        except Exception as e:
            import traceback
            print(f"[Worker] 오류 발생: {e}")
            traceback.print_exc()
            self.finished.emit(False, str(e))

class TaggerWorker(QThread):
    """태그 추론을 수행하는 워커 스레드"""
    finished = pyqtSignal(dict) # result dict
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, pil_image, general_th=0.35, character_th=0.85):
        super().__init__()
        self.pil_image = pil_image
        self.general_th = general_th
        self.character_th = character_th

    def run(self):
        try:
            if not HAS_TAGGER_LIBS:
                self.error.emit("onnxruntime 라이브러리가 필요합니다.")
                return

            self.progress.emit("모델 로딩 중...")
            ensure_model_loaded()

            sess = _TAGGER_CACHE["session"]
            names = _TAGGER_CACHE["names"]
            categories = _TAGGER_CACHE["categories"]

            self.progress.emit("이미지 전처리 중...")
            x = preprocess_image(self.pil_image)

            self.progress.emit("태그 추론 중...")
            input_name = sess.get_inputs()[0].name
            logits = sess.run(None, {input_name: x})[0]
            probs = sigmoid(logits[0])

            result = {
                "rating": [],
                "character": [],
                "general": [],
            }

            for i, p in enumerate(probs):
                score = float(p)
                tag = names[i]
                
                # 카테고리 없는 경우 처리
                if categories is None:
                    if score >= self.general_th:
                        result["general"].append((tag, score))
                    continue

                cat = int(categories[i])
                
                if cat == 9:  # rating
                    result["rating"].append((tag, score))
                elif cat == 4:  # character
                    if score >= self.character_th:
                        result["character"].append((tag, score))
                else:  # general (0)
                    if score >= self.general_th:
                        result["general"].append((tag, score))

            # 정렬
            for k in result:
                result[k].sort(key=lambda x: x[1], reverse=True)

            if result["rating"]:
                result["rating"] = result["rating"][:1]

            self.finished.emit(result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(f"추론 실패: {str(e)}")

# --- UI Classes ---

class ThresholdButton(QPushButton):
    """Threshold 선택 버튼 (Character Prompt Block 스타일)"""
    def __init__(self, text, value, parent=None):
        super().__init__(text, parent)
        self.value = value
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(get_scaled_size(32))

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(16)}px;
                padding: 0px {get_scaled_size(12)}px;
            }}
            QPushButton:hover {{
                border-color: {COMMON_STYLES['text_secondary']};
            }}
            QPushButton:checked {{
                background-color: {COMMON_STYLES['input_focus']};
                color: white;
                border-color: {COMMON_STYLES['input_focus']};
                font-weight: bold;
            }}
        """)

class DownloadProgressDialog(QDialog):
    """다운로드 진행 상황 및 수동 다운로드 안내 다이얼로그"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("구성 요소 다운로드")
        self.setModal(True)
        self.setMinimumWidth(get_scaled_size(600))
        self.setMinimumHeight(get_scaled_size(400))

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 상태 메시지 라벨
        self.status_label = QLabel("모델 다운로드 중...")
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        layout.addWidget(self.status_label)

        # 진행 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                text-align: center;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        layout.addWidget(self.progress_bar)

        # 수동 다운로드 안내
        help_label = QLabel("[다운로드가 안되나요?] 다음 순서를 따르세요:")
        help_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
                margin-top: 10px;
            }}
        """)
        layout.addWidget(help_label)

        # 수동 다운로드 안내 TextBrowser (하이퍼링크 지원)
        self.help_text = QTextBrowser()
        self.help_text.setReadOnly(True)
        self.help_text.setMaximumHeight(get_scaled_size(150))

        # 설치 경로
        self.install_path = os.path.join(os.getcwd(), "data", "tagger")

        # HTML 형식으로 내용 작성 (하이퍼링크 포함)
        html_content = f"""
        <html>
        <body style="background-color: white; color: black; font-family: {FONT_FAMILY}; font-size: {get_scaled_font_size(12)}px;">
        <ol>
            <li>
                <a href="https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/tree/main" style="color: #0066cc;">
                    https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/tree/main
                </a>
                사이트를 방문하여 <b>model.onnx (467 MB)</b>, <b>selected_tags.csv (308 kB)</b> 파일을 다운로드 받습니다.
            </li>
            <br>
            <li>
                다운로드 받은 파일들을 설치된 경로의
                <a href="local_folder" style="color: #0066cc;">
                    \\data\\tagger
                </a>
                폴더로 옮깁니다.
            </li>
            <br>
            <li>
                <b>취소</b> 버튼을 누른 뒤, 해당 파일들을 옮기고 다시 <b>지금 설치 및 다운로드</b> 버튼을 눌러주세요.
            </li>
        </ol>
        </body>
        </html>
        """
        self.help_text.setHtml(html_content)

        # 링크 클릭 처리 (웹은 브라우저, 폴더는 탐색기)
        self.help_text.setOpenExternalLinks(False)
        self.help_text.anchorClicked.connect(self._on_link_clicked)

        # 하얀색 배경 적용
        self.help_text.setStyleSheet("""
            QTextBrowser {
                background-color: white;
                color: black;
                border: 1px solid #cccccc;
                border-radius: 4px;
            }
        """)

        layout.addWidget(self.help_text)

        # 취소 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_button = QPushButton("취소")
        self.cancel_button.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.cancel_button.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_button)

        layout.addLayout(btn_layout)

        # 다이얼로그 배경색
        self.setStyleSheet(f"QDialog {{ background-color: {DARK_COLORS['bg_primary']}; }}")

    def set_progress(self, value: int, message: str):
        """진행률 업데이트"""
        self.progress_bar.setValue(value)
        self.status_label.setText(message)

    def _on_link_clicked(self, url: QUrl):
        """링크 클릭 처리: 웹은 브라우저, 로컬 폴더는 탐색기"""
        url_string = url.toString()

        if url_string == "local_folder":
            # 로컬 폴더를 Windows 탐색기로 열기
            try:
                # 폴더가 없으면 생성
                if not os.path.exists(self.install_path):
                    os.makedirs(self.install_path)

                # Windows 탐색기로 폴더 열기
                os.startfile(self.install_path)
            except Exception as e:
                print(f"[Dialog] 폴더 열기 실패: {e}")
        elif url_string.startswith("http://") or url_string.startswith("https://"):
            # 웹 URL을 기본 브라우저로 열기
            QDesktopServices.openUrl(url)

class ClickableFrame(QFrame):
    clicked = pyqtSignal()
    paste_requested = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.matches(QAction.StandardKey.Paste) or (event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V):
            self.paste_requested.emit()
        super().keyPressEvent(event)


class ImageTaggerBlock(BlockWidget):
    """
    이미지 태그 추출 블록
    """
    
    tags_extracted = pyqtSignal(str) # 추출된 태그 문자열 시그널

    def __init__(self, parent=None):
        super().__init__(title="이미지 태거 (WD14 v3)", parent=parent)

        self.current_pil_image = None
        self.worker = None

        # Quick Search / Main Prompt 블록 참조 (나중에 설정)
        self.quick_search_block = None
        self.main_prompt_block = None

        self._init_content()

    def set_quick_search_block(self, quick_search_block):
        """Quick Search 블록 참조 설정"""
        self.quick_search_block = quick_search_block
        print("[ImageTaggerBlock] QuickSearchBlock 참조 설정됨")

    def set_main_prompt_block(self, main_prompt_block):
        """Main Prompt 블록 참조 설정"""
        self.main_prompt_block = main_prompt_block
        print("[ImageTaggerBlock] MainPromptBlock 참조 설정됨")

    def _filter_tags_with_quicksearch(self, tag_string: str) -> str:
        """
        Quick Search 화이트리스트로 태그 필터링

        Args:
            tag_string: 쉼표로 구분된 태그 문자열

        Returns:
            str: 필터링된 태그 문자열 (Quick Search에 존재하는 태그만)
        """
        if not self.quick_search_block or not hasattr(self.quick_search_block, 'tag_to_id'):
            print("[ImageTaggerBlock] Quick Search 블록이 없거나 tag_to_id가 없음 - 필터링 없이 전체 반환")
            return tag_string

        # 쉼표로 분리
        tags = [t.strip() for t in tag_string.split(',') if t.strip()]

        # Quick Search의 tag_to_id에 있는 태그만 필터링
        valid_tags = []
        for tag in tags:
            if tag in self.quick_search_block.tag_to_id:
                valid_tags.append(tag)

        print(f"[ImageTaggerBlock] 필터링: {len(tags)}개 -> {len(valid_tags)}개")

        return ', '.join(valid_tags)

    def _init_content(self):
        self.main_layout_container = QVBoxLayout()
        self.main_layout_container.setContentsMargins(0, 0, 0, 0)
        self.main_layout_container.setSpacing(0)
        self.content_layout.addLayout(self.main_layout_container)

        # "이미지 꺼내기" 버튼 참조 (나중에 생성)
        self.btn_extract_image = None

        if self._check_environment_ready():
            self._setup_main_view()
        else:
            self._setup_install_view()

    def _check_environment_ready(self) -> bool:
        """환경(패키지 + 모델 파일) 준비 여부 확인"""
        # 1. 패키지 확인
        if not self._check_packages_installed():
            return False
            
        # 2. 모델 파일 확인
        base_dir = os.path.join(os.getcwd(), "data", "tagger")
        onnx_path = os.path.join(base_dir, "model.onnx")
        csv_path = os.path.join(base_dir, "selected_tags.csv")
        
        if os.path.exists(onnx_path) and os.path.exists(csv_path):
            return True
            
        return False

    def _setup_install_view(self):
        """설치 유도 UI"""
        # 기존 내용 삭제
        self._clear_layout(self.main_layout_container)
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 아이콘
        icon_label = QLabel("📦")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 32px;")
        layout.addWidget(icon_label)
        
        # 안내 문구
        info_label = QLabel("이미지 태거(WD14)를 사용하려면\n추가 구성 요소 설치가 필요합니다.")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px;")
        layout.addWidget(info_label)
        
        # 상세 내용 (패키지 + 모델)
        detail_label = QLabel("- python package: onnxruntime\n- model: wd-swinv2-tagger-v3")
        detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        layout.addWidget(detail_label)
        
        layout.addStretch()
        
        # 설치 버튼
        btn_install = QPushButton("지금 설치 및 다운로드")
        btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_install.setFixedHeight(get_scaled_size(40))
        btn_install.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        btn_install.clicked.connect(self._start_full_installation)
        layout.addWidget(btn_install)
        
        self.main_layout_container.addWidget(container)

    def _setup_main_view(self):
        """메인 기능 UI"""
        # 기존 내용 삭제
        self._clear_layout(self.main_layout_container)
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(10))
        
        # 설명 라벨
        desc = QLabel("이미지를 업로드하고 태그를 추출합니다. (General Tags only)")
        desc.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(13)}px; margin-bottom: 4px;")
        layout.addWidget(desc)

        # === 설정 영역 (Threshold) - 토글 버튼 방식 ===
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(get_scaled_size(8))

        lbl_th = QLabel("Threshold:")
        lbl_th.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px;")
        settings_layout.addWidget(lbl_th)

        # 버튼 그룹 (배타적 선택)
        self.threshold_group = QButtonGroup(self)
        self.threshold_group.setExclusive(True)

        # Threshold 버튼들: 0.51, 0.61, 0.71
        self.btn_th_051 = ThresholdButton("0.51", 0.51)
        self.btn_th_061 = ThresholdButton("0.61", 0.61)
        self.btn_th_071 = ThresholdButton("0.71", 0.71)

        self.threshold_group.addButton(self.btn_th_051)
        self.threshold_group.addButton(self.btn_th_061)
        self.threshold_group.addButton(self.btn_th_071)

        # 기본 선택: 0.51
        self.btn_th_051.setChecked(True)

        # Threshold 변경 시 태그 추출 버튼 재활성화
        self.threshold_group.buttonClicked.connect(self._on_threshold_changed)

        settings_layout.addWidget(self.btn_th_051)
        settings_layout.addWidget(self.btn_th_061)
        settings_layout.addWidget(self.btn_th_071)
        settings_layout.addStretch()

        layout.addLayout(settings_layout)

        # === 이미지 업로드 영역 ===
        self.upload_frame = QFrame()
        self.upload_frame.setMinimumHeight(get_scaled_size(180))
        self.upload_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 2px dashed {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)

        self.upload_layout = QVBoxLayout(self.upload_frame)
        self.upload_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.upload_layout.setSpacing(get_scaled_size(8))

        # Empty State (버튼 2개)
        self.empty_widget = QWidget()
        empty_l = QVBoxLayout(self.empty_widget)
        empty_l.setSpacing(get_scaled_size(8))

        icon = QLabel("🖼️")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 24px;")
        empty_l.addWidget(icon)

        # 파일에서 선택 버튼
        btn_file = QPushButton("📁 파일에서 선택")
        btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_file.setFixedHeight(get_scaled_size(36))
        btn_file.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        btn_file.clicked.connect(self._open_file_dialog)
        empty_l.addWidget(btn_file)

        # 클립보드에서 가져오기 버튼
        btn_clipboard = QPushButton("📋 클립보드에서 가져오기")
        btn_clipboard.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clipboard.setFixedHeight(get_scaled_size(36))
        btn_clipboard.setStyleSheet(get_button_style())
        btn_clipboard.clicked.connect(self._paste_from_clipboard)
        empty_l.addWidget(btn_clipboard)

        # Preview State
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.hide()

        self.upload_layout.addWidget(self.empty_widget)
        self.upload_layout.addWidget(self.preview_label)

        layout.addWidget(self.upload_frame)

        # === 이미지 꺼내기 버튼 (이미지 로드 시에만 표시) ===
        self.btn_extract_image = QPushButton("📤 이미지 꺼내기")
        self.btn_extract_image.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_extract_image.setFixedHeight(get_scaled_size(36))
        self.btn_extract_image.setStyleSheet(get_button_style(bg_color=COMMON_STYLES['input_border'], text_color=DARK_COLORS['text_primary']))
        self.btn_extract_image.clicked.connect(self._extract_current_image)
        self.btn_extract_image.hide()  # 초기에는 숨김

        layout.addWidget(self.btn_extract_image)

        # === 실행 버튼 ===
        self.btn_run = QPushButton("⚡ 태그 추출 실행")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.setFixedHeight(get_scaled_size(36))
        self.btn_run.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_run.clicked.connect(self._run_tagging)
        self.btn_run.setEnabled(False) # 이미지 로드 전까지 비활성

        layout.addWidget(self.btn_run)

        # === 진행바 ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(get_scaled_size(4))
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {DARK_COLORS['accent_blue']}; }}")
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.main_layout_container.addWidget(container)

    def _clear_layout(self, layout):
        """레이아웃 내용 삭제"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _start_full_installation(self):
        """전체 설치 프로세스 시작 (패키지 -> 모델 다운로드)"""
        # 1. 패키지 설치
        if not self._check_packages_installed():
            self._install_packages(next_step=self._start_model_download)
        else:
            self._start_model_download()

    def _start_model_download(self):
        """모델 다운로드 시작"""
        # 패키지 설치 후 다시 체크 및 로드 시도
        global ort
        if 'onnxruntime' not in sys.modules:
            try:
                import onnxruntime as ort
                global HAS_TAGGER_LIBS
                HAS_TAGGER_LIBS = True
            except ImportError:
                QMessageBox.critical(self, "오류", "패키지 설치 후 로드에 실패했습니다. 프로그램을 재시작해주세요.")
                return

        self.download_worker = TaggerDownloadWorker()

        # 커스텀 다운로드 다이얼로그
        self.progress_dialog = DownloadProgressDialog(self)

        # 워커 시그널 연결
        self.download_worker.progress.connect(self.progress_dialog.set_progress)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.start()

        # 다이얼로그 표시
        self.progress_dialog.exec()

    def _on_download_finished(self, success, message):
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()

        if success:
            QMessageBox.information(self, "완료", "모든 준비가 완료되었습니다.")
            self._setup_main_view()
        else:
            QMessageBox.critical(self, "실패", f"다운로드 중 오류가 발생했습니다:\n{message}")

    # --- 이미지 로드 관련 로직 ---

    def _open_file_dialog(self):
        # 여러 파일 선택 가능
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "이미지 선택 (여러 개 가능)", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if file_paths:
            if len(file_paths) == 1:
                # 단일 이미지: 기존 방식
                self._load_image(file_paths[0])
            else:
                # 여러 이미지: 배치 처리 윈도우 열기
                self._open_batch_processing_window(file_paths)

    def _paste_from_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                self._load_qimage(image)
        elif mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                        self._load_image(path)
                        break

    def _load_image(self, file_path):
        try:
            pil_img = Image.open(file_path).convert("RGB")
            self.current_pil_image = pil_img
            self._update_preview(QPixmap(file_path))

            # 버튼 상태 초기화
            self.btn_run.setEnabled(True)
            self.btn_run.setText("⚡ 태그 추출 실행")

            # 이미지 로드 시 "이미지 꺼내기" 버튼 표시
            if self.btn_extract_image:
                self.btn_extract_image.show()
        except Exception as e:
            print(f"이미지 로드 실패: {e}")

    def _load_qimage(self, qimage):
        try:
            buffer = QBuffer()
            buffer.open(QBuffer.OpenModeFlag.ReadWrite)
            qimage.save(buffer, "PNG")
            pil_img = Image.open(io.BytesIO(buffer.data())).convert("RGB")
            self.current_pil_image = pil_img
            self._update_preview(QPixmap.fromImage(qimage))

            # 버튼 상태 초기화
            self.btn_run.setEnabled(True)
            self.btn_run.setText("⚡ 태그 추출 실행")

            # 이미지 로드 시 "이미지 꺼내기" 버튼 표시
            if self.btn_extract_image:
                self.btn_extract_image.show()
        except Exception as e:
            print(f"이미지 변환 실패: {e}")

    def _update_preview(self, pixmap):
        if pixmap.isNull(): return
        self.empty_widget.hide()
        self.preview_label.show()
        
        # 비율 유지 리사이즈
        w, h = pixmap.width(), pixmap.height()
        target_h = get_scaled_size(180)
        
        if h > target_h:
            pixmap = pixmap.scaledToHeight(target_h, Qt.TransformationMode.SmoothTransformation)
            
        self.preview_label.setPixmap(pixmap)

    # --- 태그 추출 로직 ---

    def _run_tagging(self):
        # 1. 패키지 설치 확인
        if not self._check_packages_installed():
            self._show_install_dialog()
            return

        if not self.current_pil_image:
            return

        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ 추출 중...")
        self.progress_bar.setRange(0, 0) # Indeterminate
        self.progress_bar.show()

        # 선택된 threshold 버튼에서 값 가져오기
        checked_button = self.threshold_group.checkedButton()
        th = checked_button.value if checked_button else 0.61  # 기본값 0.61

        self.worker = TaggerWorker(self.current_pil_image, general_th=th)
        self.worker.progress.connect(lambda msg: self.btn_run.setText(f"⏳ {msg}"))
        self.worker.finished.connect(self._on_tagging_finished)
        self.worker.error.connect(self._on_tagging_error)
        self.worker.start()

    def _on_tagging_finished(self, result):
        self.progress_bar.hide()

        # General 태그만 사용
        general_tags = result.get("general", [])

        if not general_tags:
            # 태그가 없는 경우 버튼 재활성화
            self.btn_run.setEnabled(True)
            self.btn_run.setText("⚡ 태그 추출 실행")
            print("[ImageTaggerBlock] 매칭되는 태그가 없습니다. Threshold를 낮춰보세요.")
            return

        # 태그 문자열 생성 (언더바 제거, 스코어 없이 태그만)
        cleaned_tags = [t[0].replace("_", " ") for t in general_tags]
        tag_str = ", ".join(cleaned_tags)

        # Quick Search 필터링
        filtered_tags = self._filter_tags_with_quicksearch(tag_str)

        # 시그널 발생 (필터링된 태그 전송)
        if filtered_tags.strip():
            self.tags_extracted.emit(filtered_tags)
            print(f"[ImageTaggerBlock] 태그 추출 완료: {len(general_tags)}개 -> {len(filtered_tags.split(','))}개 (필터링)")
        else:
            print("[ImageTaggerBlock] 필터링 후 유효한 태그가 없습니다.")

        # 버튼을 "완료됨"으로 변경하고 비활성화
        self.btn_run.setText("✓ 완료됨")
        self.btn_run.setEnabled(False)

    def _on_tagging_error(self, err_msg):
        self.progress_bar.hide()
        self.btn_run.setEnabled(True)
        self.btn_run.setText("⚡ 태그 추출 실행")
        print(f"[ImageTaggerBlock] 오류 발생: {err_msg}")

    def _on_threshold_changed(self):
        """Threshold 변경 시 태그 추출 버튼 재활성화"""
        if self.current_pil_image:
            self.btn_run.setEnabled(True)
            self.btn_run.setText("⚡ 태그 추출 실행")

    def _extract_current_image(self):
        """현재 로드된 이미지를 제거하고 초기 상태로 되돌리기"""
        if not self.current_pil_image:
            print("[ImageTaggerBlock] 제거할 이미지가 없습니다.")
            return

        # 이미지 제거
        self.current_pil_image = None

        # UI 초기 상태로 복원
        self.preview_label.hide()
        self.empty_widget.show()

        # 버튼 상태 초기화
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⚡ 태그 추출 실행")
        self.btn_extract_image.hide()

        print("[ImageTaggerBlock] 이미지 제거 완료")

    def _open_batch_processing_window(self, file_paths):
        """배치 이미지 처리 윈도우 열기"""
        from ui.interactive.batch_image_processing_window import BatchImageProcessingWindow

        # Quick Search, Main Prompt, AppContext 참조 전달
        self.batch_window = BatchImageProcessingWindow(
            file_paths=file_paths,
            quick_search_block=self.quick_search_block,
            main_prompt_block=self.main_prompt_block,
            app_context=getattr(self, 'app_context', None),
            parent=self
        )
        self.batch_window.show()

    # --- 패키지 및 모델 설치 로직 ---

    def _check_packages_installed(self) -> bool:
        """필요한 패키지 설치 여부 확인"""
        try:
            # 전역 변수 업데이트 시도
            global HAS_TAGGER_LIBS
            if HAS_TAGGER_LIBS:
                return True
                
            spec_ort = importlib.util.find_spec('onnxruntime')
            
            if spec_ort:
                HAS_TAGGER_LIBS = True
                return True
            return False
        except Exception:
            return False

    def _start_full_installation(self):
        """전체 설치 프로세스 시작 (패키지 -> 모델 다운로드)"""
        # 1. 패키지 설치
        if not self._check_packages_installed():
            self._install_packages(next_step=self._start_model_download)
        else:
            self._start_model_download()

    def _install_packages(self, next_step=None):
        """패키지 설치 실행"""
        # 가상환경 확인
        venv_active = hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
        if not venv_active:
            QMessageBox.warning(
                self, "설치 불가",
                "가상환경에서만 패키지를 설치할 수 있습니다.\n터미널에서 직접 설치해주세요:\npip install onnxruntime"
            )
            return

        # 진행 다이얼로그
        progress = QProgressDialog("패키지 설치 중... (onnxruntime)", "취소", 0, 0, self)
        progress.setWindowTitle("패키지 설치")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        # 스타일 적용
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
            pip_cmd = [sys.executable, '-m', 'pip', 'install', 'onnxruntime']
            print(f"🔧 실행: {' '.join(pip_cmd)}")

            # UI 비활성화
            self.setEnabled(False)

            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            progress.close()
            self.setEnabled(True) # UI 활성화

            if result.returncode == 0:
                print("✅ 패키지 설치 완료")
                
                # 전역 변수 업데이트 및 임포트 시도
                global ort, HAS_TAGGER_LIBS
                import onnxruntime as ort
                HAS_TAGGER_LIBS = True
                
                # 다음 단계 실행
                if next_step:
                    next_step()
                else:
                    QMessageBox.information(
                        self, "설치 완료",
                        "패키지가 성공적으로 설치되었습니다."
                    )
                    self._setup_main_view() # 메인 뷰 전환 시도
                
            else:
                error_msg = result.stderr[:500] if result.stderr else "알 수 없는 오류"
                QMessageBox.critical(
                    self, "설치 실패",
                    f"패키지 설치에 실패했습니다.\n\n{error_msg}"
                )
                print(f"❌ 패키지 설치 실패: {result.stderr}")

        except subprocess.TimeoutExpired:
            progress.close()
            self.setEnabled(True)
            QMessageBox.critical(self, "설치 실패", "설치 시간이 초과되었습니다.")
        except Exception as e:
            progress.close()
            self.setEnabled(True)
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "설치 실패", f"설치 중 오류 발생:\n{str(e)}")
