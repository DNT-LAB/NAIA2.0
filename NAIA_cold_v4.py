import __init__
import core.dll_fix  # Windows DLL 로드 문제 해결
import sys
import os
import subprocess

# 과학 연산 라이브러리 스레드 제한 (메모리 누수 방지용)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import json
import pandas as pd
import random
import requests
from io import BytesIO
from PIL import Image, ImageGrab
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox, QComboBox, QFrame,
    QScrollArea, QSplitter, QStatusBar, QTabWidget, QMessageBox, QSpinBox, QSlider, QDoubleSpinBox,
    QFileDialog, QWidgetAction, QButtonGroup, QMenu, QProgressDialog, QSizePolicy, QRadioButton
)
from core.middle_section_controller import MiddleSectionController
from core.context import AppContext
from core.generation_controller import GenerationController
from ui.theme import DARK_COLORS, DARK_STYLES, CUSTOM, get_dynamic_styles
from ui.scaling_manager import get_scaling_manager, get_scaled_font_size, get_scaled_size
from ui.scaling_settings_dialog import ScalingSettingsDialog
from ui.collapsible import CollapsibleBox
from ui.right_view import RightView
from ui.temp_generation_window import TempGenerationWindow
from ui.resolution_manager_dialog import ResolutionManagerDialog
from ui.remote_window import RemoteWindow
from ui.interactive_window import InteractiveWindow
from PyQt6.QtGui import QFont, QFontDatabase, QIntValidator, QDoubleValidator, QTextCursor, QCursor, QAction, QDesktopServices, QSyntaxHighlighter, QTextCharFormat, QColor
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal, QTimer, QEvent, QMimeData, QUrl
from core.search_controller import SearchController
from core.search_result_model import SearchResultModel
from core.autocomplete_manager import AutoCompleteManager
from core.tag_data_manager import TagDataManager
from core.wildcard_manager import WildcardManager
from core.prompt_generation_controller import PromptGenerationController
from utils.load_generation_params import GenerationParamsManager
from ui.img2img_popup import Img2ImgPopup
from ui.img2img_panel import Img2ImgPanel
from ui.img2img_window import Img2ImgWindow
from core.main_controller import MainController
from utils.token_calculator import get_token_calculator
from core.comfyui_utils import ComfyUIAPIUtils

cfg_validator = QDoubleValidator(1.0, 10.0, 1)
step_validator = QIntValidator(1, 50)
cfg_rescale_validator = QDoubleValidator(-1.0, 1.0, 2)
_autocomplete_manager = None

# 웹엔진 관련 설정 (QApplication 생성 전에 필요)
def setup_webengine():  
    """WebEngine 설정"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    
    # QApplication 생성 전 필수 설정
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    #os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "8888"
    
    # WebEngine 모듈 사전 로드
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebEngineCore import QWebEngineProfile
        print("✅ WebEngine 모듈 사전 로드 완료")
    except ImportError:
        print("❌ PyQt6-WebEngine이 설치되지 않았습니다")


class ParquetLoader(QObject):
    finished = pyqtSignal(SearchResultModel)
    def run(self, file_path):
        df = pd.read_parquet(file_path)
        self.finished.emit(SearchResultModel(df))

def load_custom_fonts():
    """Pretendard 폰트 로드"""
    # 실행 경로에서 폰트 파일 찾기
    current_dir = os.path.dirname(os.path.abspath(__file__))
    regular_font_path = os.path.join(current_dir, "Pretendard-Regular.otf")
    bold_font_path = os.path.join(current_dir, "Pretendard-Bold.otf")
    
    fonts_loaded = []
    
    if os.path.exists(regular_font_path):
        font_id = QFontDatabase.addApplicationFont(regular_font_path)
        if font_id != -1:
            fonts_loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
            print(f"Pretendard-Regular 폰트 로드 성공: {regular_font_path}")
    else:
        print(f"Pretendard-Regular.otf 파일을 찾을 수 없습니다: {regular_font_path}")
    
    if os.path.exists(bold_font_path):
        font_id = QFontDatabase.addApplicationFont(bold_font_path)
        if font_id != -1:
            fonts_loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
            print(f"Pretendard-Bold 폰트 로드 성공: {bold_font_path}")
    else:
        print(f"Pretendard-Bold.otf 파일을 찾을 수 없습니다: {bold_font_path}")
    
    return fonts_loaded


def get_autocomplete_manager(app_context=None):
    global _autocomplete_manager
    if _autocomplete_manager is None:
        _autocomplete_manager = AutoCompleteManager(app_context)  # 1회만 생성
    return _autocomplete_manager

class ImageDownloadThread(QThread):
    image_downloaded = pyqtSignal(Image.Image)
    download_failed = pyqtSignal(str)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        
    def run(self):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(self.url, headers=headers, timeout=10, stream=True)
            response.raise_for_status()
            
            # 이미지 데이터를 메모리로 읽기
            image_data = BytesIO(response.content)
            pil_image = Image.open(image_data)

            # 이미지 모드를 유지 (RGBA의 경우 stealth PNG 메타데이터 보존)
            # RGB/RGBA/기타 모드 모두 그대로 전달
            print(f"✅ ImageDownloadThread: 이미지 다운로드 완료, 모드 = {pil_image.mode}")

            self.image_downloaded.emit(pil_image)
            
        except requests.exceptions.RequestException as e:
            self.download_failed.emit(f"네트워크 오류: {str(e)}")
        except Exception as e:
            self.download_failed.emit(f"이미지 처리 오류: {str(e)}")


class GitHubUpdateChecker(QThread):
    """GitHub 저장소의 최신 커밋을 확인하는 스레드"""
    update_available = pyqtSignal(str, str, str)  # latest_commit_sha, commit_message, commit_date

    def __init__(self, owner, repo, branch, current_sha):
        super().__init__()
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.current_sha = current_sha
        # 특정 브랜치의 최신 커밋을 가져오는 API URL
        self.request_url = f"https://api.github.com/repos/{self.owner}/{self.repo}/commits?sha={self.branch}&per_page=1"
        self.is_running = True

    def run(self):
        if not self.current_sha:
            print("⚠️ 로컬 버전 정보(SHA)가 없어 업데이트를 확인할 수 없습니다.")
            return

        try:
            headers = {'User-Agent': 'NAIA-Update-Checker'}
            response = requests.get(self.request_url, headers=headers, timeout=15)
            response.raise_for_status()  # 200 OK가 아니면 예외 발생

            latest_commit_data = response.json()[0]
            latest_sha = latest_commit_data['sha'][:7]  # 짧은 형태로 저장
            commit_message = latest_commit_data['commit']['message'].split('\n')[0]  # 첫 줄만 사용
            
            # 커밋 날짜 파싱 (ISO 8601 형식을 YYYYMMDD로 변환)
            commit_date_str = latest_commit_data['commit']['author']['date']
            from datetime import datetime
            commit_date = datetime.fromisoformat(commit_date_str.replace('Z', '+00:00'))
            commit_date_formatted = commit_date.strftime('%Y%m%d')

            print(f"🔍 업데이트 확인 ({self.branch} 브랜치): 현재={self.current_sha[:7]}, 최신={latest_sha}")

            # 항상 최신 버전 정보를 emit (같든 다르든)
            self.update_available.emit(latest_sha, commit_message, commit_date_formatted)
            
            if self.current_sha[:7] != latest_sha:
                print(f"✨ 새로운 업데이트 발견! {latest_sha}: {commit_message}")
        except requests.exceptions.Timeout:
            print("⏱️ GitHub API 요청 시간 초과 (네트워크가 느리거나 오프라인 상태)")
        except requests.exceptions.ConnectionError:
            print("🔌 네트워크 연결 오류 (오프라인 상태이거나 GitHub에 접속할 수 없음)")
        except requests.exceptions.RequestException as e:
            print(f"❌ GitHub API 요청 실패: {str(e)[:100]}")  # 긴 오류 메시지 제한
        except Exception as e:
            print(f"❌ 업데이트 확인 중 예기치 않은 오류: {str(e)[:100]}")

    def stop(self):
        self.is_running = False


class PromptHighlighter(QSyntaxHighlighter):
    """프롬프트 텍스트 하이라이터

    규칙 1: '#'로 시작해서 쉼표까지 → 연노랑색 텍스트
    규칙 2: '-'로 시작하고 [:6] 안에 '::'가 없으면 쉼표까지 → 연회색 텍스트
    규칙 3: ':begin' 토큰 → 하늘색
    규칙 4: ':seq' 토큰 → 조금 진한 연노랑색
    규칙 5: ':end' 토큰 → 연보라색
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 연노랑색 포맷 (# 주석용)
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#FFFFE0"))  # 연노랑색 텍스트

        # 연회색 포맷 (- 음수 가중치용)
        self.negative_weight_format = QTextCharFormat()
        self.negative_weight_format.setForeground(QColor("#999999"))  # 연회색 텍스트

        # 🆕 시퀀스 토큰 포맷
        self.begin_format = QTextCharFormat()
        self.begin_format.setForeground(QColor("#87CEEB"))  # 하늘색

        self.seq_format = QTextCharFormat()
        self.seq_format.setForeground(QColor("#FFD700"))  # 조금 진한 연노랑색 (골드)

        self.end_format = QTextCharFormat()
        self.end_format.setForeground(QColor("#DDA0DD"))  # 연보라색 (플럼)

    def highlightBlock(self, text: str):
        """각 텍스트 블록(줄)에 대해 하이라이팅 적용"""
        # 🆕 먼저 시퀀스 토큰 하이라이팅 적용 (우선순위 높음)
        self._highlight_sequence_tokens(text)

        # 기존 로직: 세그먼트 기반 하이라이팅
        pos = 0

        while pos < len(text):
            # 현재 위치에서 다음 쉼표 찾기
            comma_index = text.find(',', pos)

            if comma_index == -1:
                # 더 이상 쉼표가 없으면 나머지 전체 확인
                segment = text[pos:].strip()
                self._apply_format_to_segment(text, pos, len(text), segment)
                break
            else:
                # 쉼표를 찾았으면 해당 구간 확인
                segment = text[pos:comma_index].strip()
                self._apply_format_to_segment(text, pos, comma_index + 1, segment)

                # 다음 구간으로 이동 (쉼표 다음부터)
                pos = comma_index + 1

    def _highlight_sequence_tokens(self, text: str):
        """🆕 시퀀스 토큰(:begin, :seq, :end) 하이라이팅"""
        import re

        # :begin 토큰 찾기 (대소문자 무시)
        for match in re.finditer(r':begin\b', text, re.IGNORECASE):
            self.setFormat(match.start(), match.end() - match.start(), self.begin_format)

        # :seq 토큰 찾기 (숫자/문자 포함, 대소문자 무시)
        # 예: :seq1, :seqX, :seqabc 등
        for match in re.finditer(r':seq[a-z0-9]*\b', text, re.IGNORECASE):
            self.setFormat(match.start(), match.end() - match.start(), self.seq_format)

        # :end 토큰 찾기 (대소문자 무시)
        for match in re.finditer(r':end\b', text, re.IGNORECASE):
            self.setFormat(match.start(), match.end() - match.start(), self.end_format)

    def _apply_format_to_segment(self, text: str, start_pos: int, end_pos: int, segment: str):
        """세그먼트에 포맷 적용"""
        if not segment:
            return

        # 규칙 1: '#'으로 시작하면 연노랑색
        if segment.startswith('#'):
            self.setFormat(start_pos, end_pos - start_pos, self.comment_format)
        # 규칙 2: '-'로 시작하고 [:6] 안에 '::'가 없으면 연회색
        elif segment.startswith('-'):
            # 원본 텍스트에서 실제 세그먼트 위치 찾기
            actual_segment_start = text.find(segment, start_pos)
            if actual_segment_start != -1:
                # '-' 이후 최대 6자 확인
                check_range = segment[:7] if len(segment) >= 7 else segment
                if '::' not in check_range:
                    # '::'가 없으면 쉼표까지 연회색 처리
                    self.setFormat(start_pos, end_pos - start_pos, self.negative_weight_format)

class PromptTextEdit(QTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.download_thread = None
        self.progress_dialog = None
        # AppContext를 나중에 주입받을 변수
        self.app_context = None

    def insertFromMimeData(self, source: QMimeData):
        # 1. 클립보드 이미지 처리
        if source.hasImage():
            pil_img = ImageGrab.grabclipboard()
            if isinstance(pil_img, Image.Image):
                self.show_img2img_popup(pil_img)
                return  # 기본 텍스트 삽입 방지

        # 2. 파일 드롭 처리
        if source.hasUrls():
            for url in source.urls():
                # 로컬 파일 경로 처리
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if path and os.path.exists(path):
                        ext = os.path.splitext(path)[1].lower()
                        if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'):
                            pil_img = Image.open(path)
                            self.show_img2img_popup(pil_img)
                            return
                # 웹 URL 처리
                else:
                    url_string = url.toString()
                    if self.is_web_image_url(url_string):
                        self.download_web_image(url_string)
                        return
        
        # 3. 이미지 데이터가 아니면 기본 붙여넣기 동작 수행
        super().insertFromMimeData(source)

    def is_web_image_url(self, url_string: str) -> bool:
        """웹 이미지 URL인지 확인"""
        if not url_string.startswith(('http://', 'https://')):
            return False
        
        # URL 끝에 이미지 확장자가 있는지 확인
        ext = os.path.splitext(url_string.split('?')[0])[1].lower()
        return ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')

    def download_web_image(self, url: str):
        """웹 이미지를 다운로드하여 처리"""
        # 이미 다운로드 중이면 무시
        if self.download_thread and self.download_thread.isRunning():
            return
            
        # 프로그레스 다이얼로그 생성
        self.progress_dialog = QProgressDialog("이미지 다운로드 중... \n복사 붙여넣기를 권장합니다", "취소", 0, 0, self)
        self.progress_dialog.setWindowTitle("이미지 다운로드")
        self.progress_dialog.setModal(True)
        self.progress_dialog.show()
        
        # 다운로드 스레드 시작
        self.download_thread = ImageDownloadThread(url)
        self.download_thread.image_downloaded.connect(self.on_image_downloaded)
        self.download_thread.download_failed.connect(self.on_download_failed)
        self.download_thread.finished.connect(self.on_download_finished)
        
        # 취소 버튼 연결
        self.progress_dialog.canceled.connect(self.cancel_download)
        
        self.download_thread.start()
    
    def on_image_downloaded(self, pil_image: Image.Image):
        """이미지 다운로드 완료 시 호출"""
        self.show_img2img_popup(pil_image)
    
    def on_download_failed(self, error_msg: str):
        """다운로드 실패 시 호출"""
        QMessageBox.warning(self, "다운로드 실패", f"이미지를 다운로드할 수 없습니다.\n\n{error_msg}")
    
    def on_download_finished(self):
        """다운로드 완료 후 정리"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        self.download_thread = None
    
    def cancel_download(self):
        """다운로드 취소"""
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()
        self.on_download_finished()

    def show_img2img_popup(self, pil_image: Image.Image):
        print(f"🔍 show_img2img_popup 호출: 이미지 모드 = {pil_image.mode}, 크기 = {pil_image.size}")
        main_window = self.window()
        popup = Img2ImgPopup(pil_image=pil_image, app_context=self.app_context, parent=main_window)

        # 팝업의 신호를 메인 윈도우의 슬롯에 연결
        if hasattr(main_window, 'activate_img2img_panel'):
            popup.img2img_requested.connect(main_window.activate_img2img_panel)
        if hasattr(main_window, 'activate_inpaint_mode'):
            popup.inpaint_requested.connect(main_window.activate_inpaint_mode)
        if hasattr(main_window, 'activate_vibe_transfer'):
            popup.import_vibe_transfer_requested.connect(main_window.activate_vibe_transfer)
        if hasattr(main_window, 'on_tag_interrogation_requested'):
            popup.tag_interrogation_requested.connect(main_window.on_tag_interrogation_requested)

        # 팝업 위치 조정 및 실행
        cursor_pos = QCursor.pos()
        popup_rect = popup.geometry()

        # 팝업의 좌상단 위치 계산 (마우스 커서 x 좌표 중앙, 마우스 커서 y 좌표 - 팝업 높이)
        new_x = cursor_pos.x() - popup_rect.width() // 2
        new_y = cursor_pos.y() - popup_rect.height()

        # 화면 경계 처리 (선택 사항)
        screen = main_window.screen()
        screen_rect = screen.availableGeometry()
        new_x = max(screen_rect.left() + 5, min(new_x, screen_rect.right() - popup_rect.width() - 5))
        new_y = max(screen_rect.top() + 5, min(new_y, screen_rect.bottom() - popup_rect.height() - 5))

        popup.move(new_x, new_y)

        popup.exec()

    def dragEnterEvent(self, event):
        """드래그 진입 시 이벤트 (선택적으로 미리보기 제공)"""
        if event.mimeData().hasUrls():
            # 웹 URL 미리 체크해서 드래그 커서 변경 가능
            for url in event.mimeData().urls():
                url_string = url.toString()
                if self.is_web_image_url(url_string):
                    event.acceptProposedAction()
                    return
        
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """드래그 이동 시 이벤트"""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                url_string = url.toString()
                if self.is_web_image_url(url_string):
                    event.acceptProposedAction()
                    return
        
        super().dragMoveEvent(event)


class _PipInstallWorker(QObject):
    """백그라운드에서 pip install을 실행하는 워커"""
    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, python_exe: str, package: str):
        super().__init__()
        self._python_exe = python_exe
        self._package = package

    def run(self):
        import subprocess
        try:
            result = subprocess.run(
                [self._python_exe, '-m', 'pip', 'install', self._package],
                check=True, capture_output=True, text=True
            )
            self.finished.emit(True, result.stdout)
        except subprocess.CalledProcessError as e:
            self.finished.emit(False, e.stderr or str(e))
        except Exception as e:
            self.finished.emit(False, str(e))


class TempWindowManager:
    """임시 생성 창 관리자 - 여러 개의 임시 창 생명주기 관리"""

    def __init__(self, main_window):
        """
        Args:
            main_window: ModernMainWindow 인스턴스
        """
        self.main_window = main_window
        self.temp_windows = {}  # {window_id: TempGenerationWindow}
        self.next_window_id = 1

    def create_temp_window(self):
        """
        새 임시 창 생성 및 초기화

        Returns:
            TempGenerationWindow: 생성된 임시 창 인스턴스
        """
        window_id = self.next_window_id
        self.next_window_id += 1

        # 임시 창 생성 (완전 독립)
        temp_window = TempGenerationWindow(
            window_id=window_id,
            app_context=self.main_window.app_context,
            parent=None  # 완전 독립
        )

        # 시그널 연결
        temp_window.generate_requested.connect(
            self.main_window.on_temp_window_generate_requested
        )
        temp_window.params_update_requested.connect(
            self.main_window.apply_temp_params
        )
        temp_window.random_prompt_requested.connect(
            self.handle_random_prompt_request
        )
        temp_window.window_closing.connect(
            self.main_window.on_temp_window_closing
        )

        # 추적 딕셔너리에 추가
        self.temp_windows[window_id] = temp_window

        # 창 표시 (독립 창으로)
        temp_window.show()
        temp_window.raise_()
        temp_window.activateWindow()

        print(f"✅ [TempWindowManager] 임시 창 #{window_id} 생성 완료 (총 {len(self.temp_windows)}개)")

        return temp_window

    def handle_random_prompt_request(self, window_id: int):
        """
        🆕 Issue 1 Fix: 임시 창에서 Random/Next Prompt 요청 처리

        메인 UI를 오염시키지 않고 독립적으로 프롬프트를 생성하여 임시 창에 반영합니다.

        Args:
            window_id: 요청한 창의 ID
        """
        print(f"[TempWindowManager] 임시 창 #{window_id}에서 Random/Next Prompt 요청 수신")

        # 임시 창 확인
        temp_window = self.temp_windows.get(window_id)
        if not temp_window:
            print(f"⚠️ [TempWindowManager] 임시 창 #{window_id}를 찾을 수 없습니다")
            return

        # 프롬프트 고정 체크박스 상태 확인
        is_fixed = temp_window.prompt_fixed_checkbox.isChecked()

        # 독립적인 프롬프트 생성 (메인 UI 메서드 사용하되 결과만 가져옴)
        # 메인 UI의 프롬프트를 임시 저장
        original_main_prompt = self.main_window.main_prompt_textedit.toPlainText()
        original_negative_prompt = self.main_window.negative_prompt_textedit.toPlainText()

        try:
            # 🆕 FR-3: 메인 PromptEngineeringModule 훅 비활성화 (임시 창 자체 훅 사용)
            self.main_window.app_context.skip_prompt_engineering_hook = True
            print("[DEBUG] ✅ skip_prompt_engineering_hook = True 설정")

            # 와일드카드 단독 모드 체크
            is_wildcard_standalone = hasattr(temp_window, 'wildcard_standalone_checkbox') and temp_window.wildcard_standalone_checkbox.isChecked()

            if is_wildcard_standalone:
                # 와일드카드 단독 모드: trigger_random_prompt()를 호출하지 않고 빈 프롬프트 사용
                print("[DEBUG] 와일드카드 단독 모드: 랜덤 프롬프트 생성 건너뛰기")
                new_main_prompt = ""  # 빈 프롬프트
                new_negative_prompt = self.main_window.negative_prompt_textedit.toPlainText()
            else:
                # 일반 모드: 메인 UI의 프롬프트 생성 메서드 호출
                if hasattr(self.main_window, 'trigger_random_prompt'):
                    self.main_window.trigger_random_prompt()
                else:
                    print(f"⚠️ [TempWindowManager] MainWindow에 trigger_random_prompt 메서드가 없습니다")
                    return

                # 생성된 프롬프트 가져오기
                new_main_prompt = self.main_window.main_prompt_textedit.toPlainText()
                new_negative_prompt = self.main_window.negative_prompt_textedit.toPlainText()

                print(f"[DEBUG] 메인 UI에서 생성된 프롬프트: {new_main_prompt[:50]}...")

            # 🆕 FR-3: 임시 창의 프롬프트 엔지니어링 훅 수동 실행
            if hasattr(temp_window, 'prompt_engineering_tab'):
                print(f"[DEBUG] 임시 창 프롬프트 엔지니어링 훅 실행 중...")

                # PromptContext 생성
                from core.prompt_context import PromptContext
                # pd는 이미 파일 상단에서 전역 import됨 (line 14)

                # source_row 준비 (와일드카드 단독 모드 지원)
                if hasattr(temp_window, 'wildcard_standalone_checkbox') and temp_window.wildcard_standalone_checkbox.isChecked():
                    # 와일드카드 단독 모드: 빈 데이터로 source_row 생성
                    empty_data = {
                        'general': None,
                        'character': None,
                        'copyright': None,
                        'artist': None,
                        'meta': None
                    }
                    source_row = pd.Series(empty_data, name="wildcard_standalone")
                    print(f"[DEBUG] 와일드카드 단독 모드: 빈 source_row 생성")
                else:
                    source_row = self.main_window.app_context.current_source_row
                    if source_row is None:
                        source_row = pd.Series({'general': None}, name="temp_window_random")

                # tags 파싱 (쉼표로 분리)
                input_tags = [tag.strip() for tag in new_main_prompt.split(',') if tag.strip()]

                # PromptContext 초기화
                temp_context = PromptContext(
                    source_row=source_row,
                    settings={},
                    prefix_tags=[],
                    main_tags=input_tags,
                    postfix_tags=[]
                )

                # 수동 훅 실행
                try:
                    modified_context = temp_window.prompt_engineering_tab.execute_manual_hook(temp_context)

                    # 수정된 태그를 다시 문자열로 결합
                    all_tags = modified_context.prefix_tags + modified_context.main_tags + modified_context.postfix_tags
                    new_main_prompt = ', '.join(all_tags)

                    print(f"[DEBUG] ✅ 임시 창 프롬프트 엔지니어링 적용 완료: {new_main_prompt[:50]}...")
                except Exception as e:
                    print(f"[DEBUG] ⚠️ 임시 창 프롬프트 엔지니어링 훅 실행 오류: {e}")
            else:
                print(f"[DEBUG] ⚠️ 임시 창에 prompt_engineering_tab이 없습니다")

            # 임시 창에 프롬프트 업데이트
            temp_window.update_prompts(new_main_prompt, new_negative_prompt)

            print(f"[TempWindowManager] 임시 창 #{window_id} 프롬프트 업데이트 완료 (고정 모드: {is_fixed})")

        finally:
            # 🆕 FR-3: 메인 PromptEngineeringModule 훅 재활성화
            self.main_window.app_context.skip_prompt_engineering_hook = False
            print("[DEBUG] ✅ skip_prompt_engineering_hook = False 해제")

            # 메인 UI 프롬프트 복원 (오염 방지)
            self.main_window.main_prompt_textedit.setPlainText(original_main_prompt)
            self.main_window.negative_prompt_textedit.setPlainText(original_negative_prompt)

            print(f"[TempWindowManager] 메인 UI 프롬프트 복원 완료 (오염 방지)")

    def close_temp_window(self, window_id: int):
        """
        임시 창 닫기 및 정리

        Args:
            window_id: 닫을 창의 ID
        """
        if window_id in self.temp_windows:
            window = self.temp_windows[window_id]

            # 창 닫기
            window.close()

            # deleteLater 호출하여 Qt 객체 정리
            window.deleteLater()

            # 딕셔너리에서 제거
            del self.temp_windows[window_id]

            print(f"🗑️ [TempWindowManager] 임시 창 #{window_id} 정리 완료 (남은 창: {len(self.temp_windows)}개)")

    def cleanup_all_temp_windows(self):
        """
        모든 임시 창 강제 닫기 (메인 윈도우 닫을 때 호출)
        """
        window_ids = list(self.temp_windows.keys())

        for window_id in window_ids:
            self.close_temp_window(window_id)

        print(f"🧹 [TempWindowManager] 모든 임시 창 정리 완료")


class Img2ImgWindowManager:
    """독립 Img2Img/Inpaint 윈도우 관리자"""

    def __init__(self, main_window):
        self.main_window = main_window
        self.windows = {}  # {window_id: Img2ImgWindow}
        self._next_id = 1
        self._last_strength = 50  # 0~99 (기본값 0.50)
        self._last_noise = 0      # 0~99 (기본값 0.00)
        self._batch_states = {}   # {window_id: {'total', 'current', 'params'}}

    def create_window(self, pil_image, mode='img2img',
                      mask_data=None, outpaint_data=None,
                      history_item=None, auto_generate=False):
        """새 독립 Img2Img 윈도우 생성"""
        window_id = self._next_id
        self._next_id += 1

        window = Img2ImgWindow(window_id, self.main_window.app_context)
        window.generate_requested.connect(self.main_window.on_img2img_window_generate)
        window.window_closing.connect(self._on_window_closing)
        window.cancel_batch_requested.connect(self._on_cancel_batch)

        window.set_image(pil_image, mode, mask_data, outpaint_data)

        # 프롬프트 초기화
        if (history_item and
                hasattr(history_item, 'prompt_context') and
                history_item.prompt_context):
            window.initialize_from_history_item(history_item)
        else:
            window.initialize_from_main_ui(self.main_window)

        # 마지막 Strength/Noise 값 적용
        window.strength_slider.setValue(self._last_strength)
        window.noise_slider.setValue(self._last_noise)

        self.windows[window_id] = window
        window.show()

        # 즉시 생성 (Outpaint Accept 등)
        if auto_generate:
            window.on_generate_clicked()

        return window

    def _on_window_closing(self, window_id):
        if window_id in self.windows:
            window = self.windows[window_id]
            # Strength/Noise 값 기억
            self._last_strength = window.strength_slider.value()
            self._last_noise = window.noise_slider.value()
            self.windows.pop(window_id)
        self._batch_states.pop(window_id, None)

    # ─── 배치 반복 생성 ─────────────────────────────────

    def setup_batch(self, window_id: int, params: dict, total: int):
        """배치 초기화 — 윈도우에 Progress UI 표시"""
        self._batch_states[window_id] = {
            'total': total,
            'current': 0,
            'params': params.copy(),
        }
        window = self.windows.get(window_id)
        if window:
            window.start_batch_ui(total)
        print(f"[Img2ImgBatch] Window #{window_id}: 배치 시작 ({total}회)")

    def on_batch_generation_completed(self, window_id: int):
        """한 건 완료 → 진행률 갱신 → 다음 트리거 또는 배치 종료"""
        state = self._batch_states.get(window_id)
        if not state:
            return  # 취소됨 or 창 닫힘

        state['current'] += 1
        current, total = state['current'], state['total']

        window = self.windows.get(window_id)
        if window:
            window.update_batch_progress(current, total)

        print(f"[Img2ImgBatch] Window #{window_id}: {current}/{total} 완료")

        if current < total:
            QTimer.singleShot(100, lambda: self._trigger_next_batch(window_id))
        else:
            self._finish_batch(window_id)

    def _trigger_next_batch(self, window_id: int):
        """다음 생성 트리거 (동일 params 재사용)"""
        state = self._batch_states.get(window_id)
        if not state or window_id not in self.windows:
            self._batch_states.pop(window_id, None)
            return
        params = state['params'].copy()
        params['img2img_batch_request'] = True
        params['img2img_batch_total'] = state['total']
        params['img2img_batch_window_id'] = window_id
        self.main_window.generation_controller.execute_generation_pipeline(overrides=params)

    def _finish_batch(self, window_id: int):
        """배치 정상 완료"""
        self._batch_states.pop(window_id, None)
        window = self.windows.get(window_id)
        if window:
            window.finish_batch_ui()
        print(f"[Img2ImgBatch] Window #{window_id}: 배치 완료")

    def _on_cancel_batch(self, window_id: int):
        """배치 취소 요청 처리"""
        if window_id in self._batch_states:
            state = self._batch_states.pop(window_id)
            window = self.windows.get(window_id)
            if window:
                window.finish_batch_ui()
            print(f"[Img2ImgBatch] Window #{window_id}: 배치 중지 ({state['current']}/{state['total']})")

    def is_any_batch_running(self) -> bool:
        """배치 진행 중 여부"""
        return len(self._batch_states) > 0

    def close_all(self):
        for w in list(self.windows.values()):
            w.close()
        self.windows.clear()
        self._batch_states.clear()


class ModernMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 기본 타이틀 설정 (Git 정보 없을 때 사용)
        self.base_title = "NAIA v2.0.0 Dev 150"
        self.setWindowTitle(self.base_title + " - 260225")  # 기존 형식 유지
        
        # 스케일링 매니저 초기화 (UI 생성 전에 먼저 초기화)
        self.scaling_manager = get_scaling_manager()
        
        # 업데이트 확인 스레드 변수 추가
        self.update_checker_thread = None
        self.github_repo_owner = "DNT-LAB"    # GitHub 사용자명
        self.github_repo_name = "NAIA2.0"     # GitHub 저장소 이름
        self.github_branch = "Dev0714"        # GitHub 브랜치
        
        # Git 정보 저장 변수
        self.current_commit_sha = ""
        self.current_commit_date = ""
        self.latest_commit_sha = ""
        self.latest_commit_date = ""
        self.has_git = False
        
        self.set_initial_window_size()
        self.kr_tags_df = self._load_kr_tags()
        self.params_expanded = False
        
        # 동적 테마 적용
        self.apply_dynamic_styles()
        
        # 새로 추가: 파라미터 확장 상태 추적
        self.params_expanded = False

        # 🆕 모듈 시스템 관련 변수 추가
        self.middle_section_controller = None
        self.automation_module = None
        # [신규] 자동 생성 중복 방지를 위한 플래그
        self.auto_generation_in_progress = False
        self.last_auto_generation_time = 0
        self.last_image_generation_time = 0

        #  검색 결과를 저장할 변수 및 컨트롤러 초기화
        self.search_results = SearchResultModel()
        self.search_controller = SearchController()
        # 검색 컨트롤러 시그널 연결은 MainController에서 처리됩니다

        self.image_window = None 
        # [신규] 데이터 및 와일드카드 관리자 초기화
        self.tag_data_manager = TagDataManager()
        self.wildcard_manager = WildcardManager()
        self.app_context = AppContext(self, self.wildcard_manager, self.tag_data_manager)

        self.img2img_panel = Img2ImgPanel(self)

        # TempWindowManager 초기화
        self.temp_window_manager = TempWindowManager(self)

        # Img2ImgWindowManager 초기화
        self.img2img_window_manager = Img2ImgWindowManager(self)

        # EZ Mode 창 변수 초기화
        self.ez_mode_window = None

        # 🆕 임시 창 자동 종료를 위한 모드/모델 추적 변수
        self._previous_api_mode = "NAI"
        self._previous_nai_model = "NAID4.5F"

        # MainController 초기화 (UI 초기화 전에 생성)
        self.controller = MainController(self)
        self.scaling_manager.scaling_changed.connect(self.controller.on_scaling_changed)

        self.init_ui()
        
        # MiddleSectionController가 모듈 인스턴스들을 가지고 있음
        self.middle_section_controller.initialize_modules_with_context(self.app_context)
        self.generation_controller = GenerationController(
            self.app_context,
            self.middle_section_controller.module_instances
        )
        self.app_context.middle_section_controller = self.middle_section_controller

        self.prompt_gen_controller = PromptGenerationController(self.app_context)
        
        # 신호 연결 (UI 초기화 후)
        self.controller.connect_signals()
        # 🆕 메인 생성 파라미터 모드 관리자 추가
        self.generation_params_manager = GenerationParamsManager(self)
        
        # AppContext에 모드 변경 이벤트 구독
        self.app_context.subscribe_mode_swap(self.generation_params_manager.on_mode_changed)
        self.app_context.subscribe_mode_swap(self._on_mode_changed_for_remote)
        self.app_context.subscribe_mode_swap(lambda *_: self._update_model_list_for_comfyui())
        
        # 초기 토큰 카운트 업데이트
        QTimer.singleShot(100, self.update_token_count)
        QTimer.singleShot(100, self.update_negative_token_count)
        
        # CharacterModule 업데이트 시 토큰 카운트 업데이트
        self.app_context.subscribe("character_changed", lambda: self.update_token_count())

        # 큐 이벤트 구독 - 버튼 상태 자동 업데이트
        def update_button_on_queue_event(_=None):
            """큐 이벤트 발생 시 버튼 상태 업데이트"""
            if hasattr(self, 'generation_controller') and self.generation_controller:
                self.generation_controller._update_button_with_queue_size()

        for queue_event in [
            "queue_request_enqueued", "queue_request_dequeued",
            "queue_queue_paused", "queue_queue_resumed",
            "queue_queue_cleared", "queue_request_removed"
        ]:
            self.app_context.subscribe(queue_event, update_button_on_queue_event)

        # 초기 설정 로드 (NAI 모드)
        self.generation_params_manager.load_mode_settings("NAI")

        # [신규] 앱 시작 시 마지막 상태 로드
        # self.load_generation_parameters()
        self.load_last_search_state()

        # ✅ 2. AutoCompleteManager 초기화 방식 변경
        print("🔍 AutoCompleteManager 전역 인스턴스 요청 중...")
        # 새로운 getter 패턴 사용
        self.autocomplete_manager = get_autocomplete_manager(app_context=self.app_context)
        self.workflow_manager = self.app_context.comfyui_workflow_manager

        self.main_prompt_textedit.installEventFilter(self)
        self.negative_prompt_textedit.installEventFilter(self)
        self.main_prompt_textedit.viewport().installEventFilter(self)
        self.negative_prompt_textedit.viewport().installEventFilter(self)

        self.resolution_is_detected = False

        # 초기화 완료 후 splitter stretch factor 업데이트
        QTimer.singleShot(100, self.update_splitter_stretch_factors)
        # 초기 체크박스 색상 설정 (기본 모델에 따라)
        QTimer.singleShot(300, self.update_naid_checkbox_colors)
        
        # 프로그램 시작 시 업데이트 확인 (UI 초기화 완료 후 충분한 시간 뒤에)
        QTimer.singleShot(2000, self.check_for_updates)  # 2초 후 시작

        # 🆕 멀티 NAI 계정 알림 (업데이트 확인 후)
        QTimer.singleShot(3000, self._show_multi_account_notification)  # 3초 후 시작

    def apply_dynamic_styles(self):
        """동적 스타일시트 적용"""
        try:
            dynamic_styles = get_dynamic_styles()
            # 메인 윈도우 스타일 적용 (CUSTOM["main"] 대신 동적 스타일 사용)
            main_style = f"""
                QMainWindow {{
                    background-color: {DARK_COLORS['bg_primary']};
                    color: {DARK_COLORS['text_primary']};
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                    font-size: {get_scaled_font_size(14)}px;
                }}
            """
            self.setStyleSheet(main_style)
            print(f"동적 UI 스케일링 적용됨 (스케일: {self.scaling_manager.get_scale_factor():.2f}x)")
        except Exception as e:
            print(f"동적 스타일 적용 실패: {e}")
            # 폴백: 기존 정적 스타일 사용
            self.setStyleSheet(CUSTOM["main"])
    
    def show_scaling_settings(self):
        """UI 스케일링 설정 다이얼로그 표시"""
        dialog = ScalingSettingsDialog(self)
        dialog.scaling_changed.connect(self.controller.on_scaling_changed)
        dialog.exec()

    # 자동완성 기능 사용 가능 여부를 확인하는 헬퍼 메서드
    def is_autocomplete_available(self) -> bool:
        """자동완성 기능이 사용 가능한지 확인합니다."""
        return (self.autocomplete_manager is not None and 
                hasattr(self.autocomplete_manager, '_initialized') and
                self.autocomplete_manager._initialized)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("1단계 구현 완료: 메인 스플리터 통합")
        self.status_bar.setStyleSheet(CUSTOM["status_bar"])
        

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_panel = self.create_left_panel()
        self.image_window = self.create_right_panel()

        # 해상도별 최소 너비 설정
        window_width = self.width() if self.width() > 0 else get_scaled_size(1920)
        if window_width <= get_scaled_size(1920):  # FHD 이하
            # FHD에서는 좌측 패널 최소 너비를 줄여서 더 유연하게 조정
            left_min_width = get_scaled_size(300)  # 600 -> 450으로 감소
            left_min_size = get_scaled_size(300)
        else:  # QHD 이상
            left_min_width = get_scaled_size(450)   # 기존 유지
            left_min_size = get_scaled_size(450)
            
        left_panel.setMinimumWidth(left_min_width)
        self.image_window.setMinimumWidth(get_scaled_size(350))  # 우측 패널 최소 너비 유지
        
        # 선호 크기 설정 (초기 크기)
        left_panel.setMinimumSize(left_min_size, get_scaled_size(350))
        self.image_window.setMinimumSize(get_scaled_size(650), get_scaled_size(350))

        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(self.image_window)
        # FHD 대응: 더 균형잡힌 패널 비율 (45:55)
        self.main_splitter.setStretchFactor(0, 49)
        self.main_splitter.setStretchFactor(1, 51)

        main_layout.addWidget(self.main_splitter)

    def create_middle_section(self):
        """중간 섹션: 동적 모듈 로드 및 EnhancedCollapsibleBox 하위로 배치"""
        
        # 스크롤 영역 설정 (기존과 동일)
        middle_scroll_area = QScrollArea()
        middle_scroll_area.setWidgetResizable(True)
        middle_scroll_area.setStyleSheet(CUSTOM["middle_scroll_area"])

        # 모듈 컨테이너
        middle_container = QWidget()
        middle_layout = QVBoxLayout(middle_container)
        middle_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        middle_layout.setContentsMargins(6, 6, 6, 6)
        middle_layout.setSpacing(6)

        try:
            # 모듈 디렉토리 경로
            modules_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modules')

            # 컨트롤러 생성 및 모듈 로드
            self.middle_section_controller = MiddleSectionController(modules_dir, self.app_context, parent=self)
            self.middle_section_controller.build_ui(middle_layout)

            # [신규] 모듈 로드 완료 후 자동화 시그널 연결
            self.controller.connect_automation_signals()
            
            # E621 이벤트 모듈 시그널 연결
            self.controller.connect_e621_event_signals()

            # 상태 메시지 업데이트
            loaded_count = len(self.middle_section_controller.module_instances)
            self.status_bar.showMessage(f"✅ 모듈 시스템 활성화: {loaded_count}개 모듈 로드 완료 (분리 기능 포함)")
            
            print(f"🎉 모듈 시스템 성공적으로 활성화! {loaded_count}개 모듈 로드됨 (분리 기능 활성화)")
            
        except Exception as e:
            print(f"❌ 모듈 시스템 오류: {e}")
            self.status_bar.showMessage(f"⚠️ 모듈 시스템 오류 - 기본 모드로 동작")
            
            # 폴백: 기본 레이블 표시
            fallback_label = QLabel("모듈 로드 중 오류가 발생했습니다.")
            fallback_label.setStyleSheet(DARK_STYLES['label_style'])
            middle_layout.addWidget(fallback_label)

        middle_scroll_area.setWidget(middle_container)
        return middle_scroll_area

    def create_left_panel(self):
        # 메인 컨테이너 위젯
        main_container = QWidget()
        main_container.setStyleSheet(DARK_STYLES['main_container'])
        
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # 🚀 핵심 수정: 단일 수직 스플리터로 통합
        self.vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        self.vertical_splitter.setStyleSheet(CUSTOM["main_splitter"])

        # === 상단 영역: 검색 + 프롬프트 ===
        top_container = self.create_top_section()
        self.vertical_splitter.addWidget(top_container)

        # === 중간 영역: 자동화 설정들 ===  
        middle_container = self.create_middle_section()
        self.vertical_splitter.addWidget(middle_container)

        # FHD 대응: 스플리터 비율 설정 (상단 45%, 중간 55%)
        self.vertical_splitter.setStretchFactor(0, 45)
        self.vertical_splitter.setStretchFactor(1, 55)
        
        # 메인 레이아웃에 스플리터 추가
        main_layout.addWidget(self.vertical_splitter)
        main_layout.insertWidget(1, self.img2img_panel)

        # === 하단 영역: 확장 가능한 생성 제어 영역 ===
        bottom_area = self.create_enhanced_generation_area()
        main_layout.addWidget(bottom_area)

        return main_container

    def create_top_section(self):
        """상단 섹션: 검색 및 프롬프트 입력"""
        top_scroll_area = QScrollArea()
        top_scroll_area.setWidgetResizable(True)
        top_scroll_area.setStyleSheet(CUSTOM["top_scroll_area"])
        
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        # 검색 및 필터링 섹션
        search_box = CollapsibleBox("프롬프트 검색 / 필터링 / API 관리")
        self.search_collapsible_box = search_box  # 나중에 업데이트하기 위해 참조 저장
        
        # NAI 모드인지 확인하고 Anlas 표시
        if self.app_context.current_api_mode == "NAI":
            anlas = self.app_context.api_service.get_anlas()
            search_box.update_anlas(anlas)

        # 전체 검색 레이아웃
        search_main_layout = QVBoxLayout()
        search_main_layout.setSpacing(8)
        
        # === API 관리 레이아웃 (상단) ===
        api_layout = QHBoxLayout()
        api_layout.setSpacing(6)

        # NAI 토글 버튼
        self.nai_toggle_btn = QPushButton("NAI")
        self.nai_toggle_btn.setCheckable(True)
        self.nai_toggle_btn.setChecked(True)  # 기본값: NAI 선택
        self.nai_toggle_btn.setFixedHeight(38)
        self.nai_toggle_btn.clicked.connect(lambda: self.toggle_search_mode("NAI"))

        # WEBUI 토글 버튼
        self.webui_toggle_btn = QPushButton("WEBUI")
        self.webui_toggle_btn.setCheckable(True)
        self.webui_toggle_btn.setChecked(False)
        self.webui_toggle_btn.setFixedHeight(38)
        self.webui_toggle_btn.clicked.connect(lambda: self.toggle_search_mode("WEBUI"))

        # 🆕 ComfyUI 토글 버튼 추가
        self.comfyui_toggle_btn = QPushButton("COMFYUI")
        self.comfyui_toggle_btn.setCheckable(True)
        self.comfyui_toggle_btn.setChecked(False)
        self.comfyui_toggle_btn.setFixedHeight(38)
        self.comfyui_toggle_btn.clicked.connect(lambda: self.toggle_search_mode("COMFYUI"))

        # API 관리 버튼
        api_manage_btn = QPushButton("API 관리")
        api_manage_btn.setFixedHeight(38)
        api_manage_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        api_manage_btn.clicked.connect(self.open_search_management)

        # 토글 버튼 스타일 정의
        toggle_active_style = CUSTOM["toggle_active_style"]
        toggle_inactive_style = CUSTOM["toggle_inactive_style"]

        # 초기 스타일 적용
        self.nai_toggle_btn.setStyleSheet(toggle_active_style)
        self.webui_toggle_btn.setStyleSheet(toggle_inactive_style)
        self.comfyui_toggle_btn.setStyleSheet(toggle_inactive_style)  # 🆕 추가

        # 스타일을 나중에 사용하기 위해 저장
        self.toggle_active_style = toggle_active_style
        self.toggle_inactive_style = toggle_inactive_style

        # 🔧 수정: 4개 버튼을 균등하게 배치 (API 관리 버튼 포함)
        api_layout.addWidget(self.nai_toggle_btn, 1)
        api_layout.addWidget(self.webui_toggle_btn, 1)
        api_layout.addWidget(self.comfyui_toggle_btn, 1)  # 🆕 추가
        api_layout.addWidget(api_manage_btn, 1)

        search_main_layout.addLayout(api_layout)
        
        # === 기존 검색 레이아웃 (하단) ===
        search_layout = QVBoxLayout()
        search_layout.setSpacing(6)
        
        search_label = QLabel("검색 키워드")
        search_label.setStyleSheet(DARK_STYLES['label_style'])
        search_layout.addWidget(search_label)
        self.search_input = QLineEdit()
        self.search_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        search_layout.addWidget(self.search_input)
        
        exclude_label = QLabel("제외 키워드")
        exclude_label.setStyleSheet(DARK_STYLES['label_style'])
        search_layout.addWidget(exclude_label)
        self.exclude_input = QLineEdit()
        self.exclude_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        search_layout.addWidget(self.exclude_input)
        
        rating_layout = QHBoxLayout()
        rating_layout.setSpacing(8)
        
        # [수정] 체크박스들을 딕셔너리로 관리
        self.rating_checkboxes = {}
        checkboxes_map = {"Explicit": "e", "NSFW": "q", "Sensitive": "s", "General": "g"}
        for text, key in checkboxes_map.items():
            cb = QCheckBox(text)
            cb.setStyleSheet(DARK_STYLES['dark_checkbox'])
            cb.setChecked(True) # 기본적으로 모두 체크
            rating_layout.addWidget(cb)
            self.rating_checkboxes[key] = cb
        
        rating_layout.addStretch(1)

        # 검색 모드 라디오 버튼 (24.11 = max_129, 25.09 = max_149)
        self.search_mode_2411 = QRadioButton("24.11")
        self.search_mode_2411.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                spacing: {get_scaled_size(5)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
        self.search_mode_2411.setToolTip("24.11 데이터셋 (130개 파일, 빠른 검색)")
        rating_layout.addWidget(self.search_mode_2411)

        self.search_mode_2509 = QRadioButton("25.09")
        self.search_mode_2509.setChecked(True)  # 기본값
        self.search_mode_2509.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                spacing: {get_scaled_size(5)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
        self.search_mode_2509.setToolTip("25.09 데이터셋 (150개 파일, 최신 데이터)")
        rating_layout.addWidget(self.search_mode_2509)

        self.search_mode_1109 = QRadioButton("11-09")
        self.search_mode_1109.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                spacing: {get_scaled_size(5)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
        self.search_mode_1109.setToolTip("11-09 신규 데이터 (20개 파일, tags_130~149)")
        rating_layout.addWidget(self.search_mode_1109)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(16)}px; margin-left: 10px; margin-right: 10px;")
        rating_layout.addWidget(self.progress_label)

        self.search_btn = QPushButton("검색")
        self.search_btn.setStyleSheet(DARK_STYLES['primary_button'])
        rating_layout.addWidget(self.search_btn)
        search_layout.addLayout(rating_layout)
        
        # 메인 레이아웃에 검색 레이아웃 추가
        search_main_layout.addLayout(search_layout)
        
        # CollapsibleBox에 전체 레이아웃 설정
        search_box.setContentLayout(search_main_layout)
        top_layout.addWidget(search_box)

        # 검색 결과 표시 프레임
        self.search_result_frame = QFrame()
        self.search_result_frame.setStyleSheet(DARK_STYLES['compact_card'])
        search_result_layout = QHBoxLayout(self.search_result_frame)
        search_result_layout.setContentsMargins(10, 6, 10, 6)
        
        # [수정] 결과 레이블을 self 변수로 저장
        self.result_label1 = QLabel("검색: 0")
        self.result_label1.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-family: 'Pretendard'; font-size: {get_scaled_font_size(18)}px;")
        self.result_label2 = QLabel("남음: 0")
        self.result_label2.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-family: 'Pretendard'; font-size: {get_scaled_font_size(18)}px;")
        
        search_result_layout.addWidget(self.result_label1)
        search_result_layout.addWidget(self.result_label2)
        search_result_layout.addStretch(1)

        self.save_settings_btn = QPushButton("💾 설정 저장")
        self.save_settings_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: #5CBF60;
            }}
            QPushButton:pressed {{
                background-color: #3E8E41;
            }}
        """)
        self.save_settings_btn.setToolTip("현재 모든 설정을 저장합니다")
        
        self.restore_btn = QPushButton("⚙️ 복원")
        self.restore_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        
        # 복원 버튼에 컨텍스트 메뉴 추가
        self.restore_menu = QMenu(self)
        menu_style = f"""
            QMenu {{ background-color: {DARK_COLORS['bg_tertiary']}; color: {DARK_COLORS['text_primary']}; border: 1px solid {DARK_COLORS['border']}; border-radius: 4px; padding: 5px; }}
            QMenu::item {{ padding: 8px 20px; border-radius: 4px; }}
            QMenu::item:selected {{ background-color: {DARK_COLORS['accent_blue']}; }}
        """
        self.restore_menu.setStyleSheet(menu_style)
        
        # 메뉴 액션들 추가
        restore_search_action = QAction("🔄 검색결과 복원", self)
        restore_search_action.triggered.connect(self.restore_search_results)
        self.restore_menu.addAction(restore_search_action)
        
        load_parquet_action = QAction("📂 불러오기", self)
        load_parquet_action.triggered.connect(self.load_custom_parquet)
        self.restore_menu.addAction(load_parquet_action)
        
        merge_parquet_action = QAction("🔀 합치기", self)
        merge_parquet_action.triggered.connect(self.merge_custom_parquet)
        self.restore_menu.addAction(merge_parquet_action)
        
        export_parquet_action = QAction("💾 내보내기", self)
        export_parquet_action.triggered.connect(self.export_custom_parquet)
        self.restore_menu.addAction(export_parquet_action)
        
        save_execution_action = QAction("🚀 실행파일 저장", self)
        save_execution_action.triggered.connect(self.save_to_execution_file)
        self.restore_menu.addAction(save_execution_action)
        
        # 버튼에 메뉴 할당
        self.restore_btn.setMenu(self.restore_menu)
        self.deep_search_btn = QPushButton("심층검색")
        self.deep_search_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        
        search_result_layout.addWidget(self.save_settings_btn)
        search_result_layout.addWidget(self.restore_btn)
        search_result_layout.addWidget(self.deep_search_btn)
        top_layout.addWidget(self.search_result_frame)
        
        # 메인 프롬프트 창
        self.prompt_tabs = QTabWidget()
        self.prompt_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        self.prompt_tabs.setMinimumHeight(100)
        
        # 프롬프트 탭 분리 상태 추적
        self.prompt_tabs_detached = False
        self.prompt_tabs_window = None

        # Custom API 창 분리 상태 추적
        self.custom_api_detached = False
        self.custom_api_window = None

        # 탭 위젯에 우클릭 메뉴 추가
        self.prompt_tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.prompt_tabs.customContextMenuRequested.connect(self.show_prompt_tabs_context_menu)
        
        main_prompt_widget = QWidget()
        negative_prompt_widget = QWidget()
        
        main_prompt_layout = QVBoxLayout(main_prompt_widget)
        negative_prompt_layout = QVBoxLayout(negative_prompt_widget)
        
        main_prompt_layout.setContentsMargins(4, 4, 4, 4)
        negative_prompt_layout.setContentsMargins(4, 4, 4, 4)
        
        # [수정] 메인 프롬프트 텍스트 위젯을 self 변수로 저장
        self.main_prompt_textedit = PromptTextEdit()
        self.main_prompt_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.main_prompt_textedit.app_context = self.app_context # AppContext 주입
        self.main_prompt_textedit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.main_prompt_textedit.setPlaceholderText("메인 프롬프트를 입력하세요...")
        self.main_prompt_textedit.setMinimumHeight(100)
        main_prompt_layout.addWidget(self.main_prompt_textedit)
        self.main_prompt_textedit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.main_prompt_textedit.customContextMenuRequested.connect(self.show_prompt_context_menu)
        self.main_prompt_textedit.setStyleSheet(DARK_STYLES['compact_textedit'])

        # PromptHighlighter 적용
        self.main_prompt_highlighter = PromptHighlighter(self.main_prompt_textedit.document())

        self.main_prompt_token_label = QLabel("Estimated Tokens : 0 (Main 0 + Character 0)")
        main_prompt_layout.addWidget(self.main_prompt_token_label)
        
        # Connect text change event to update token count
        self.main_prompt_textedit.textChanged.connect(self.update_token_count)

        self.negative_prompt_textedit = PromptTextEdit()
        self.negative_prompt_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.negative_prompt_textedit.app_context = self.app_context
        self.negative_prompt_textedit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.negative_prompt_textedit.setPlaceholderText("네거티브 프롬프트를 입력하세요...")
        self.negative_prompt_textedit.setMinimumHeight(100)
        # 기본 QMenu 컨텍스트 메뉴 설정
        self.negative_prompt_textedit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.negative_prompt_textedit.customContextMenuRequested.connect(self.show_negative_prompt_context_menu)
        negative_prompt_layout.addWidget(self.negative_prompt_textedit)
        
        # 네거티브 프롬프트 토큰 카운트 라벨 추가
        self.negative_prompt_token_label = QLabel("Estimated Tokens : 0")
        negative_prompt_layout.addWidget(self.negative_prompt_token_label)
        
        # Connect negative prompt text change event to update token count
        self.negative_prompt_textedit.textChanged.connect(self.update_negative_token_count)
        
        self.prompt_tabs.addTab(main_prompt_widget, "메인 프롬프트")
        self.prompt_tabs.addTab(negative_prompt_widget, "네거티브 프롬프트 (UC)")

        self.previous_tab_index = 0  # 이전 탭 인덱스 저장용

        # 외부 창 상태 추적
        self.remote_window = None
        self.remote_window_open = False
        self.interactive_window = None
        self.interactive_window_open = False
        self.event_preset_window = None
        self.event_preset_window_open = False

        # 탭 전환 이벤트 연결
        self.prompt_tabs.currentChanged.connect(self._on_prompt_tab_changed)

        # 탭 바 우측 상단 버튼 컨테이너
        corner_widget_container = QWidget()
        corner_layout = QHBoxLayout(corner_widget_container)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(2)

        # 확장 기능 버튼 (컨텍스트 메뉴)
        self.extra_features_btn = QPushButton("🎨확장기능")
        self.extra_features_btn.setFixedSize(95, 55)
        self.extra_features_btn.setToolTip("확장 기능")
        self.extra_features_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 4px;
            }}
            QPushButton::menu-indicator {{
                width: 0px;
            }}
        """)

        # 확장 기능 컨텍스트 메뉴
        self.extra_features_menu = QMenu(self)
        self.extra_features_menu.setStyleSheet(f"""
            QMenu {{ background-color: {DARK_COLORS['bg_tertiary']}; color: {DARK_COLORS['text_primary']}; border: 1px solid {DARK_COLORS['border']}; border-radius: 4px; padding: 5px; }}
            QMenu::item {{ padding: 8px 20px; border-radius: 4px; }}
            QMenu::item:selected {{ background-color: {DARK_COLORS['accent_blue']}; }}
        """)

        # Event Preset 액션 (최상위)
        self.event_preset_action = QAction("📋 Event Preset", self)
        self.event_preset_action.triggered.connect(self._open_event_preset_window)
        self.extra_features_menu.addAction(self.event_preset_action)

        # Remote Window 액션
        self.remote_action = QAction("📡 리모트", self)
        self.remote_action.triggered.connect(self._open_remote_window)
        self.extra_features_menu.addAction(self.remote_action)

        # Interactive Window 액션
        self.interactive_action = QAction("🎨 Interactive Window", self)
        self.interactive_action.triggered.connect(self._open_interactive_window)
        self.extra_features_menu.addAction(self.interactive_action)

        # EZ Mode 액션
        self.ez_mode_action = QAction("⚡ EZ Mode", self)
        self.ez_mode_action.triggered.connect(self.open_ez_mode_window)
        self.extra_features_menu.addAction(self.ez_mode_action)

        self.extra_features_btn.setMenu(self.extra_features_menu)
        corner_layout.addWidget(self.extra_features_btn)

        # 대기열 버튼 추가
        self.queue_btn = QPushButton("대기열")
        self.queue_btn.setFixedSize(80, 55)
        self.queue_btn.setToolTip("생성 대기열 관리")
        self.queue_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 4px;
            }}
        """)
        self.queue_btn.clicked.connect(self.toggle_queue_window)
        #corner_layout.addWidget(self.queue_btn)

        # [Temp] 버튼 추가 (임시 생성 창)
        self.prompt_tabs_temp_btn = QPushButton("📝")
        self.prompt_tabs_temp_btn.setFixedSize(45, 55)
        self.prompt_tabs_temp_btn.setToolTip("임시 생성 창 열기")
        self.prompt_tabs_temp_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 4px;
            }}
        """)
        self.prompt_tabs_temp_btn.clicked.connect(self.create_temp_generation_window)
        corner_layout.addWidget(self.prompt_tabs_temp_btn)

        # detach 버튼 추가
        self.prompt_tabs_detach_btn = QPushButton("🔓")
        self.prompt_tabs_detach_btn.setFixedSize(45, 55)
        self.prompt_tabs_detach_btn.setToolTip("외부 창으로 분리")
        self.prompt_tabs_detach_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 4px;
            }}
        """)
        self.prompt_tabs_detach_btn.clicked.connect(self.toggle_prompt_tabs_detach)
        corner_layout.addWidget(self.prompt_tabs_detach_btn)

        self.prompt_tabs.setCornerWidget(corner_widget_container, Qt.Corner.TopRightCorner)
        
        # 프롬프트 탭 컨테이너 생성 (분리/재부착을 위한 래퍼)
        self.prompt_tabs_container = QWidget()
        prompt_tabs_container_layout = QVBoxLayout(self.prompt_tabs_container)
        prompt_tabs_container_layout.setContentsMargins(0, 0, 0, 0)
        prompt_tabs_container_layout.addWidget(self.prompt_tabs)
        
        top_layout.addWidget(self.prompt_tabs_container)

        top_scroll_area.setWidget(top_container)
        return top_scroll_area

    def disable_wheel_event(self, widget):
        """위젯의 마우스 휠 이벤트를 비활성화"""
        def wheelEvent(event):
            event.ignore()
        widget.wheelEvent = wheelEvent
        return widget
    
    def create_enhanced_generation_area(self):
        """확장 가능한 생성 제어 영역 생성"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # 1. 투명 배경의 확장 버튼 프레임
        self.expand_button_frame = QFrame(container)
        self.expand_button_frame.setStyleSheet(DARK_STYLES['transparent_frame'])
        expand_button_layout = QHBoxLayout(self.expand_button_frame)
        expand_button_layout.setContentsMargins(8, 4, 8, 4)
        
        # 왼쪽 스페이서
        expand_button_layout.addStretch(1)
        
        # 확장/축소 토글 버튼
        self.params_toggle_button = QPushButton("▲ 생성 파라미터 열기")
        self.params_toggle_button.setStyleSheet(DARK_STYLES['expand_toggle_button'])
        self.params_toggle_button.clicked.connect(self.toggle_params_panel)
        expand_button_layout.addWidget(self.params_toggle_button)
        
        # 오른쪽 스페이서
        expand_button_layout.addStretch(1)
        
        container_layout.addWidget(self.expand_button_frame)
        
        # 2. 확장 가능한 생성 파라미터 영역
        self.params_area = QWidget(container)
        self.params_area.setVisible(False)  # 기본적으로 숨김
        self.params_area.setStyleSheet(DARK_STYLES['compact_card'])
        
        params_layout = QVBoxLayout(self.params_area)
        params_layout.setContentsMargins(12, 12, 12, 12)
        params_layout.setSpacing(8)
        
        # 생성 파라미터 제목
        params_title = QLabel("🎛️ 생성 파라미터")
        params_title.setStyleSheet(CUSTOM["params_title"])
        params_layout.addWidget(params_title)
        
        # 파라미터 그리드 레이아웃
        params_grid = QGridLayout()
        params_grid.setSpacing(8)
        
        # 생성 파라미터 라벨들을 위한 공통 스타일
        param_label_style = CUSTOM["param_label_style"]
        
        # === 첫 번째 행: 모델 선택 + 스케줄러 ===
        model_label = QLabel("모델 선택")
        model_label.setStyleSheet(param_label_style)
        params_grid.addWidget(model_label, 0, 0)
        
        self.model_combo = QComboBox()
        self.model_combo.addItems(["NAID4.5F", "NAID4.5C", "NAID4.0F", "NAID4.0C", "NAID3"])
        self.model_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.disable_wheel_event(self.model_combo)  # 마우스 휠 비활성화
        self.model_combo.currentTextChanged.connect(self.update_naid_checkbox_colors)  # 모델 변경 시 체크박스 색상 업데이트
        self.model_combo.currentTextChanged.connect(self._on_model_changing)  # 🆕 임시 창 자동 종료 체크
        params_grid.addWidget(self.model_combo, 0, 1)
        
        scheduler_label = QLabel("스케줄러")
        scheduler_label.setStyleSheet(param_label_style)
        params_grid.addWidget(scheduler_label, 0, 2)
        
        self.scheduler_combo = QComboBox()
        self.scheduler_combo.addItems(["karras", "native", "exponential", "polyexponential"])
        self.scheduler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.disable_wheel_event(self.scheduler_combo)  # 마우스 휠 비활성화
        params_grid.addWidget(self.scheduler_combo, 0, 3)
        
        # === 두 번째 행: 해상도 + 랜덤 해상도 ===
        resolution_label = QLabel("해상도")
        resolution_label.setStyleSheet(param_label_style)
        params_grid.addWidget(resolution_label, 1, 0)

        self.resolution_combo = QComboBox()
        # ✅ JSON 파일에서 해상도 로드 (없으면 기본값 사용)
        self.resolutions = self._load_resolutions()
        self.resolution_combo.addItems(self.resolutions)
        self.resolution_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.disable_wheel_event(self.resolution_combo)  # 마우스 휠 비활성화
        params_grid.addWidget(self.resolution_combo, 1, 1)
        
        # 랜덤 해상도 체크박스
        self.random_resolution_checkbox = QCheckBox("랜덤 해상도")
        self.random_resolution_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        params_grid.addWidget(self.random_resolution_checkbox, 1, 2)
        
        # 해상도 관리 버튼
        resolution_manage_btn = QPushButton("해상도 관리")
        resolution_manage_btn.setStyleSheet(DARK_STYLES['compact_button'])
        resolution_manage_btn.setFixedWidth(100)
        resolution_manage_btn.clicked.connect(self.open_resolution_manager) 
        params_grid.addWidget(resolution_manage_btn, 1, 3)
        
        # === 세 번째 행: 샘플러 + Steps ===
        sampler_label = QLabel("샘플러")
        sampler_label.setStyleSheet(param_label_style)
        params_grid.addWidget(sampler_label, 2, 0)
        
        self.sampler_combo = QComboBox()
        # NAI 기본 샘플러들로 시작 (WEBUI 모드 전환 시 동적으로 변경됨)
        self.sampler_combo.addItems(["k_euler_ancestral", "k_euler", "k_dpmpp_2m", 
                                    "k_dpmpp_2s_ancestral", "k_dpmpp_sde", "k_dpmpp_2m_sde", "ddim_v3"])
        self.sampler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.disable_wheel_event(self.sampler_combo)  # 마우스 휠 비활성화
        params_grid.addWidget(self.sampler_combo, 2, 1)
        
        steps_label = QLabel("Steps")
        steps_label.setStyleSheet(param_label_style)
        params_grid.addWidget(steps_label, 2, 2)
        
        self.steps_spinbox = QSpinBox()
        self.steps_spinbox.setRange(1, 150)
        self.steps_spinbox.setValue(28)
        self.steps_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.disable_wheel_event(self.steps_spinbox)  # 마우스 휠 비활성화
        params_grid.addWidget(self.steps_spinbox, 2, 3)
        
        # === 네 번째 행: CFG Scale + CFG Rescale ===
        cfg_label = QLabel("CFG Scale")
        cfg_label.setStyleSheet(param_label_style)
        params_grid.addWidget(cfg_label, 3, 0)
        
        # CFG Scale 슬라이더 컨테이너
        cfg_container = QWidget()
        cfg_container_layout = QHBoxLayout(cfg_container)
        cfg_container_layout.setContentsMargins(0, 0, 0, 0)
        cfg_container_layout.setSpacing(5)
        
        self.cfg_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.cfg_scale_slider.setRange(10, 100)  # 1.0 ~ 30.0을 10 ~ 300으로 표현
        self.cfg_scale_slider.setValue(50)  # 기본값 5.0
        self.cfg_scale_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        self.disable_wheel_event(self.cfg_scale_slider)  # 마우스 휠 비활성화
        cfg_container_layout.addWidget(self.cfg_scale_slider)
        
        # CFG 값 표시 라벨
        self.cfg_value_label = QLabel("5.0")
        self.cfg_value_label.setStyleSheet(param_label_style)
        self.cfg_value_label.setFixedWidth(60)  # 30 → 40으로 증가
        self.cfg_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cfg_container_layout.addWidget(self.cfg_value_label)
        
        # CFG 슬라이더 값 변경 시 라벨 업데이트
        self.cfg_scale_slider.valueChanged.connect(
            lambda value: self.cfg_value_label.setText(f"{value/10:.1f}")
        )
        
        params_grid.addWidget(cfg_container, 3, 1)
        
        # CFG Rescale (NAI 전용) 라벨
        self.cfg_rescale_label = QLabel("CFG Rescale")
        self.cfg_rescale_label.setStyleSheet(param_label_style)
        params_grid.addWidget(self.cfg_rescale_label, 3, 2)
        
        # CFG Rescale 슬라이더 컨테이너
        rescale_container = QWidget()
        rescale_container_layout = QHBoxLayout(rescale_container)
        rescale_container_layout.setContentsMargins(0, 0, 0, 0)
        rescale_container_layout.setSpacing(5)
        
        self.cfg_rescale_slider = QSlider(Qt.Orientation.Horizontal)
        self.cfg_rescale_slider.setRange(-25, 100)  # 0.0 ~ 1.0을 0 ~ 100으로 표현
        self.cfg_rescale_slider.setValue(45)  # 기본값 0.2
        self.cfg_rescale_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        self.disable_wheel_event(self.cfg_rescale_slider)  # 마우스 휠 비활성화
        rescale_container_layout.addWidget(self.cfg_rescale_slider)
        
        # CFG Rescale 값 표시 라벨
        self.cfg_rescale_value_label = QLabel("0.40")
        self.cfg_rescale_value_label.setStyleSheet(param_label_style)
        self.cfg_rescale_value_label.setFixedWidth(68)  # 30 → 40으로 증가
        self.cfg_rescale_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rescale_container_layout.addWidget(self.cfg_rescale_value_label)
        
        # CFG Rescale 슬라이더 값 변경 시 라벨 업데이트
        self.cfg_rescale_slider.valueChanged.connect(
            lambda value: self.cfg_rescale_value_label.setText(f"{value/100:.2f}")
        )
        
        params_grid.addWidget(rescale_container, 3, 3)
        self.nai_rescale_ui = [self.cfg_rescale_label, rescale_container]

        # ComfyUI Rescale CFG (ANIMA 모드 전용) - NAI CFG Rescale과 동일 위치 (row 3, col 2-3)
        self.comfyui_rescale_label = QLabel("Rescale CFG")
        self.comfyui_rescale_label.setStyleSheet(param_label_style)
        params_grid.addWidget(self.comfyui_rescale_label, 3, 2)

        comfyui_rescale_container = QWidget()
        comfyui_rescale_layout = QHBoxLayout(comfyui_rescale_container)
        comfyui_rescale_layout.setContentsMargins(0, 0, 0, 0)
        comfyui_rescale_layout.setSpacing(5)

        self.comfyui_rescale_slider = QSlider(Qt.Orientation.Horizontal)
        self.comfyui_rescale_slider.setRange(0, 100)  # 0.00 ~ 1.00
        self.comfyui_rescale_slider.setValue(70)  # 기본값 0.70
        self.comfyui_rescale_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        self.disable_wheel_event(self.comfyui_rescale_slider)
        comfyui_rescale_layout.addWidget(self.comfyui_rescale_slider)

        self.comfyui_rescale_value_label = QLabel("0.70")
        self.comfyui_rescale_value_label.setStyleSheet(param_label_style)
        self.comfyui_rescale_value_label.setFixedWidth(68)
        self.comfyui_rescale_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        comfyui_rescale_layout.addWidget(self.comfyui_rescale_value_label)

        self.comfyui_rescale_slider.valueChanged.connect(
            lambda value: self.comfyui_rescale_value_label.setText(f"{value/100:.2f}")
        )

        params_grid.addWidget(comfyui_rescale_container, 3, 3)
        self.comfyui_rescale_ui = [self.comfyui_rescale_label, comfyui_rescale_container]

        # ComfyUI Rescale CFG는 초기에 숨김 (ComfyUI + ANIMA 모드에서만 표시)
        for w in self.comfyui_rescale_ui:
            w.setVisible(False)

        # === 다섯 번째 행: 시드 입력 + 시드 고정 ===
        seed_label = QLabel("시드")
        seed_label.setStyleSheet(param_label_style)
        params_grid.addWidget(seed_label, 4, 0)
        
        self.seed_input = QLineEdit("0")
        self.seed_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.seed_input.setPlaceholderText("0 = 랜덤")
        self.seed_input.setProperty("autocomplete_ignore", True)
        params_grid.addWidget(self.seed_input, 4, 1)
        
        # 시드 관련 체크박스들
        seed_controls_layout = QHBoxLayout()
        seed_controls_layout.setSpacing(12)
        
        self.seed_fix_checkbox = QCheckBox("시드 고정")
        self.seed_fix_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        seed_controls_layout.addWidget(self.seed_fix_checkbox)
        
        self.auto_fit_resolution_checkbox = QCheckBox("자동 해상도 맞춤")
        self.auto_fit_resolution_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        seed_controls_layout.addWidget(self.auto_fit_resolution_checkbox)
        
        seed_controls_layout.addStretch()
        
        params_grid.addLayout(seed_controls_layout, 4, 2, 1, 2)  # 2칸 차지
        
        params_layout.addLayout(params_grid)
        
        # === NAID Option / Hires Option 라인 (모드별 전환) ===
        # 섹션 라벨 (모드에 따라 텍스트 변경)
        self.option_section_label = QLabel("NAID Option")
        self.option_section_label.setStyleSheet(CUSTOM["naid_options_label"])
        
        # NAI 모드 전용 레이아웃
        self.naid_option_layout = QHBoxLayout()
        self.naid_option_layout.setSpacing(12)
        self.naid_option_layout.addWidget(self.option_section_label)
        
        # 4개의 NAID 옵션 체크박스
        naid_options = ["SMEA", "DYN", "VAR+", "DECRISP"]
        self.advanced_checkboxes = {}
        
        for option in naid_options:
            checkbox = QCheckBox(option)
            checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
            self.naid_option_layout.addWidget(checkbox)
            self.advanced_checkboxes[option] = checkbox
        
        self.naid_option_layout.addStretch()  # 오른쪽 여백
        
        # 🔥 수정: WEBUI 모드 전용 레이아웃을 2행으로 분리
        self.hires_option_widget = QWidget()
        self.hires_option_widget_layout = QVBoxLayout(self.hires_option_widget)
        self.hires_option_widget_layout.setSpacing(8)
        self.hires_option_widget_layout.setContentsMargins(0, 0, 0, 0)
        
        # 첫 번째 행: Hires-fix 활성화 + 배율 + 업스케일러
        self.hires_option_layout_row1 = QHBoxLayout()
        self.hires_option_layout_row1.setSpacing(8)
        
        # Hires-fix 활성화 체크박스
        self.enable_hr_checkbox = QCheckBox("Hires-fix 활성화")
        self.enable_hr_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.hires_option_layout_row1.addWidget(self.enable_hr_checkbox)
        
        # 구분선
        separator1 = QLabel("|")
        separator1.setStyleSheet(param_label_style)
        self.hires_option_layout_row1.addWidget(separator1)
        
        # HR Scale 스핀박스
        hr_scale_label = QLabel("배율")
        hr_scale_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row1.addWidget(hr_scale_label)
        
        self.hr_scale_spinbox = QDoubleSpinBox()
        self.hr_scale_spinbox.setRange(1.0, 4.0)
        self.hr_scale_spinbox.setSingleStep(0.1)
        self.hr_scale_spinbox.setValue(1.5)
        self.hr_scale_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.hr_scale_spinbox.setFixedWidth(80)
        self.hires_option_layout_row1.addWidget(self.hr_scale_spinbox)
        
        # 구분선
        separator2 = QLabel("|")
        separator2.setStyleSheet(param_label_style)
        self.hires_option_layout_row1.addWidget(separator2)
        
        # HR 업스케일러 콤보박스
        hr_upscaler_label = QLabel("업스케일러")
        hr_upscaler_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row1.addWidget(hr_upscaler_label)
        
        self.hr_upscaler_combo = QComboBox()
        self.hr_upscaler_combo.addItems(["Lanczos", "Nearest", "ESRGAN_4x", "LDSR", "SwinIR_4x"])
        self.hr_upscaler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.hr_upscaler_combo.setMinimumWidth(120)
        self.disable_wheel_event(self.hr_upscaler_combo)  # 마우스 휠 비활성화
        self.hires_option_layout_row1.addWidget(self.hr_upscaler_combo)
        
        self.hires_option_layout_row1.addStretch()
        
        # 두 번째 행: Hires Steps + Denoising Strength
        self.hires_option_layout_row2 = QHBoxLayout()
        self.hires_option_layout_row2.setSpacing(8)
        
        # Hires Steps 스핀박스
        hires_steps_label = QLabel("Hires Steps")
        hires_steps_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row2.addWidget(hires_steps_label)
        
        self.hires_steps_spinbox = QSpinBox()
        self.hires_steps_spinbox.setRange(0, 150)
        self.hires_steps_spinbox.setValue(0)  # 기본값 0 (use same as generation)
        self.hires_steps_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.hires_steps_spinbox.setFixedWidth(80)
        self.disable_wheel_event(self.hires_steps_spinbox)  # 마우스 휠 비활성화
        self.hires_option_layout_row2.addWidget(self.hires_steps_spinbox)
        
        # 구분선
        separator3 = QLabel("|")
        separator3.setStyleSheet(param_label_style)
        self.hires_option_layout_row2.addWidget(separator3)
        
        # Denoising Strength 스핀박스로 변경
        denoising_label = QLabel("Denoise")
        denoising_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row2.addWidget(denoising_label)
        
        # Denoising 스핀박스
        self.denoising_strength_spinbox = QDoubleSpinBox()
        self.denoising_strength_spinbox.setRange(0.0, 1.0)  # 0.0 ~ 1.0
        self.denoising_strength_spinbox.setSingleStep(0.01)  # 0.01 단위
        self.denoising_strength_spinbox.setDecimals(2)  # 소수점 2자리
        self.denoising_strength_spinbox.setValue(0.50)  # 기본값 0.5
        self.denoising_strength_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.denoising_strength_spinbox.setFixedWidth(80)
        self.disable_wheel_event(self.denoising_strength_spinbox)  # 마우스 휠 비활성화
        self.hires_option_layout_row2.addWidget(self.denoising_strength_spinbox)
        
        # 구분선
        separator4 = QLabel("|")
        separator4.setStyleSheet(param_label_style)
        self.hires_option_layout_row2.addWidget(separator4)
        
        # hr_cfg 스핀박스 추가
        hr_cfg_label = QLabel("hr CFG")
        hr_cfg_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row2.addWidget(hr_cfg_label)
        
        self.hr_cfg_spinbox = QDoubleSpinBox()
        self.hr_cfg_spinbox.setRange(0.0, 30.0)  # 0 ~ 30
        self.hr_cfg_spinbox.setSingleStep(0.1)  # 0.1 단위
        self.hr_cfg_spinbox.setDecimals(1)  # 소수점 1자리
        self.hr_cfg_spinbox.setValue(0.0)  # 기본값 0
        self.hr_cfg_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.hr_cfg_spinbox.setFixedWidth(80)
        self.disable_wheel_event(self.hr_cfg_spinbox)  # 마우스 휠 비활성화
        self.hires_option_layout_row2.addWidget(self.hr_cfg_spinbox)
        
        self.hires_option_layout_row2.addStretch()
        
        # 위젯에 두 행 추가
        self.hires_option_widget_layout.addLayout(self.hires_option_layout_row1)
        self.hires_option_widget_layout.addLayout(self.hires_option_layout_row2)
        
        # Comfyui
        self.comfyui_option_widget = QWidget()
        self.comfyui_option_widget_layout = QVBoxLayout(self.comfyui_option_widget)
        self.comfyui_option_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.comfyui_option_widget_layout.setSpacing(8)

        # ComfyUI 섹션 제목
        comfyui_section_label = QLabel("🎨 ComfyUI 옵션")
        comfyui_section_label.setStyleSheet(DARK_STYLES['label_style'].replace(f"font-size: {get_scaled_font_size(19)}px;", f"font-size: {get_scaled_font_size(18)}px; font-weight: 600;"))
        self.comfyui_option_widget_layout.addWidget(comfyui_section_label)

        # 샘플링 모드 선택 (라디오 버튼 그룹)
        sampling_mode_label = QLabel("샘플링 모드:")
        sampling_mode_label.setStyleSheet(DARK_STYLES['label_style'])
        self.comfyui_option_widget_layout.addWidget(sampling_mode_label)

        # 라디오 버튼 컨테이너
        sampling_mode_container = QWidget()
        sampling_mode_layout = QHBoxLayout(sampling_mode_container)
        sampling_mode_layout.setContentsMargins(0, 0, 0, 0)
        sampling_mode_layout.setSpacing(12)

        # EPS 라디오 버튼 (기본값)
        self.eps_radio = QRadioButton("EPS")
        self.eps_radio.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.eps_radio.setToolTip("기본 Epsilon 샘플링 모드 (CheckpointLoaderSimple 사용)")
        self.eps_radio.setChecked(True)

        # V-Pred 라디오 버튼
        self.v_pred_radio = QRadioButton("V-Pred")
        self.v_pred_radio.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.v_pred_radio.setToolTip("V-Prediction 샘플링 모드 (CheckpointLoaderSimple + ModelSamplingDiscrete)")

        # ANIMA 라디오 버튼
        self.anima_radio = QRadioButton("ANIMA")
        self.anima_radio.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.anima_radio.setToolTip("최신 ANIMA 모델 형식 (UNETLoader + CLIPLoader 사용)")

        # 버튼 그룹으로 묶기 (배타적 선택)
        self.sampling_mode_group = QButtonGroup(self)
        self.sampling_mode_group.addButton(self.eps_radio)
        self.sampling_mode_group.addButton(self.v_pred_radio)
        self.sampling_mode_group.addButton(self.anima_radio)

        sampling_mode_layout.addWidget(self.eps_radio)
        sampling_mode_layout.addWidget(self.v_pred_radio)
        sampling_mode_layout.addWidget(self.anima_radio)
        sampling_mode_layout.addStretch()

        # ANIMA 라디오 토글 시 Rescale CFG 가시성 제어
        self.sampling_mode_group.buttonClicked.connect(self._on_sampling_mode_changed)

        self.comfyui_option_widget_layout.addWidget(sampling_mode_container)

        # 1. 기존 라벨을 "워크플로우 선택"으로 재사용하고 활성화합니다.
        comfyui_workflow_label = QLabel("워크플로우 선택:")
        comfyui_workflow_label.setStyleSheet(DARK_STYLES['label_style'])
        comfyui_workflow_label.setEnabled(True)
        self.comfyui_option_widget_layout.addWidget(comfyui_workflow_label)

        # 2. 기존 QWidget과 QHBoxLayout을 버튼들을 담을 컨테이너로 재사용합니다.
        self.comfyui_workflow_section = QWidget()
        self.comfyui_workflow_section.setEnabled(True)
        comfyui_workflow_layout = QHBoxLayout(self.comfyui_workflow_section)
        comfyui_workflow_layout.setContentsMargins(0, 0, 0, 0)
        comfyui_workflow_layout.setSpacing(6)

        # 3. 토글 버튼들을 생성합니다. (클래스 멤버 변수로 선언해야 다른 메서드에서 접근 가능)
        self.workflow_default_btn = QPushButton("기본")
        self.workflow_default_btn.setCheckable(True)
        self.workflow_default_btn.setChecked(True)
        self.workflow_default_btn.setStyleSheet(DARK_STYLES['toggle_button'])

        self.workflow_custom_btn = QPushButton("커스텀")
        self.workflow_custom_btn.setCheckable(True)
        self.workflow_custom_btn.setEnabled(False) # 커스텀 워크플로우 로드 전까지 비활성화
        self.workflow_custom_btn.setStyleSheet(DARK_STYLES['toggle_button'])

        # 4. QButtonGroup으로 토글 버튼들을 그룹화하여 하나만 선택되도록 합니다.
        self.workflow_toggle_group = QButtonGroup(self)
        self.workflow_toggle_group.addButton(self.workflow_default_btn)
        self.workflow_toggle_group.addButton(self.workflow_custom_btn)
        self.workflow_toggle_group.setExclusive(True)

        # 5. '불러오기' 버튼을 생성합니다.
        self.workflow_load_btn = QPushButton("불러오기(이미지)")
        self.workflow_load_btn.setStyleSheet(DARK_STYLES['secondary_button'])

        # 6. 버튼들을 레이아웃에 추가합니다.
        comfyui_workflow_layout.addWidget(self.workflow_default_btn, 1)
        comfyui_workflow_layout.addWidget(self.workflow_custom_btn, 1)
        comfyui_workflow_layout.addWidget(self.workflow_load_btn, 1)
        
        # 7. 버튼 컨테이너 위젯을 최종적으로 부모 레이아웃에 추가합니다.
        self.comfyui_option_widget_layout.addWidget(self.comfyui_workflow_section)

        # 모드별 위젯 그룹 정리 (기존 코드 수정)
        self.naid_option_widgets = [
            self.option_section_label
        ] + list(self.advanced_checkboxes.values())

        self.hires_option_widgets = [
            self.hires_option_widget  # 전체 위젯 컨테이너만 포함
        ]

        # 🆕 ComfyUI 위젯 그룹 추가
        self.comfyui_option_widgets = [
            self.comfyui_option_widget  # 전체 ComfyUI 위젯 컨테이너
        ]

        # 기본적으로 NAI 모드로 시작 (다른 모드 위젯들 숨김)
        self.hires_option_widget.setVisible(False)
        self.comfyui_option_widget.setVisible(False)  # 🆕 ComfyUI 위젯도 기본 숨김

        # 레이아웃에 추가 (기존 코드에 ComfyUI 위젯 추가)
        params_layout.addLayout(self.naid_option_layout)
        params_layout.addWidget(self.hires_option_widget)
        params_layout.addWidget(self.comfyui_option_widget)  # 🆕 ComfyUI 위젯 추가
        
        # === Custom API 파라미터 섹션 ===
        custom_api_header = QHBoxLayout()
        custom_api_header.setSpacing(6)

        self.custom_api_checkbox = QCheckBox("Add custom/override api parameters")
        self.custom_api_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.custom_api_checkbox.toggled.connect(self.toggle_custom_api_params)
        custom_api_header.addWidget(self.custom_api_checkbox)

        # Detach 버튼 추가
        self.custom_api_detach_btn = QPushButton("🔓")
        self.custom_api_detach_btn.setToolTip("외부 창으로 분리")
        self.custom_api_detach_btn.setFixedSize(36, 24)
        self.custom_api_detach_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 4px;
            }}
            QPushButton:disabled {{
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.custom_api_detach_btn.clicked.connect(self.toggle_custom_api_detach)
        self.custom_api_detach_btn.setEnabled(False)  # 기본 비활성화 상태
        custom_api_header.addWidget(self.custom_api_detach_btn)

        custom_api_header.addStretch()
        params_layout.addLayout(custom_api_header)
        
        # Custom Script 텍스트박스 (기본적으로 숨김)
        self.custom_script_textbox = QTextEdit()
        self.custom_script_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.custom_script_textbox.setPlaceholderText("Custom API parameters (JSON format)...")
        self.custom_script_textbox.setFixedHeight(80)
        self.custom_script_textbox.setVisible(False)  # 기본적으로 숨김
        self.custom_script_textbox.setProperty("autocomplete_ignore", True)
        params_layout.addWidget(self.custom_script_textbox)
        
        container_layout.addWidget(self.params_area)
        
        # 3. 기존 생성 제어 프레임
        generation_control_frame = QFrame(container)
        generation_control_frame.setStyleSheet(DARK_STYLES['compact_card'])
        gen_control_layout = QVBoxLayout(generation_control_frame)
        gen_control_layout.setContentsMargins(12, 12, 12, 12)
        gen_control_layout.setSpacing(8)
        
        self.gen_button_layout = QHBoxLayout()
        self.gen_button_layout.setSpacing(6)
        
        self.random_prompt_btn = QPushButton("랜덤/다음 프롬프트")
        self.random_prompt_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.gen_button_layout.addWidget(self.random_prompt_btn)
        
        self.generate_button_main = QPushButton("🎨 이미지 생성 요청")
        self.generate_button_main.setStyleSheet(DARK_STYLES['primary_button'])
        self.gen_button_layout.addWidget(self.generate_button_main)
        
        gen_control_layout.addLayout(self.gen_button_layout)
        gen_control_layout.addSpacing(12)
        
        # 🔥 수정: 체크박스 레이아웃을 화면 너비에 맞춰 조정
        gen_checkbox_layout = QHBoxLayout()
        gen_checkbox_layout.setSpacing(12)
        
        self.generation_checkboxes = {}
        checkbox_texts = ["프롬프트 고정", "자동 생성", "터보 옵션", "와일드카드 단독 모드"]
        
        # 체크박스들을 균등하게 배치
        for i, cb_text in enumerate(checkbox_texts):
            cb = QCheckBox(cb_text)
            cb.setStyleSheet(DARK_STYLES['dark_checkbox'])
            gen_checkbox_layout.addWidget(cb, 1)  # stretch factor 1로 균등 배치
            self.generation_checkboxes[cb_text] = cb
            # 터보 옵션 체크박스 이벤트 연결
            if cb_text == "터보 옵션":
                cb.setEnabled(True)  # 활성화됨
                cb.clicked.connect(self.on_turbo_option_changed)

        # 오른쪽 여백을 위한 stretch (제거하지 않음)
        gen_checkbox_layout.addStretch()
        gen_control_layout.addLayout(gen_checkbox_layout)
        
        container_layout.addWidget(generation_control_frame)
        
        return container
    
    def on_turbo_option_changed(self, checked):
        """터보 옵션 체크박스 상태 변경 시 호출"""
        if checked:
            # 체크박스 자동 해제
            self.generation_checkboxes["터보 옵션"].setChecked(False)

            # 터보 모드 선택 다이얼로그 표시
            self._show_turbo_mode_dialog()

    def _show_turbo_mode_dialog(self):
        """터보 모드 선택 다이얼로그 표시"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton

        dialog = QDialog(self)
        dialog.setWindowTitle("🚀 터보 모드 선택")
        dialog.setFixedSize(350, 200)
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # 타이틀
        title = QLabel("터보 모드를 선택하세요")
        title.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 설명
        desc = QLabel("연속 이미지를 빠르게 생성할 수 있는 모드입니다.")
        desc.setStyleSheet(f"""
            font-size: 12px;
            color: {DARK_COLORS['text_secondary']};
        """)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addStretch()

        # 연속 이미지 생성 버튼
        inpaint_btn = QPushButton("🎬 연속 이미지 생성 (Inpaint)")
        inpaint_btn.setStyleSheet(DARK_STYLES['primary_button'])
        inpaint_btn.setFixedHeight(40)
        inpaint_btn.clicked.connect(lambda: self._on_turbo_mode_selected(dialog, 'inpaint'))
        layout.addWidget(inpaint_btn)

        # 취소 버튼
        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_btn.clicked.connect(dialog.reject)
        layout.addWidget(cancel_btn)

        dialog.exec()

    def _on_turbo_mode_selected(self, dialog, mode: str):
        """터보 모드 선택됨"""
        dialog.accept()

        if mode == 'inpaint':
            # TurboEventSequenceTabModule 동적 탭 생성
            if self.image_window and hasattr(self.image_window, 'tab_controller'):
                self.image_window.tab_controller.add_tab_by_name(
                    'TurboEventSequenceTabModule',
                    main_window=self
                )
                self.status_bar.showMessage("🚀 Turbo Sequence 탭이 생성되었습니다.")
    
    def on_turbo_preset_applied(self, preset):
        """터보 프리셋이 적용되었을 때 호출"""
        # 프리셋을 app_context에 저장하여 generation 시 사용
        if hasattr(self.app_context, 'turbo_preset'):
            self.app_context.turbo_preset = preset
        else:
            setattr(self.app_context, 'turbo_preset', preset)
        self.status_bar.showMessage("✅ 터보 프리셋이 적용되었습니다.")
    
    def toggle_params_panel(self):
        """생성 파라미터 패널 토글"""
        if self.params_expanded:
            # 축소
            self.params_area.setVisible(False)
            self.params_toggle_button.setText("▲ 생성 파라미터 열기")
            self.params_expanded = False
            self.status_bar.showMessage("생성 파라미터 패널이 축소되었습니다.")
        else:
            # 확장
            self.params_area.setVisible(True)
            self.params_toggle_button.setText("▼ 생성 파라미터 닫기")
            self.params_expanded = True
            self.status_bar.showMessage("생성 파라미터 패널이 확장되었습니다.")
    
    def toggle_custom_api_params(self, checked):
        """Custom API 파라미터 텍스트박스 토글"""
        # 분리된 상태가 아닐 때만 텍스트박스 가시성 토글
        self.custom_script_textbox.setVisible(checked and not self.custom_api_detached)
        # Detach 버튼은 항상 보이되, 체크박스가 켜질 때만 활성화
        self.custom_api_detach_btn.setEnabled(checked)
        if checked:
            self.status_bar.showMessage("Custom API 파라미터 입력이 활성화되었습니다.")
        else:
            self.status_bar.showMessage("Custom API 파라미터 입력이 비활성화되었습니다.")

    def toggle_custom_api_detach(self):
        """Custom API 텍스트박스 분리/복귀 토글"""
        if self.custom_api_detached:
            self.reattach_custom_api()
        else:
            self.detach_custom_api()

    def detach_custom_api(self):
        """Custom API 텍스트박스를 외부 창으로 분리"""
        if self.custom_api_detached:
            print("⚠️ Custom API 창이 이미 분리되어 있습니다.")
            return

        try:
            print("🔧 Custom API 창 분리 시작...")

            # 1. 텍스트박스를 레이아웃에서 분리
            self.params_area.layout().removeWidget(self.custom_script_textbox)
            self.custom_script_textbox.setParent(None)

            # 2. 래핑 위젯 생성 (확장된 UI)
            detached_widget = QWidget()
            detached_layout = QVBoxLayout(detached_widget)
            detached_layout.setContentsMargins(8, 8, 8, 8)

            # 분리된 창에서는 텍스트박스 크기 확장
            self.custom_script_textbox.setMinimumHeight(300)
            self.custom_script_textbox.setMaximumHeight(16777215)  # 최대 높이 제한 해제
            detached_layout.addWidget(self.custom_script_textbox)
            self.custom_script_textbox.setVisible(True)

            # 3. DetachedWindow 생성
            from ui.detached_window import DetachedWindow
            self.custom_api_window = DetachedWindow(
                detached_widget,
                "Custom API Parameters",
                -1,
                parent_container=self
            )
            self.custom_api_window.window_closed.connect(self.on_custom_api_window_closed)
            self.custom_api_window.setMinimumSize(400, 400)
            self.custom_api_window.resize(500, 450)
            self.custom_api_window.show()
            self.custom_api_window.raise_()
            self.custom_api_window.activateWindow()

            # 4. 상태 업데이트
            self.custom_api_detached = True
            self.custom_api_detach_btn.setText("🔒")
            self.custom_api_detach_btn.setToolTip("원래 위치로 복귀")

            print("✅ Custom API 창 분리 완료")

        except Exception as e:
            print(f"❌ Custom API 분리 실패: {e}")
            import traceback
            traceback.print_exc()

    def reattach_custom_api(self):
        """분리된 Custom API 창을 원래 위치로 복귀"""
        if not self.custom_api_detached:
            print("⚠️ Custom API 창이 분리되어 있지 않습니다.")
            return

        try:
            print("🔄 Custom API 창 복귀 시작...")

            # 1. 창에서 위젯 회수
            if self.custom_api_window:
                detached_widget = self.custom_api_window.get_original_widget()
                if detached_widget and detached_widget.layout():
                    # 텍스트박스 추출
                    detached_widget.layout().removeWidget(self.custom_script_textbox)
                self.custom_api_window.close()

            # 2. 원래 크기로 복원
            self.custom_script_textbox.setParent(None)
            self.custom_script_textbox.setFixedHeight(80)

            # 3. 원래 레이아웃에 추가
            self.params_area.layout().addWidget(self.custom_script_textbox)
            self.custom_script_textbox.setVisible(self.custom_api_checkbox.isChecked())

            # 4. 상태 업데이트
            self.custom_api_detached = False
            self.custom_api_window = None
            self.custom_api_detach_btn.setText("🔓")
            self.custom_api_detach_btn.setToolTip("외부 창으로 분리")

            print("✅ Custom API 창 복귀 완료")

        except Exception as e:
            print(f"❌ Custom API 복귀 실패: {e}")
            import traceback
            traceback.print_exc()

    def on_custom_api_window_closed(self, tab_index, widget):
        """Custom API 창이 닫힐 때 호출"""
        self.reattach_custom_api()

    def toggle_search_mode(self, mode):
        """NAI/WEBUI/COMFYUI 검색 모드 토글 (ComfyUI 지원 추가)"""
        if mode == "NAI":
            # NAI 모드 활성화
            self.nai_toggle_btn.setChecked(True)
            self.webui_toggle_btn.setChecked(False)
            self.comfyui_toggle_btn.setChecked(False)  # 🆕 추가
            
            # 스타일 적용
            self.nai_toggle_btn.setStyleSheet(self.toggle_active_style)
            self.webui_toggle_btn.setStyleSheet(self.toggle_inactive_style)
            self.comfyui_toggle_btn.setStyleSheet(self.toggle_inactive_style)  # 🆕 추가
            
            # UI 위젯 표시/숨김
            for widget in self.naid_option_widgets:
                widget.setVisible(True)
            for widget in self.hires_option_widgets:
                widget.setVisible(False)
            for widget in self.comfyui_option_widgets:  # 🆕 추가
                widget.setVisible(False)

            # NAI CFG Rescale 표시, ComfyUI Rescale CFG 숨김
            for w in self.nai_rescale_ui:
                w.setVisible(True)
            for w in self.comfyui_rescale_ui:
                w.setVisible(False)

            # 🆕 임시 창 자동 종료 체크
            old_mode = self._previous_api_mode
            if old_mode != mode:
                if not self.check_and_close_temp_windows("API 모드", old_mode, mode):
                    # 취소: 이전 모드로 롤백
                    print(f"🔄 [ModernMainWindow] API 모드 변경 취소: {old_mode}로 복귀")
                    self.toggle_search_mode(old_mode)
                    return
                self._previous_api_mode = mode

            self.status_bar.showMessage("NAI 모드로 전환되었습니다.")
            self.app_context.set_api_mode(mode)
            
            # NAI 모드로 전환 시 Anlas 업데이트
            self.update_anlas_display()
            
            # 토큰 카운트 업데이트
            self.update_token_count()
            
        elif mode == "WEBUI":
            # WEBUI 모드 선택 시 연결 테스트 수행 (기존 로직 유지)
            try:
                api_management = None
                tab_was_open = False
                
                if hasattr(self, 'image_window') and self.image_window:
                    # 이미 열린 API 관리 탭 찾기
                    for i in range(self.image_window.tab_widget.count()):
                        widget = self.image_window.tab_widget.widget(i)
                        if hasattr(widget, '__class__') and 'APIManagementWindow' in widget.__class__.__name__:
                            api_management = widget
                            tab_was_open = True
                            break
                    
                    # 스텔스 모드: API 관리 탭이 없으면 임시로 생성
                    if not api_management:
                        from tabs.api_management_window import APIManagementWindow
                        api_management = APIManagementWindow(self.app_context, self)
                    
                    if api_management and hasattr(api_management, 'webui_url_input'):
                        # 저장된 WEBUI URL 가져오기
                        if not tab_was_open:
                            webui_url = self.app_context.secure_token_manager.get_token('webui_url')
                        else:
                            webui_url = api_management.webui_url_input.text().strip()
                        
                        if not webui_url:
                            self.status_bar.showMessage("⚠️ WEBUI URL을 먼저 설정해주세요.", 5000)
                            self.open_search_management()
                            return
                        
                        # WebUI 연결 테스트
                        self.status_bar.showMessage("🔄 WEBUI 연결을 확인하는 중...", 3000)
                        validated_url = self.test_webui(webui_url)
                        
                        if validated_url:
                            # ✅ 연결 성공 시 WEBUI 모드로 전환
                            self.nai_toggle_btn.setChecked(False)
                            self.webui_toggle_btn.setChecked(True)
                            self.comfyui_toggle_btn.setChecked(False)  # 🆕 추가
                            
                            # 스타일 적용
                            self.nai_toggle_btn.setStyleSheet(self.toggle_inactive_style)
                            self.webui_toggle_btn.setStyleSheet(self.toggle_active_style)
                            self.comfyui_toggle_btn.setStyleSheet(self.toggle_inactive_style)  # 🆕 추가
                            
                            # UI 위젯 표시/숨김
                            for widget in self.naid_option_widgets:
                                widget.setVisible(False)
                            for widget in self.hires_option_widgets:
                                widget.setVisible(True)
                            for widget in self.comfyui_option_widgets:  # 🆕 추가
                                widget.setVisible(False)

                            # WEBUI: NAI/ComfyUI Rescale 둘 다 숨김
                            for w in self.nai_rescale_ui:
                                w.setVisible(False)
                            for w in self.comfyui_rescale_ui:
                                w.setVisible(False)

                            self.status_bar.showMessage(f"✅ WEBUI 모드로 전환되었습니다. ({validated_url})", 5000)

                            # 검증된 URL을 키링에 저장
                            clean_url = validated_url.replace('https://', '').replace('http://', '')
                            self.app_context.secure_token_manager.save_token('webui_url', clean_url)

                            # 🆕 임시 창 자동 종료 체크
                            old_mode = self._previous_api_mode
                            if old_mode != mode:
                                if not self.check_and_close_temp_windows("API 모드", old_mode, mode):
                                    # 취소: 이전 모드로 롤백
                                    print(f"🔄 [ModernMainWindow] API 모드 변경 취소: {old_mode}로 복귀")
                                    self.toggle_search_mode(old_mode)
                                    return
                                self._previous_api_mode = mode

                            self.app_context.set_api_mode(mode)
                            
                            # 토큰 카운트 업데이트
                            self.update_token_count()
                            
                            # URL 정규화 (스마트 프로토콜 선택)
                            normalized_url = validated_url.replace('https://', '').replace('http://', '')
                            if normalized_url.startswith("127"):
                                normalized_url = f"http://{normalized_url}"
                            else:
                                normalized_url = f"https://{normalized_url}"

                            # ✅ WEBUI 웹뷰 탭 열기
                            if self.image_window and hasattr(self.image_window, 'tab_controller'):
                                self.image_window.tab_controller.add_tab_by_name(
                                    'SimpleWebViewTabModule',
                                    api_url=normalized_url,
                                    api_mode='WEBUI',
                                    app_context=self.app_context
                                )
                            
                        else:
                            # ❌ 연결 실패 시에만 API 관리 창으로 이동
                            self.status_bar.showMessage(f"❌ WEBUI 연결 실패: {webui_url}", 5000)
                            if not tab_was_open:
                                self.open_search_management()
                            
                            # 오류 메시지 표시
                            from PyQt6.QtWidgets import QMessageBox
                            QMessageBox.critical(
                                self, 
                                "WEBUI 연결 실패", 
                                f"WebUI 서버에 연결할 수 없습니다.\n\n"
                                f"확인할 사항:\n"
                                f"• WebUI가 실행 중인지 확인\n"
                                f"• 주소가 올바른지 확인: {webui_url}\n"
                                f"• API 접근이 활성화되어 있는지 확인\n\n"
                                f"API 관리 탭에서 올바른 주소를 입력해주세요."
                            )
                    else:
                        self.status_bar.showMessage("⚠️ API 관리 기능을 사용할 수 없습니다.", 5000)
                        self.open_search_management()
                        
            except Exception as e:
                print(f"❌ WEBUI 모드 전환 중 오류: {e}")
                self.status_bar.showMessage(f"❌ WEBUI 모드 전환 실패: {str(e)}", 5000)
                self.open_search_management()
        
        elif mode == "COMFYUI":  # 🆕 ComfyUI 모드 - 동적 로딩 추가
            # ComfyUI 모드 선택 시 연결 테스트 및 동적 옵션 로드
            try:
                api_management = None
                tab_was_open = False
                
                if hasattr(self, 'image_window') and self.image_window:
                    # 이미 열린 API 관리 탭 찾기
                    for i in range(self.image_window.tab_widget.count()):
                        widget = self.image_window.tab_widget.widget(i)
                        if hasattr(widget, '__class__') and 'APIManagementWindow' in widget.__class__.__name__:
                            api_management = widget
                            tab_was_open = True
                            break
                    
                    # 스텔스 모드: API 관리 탭이 없으면 임시로 생성
                    if not api_management:
                        from tabs.api_management_window import APIManagementWindow
                        api_management = APIManagementWindow(self.app_context, self)
                    
                    if api_management and hasattr(api_management, 'comfyui_url_input'):
                        # 저장된 ComfyUI URL 가져오기
                        if not tab_was_open:
                            comfyui_url = self.app_context.secure_token_manager.get_token('comfyui_url')
                        else:
                            comfyui_url = api_management.comfyui_url_input.text().strip()
                        
                        if not comfyui_url:
                            self.status_bar.showMessage("⚠️ ComfyUI URL을 먼저 설정해주세요.", 5000)
                            self.open_search_management()
                            return
                        
                        # ComfyUI 연결 테스트
                        self.status_bar.showMessage("🔄 ComfyUI 연결을 확인하는 중...", 3000)
                        validated_url = self.test_comfyui(comfyui_url)
                        
                        if validated_url:
                            # ✅ 연결 성공 시 ComfyUI 모드로 전환
                            self.nai_toggle_btn.setChecked(False)
                            self.webui_toggle_btn.setChecked(False)
                            self.comfyui_toggle_btn.setChecked(True)
                            
                            # 스타일 적용
                            self.nai_toggle_btn.setStyleSheet(self.toggle_inactive_style)
                            self.webui_toggle_btn.setStyleSheet(self.toggle_inactive_style)
                            self.comfyui_toggle_btn.setStyleSheet(self.toggle_active_style)
                            
                            # UI 위젯 표시/숨김
                            for widget in self.naid_option_widgets:
                                widget.setVisible(False)
                            for widget in self.hires_option_widgets:
                                widget.setVisible(False)
                            for widget in self.comfyui_option_widgets:
                                widget.setVisible(True)

                            # ComfyUI: NAI Rescale 숨김, ComfyUI Rescale은 ANIMA 선택 시만 표시
                            for w in self.nai_rescale_ui:
                                w.setVisible(False)
                            is_anima = hasattr(self, 'anima_radio') and self.anima_radio.isChecked()
                            for w in self.comfyui_rescale_ui:
                                w.setVisible(is_anima)

                            self.status_bar.showMessage(f"✅ ComfyUI 모드로 전환되었습니다. ({comfyui_url})", 5000)

                            # 검증된 URL을 키링에 저장
                            self.app_context.secure_token_manager.save_token('comfyui_url', comfyui_url)

                            # 🆕 임시 창 자동 종료 체크
                            old_mode = self._previous_api_mode
                            if old_mode != mode:
                                if not self.check_and_close_temp_windows("API 모드", old_mode, mode):
                                    # 취소: 이전 모드로 롤백
                                    print(f"🔄 [ModernMainWindow] API 모드 변경 취소: {old_mode}로 복귀")
                                    self.toggle_search_mode(old_mode)
                                    return
                                self._previous_api_mode = mode

                            self.app_context.set_api_mode(mode)
                            
                            # 토큰 카운트 업데이트1
                            self.update_token_count()
                            
                            # URL 정규화 (http:// 중복 방지)
                            normalized_url = comfyui_url
                            if not normalized_url.startswith(("http://", "https://")):
                                normalized_url = f"http://{normalized_url}"
                            elif normalized_url.startswith("http://http://"):
                                normalized_url = normalized_url.replace("http://http://", "http://")
                            elif normalized_url.startswith("https://http://"):
                                normalized_url = normalized_url.replace("https://http://", "http://")
                            elif normalized_url.startswith("http://https://"):
                                normalized_url = normalized_url.replace("http://https://", "https://")
                            
                            # ✅ ComfyUI 웹뷰 탭 열기
                            # if self.image_window and hasattr(self.image_window, 'tab_controller'):
                            #     self.image_window.tab_controller.add_tab_by_name(
                            #         'SimpleWebViewTabModule',
                            #         api_url=normalized_url,
                            #         api_mode='COMFYUI'
                            #     )

                        else:
                            # ❌ 연결 실패
                            self.status_bar.showMessage(f"❌ ComfyUI 연결 실패: {comfyui_url}", 5000)
                            if not tab_was_open:
                                self.open_search_management()
                            
                            # 오류 메시지 표시
                            from PyQt6.QtWidgets import QMessageBox
                            QMessageBox.critical(
                                self, 
                                "ComfyUI 연결 실패", 
                                f"ComfyUI 서버에 연결할 수 없습니다.\n\n"
                                f"확인할 사항:\n"
                                f"• ComfyUI가 실행 중인지 확인\n"
                                f"• 주소가 올바른지 확인: {comfyui_url}\n"
                                f"• 포트 번호가 정확한지 확인 (기본: 8188)\n\n"
                                f"API 관리 탭에서 올바른 주소를 입력해주세요."
                            )
                    else:
                        self.status_bar.showMessage("⚠️ API 관리 기능을 사용할 수 없습니다.", 5000)
                        self.open_search_management()
                        
            except Exception as e:
                print(f"❌ ComfyUI 모드 전환 중 오류: {e}")
                self.status_bar.showMessage(f"❌ ComfyUI 모드 전환 실패: {str(e)}", 5000)
                self.open_search_management()

    def open_search_management(self):
        # ✅ RightView의 tab_controller를 통해 동적 탭 생성을 요청
        if self.image_window and hasattr(self.image_window, 'tab_controller'):
            self.image_window.tab_controller.add_tab_by_name(
                'APIManagementTabModule' # ◀ 모듈의 클래스 이름을 문자열로 전달
            )
            self.status_bar.showMessage("⚙️ API 관리 탭으로 이동했습니다.", 3000)
        else:
            self.status_bar.showMessage("⚠️ API 관리 탭을 열 수 없습니다.", 5000)

    def update_anlas_display(self):
        """NAI 모드에서 Anlas 값을 업데이트하여 CollapsibleBox 제목에 표시합니다."""
        if not hasattr(self, 'search_collapsible_box'):
            return
        
        # NAI 모드일 때만 Anlas 표시
        if self.app_context.current_api_mode == "NAI":
            anlas = self.app_context.api_service.get_anlas()
            self.search_collapsible_box.update_anlas(anlas)
        else:
            self.search_collapsible_box.update_anlas(None)

    def create_right_panel(self):
       # [수정] 생성자에 main_window 참조를 전달합니다.
       right_view_instance = RightView(self.app_context)
       return right_view_instance

    def get_dark_style(self, style_key: str) -> str:
        return DARK_STYLES.get(style_key, '')
    
    def get_dark_color(self, color_key: str) -> str:
        return DARK_COLORS.get(color_key, '#FFFFFF')



    def set_positive_prompt(self, prompt: str):
        """전달받은 프롬프트를 메인 UI의 프롬프트 입력창에 설정합니다."""
        self.main_prompt_textedit.setPlainText(prompt)
        print(f"📋 프롬프트 불러오기 완료.")
        self.status_bar.showMessage("프롬프트가 성공적으로 로드되었습니다.", 3000)
    
    def update_naid_checkbox_colors(self, model_text: str = None):
        """모델 선택에 따라 NAID 체크박스 색상을 업데이트합니다."""
        if model_text is None or model_text == "":
            model_text = self.model_combo.currentText()
        
        # NAID3일 때는 모든 체크박스 흰색, 그 외에는 SMEA, DYN, DECRISP를 회색으로
        is_naid3 = (model_text == "NAID3")
        
        for option_name, checkbox in self.advanced_checkboxes.items():
            if is_naid3:
                # NAID3: 모든 체크박스 흰색
                checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
            else:
                # 다른 모델: VAR+만 흰색, 나머지는 회색
                if option_name == "VAR+":
                    checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
                else:
                    # SMEA, DYN, DECRISP는 회색으로
                    gray_style = DARK_STYLES['dark_checkbox'].replace(
                        f"color: {DARK_COLORS['text_primary']}", 
                        f"color: {DARK_COLORS['text_secondary']}"
                    )
                    checkbox.setStyleSheet(gray_style)

    def get_main_parameters(self) -> dict:
        """메인 UI의 파라미터들을 수집하여 딕셔너리로 반환합니다."""
        params = {}
        try:
            # 해상도 파싱 - 공백 처리 개선
            resolution_text = self.resolution_combo.currentText()
            if " x " in resolution_text:
                width_str, height_str = resolution_text.split(" x ")
                width, height = int(width_str.strip()), int(height_str.strip())
            else:
                # 기본값 설정
                width, height = 1024, 1024
            
            # 시드 처리
            if self.seed_fix_checkbox.isChecked():
                try:
                    seed_value = int(self.seed_input.text())
                except ValueError:
                    seed_value = -1
            else:
                seed_value = random.randint(0, 9999999999)
                self.seed_input.setText(str(seed_value))

            # 프롬프트 처리 (쉼표 기준 정리)
            processed_input = ', '.join([item.strip() for item in self.main_prompt_textedit.toPlainText().split(',') if item.strip()])
            processed_negative_prompt = ', '.join([item.strip() for item in self.negative_prompt_textedit.toPlainText().split(',') if item.strip()])

            # 🔧 기존 구조 유지: 실제 위젯 이름에 맞게 파라미터 수집
            params = {
                "action": "generate",
                "access_token": "",
                "input": processed_input,
                "negative_prompt": processed_negative_prompt,
                "model": self.model_combo.currentText(),
                "scheduler": self.scheduler_combo.currentText(),
                "sampler": self.sampler_combo.currentText(),
                "resolution": self.resolution_combo.currentText(),  # UI 표시용
                "width": width,
                "height": height,
                "seed": seed_value,
                "random_resolution": self.random_resolution_checkbox.isChecked(),
                "steps": self.steps_spinbox.value(),
                "cfg_scale": self.cfg_scale_slider.value() / 10.0,  # 슬라이더 값(10~300) → 실제 값(1.0~30.0)
                "cfg_rescale": self.cfg_rescale_slider.value() / 100.0,  # 슬라이더 값(0~100) → 실제 값(0.0~1.0)
                
                # 고급 체크박스들 (딕셔너리에서 직접 접근)
                "SMEA": self.advanced_checkboxes["SMEA"].isChecked(),
                "DYN": self.advanced_checkboxes["DYN"].isChecked(),
                "VAR+": self.advanced_checkboxes["VAR+"].isChecked(),
                "DECRISP": self.advanced_checkboxes["DECRISP"].isChecked(),
                
                # 커스텀 API 파라미터
                "use_custom_api_params": self.custom_api_checkbox.isChecked(),
                "custom_api_params": self.custom_script_textbox.toPlainText()
            }
            
            # 🆕 추가: WEBUI 전용 파라미터들 (해당 모드일 때만)
            if hasattr(self, 'enable_hr_checkbox'):
                params.update({
                    "enable_hr": self.enable_hr_checkbox.isChecked(),
                    "hr_scale": self.hr_scale_spinbox.value() if hasattr(self, 'hr_scale_spinbox') else 1.5,
                    "hr_upscaler": self.hr_upscaler_combo.currentText() if hasattr(self, 'hr_upscaler_combo') else "Lanczos",
                    "denoising_strength": self.denoising_strength_spinbox.value() if hasattr(self, 'denoising_strength_spinbox') else 0.5,
                    "hires_steps": self.hires_steps_spinbox.value() if hasattr(self, 'hires_steps_spinbox') else 0
                })
                
                # WEBUI 모드에서 hr_cfg 추가
                if self.get_current_api_mode() == "WEBUI" and hasattr(self, 'hr_cfg_spinbox'):
                    params["hr_cfg"] = self.hr_cfg_spinbox.value()
                
            # 🆕 추가: ComfyUI 전용 파라미터들 (현재 모드가 ComfyUI일 때만)
            current_mode = self.get_current_api_mode()
            if current_mode == "COMFYUI":
                if hasattr(self, 'eps_radio') and hasattr(self, 'v_pred_radio') and hasattr(self, 'anima_radio'):
                    # 선택된 샘플링 모드 확인
                    if self.eps_radio.isChecked():
                        sampling_mode = "eps"
                        workflow_type = "checkpoint"
                    elif self.v_pred_radio.isChecked():
                        sampling_mode = "v_prediction"
                        workflow_type = "checkpoint"
                    elif self.anima_radio.isChecked():
                        sampling_mode = "anima"
                        workflow_type = "unet"
                    else:
                        # 기본값
                        sampling_mode = "eps"
                        workflow_type = "checkpoint"

                    params.update({
                        "sampling_mode": sampling_mode,
                        "workflow_type": workflow_type,  # checkpoint 또는 unet
                        "filename_prefix": "NAIA_ComfyUI"  # 기본 파일명 접두사
                    })

                    # ANIMA 모드: Rescale CFG 값 추가
                    if workflow_type == "unet" and hasattr(self, 'comfyui_rescale_slider'):
                        params["rescale_cfg"] = self.comfyui_rescale_slider.value() / 100.0

                    # 디버그 정보
                    print(f"🎨 ComfyUI 파라미터 수집 완료:")
                    print(f"   - 샘플링 모드: {params['sampling_mode']}")
                    print(f"   - 워크플로우 타입: {params['workflow_type']}")
                    if 'rescale_cfg' in params:
                        print(f"   - Rescale CFG: {params['rescale_cfg']}")
                    print(f"   - 해상도: {params['width']}x{params['height']}")
                    print(f"   - 스텝: {params['steps']}, CFG: {params['cfg_scale']}")
                else:
                    # ComfyUI 위젯이 아직 초기화되지 않은 경우 기본값 사용
                    params.update({
                        "sampling_mode": "eps",
                        "workflow_type": "checkpoint",
                        "filename_prefix": "NAIA_ComfyUI"
                    })
                    print("⚠️ ComfyUI 위젯이 초기화되지 않아 기본값을 사용합니다.")

            # 🆕 추가: 자동 해상도 맞춤 옵션 (모든 모드 공통)
            if hasattr(self, 'auto_fit_resolution_checkbox'):
                params["auto_fit_resolution"] = self.auto_fit_resolution_checkbox.isChecked()
                    
        except (ValueError, KeyError, AttributeError) as e:
            print(f"❌ 파라미터 수집 오류: {e}")
            # 오류 발생 시 사용자에게 알림
            self.status_bar.showMessage(f"⚠️ 생성 파라미터 값에 오류가 있습니다: {e}", 5000)
            return {}  # 빈 딕셔너리 반환

        return params

    # update_ui_with_result 메서드 수정
    def update_ui_with_result(self, result: dict):
        """APIService의 결과를 받아 UI에 업데이트하고 히스토리에 추가"""
        try:
            if not self.image_window:
                print("❌ image_window가 None입니다.")
                return
                
            image_object = result.get("image")
            info_text = result.get("info", "")
            source_row = result.get("source_row")
            raw_bytes = result.get("raw_bytes")

            if image_object is None:
                print("❌ image_object가 None입니다.")
                return
            try:
                # 특수 요청 여부 확인
                generation_params = result.get("generation_params", {})
                is_assets_request = generation_params.get("assets_workshop_request", False)
                is_artist_thumb_request = generation_params.get("artist_thumb_request", False)
                is_studio_request = generation_params.get("studio_request", False)
                studio_frame_index = generation_params.get("studio_frame_index", 0)
                
                self.image_window.update_image(image_object)
                
                # Interactive Mode 요청인 경우 별도 이벤트 발행
                is_interactive_request = generation_params.get("interactive_mode_request", False)
                if is_interactive_request:
                    print("🎮 Interactive Mode 요청 감지 - 전용 이벤트 발행")
                    # AppContext를 통해 이벤트 발행
                    if hasattr(self, 'app_context') and self.app_context:
                        self.app_context.publish("generation_completed_for_interactive", image_object)

                # Assets Workshop 요청인 경우 별도 이벤트 발행
                if is_assets_request:
                    print("📦 Assets Workshop 요청 감지 - 전용 이벤트 발행")
                    # AppContext를 통해 이벤트 발행
                    if hasattr(self, 'app_context') and self.app_context:
                        self.app_context.publish("generation_completed_for_assets", image_object)

                # Artist Thumb 요청인 경우 별도 이벤트 발행
                if is_artist_thumb_request:
                    print("🎨 Artist Thumb 요청 감지 - 전용 이벤트 발행")
                    # AppContext를 통해 이벤트 발행
                    if hasattr(self, 'app_context') and self.app_context:
                        self.app_context.publish("generation_completed_for_artist_thumb", image_object)

                # Event Preset 요청인 경우 별도 이벤트 발행
                is_event_preset_request = generation_params.get("event_preset_request", False)
                if is_event_preset_request:
                    print("📋 Event Preset 요청 감지 - 전용 이벤트 발행")
                    if hasattr(self, 'app_context') and self.app_context:
                        self.app_context.publish("generation_completed_for_event_preset", image_object)

                # Studio 요청인 경우 별도 이벤트 발행
                if is_studio_request:
                    print(f"🎬 Studio 요청 감지 - 전용 이벤트 발행 (frame: {studio_frame_index})")
                    if hasattr(self, 'app_context') and self.app_context:
                        studio_seed = generation_params.get("seed", -1)
                        self.app_context.publish("generation_completed_for_studio", {
                            "image": image_object,
                            "frame_index": studio_frame_index,
                            "seed": studio_seed
                        })

                # Turbo Sequence 요청인 경우 별도 이벤트 발행
                is_turbo_sequence_request = generation_params.get("turbo_sequence_request", False)
                turbo_sequence_index = generation_params.get("turbo_sequence_index", 0)
                if is_turbo_sequence_request:
                    print(f"🚀 Turbo Sequence 요청 감지 - 전용 이벤트 발행 (index: {turbo_sequence_index})")
                    if hasattr(self, 'app_context') and self.app_context:
                        # 🆕 인페인트 다이얼로그 식별자도 포함
                        event_data = {
                            "image": image_object,
                            "turbo_sequence_request": True,
                            "turbo_sequence_index": turbo_sequence_index
                        }
                        # 인페인트 다이얼로그에서 온 요청인 경우 식별자 추가
                        if generation_params.get("sequence_inpaint_dialog"):
                            event_data["sequence_inpaint_dialog"] = True
                            event_data["sequence_inpaint_request_id"] = generation_params.get("sequence_inpaint_request_id")
                        self.app_context.publish("generation_completed", event_data)

                # Img2Img Batch 요청인 경우 다음 생성 트리거
                is_img2img_batch_request = generation_params.get("img2img_batch_request", False)
                if is_img2img_batch_request and hasattr(self, 'img2img_window_manager'):
                    img2img_batch_window_id = generation_params.get("img2img_batch_window_id", -1)
                    print(f"🔄 Img2Img Batch 완료 감지 (window #{img2img_batch_window_id})")
                    self.img2img_window_manager.on_batch_generation_completed(img2img_batch_window_id)

                # Main Window → Assets 자동 전파 (추후 제거 가능)
                # 📝 참고: 사용자 혼란 방지를 위해 필요시 아래 라인들을 주석처리하여 비활성화 가능
                if not is_assets_request:
                    self.image_window.update_assets_image(image_object)  # ← 이 라인을 주석처리하면 전파 차단
                    
            except Exception as e:
                print(f"❌ 이미지 업데이트 실패: {e}")
                return
                
            # 정보 업데이트
            try:
                self.image_window.update_info(info_text)
            except Exception as e:
                print(f"❌ 정보 업데이트 실패: {e}")
                
            # 히스토리 추가
            try:
                print(f"  - image_object type: {type(image_object)}")
                print(f"  - raw_bytes type: {type(raw_bytes)}, length: {len(raw_bytes) if raw_bytes else 'None'}")
                print(f"  - info_text type: {type(info_text)}, length: {len(info_text) if info_text else 'None'}")
                print(f"  - source_row type: {type(source_row)}")
                
                # 🆕 확장된 메타데이터와 함께 히스토리 추가
                self.image_window.add_to_history(
                    image_object, 
                    raw_bytes, 
                    info_text, 
                    source_row,
                    generation_result=result  # 🆕 전체 결과 객체 전달
                )
            except Exception as e:
                print(f"❌ 히스토리 추가 실패: {e}")
                import traceback
                traceback.print_exc()
            
            self.status_bar.showMessage("🎉 생성 완료!")
            
            # 자동화 모듈 처리 (안전하게)
            if self.automation_module:
                try:
                    should_proceed_to_next = self.automation_module.notify_generation_completed()
                    if should_proceed_to_next is False:
                        return
                except Exception as e:
                    print(f"❌ 자동화 모듈 notify_generation_completed 실패: {e}")
                    return

            # 자동 생성 체크
            try:
                # 자동 생성이 활성화되어 있고, 자동화가 실행 중일 때만 지연시간 적용
                auto_generate_checkbox = self.generation_checkboxes.get("자동 생성")
                if (auto_generate_checkbox and auto_generate_checkbox.isChecked() and 
                    self.automation_module and self.automation_module.automation_controller.is_running):
                    delay = self.automation_module.get_generation_delay()
                    if delay > 0:
                        print(f"⏱️ 생성 지연: {delay:.1f}초")
                        # 카운트다운 스레드를 사용하여 지연 시각화
                        if hasattr(self.automation_module, 'start_delay_countdown'):
                            # 카운트다운 완료 시 자동 생성 트리거를 연결
                            self.automation_module.countdown_thread = None  # 기존 연결 해제를 위해 초기화
                            self.automation_module.start_delay_countdown_for_new_prompt(delay)
                        else:
                            # 폴백: 기존 방식 사용
                            if hasattr(self.automation_module, 'delay_info_label') and self.automation_module.delay_info_label:
                                self.automation_module.delay_info_label.setText(f"⏱️ 지연: {delay:.1f}초 후 다음 생성")
                            from PyQt6.QtCore import QTimer
                            QTimer.singleShot(int(delay * 1000), self._check_and_trigger_auto_generation)
                    else:
                        if hasattr(self.automation_module, 'delay_info_label') and self.automation_module.delay_info_label:
                            self.automation_module.delay_info_label.setText("⚡ 지연 없음")
                        self._check_and_trigger_auto_generation()
                else:
                    # 자동화가 비활성화된 경우 지연 없이 즉시 실행
                    if self.automation_module and hasattr(self.automation_module, 'delay_info_label') and self.automation_module.delay_info_label:
                        self.automation_module.delay_info_label.setText("")
                    self._check_and_trigger_auto_generation()
            except Exception as e:
                print(f"❌ 자동 생성 체크 실패: {e}")

            # 🆕 Autosave: 특수 요청이 아닌 일반 생성 완료 시에만 자동 저장
            try:
                generation_params = result.get("generation_params", {})
                is_special_request = (
                    generation_params.get("assets_workshop_request", False) or
                    generation_params.get("artist_thumb_request", False) or
                    generation_params.get("studio_request", False) or
                    generation_params.get("interactive_mode_request", False) or
                    generation_params.get("event_preset_request", False) or
                    generation_params.get("turbo_sequence_request", False) or
                    generation_params.get("img2img_batch_request", False)
                )

                if not is_special_request:
                    self._perform_autosave_on_generation()
            except Exception as e:
                # 자동 저장 실패해도 프로그램은 계속 동작
                print(f"⚠️ [Autosave] 트리거 실패: {e}")

        except Exception as e:
            print(f"❌ update_ui_with_result 전체 에러: {e}")
            import traceback
            traceback.print_exc()
            self.status_bar.showMessage(f"❌ 결과 처리 오류: {e}")

    def _check_and_trigger_auto_generation(self):
        """자동 생성 조건을 확인하고 조건이 만족되면 다음 사이클을 시작합니다."""
        # 조건 확인: "자동 생성"이 체크되어 있고 "프롬프트 고정"이 체크되어 있지 않음
        auto_generate_checkbox = self.generation_checkboxes.get("자동 생성")
        prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")
        
        if not auto_generate_checkbox.isChecked():
            return  # 자동 생성 체크박스가 없으면 종료

        try:
            # [큐 우선] 큐가 비어있지 않으면 큐 처리가 끝날 때까지 자동생성 대기
            if hasattr(self, 'app_context') and self.app_context:
                queue_manager = self.app_context.generation_queue_manager
                if queue_manager and not queue_manager.is_empty() and not queue_manager.is_paused():
                    self.status_bar.showMessage("큐 처리 중... 자동생성 대기")
                    QTimer.singleShot(500, self._check_and_trigger_auto_generation)
                    return

            if (hasattr(self, 'generation_controller') and
                self.generation_controller.is_generating):
                print("🔄 이미지 생성 중이므로 자동 생성 건너뜀")
                # 약간의 지연 후 다시 시도
                QTimer.singleShot(800, self._check_and_trigger_auto_generation)
                return
                
            # [추가] 스레드 상태 확인
            if (hasattr(self, 'generation_controller') and 
                self.generation_controller.generation_thread and 
                self.generation_controller.generation_thread.isRunning()):
                print("🔄 이전 스레드가 아직 실행 중이므로 잠시 대기...")
                QTimer.singleShot(200, self._check_and_trigger_auto_generation)
                return

            # [신규] 반복 생성 중인지 확인 - 반복 중이면 자동 생성 건너뛰기
            if (self.automation_module and
                hasattr(self.automation_module, 'current_repeat_count') and
                self.automation_module.current_repeat_count > 0):
                print(f"🔁 반복 생성 중이므로 자동 생성 건너뜀 (현재 반복: {self.automation_module.current_repeat_count})")
                return

            # Img2Img 배치 반복 생성 중이면 자동 생성 건너뛰기
            if (hasattr(self, 'img2img_window_manager') and
                self.img2img_window_manager.is_any_batch_running()):
                print("🔄 Img2Img 배치 생성 중이므로 자동 생성 건너뜀")
                return

            # [신규] 중복 실행 방지 - 시간 기반 체크
            import time
            current_time = time.time()
            # if self.auto_generation_in_progress or (current_time - self.last_auto_generation_time) < 1.0:
            #     print(f"⚠️ 자동 생성 중복 방지: in_progress={self.auto_generation_in_progress}, time_diff={current_time - self.last_auto_generation_time:.2f}s")
            #     return
                
            if auto_generate_checkbox.isChecked() and not prompt_fixed_checkbox.isChecked():
                # 검색 결과가 있는지 확인
                if self.search_results.is_empty() and not self.generation_checkboxes["와일드카드 단독 모드"].isChecked():
                    self.status_bar.showMessage("⚠️ 검색 결과가 없어 자동 생성을 중단합니다.")
                    # 자동화 중단 (자동화가 활성화되어 있는 경우만)
                    if self.automation_module and self.automation_module.automation_controller.is_running:
                        self.automation_module.stop_automation()
                    return
                
                # [신규] 자동 생성 플래그 설정
                self.auto_generation_in_progress = True
                self.last_auto_generation_time = current_time
                self.status_bar.showMessage("🔄 자동 생성: 다음 프롬프트 생성 중...")
                
                # 다음 프롬프트 생성 요청
                # 🔧 ComfyUI 샘플링 모드 감지 (라디오 버튼에서 직접 읽기)
                comfyui_sampling_mode = "eps"  # 기본값
                if hasattr(self, 'anima_radio') and self.anima_radio.isChecked():
                    comfyui_sampling_mode = "anima"
                elif hasattr(self, 'v_pred_radio') and self.v_pred_radio.isChecked():
                    comfyui_sampling_mode = "v_prediction"
                elif hasattr(self, 'eps_radio') and self.eps_radio.isChecked():
                    comfyui_sampling_mode = "eps"

                settings = {
                    'prompt_fixed': False,
                    'auto_generate': True,
                    'turbo_mode': self.generation_checkboxes["터보 옵션"].isChecked(),
                    'wildcard_standalone': self.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
                    "auto_fit_resolution": self.auto_fit_resolution_checkbox.isChecked(),
                    'api_mode': self.app_context.get_api_mode(),  # 🆕 ANIMA 모드 감지를 위해 추가
                    'comfyui_sampling_mode': comfyui_sampling_mode  # 🔧 라디오 버튼에서 직접 읽기
                }
                
                # 프롬프트 생성 컨트롤러에 자동 생성 플래그 설정
                self.prompt_gen_controller.auto_generation_requested = True

                #1009 변경사항 -> hooker와 호환되지 않는 NAI 캐릭터 프롬프트 처리 위치 변경
                char_module = self.middle_section_controller.get_module_instance("CharacterModule")
                if (char_module and 
                    hasattr(char_module, 'is_auto_mode_active') and 
                    char_module.is_auto_mode_active()):
                    
                    # 자동 생성 모드에서 이미지 생성 트리거
                    self._trigger_auto_image_generation()

                if (char_module and
                    char_module.activate_checkbox.isChecked() and
                    not char_module.reroll_on_generate_checkbox.isChecked()):

                    print("🔄️ 자동 생성: 캐릭터 와일드카드를 갱신합니다.")
                    char_module.process_and_update_view()

                # 프리셋 랜더마이저 신호 발행 (자동 생성 시 랜덤 프리셋 적용)
                self.app_context.publish("random_prompt_triggered_preset_randomizer")

                self.prompt_gen_controller.generate_next_prompt(self.search_results, settings)
            elif auto_generate_checkbox.isChecked() and prompt_fixed_checkbox.isChecked():
                self.auto_generation_in_progress = True
                self.last_auto_generation_time = current_time
                self.status_bar.showMessage("🔄 자동 생성: 프롬프트 고정이 체크되어 있어 생성 단계로 넘어갑니다...")
                self._trigger_auto_image_generation()
                
        except Exception as e:
            # [신규] 오류 시 플래그 해제
            self.auto_generation_in_progress = False
            self.status_bar.showMessage(f"❌ 자동 생성 체크 오류: {e}")
            print(f"자동 생성 체크 오류: {e}")

    # [신규] 자동화 활성 상태 확인 메서드 추가
    def get_automation_active_status(self) -> bool:
        """현재 자동화가 활성화되어 있는지 확인"""
        try:
            if self.automation_module and self.automation_module.automation_controller:
                return self.automation_module.automation_controller.is_running
            return False
        except Exception as e:
            print(f"⚠️ 자동화 활성 상태 확인 실패: {e}")
            return False


    def trigger_search(self):
        """'검색' 버튼 클릭 시 컨트롤러를 통해 검색을 시작하는 슬롯"""
        self.search_btn.setEnabled(False)
        self.search_btn.setText("검색 중...")

        # [수정] 새 검색 시작 시 진행률 레이블을 다시 표시
        self.progress_label.setText("0/0") # 초기 텍스트 설정
        self.progress_label.setVisible(True)

        # [신규] 새 검색 시작 시 기존 결과 초기화
        self.search_results = SearchResultModel()
        self.result_label1.setText("검색: 0")

        # 🆕 검색 모드에 따라 파일 범위 설정 (2025-02-02)
        if self.search_mode_2411.isChecked():
            self.search_controller.set_file_range(None, 129)  # 24.11 데이터셋 (tags_00~129, 130개)
        elif self.search_mode_2509.isChecked():
            self.search_controller.set_file_range(None, 149)  # 25.09 데이터셋 (tags_00~149, 150개)
        elif self.search_mode_1109.isChecked():
            self.search_controller.set_file_range(130, 149)   # 11-09 신규 데이터 (tags_130~149, 20개)

        # UI에서 검색 파라미터 수집
        search_params = {
            'query': self.search_input.text(),
            'exclude_query': self.exclude_input.text(),
            'rating_e': self.rating_checkboxes['e'].isChecked(),
            'rating_q': self.rating_checkboxes['q'].isChecked(),
            'rating_s': self.rating_checkboxes['s'].isChecked(),
            'rating_g': self.rating_checkboxes['g'].isChecked(),
        }

        try:
            save_dir = 'save'
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, 'search_tags.json'), 'w', encoding='utf-8') as f:
                json.dump(search_params, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.status_bar.showMessage(f"⚠️ 검색어 저장 실패: {e}", 5000)

        self.search_controller.start_search(search_params)

    def update_search_progress(self, completed: int, total: int):
        """검색 진행률에 따라 UI 업데이트"""
        percentage = int((completed / total) * 100) if total > 0 else 0
        self.progress_label.setText(f"{completed}/{total}")
        self.search_btn.setText(f"검색 중 ({percentage}%)")

    def on_partial_search_result(self, partial_df: pd.DataFrame):
        """부분 검색 결과를 받아 UI에 즉시 반영"""
        self.search_results.append_dataframe(partial_df)
        self.result_label1.setText(f"검색: {self.search_results.get_count()}")
        self.result_label2.setText(f"남음: {self.search_results.get_count()}")

    def on_search_complete(self, total_count: int):
        """검색 완료 시 호출되는 슬롯, 결과 파일 저장"""
        self.search_btn.setEnabled(True)
        self.search_btn.setText("검색")
        self.progress_label.setVisible(False)
        self.status_bar.showMessage(f"✅ 검색 완료! {total_count}개의 결과를 찾았습니다.", 5000)

        # [신규] 검색 결과 Parquet 파일로 저장
        if not self.search_results.is_empty():
            try:
                self.search_results.get_dataframe().to_parquet('naia_temp_rows.parquet')
            except Exception as e:
                self.status_bar.showMessage(f"⚠️ 결과 파일 저장 실패: {e}", 5000)

    def on_search_error(self, error_message: str):
        """검색 오류 발생 시 호출되는 슬롯"""
        self.search_btn.setEnabled(True)
        self.search_btn.setText("검색")
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "검색 오류", error_message)
        self.status_bar.showMessage(f"❌ 검색 중 오류 발생", 5000)

    # [신규] 앱 시작 시 상태를 로드하는 메서드
    def load_last_search_state(self):
        """앱 시작 시 search_tags.json과 naia_temp_rows.parquet을 로드합니다."""
        # 1. 검색어 로드
        query_file = os.path.join('save', 'search_tags.json')
        if os.path.exists(query_file):
            try:
                with open(query_file, 'r', encoding='utf-8') as f:
                    params = json.load(f)
                self.search_input.setText(params.get('query', ''))
                self.exclude_input.setText(params.get('exclude_query', ''))
                self.rating_checkboxes['e'].setChecked(params.get('rating_e', True))
                self.rating_checkboxes['q'].setChecked(params.get('rating_q', True))
                self.rating_checkboxes['s'].setChecked(params.get('rating_s', True))
                self.rating_checkboxes['g'].setChecked(params.get('rating_g', True))
            except Exception as e:
                self.status_bar.showMessage(f"⚠️ 이전 검색어 로드 실패: {e}", 5000)
                
        # 2. 결과 Parquet 파일 비동기 로드
        result_file = 'naia_temp_rows.parquet'
        if os.path.exists(result_file):
            self.status_bar.showMessage("이전 검색 결과를 불러오는 중...", 3000)
            
            # 기존 스레드가 있으면 정리
            if hasattr(self, 'load_thread') and self.load_thread is not None:
                if self.load_thread.isRunning():
                    self.load_thread.quit()
                    self.load_thread.wait(1000)
                try:
                    self.load_thread.deleteLater()
                except:
                    pass
                self.load_thread = None
            
            if hasattr(self, 'loader') and self.loader is not None:
                try:
                    self.loader.deleteLater()
                except:
                    pass
                self.loader = None
            
            # 새로운 스레드와 로더 생성
            self.load_thread = QThread()
            self.loader = ParquetLoader()
            self.loader.moveToThread(self.load_thread)
            self.load_thread.started.connect(lambda: self.loader.run(result_file))
            self.loader.finished.connect(self.on_previous_results_loaded)
            self.loader.finished.connect(self.loader.deleteLater)
            self.load_thread.finished.connect(self.load_thread.deleteLater)
            self.load_thread.start()

    def restore_search_results(self):
        """'naia_temp_rows.parquet' 파일이 있으면 비동기로 로드합니다."""
        result_file = 'naia_temp_rows.parquet'
        if os.path.exists(result_file):
            self.search_results.set_dataframe(pd.DataFrame())
            self.status_bar.showMessage("이전 검색 결과를 복원하는 중...", 3000)
            
            # 기존 스레드가 실행 중이면 정리
            if hasattr(self, 'load_thread') and self.load_thread is not None:
                if self.load_thread.isRunning():
                    self.load_thread.quit()
                    self.load_thread.wait(1000)  # 최대 1초 대기
                    if self.load_thread.isRunning():
                        self.load_thread.terminate()
                        self.load_thread.wait()
                
                # 기존 스레드 정리
                try:
                    self.load_thread.deleteLater()
                except:
                    pass
                self.load_thread = None
            
            # 기존 로더 정리
            if hasattr(self, 'loader') and self.loader is not None:
                try:
                    self.loader.deleteLater()
                except:
                    pass
                self.loader = None
            
            # 새로운 스레드와 로더 생성
            self.load_thread = QThread()
            self.loader = ParquetLoader()
            self.loader.moveToThread(self.load_thread)
            
            # 연결 설정
            self.load_thread.started.connect(lambda: self.loader.run(result_file))
            self.loader.finished.connect(self.on_previous_results_loaded)
            self.loader.finished.connect(self.loader.deleteLater)
            self.load_thread.finished.connect(self.load_thread.deleteLater)
            
            # 스레드 시작
            self.load_thread.start()
        else:
            self.status_bar.showMessage("⚠️ 복원할 검색 결과 파일(naia_temp_rows.parquet)이 없습니다.", 5000)


    def on_previous_results_loaded(self, result_model: SearchResultModel):
        """비동기로 로드된 이전 검색 결과를 UI에 적용"""
        self.search_results.append_dataframe(result_model.get_dataframe())
        
        # 라벨 업데이트
        count = self.search_results.get_count()
        self.result_label1.setText(f"검색: {count}")
        self.result_label2.setText(f"남음: {count}")
        self.status_bar.showMessage(f"✅ 이전 검색 결과 {count:,}개를 불러왔습니다.", 5000)
    
    def load_custom_parquet(self):
        """사용자가 선택한 parquet 파일을 불러오기 (현재 결과를 비움)"""
        # custom_tags 폴더 확인 및 생성
        custom_tags_dir = os.path.join("save", "custom_tags")
        if not os.path.exists(custom_tags_dir):
            os.makedirs(custom_tags_dir, exist_ok=True)
        
        # 파일 다이얼로그 열기
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Parquet 파일 불러오기",
            custom_tags_dir,
            "Parquet Files (*.parquet);;All Files (*.*)"
        )
        
        if file_path:
            try:
                # 현재 검색 결과 비우기
                self.search_results.set_dataframe(pd.DataFrame())
                
                # 파일 불러오기
                df = pd.read_parquet(file_path)
                self.search_results.set_dataframe(df)
                
                row_count = len(df)
                # UI 라벨 업데이트
                self.result_label1.setText(f"검색: {row_count:,}")
                self.result_label2.setText(f"남음: {row_count:,}")
                self.status_bar.showMessage(f"✅ {os.path.basename(file_path)} 파일을 불러왔습니다. ({row_count:,}개 항목)", 5000)
            except Exception as e:
                QMessageBox.critical(self, "오류", f"파일을 불러오는 중 오류가 발생했습니다:\n{str(e)}")
                self.status_bar.showMessage(f"❌ 파일 불러오기 실패: {str(e)}", 5000)
    
    def merge_custom_parquet(self):
        """사용자가 선택한 parquet 파일을 현재 결과에 합치기"""
        # custom_tags 폴더 확인 및 생성
        custom_tags_dir = os.path.join("save", "custom_tags")
        if not os.path.exists(custom_tags_dir):
            os.makedirs(custom_tags_dir, exist_ok=True)
        
        # 파일 다이얼로그 열기
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Parquet 파일 합치기",
            custom_tags_dir,
            "Parquet Files (*.parquet);;All Files (*.*)"
        )
        
        if file_path:
            try:
                # 새 파일 불러오기
                new_df = pd.read_parquet(file_path)
                
                # 현재 데이터프레임과 합치기
                current_df = self.search_results.get_dataframe()
                if current_df.empty:
                    merged_df = new_df
                else:
                    merged_df = pd.concat([current_df, new_df], ignore_index=True)
                
                self.search_results.set_dataframe(merged_df)
                
                new_count = len(new_df)
                total_count = len(merged_df)
                # UI 라벨 업데이트
                self.result_label1.setText(f"검색: {total_count:,}")
                self.result_label2.setText(f"남음: {total_count:,}")
                self.status_bar.showMessage(
                    f"✅ {os.path.basename(file_path)}을(를) 합쳤습니다. "
                    f"(+{new_count:,}개, 총 {total_count:,}개 항목)", 
                    5000
                )
            except Exception as e:
                QMessageBox.critical(self, "오류", f"파일을 합치는 중 오류가 발생했습니다:\n{str(e)}")
                self.status_bar.showMessage(f"❌ 파일 합치기 실패: {str(e)}", 5000)
    
    def export_custom_parquet(self):
        """현재 검색 결과를 사용자가 지정한 이름으로 내보내기"""
        # custom_tags 폴더 확인 및 생성
        custom_tags_dir = os.path.join("save", "custom_tags")
        if not os.path.exists(custom_tags_dir):
            os.makedirs(custom_tags_dir, exist_ok=True)
        
        # 현재 데이터프레임 확인
        current_df = self.search_results.get_dataframe()
        if current_df.empty:
            QMessageBox.warning(self, "경고", "내보낼 검색 결과가 없습니다.")
            return
        
        # 파일 다이얼로그 열기
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Parquet 파일로 내보내기",
            os.path.join(custom_tags_dir, "my_tags.parquet"),
            "Parquet Files (*.parquet);;All Files (*.*)"
        )
        
        if file_path:
            try:
                # .parquet 확장자 확인
                if not file_path.endswith('.parquet'):
                    file_path += '.parquet'
                
                # 파일 저장
                current_df.to_parquet(file_path, index=False)
                
                row_count = len(current_df)
                self.status_bar.showMessage(
                    f"✅ {os.path.basename(file_path)}로 내보냈습니다. ({row_count:,}개 항목)", 
                    5000
                )
            except Exception as e:
                QMessageBox.critical(self, "오류", f"파일을 내보내는 중 오류가 발생했습니다:\n{str(e)}")
                self.status_bar.showMessage(f"❌ 파일 내보내기 실패: {str(e)}", 5000)
    
    def save_to_execution_file(self):
        """현재 남아있는 행으로 naia_temp_rows.parquet 업데이트"""
        try:
            # 현재 데이터프레임 가져오기
            current_df = self.search_results.get_dataframe()
            
            if current_df.empty:
                QMessageBox.warning(self, "경고", "저장할 검색 결과가 없습니다.")
                return
            
            # naia_temp_rows.parquet에 저장
            execution_file = 'naia_temp_rows.parquet'
            current_df.to_parquet(execution_file, index=False)
            
            row_count = len(current_df)
            self.status_bar.showMessage(
                f"✅ 실행 파일(naia_temp_rows.parquet)을 업데이트했습니다. ({row_count:,}개 항목)", 
                5000
            )
        except Exception as e:
            QMessageBox.critical(self, "오류", f"실행 파일 저장 중 오류가 발생했습니다:\n{str(e)}")
            self.status_bar.showMessage(f"❌ 실행 파일 저장 실패: {str(e)}", 5000)
    
    def show_prompt_tabs_context_menu(self, pos):
        """프롬프트 탭 위젯의 컨텍스트 메뉴 표시"""
        menu = QMenu(self)
        menu.setStyleSheet(DARK_STYLES['menu_style'] if 'menu_style' in DARK_STYLES else "")
        
        if not self.prompt_tabs_detached:
            detach_action = QAction("🔓 외부 창으로 분리", self)
            detach_action.triggered.connect(self.detach_prompt_tabs)
            menu.addAction(detach_action)
        else:
            reattach_action = QAction("🔒 원래 위치로 복귀", self)
            reattach_action.triggered.connect(self.reattach_prompt_tabs)
            menu.addAction(reattach_action)
        
        menu.exec(self.prompt_tabs.mapToGlobal(pos))
    
    def detach_prompt_tabs(self):
        """프롬프트 탭을 외부 창으로 분리"""
        if self.prompt_tabs_detached:
            print("⚠️ 프롬프트 탭이 이미 분리되어 있습니다.")
            return
        
        try:
            print("🔧 프롬프트 탭 분리 시작...")
            
            # 1. 현재 컨테이너에서 탭 위젯 제거
            self.prompt_tabs_container.layout().removeWidget(self.prompt_tabs)
            self.prompt_tabs.setParent(None)
            
            # 2. 컨테이너를 레이아웃에서 제거 (공간 완전히 압축)
            # top_layout을 찾기 위해 부모 위젯 탐색
            parent_widget = self.prompt_tabs_container.parent()
            if parent_widget and parent_widget.layout():
                self.prompt_tabs_container_index = parent_widget.layout().indexOf(self.prompt_tabs_container)
                parent_widget.layout().removeWidget(self.prompt_tabs_container)
                self.prompt_tabs_container.setVisible(False)
            
            # 3. 스플리터 크기 조정 (프롬프트 영역 공간을 중간 섹션에 할당)
            if hasattr(self, 'vertical_splitter'):
                # 현재 스플리터 크기 저장
                self.saved_splitter_sizes = self.vertical_splitter.sizes()
                # 상단 영역 축소, 중간 영역 확장
                total_height = sum(self.saved_splitter_sizes)
                if total_height > 0:
                    # 상단을 최소 크기로, 나머지를 중간에 할당
                    new_top_size = max(100, self.saved_splitter_sizes[0] - 350)  # 최소 150px 유지
                    new_middle_size = total_height - new_top_size
                    self.vertical_splitter.setSizes([new_top_size, new_middle_size])
            
            # 3. 프롬프트 탭을 감싸는 위젯 생성 (버튼 추가를 위해)
            detached_widget = QWidget()
            detached_layout = QVBoxLayout(detached_widget)
            detached_layout.setContentsMargins(8, 8, 8, 8)
            detached_layout.setSpacing(8)
            
            # 탭 위젯 추가
            detached_layout.addWidget(self.prompt_tabs)
            
            # 생성 파라미터 컨테이너 생성
            params_container = QWidget()
            params_layout = QVBoxLayout(params_container)
            params_layout.setContentsMargins(8, 4, 8, 4)
            params_layout.setSpacing(4)
            
            # Line 1: 해상도 관련 컨트롤
            resolution_layout = QHBoxLayout()
            resolution_layout.setSpacing(6)
            
            # 해상도 콤보박스 (복사본)
            self.detached_resolution_combo = QComboBox()
            self.detached_resolution_combo.addItems(self.resolutions)
            self.detached_resolution_combo.setCurrentText(self.resolution_combo.currentText())
            self.detached_resolution_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
            self.disable_wheel_event(self.detached_resolution_combo)  # 마우스 휠 비활성화
            self.detached_resolution_combo.currentTextChanged.connect(self.sync_resolution_to_main)
            resolution_layout.addWidget(self.detached_resolution_combo, 2)
            
            # 랜덤 해상도 체크박스 (복사본)
            self.detached_random_resolution = QCheckBox("랜덤 해상도")
            self.detached_random_resolution.setStyleSheet(DARK_STYLES['dark_checkbox'])
            self.detached_random_resolution.setChecked(self.random_resolution_checkbox.isChecked())
            self.detached_random_resolution.toggled.connect(self.sync_random_resolution_to_main)
            resolution_layout.addWidget(self.detached_random_resolution)
            
            # 자동 맞춤 체크박스 (복사본)
            self.detached_auto_fit = QCheckBox("자동 맞춤")
            self.detached_auto_fit.setStyleSheet(DARK_STYLES['dark_checkbox'])
            self.detached_auto_fit.setChecked(self.auto_fit_resolution_checkbox.isChecked())
            self.detached_auto_fit.toggled.connect(self.sync_auto_fit_to_main)
            resolution_layout.addWidget(self.detached_auto_fit)
            
            params_layout.addLayout(resolution_layout)
            
            # Line 2: 생성 옵션 체크박스들 (상단 마진 추가)
            options_layout = QHBoxLayout()
            options_layout.setSpacing(6)
            options_layout.setContentsMargins(0, 8, 0, 0)  # 상단 마진 8px
            
            # 시드 고정 체크박스 (복사본)
            self.detached_seed_fix = QCheckBox("시드 고정")
            self.detached_seed_fix.setStyleSheet(DARK_STYLES['dark_checkbox'])
            self.detached_seed_fix.setChecked(self.seed_fix_checkbox.isChecked())
            self.detached_seed_fix.toggled.connect(self.sync_seed_fix_to_main)
            options_layout.addWidget(self.detached_seed_fix)
            
            # 프롬프트 고정 체크박스 (복사본)
            self.detached_prompt_fixed = QCheckBox("프롬프트 고정")
            self.detached_prompt_fixed.setStyleSheet(DARK_STYLES['dark_checkbox'])
            self.detached_prompt_fixed.setChecked(self.generation_checkboxes["프롬프트 고정"].isChecked())
            self.detached_prompt_fixed.toggled.connect(self.sync_prompt_fixed_to_main)
            options_layout.addWidget(self.detached_prompt_fixed)
            
            # 자동 생성 체크박스 (복사본)
            self.detached_auto_generate = QCheckBox("자동 생성")
            self.detached_auto_generate.setStyleSheet(DARK_STYLES['dark_checkbox'])
            self.detached_auto_generate.setChecked(self.generation_checkboxes["자동 생성"].isChecked())
            self.detached_auto_generate.toggled.connect(self.sync_auto_generate_to_main)
            options_layout.addWidget(self.detached_auto_generate)
            
            params_layout.addLayout(options_layout)
            detached_layout.addWidget(params_container)
            
            # 구분선 추가
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setStyleSheet(f"background-color: {DARK_COLORS['border']}; max-height: 1px;")
            detached_layout.addWidget(separator)
            
            # 버튼 컨테이너 생성
            button_container = QWidget()
            button_layout = QHBoxLayout(button_container)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(6)  # 메인 윈도우와 동일한 간격
            
            # 랜덤 프롬프트 버튼 (복사본)
            self.detached_random_btn = QPushButton(self.random_prompt_btn.text())
            self.detached_random_btn.setStyleSheet(DARK_STYLES['secondary_button'])  # 원본과 동일한 스타일
            self.detached_random_btn.setEnabled(self.random_prompt_btn.isEnabled())
            self.detached_random_btn.clicked.connect(self.trigger_random_prompt)
            self.detached_random_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)  # 너비 확장
            button_layout.addWidget(self.detached_random_btn, 1)  # stretch factor 1 for equal width
            
            # 생성 버튼 (복사본)
            self.detached_generate_btn = QPushButton("🎨 이미지 생성 요청")
            self.detached_generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
            self.detached_generate_btn.setEnabled(self.generate_button_main.isEnabled())
            self.detached_generate_btn.clicked.connect(self.generation_controller.execute_generation_pipeline)
            self.detached_generate_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)  # 너비 확장
            button_layout.addWidget(self.detached_generate_btn, 1)  # stretch factor 1 for equal width
            
            detached_layout.addWidget(button_container)
            
            # 4. DetachedWindow 생성
            from ui.detached_window import DetachedWindow
            self.prompt_tabs_window = DetachedWindow(
                detached_widget,
                "프롬프트 편집기",
                -1,
                parent_container=self
            )
            self.prompt_tabs_window.window_closed.connect(self.on_prompt_tabs_window_closed)
            
            # 최소 크기 설정
            self.prompt_tabs_window.setMinimumSize(350, 650)
            self.prompt_tabs_window.resize(600, 650)
            
            # 5. 창 표시
            self.prompt_tabs_window.show()
            self.prompt_tabs_window.raise_()
            self.prompt_tabs_window.activateWindow()
            
            self.prompt_tabs_detached = True
            
            # detach 버튼 텍스트 업데이트
            if hasattr(self, 'prompt_tabs_detach_btn'):
                self.prompt_tabs_detach_btn.setText("🔒")
                self.prompt_tabs_detach_btn.setToolTip("원래 위치로 복귀")
            
            # 메인 윈도우 컨트롤들과 연결 설정
            self.setup_main_to_detached_sync()
            
            # 현재 버튼 상태 동기화
            self.update_random_prompt_button_state()
            
            print("✅ 프롬프트 탭 분리 완료")
            
        except Exception as e:
            print(f"❌ 프롬프트 탭 분리 실패: {e}")
            import traceback
            traceback.print_exc()
            
            # 실패 시 복원
            try:
                if hasattr(self, 'prompt_tabs_placeholder'):
                    self.prompt_tabs_container.layout().removeWidget(self.prompt_tabs_placeholder)
                    self.prompt_tabs_placeholder.deleteLater()
                self.prompt_tabs_container.layout().addWidget(self.prompt_tabs)
                self.prompt_tabs_detached = False
            except Exception as restore_error:
                print(f"복원 실패: {restore_error}")
    
    def reattach_prompt_tabs(self):
        """분리된 프롬프트 탭을 원래 위치로 복귀"""
        if not self.prompt_tabs_detached:
            print("⚠️ 프롬프트 탭이 분리되어 있지 않습니다.")
            return
        
        try:
            print("🔄 프롬프트 탭 복귀 시작...")
            
            # 1. 창에서 위젯 회수
            if self.prompt_tabs_window:
                detached_widget = self.prompt_tabs_window.get_original_widget()
                # detached_widget에서 prompt_tabs 추출
                if detached_widget and detached_widget.layout():
                    # 탭 위젯 찾기
                    for i in range(detached_widget.layout().count()):
                        item = detached_widget.layout().itemAt(i)
                        if item and item.widget() == self.prompt_tabs:
                            detached_widget.layout().removeWidget(self.prompt_tabs)
                            break
                
                self.prompt_tabs_window.close()
                self.prompt_tabs_window = None
            
            # 2. 동기화 연결 해제
            self.cleanup_main_to_detached_sync()
            
            # 3. 분리된 컨트롤들 정리
            detached_controls = [
                'detached_random_btn', 'detached_generate_btn',
                'detached_resolution_combo', 'detached_random_resolution',
                'detached_auto_fit', 'detached_seed_fix',
                'detached_prompt_fixed', 'detached_auto_generate'
            ]
            
            for control_name in detached_controls:
                if hasattr(self, control_name):
                    control = getattr(self, control_name)
                    control.deleteLater()
                    delattr(self, control_name)
            
            # 3. 프롬프트 탭을 컨테이너에 다시 추가
            self.prompt_tabs_container.layout().addWidget(self.prompt_tabs)
            
            # 4. 컨테이너를 원래 레이아웃 위치에 복귀
            parent_widget = self.prompt_tabs_container.parent()
            if parent_widget and parent_widget.layout():
                # 저장된 인덱스가 있으면 그 위치에, 없으면 마지막에 추가
                if hasattr(self, 'prompt_tabs_container_index'):
                    parent_widget.layout().insertWidget(self.prompt_tabs_container_index, self.prompt_tabs_container)
                else:
                    parent_widget.layout().addWidget(self.prompt_tabs_container)
            self.prompt_tabs_container.setVisible(True)
            
            # 5. 스플리터 크기 복원
            if hasattr(self, 'vertical_splitter') and hasattr(self, 'saved_splitter_sizes'):
                self.vertical_splitter.setSizes(self.saved_splitter_sizes)
            
            self.prompt_tabs_detached = False
            
            # detach 버튼 텍스트 업데이트
            if hasattr(self, 'prompt_tabs_detach_btn'):
                self.prompt_tabs_detach_btn.setText("🔓")
                self.prompt_tabs_detach_btn.setToolTip("외부 창으로 분리")
            
            print("✅ 프롬프트 탭 복귀 완료")
            
        except Exception as e:
            print(f"❌ 프롬프트 탭 복귀 실패: {e}")
            import traceback
            traceback.print_exc()
    
    def on_prompt_tabs_window_closed(self, tab_index, widget):
        """프롬프트 탭 분리 창이 닫힐 때 호출"""
        self.reattach_prompt_tabs()
    
    def toggle_prompt_tabs_detach(self):
        """프롬프트 탭 분리/복귀 토글"""
        if self.prompt_tabs_detached:
            self.reattach_prompt_tabs()
        else:
            self.detach_prompt_tabs()

    # === 리모트/Interactive/EZ 관련 메서드 ===

    def _on_prompt_tab_changed(self, index: int):
        """프롬프트 탭 전환 이벤트 핸들러"""
        # 일반 탭 클릭 시 이전 탭 인덱스 업데이트
        self.previous_tab_index = index

    def _open_remote_window(self):
        """리모트 창 열기"""
        if self.remote_window_open and self.remote_window:
            # 이미 열려있으면 활성화
            self.remote_window.raise_()
            self.remote_window.activateWindow()
            return

        # 리모트 창 생성
        self.remote_window = RemoteWindow(parent_app=self)
        self.remote_window.window_closed.connect(self._on_remote_window_closed)
        self.remote_window.show()

        # 상태 업데이트
        self.remote_window_open = True
        self.remote_action.setText("📡 리모트 (열림)")
        self.remote_action.setEnabled(False)

    def _on_remote_window_closed(self):
        """리모트 창 닫힘 이벤트"""
        self.remote_window = None
        self.remote_window_open = False
        self.remote_action.setText("📡 리모트")
        self.remote_action.setEnabled(True)

    # === Interactive 탭 관련 메서드 ===

    def _open_interactive_window(self):
        """Interactive 창 열기"""
        if self.interactive_window_open and self.interactive_window:
            # 이미 열려있으면 활성화
            self.interactive_window.raise_()
            self.interactive_window.activateWindow()
            return

        # Interactive 창 생성
        self.interactive_window = InteractiveWindow(parent_app=self, app_context=self.app_context)
        self.interactive_window.window_closed.connect(self._on_interactive_window_closed)
        self.interactive_window.show()

        # 상태 업데이트
        self.interactive_window_open = True
        self.interactive_action.setText("🎨 Interactive Window (열림)")
        self.interactive_action.setEnabled(False)

    def _on_interactive_window_closed(self):
        """Interactive 창 닫힘 이벤트"""
        self.interactive_window = None
        self.interactive_window_open = False
        self.interactive_action.setText("🎨 Interactive Window")
        self.interactive_action.setEnabled(True)

    # === Event Preset 관련 메서드 ===

    def _open_event_preset_window(self):
        """Event Preset 창 열기"""
        if self.event_preset_window_open and self.event_preset_window:
            self.event_preset_window.raise_()
            self.event_preset_window.activateWindow()
            return

        from ui.event_preset import EventPresetWindow

        # 데이터 확인 + 다운로드 (윈도우 생성 전 사전작업)
        if not EventPresetWindow.ensure_data_available(parent=self):
            return

        self.event_preset_window = EventPresetWindow(
            app_context=self.app_context,
            kr_tags_df=self.kr_tags_df,
            parent=None,
        )
        self.event_preset_window.window_closed.connect(self._on_event_preset_window_closed)
        self.event_preset_window.apply_to_main_prompt.connect(
            self.on_instant_generation_requested
        )
        self.event_preset_window.show()

        self.event_preset_window_open = True
        self.event_preset_action.setText("📋 Event Preset (열림)")
        self.event_preset_action.setEnabled(False)

    def _on_event_preset_window_closed(self):
        """Event Preset 창 닫힘 이벤트"""
        self.event_preset_window = None
        self.event_preset_window_open = False
        self.event_preset_action.setText("📋 Event Preset")
        self.event_preset_action.setEnabled(True)

    def _on_mode_changed_for_remote(self, _old_mode: str, new_mode: str):
        """모드 변경 시 리모트 메뉴 가시성 제어"""
        is_nai_mode = (new_mode == "NAI")

        # NAI 모드가 아니면 리모트 창 닫기
        if not is_nai_mode and self.remote_window_open and self.remote_window:
            self.remote_window.close()

        # 메뉴 액션 가시성 설정
        self.remote_action.setVisible(is_nai_mode)

    def _update_model_list_for_comfyui(self):
        """
        현재 API 모드에 맞게 모델 리스트를 업데이트

        - NAI: 기본 NAI 모델 리스트
        - WEBUI: SD-WebUI 서버에서 모델 가져오기
        - COMFYUI: CheckpointLoader + UNETLoader 모델 가져오기
        """
        current_mode = self.app_context.get_api_mode()

        # 현재 선택된 모델 저장
        current_model = self.model_combo.currentText()

        if current_mode == "NAI":
            # NAI 기본 모델로 복원
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            self.model_combo.addItems(["NAID4.5F", "NAID4.5C", "NAID4.0F", "NAID4.0C", "NAID3"])
            self.model_combo.blockSignals(False)
            print("✅ 모델 리스트: NAI 기본 모델로 복원")
            return

        elif current_mode == "WEBUI":
            # WEBUI 서버에서 모델 가져오기
            from core.webui_utils import WebuiAPIUtils

            webui_url = self.app_context.secure_token_manager.get_token('webui_url')
            if not webui_url:
                print("⚠️ WEBUI URL이 설정되지 않았습니다.")
                return

            # URL 정규화
            if not webui_url.startswith('http://') and not webui_url.startswith('https://'):
                webui_url = f"http://{webui_url}"

            models = WebuiAPIUtils.get_model_list(webui_url)

            if models:
                self.model_combo.blockSignals(True)
                self.model_combo.clear()
                self.model_combo.addItems(models)

                # 이전 선택 복원 (가능한 경우)
                if current_model in models:
                    self.model_combo.setCurrentText(current_model)
                elif self.model_combo.count() > 0:
                    self.model_combo.setCurrentIndex(0)

                self.model_combo.blockSignals(False)
                print(f"✅ WEBUI 모델 리스트 업데이트: {len(models)}개 모델")
            else:
                print("⚠️ WEBUI 서버에서 모델을 가져올 수 없습니다. 서버가 실행 중인지 확인하세요.")
            return

        elif current_mode == "COMFYUI":
            # ComfyUI 서버에서 모델 가져오기
            comfyui_url = self.app_context.secure_token_manager.get_token('comfyui_url')
            if not comfyui_url:
                comfyui_url = "http://127.0.0.1:8188"

            models = ComfyUIAPIUtils.get_model_list(comfyui_url)

            if models:
                self.model_combo.blockSignals(True)
                self.model_combo.clear()
                self.model_combo.addItems(models)

                # 이전 선택 복원 (가능한 경우)
                if current_model in models:
                    self.model_combo.setCurrentText(current_model)
                elif self.model_combo.count() > 0:
                    self.model_combo.setCurrentIndex(0)

                self.model_combo.blockSignals(False)
                print(f"✅ ComfyUI 모델 리스트 업데이트: {len(models)}개 모델")
            else:
                print("⚠️ ComfyUI 서버에서 모델을 가져올 수 없습니다. 서버가 실행 중인지 확인하세요.")
            return

    # === 임시 생성 창 관련 메서드 ===

    def create_temp_generation_window(self):
        """
        임시 생성 창 생성

        [Temp] 버튼 클릭 시 호출되어 새로운 TempGenerationWindow를 생성합니다.
        TempWindowManager를 통해 창을 생성하고, 기존 메인 UI의 프롬프트를 복제합니다.
        """
        print("🔄 [ModernMainWindow] 임시 생성 창 생성 요청")

        if hasattr(self, 'temp_window_manager'):
            temp_window = self.temp_window_manager.create_temp_window()

            # 기존 메인 UI의 프롬프트 복제
            main_prompt = self.main_prompt_textedit.toPlainText()
            negative_prompt = self.negative_prompt_textedit.toPlainText()

            temp_window.set_prompts(main_prompt, negative_prompt)

            # 🆕 기존 메인 UI의 생성 파라미터 복제
            temp_window.set_initial_params(self)

            # 🆕 Issue 2 Fix: 메인 UI 모듈 상태 복제 (캐릭터 등)
            temp_window.initialize_from_main_modules(self)

            print(f"✅ [ModernMainWindow] 임시 창 #{temp_window.window_id} 생성 완료 (프롬프트 + 파라미터 + 모듈 상태 복제됨)")
        else:
            print("❌ [ModernMainWindow] TempWindowManager가 초기화되지 않았습니다")

    def on_temp_window_generate_requested(self, window_id: int, params: dict):
        """
        임시 생성 창에서 생성 요청 시 호출

        Args:
            window_id: 요청한 임시 창의 ID
            params: 생성 파라미터 (input, negative_prompt, characters 등)

        임시 창의 프롬프트를 사용하여 GenerationController를 통해 생성 파이프라인을 실행합니다.
        """
        print(f"\n{'='*80}")
        print(f"📥 [ModernMainWindow] on_temp_window_generate_requested() 호출됨!")
        print(f"📥 임시 창 ID: {window_id}")
        print(f"📥 params keys: {list(params.keys()) if params else 'None'}")
        print(f"{'='*80}\n")

        try:
            # 🆕 FR-2-1: 임시 창 모드 플래그 설정
            print(f"[DEBUG] temp_window_manager 타입: {type(self.temp_window_manager).__name__}")
            print(f"[DEBUG] temp_windows 딕셔너리 keys: {list(self.temp_window_manager.temp_windows.keys())}")
            print(f"[DEBUG] 찾으려는 window_id: {window_id} (type: {type(window_id).__name__})")

            temp_window = self.temp_window_manager.temp_windows.get(window_id)
            print(f"[DEBUG] temp_window.get({window_id}) 결과: {temp_window}")

            if temp_window:
                print(f"[DEBUG] ✅ 임시 창 #{window_id} 찾음. AppContext 플래그 설정 중...")
                print(f"[DEBUG] temp_window.character_tab 타입: {type(temp_window.character_tab).__name__}")

                # 플래그 설정
                self.app_context.temp_window_mode = True
                self.app_context.temp_window_character_tab = temp_window.character_tab

                print(f"[DEBUG] ✅ temp_window_mode = True")
                print(f"[DEBUG] ✅ temp_window_character_tab = {type(temp_window.character_tab).__name__}")
            else:
                print(f"[DEBUG] ⚠️⚠️⚠️ 임시 창 #{window_id}를 찾을 수 없습니다!")
                print(f"[DEBUG] ⚠️ 가능한 원인:")
                print(f"[DEBUG] ⚠️   1. window_id 불일치 (찾는 ID: {window_id}, 실제 keys: {list(self.temp_window_manager.temp_windows.keys())})")
                print(f"[DEBUG] ⚠️   2. 임시 창이 아직 등록되지 않음")
                print(f"[DEBUG] ⚠️   3. 임시 창이 이미 닫힘")
                print(f"[DEBUG] ⚠️ 플래그 설정 건너뜀 → temp_window_mode는 False로 유지됨")

            # 생성 파라미터 수집
            main_prompt = params.get('input', '')
            negative_prompt = params.get('negative_prompt', '')

            print(f"  - Main Prompt: {main_prompt[:50]}{'...' if len(main_prompt) > 50 else ''}")
            print(f"  - Negative Prompt: {negative_prompt[:50]}{'...' if len(negative_prompt) > 50 else ''}")

            # GenerationController를 통해 생성 파이프라인 실행
            # 모든 params를 그대로 전달 (characters 포함)
            overrides = params.copy()

            # execute_generation_pipeline 호출
            # (GenerationController가 자동으로 큐에 추가하거나 즉시 실행)
            if hasattr(self, 'generation_controller'):
                self.generation_controller.execute_generation_pipeline(overrides=overrides)
                print(f"✅ [ModernMainWindow] 임시 창 #{window_id} 생성 요청 처리 완료")
            else:
                print("❌ [ModernMainWindow] GenerationController가 없습니다")
                # 플래그 해제
                self.app_context.temp_window_mode = False
                self.app_context.temp_window_character_tab = None

        except Exception as e:
            print(f"❌ [ModernMainWindow] 임시 창 생성 요청 처리 중 오류: {e}")
            import traceback
            traceback.print_exc()

            # 에러 발생 시 플래그 해제
            self.app_context.temp_window_mode = False
            self.app_context.temp_window_character_tab = None

    def apply_temp_params(self, params: dict):
        """
        임시 생성 창에서 받은 파라미터를 메인 UI에 적용

        Args:
            params: TempGenerationParamsWidget.collect_parameters()에서 반환된 딕셔너리
                    + input, negative_prompt
                    + apply_sections (optional): 어떤 섹션을 적용할지 선택
        """
        print("[ModernMainWindow] 임시 창 파라미터를 메인 UI에 적용 중...")

        # 선택적 적용 섹션 확인
        apply_sections = params.get('apply_sections', {
            'main_prompt': True,
            'negative_prompt': True,
            'generation_params': True,
            'character': False,
            'prompt_engineering': False
        })

        try:
            # 1. 프롬프트 적용
            if apply_sections.get('main_prompt', True) and 'input' in params:
                self.main_prompt_textedit.setPlainText(params['input'])
                print(f"  ✅ Main Prompt: {params['input'][:50]}{'...' if len(params['input']) > 50 else ''}")

            if apply_sections.get('negative_prompt', True) and 'negative_prompt' in params:
                self.negative_prompt_textedit.setPlainText(params['negative_prompt'])
                print(f"  ✅ Negative Prompt: {params['negative_prompt'][:50]}{'...' if len(params['negative_prompt']) > 50 else ''}")

            # 2. 생성 파라미터 적용 (선택된 경우만)
            if apply_sections.get('generation_params', True):
                # 해상도 적용
                if 'width' in params and 'height' in params:
                    resolution_text = f"{params['width']} x {params['height']}"
                    index = self.resolution_combo.findText(resolution_text, Qt.MatchFlag.MatchContains)
                    if index >= 0:
                        self.resolution_combo.setCurrentIndex(index)
                        print(f"  ✅ Resolution: {resolution_text}")

                # 기본 파라미터 적용
                if 'steps' in params:
                    self.steps_spinbox.setValue(params['steps'])
                    print(f"  ✅ Steps: {params['steps']}")

                if 'scale' in params:
                    self.cfg_scale_slider.setValue(int(params['scale'] * 10))
                    print(f"  ✅ CFG Scale: {params['scale']}")

                if 'seed' in params:
                    self.seed_input.setText(str(params['seed']))
                    print(f"  ✅ Seed: {params['seed']}")

                if 'sampler' in params:
                    index = self.sampler_combo.findText(params['sampler'])
                    if index >= 0:
                        self.sampler_combo.setCurrentIndex(index)
                        print(f"  ✅ Sampler: {params['sampler']}")

                if 'noise_schedule' in params:
                    index = self.scheduler_combo.findText(params['noise_schedule'])
                    if index >= 0:
                        self.scheduler_combo.setCurrentIndex(index)
                        print(f"  ✅ Scheduler: {params['noise_schedule']}")

                # NAI 전용 파라미터
                if self.app_context.get_api_mode() == "NAI":
                    if 'model' in params:
                        index = self.model_combo.findText(params['model'])
                        if index >= 0:
                            self.model_combo.setCurrentIndex(index)
                            print(f"  ✅ NAI Model: {params['model']}")

                    if 'cfg_rescale' in params:
                        self.cfg_rescale_slider.setValue(int(params['cfg_rescale'] * 100))
                        print(f"  ✅ CFG Rescale: {params['cfg_rescale']}")

                    # NAI 옵션 체크박스
                    if 'sm' in params:
                        self.advanced_checkboxes['SMEA'].setChecked(params['sm'])
                    if 'sm_dyn' in params:
                        self.advanced_checkboxes['DYN'].setChecked(params['sm_dyn'])
                    if 'variety_plus' in params:
                        self.advanced_checkboxes['VAR+'].setChecked(params['variety_plus'])
                    if 'decrisper' in params:
                        self.advanced_checkboxes['DECRISP'].setChecked(params['decrisper'])

                # WEBUI 전용 파라미터
                elif self.app_context.get_api_mode() == "WEBUI":
                    if 'enable_hr' in params and hasattr(self, 'enable_hr_checkbox'):
                        self.enable_hr_checkbox.setChecked(params['enable_hr'])
                    if 'hr_scale' in params and hasattr(self, 'hr_scale_spinbox'):
                        self.hr_scale_spinbox.setValue(params['hr_scale'])
                    if 'hr_upscaler' in params and hasattr(self, 'hr_upscaler_combo'):
                        index = self.hr_upscaler_combo.findText(params['hr_upscaler'])
                        if index >= 0:
                            self.hr_upscaler_combo.setCurrentIndex(index)

                # 체크박스들
                if 'random_resolution' in params:
                    self.random_resolution_checkbox.setChecked(params['random_resolution'])
                if 'seed_fix' in params:
                    self.seed_fix_checkbox.setChecked(params['seed_fix'])
                if 'auto_fit_resolution' in params:
                    self.auto_fit_resolution_checkbox.setChecked(params['auto_fit_resolution'])

            # 3. 캐릭터 적용 (선택된 경우만)
            if apply_sections.get('character', False):
                if 'temp_window_character_tab' in params:
                    # VirtualCharacterTab에서 텍스트만 추출하여 메인 CharacterModule에 덤핑
                    temp_char_tab = params['temp_window_character_tab']
                    character_module = self.app_context.middle_section_controller.get_module_instance("CharacterModule")

                    if character_module and temp_char_tab and hasattr(temp_char_tab, 'get_display_text'):
                        # VirtualCharacterTab에서 표시 중인 텍스트 가져오기
                        display_text = temp_char_tab.get_display_text()

                        if display_text:
                            # CharacterModule의 첫 번째 캐릭터 위젯에 텍스트 덤핑
                            if hasattr(character_module, 'character_widgets') and len(character_module.character_widgets) > 0:
                                first_widget = character_module.character_widgets[0]
                                if hasattr(first_widget, 'prompt_textbox'):
                                    first_widget.prompt_textbox.setPlainText(display_text)
                                    # 체크박스 활성화
                                    if hasattr(first_widget, 'active_checkbox'):
                                        first_widget.active_checkbox.setChecked(True)
                                    print(f"  ✅ Character: 첫 번째 위젯에 텍스트 덤핑 완료 ({len(display_text)} 문자)")
                            else:
                                print(f"  ⚠️ Character: character_widgets를 찾을 수 없거나 비어있음")
                        else:
                            print(f"  ⚠️ Character: 덤핑할 텍스트가 비어있음")

            # 4. 프롬프트 엔지니어링 적용 (선택된 경우만)
            if apply_sections.get('prompt_engineering', False):
                if 'temp_window_prompt_engineering_tab' in params:
                    # 프롬프트 엔지니어링 모듈을 통해 설정 적용
                    pe_module = self.app_context.middle_section_controller.get_module_instance("PromptEngineeringModule")
                    temp_pe_tab = params['temp_window_prompt_engineering_tab']
                    if pe_module and temp_pe_tab:
                        # 텍스트 필드 복사
                        if hasattr(temp_pe_tab, 'pre_textedit') and hasattr(pe_module, 'pre_textedit'):
                            pe_module.pre_textedit.setPlainText(temp_pe_tab.pre_textedit.toPlainText())
                        if hasattr(temp_pe_tab, 'post_textedit') and hasattr(pe_module, 'post_textedit'):
                            pe_module.post_textedit.setPlainText(temp_pe_tab.post_textedit.toPlainText())
                        if hasattr(temp_pe_tab, 'auto_hide_textedit') and hasattr(pe_module, 'auto_hide_textedit'):
                            pe_module.auto_hide_textedit.setPlainText(temp_pe_tab.auto_hide_textedit.toPlainText())

                        # 체크박스 복사
                        if hasattr(temp_pe_tab, 'preprocessing_checkboxes') and hasattr(pe_module, 'preprocessing_checkboxes'):
                            for key, checkbox in temp_pe_tab.preprocessing_checkboxes.items():
                                if key in pe_module.preprocessing_checkboxes:
                                    pe_module.preprocessing_checkboxes[key].setChecked(checkbox.isChecked())

                        print(f"  ✅ Prompt Engineering: 설정 적용됨")

            print(f"✅ [ModernMainWindow] 임시 창 파라미터 적용 완료: {len(params)} 항목")

        except Exception as e:
            print(f"❌ [ModernMainWindow] 파라미터 적용 중 오류: {e}")
            import traceback
            traceback.print_exc()

    def on_temp_window_closing(self, window_id: int):
        """
        임시 생성 창이 닫힐 때 호출

        Args:
            window_id: 닫히는 임시 창의 ID

        TempWindowManager를 통해 창을 정리합니다.
        """
        print(f"🔄 [ModernMainWindow] 임시 창 #{window_id} 닫기 요청 수신")

        if hasattr(self, 'temp_window_manager'):
            self.temp_window_manager.close_temp_window(window_id)
            print(f"✅ [ModernMainWindow] 임시 창 #{window_id} 정리 완료")
        else:
            print("❌ [ModernMainWindow] TempWindowManager가 초기화되지 않았습니다")

    def check_and_close_temp_windows(self, change_type: str, old_value: str, new_value: str) -> bool:
        """
        모드/모델 변경 시 임시 창 자동 종료 확인

        Args:
            change_type: 변경 타입 ("API 모드", "NAI 모델")
            old_value: 이전 값
            new_value: 새 값

        Returns:
            bool: True=계속 진행, False=변경 취소
        """
        from PyQt6.QtWidgets import QMessageBox

        # 임시 창이 없으면 즉시 허용
        if not hasattr(self, 'temp_window_manager'):
            return True

        temp_count = len(self.temp_window_manager.temp_windows)
        if temp_count == 0:
            return True

        # 확인 다이얼로그 표시
        print(f"⚠️ [ModernMainWindow] {change_type} 변경 감지: {old_value} → {new_value}")
        print(f"   현재 {temp_count}개의 임시 창이 열려 있습니다")

        reply = QMessageBox.question(
            self,
            "임시 생성 윈도우 종료 확인",
            f"{temp_count}개의 임시 생성 윈도우가 자동으로 종료됩니다.\n\n"
            f"변경 내용: {change_type}\n"
            f"  • 이전: {old_value}\n"
            f"  • 새로: {new_value}\n\n"
            f"계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No  # 기본값: No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # 모든 임시 창 종료
            print(f"✅ [ModernMainWindow] 사용자 승인: 임시 창 {temp_count}개 종료 중...")
            self.temp_window_manager.cleanup_all_temp_windows()
            return True
        else:
            # 변경 취소
            print(f"🚫 [ModernMainWindow] 사용자 취소: {change_type} 변경 취소됨")
            return False

    # === EZ Mode 관련 메서드 ===

    def open_ez_mode_window(self):
        """
        EZ Mode 창 열기

        [EZ] 버튼 클릭 시 호출되어 EZModeWindow를 생성하거나 기존 창을 활성화합니다.
        """
        print("[OK] [ModernMainWindow] EZ Mode 창 열기 요청")

        # 이미 열려있으면 활성화
        if hasattr(self, 'ez_mode_window') and self.ez_mode_window is not None:
            if self.ez_mode_window.isVisible():
                self.ez_mode_window.raise_()
                self.ez_mode_window.activateWindow()
                print("[OK] [ModernMainWindow] 기존 EZ Mode 창 활성화")
                return

        try:
            from ui.ezmode.ezmode_window import EZModeWindow

            # EZ Mode 창 생성
            self.ez_mode_window = EZModeWindow(self.app_context, parent=self)

            # 프롬프트 생성 이벤트 구독
            self.app_context.subscribe('ez_mode_prompt_generated', self._on_ez_mode_prompt_generated)

            # 즉시 생성 시그널 연결 (EZModeWindow → MainWindow)
            self.ez_mode_window.instant_generation_requested.connect(self.on_generate_with_image_requested)
            print("✅ EZ Mode instant_generation_requested 시그널이 연결되었습니다.")

            # 창 닫기 이벤트 연결
            self.ez_mode_window.destroyed.connect(self.on_ez_mode_window_closing)

            # 창 표시
            self.ez_mode_window.show()
            self.ez_mode_window.raise_()
            self.ez_mode_window.activateWindow()

            # 메뉴 액션 상태 업데이트
            self.ez_mode_action.setText("⚡ EZ Mode (열림)")
            self.ez_mode_action.setEnabled(False)

            print("[OK] [ModernMainWindow] EZ Mode 창 생성 완료")

        except Exception as e:
            print(f"[ERROR] [ModernMainWindow] EZ Mode 창 생성 실패: {e}")
            import traceback
            traceback.print_exc()

            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                "EZ Mode 오류",
                f"EZ Mode 창을 열 수 없습니다.\n\n{str(e)}"
            )

    def _on_ez_mode_prompt_generated(self, data: dict):
        """
        EZ Mode에서 프롬프트 생성 시 호출

        Args:
            data: {'prompt': str} - 생성된 프롬프트
        """
        prompt = data.get('prompt', '')

        if prompt:
            # 메인 프롬프트에 적용
            self.main_prompt_textedit.setPlainText(prompt)
            print(f"[OK] [ModernMainWindow] EZ Mode 프롬프트 적용: {len(prompt)} characters")

    def on_ez_mode_window_closing(self):
        """
        EZ Mode 창이 닫힐 때 호출
        """
        print("[OK] [ModernMainWindow] EZ Mode 창 닫기")

        # 이벤트 구독 해제
        if hasattr(self, 'app_context'):
            # Note: AppContext에 unsubscribe 메서드가 있다면 사용
            pass

        # 참조 제거
        self.ez_mode_window = None

        # 메뉴 액션 상태 복원
        self.ez_mode_action.setText("⚡ EZ Mode")
        self.ez_mode_action.setEnabled(True)

    def _on_model_changing(self, new_model: str):
        """
        NAI 모델 변경 시 호출 (임시 창 자동 종료 체크)

        NAID3 ↔ NAID4.x 전환 시에만 임시 창 종료 확인 필요
        """
        old_model = self._previous_nai_model
        current_api_mode = self.app_context.get_api_mode()

        # NAI 모드가 아니면 체크 불필요
        if current_api_mode != "NAI":
            self._previous_nai_model = new_model
            return

        # NAID3 ↔ 다른 모델 전환 감지
        is_naid3_change = (
            (old_model == "NAID3" and new_model != "NAID3") or
            (old_model != "NAID3" and new_model == "NAID3")
        )

        if is_naid3_change:
            # 임시 창 종료 확인
            if not self.check_and_close_temp_windows("NAI 모델", old_model, new_model):
                # 취소: 모델 선택 롤백
                print(f"🔄 [ModernMainWindow] 모델 선택 롤백: {new_model} → {old_model}")
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentText(old_model)
                self.model_combo.blockSignals(False)
                return

        # 정상 진행: 새 모델 저장
        self._previous_nai_model = new_model
        print(f"✅ [ModernMainWindow] NAI 모델 변경 완료: {old_model} → {new_model}")

    def toggle_queue_window(self):
        """대기열 창 열기/닫기 토글"""
        # TODO: 대기열 창 구현
        QMessageBox.information(self, "대기열", "대기열 기능은 아직 구현 중입니다.")
    
    # === 분리된 창의 컨트롤 동기화 메서드들 ===
    
    def sync_resolution_to_main(self, text):
        """분리된 창의 해상도를 메인 윈도우에 동기화"""
        if hasattr(self, 'resolution_combo'):
            self.resolution_combo.setCurrentText(text)
    
    def sync_random_resolution_to_main(self, checked):
        """분리된 창의 랜덤 해상도를 메인 윈도우에 동기화"""
        if hasattr(self, 'random_resolution_checkbox'):
            self.random_resolution_checkbox.setChecked(checked)
    
    def sync_auto_fit_to_main(self, checked):
        """분리된 창의 자동 맞춤을 메인 윈도우에 동기화"""
        if hasattr(self, 'auto_fit_resolution_checkbox'):
            self.auto_fit_resolution_checkbox.setChecked(checked)
    
    def sync_seed_fix_to_main(self, checked):
        """분리된 창의 시드 고정을 메인 윈도우에 동기화"""
        if hasattr(self, 'seed_fix_checkbox'):
            self.seed_fix_checkbox.setChecked(checked)
    
    def sync_prompt_fixed_to_main(self, checked):
        """분리된 창의 프롬프트 고정을 메인 윈도우에 동기화"""
        if "프롬프트 고정" in self.generation_checkboxes:
            self.generation_checkboxes["프롬프트 고정"].setChecked(checked)
            # 버튼 상태도 업데이트
            self.update_random_prompt_button_state()
    
    def sync_auto_generate_to_main(self, checked):
        """분리된 창의 자동 생성을 메인 윈도우에 동기화"""
        if "자동 생성" in self.generation_checkboxes:
            self.generation_checkboxes["자동 생성"].setChecked(checked)
    
    # === 메인 윈도우에서 분리된 창으로 동기화 ===
    
    def setup_main_to_detached_sync(self):
        """메인 윈도우 컨트롤들의 시그널을 분리된 창과 연결"""
        # 해상도 콤보박스
        self.resolution_combo.currentTextChanged.connect(
            lambda text: self.detached_resolution_combo.setCurrentText(text) 
            if hasattr(self, 'detached_resolution_combo') else None
        )
        
        # 체크박스들
        self.random_resolution_checkbox.toggled.connect(
            lambda checked: self.detached_random_resolution.setChecked(checked)
            if hasattr(self, 'detached_random_resolution') else None
        )
        self.auto_fit_resolution_checkbox.toggled.connect(
            lambda checked: self.detached_auto_fit.setChecked(checked)
            if hasattr(self, 'detached_auto_fit') else None
        )
        self.seed_fix_checkbox.toggled.connect(
            lambda checked: self.detached_seed_fix.setChecked(checked)
            if hasattr(self, 'detached_seed_fix') else None
        )
        self.generation_checkboxes["프롬프트 고정"].toggled.connect(
            lambda checked: self.detached_prompt_fixed.setChecked(checked)
            if hasattr(self, 'detached_prompt_fixed') else None
        )
        self.generation_checkboxes["자동 생성"].toggled.connect(
            lambda checked: self.detached_auto_generate.setChecked(checked)
            if hasattr(self, 'detached_auto_generate') else None
        )
    
    def cleanup_main_to_detached_sync(self):
        """메인 윈도우 컨트롤들의 동기화 시그널 연결 해제"""
        try:
            # 기존 연결들을 안전하게 해제
            self.resolution_combo.currentTextChanged.disconnect()
        except TypeError:
            pass  # 연결되지 않았으면 무시
        
        try:
            self.random_resolution_checkbox.toggled.disconnect()
        except TypeError:
            pass
        
        try:
            self.auto_fit_resolution_checkbox.toggled.disconnect()
        except TypeError:
            pass
        
        try:
            self.seed_fix_checkbox.toggled.disconnect()
        except TypeError:
            pass
        
        try:
            self.generation_checkboxes["프롬프트 고정"].toggled.disconnect()
        except TypeError:
            pass
        
        try:
            self.generation_checkboxes["자동 생성"].toggled.disconnect()
        except TypeError:
            pass         

    def open_depth_search_tab(self):
        """심층 검색 탭을 열거나, 이미 열려있으면 해당 탭으로 전환"""
        if self.search_results.is_empty():
            return
            
        # ✅ RightView의 tab_controller를 통해 동적 탭 생성을 요청
        if self.image_window and hasattr(self.image_window, 'tab_controller'):
            self.image_window.tab_controller.add_tab_by_name(
                'DepthSearchTabModule', # ◀ 모듈의 클래스 이름을 문자열로 전달
                search_results=self.search_results, 
                main_window=self
            )

    def on_depth_search_results_assigned(self, new_search_result: SearchResultModel):
        """심층 검색 탭에서 할당된 결과를 메인 UI에 반영"""
        self.search_results = new_search_result
        count = self.search_results.get_count()
        self.result_label1.setText(f"검색: {count}")
        self.result_label2.setText(f"남음: {count}")
        self.status_bar.showMessage(f"✅ 심층 검색 결과 {count}개가 메인에 할당되었습니다.", 5000)

    # --- [신규] 프롬프트 생성 관련 메서드들 ---
    def on_instant_generation_requested(self, tags_dict: dict | pd.Series):
        """WebView에서 추출된 태그로 즉시 프롬프트를 생성합니다."""
        self.status_bar.showMessage("추출된 태그로 프롬프트 생성 중...")

        # 현재 UI의 생성 설정값들을 가져옴
        # 🔧 ComfyUI 샘플링 모드 감지 (라디오 버튼에서 직접 읽기)
        comfyui_sampling_mode = "eps"  # 기본값
        if hasattr(self, 'anima_radio') and self.anima_radio.isChecked():
            comfyui_sampling_mode = "anima"
        elif hasattr(self, 'v_pred_radio') and self.v_pred_radio.isChecked():
            comfyui_sampling_mode = "v_prediction"
        elif hasattr(self, 'eps_radio') and self.eps_radio.isChecked():
            comfyui_sampling_mode = "eps"

        settings = {
            'prompt_fixed': self.generation_checkboxes["프롬프트 고정"].isChecked(),
            'auto_generate': self.generation_checkboxes["자동 생성"].isChecked(),
            'turbo_mode': self.generation_checkboxes["터보 옵션"].isChecked(),
            'wildcard_standalone': self.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
            'api_mode': self.app_context.get_api_mode(),  # 🆕 ANIMA 모드 감지를 위해 추가
            'comfyui_sampling_mode': comfyui_sampling_mode  # 🔧 라디오 버튼에서 직접 읽기
        }

        # 컨트롤러에 즉시 생성을 요청
        self.prompt_gen_controller.generate_instant_source(tags_dict, settings)

    def trigger_random_prompt(self):
        """[랜덤/다음 프롬프트] 버튼 클릭 시 컨트롤러를 통해 프롬프트 생성을 시작"""
        self.random_prompt_btn.setEnabled(False)
        # 분리된 버튼도 비활성화
        if hasattr(self, 'detached_random_btn'):
            self.detached_random_btn.setEnabled(False)
        self.status_bar.showMessage("다음 프롬프트를 생성 중...")

        # UI에서 생성 관련 설정값들을 수집
        # 🔧 ComfyUI 샘플링 모드 감지 (라디오 버튼에서 직접 읽기)
        comfyui_sampling_mode = "eps"  # 기본값
        if hasattr(self, 'anima_radio') and self.anima_radio.isChecked():
            comfyui_sampling_mode = "anima"
        elif hasattr(self, 'v_pred_radio') and self.v_pred_radio.isChecked():
            comfyui_sampling_mode = "v_prediction"
        elif hasattr(self, 'eps_radio') and self.eps_radio.isChecked():
            comfyui_sampling_mode = "eps"

        settings = {
            'prompt_fixed': self.generation_checkboxes["프롬프트 고정"].isChecked(),
            'auto_generate': self.generation_checkboxes["자동 생성"].isChecked(),
            'turbo_mode': self.generation_checkboxes["터보 옵션"].isChecked(),
            'wildcard_standalone': self.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
            "auto_fit_resolution": self.auto_fit_resolution_checkbox.isChecked(),
            'api_mode': self.app_context.get_api_mode(),  # 🆕 ANIMA 모드 감지를 위해 추가
            'comfyui_sampling_mode': comfyui_sampling_mode  # 🔧 라디오 버튼에서 직접 읽기
        }
        self.app_context.publish("random_prompt_triggered")

        # [수정] 수동 생성 시에는 자동 생성 플래그를 False로 설정
        self.prompt_gen_controller.auto_generation_requested = False
        self.prompt_gen_controller.generate_next_prompt(self.search_results, settings)

    def _trigger_auto_image_generation(self):
        """자동 생성 모드에서 이미지 생성을 트리거합니다."""
        try:
            # [수정] is_generating 체크 제거 - 프롬프트 생성 완료 후 호출되므로 생성 가능한 상태
            # 대신 간단한 시간 기반 중복 방지만 적용
            import time
            current_time = time.time()
            
            # 마지막 이미지 생성 시간 체크 (0.5초 이내 중복 방지)
            if not hasattr(self, 'last_image_generation_time'):
                self.last_image_generation_time = 0
                
            if (current_time - self.last_image_generation_time) < 0.5:
                print(f"⚠️ 이미지 생성 중복 방지: time_diff={current_time - self.last_image_generation_time:.2f}s")
                return
                
            self.last_image_generation_time = current_time
            
            # 이미지 생성 실행
            self.generation_controller.execute_generation_pipeline()
            
        except Exception as e:
            self.status_bar.showMessage(f"❌ 자동 이미지 생성 오류: {e}")
            print(f"자동 이미지 생성 오류: {e}")

    def on_prompt_generated(self, prompt_text: str):
        """컨트롤러로부터 생성된 프롬프트를 받아 UI에 업데이트"""
        self.main_prompt_textedit.setPlainText(prompt_text)

        # 🆕 EZ Mode Skip Flags 해제 (항상 프롬프트 생성 후 정리)
        if hasattr(self.app_context, 'skip_prompt_engineering_hook') and self.app_context.skip_prompt_engineering_hook:
            self.app_context.skip_prompt_engineering_hook = False
            print(f"[MainWindow] ✅ skip_prompt_engineering_hook = False 해제 (전체 훅 재활성화)")

        if hasattr(self.app_context, 'skip_prompt_engineering_auto_hide') and self.app_context.skip_prompt_engineering_auto_hide:
            self.app_context.skip_prompt_engineering_auto_hide = False
            print(f"[MainWindow] ✅ skip_prompt_engineering_auto_hide = False 해제 (Auto Hide 재활성화)")

        # [신규] 새 프롬프트 생성 시 반복 카운터 리셋
        if self.automation_module:
            self.automation_module.reset_repeat_counter()

        # [신규] 자동 생성 플래그 해제
        self.auto_generation_in_progress = False
        
        # [수정] 자동 생성 모드인지 확인하고 처리
        if hasattr(self.prompt_gen_controller, 'auto_generation_requested') and self.prompt_gen_controller.auto_generation_requested:
            # 자동 생성 플래그 해제
            self.prompt_gen_controller.auto_generation_requested = False

            # char_module = self.middle_section_controller.get_module_instance("CharacterModule")
            # if (char_module and 
            #     hasattr(char_module, 'is_auto_mode_active') and 
            #     char_module.is_auto_mode_active()):
                
            #     # 자동 생성 모드에서 이미지 생성 트리거
            #     self._trigger_auto_image_generation()
            # if (char_module and 
            #     char_module.activate_checkbox.isChecked() and 
            #     not char_module.reroll_on_generate_checkbox.isChecked()):
                
            #     print("🔄️ 자동 생성: 캐릭터 와일드카드를 갱신합니다.")
            #     char_module.process_and_update_view()
            
            self.status_bar.showMessage("🔄 자동 생성: 프롬프트 생성 완료, 이미지 생성 시작...")
            
            # 자동으로 이미지 생성 실행 (약간의 지연을 두어 UI 업데이트 완료 후 실행)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._trigger_auto_image_generation)
        else:
            # 수동 생성인 경우
            self.status_bar.showMessage("✅ 다음 프롬프트 생성 완료!", 3000)
            self.random_prompt_btn.setEnabled(True)
            # 분리된 버튼도 활성화
            if hasattr(self, 'detached_random_btn'):
                self.detached_random_btn.setEnabled(True)

    def on_generation_error(self, error_message: str):
        """프롬프트 생성 중 오류 발생 시 호출"""
        # [신규] 오류 시 플래그 해제
        self.auto_generation_in_progress = False

        self.status_bar.showMessage(f"❌ 생성 오류: {error_message}", 5000)
        self.random_prompt_btn.setEnabled(True)
        # 분리된 버튼도 활성화
        if hasattr(self, 'detached_random_btn'):
            self.detached_random_btn.setEnabled(True)

    def load_generation_parameters(self):
        # 기존 방식 대신 모드별 로드
        current_mode = self.app_context.get_api_mode()
        self.generation_params_manager.load_mode_settings(current_mode)
    
    def save_generation_parameters(self):
        # 기존 방식 대신 모드별 저장
        current_mode = self.app_context.get_api_mode()
        self.generation_params_manager.save_mode_settings(current_mode)
    
    def read_current_version(self) -> tuple:
        """Git 명령어로 현재 브랜치, 커밋 SHA, 날짜를 가져옵니다.
        반환: (branch, sha, date) 튜플 또는 ("", "", "") if Git 저장소가 아니거나 오류 발생
        """
        try:
            # .git 폴더가 있는지 확인 (ZIP 다운로드 등의 경우 없을 수 있음)
            git_dir = os.path.join(os.path.dirname(__file__), '.git')
            if not os.path.exists(git_dir):
                print("⚠️ .git 폴더가 없습니다. (ZIP 다운로드 또는 Git 저장소가 아님)")
                self.has_git = False
                return "", "", ""
            
            # Windows에서 콘솔 창 숨기기 위한 설정
            startupinfo = None
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            # macOS/Linux에서는 startupinfo가 None으로 유지됨 (정상 동작)
            
            # 현재 브랜치 이름 가져오기
            branch_result = subprocess.run(
                ['git', 'branch', '--show-current'],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(__file__),
                startupinfo=startupinfo
            )
            
            # 현재 커밋 SHA 가져오기 (짧은 형태)
            sha_result = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(__file__),
                startupinfo=startupinfo
            )
            
            # 현재 커밋 날짜 가져오기 (YYYYMMDD 형식)
            date_result = subprocess.run(
                ['git', 'show', '-s', '--format=%cd', '--date=format:%Y%m%d', 'HEAD'],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(__file__),
                startupinfo=startupinfo
            )
            
            if branch_result.returncode == 0 and sha_result.returncode == 0 and date_result.returncode == 0:
                branch = branch_result.stdout.strip()
                sha = sha_result.stdout.strip()
                date = date_result.stdout.strip()
                
                # shallow clone의 경우 브랜치 이름이 비어있을 수 있음
                if not branch:
                    # detached HEAD 상태일 수 있으므로 기본 브랜치 사용
                    branch = self.github_branch
                    print(f"⚠️ Detached HEAD 상태 또는 shallow clone. 기본 브랜치 사용: {branch}")
                
                self.has_git = True
                print(f"📍 현재 Git 정보: 브랜치={branch}, SHA={sha}, 날짜={date}")
                return branch, sha, date
            else:
                print("⚠️ Git 명령 실행 실패. Git이 설치되어 있지 않을 수 있습니다.")
                self.has_git = False
                
        except FileNotFoundError:
            print("⚠️ Git이 설치되어 있지 않습니다.")
            self.has_git = False
        except Exception as e:
            print(f"⚠️ Git 정보 읽기 실패: {e}")
            self.has_git = False
        
        return "", "", ""

    def check_for_updates(self):
        """업데이트 확인 스레드를 시작합니다."""
        current_branch, current_sha, current_date = self.read_current_version()
        
        # Git 정보 저장
        self.current_commit_sha = current_sha
        self.current_commit_date = current_date
        
        # Git이 있는 경우 윈도우 타이틀 업데이트
        if self.has_git and current_sha:
            self.update_window_title()
        
        # 브랜치가 다르면 경고 메시지 출력
        if current_branch and current_branch != self.github_branch:
            print(f"⚠️ 브랜치 불일치: 로컬={current_branch}, 설정={self.github_branch}")
            # 로컬 브랜치를 우선 사용
            self.github_branch = current_branch
        
        if not current_sha:
            print("⚠️ Git 정보를 가져올 수 없어 업데이트 확인을 건너뜁니다.")
            return

        # 이전 스레드가 실행 중이면 중복 실행 방지
        if self.update_checker_thread and self.update_checker_thread.isRunning():
            return

        self.update_checker_thread = GitHubUpdateChecker(
            owner=self.github_repo_owner,
            repo=self.github_repo_name,
            branch=self.github_branch,
            current_sha=current_sha
        )
        self.update_checker_thread.update_available.connect(self.on_version_checked)
        self.update_checker_thread.start()

    def on_version_checked(self, latest_sha: str, commit_message: str, commit_date: str):
        """버전 확인 결과를 처리하고 필요시 업데이트 알림을 표시합니다."""
        # 최신 버전 정보 저장
        self.latest_commit_sha = latest_sha
        self.latest_commit_date = commit_date
        
        # 윈도우 타이틀 업데이트
        self.update_window_title()
        
        # 업데이트가 있는 경우에만 상태 표시줄에 알림 표시
        # if self.current_commit_sha != latest_sha:
        #     # 클릭 가능한 라벨 생성
        #     update_label = QLabel(f"✨ 새 버전 업데이트 가능 ({self.github_branch}): {commit_message[:30]}...")
        #     update_label.setStyleSheet("color: #87CEEB; text-decoration: underline; cursor: pointer;")
        #     update_label.setToolTip(f"클릭하여 GitHub {self.github_branch} 브랜치에서 변경 사항 확인")

        #     # 라벨 클릭 시 GitHub 페이지 열기 - QDesktopServices 사용
        #     # 브랜치별 커밋 페이지로 이동
        #     repo_url = f"https://github.com/{self.github_repo_owner}/{self.github_repo_name}/commit/{latest_sha}"
        #     update_label.mousePressEvent = lambda event: QDesktopServices.openUrl(QUrl(repo_url))

        #     # 상태 표시줄 오른쪽에 영구 위젯으로 추가
        #     self.status_bar.addPermanentWidget(update_label)
        # else:
        #     print("✅ 현재 최신 버전을 사용 중입니다.")
    
    def update_window_title(self):
        """Git 정보를 기반으로 윈도우 타이틀을 업데이트합니다."""
        if not self.has_git:
            # Git이 없으면 기존 형식 유지
            return
        
        # 기본 타이틀에 버전 정보 추가
        title = f"{self.base_title} - {self.current_commit_sha} : {self.current_commit_date}"
        
        # 최신 버전 체크
        if self.latest_commit_sha:
            if self.current_commit_sha == self.latest_commit_sha:
                title += " (최신 버전)"
            else:
                title += f" (업데이트가 있습니다 : {self.latest_commit_date})"
        
        self.setWindowTitle(title)

    def _show_multi_account_notification(self):
        """🆕 멀티 NAI 계정 활성화 시 시작 알림 표시"""
        try:
            import json
            from pathlib import Path

            # NAI 모드가 아니면 체크하지 않음
            if self.app_context.current_api_mode != "NAI":
                return

            # save/nai_accounts.json 로드
            accounts_file = Path("save/nai_accounts.json")

            if not accounts_file.exists():
                # 계정 파일이 없으면 알림 없음
                return

            with open(accounts_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 🆕 안전장치: 자동 복구된 경우 알림 스킵
            if data.get('auto_recovered', False):
                print("ℹ️ 계정 자동 복구가 수행되었습니다. 시작 알림을 스킵합니다.")
                return

            accounts = data.get('accounts', [])
            round_robin_enabled = data.get('round_robin_enabled', False)
            main_account_enabled = data.get('main_account_enabled', True)

            # 활성화된 추가 계정 카운트
            enabled_additional_accounts = sum(1 for acc in accounts if acc.get('enabled', False))

            # 🆕 총 활성 계정 = 메인(활성화 시 1) + 활성화된 추가 계정
            total_active_accounts = (1 if main_account_enabled else 0) + enabled_additional_accounts

            # 멀티 계정이 활성화된 경우에만 알림 표시
            if total_active_accounts > 1:
                mode_text = "라운드 로빈 모드" if round_robin_enabled else "단일 계정 모드"

                # 상태바에 메시지 표시 (5초)
                message = f"🔄 멀티 NAI 계정 활성화됨: {total_active_accounts}개 계정 ({mode_text})"
                self.status_bar.showMessage(message, 5000)

                # 콘솔에도 출력
                print(f"\n{'='*60}")
                print(f"🔄 멀티 NAI 계정 시스템 활성화")
                print(f"   - 총 활성 계정: {total_active_accounts}개 (메인 {'1개' if main_account_enabled else '0개'} + 추가 {enabled_additional_accounts}개)")
                print(f"   - 운영 모드: {mode_text}")
                if round_robin_enabled:
                    print(f"   - 이미지 생성 시 카운터 기반으로 계정을 순환합니다.")
                else:
                    print(f"   - 활성화된 단일 계정만 사용됩니다.")
                print(f"{'='*60}\n")

        except Exception as e:
            print(f"⚠️ 멀티 계정 알림 표시 오류: {e}")

    def _perform_autosave_on_generation(self):
        """이미지 생성 완료 시 자동 저장 (특수 요청 제외)"""
        try:
            current_mode = self.app_context.get_api_mode()

            # 1. 프리셋 저장 (PromptEngineeringModule)
            prompt_eng_module = self.middle_section_controller.get_module_instance("PromptEngineeringModule")
            if prompt_eng_module and hasattr(prompt_eng_module, 'save_on_exit'):
                prompt_eng_module.save_on_exit()

            # 2. 생성 파라미터 저장
            self.generation_params_manager.save_mode_settings(current_mode)

            # 3. 모드 대응 모듈 저장
            self.app_context.mode_manager.save_all_current_mode()

            # 상태바에 짧게 표시 (방해되지 않도록)
            print(f"💾 자동 저장 완료")

        except Exception as e:
            # 자동 저장 실패해도 프로그램은 계속 동작
            print(f"⚠️ [Autosave] 자동 저장 실패: {e}")

    def closeEvent(self, event):
        # 프로그램 종료 시 현재 모드 설정 저장
        try:
            # 🆕 생성 스레드 안전 종료 (가장 먼저 실행)
            if hasattr(self, 'generation_controller') and self.generation_controller:
                try:
                    self.generation_controller.safe_shutdown(timeout_ms=3000)
                except Exception as e:
                    print(f"⚠️ 생성 스레드 종료 중 오류: {e}")

            # [추가] 분리된 모든 모듈 창 닫기 요청
            if self.middle_section_controller:
                self.middle_section_controller.close_all_detached_modules()

                # 퀵 프리셋 저장 (PromptEngineeringModule)
                prompt_eng_module = self.middle_section_controller.get_module_instance("PromptEngineeringModule")
                if prompt_eng_module and hasattr(prompt_eng_module, 'save_on_exit'):
                    prompt_eng_module.save_on_exit()

            self.image_window.close_all_detached_windows()

            # 모든 임시 생성 창 닫기
            if hasattr(self, 'temp_window_manager'):
                self.temp_window_manager.cleanup_all_temp_windows()

            # 모든 Img2Img 독립 윈도우 닫기
            if hasattr(self, 'img2img_window_manager'):
                self.img2img_window_manager.close_all()

            current_mode = self.app_context.get_api_mode()
            self.generation_params_manager.save_mode_settings(current_mode)

            # 모든 모드 대응 모듈들 설정 저장
            self.app_context.mode_manager.save_all_current_mode()

            print(f"💾 프로그램 종료 시 {current_mode} 모드 설정 저장 완료")

        except Exception as e:
            print(f"❌ 설정 저장 중 오류: {e}")

        event.accept()

    def get_api_mode(self) -> str:
        return self.app_context.get_api_mode()

    def on_resolution_detected(self, width: int, height: int):
        """컨트롤러로부터 받은 해상도를 콤보박스에 적용합니다."""
        resolution_str = f"{width} x {height}"
        self.resolution_combo.setCurrentText(resolution_str)
        self.resolution_is_detected = True
        self.status_bar.showMessage(f"✅ 해상도 자동 맞춤: {resolution_str}", 3000)

    def _load_resolutions(self) -> list:
        """JSON 파일에서 해상도 목록을 로드합니다."""
        resolutions_file = "save/resolutions.json"
        default_resolutions = [
            "1024 x 1024", "960 x 1088", "896 x 1152", "832 x 1216",
            "1088 x 960", "1152 x 896", "1216 x 832"
        ]

        try:
            if os.path.exists(resolutions_file):
                with open(resolutions_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 유효성 검사: 리스트이고 비어있지 않은지
                    if isinstance(loaded, list) and len(loaded) > 0:
                        print(f"✅ 해상도 로드 완료: {len(loaded)}개 항목")
                        return loaded
                    else:
                        print("⚠️ 저장된 해상도 목록이 비어있거나 유효하지 않음. 기본값 사용")
                        return default_resolutions
            else:
                print("ℹ️ 해상도 파일 없음. 기본값 사용 및 저장")
                # 기본값으로 파일 생성
                self._save_resolutions(default_resolutions)
                return default_resolutions

        except Exception as e:
            print(f"❌ 해상도 로드 실패: {e}. 기본값 사용")
            return default_resolutions

    def _save_resolutions(self, resolutions: list):
        """해상도 목록을 JSON 파일에 저장합니다."""
        resolutions_file = "save/resolutions.json"

        try:
            # print(f"[DEBUG] _save_resolutions 시작")
            # print(f"[DEBUG] 저장할 해상도: {resolutions}")
            # print(f"[DEBUG] 저장 경로: {resolutions_file}")

            # save 디렉토리 생성
            # print(f"[DEBUG] save 디렉토리 생성 시도...")
            os.makedirs("save", exist_ok=True)
            # print(f"[DEBUG] save 디렉토리 생성 완료 (또는 이미 존재)")

            # 절대 경로 확인
            # abs_path = os.path.abspath(resolutions_file)
            # print(f"[DEBUG] 절대 경로: {abs_path}")

            # JSON 저장
            # print(f"[DEBUG] JSON 파일 쓰기 시작...")
            with open(resolutions_file, 'w', encoding='utf-8') as f:
                json.dump(resolutions, f, ensure_ascii=False, indent=2)
            # print(f"[DEBUG] JSON 파일 쓰기 완료")

            # 파일 존재 확인
            # if os.path.exists(resolutions_file):
            #     file_size = os.path.getsize(resolutions_file)
            #     print(f"[DEBUG] 파일 생성 확인: {resolutions_file} (크기: {file_size} bytes)")
            # else:
            #     print(f"[DEBUG] ⚠️ 파일이 생성되지 않았음!")

            print(f"✅ 해상도 저장 완료: {len(resolutions)}개 항목")

        except Exception as e:
            print(f"❌ 해상도 저장 실패: {e}")
            import traceback
            traceback.print_exc()

    def open_resolution_manager(self):
        """해상도 관리 다이얼로그를 열고, 결과를 반영합니다."""
        dialog = ResolutionManagerDialog(self.resolutions, self)

        # print(f"[DEBUG] 해상도 관리 다이얼로그 열림")
        dialog_result = dialog.exec()
        # print(f"[DEBUG] 다이얼로그 결과: {dialog_result}")

        if dialog_result:
            new_resolutions = dialog.get_updated_resolutions()
            # print(f"[DEBUG] 새 해상도 목록: {new_resolutions} (개수: {len(new_resolutions) if new_resolutions else 0})")

            if new_resolutions:
                self.resolutions = new_resolutions

                # ✅ 파일에 저장
                # print(f"[DEBUG] _save_resolutions 호출 시작")
                self._save_resolutions(self.resolutions)
                # print(f"[DEBUG] _save_resolutions 호출 완료")

                # [수정-1] 메인 UI의 콤보박스 구성 업데이트
                current_selection = self.resolution_combo.currentText()
                self.resolution_combo.clear()
                self.resolution_combo.addItems(self.resolutions)

                # 기존 선택 항목이 새 목록에도 있으면 유지, 없으면 첫 항목 선택
                if current_selection in self.resolutions:
                    self.resolution_combo.setCurrentText(current_selection)
                else:
                    self.resolution_combo.setCurrentIndex(0) # 첫 번째 항목을 기본값으로 설정

                self.status_bar.showMessage("✅ 해상도 목록이 저장되었습니다.", 3000)
            else:
                # print(f"[DEBUG] 해상도 목록이 비어있음 - 경고 표시")
                QMessageBox.warning(self, "경고", "해상도 목록이 비어있을 수 없습니다. 변경사항이 적용되지 않았습니다.")
        # else:
        #     print(f"[DEBUG] 다이얼로그 취소됨 (exec() = False)")

    # [신규] prompt_popped 시그널을 처리할 슬롯
    def on_prompt_popped(self, remaining_count: int):
        """프롬프트가 하나 사용된 후 남은 행 개수를 UI에 업데이트합니다."""
        self.result_label2.setText(f"남음: {remaining_count}")

    # [신규] 현재 활성화된 API 모드를 반환하는 메서드
    def get_current_api_mode(self) -> str:
        """
        현재 선택된 토글 버튼에 따라 'NAI', 'WEBUI', 또는 'COMFYUI' 문자열을 반환합니다.
        """
        if self.nai_toggle_btn.isChecked():
            return "NAI"
        elif self.webui_toggle_btn.isChecked():
            return "WEBUI"
        elif self.comfyui_toggle_btn.isChecked():  # 🆕 ComfyUI 지원 추가
            return "COMFYUI"
        else:
            # 기본값은 NAI (안전장치)
            return "NAI"
        
    def connect_automation_signals(self):
        """자동화 모듈과의 시그널 연결"""
        # 자동화 모듈 찾기
        if self.middle_section_controller:
            for module in self.middle_section_controller.module_instances:
                if hasattr(module, 'automation_controller'):
                    self.automation_module = module
                    break
        
        if self.automation_module:
            try:
                # 콜백 함수 등록 (시그널 대신)
                self.automation_module.set_automation_status_callback(
                    self.update_automation_status
                )
                
                self.automation_module.set_generation_delay_callback(
                    self.on_generation_delay_changed
                )
                
                # [신규] 자동 생성 상태 확인 콜백 등록
                self.automation_module.set_auto_generate_status_callback(
                    self.get_auto_generate_status
                )

                # [신규] 자동화 활성 상태 확인 콜백 등록 (누락된 부분)
                self.automation_module.set_automation_active_status_callback(
                    self.get_automation_active_status
                )
                
                print("✅ 자동화 모듈 콜백 연결 완료")
            except Exception as e:
                print(f"⚠️ 자동화 모듈 콜백 연결 실패: {e}")
        else:
            print("⚠️ 자동화 모듈을 찾을 수 없습니다.")

    # [신규] 자동 생성 상태 확인 메서드 추가
    def get_auto_generate_status(self) -> bool:
        """현재 자동 생성 체크박스 상태를 반환"""
        try:
            auto_generate_checkbox = self.generation_checkboxes.get("자동 생성")
            if auto_generate_checkbox:
                return auto_generate_checkbox.isChecked()
            return False
        except Exception as e:
            print(f"⚠️ 자동 생성 상태 확인 실패: {e}")
            return False

    def update_automation_status(self, text: str):
        """자동화 상태 텍스트 업데이트"""
        # 상태바에 자동화 진행 상황 표시
        self.status_bar.showMessage(text)

    def on_generation_delay_changed(self, delay: float):
        """생성 지연 시간 변경 시 처리"""
        print(f"생성 지연 시간 변경: {delay}초")
        # 필요시 추가 처리 로직

    def test_webui(self, url):
        """WebUI 연결 테스트 함수"""
        import requests
        # ignore http or https, check both.
        url = url.replace('http://', '').replace('https://', '').rstrip('/')
        # just checking connection, so any api is okay.
        try:
            if "127.0" not in url: res = requests.get(f"https://{url}/sdapi/v1/progress?skip_current_image=true", timeout=1)
            else: res = requests.get(f"http://{url}/sdapi/v1/progress?skip_current_image=true", timeout=1)
            if res.status_code == 200 and 'progress' in res.json():
                return f'https://{url}'
            else:
                raise Exception('invalid status')
        except Exception:
            try:
                res = requests.get(f"http://{url}/sdapi/v1/progress?skip_current_image=true", timeout=1)
                if res.status_code == 200 and 'progress' in res.json():
                    return f'http://{url}'
                else:
                    raise Exception('invalid status')
            except Exception:
                pass
        return None
    
    def test_comfyui(self, url):
        """ComfyUI 연결 테스트 함수 (test_webui와 유사한 패턴)"""
        import requests
        
        # URL 테스트 전략: 사용자 입력 → 기본 포트들 (8000, 8188)
        test_urls = []
        original_url = url.strip().rstrip('/')

        # 1. 사용자가 입력한 URL을 그대로 먼저 시도
        if original_url.startswith('http://') or original_url.startswith('https://'):
            test_urls.append(original_url)
        else:
            # 프로토콜이 없으면 http와 https 모두 시도
            test_urls.append(f"http://{original_url}")
            test_urls.append(f"https://{original_url}")

        # 2. 포트가 없는 경우, 기본 포트들을 추가해서 재시도
        clean_url = original_url.replace('https://', '').replace('http://', '')
        has_port = ':' in clean_url.split('/')[0]  # 경로 제외하고 호스트:포트 부분만 체크

        if not has_port:
            # 원격 터널 서비스 감지 (포트 불필요)
            remote_tunnel_services = [
                'trycloudflare.com',  # Cloudflare Tunnel
                'ngrok',              # ngrok (ngrok.io, ngrok-free.app 등)
                'gradio.live',        # Gradio Share
                'serveo.net',         # Serveo
                'localhost.run',      # localhost.run
                'tunnelto.dev',       # Tunnelto
                'localtunnel.me',     # Localtunnel
            ]

            is_remote_tunnel = any(service in clean_url for service in remote_tunnel_services)

            if not is_remote_tunnel:
                # 로컬 서버: 기본 포트들 시도 (8000, 8188)
                for port in [8000, 8188]:
                    test_urls.append(f"http://{clean_url}:{port}")
                    test_urls.append(f"https://{clean_url}:{port}")
        
        for test_url in test_urls:
            try:
                print(f"🔍 ComfyUI 연결 테스트: {test_url}")
                
                # /system_stats 엔드포인트로 연결 테스트
                response = requests.get(f"{test_url}/system_stats", timeout=8)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        # ComfyUI 응답 구조 확인
                        if 'system' in data or 'devices' in data:
                            print(f"✅ ComfyUI 연결 성공: {test_url}")
                            return test_url
                    except json.JSONDecodeError:
                        continue
                
            except requests.exceptions.ConnectTimeout:
                print(f"⏰ ComfyUI 연결 시간 초과: {test_url}")
                continue
            except requests.exceptions.ConnectionError:
                print(f"❌ ComfyUI 연결 실패: {test_url}")
                continue
            except Exception as e:
                print(f"❌ ComfyUI 테스트 중 예외: {test_url} - {e}")
                continue
        
        print(f"❌ 모든 ComfyUI 연결 시도 실패: {url}")
        return None

    def connect_checkbox_signals(self):
        """체크박스 시그널을 연결하는 메서드 (init에서 호출)"""
        try:
            prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")
            if prompt_fixed_checkbox:
                prompt_fixed_checkbox.toggled.connect(self.update_random_prompt_button_state)
                
            # 초기 상태 설정
            self.update_random_prompt_button_state()
            
        except Exception as e:
            print(f"❌ 체크박스 시그널 연결 오류: {e}")

    def update_random_prompt_button_state(self):
        """generation_checkboxes 상태에 따라 random_prompt_btn을 활성화/비활성화"""
        try:
            # "프롬프트 고정" 체크박스 확인
            prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")
            prompt_fixed = prompt_fixed_checkbox and prompt_fixed_checkbox.isChecked()

            if prompt_fixed:
                # 프롬프트 고정 모드
                self.random_prompt_btn.setEnabled(False)
                self.random_prompt_btn.setText("프롬프트 고정됨")
                if hasattr(self, 'detached_random_btn'):
                    self.detached_random_btn.setEnabled(False)
                    self.detached_random_btn.setText("프롬프트 고정됨")
            else:
                # 일반 모드 (활성화)
                self.random_prompt_btn.setEnabled(True)
                self.random_prompt_btn.setText("랜덤/다음 프롬프트")
                if hasattr(self, 'detached_random_btn'):
                    self.detached_random_btn.setEnabled(True)
                    self.detached_random_btn.setText("랜덤/다음 프롬프트")

        except Exception as e:
            print(f"❌ 버튼 상태 업데이트 오류: {e}")

    def set_initial_window_size(self):
        """
        사용자의 가용 화면 해상도를 기준으로 창의 초기 크기를 설정하고
        화면 중앙에 배치합니다.
        """
        try:
            # 사용자의 주 모니터에서 작업 표시줄을 제외한 가용 영역의 정보를 가져옵니다.
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            
            # FHD 모니터 대응: 화면 크기에 따라 적절한 비율 설정
            # FHD(1920x1080) 이하에서는 더 작은 비율 사용
            width_ratio = 0.75 if screen_geometry.width() <= 1920 else 0.85
            height_ratio = 0.75 if screen_geometry.height() <= 1080 else 0.85
            
            initial_width = int(screen_geometry.width() * width_ratio)
            initial_height = int(screen_geometry.height() * height_ratio)
            
            # 계산된 크기로 창의 크기를 조절합니다.
            self.resize(initial_width, initial_height)
            
            # 창을 화면의 중앙으로 이동시킵니다.
            self.move(screen_geometry.center() - self.rect().center())
            
            print(f"🖥️ 동적 창 크기 설정 완료: {initial_width}x{initial_height}")

        except Exception as e:
            print(f"⚠️ 동적 창 크기 설정 실패: {e}. FHD 대응 기본 크기로 설정합니다.")
            # 오류 발생 시 FHD 모니터에 적합한 기본값 설정
            default_width = get_scaled_size(1200)
            default_height = get_scaled_size(650)
            self.resize(default_width, default_height)

    def show_negative_prompt_context_menu(self, pos):
        """negative_prompt_textedit에서 우클릭 시 기본 QMenu를 표시합니다."""
        # 기본 스타일의 QMenu 생성 (스타일시트 적용 없음)
        menu = self.negative_prompt_textedit.createStandardContextMenu()
        if menu:
            # 선택된 텍스트가 있으면 인스턴트 와일드카드 추가 메뉴 표시
            cursor = self.negative_prompt_textedit.textCursor()
            selected_text = cursor.selectedText().strip()
            
            if selected_text:
                # 인스턴트 와일드카드 모듈 찾기
                instant_wildcard_module = None
                if hasattr(self, 'middle_section_controller'):
                    instant_wildcard_module = self.middle_section_controller.get_module_instance("InstantWildcardModule")
                
                if instant_wildcard_module:
                    # 상단에 액션 삽입
                    actions = menu.actions()
                    add_wildcard_action = QAction("➕ 인스턴트 와일드카드 추가", menu)
                    add_wildcard_action.triggered.connect(lambda: instant_wildcard_module.add_from_selection(selected_text))
                    
                    if actions:
                        menu.insertAction(actions[0], add_wildcard_action)
                        menu.insertSeparator(actions[0])
                    else:
                        menu.addAction(add_wildcard_action)
            
            menu.exec(self.negative_prompt_textedit.mapToGlobal(pos))
    
    def show_prompt_context_menu(self, pos):
        """main_prompt_textedit에서 우클릭 시 KR_tags 정보를 포함한 커스텀 메뉴를 표시합니다."""
        menu = QMenu(self)

        # --- 0. 선택된 텍스트가 있으면 인스턴트 와일드카드 추가 메뉴 표시 ---
        cursor = self.main_prompt_textedit.textCursor()
        selected_text = cursor.selectedText().strip()
        
        if selected_text:
            # 인스턴트 와일드카드 모듈 찾기
            instant_wildcard_module = None
            if hasattr(self, 'middle_section_controller'):
                instant_wildcard_module = self.middle_section_controller.get_module_instance("InstantWildcardModule")
            
            if instant_wildcard_module:
                add_wildcard_action = QAction("➕ 인스턴트 와일드카드 추가", menu)
                add_wildcard_action.triggered.connect(lambda: instant_wildcard_module.add_from_selection(selected_text))
                menu.addAction(add_wildcard_action)
                menu.addSeparator()

        # --- 1. 커서 위치의 태그 찾기 ---
        cursor = self.main_prompt_textedit.cursorForPosition(pos)
        text = self.main_prompt_textedit.toPlainText()
        tag_under_cursor, start_pos, end_pos = self._get_tag_at_cursor(cursor)

        # --- 2. Parquet 데이터 조회 및 커스텀 메뉴 생성 ---
        if not self.kr_tags_df.empty and tag_under_cursor:
            matching_rows = self.kr_tags_df[self.kr_tags_df['tag'] == tag_under_cursor]

            if not matching_rows.empty:
                data = matching_rows.iloc[0]
                
                # 클릭 불가능한 정보 표시용 액션을 만드는 헬퍼 함수
                def create_info_action(text, font_size, is_bold=False, word_wrap=False):
                    widget_action = QWidgetAction(menu)
                    widget = QWidget()
                    layout = QHBoxLayout(widget)
                    layout.setContentsMargins(8, 4, 8, 4)
                    label = QLabel(str(text)) # 모든 텍스트를 문자열로 변환
                    style = f"font-size: {font_size}px; color: #000000;"
                    if is_bold: style += " font-weight: 600;"
                    label.setStyleSheet(style)
                    if word_wrap:
                        label.setWordWrap(True)
                        label.setMinimumWidth(300) # 줄바꿈을 위한 최소 너비
                    layout.addWidget(label)
                    widget_action.setDefaultWidget(widget)
                    widget_action.setEnabled(False) # 클릭 비활성화
                    return widget_action

                # 아이템 1: 태그 (24px) + 카운트 (14px)
                title_action = QWidgetAction(menu)
                title_widget = QWidget()
                title_layout = QHBoxLayout(title_widget)
                title_layout.setContentsMargins(8, 4, 8, 4)
                
                tag_label = QLabel(data.get('tag', ''))
                tag_label.setStyleSheet(f"font-size: {get_scaled_font_size(24)}px; font-weight: 600; color: #000000;")
                
                count_val = data.get('count', 0)
                count_label = QLabel(f"{count_val:,}" if pd.notna(count_val) else "")
                count_label.setStyleSheet(f"font-size: {get_scaled_font_size(15)}px; color: #111111;")
                
                title_layout.addWidget(tag_label)
                title_layout.addStretch()
                title_layout.addWidget(count_label)
                title_action.setDefaultWidget(title_widget)
                title_action.setEnabled(False)
                menu.addAction(title_action)
                menu.addSeparator()

                # 아이템 2: 카테고리 (18px)
                category_text = data.get('category')
                if pd.notna(category_text) and category_text:
                    menu.addAction(create_info_action(f"Category: {category_text}", 18))

                # 아이템 3: 설명 (14px, 자동 줄바꿈)
                desc_text = data.get('desc')
                if pd.notna(desc_text) and desc_text:
                    menu.addAction(create_info_action(desc_text, 15, word_wrap=True))
                
                # 아이템 4: 키워드 (14px)
                keywords_text = data.get('keywords')
                if pd.notna(keywords_text) and keywords_text:
                    menu.addAction(create_info_action(f"Keywords: {keywords_text}", 15))

                menu.addSeparator()

        # --- 3. 기존 표준 메뉴 (복사, 붙여넣기 등) 추가 ---
        standard_menu = self.main_prompt_textedit.createStandardContextMenu()
        menu.addActions(standard_menu.actions())

        menu.exec(self.main_prompt_textedit.mapToGlobal(pos))

    def _get_tag_at_cursor(self, cursor):
        """커서 위치의 태그와 시작/끝 위치를 반환하는 헬퍼 메서드"""
        cursor_pos = cursor.position()
        text = self.main_prompt_textedit.toPlainText()

        start_pos = text.rfind(',', 0, cursor_pos) + 1
        end_pos = text.find(',', cursor_pos)
        if end_pos == -1:
            end_pos = len(text)
        
        # 앞뒤 공백 제거
        temp_start = start_pos
        while temp_start < end_pos and text[temp_start].isspace():
            temp_start += 1
        
        tag = text[temp_start:end_pos].strip()
        return tag, start_pos, end_pos

    def _replace_tag_in_prompt(self, new_tag, start, end):
        """선택한 추천 태그로 프롬프트를 교체하는 헬퍼 메서드"""
        cursor = self.main_prompt_textedit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(new_tag)

    def _load_kr_tags(self):
        """data/KR_tags.parquet 파일을 로드하여 DataFrame으로 반환합니다."""
        filepath = 'data/KR_tags.parquet'
        if os.path.exists(filepath):
            try:
                print(f"🔍 '{filepath}' 파일 로딩 중...")
                df = pd.read_parquet(filepath)
                print(f"✅ '{filepath}' 로딩 완료. {len(df):,}개 태그.")
                return df
            except Exception as e:
                print(f"❌ '{filepath}' 파일 로딩 실패: {e}")
        else:
            print(f"⚠️ '{filepath}' 파일을 찾을 수 없습니다.")
        return pd.DataFrame() # 실패 시 빈 DataFrame 반환

    def save_all_current_settings(self):
        """현재 모든 설정을 저장하는 메서드"""
        try:
            current_mode = self.app_context.get_api_mode()
            
            # 버튼 상태 변경 (저장 중 표시)
            self.save_settings_btn.setText("💾 저장 중...")
            self.save_settings_btn.setEnabled(False)
            
            saved_items = []
            failed_items = []
            
            # 1. 메인 생성 파라미터 저장
            try:
                self.generation_params_manager.save_mode_settings(current_mode)
                saved_items.append("메인 생성 파라미터")
            except Exception as e:
                failed_items.append(f"메인 생성 파라미터: {str(e)}")
            
            # 2. 모든 ModeAware 모듈 설정 저장
            if self.app_context and self.app_context.mode_manager:
                try:
                    self.app_context.mode_manager.save_all_current_mode()
                    
                    # 저장된 모듈 수 계산
                    mode_aware_count = len(self.app_context.mode_manager.registered_modules)
                    if mode_aware_count > 0:
                        saved_items.append(f"모드 인식 모듈 ({mode_aware_count}개)")
                    
                except Exception as e:
                    failed_items.append(f"모드 인식 모듈: {str(e)}")
               
            # 결과 메시지 생성
            if saved_items and not failed_items:
                # 모든 저장 성공
                message = f"✅ 설정 저장 완료 ({current_mode} 모드)\n저장된 항목: {', '.join(saved_items)}"
                self.status_bar.showMessage(f"✅ 모든 설정이 저장되었습니다 ({current_mode} 모드)", 4000)
                
            elif saved_items and failed_items:
                # 일부 저장 성공, 일부 실패
                message = f"⚠️ 설정 부분 저장 완료 ({current_mode} 모드)\n✅ 저장됨: {', '.join(saved_items)}\n❌ 실패: {', '.join(failed_items)}"
                self.status_bar.showMessage(f"⚠️ 일부 설정 저장 실패", 4000)
                
            else:
                # 모든 저장 실패
                message = f"❌ 설정 저장 실패 ({current_mode} 모드)\n실패 항목: {', '.join(failed_items)}"
                self.status_bar.showMessage("❌ 설정 저장 실패", 4000)
            
            print(message)
            
            # 성공한 항목이 있으면 토스트 메시지도 표시
            if saved_items:
                # QMessageBox로 간단한 알림 표시 (자동으로 사라지지 않음, 사용자가 확인 필요)
                from PyQt6.QtWidgets import QMessageBox
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Information)
                msg.setWindowTitle("설정 저장 완료")
                msg.setText(f"현재 모드({current_mode})의 설정이 저장되었습니다.")
                
                details = f"저장된 항목:\n• " + "\n• ".join(saved_items)
                if failed_items:
                    details += f"\n\n실패한 항목:\n• " + "\n• ".join(failed_items)
                msg.setDetailedText(details)
                
                # 자동으로 닫히도록 타이머 설정 (3초 후 자동 닫기)
                from PyQt6.QtCore import QTimer
                timer = QTimer()
                timer.timeout.connect(msg.accept)
                timer.setSingleShot(True)
                timer.start(3000)  # 3초 후 자동 닫기
                
                msg.exec()
            
        except Exception as e:
            error_message = f"❌ 설정 저장 중 예외 발생: {str(e)}"
            print(error_message)
            self.status_bar.showMessage("❌ 설정 저장 중 오류 발생", 4000)
            
        finally:
            # 버튼 상태 복원
            self.save_settings_btn.setText("💾 설정 저장")
            self.save_settings_btn.setEnabled(True)

    def update_token_count(self):
        """Update the token count label based on current prompts and mode."""
        try:
            # Get token calculator
            calculator = get_token_calculator()
            if not calculator.available:
                self.main_prompt_token_label.setText("Estimated Tokens : N/A (tiktoken not available)")
                return
            
            # Get main prompt text
            main_prompt = self.main_prompt_textedit.toPlainText()
            
            # Get current API mode
            current_mode = self.get_current_api_mode()
            
            # Get character prompt if in NAI mode
            character_prompt = ""
            if current_mode == "NAI":
                try:
                    character_module = self.middle_section_controller.get_module_instance("CharacterModule")
                    if character_module and hasattr(character_module, 'modifiable_clone'):
                        characters = character_module.modifiable_clone.get('characters', [])
                        if characters and character_module.activate_checkbox.isChecked():
                            # Join all character strings into one
                            character_prompt = ' '.join(str(char) for char in characters if char)
                except Exception as e:
                    print(f"Warning: Could not get character module data: {e}")
            
            # Calculate tokens
            token_counts = calculator.count_prompt_tokens(main_prompt, character_prompt, current_mode)
            
            # Format and update label
            label_text = calculator.format_token_label(token_counts, current_mode)
            self.main_prompt_token_label.setText(label_text)
            
        except Exception as e:
            print(f"Error updating token count: {e}")
            self.main_prompt_token_label.setText("Estimated Tokens : Error")
    
    def update_negative_token_count(self):
        """Update the negative prompt token count label."""
        try:
            # Get token calculator
            calculator = get_token_calculator()
            if not calculator.available:
                self.negative_prompt_token_label.setText("Estimated Tokens : N/A (tiktoken not available)")
                return
            
            # Get negative prompt text
            negative_prompt = self.negative_prompt_textedit.toPlainText()
            
            # Calculate tokens (negative prompt only, no mode dependency)
            token_count = calculator.count_tokens(negative_prompt)
            
            # Update label with simple format
            self.negative_prompt_token_label.setText(f"Estimated Tokens : {token_count}")
            
        except Exception as e:
            print(f"Error updating negative token count: {e}")
            self.negative_prompt_token_label.setText("Estimated Tokens : Error")
    
    def _load_custom_workflow_from_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "ComfyUI 워크플로우 이미지 선택", "", "Image Files (*.png)"
        )

        if not file_path:
            return

        try:
            from core.comfyui_utils import WorkflowValidationDialog
            with Image.open(file_path) as img:
                # ComfyUI는 'prompt'와 'workflow' 키에 JSON 문자열로 저장합니다.
                metadata = img.info
                if 'prompt' not in metadata or 'workflow' not in metadata:
                    QMessageBox.warning(self, "오류", "선택한 이미지에서 ComfyUI 워크플로우 정보를 찾을 수 없습니다. 만약 NAIA에서 생성한 이미지라면 COMFYUI에서 먼저 이미지를 생성하여 저장한 뒤 NAIA로 불러와주세요.")
                    return

                # 워크플로우 분석 및 검증
                analysis_result = self.workflow_manager.analyze_workflow_for_ui(metadata)

                # 검증 결과 팝업 표시
                dialog = WorkflowValidationDialog(analysis_result, self)
                dialog.exec()

                # 검증 성공 시, 실제 워크플로우를 매니저에 로드
                if analysis_result['success']:
                    # 기존 load_workflow_from_metadata를 사용하여 워크플로우를 정식으로 로드
                    self.workflow_manager.load_workflow_from_metadata(metadata)
                    self.workflow_custom_btn.setEnabled(True)
                    self.workflow_custom_btn.setChecked(True)
                    self.status_bar.showMessage("✅ 커스텀 워크플로우가 활성화되었습니다.", 3000)

        except Exception as e:
            QMessageBox.critical(self, "파일 오류", f"이미지를 분석하는 중 오류가 발생했습니다:\n{e}")

    # [신규] 워크플로우 타입 토글 시 호출될 메서드
    def _on_workflow_type_changed(self):
        if self.workflow_default_btn.isChecked():
            self.workflow_manager.clear_user_workflow()
            # 커스텀 워크플로우가 비워졌으므로 버튼을 다시 비활성화
            self.workflow_custom_btn.setEnabled(False)
            self.status_bar.showMessage("🔄 기본 워크플로우로 전환되었습니다.", 3000)

    def _on_sampling_mode_changed(self, button):
        """ComfyUI 샘플링 모드 변경 시 Rescale CFG 가시성 제어"""
        is_anima = (button == self.anima_radio)
        # ComfyUI 모드일 때만 Rescale CFG 표시/숨김 처리
        if self.get_current_api_mode() == "COMFYUI":
            for w in self.comfyui_rescale_ui:
                w.setVisible(is_anima)

    def on_generate_with_image_requested(self, tags_dict: dict):
        """WebView에서 추출된 태그로 프롬프트를 생성하고 바로 이미지 생성을 시작합니다."""
        self.status_bar.showMessage("추출된 태그로 프롬프트 생성 및 이미지 생성 시작...")

        # 1. 프롬프트 생성 (기존 로직 재사용)
        self.on_instant_generation_requested(tags_dict)

        # 2. 프롬프트 생성이 UI에 반영된 후 이미지 생성을 트리거하기 위해 QTimer.singleShot 사용
        QTimer.singleShot(100, self.generation_controller.execute_generation_pipeline)

    def activate_img2img_panel(self, pil_image: Image.Image):
        """Img2ImgPopup의 요청을 받아 독립 Img2Img 윈도우를 엽니다."""
        print(f"🖼️ Img2Img 윈도우 열기 (이미지 크기: {pil_image.size})")
        self.img2img_window_manager.create_window(pil_image, mode='img2img')
        self.status_bar.showMessage("Img2Img 윈도우가 열렸습니다.", 3000)

    def activate_inpaint_mode(self, pil_image: Image.Image, skip_window: bool = False):
        """Img2ImgPopup의 요청을 받아 InpaintWindow → 독립 Img2Img 윈도우를 엽니다.
        skip_window=True: 스케치북 등에서 마스크를 이미 갖고 있는 경우 (기존 패널 방식)
        """
        print(f"🎨 Inpaint 모드 활성화 요청 (이미지 크기: {pil_image.size})")
        if skip_window:
            # 스케치북 등 기존 호출: img2img_panel 사용 (호출자가 이후 패널 직접 접근)
            if hasattr(self, 'img2img_panel'):
                self.img2img_panel.set_image(pil_image)
            return
        from ui.inpaint_window import InpaintWindow
        result = InpaintWindow.get_inpaint_data(pil_image, None, self)
        if result:
            mask_data = {
                'full_mask_image': result.get('full_mask_image'),
                'small_mask_image': result.get('small_mask_image'),
            }
            self.img2img_window_manager.create_window(
                pil_image, mode='inpaint', mask_data=mask_data
            )
    
    def activate_vibe_transfer(self, pil_image: Image.Image):
        """Import Vibe Transfer 요청을 처리하여 이미지를 vibe transfer 모듈에 추가합니다."""
        try:
            # VibeTransferModule 찾기
            if hasattr(self, 'middle_section_controller'):
                vibe_module = self.middle_section_controller.get_module_instance("VibeTransferModule")
                if vibe_module:
                    # 임시 파일로 저장
                    import hashlib
                    from pathlib import Path
                    temp_path = Path("temp") / f"vibe_import_{hashlib.sha256(str(pil_image).encode()).hexdigest()[:16]}.png"
                    temp_path.parent.mkdir(exist_ok=True)
                    pil_image.save(str(temp_path))
                    
                    # vibe frame 추가 (upload와 동일한 처리)
                    vibe_module._add_vibe_frame(str(temp_path))
                    print(f"📦 Vibe Transfer로 이미지 추가됨: {temp_path}")
                    self.status_bar.showMessage("Vibe Transfer로 이미지가 추가되었습니다.", 3000)
                else:
                    QMessageBox.warning(self, "경고", "Vibe Transfer 모듈을 찾을 수 없습니다.")
        except Exception as e:
            print(f"Error adding image to vibe transfer: {e}")
            QMessageBox.critical(self, "오류", f"Vibe Transfer에 이미지 추가 실패:\n{str(e)}")
    
    # ─── Tag Interrogation (Danbooru 태그 분석) ──────────────

    def on_tag_interrogation_requested(self, pil_image: Image.Image):
        """Tag Interrogation: WD14 태그 분석 요청 처리"""
        import importlib.util
        import os

        # Step 1: onnxruntime 설치 확인
        has_ort = importlib.util.find_spec('onnxruntime') is not None
        if not has_ort:
            reply = QMessageBox.question(
                self, "onnxruntime 필요",
                "태그 분석을 위해 onnxruntime 라이브러리가 필요합니다.\n"
                "설치하시겠습니까? (pip install onnxruntime)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._tag_pil_image = pil_image
                self._start_onnxruntime_install()
            return

        # Step 2: 모델 파일 확인
        base_dir = os.path.join(os.getcwd(), "data", "tagger")
        onnx_path = os.path.join(base_dir, "model.onnx")
        csv_path = os.path.join(base_dir, "selected_tags.csv")

        if not os.path.exists(onnx_path) or not os.path.exists(csv_path):
            from ui.interactive.image_tagger_block import (
                TaggerDownloadWorker, DownloadProgressDialog
            )
            self._tag_pil_image = pil_image
            self._tag_download_dialog = DownloadProgressDialog(self)
            self._tag_download_worker = TaggerDownloadWorker()
            self._tag_download_worker.progress.connect(
                lambda pct, msg: (
                    self._tag_download_dialog.progress_bar.setValue(pct),
                    self._tag_download_dialog.status_label.setText(msg)
                )
            )
            self._tag_download_worker.finished.connect(self._on_tag_download_finished)
            self._tag_download_dialog.show()
            self._tag_download_worker.start()
            return

        # Step 3: 태그 분석 실행
        from ui.interactive.image_tagger_block import TaggerWorker
        self._tag_pil_image = pil_image
        self.status_bar.showMessage("🏷️ 태그 분석 중...")

        self._tagger_worker = TaggerWorker(pil_image, general_th=0.56, character_th=0.85)
        self._tagger_worker.progress.connect(
            lambda msg: self.status_bar.showMessage(f"🏷️ {msg}")
        )
        self._tagger_worker.finished.connect(self._on_tag_interrogation_finished)
        self._tagger_worker.error.connect(self._on_tag_interrogation_error)
        self._tagger_worker.start()

    def _start_onnxruntime_install(self):
        """onnxruntime 설치를 백그라운드 스레드에서 실행"""
        import sys

        # 설치 진행 다이얼로그
        self._ort_install_dialog = QProgressDialog(
            "onnxruntime 설치 중...", None, 0, 0, self
        )
        self._ort_install_dialog.setWindowTitle("패키지 설치")
        self._ort_install_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._ort_install_dialog.setCancelButton(None)
        self._ort_install_dialog.setMinimumDuration(0)
        self._ort_install_dialog.show()

        # 워커 스레드에서 pip install 실행
        self._ort_install_thread = QThread()
        self._ort_install_worker = _PipInstallWorker(sys.executable, 'onnxruntime')
        self._ort_install_worker.moveToThread(self._ort_install_thread)
        self._ort_install_thread.started.connect(self._ort_install_worker.run)
        self._ort_install_worker.finished.connect(self._on_onnxruntime_install_finished)
        self._ort_install_worker.finished.connect(self._ort_install_thread.quit)
        self._ort_install_thread.finished.connect(self._ort_install_worker.deleteLater)
        self._ort_install_thread.finished.connect(self._ort_install_thread.deleteLater)
        self._ort_install_thread.start()

    def _on_onnxruntime_install_finished(self, success: bool, message: str):
        """onnxruntime 설치 완료 콜백"""
        if hasattr(self, '_ort_install_dialog') and self._ort_install_dialog:
            self._ort_install_dialog.close()
            self._ort_install_dialog = None

        if success:
            # 동적으로 onnxruntime import → 모듈에 ort + HAS_TAGGER_LIBS 갱신
            try:
                import onnxruntime as ort
                import ui.interactive.image_tagger_block as tagger_mod
                tagger_mod.ort = ort
                tagger_mod.HAS_TAGGER_LIBS = True
            except ImportError:
                QMessageBox.critical(
                    self, "오류",
                    "onnxruntime 설치 후 로드에 실패했습니다.\n프로그램을 재시작해주세요."
                )
                return

            QMessageBox.information(
                self, "설치 완료",
                "onnxruntime이 설치되었습니다.\n태그 분석을 자동으로 시작합니다."
            )
            # 자동으로 태그 분석 재시도
            if hasattr(self, '_tag_pil_image') and self._tag_pil_image:
                self.on_tag_interrogation_requested(self._tag_pil_image)
        else:
            QMessageBox.critical(self, "설치 실패", f"설치 중 오류:\n{message}")

    def _on_tag_download_finished(self, success: bool, message: str):
        """태그 모델 다운로드 완료"""
        if hasattr(self, '_tag_download_dialog') and self._tag_download_dialog:
            self._tag_download_dialog.close()
            self._tag_download_dialog = None
        if success:
            if hasattr(self, '_tag_pil_image') and self._tag_pil_image:
                self.on_tag_interrogation_requested(self._tag_pil_image)
        else:
            QMessageBox.warning(self, "다운로드 실패", message)

    def _on_tag_interrogation_error(self, error_msg: str):
        """태그 분석 오류"""
        self.status_bar.showMessage(f"태그 분석 실패: {error_msg}", 5000)
        QMessageBox.warning(self, "태그 분석 오류", error_msg)

    def _on_tag_interrogation_finished(self, result: dict):
        """태그 분석 완료 → 파이프라인 처리 → 결과 창 표시"""
        self.status_bar.showMessage("🏷️ 태그 분석 완료. 프롬프트 생성 중...")

        # general 태그 추출 + 언더스코어 제거
        general_tags = result.get("general", [])
        tag_strings = [t[0].replace("_", " ") for t in general_tags]
        tags_dict = {"general": tag_strings}

        # 설정 수집 (on_instant_generation_requested와 동일)
        comfyui_sampling_mode = "eps"
        if hasattr(self, 'anima_radio') and self.anima_radio.isChecked():
            comfyui_sampling_mode = "anima"
        elif hasattr(self, 'v_pred_radio') and self.v_pred_radio.isChecked():
            comfyui_sampling_mode = "v_prediction"
        elif hasattr(self, 'eps_radio') and self.eps_radio.isChecked():
            comfyui_sampling_mode = "eps"

        settings = {
            'prompt_fixed': self.generation_checkboxes["프롬프트 고정"].isChecked(),
            'auto_generate': self.generation_checkboxes["자동 생성"].isChecked(),
            'turbo_mode': self.generation_checkboxes["터보 옵션"].isChecked(),
            'wildcard_standalone': self.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
            'api_mode': self.app_context.get_api_mode(),
            'comfyui_sampling_mode': comfyui_sampling_mode
        }

        # 파이프라인 정제 (side-effect 없음)
        final_prompt = self.prompt_gen_controller.generate_instant_source_silent(tags_dict, settings)
        if final_prompt is None:
            final_prompt = ", ".join(tag_strings)

        # 결과 윈도우 표시
        from ui.tag_result_window import TagResultWindow

        self._tag_result_window = TagResultWindow(
            pil_image=self._tag_pil_image,
            prompt_text=final_prompt,
            parent=None
        )
        self._tag_result_window.apply_to_main_prompt.connect(
            lambda text: self.main_prompt_textedit.setPlainText(text)
        )
        self._tag_result_window.instant_generate_requested.connect(
            self._on_tag_result_instant_generate
        )
        self._tag_result_window.img2img_requested.connect(
            self._on_tag_result_img2img
        )
        self._tag_result_window.inpaint_requested.connect(
            self._on_tag_result_inpaint
        )
        self._tag_result_window.show()
        self.status_bar.showMessage("🏷️ 태그 분석 결과가 표시되었습니다.", 3000)

    def _on_tag_result_instant_generate(self, prompt_text: str):
        """태그 결과 창에서 즉시 생성 요청"""
        overrides = {'input': prompt_text}
        self.generation_controller.execute_generation_pipeline(overrides=overrides)

    def _on_tag_result_img2img(self, pil_image, prompt_text: str):
        """태그 결과 창에서 img2img 요청"""
        self.main_prompt_textedit.setPlainText(prompt_text)
        self.img2img_window_manager.create_window(pil_image, mode='img2img')

    def _on_tag_result_inpaint(self, pil_image, prompt_text: str):
        """태그 결과 창에서 Inpaint 요청"""
        self.main_prompt_textedit.setPlainText(prompt_text)
        from ui.inpaint_window import InpaintWindow
        result = InpaintWindow.get_inpaint_data(pil_image, None, self)
        if result:
            mask_data = {
                'full_mask_image': result.get('full_mask_image'),
                'small_mask_image': result.get('small_mask_image'),
            }
            self.img2img_window_manager.create_window(
                pil_image, mode='inpaint', mask_data=mask_data
            )

    def apply_prompt_from_metadata(self, prompt: str, negative: str):
        """메타데이터에서 프롬프트를 적용합니다."""
        try:
            # 메인 프롬프트 적용
            if hasattr(self, 'prompt_input'):
                self.prompt_input.setPlainText(prompt)
            
            # 네거티브 프롬프트 적용
            if hasattr(self, 'negative_prompt_input'):
                self.negative_prompt_input.setPlainText(negative)
            
            print(f"✅ 메타데이터에서 프롬프트 적용 완료")
            self.status_bar.showMessage("프롬프트가 적용되었습니다.", 3000)
        except Exception as e:
            print(f"❌ 프롬프트 적용 중 오류: {e}")
    
    def apply_settings_from_metadata(self, settings: dict):
        """메타데이터에서 설정값을 일괄 적용합니다."""
        try:
            current_mode = self.app_context.get_api_mode()
            
            # 메타데이터에서 소스 모드 감지
            source_mode = self._detect_metadata_source_mode(settings)
            
            # 모드 호환성 체크
            if source_mode and source_mode != current_mode:
                # NAI ↔ WEBUI 간 상호 호환 불가
                if (source_mode == "NAI" and current_mode == "WEBUI") or \
                   (source_mode == "WEBUI" and current_mode == "NAI"):
                    error_msg = QMessageBox(self)
                    error_msg.setWindowTitle("호환되지 않는 모드")
                    error_msg.setText(f"{source_mode} 모드의 설정값을 {current_mode} 모드에서 적용할 수 없습니다.\n\n"
                                     f"동일한 모드로 전환한 후 다시 시도해주세요.")
                    error_msg.setIcon(QMessageBox.Icon.Critical)
                    
                    # 다크 테마 및 하얀 텍스트 적용
                    error_msg.setStyleSheet("""
                        QMessageBox {
                            background-color: #2b2b2b;
                            color: white;
                        }
                        QMessageBox QLabel {
                            color: white;
                        }
                        QMessageBox QPushButton {
                            background-color: #404040;
                            border: 1px solid #555555;
                            color: white;
                            padding: 5px 15px;
                            border-radius: 3px;
                        }
                        QMessageBox QPushButton:hover {
                            background-color: #505050;
                        }
                        QMessageBox QPushButton:pressed {
                            background-color: #353535;
                        }
                    """)
                    
                    error_msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                    error_msg.exec()
                    return
            
            # 경고 메시지 표시
            has_characters = 'characters' in settings
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("설정값 일괄 적용")
            if has_characters:
                msg_box.setText("현재 프리셋의 설정값이 소실되며,\n캐릭터 프롬프트가 추가됩니다.\n(기존 캐릭터는 비활성화)\n\n계속하시겠습니까?")
            else:
                msg_box.setText("현재 프리셋의 설정값이 소실됩니다.\n계속하시겠습니까?")
            msg_box.setIcon(QMessageBox.Icon.Warning)
            
            # 다크 테마 및 하얀 텍스트 적용
            msg_box.setStyleSheet("""
                QMessageBox {
                    background-color: #2b2b2b;
                    color: white;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #404040;
                    border: 1px solid #555555;
                    color: white;
                    padding: 5px 15px;
                    border-radius: 3px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #505050;
                }
                QMessageBox QPushButton:pressed {
                    background-color: #353535;
                }
            """)
            
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
            
            if msg_box.exec() != QMessageBox.StandardButton.Yes:
                return
            
            print(f"📝 메타데이터 설정 적용 시작 (모드: {current_mode})")
            
            # 랜덤 해상도 및 자동 해상도 맞춤 비활성화
            if hasattr(self, 'random_resolution_checkbox'):
                self.random_resolution_checkbox.setChecked(False)
                print("  ✓ 랜덤 해상도: 비활성화")
            
            if hasattr(self, 'auto_fit_resolution_checkbox'):
                self.auto_fit_resolution_checkbox.setChecked(False)
                print("  ✓ 자동 해상도 맞춤: 비활성화")
            
            # 시드 고정 활성화
            if hasattr(self, 'seed_checkbox'):
                self.seed_checkbox.setChecked(True)
                print("  ✓ 시드 고정: 활성화")
            
            # 호환성 딕셔너리 생성 (prompt_engineering_module 참조)
            compat_settings = self._create_metadata_compatibility_dict(settings, current_mode)
            
            # 프롬프트 적용
            if 'prompt' in compat_settings:
                if hasattr(self, 'main_prompt_textedit'):
                    self.main_prompt_textedit.setPlainText(compat_settings['prompt'])
                elif hasattr(self, 'prompt_input'):
                    self.prompt_input.setPlainText(compat_settings['prompt'])
                print(f"  ✓ 프롬프트 적용 (길이: {len(compat_settings['prompt'])})")
            
            if 'negative' in compat_settings:
                if hasattr(self, 'negative_prompt_textedit'):
                    self.negative_prompt_textedit.setPlainText(compat_settings['negative'])
                elif hasattr(self, 'negative_prompt_input'):
                    self.negative_prompt_input.setPlainText(compat_settings['negative'])
                print(f"  ✓ 네거티브 적용 (길이: {len(compat_settings['negative'])})")
            
            # apply_main_ui_settings 스타일로 설정 적용
            if current_mode == "NAI":
                self._apply_nai_settings(compat_settings)
            elif current_mode == "WEBUI":
                self._apply_webui_settings(compat_settings)
            elif current_mode == "COMFYUI":
                self._apply_comfyui_settings(compat_settings)

            # 캐릭터 프롬프트 적용 (settings에 characters 키가 있을 때만)
            if 'characters' in settings:
                self._apply_character_settings_from_metadata(settings)

            print(f"✅ 메타데이터 설정 적용 완료")
            # 성공 메시지는 출력하지 않음 (사용자 요청)

        except Exception as e:
            import traceback
            print(f"❌ 설정값 적용 중 오류: {e}")
            traceback.print_exc()
            self.status_bar.showMessage(f"설정 적용 중 일부 오류 발생: {e}", 5000)

    def _apply_character_settings_from_metadata(self, settings: dict):
        """메타데이터의 캐릭터 프롬프트를 CharacterModule에 적용

        기존 캐릭터 위젯은 유지하고, 최하단에 새 위젯을 추가하여
        메타데이터 캐릭터 프롬프트를 할당한 뒤 자동으로 활성화합니다.
        """
        try:
            characters = settings.get('characters', [])
            characters_uc = settings.get('characters_uc', [])

            if not characters:
                return

            if not hasattr(self, 'middle_section_controller'):
                print("  ⚠️ middle_section_controller를 찾을 수 없습니다.")
                return

            char_module = self.middle_section_controller.get_module_instance("CharacterModule")
            if not char_module:
                print("  ⚠️ CharacterModule을 찾을 수 없습니다.")
                return

            # 기존 위젯 비활성화
            for widget in char_module.character_widgets:
                widget.active_checkbox.setChecked(False)

            # 최하단에 새 캐릭터 위젯 추가
            for i, char_prompt in enumerate(characters):
                char_uc = characters_uc[i] if i < len(characters_uc) else ""
                char_module.add_character_widget(
                    prompt_text=char_prompt,
                    uc_text=char_uc,
                    is_enabled=True
                )

            # CharacterModule 활성화
            if hasattr(char_module, 'activate_checkbox') and char_module.activate_checkbox:
                char_module.activate_checkbox.setChecked(True)

            # 미리보기 갱신
            if hasattr(char_module, 'process_and_update_view'):
                char_module.process_and_update_view()

            print(f"  ✓ 캐릭터 프롬프트 적용 ({len(characters)}명 추가, 기존 유지)")

        except Exception as e:
            print(f"  ⚠️ 캐릭터 적용 실패: {e}")

    def _detect_metadata_source_mode(self, settings: dict) -> str:
        """메타데이터에서 소스 모드를 감지합니다."""
        # Software 필드 확인 (NAI)
        if 'Software' in settings and settings['Software'] == 'NovelAI':
            return 'NAI'
        
        # type 필드 확인
        if 'type' in settings:
            type_info = settings['type'].lower()
            if type_info == 'nai':
                return 'NAI'
            elif type_info == 'webui':
                return 'WEBUI'
            elif type_info == 'comfyui':
                return 'COMFYUI'
        
        # NAI 전용 파라미터 확인
        nai_specific = ['noise_schedule', 'sm', 'sm_dyn', 'dynamic_thresholding', 
                       'controlnet_strength', 'legacy', 'skip_cfg_above_sigma', 
                       'uncond_scale', 'cfg_rescale']
        for param in nai_specific:
            if param in settings:
                return 'NAI'
        
        # WebUI 전용 파라미터 확인
        webui_specific = ['enable_hr', 'hr_scale', 'hr_upscaler', 'denoising_strength',
                         'Model hash', 'Model', 'VAE', 'VAE hash', 'Clip skip',
                         'Face restoration', 'RNG', 'Hires upscaler']
        for param in webui_specific:
            if param in settings:
                return 'WEBUI'
        
        # parameters 필드 내부 확인
        if 'parameters' in settings:
            params = settings['parameters']
            # WebUI 스타일 parameters
            if any(key in params for key in ['Model hash', 'Model', 'VAE']):
                return 'WEBUI'
        
        # ComfyUI workflow 확인
        if 'workflow' in settings:
            return 'COMFYUI'
        
        # 기본값: None (알 수 없음)
        return None
    
    def _create_metadata_compatibility_dict(self, settings: dict, mode: str) -> dict:
        """메타데이터를 현재 모드에 맞게 변환하는 호환성 딕셔너리 생성"""
        compat = {}
        
        # 프롬프트 매핑
        if 'prompt' in settings:
            compat['prompt'] = settings['prompt']
        
        # 네거티브 프롬프트 매핑 (uc, negative, negative_prompt 등)
        if 'negative' in settings:
            compat['negative'] = settings['negative']
        elif 'uc' in settings:
            compat['negative'] = settings['uc']
        elif 'negative_prompt' in settings:
            compat['negative'] = settings['negative_prompt']
        
        # Steps 매핑
        if 'steps' in settings:
            compat['steps'] = int(settings['steps'])
        
        # CFG Scale 매핑 (scale, cfg_scale)
        if 'scale' in settings:
            compat['cfg_scale'] = float(settings['scale'])
        elif 'cfg_scale' in settings:
            compat['cfg_scale'] = float(settings['cfg_scale'])
        
        # Seed 매핑
        if 'seed' in settings:
            compat['seed'] = str(settings['seed'])
        
        # Sampler 매핑
        if 'sampler' in settings:
            compat['sampler'] = settings['sampler']
        
        # NAI 전용 파라미터
        if mode == "NAI":
            # Noise Schedule
            if 'noise_schedule' in settings:
                compat['noise_schedule'] = settings['noise_schedule']
            
            # SMEA 관련
            if 'sm' in settings:
                compat['SMEA'] = bool(settings['sm'])
            if 'sm_dyn' in settings:
                compat['DYN'] = bool(settings['sm_dyn'])
            
            # VAR+ (skip_cfg_above_sigma)
            if 'skip_cfg_above_sigma' in settings:
                skip_val = settings['skip_cfg_above_sigma']
                compat['VAR+'] = bool(skip_val and skip_val != 0)
            elif 'VAR+' in settings:
                compat['VAR+'] = bool(settings['VAR+'])
            
            # DECRISP
            if 'decrisper' in settings:
                compat['DECRISP'] = bool(settings['decrisper'])
            elif 'DECRISP' in settings:
                compat['DECRISP'] = bool(settings['DECRISP'])
            
            # UC Strength
            if 'uncond_scale' in settings:
                compat['uncond_scale'] = float(settings['uncond_scale'])
            
            # CFG Rescale
            if 'cfg_rescale' in settings:
                compat['cfg_rescale'] = float(settings['cfg_rescale'])
        
        # WEBUI 전용 파라미터
        elif mode == "WEBUI":
            # Scheduler
            if 'scheduler' in settings:
                compat['scheduler'] = settings['scheduler']
            elif 'noise_schedule' in settings:
                # NAI noise_schedule을 WEBUI scheduler로 매핑
                schedule_mapping = {
                    'native': 'karras',
                    'karras': 'karras',
                    'exponential': 'exponential',
                    'polyexponential': 'normal'
                }
                compat['scheduler'] = schedule_mapping.get(settings['noise_schedule'], 'normal')
            
            # Sampler 변환 (NAI → WEBUI)
            if 'sampler' in compat:
                sampler_mapping = {
                    'k_euler_ancestral': 'Euler a',
                    'k_euler': 'Euler',
                    'k_dpmpp_2m': 'DPM++ 2M',
                    'k_dpmpp_2s_ancestral': 'DPM++ 2S a',
                    'k_dpmpp_sde': 'DPM++ SDE',
                    'k_dpmpp_2m_sde': 'DPM++ 2M SDE',
                    'ddim_v3': 'DDIM'
                }
                if compat['sampler'] in sampler_mapping:
                    compat['sampler'] = sampler_mapping[compat['sampler']]
            
            # Hires Fix
            if 'enable_hr' in settings:
                compat['enable_hr'] = bool(settings['enable_hr'])
            if 'hr_scale' in settings:
                compat['hr_scale'] = float(settings['hr_scale'])
            if 'hr_upscaler' in settings:
                compat['hr_upscaler'] = settings['hr_upscaler']
            if 'denoising_strength' in settings:
                compat['denoising_strength'] = float(settings['denoising_strength'])
        
        # 해상도
        if 'width' in settings and 'height' in settings:
            compat['width'] = int(settings['width'])
            compat['height'] = int(settings['height'])
        
        # 모델 정보
        if 'model' in settings:
            compat['model'] = settings['model']
        
        return compat
    
    def _apply_nai_settings(self, settings: dict):
        """NAI 모드 설정 적용"""
        print(f"  NAI 설정 적용 중...")
        
        # CFG Scale
        if 'cfg_scale' in settings and hasattr(self, 'cfg_scale_slider'):
            slider_value = int(float(settings['cfg_scale']) * 10)
            self.cfg_scale_slider.setValue(slider_value)
            if hasattr(self, 'cfg_value_label'):
                self.cfg_value_label.setText(str(settings['cfg_scale']))
            print(f"    ✓ CFG Scale: {settings['cfg_scale']}")
        
        # CFG Rescale (NAI 전용)
        if 'cfg_rescale' in settings and hasattr(self, 'cfg_rescale_slider'):
            slider_value = int(float(settings['cfg_rescale']) * 100)
            self.cfg_rescale_slider.setValue(slider_value)
            print(f"    ✓ CFG Rescale: {settings['cfg_rescale']}")
        
        # Sampler (독립적으로 적용)
        if 'sampler' in settings and hasattr(self, 'sampler_combo'):
            sampler_text = settings['sampler']
            index = self.sampler_combo.findText(sampler_text)
            if index >= 0:
                self.sampler_combo.setCurrentIndex(index)
                print(f"    ✓ Sampler: {sampler_text}")
        
        # Scheduler (별도 콤보박스로 적용)
        if 'noise_schedule' in settings and hasattr(self, 'scheduler_combo'):
            scheduler_text = settings['noise_schedule']
            index = self.scheduler_combo.findText(scheduler_text)
            if index >= 0:
                self.scheduler_combo.setCurrentIndex(index)
                print(f"    ✓ Scheduler: {scheduler_text}")
        elif 'scheduler' in settings and hasattr(self, 'scheduler_combo'):
            scheduler_text = settings['scheduler']
            index = self.scheduler_combo.findText(scheduler_text)
            if index >= 0:
                self.scheduler_combo.setCurrentIndex(index)
                print(f"    ✓ Scheduler: {scheduler_text}")
        
        # Steps
        if 'steps' in settings and hasattr(self, 'steps_spinbox'):
            self.steps_spinbox.setValue(int(settings['steps']))
            print(f"    ✓ Steps: {settings['steps']}")
        
        # Advanced checkboxes
        if hasattr(self, 'advanced_checkboxes'):
            for key in ['SMEA', 'DYN', 'VAR+', 'DECRISP']:
                if key in settings and key in self.advanced_checkboxes:
                    self.advanced_checkboxes[key].setChecked(bool(settings[key]))
                    print(f"    ✓ {key}: {settings[key]}")
        
        # Seed
        if 'seed' in settings:
            if hasattr(self, 'seed_checkbox'):
                self.seed_checkbox.setChecked(True)
            if hasattr(self, 'seed_input'):
                self.seed_input.setText(str(settings['seed']))
                print(f"    ✓ Seed: {settings['seed']}")
        
        # Model
        if 'model' in settings and hasattr(self, 'model_combo'):
            index = self.model_combo.findText(settings['model'])
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
                print(f"    ✓ Model: {settings['model']}")
        
        # Resolution
        if 'width' in settings and 'height' in settings and hasattr(self, 'resolution_combo'):
            resolution_text = f"{settings['width']} x {settings['height']}"
            index = self.resolution_combo.findText(resolution_text)
            if index >= 0:
                self.resolution_combo.setCurrentIndex(index)
                print(f"    ✓ Resolution: {resolution_text}")
    
    def _apply_webui_settings(self, settings: dict):
        """WEBUI 모드 설정 적용"""
        print(f"  WEBUI 설정 적용 중...")
        
        # CFG Scale
        if 'cfg_scale' in settings and hasattr(self, 'cfg_scale_slider'):
            slider_value = int(float(settings['cfg_scale']) * 10)
            self.cfg_scale_slider.setValue(slider_value)
            print(f"    ✓ CFG Scale: {settings['cfg_scale']}")
        
        # Sampler
        if 'sampler' in settings and hasattr(self, 'sampler_combo'):
            index = self.sampler_combo.findText(settings['sampler'])
            if index >= 0:
                self.sampler_combo.setCurrentIndex(index)
                print(f"    ✓ Sampler: {settings['sampler']}")
        
        # Steps
        if 'steps' in settings and hasattr(self, 'steps_spinbox'):
            self.steps_spinbox.setValue(int(settings['steps']))
            print(f"    ✓ Steps: {settings['steps']}")
        
        # Scheduler
        if 'scheduler' in settings and hasattr(self, 'scheduler_combo'):
            index = self.scheduler_combo.findText(settings['scheduler'])
            if index >= 0:
                self.scheduler_combo.setCurrentIndex(index)
                print(f"    ✓ Scheduler: {settings['scheduler']}")
        
        # Hires Fix
        if 'enable_hr' in settings and hasattr(self, 'enable_hr_checkbox'):
            self.enable_hr_checkbox.setChecked(bool(settings['enable_hr']))
            print(f"    ✓ Hires Fix: {settings['enable_hr']}")
        
        if 'hr_scale' in settings and hasattr(self, 'hr_scale_spinbox'):
            self.hr_scale_spinbox.setValue(float(settings['hr_scale']))
            print(f"    ✓ HR Scale: {settings['hr_scale']}")
        
        if 'hr_upscaler' in settings and hasattr(self, 'hr_upscaler_combo'):
            index = self.hr_upscaler_combo.findText(settings['hr_upscaler'])
            if index >= 0:
                self.hr_upscaler_combo.setCurrentIndex(index)
                print(f"    ✓ HR Upscaler: {settings['hr_upscaler']}")
        
        # Denoising strength
        if 'denoising_strength' in settings and hasattr(self, 'denoising_strength_slider'):
            slider_value = int(float(settings['denoising_strength']) * 100)
            self.denoising_strength_slider.setValue(slider_value)
            print(f"    ✓ Denoising Strength: {settings['denoising_strength']}")
        
        # Model
        if 'model' in settings and hasattr(self, 'model_combo'):
            index = self.model_combo.findText(settings['model'])
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
                print(f"    ✓ Model: {settings['model']}")
        
        # Seed
        if 'seed' in settings:
            if hasattr(self, 'seed_checkbox'):
                self.seed_checkbox.setChecked(True)
            if hasattr(self, 'seed_input'):
                self.seed_input.setText(str(settings['seed']))
                print(f"    ✓ Seed: {settings['seed']}")
        
        # Resolution
        if 'width' in settings and 'height' in settings and hasattr(self, 'resolution_combo'):
            resolution_text = f"{settings['width']} x {settings['height']}"
            index = self.resolution_combo.findText(resolution_text)
            if index >= 0:
                self.resolution_combo.setCurrentIndex(index)
                print(f"    ✓ Resolution: {resolution_text}")
    
    def _apply_comfyui_settings(self, settings: dict):
        """COMFYUI 모드 설정 적용"""
        print(f"  COMFYUI 설정 적용 중...")
        
        # COMFYUI는 워크플로우 기반이므로 기본적인 프롬프트만 적용
        if 'workflow' in settings:
            print(f"    ℹ️ Workflow: {settings['workflow']}")
        
        # 해상도는 공통으로 적용 가능
        if 'width' in settings and 'height' in settings and hasattr(self, 'resolution_combo'):
            resolution_text = f"{settings['width']} x {settings['height']}"
            index = self.resolution_combo.findText(resolution_text)
            if index >= 0:
                self.resolution_combo.setCurrentIndex(index)
                print(f"    ✓ Resolution: {resolution_text}")
    
    def send_to_img2img_with_metadata(self, pil_image: Image.Image, metadata: dict):
        """메타데이터와 함께 독립 Img2Img 윈도우를 엽니다."""
        try:
            # 메타데이터에서 프롬프트 추출 시 메인 프롬프트에 설정
            if 'prompt' in metadata and metadata['prompt']:
                self.main_prompt_textedit.setPlainText(metadata['prompt'])
            self.img2img_window_manager.create_window(pil_image, mode='img2img')
            print(f"✅ 이미지와 메타데이터로 Img2Img 윈도우 열기 완료")
            self.status_bar.showMessage("Img2Img 윈도우가 열렸습니다.", 3000)
        except Exception as e:
            print(f"❌ img2img 전송 중 오류: {e}")

    def on_send_to_inpaint_requested(self, history_item):
        """InpaintWindow에서 마스크 그린 후 → 독립 윈도우 열기"""
        if not history_item or not hasattr(history_item, 'image'):
            return

        pil_image = history_item.image

        from ui.inpaint_window import InpaintWindow
        result = InpaintWindow.get_inpaint_data(pil_image, None, self)
        if result is None:
            return

        mask_data = {
            'full_mask_image': result.get('full_mask_image'),
            'small_mask_image': result.get('small_mask_image'),
        }
        self.img2img_window_manager.create_window(
            pil_image=pil_image,
            mode='inpaint',
            mask_data=mask_data,
            history_item=history_item
        )

    def on_send_to_img2img_requested(self, history_item):
        """독립 Img2Img 윈도우 열기"""
        if not history_item or not hasattr(history_item, 'image'):
            return
        self.img2img_window_manager.create_window(
            pil_image=history_item.image,
            mode='img2img',
            history_item=history_item
        )

    def on_instant_outpaint_requested(self, history_item):
        """즉시 Auto-Outpainting 실행 (img2img 패널 바이패스)"""
        if not history_item or not hasattr(history_item, 'image'):
            return
        pil_image = history_item.image
        byte_arr = BytesIO()
        pil_image.save(byte_arr, format='PNG')
        overrides = {
            "image_bytes": byte_arr.getvalue(),
            "type": "auto_outpainting",
            "strength": 0.70,
            "noise": 0.00,
            "width": pil_image.width,
            "height": pil_image.height,
        }
        self.status_bar.showMessage("🎨 Instant Outpainting 요청 중...", 3000)
        self.generation_controller.execute_generation_pipeline(overrides=overrides)

    def on_send_to_outpaint_requested(self, history_item):
        """OutpaintWindow → 독립 윈도우로 결과 전달"""
        if not history_item or not hasattr(history_item, 'image'):
            return
        pil_image = history_item.image

        from ui.outpaint_window import OutpaintWindow
        result = OutpaintWindow.get_outpaint_data(pil_image, self)
        if result is None:
            return

        self.img2img_window_manager.create_window(
            pil_image=pil_image,
            mode='auto_outpainting',
            outpaint_data=result,
            history_item=history_item,
            auto_generate=True
        )

    def on_img2img_window_generate(self, _window_id: int, params: dict):
        """독립 Img2Img 윈도우에서 생성 요청"""
        # 배치 반복 생성 셋업
        batch_total = params.get('img2img_batch_total', 1)
        if batch_total > 1:
            self.img2img_window_manager.setup_batch(_window_id, params, batch_total)
            params['img2img_batch_request'] = True
            params['img2img_batch_window_id'] = _window_id
        self.generation_controller.execute_generation_pipeline(overrides=params)

    def on_save_to_remote_event_requested(self, history_item):
        """🆕 리모트 이벤트 저장 요청 처리"""
        if not history_item:
            print("⚠️ history_item이 없습니다.")
            return

        # RemoteWindow가 열려있다면 직접 추가
        if self.remote_window_open and self.remote_window:
            self.remote_window.add_remote_event(history_item)
            self.status_bar.showMessage("📌 리모트 이벤트가 저장되었습니다.", 3000)
        else:
            # RemoteWindow가 없으면 열고 추가
            self._open_remote_window()
            if self.remote_window:
                self.remote_window.add_remote_event(history_item)
                self.status_bar.showMessage("📌 리모트 이벤트가 저장되었습니다.", 3000)

    def update_splitter_stretch_factors(self):
        """좌측 패널의 실제 필요 공간에 따라 splitter의 stretch factor를 동적으로 조정"""
        if not (hasattr(self, 'search_result_frame') and hasattr(self, 'main_splitter')):
            return
            
        # 현재 윈도우 크기
        window_width = self.width()
        if window_width <= 0:
            return
            
        # 좌측 패널의 핵심 컴포넌트들의 최소 필요 너비 계산
        search_frame_width = 0
        gen_button_width = 0
        
        try:
            # search_result_frame 내부 요소들의 실제 필요 너비를 정확히 계산
            if hasattr(self, 'search_result_frame') and self.search_result_frame:
                # search_result_frame 내부의 모든 자식 위젯들의 너비 합산
                children_width = 0
                layout = self.search_result_frame.layout()
                
                if layout:
                    # 레이아웃 내부의 모든 아이템들의 너비 계산
                    for i in range(layout.count()):
                        item = layout.itemAt(i)
                        if item and item.widget():
                            widget = item.widget()
                            # 위젯의 실제 필요 너비 (sizeHint 기준)
                            widget_width = widget.sizeHint().width()
                            children_width += widget_width
                    
                    # 레이아웃 spacing 고려
                    if layout.count() > 1:
                        children_width += layout.spacing() * (layout.count() - 1)
                
                # frame의 margins/padding 고려
                frame_margins = get_scaled_size(20)  # frame 자체의 여백
                layout_margins = get_scaled_size(20)  # 레이아웃 여백
                safety_margin = get_scaled_size(40)   # 안전 여백
                
                search_frame_width = children_width + frame_margins + layout_margins + safety_margin
                
                # 최소 너비 보장 (너무 작아지는 것을 방지)
                min_search_width = get_scaled_size(450)  # 검색 결과 프레임 최소 너비
                search_frame_width = max(search_frame_width, min_search_width)
                
            # gen_button_layout의 실제 필요 너비  
            if hasattr(self, 'gen_button_layout'):
                gen_button_width = (
                    self.random_prompt_btn.sizeHint().width() +
                    self.generate_button_main.sizeHint().width() +
                    get_scaled_size(30)  # spacing과 여백
                )
        except Exception as e:
            # 계산 실패 시 안전한 기본값 사용 (로그는 디버깅 시에만)
            search_frame_width = get_scaled_size(500)
            gen_button_width = get_scaled_size(400)
        
        # 좌측 패널이 실제로 필요한 최소 너비
        left_min_required = max(search_frame_width, gen_button_width, get_scaled_size(550))
        
        # DPI와 UI 사이즈에 따른 동적 최소 stretch 계산
        # 사용자의 splitter 조정 기능을 보장하면서도 내용이 잘리지 않도록 함
        min_left_ratio = left_min_required / window_width
        
        # DPI별 기본 최소/최대 stretch 범위 설정
        from ui.scaling_manager import get_current_scale_factor
        dpi_scale = get_current_scale_factor()
        
        if dpi_scale <= 1.0:  # 100% 스케일 (FHD 등)
            base_min_stretch = 25  # 최소 20%
            base_max_stretch = 40  # 최대 40%
        elif dpi_scale <= 1.5:  # 125-150% 스케일
            base_min_stretch = 28  # 약간 증가
            base_max_stretch = 42
        else:  # 175% 이상 (고DPI)
            base_min_stretch = 32  # 더 많은 공간 필요
            base_max_stretch = 45
        
        # 계산된 최소 요구사항에 따라 동적 조정
        dynamic_min_stretch = max(base_min_stretch, int(min_left_ratio * 100))
        dynamic_max_stretch = max(base_max_stretch, dynamic_min_stretch + 5)  # 최소한의 조정 여유
        
        # FHD 해상도 기준 적응적 비율 계산
        if window_width <= get_scaled_size(1920):  # FHD 이하
            # FHD에서는 좌측 패널 비율을 줄여서 우측 패널(이미지 뷰어)에 더 많은 공간 할당
            target_ratio = max(0.30, min(0.40, left_min_required / window_width))
        else:  # QHD 이상
            # 고해상도에서는 기존 비율 유지
            target_ratio = max(0.40, min(0.50, left_min_required / window_width))
            
        # stretch factor 계산 (100 기준)
        left_stretch = int(target_ratio * 100)
        right_stretch = 100 - left_stretch
        
        # 동적으로 계산된 최소/최대 제한 적용
        left_stretch = max(dynamic_min_stretch, min(dynamic_max_stretch, left_stretch))
        right_stretch = 100 - left_stretch
        
        # stretch factor 업데이트
        self.main_splitter.setStretchFactor(0, left_stretch)
        self.main_splitter.setStretchFactor(1, right_stretch)
    
    def resizeEvent(self, event):
        """윈도우 크기 변경 시 splitter stretch factor 업데이트"""
        super().resizeEvent(event)
        
        # 초기화가 완료된 후에만 실행
        if hasattr(self, 'search_result_frame') and hasattr(self, 'main_splitter'):
            # 약간의 지연을 주어 UI 렌더링 완료 후 업데이트
            QTimer.singleShot(50, self.update_splitter_stretch_factors)

if __name__ == "__main__":
    # 기존 환경 설정들...
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "RoundPreferFloor"
    
    setup_webengine()
    app = QApplication(sys.argv)
    
    # 기존 DPI 및 폰트 설정들...
    loaded_fonts = load_custom_fonts()
    
    # 기본 폰트 설정
    if loaded_fonts:
        default_font = QFont("Pretendard", 12)
        try:
            default_font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
            default_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        except AttributeError:
            pass
        app.setFont(default_font)
        print(f"Pretendard 폰트가 기본 폰트로 설정되었습니다.")
    else:
        default_font = QFont("Segoe UI", 12)
        try:
            default_font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
            default_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        except AttributeError:
            pass
        app.setFont(default_font)
        print("Pretendard 폰트를 찾을 수 없어 시스템 기본 폰트를 사용합니다.")
    
    # 메인 윈도우 생성
    window = ModernMainWindow()

    window.show()
    sys.exit(app.exec())

## 생성형 AI 개발 가이드라인
"""
이 문서는 생성형 AI가 NAIA 프로젝트의 코드를 수정하거나 새로운 기능을 추가할 때
따라야 할 가이드라인을 정의합니다.

1.  아키텍처 존중 (Respect the Architecture)
    -   코드를 수정하기 전에, 반드시 현재의 아키텍처(AppContext, Controller, Pipeline Hook)를
        먼저 이해해야 합니다.
    -   핵심 로직을 직접 수정하기보다는, 가급적 모듈과 훅 시스템을 통해 기능을 확장하십시오.

2.  모듈성 및 단일 책임 원칙 (Modularity and Single Responsibility)
    -   새로운 기능은 독립적인 모듈 또는 클래스로 구현하는 것을 지향합니다.
    -   하나의 클래스나 메서드는 하나의 명확한 책임만 갖도록 작성하십시오.

3.  비동기 처리 (Asynchronous Processing)
    -   파일 I/O, 네트워크 요청, 무거운 연산 등 0.1초 이상 소요될 수 있는 모든 작업은
        반드시 QThread와 Worker를 사용한 비동기 방식으로 구현하여 UI 멈춤 현상을 방지해야 합니다.

4.  코드 품질 및 명확성 (Code Quality and Clarity)
    -   모든 새로운 코드에는 그 목적과 작동 방식을 설명하는 주석을 명확하게 작성해야 합니다.
    -   변수와 메서드의 이름은 그 기능을 명확히 알 수 있도록 직관적으로 작성하십시오.

5.  사용자 경험 (User Experience)
    -   모든 기능 추가 및 변경은 최종 사용자의 경험을 최우선으로 고려해야 합니다.
    -   UI는 일관된 디자인을 유지해야 하며, 사용자의 작업을 방해하지 않는 직관적인
        인터페이스를 제공해야 합니다.
"""