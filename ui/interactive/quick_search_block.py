"""
Quick Search Block - Interactive Mode
태그 기반 이벤트 검색, 필터링 및 랜덤 프롬프트 생성 블록
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QSizePolicy, QScrollArea, QProgressDialog,
    QMessageBox, QDialog, QProgressBar, QStyleFactory, QLayout, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QRect, QSize, QPoint
from PyQt6.QtGui import QColor, QCursor, QFontMetrics

from ui.interactive.block_widget import BlockWidget
from ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY
)
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_size, get_scaled_font_size

import pickle
import struct
import lzma
import zipfile
import urllib.request
import urllib.error
import ssl
from collections import Counter
from typing import Dict, List, Set, Optional
from pathlib import Path

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

from ui.interactive.quick_search_data import SinglePartitionStore

# SSL 인증서 검증
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

# === 상수 정의 ===
QUICK_SEARCH_DIR = Path("data/quick_search")
PARTITION_METADATA_FILE = QUICK_SEARCH_DIR / "metadata.tgpm"
HUGGINGFACE_DATA_URL = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/naia-tag-events.zip"

# Person 카테고리 목록
PERSON_CATEGORIES = [
    '1girl_solo', '1boy_solo', '1girl', '1boy', '1girl_1boy',
    '1girl_multiple_boys', '1boy_multiple_girls',
    '2girls', '2boys', 'multiple_girls', 'multiple_boys',
    'multiple_girls_multiple_boys', 'other',
]

# 카테고리별 라벨 (참고용)
PERSON_LABELS = {
    '1girl_solo': '1 Girl Solo',
    '1boy_solo': '1 Boy Solo',
    '1girl': '1 Girl',
    '1boy': '1 Boy',
    '1girl_1boy': '1 Girl + 1 Boy',
    '1girl_multiple_boys': '1 Girl + Boys',
    '1boy_multiple_girls': '1 Boy + Girls',
    '2girls': '2 Girls',
    '2boys': '2 Boys',
    'multiple_girls': 'Multiple Girls',
    'multiple_boys': 'Multiple Boys',
    'multiple_girls_multiple_boys': 'Multiple Mixed',
    'other': 'Other',
}

# 카테고리별 자동 선택 태그
PERSON_AUTO_TAGS = {
    '1girl_solo': ['1girl', 'solo'],
    '1boy_solo': ['1boy', 'solo'],
    '1girl': ['1girl'],
    '1boy': ['1boy'],
    '1girl_1boy': ['1girl', '1boy'],
    '1girl_multiple_boys': ['1girl'],
    '1boy_multiple_girls': ['1boy'],
    '2girls': ['2girls'],
    '2boys': ['2boys'],
    'multiple_girls': ['multiple girls'],
    'multiple_boys': ['multiple boys'],
    'multiple_girls_multiple_boys': [],
    'other': [],
}

class FlowLayout(QLayout):
    """너비 기반 동적 줄바꿈을 지원하는 Flow Layout (EZMode STEP4에서 복사)"""

    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._item_list = []
        self._spacing = spacing

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self._do_layout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        margin = self.contentsMargins().left()
        size += QSize(2 * margin, 2 * margin)
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._item_list:
            space_x = spacing
            space_y = spacing

            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y()

    def spacing(self):
        if self._spacing >= 0:
            return self._spacing
        else:
            return self.parent().style().layoutSpacing(
                QSizePolicy.ControlType.PushButton,
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Horizontal
            )

# 태그 버튼 스타일 (포함/제외)
TAG_BTN_STYLE = """
    QPushButton {{
        background-color: {bg_color};
        color: white;
        border: 1px solid {border_color};
        border-radius: {radius}px;
        padding: 4px 8px;
        font-family: {font_family};
        font-size: {font_size}px;
        text-align: left;
    }}
    QPushButton:hover {{
        background-color: {hover_color};
    }}
"""

# 추천 태그 그리드 버튼 스타일
REC_TAG_STYLE = """
    QPushButton {{
        background-color: transparent;
        color: {text_color};
        border: none;
        text-align: left;
        padding: 4px;
        font-family: {font_family};
        font-size: {font_size}px;
        font-weight: normal;
    }}
    QPushButton:hover {{
        background-color: {hover_bg};
        border-radius: 4px;
    }}
"""


class PartitionDataDownloadWorker(QThread):
    """파티션 데이터 다운로드 워커 스레드"""
    progress_updated = pyqtSignal(int, str)  # percent, message
    download_finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, url: str, target_dir: Path, parent=None):
        super().__init__(parent)
        self.url = url
        self.target_dir = target_dir
        self._cancelled = False

    def cancel(self):
        """다운로드 취소"""
        self._cancelled = True

    def _validate_metadata(self) -> tuple:
        """메타데이터 검증 (파일 존재 및 태그 수 확인)

        Returns:
            (is_valid, tag_count): 유효성 여부와 태그 수
        """
        TGPS_MAGIC = b'TGPS'
        metadata_file = self.target_dir / "metadata.tgpm"

        if not metadata_file.exists():
            return (False, 0)

        try:
            with open(metadata_file, 'rb') as f:
                magic = f.read(4)
                if magic != TGPS_MAGIC:
                    return (False, 0)

                _ = struct.unpack('<H', f.read(2))[0]  # version
                compressed_len = struct.unpack('<I', f.read(4))[0]
                compressed = f.read(compressed_len)

            serialized = lzma.decompress(compressed)
            data = pickle.loads(serialized)
            tag_count = len(data.get('tag_to_id', {}))

            # 태그 수가 13053개 이하면 구버전으로 간주
            is_valid = tag_count > 13053
            return (is_valid, tag_count)

        except Exception as e:
            print(f"[QuickSearch] 메타데이터 검증 실패: {e}")
            return (False, 0)

    def _clean_target_directory(self):
        """대상 디렉터리 내용 삭제"""
        import shutil

        if self.target_dir.exists():
            self.progress_updated.emit(5, "기존 데이터 삭제 중...")
            shutil.rmtree(self.target_dir)
            print(f"[QuickSearch] 기존 데이터 삭제 완료: {self.target_dir}")

    def run(self):
        """다운로드 및 압축 해제 실행"""
        try:
            self.progress_updated.emit(0, "메타데이터 검증 중...")

            # 메타데이터 검증
            is_valid, tag_count = self._validate_metadata()

            if not is_valid:
                if tag_count > 0:
                    print(f"[QuickSearch] 메타데이터 태그 수 부족: {tag_count} (기대: > 13053)")
                else:
                    print(f"[QuickSearch] 메타데이터 파일이 없거나 유효하지 않음")

                # 기존 데이터 삭제
                self._clean_target_directory()
            else:
                print(f"[QuickSearch] 메타데이터 검증 성공: {tag_count} 태그")
                self.download_finished.emit(True, f"데이터가 이미 최신 상태입니다 ({tag_count} 태그)")
                return

            self.progress_updated.emit(10, "다운로드 준비 중...")

            # 헤더 설정
            headers = {
                'User-Agent': 'NAIA/2.0.0 QuickSearch Module'
            }

            request = urllib.request.Request(self.url, headers=headers)

            # 임시 zip 파일 경로 (data/ 폴더에 저장)
            temp_zip = self.target_dir.parent / "naia-tag-events.zip"
            self.target_dir.mkdir(parents=True, exist_ok=True)

            # 다운로드
            with urllib.request.urlopen(request, context=SSL_CONTEXT) as response:
                total_size = int(response.headers.get('content-length', 0))
                block_size = 8192
                downloaded = 0

                with open(temp_zip, 'wb') as out_file:
                    while True:
                        if self._cancelled:
                            out_file.close()
                            if temp_zip.exists():
                                temp_zip.unlink()
                            self.download_finished.emit(False, "다운로드가 취소되었습니다.")
                            return

                        block = response.read(block_size)
                        if not block:
                            break
                        downloaded += len(block)
                        out_file.write(block)

                        if total_size > 0:
                            # 10-90% 범위로 진행률 표시
                            percent = min(90, 10 + (downloaded * 80) // total_size)
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            self.progress_updated.emit(percent, f"다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)")

            # 압축 해제
            self.progress_updated.emit(92, "압축 해제 중...")

            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(self.target_dir)

            # 임시 파일 삭제
            if temp_zip.exists():
                temp_zip.unlink()

            # 다운로드 후 재검증
            self.progress_updated.emit(95, "설치 검증 중...")
            is_valid_after, final_tag_count = self._validate_metadata()

            if not is_valid_after:
                self.download_finished.emit(False, f"설치 후 검증 실패 (태그 수: {final_tag_count})")
                return

            self.progress_updated.emit(100, "완료!")
            self.download_finished.emit(True, f"데이터 다운로드 및 설치 완료 ({final_tag_count} 태그)")

        except urllib.error.HTTPError as e:
            self.download_finished.emit(False, f"HTTP 오류 {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            self.download_finished.emit(False, f"네트워크 오류: {e.reason}")
        except zipfile.BadZipFile:
            self.download_finished.emit(False, "압축 파일이 손상되었습니다.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.download_finished.emit(False, f"오류: {str(e)}")


class DownloadProgressDialog(QDialog):
    """다운로드 진행 상태 표시 다이얼로그 (커스텀)"""
    canceled = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Search 데이터 다운로드")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # 크기 설정
        w = get_scaled_size(400)
        h = get_scaled_size(150)
        self.setFixedSize(w, h)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 메시지 라벨
        self.label = QLabel("다운로드 준비 중...")
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px; border: none;")
        layout.addWidget(self.label)
        
        # 프로그레스 바
        self.progress_bar = QProgressBar()
        # Windows 네이티브 테마 오류 방지를 위해 Fusion 스타일 강제 적용
        self.progress_bar.setStyle(QStyleFactory.create("Fusion"))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        # 스타일링
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        layout.addWidget(self.progress_bar)
        
        # 취소 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.cancel_btn.clicked.connect(self.on_cancel)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        
        
        # 다이얼로그 배경 스타일 (ID로 한정하여 자식 위젯 영향 방지)
        self.setObjectName("download_dialog")
        self.setStyleSheet(f"""
            QDialog#download_dialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

    def on_cancel(self):
        self.canceled.emit()
        self.reject()
        
    def update_progress(self, percent, message):
        self.progress_bar.setValue(percent)
        self.label.setText(message)
    
    def closeEvent(self, event):
        # 명시적 취소 버튼 클릭이 아닌 닫기(X버튼 등)도 취소로 간주
        super().closeEvent(event)
        # 하지만 X버튼으로 닫을 때도 처리가 필요할 수 있음.
        # DownloadProgressDialog를 외부에서 관리하므로, 
        # rejected 시그널을 쓰거나 on_cancel을 연결하면 됨.
        # 여기서는 안전하게 멤버 변수 canceled 연결을 유지.

class ElidedButton(QPushButton):
    """너비에 맞춰 텍스트를 줄임표(...)로 표시하는 버튼 + 좌/우 클릭 지원"""
    left_clicked = pyqtSignal(str)
    right_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ""
        self.tag_name = "" # 데이터 바인딩용

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.left_clicked.emit(self.tag_name)
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self.tag_name)
        super().mousePressEvent(event)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._update_text()
        
    def resizeEvent(self, event):
        self._update_text()
        super().resizeEvent(event)
        
    def _update_text(self):
        # 텍스트가 없거나 아직 사이즈가 없을 때
        if not self.full_text: 
            super().setText("")
            return
            
        fm = QFontMetrics(self.font())
        # 패딩 고려 (좌우 8px 정도 여유)
        width = self.width() - 16
        if width <= 0: 
            # 너비가 0이면 일단 전체 텍스트 설정 (안 보일 테니)
            super().setText(self.full_text)
            return
        
        elided = fm.elidedText(self.full_text, Qt.TextElideMode.ElideRight, width)
        super().setText(elided)

class TagButton(QPushButton):
    """좌클릭/우클릭 시그널을 분리한 태그 버튼"""
    left_clicked = pyqtSignal(str)
    right_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tag_name = ""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.left_clicked.emit(self.tag_name)
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self.tag_name)
        super().mousePressEvent(event)

class QuickSearchBlock(BlockWidget):
    """
    퀵 서치 블록: 인물/Rating 설정에 따른 태그 추천 및 필터링
    """
    def __init__(self, parent=None):
        super().__init__("Quick Search (0)", parent, block_type='default')
        
        # 데이터 상태
        self.current_page = 1
        self.total_pages = 1
        self.tags_per_page = 20 # 2 columns x 10 rows
        
        self.include_tags = [] # list of str
        self.exclude_tags = [] # list of str
        
        # 메타데이터 및 스토어
        self.tag_to_id = {}
        self.id_to_tag = {}
        self.qs_store = None # SinglePartitionStore 인스턴스

        # 임시 데이터 (실제 연동 전 테스트용)
        # 임시 데이터 (실제 연동 전 테스트용)
        self.rec_tags = [] # list of (tag, count) - 원본 전체 데이터
        self.display_tags = [] # list of (tag, count) - 필터링된 표시 데이터
        
        self._init_content()
        
        # 메타데이터 로드 시도
        if self.load_metadata():
            # 초기 파티션 로드 (q_1girl_solo.tgp)
            # PersonSettingsBlock의 초기값과 동기화: girls=1, solo=True, rating=questionable
            initial_info = {'girls': 1, 'boys': 0, 'others': 0, 'is_solo': True}
            self.load_partition('questionable', initial_info)
        
        # 초기 상태 업데이트
        self.update_tag_grid()

    def get_random_tags(self, count=10) -> List[List[str]]:
        """
        현재 필터(파티션)를 기반으로 10개의 랜덤 프롬프트를 생성하고,
        각 프롬프트의 태그 리스트를 담은 이중 리스트를 반환합니다.
        
        Args:
            count: (사용되지 않음, 호환성 유지) 생성할 프롬프트 개수 (기본 10회 고정)

        Returns:
            List[List[str]]: 10개의 태그 리스트를 담은 리스트 (예: [[tag1, tag2], [tag3, tag4], ...])
        """
        collected_tags_list = []
        
        # 10번 반복하여 랜덤 프롬프트 생성
        for _ in range(10):
            prompt_str = self.get_random_prompt()
            if prompt_str:
                # 쉼표 구분자로 분리 및 공백 제거
                tags = [t.strip() for t in prompt_str.split(',') if t.strip()]
                collected_tags_list.append(tags)
                
        return collected_tags_list

    def _validate_and_load_metadata(self) -> bool:
        """메타데이터 검증 및 로드 (필요시 다운로드 다이얼로그 표시)"""
        TGPS_MAGIC = b'TGPS'

        # 1. 파일 존재 여부 확인
        if not PARTITION_METADATA_FILE.exists():
            print(f"QuickSearch: Metadata file not found at {PARTITION_METADATA_FILE}")
            self._show_download_dialog()
            return False

        # 2. 메타데이터 로드 및 검증
        try:
            with open(PARTITION_METADATA_FILE, 'rb') as f:
                magic = f.read(4)
                if magic != TGPS_MAGIC:
                    print(f"QuickSearch: Invalid metadata format magic {magic}")
                    self._show_download_dialog()
                    return False

                _ = struct.unpack('<H', f.read(2))[0]
                compressed_len = struct.unpack('<I', f.read(4))[0]
                compressed = f.read(compressed_len)

            serialized = lzma.decompress(compressed)
            data = pickle.loads(serialized)

            tag_count = len(data.get('tag_to_id', {}))

            # 3. 태그 수 검증 (13053개 이하면 구버전)
            if tag_count <= 13053:
                print(f"QuickSearch: 메타데이터 태그 수 부족: {tag_count} (기대: > 13053)")
                self._show_download_dialog()
                return False

            # 4. 데이터 저장
            self.tag_to_id = data.get('tag_to_id', {})
            raw_id_to_tag = data.get('id_to_tag', {})
            self.id_to_tag = {int(k): v for k, v in raw_id_to_tag.items()}
            self.partition_info = data.get('partitions', {})

            print(f"QuickSearch: Loaded metadata (Tags: {tag_count})")
            return True

        except Exception as e:
            print(f"QuickSearch: Failed to load metadata: {e}")
            self._show_download_dialog()
            return False

    def load_metadata(self):
        """메타데이터 로드 (하위 호환성 유지)"""
        return self._validate_and_load_metadata()

    def _show_download_dialog(self):
        """다운로드 다이얼로그 표시"""
        # 사용자에게 다운로드 확인
        reply = QMessageBox.question(
            self,
            "Quick Search 데이터 필요",
            "Quick Search 기능을 사용하려면 약 127MB의 데이터를 다운로드해야 합니다.\n지금 다운로드하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._start_download()

    def _start_download(self):
        """다운로드 시작 (커스텀 다이얼로그 사용)"""
        # 커스텀 프로그레스 다이얼로그 생성
        self._progress_dialog = DownloadProgressDialog(self)
        
        # 워커 생성
        self._download_worker = PartitionDataDownloadWorker(
            HUGGINGFACE_DATA_URL,
            QUICK_SEARCH_DIR,
            self
        )

        # 시그널 연결
        self._download_worker.progress_updated.connect(self._on_download_progress)
        self._download_worker.download_finished.connect(self._on_download_finished)
        
        # 다이얼로그 취소 시그널 -> 다운로드 취소 처리
        self._progress_dialog.canceled.connect(self._on_download_canceled)
        
        # 워커 시작
        self._download_worker.start()
        
        # 다이얼로그 표시 (Non-blocking)
        self._progress_dialog.show()

    def _on_download_progress(self, percent: int, message: str):
        """다운로드 진행 상황 업데이트"""
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            try:
                # 커스텀 다이얼로그 업데이트 메서드 호출
                self._progress_dialog.update_progress(percent, message)
            except RuntimeError:
                pass

    def _on_download_finished(self, success: bool, message: str):
        """다운로드 완료 처리"""
        # 1. 시그널 연결 해제 및 Worker 정리
        if hasattr(self, '_download_worker') and self._download_worker:
            try:
                self._download_worker.progress_updated.disconnect()
                self._download_worker.download_finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            
            if self._download_worker.isRunning():
                self._download_worker.quit()
                self._download_worker.wait(1000)
            
            self._download_worker.deleteLater()
            self._download_worker = None

        # 2. Dialog 정리
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            try:
                self._progress_dialog.canceled.disconnect()
            except (RuntimeError, TypeError):
                pass
            
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None

        # 3. 결과 메시지 표시
        self._show_download_result(success, message)

    def _on_download_canceled(self):
        """다운로드 취소 처리"""
        # Worker 취소 요청
        if hasattr(self, '_download_worker') and self._download_worker:
            self._download_worker.cancel()
            
            if self._download_worker.isRunning():
                self._download_worker.quit()
                self._download_worker.wait(1000)
            
            self._download_worker.deleteLater()
            self._download_worker = None

        # Dialog 정리
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None

    def _show_download_result(self, success: bool, message: str):
        """다운로드 결과 메시지 표시"""
        # 실패이고 취소된 경우 메시지 표시 안함
        if not success and "취소" in message:
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("다운로드 완료" if success else "다운로드 실패")
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Icon.Information if success else QMessageBox.Icon.Warning)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        
        # 스타일 적용 (다크 테마)
        msg_box.setStyleSheet(f"""
            QMessageBox {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
            }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        
        msg_box.exec()

        if success:
            # 메타데이터 재로드
            if self._validate_and_load_metadata():
                self.update_tag_grid()

    def load_partition(self, rating: str, person_info: dict):
        """
        특정 rating 및 person_info에 기반하여 최적의 파티션 로드 및 자동 태그 설정
        """
        # 재로드를 위한 정보 저장
        self.last_rating = rating
        self.last_person_info = person_info

        if not isinstance(person_info, dict):
            print(f"QuickSearch: Invalid person_info received: {person_info}")
            return

        c_girls = person_info.get('girls', 0)
        c_boys = person_info.get('boys', 0)
        c_others = person_info.get('others', 0)
        is_solo = person_info.get('is_solo', False)
        
        # 1. 파티션 결정 (PERSON_CATEGORIES 기반)
        target_category = "1girl" # Default Fallback
        
        if c_others > 0:
            target_category = 'other'
        elif c_girls == 1 and c_boys == 0:
            target_category = '1girl_solo' if is_solo else '1girl'
        elif c_girls == 0 and c_boys == 1:
             target_category = '1boy_solo' if is_solo else '1boy'
        elif c_girls == 2 and c_boys == 0:
            target_category = '2girls'
        elif c_girls >= 3 and c_boys == 0:
            target_category = 'multiple_girls'
        elif c_girls == 0 and c_boys == 2:
            target_category = '2boys'
        elif c_girls == 0 and c_boys >= 3:
            target_category = 'multiple_boys'
        elif c_girls == 1 and c_boys == 1:
            target_category = '1girl_1boy'
        elif c_girls == 1 and c_boys >= 2:
            target_category = '1girl_multiple_boys'
        elif c_girls >= 2 and c_boys == 1:
            target_category = '1boy_multiple_girls'
        elif c_girls >= 2 and c_boys >= 2:
            target_category = 'multiple_girls_multiple_boys'
        
        # 2. 자동 태그 설정
        self.auto_added_tags = set(PERSON_AUTO_TAGS.get(target_category, []))

        # 3. 상세 인원 태그 추가 (예: 3girls, 4boys 등 구체적 숫자)
        if c_girls > 0:
            tag = "6+girls" if c_girls >= 6 else ("1girl" if c_girls == 1 else f"{c_girls}girls")
            self.auto_added_tags.add(tag)
            
        if c_boys > 0:
            tag = "6+boys" if c_boys >= 6 else ("1boy" if c_boys == 1 else f"{c_boys}boys")
            self.auto_added_tags.add(tag)
            
        if c_others > 0:
            tag = "6+others" if c_others >= 6 else ("1other" if c_others == 1 else f"{c_others}others")
            self.auto_added_tags.add(tag)
        
        # Rating 매핑
        rating_map = {
            "general": "g",
            "sensitive": "s",
            "questionable": "q",
            "explicit": "e"
        }
        r_key = rating_map.get(rating.lower(), "s")
        
        # 파일명 생성: {r_key}_{target_category}.tgp
        filename = f"{r_key}_{target_category}.tgp"
        filepath = QUICK_SEARCH_DIR / filename
        
        # 재로드를 위해 경로 저장
        self.current_partition_path = filepath
        
        if not filepath.exists():
            print(f"QuickSearch: Partition file not found: {filepath}")
            self.qs_store = SinglePartitionStore()
            self.include_tags = []
            self.exclude_tags = []
            self.refresh_tag_display()
            self.update_recommendations()
            return

        print(f"QuickSearch: Loading partition: {filename}")
        self.qs_store = SinglePartitionStore.load(filepath)
             
        # 태그 설정 (자동 태그만 설정, 나머지는 초기화)
        self.include_tags = list(self.auto_added_tags)
        self.exclude_tags = [] 
        
        self.refresh_tag_display()
        self.update_recommendations()

    def update_recommendations(self):
        """현재 스토어와 필터에 맞춰 추천 태그 갱신"""
        if not self.qs_store or not self.qs_store._loaded:
            self.rec_tags = []
            self.update_header_count(0)
            self.rec_info_label.setText(f"추천 태그 (0개 / 매칭 0건 기준):")
            self.update_tag_grid()
            return

        # 1. 이벤트 필터링
        event_indices = self.qs_store.filter_events(
            required_tags=self.include_tags,
            excluded_tags=self.exclude_tags,
            tag_to_id=self.tag_to_id
        )
        
        count = len(event_indices)
        self.update_header_count(count)
        self.rec_info_label.setText(f"추천 태그 ({len(self.tag_to_id)}개 / 매칭 {count}건 기준):")
        
        # 2. 태그 카운트
        if count > 0:
            tag_counts = self.qs_store.get_tag_counts(event_indices, self.id_to_tag)
            
            # 3. 정렬 (빈도수 내림차순)
            # 이미 포함된 태그나 제외된 태그는 추천 목록에서 제외
            filter_set = set(self.include_tags) | set(self.exclude_tags)
            
            
            self.rec_tags = [
                (tag, cnt) 
                for tag, cnt in tag_counts.most_common()
                if tag not in filter_set
            ]
        else:
            # 매칭되는 이벤트가 없으면 추천 태그도 없음
            self.rec_tags = []
        
        # 필터링 및 그리드 업데이트
        self._apply_search_filter()

    def _apply_search_filter(self, text=None):
        """검색어에 따라 태그 필터링"""
        # text 인자는 시그널에서 올 수 있으므로 사용하지 않고 직접 가져옴(혹은 사용 가능)
        query = self.search_input.text().strip().lower()
        
        if not query:
            self.display_tags = list(self.rec_tags)
        else:
            self.display_tags = [
                (tag, cnt) for tag, cnt in self.rec_tags 
                if query in tag.lower()
            ]
            
        self.current_page = 1
        self.total_pages = max(1, (len(self.display_tags) + self.tags_per_page - 1) // self.tags_per_page)
        self.update_tag_grid()

    def _reset_search(self):
        self.search_input.setText("")
        self.search_input.setFocus()

    def _clear_selected_tags(self):
        """사용자가 추가한 태그 모두 제거 (자동 태그 제외)"""
        # include_tags에서 auto_added_tags에 없는 것 제거
        self.include_tags = [tag for tag in self.include_tags if tag in self.auto_added_tags]
        
        # exclude_tags에서 auto_added_tags에 없는 것 제거
        self.exclude_tags = [tag for tag in self.exclude_tags if tag in self.auto_added_tags]
        
        self.refresh_tag_display()
        self.update_recommendations()

    def update_header_count(self, count: int):
        """헤더의 프롬프트 수 업데이트"""
        self.title = f"Quick Search ({count})"
        if self.is_collapsed:
            self.header_label.setText(f"► {self.title}")
        else:
            self.header_label.setText(f"▼ {self.title}")

    def _init_content(self):
        layout = self.get_content_layout()
        layout.setSpacing(get_scaled_size(12))

        # 1. 포함 태그 영역 (Include)
        # 헤더
        inc_header = QLabel("✔ 포함 태그 (마우스 좌클릭) :")
        inc_header.setStyleSheet(f"""
            color: #4CAF50; /* Green */
            font-weight: bold;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(16)}px;
        """)
        layout.addWidget(inc_header)
        
        layout.addWidget(inc_header)
        
        # 태그 컨테이너 (FlowLayout 적용)
        self.inc_tags_area = QWidget()
        self.inc_tags_layout = FlowLayout(self.inc_tags_area, margin=0, spacing=4)
        layout.addWidget(self.inc_tags_area)

        # 2. 제외 태그 영역 (Exclude)
        # 헤더
        exc_header = QLabel("✖ 제외 태그 (마우스 우클릭) :")
        exc_header.setStyleSheet(f"""
            color: {COMMON_STYLES['text_secondary']};
            font-weight: bold;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(16)}px;
            margin-top: {get_scaled_size(4)}px;
        """)
        layout.addWidget(exc_header)
        
        # 제외 태그 컨테이너 (FlowLayout 적용)
        self.exc_tags_area = QWidget()
        self.exc_tags_layout = FlowLayout(self.exc_tags_area, margin=0, spacing=4)
        layout.addWidget(self.exc_tags_area)

        layout.addSpacing(get_scaled_size(8))
        
        # === 검색바 영역 ===
        search_layout = QHBoxLayout()
        search_layout.setSpacing(get_scaled_size(8))
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어를 입력하세요 ...")
        self.search_input.setProperty("autocomplete_ignore", True)
        self.search_input.setFixedHeight(get_scaled_size(32))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                padding: 0 8px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {COMMON_STYLES['input_focus']};
            }}
        """)
        self.search_input.textChanged.connect(self._apply_search_filter)
        search_layout.addWidget(self.search_input)
        
        self.btn_reset_search = QPushButton("초기화")
        self.btn_reset_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_search.setFixedSize(get_scaled_size(70), get_scaled_size(32))
        self.btn_reset_search.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.btn_reset_search.clicked.connect(self._reset_search)
        search_layout.addWidget(self.btn_reset_search)
        
        layout.addLayout(search_layout)

        # 3. 추천 태그 리스트 (Grid 2x10)
        # 헤더 (정보 표시)
        self.rec_info_label = QLabel("추천 태그 (0개 / 매칭 0건 기준):")
        self.rec_info_label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_primary']};
            font-weight: bold;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(16)}px;
        """)
        layout.addWidget(self.rec_info_label)
        
        # 그리드 컨테이너
        grid_frame = QFrame()
        grid_frame.setStyleSheet(f"""
            background-color: {COMMON_STYLES['input_bg']};
            border-radius: {get_scaled_size(6)}px;
        """)
        self.rec_grid = QGridLayout(grid_frame)
        self.rec_grid.setContentsMargins(4, 4, 4, 4)
        self.rec_grid.setSpacing(2)
        
        # 20개 버튼 미리 생성 (자리잡기)
        self.rec_buttons = []
        for row in range(10):
            for col in range(2):
                btn = ElidedButton("")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                
                # 좌클릭/우클릭 시그널 연결
                btn.left_clicked.connect(self._on_rec_tag_left_click)
                btn.right_clicked.connect(self._on_rec_tag_right_click)
                
                # 스타일 설정
                btn.setStyleSheet(REC_TAG_STYLE.format(
                    text_color=COMMON_STYLES['text_primary'],
                    hover_bg=COMMON_STYLES['input_focus'] + "40", # 25% opacity
                    font_family=FONT_FAMILY,
                    font_size=get_scaled_font_size(16)
                ))
                btn.setFixedHeight(get_scaled_size(24))
                self.rec_grid.addWidget(btn, row, col)
                self.rec_buttons.append(btn)
                
        layout.addWidget(grid_frame)
        
        # 4. 하단 컨트롤 (페이지네이션 & 미리보기)
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(get_scaled_size(10))
        
        # 선택 태그 초기화 버튼
        self.btn_clear_tags = QPushButton("선택 태그 초기화")
        self.btn_clear_tags.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_tags.setFixedHeight(get_scaled_size(32))
        self.btn_clear_tags.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COMMON_STYLES['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(12)}px;
                font-weight: bold;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
        """)
        self.btn_clear_tags.clicked.connect(self._clear_selected_tags)
        bottom_layout.addWidget(self.btn_clear_tags)
        
        bottom_layout.addStretch()
        
        # 페이지네이션
        self.btn_prev = QPushButton("<")
        self.btn_prev.setFixedSize(get_scaled_size(48), get_scaled_size(32))
        self.btn_prev.setStyleSheet(self._get_pagination_style())
        self.btn_prev.clicked.connect(self.prev_page)
        
        self.page_label = QLabel("1 / 100")
        self.page_label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_secondary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(12)}px;
        """)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setFixedWidth(get_scaled_size(60))
        
        self.btn_next = QPushButton(">")
        self.btn_next.setFixedSize(get_scaled_size(48), get_scaled_size(32))
        self.btn_next.setStyleSheet(self._get_pagination_style())
        self.btn_next.clicked.connect(self.next_page)
        
        bottom_layout.addWidget(self.btn_prev)
        bottom_layout.addWidget(self.page_label)
        bottom_layout.addWidget(self.btn_next)
        
        layout.addLayout(bottom_layout)
        layout.addStretch()

    def _get_pagination_style(self):
        return f"""
            QPushButton {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: {COMMON_STYLES['input_focus']};
                border: 1px solid {COMMON_STYLES['input_focus']};
            }}
            QPushButton:pressed {{
                background-color: {COMMON_STYLES['input_focus']};
                opacity: 0.8;
            }}
        """

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def add_include_tag(self, tag):
        if tag not in self.include_tags:
            self.include_tags.append(tag)
            self.refresh_tag_display()
            self.update_recommendations()

    def remove_include_tag(self, tag):
        if tag in self.include_tags:
            self.include_tags.remove(tag)
            self.refresh_tag_display()
            self.update_recommendations()
            
    def add_exclude_tag(self, tag):
        if tag not in self.exclude_tags:
            self.exclude_tags.append(tag)
            self.refresh_tag_display()
            self.update_recommendations()

    def remove_exclude_tag(self, tag):
        if tag in self.exclude_tags:
            self.exclude_tags.remove(tag)
            self.refresh_tag_display()
            self.update_recommendations()

    def refresh_tag_display(self):
        # 1. Include Tags
        self.clear_layout(self.inc_tags_layout)
        for tag in self.include_tags:
            btn = QPushButton(f"✕ {tag}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(TAG_BTN_STYLE.format(
                bg_color="#7B1FA2", # Purple/Blue bias
                border_color="#9C27B0",
                radius=get_scaled_size(12),
                hover_color="#6A1B9A",
                font_family=FONT_FAMILY,
                font_size=get_scaled_font_size(14)
            ))
            # Lambda capture issue fix
            btn.clicked.connect(lambda checked, t=tag: self.remove_include_tag(t))
            self.inc_tags_layout.addWidget(btn)
            
        # 2. Exclude Tags
        self.clear_layout(self.exc_tags_layout)
        for tag in self.exclude_tags:
            btn = QPushButton(f"✕ {tag}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(TAG_BTN_STYLE.format(
                bg_color="#661B1C", # Darker Red
                border_color="#8E2425",
                radius=get_scaled_size(12),
                hover_color="#7F2223",
                font_family=FONT_FAMILY,
                font_size=get_scaled_font_size(14)
            ))
            btn.clicked.connect(lambda checked, t=tag: self.remove_exclude_tag(t))
            self.exc_tags_layout.addWidget(btn)
            
    def _on_rec_tag_left_click(self, tag):
        """추천 태그 좌클릭 -> 포함 태그 추가"""
        self.add_include_tag(tag)

    def _on_rec_tag_right_click(self, tag):
        """추천 태그 우클릭 -> 제외 태그 추가"""
        self.add_exclude_tag(tag)

    def update_tag_grid(self):
        """추천 태그 그리드 업데이트"""
        if not self.display_tags:
            for btn in self.rec_buttons:
                btn.setVisible(False)
            self.page_label.setText("1 / 1")
            return

        # 현재 페이지 데이터 슬라이싱
        start_idx = (self.current_page - 1) * self.tags_per_page
        end_idx = start_idx + self.tags_per_page
        
        page_items = self.display_tags[start_idx:end_idx]
        
        # 버튼 업데이트
        for i, btn in enumerate(self.rec_buttons):
            if i < len(page_items):
                tag, count = page_items[i]
                
                # Count Formatting (1k 단위)
                if count >= 1000:
                    cnt_str = f"{count/1000:.1f}k"
                else:
                    cnt_str = str(count)
                
                btn.setText(f"{tag} ({cnt_str})")
                btn.tag_name = tag # 데이터 바인딩
                btn.setVisible(True)
            else:
                btn.setVisible(False)
                
        # 페이지 라벨 업데이트
        self.page_label.setText(f"{self.current_page} / {max(1, self.total_pages)}")

    def next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.update_tag_grid()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.update_tag_grid()

    # ===== 랜덤 프롬프트 생성 =====

    def get_random_prompt(self) -> str:
        """
        현재 필터링된 이벤트에서 랜덤 프롬프트 생성

        Returns:
            str: 랜덤으로 생성된 프롬프트 (쉼표로 구분된 태그 문자열)
        """
        if not self.qs_store or not self.qs_store._loaded:
            print("[QuickSearch] 파티션 데이터가 로드되지 않음 -> 재로드 시도")
            
            # 저장된 경로로 직접 재로드 시도
            if hasattr(self, 'current_partition_path') and self.current_partition_path:
                try:
                    self.qs_store = SinglePartitionStore.load(self.current_partition_path)
                    print(f"[QuickSearch] 파티션 데이터 재로드 성공: {self.current_partition_path.name}")
                except Exception as e:
                    print(f"[QuickSearch] 파티션 데이터 재로드 실패: {e}")
            
            # 재확인
            if not self.qs_store or not self.qs_store._loaded:
                print("[QuickSearch] 파티션 데이터 로드 실패 (재시도 포함).")
                return ""

        # 1. 현재 필터링된 이벤트 인덱스 가져오기
        event_indices = self.qs_store.filter_events(
            required_tags=self.include_tags,
            excluded_tags=self.exclude_tags,
            tag_to_id=self.tag_to_id
        )

        if len(event_indices) == 0:
            print("[QuickSearch] 필터링된 이벤트가 없습니다. (Include/Exclude 태그 확인)")
            return ""

        # 2. SinglePartitionStore에서 랜덤 프롬프트 생성
        random_prompt = self.qs_store.get_random_prompt(event_indices, self.id_to_tag)

        print(f"[QuickSearch] 랜덤 프롬프트 생성 완료 (매칭 {len(event_indices)}건 중 1개 선택)")
        return random_prompt

    def force_single_search(self, tag: str):
        """특정 태그만 포함(Include)으로 설정하고 필터링 (외부 요청)"""
        if not tag:
            return

        # 1. 초기화
        self.include_tags.clear()
        self.exclude_tags.clear()
        
        # 2. 태그 추가
        # 이미 있는지 확인 불필요 (초기화 했으므로)
        self.include_tags.append(tag)
        
        # 3. 업데이트
        if hasattr(self, 'refresh_tag_display'):
            self.refresh_tag_display() # 상단 선택 태그 표시 갱신
        
        if hasattr(self, 'update_recommendations'):
            self.update_recommendations() # 추천 태그 목록 및 카운트 갱신
        
        print(f"[QuickSearch] Force single search executed: {tag}")
