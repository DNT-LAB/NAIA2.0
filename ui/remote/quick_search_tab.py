# ui/remote/quick_search_tab.py
"""
Quick Search 탭 Mixin - 파티션 기반 태그 이벤트 검색 및 프롬프트 생성

기능:
- 파티션 선택 (Rating x Person Category)
- 태그 Include/Exclude 필터링
- 랜덤 이벤트 샘플링 및 프롬프트 생성
- HuggingFace에서 데이터 자동 다운로드
"""

import json
import zipfile
import urllib.request
import urllib.error
import ssl
import struct
import lzma
import pickle
from pathlib import Path
from typing import Dict, List, Set, Optional
from collections import Counter, defaultdict
import random

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QLineEdit,
    QButtonGroup, QTextEdit, QProgressDialog,
    QTabWidget, QCheckBox, QMessageBox, QApplication,
    QLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QRect, QSize, QPoint
from PyQt6.QtGui import QPixmap

from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


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
        """레이아웃 계산 및 적용"""
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

# SSL 인증서 검증
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()


class SinglePartitionStore:
    """단일 파티션 저장소 (역인덱스 기반) - Quick Search용 경량 버전"""

    MAGIC = b'TGP1'
    VERSION = 1

    def __init__(self):
        self.num_events: int = 0
        self._event_tag_indices = None
        self._event_tag_indptr = None
        self._event_counts = None
        self._tag_to_events: Dict[int, object] = {}
        self._loaded: bool = False

    @classmethod
    def load(cls, input_path: str) -> 'SinglePartitionStore':
        """파티션 파일 로드"""
        if not HAS_NUMPY:
            raise RuntimeError("NumPy가 필요합니다")

        store = cls()

        with open(input_path, 'rb') as f:
            magic = f.read(4)
            if magic != cls.MAGIC:
                raise ValueError(f"Invalid format: {magic}")

            _ = struct.unpack('<H', f.read(2))[0]  # version
            compressed_len = struct.unpack('<I', f.read(4))[0]
            compressed = f.read(compressed_len)

        serialized = lzma.decompress(compressed)
        data = pickle.loads(serialized)

        store.num_events = data['num_events']
        store._event_tag_indices = np.frombuffer(data['event_tag_indices'], dtype=np.uint16).copy()
        store._event_tag_indptr = np.frombuffer(data['event_tag_indptr'], dtype=np.int32).copy()
        store._event_counts = np.frombuffer(data['event_counts'], dtype=np.int32).copy()

        store._tag_to_events = {
            int(k): np.frombuffer(v, dtype=np.int32).copy()
            for k, v in data['tag_to_events'].items()
        }

        store._loaded = True
        return store

    def filter_events(self, required_tags=None, excluded_tags=None, tag_to_id=None):
        """조건에 맞는 이벤트 인덱스 반환"""
        if not self._loaded or not HAS_NUMPY:
            return np.array([], dtype=np.int32) if HAS_NUMPY else []

        # 전체 이벤트에서 시작
        candidates = set(range(self.num_events))

        # Required 태그
        if required_tags and tag_to_id:
            for tag in required_tags:
                if tag in tag_to_id:
                    tag_id = tag_to_id[tag]
                    if tag_id in self._tag_to_events:
                        candidates &= set(self._tag_to_events[tag_id])
                    else:
                        return np.array([], dtype=np.int32)
                else:
                    return np.array([], dtype=np.int32)

        # Excluded 태그
        if excluded_tags and tag_to_id:
            for tag in excluded_tags:
                if tag in tag_to_id:
                    tag_id = tag_to_id[tag]
                    if tag_id in self._tag_to_events:
                        candidates -= set(self._tag_to_events[tag_id])

        return np.array(sorted(candidates), dtype=np.int32)

    def get_tag_counts(self, event_indices=None, id_to_tag=None):
        """태그별 이벤트 수 카운트"""
        if not HAS_NUMPY or id_to_tag is None:
            return Counter()

        if event_indices is None or len(event_indices) == 0:
            # 전체 태그 카운트
            return Counter({
                id_to_tag[tag_id]: len(events)
                for tag_id, events in self._tag_to_events.items()
                if tag_id in id_to_tag
            })

        event_set = set(event_indices)
        return Counter({
            id_to_tag[tag_id]: len(set(events) & event_set)
            for tag_id, events in self._tag_to_events.items()
            if tag_id in id_to_tag
        })

    def get_event_tags(self, event_idx: int, id_to_tag=None):
        """이벤트의 태그 반환"""
        if not self._loaded or id_to_tag is None:
            return set()

        if event_idx < 0 or event_idx >= self.num_events:
            return set()

        start = self._event_tag_indptr[event_idx]
        end = self._event_tag_indptr[event_idx + 1]
        tag_ids = self._event_tag_indices[start:end]

        return {id_to_tag[int(tid)] for tid in tag_ids if int(tid) in id_to_tag}


class QsPreviewPopup(QWidget):
    """Quick Search 프롬프트 미리보기 팝업 (툴팁 스타일)

    autocomplete_manager.py 패턴을 참고하여 애플리케이션 레벨 이벤트 필터로
    외부 클릭 감지를 구현합니다.
    """

    generate_requested = pyqtSignal(str)  # 생성 요청 시그널
    refresh_requested = pyqtSignal()  # 새로고침 요청 시그널

    def __init__(self, prompt: str, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        # WA_DeleteOnClose 제거 - 수동 관리
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.prompt = prompt
        self._event_filter_installed = False
        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        self.setFixedWidth(get_scaled_size(450))
        self.setMaximumHeight(get_scaled_size(350))

        # 메인 스타일
        self.setStyleSheet(f"""
            QsPreviewPopup {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 2px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(8)}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(12), get_scaled_size(10),
            get_scaled_size(12), get_scaled_size(10)
        )
        layout.setSpacing(get_scaled_size(8))

        # 헤더
        header_layout = QHBoxLayout()
        header_label = QLabel("🎲 프롬프트 미리보기")
        header_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        # 새로고침 버튼
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(get_scaled_size(28), get_scaled_size(28))
        refresh_btn.setToolTip("다시 생성")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        refresh_btn.clicked.connect(self._on_refresh)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # 프롬프트 텍스트 영역 (복사 가능)
        self.prompt_textedit = QTextEdit()
        self.prompt_textedit.setPlainText(self.prompt)
        self.prompt_textedit.setReadOnly(True)
        self.prompt_textedit.setMinimumHeight(get_scaled_size(120))
        self.prompt_textedit.setMaximumHeight(get_scaled_size(200))
        self.prompt_textedit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(16)}px;
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        layout.addWidget(self.prompt_textedit)

        # 하단 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.setSpacing(get_scaled_size(8))

        # 복사 버튼
        copy_btn = QPushButton("📋 복사")
        copy_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        copy_btn.clicked.connect(self._on_copy)
        button_layout.addWidget(copy_btn)

        button_layout.addStretch()

        # 생성 버튼
        generate_btn = QPushButton("▶️ 이 프롬프트로 생성")
        generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        generate_btn.clicked.connect(self._on_generate)
        button_layout.addWidget(generate_btn)

        layout.addLayout(button_layout)

    def set_prompt(self, prompt: str):
        """프롬프트 텍스트 설정"""
        self.prompt = prompt
        self.prompt_textedit.setPlainText(prompt)

    def _on_refresh(self):
        """새로고침 버튼 클릭"""
        self.refresh_requested.emit()

    def _on_copy(self):
        """복사 버튼 클릭"""
        QApplication.clipboard().setText(self.prompt)

    def _on_generate(self):
        """생성 버튼 클릭"""
        self.generate_requested.emit(self.prompt)

    def showEvent(self, event):
        """팝업 표시 시 이벤트 필터 설치"""
        super().showEvent(event)
        self._install_event_filter()
        self.setFocus()
        self.activateWindow()

    def hideEvent(self, event):
        """팝업 숨김 시 이벤트 필터 제거"""
        super().hideEvent(event)
        self._uninstall_event_filter()

    def _install_event_filter(self):
        """애플리케이션 레벨 이벤트 필터 설치"""
        if not self._event_filter_installed:
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
                self._event_filter_installed = True

    def _uninstall_event_filter(self):
        """애플리케이션 레벨 이벤트 필터 제거"""
        if self._event_filter_installed:
            app = QApplication.instance()
            if app:
                app.removeEventFilter(self)
                self._event_filter_installed = False

    def eventFilter(self, watched, event):
        """애플리케이션 레벨 이벤트 필터 - 외부 클릭 감지"""
        from PyQt6.QtCore import QEvent

        # 마우스 클릭 이벤트만 처리
        if event.type() == QEvent.Type.MouseButtonPress:
            if self.isVisible() and self._is_click_outside(event):
                self.hide()
                return False  # 이벤트는 계속 전파

        return super().eventFilter(watched, event)

    def _is_click_outside(self, event) -> bool:
        """클릭 위치가 팝업 외부인지 확인"""
        try:
            # PyQt6에서 마우스 이벤트의 전역 위치 가져오기
            if hasattr(event, 'globalPosition'):
                click_pos = event.globalPosition().toPoint()
            elif hasattr(event, 'globalPos'):
                click_pos = event.globalPos()
            else:
                return False

            # 팝업 geometry 내부인지 확인
            popup_rect = self.geometry()
            if popup_rect.contains(click_pos):
                return False

            return True
        except Exception:
            return False


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

# 카테고리별 라벨
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

    def run(self):
        """다운로드 및 압축 해제 실행"""
        try:
            self.progress_updated.emit(0, "다운로드 준비 중...")

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
                            percent = min(90, (downloaded * 90) // total_size)
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            self.progress_updated.emit(percent, f"다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)")

            # 압축 해제 (data/quick_search/ 폴더에 직접 압축 해제)
            self.progress_updated.emit(92, "압축 해제 중...")

            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                # zip 내부에 폴더 없이 파일들만 있으므로 target_dir에 직접 압축 해제
                zip_ref.extractall(self.target_dir)

            # 임시 파일 삭제
            if temp_zip.exists():
                temp_zip.unlink()

            self.progress_updated.emit(100, "완료!")
            self.download_finished.emit(True, f"데이터 다운로드 및 설치 완료")

        except urllib.error.HTTPError as e:
            self.download_finished.emit(False, f"HTTP 오류 {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            self.download_finished.emit(False, f"네트워크 오류: {e.reason}")
        except zipfile.BadZipFile:
            self.download_finished.emit(False, "압축 파일이 손상되었습니다.")
        except Exception as e:
            self.download_finished.emit(False, f"오류: {str(e)}")


class QuickSearchTabMixin:
    """Quick Search 탭 Mixin - RemoteWindow와 함께 상속"""

    def _init_quick_search_data(self):
        """Quick Search 데이터 초기화"""
        self.qs_store = None  # PartitionedEventStore
        self.qs_current_partition: Optional[SinglePartitionStore] = None
        self.qs_current_partition_key: Optional[str] = None
        self.qs_selected_rating = 'q'  # 기본: Questionable
        self.qs_selected_person = '1girl'  # 기본: 1girl (solo 아님)
        self.qs_include_tags: List[str] = []
        self.qs_exclude_tags: Set[str] = set()
        self.qs_matching_indices = []  # np.ndarray of matching event indices
        self.qs_tag_counts: Dict[str, int] = {}

        # 다운로드 워커
        self._qs_download_worker = None

        # 추천 태그 페이지네이션
        self.qs_tag_page = 0  # 현재 페이지 (0부터 시작)
        self.qs_tags_per_page = 60  # 페이지당 태그 수
        self.qs_total_filtered_tags: List[tuple] = []  # [(tag, freq), ...]

        # 자동 생성 플래그 (생성 완료 시 RemoteWindow에서 확인)
        self._qs_auto_generate_pending = False

    def _create_quick_search_tab(self):
        """Quick Search 탭 생성 (프리셋 탭 앞에)"""
        qs_widget = QWidget()
        qs_layout = QVBoxLayout(qs_widget)
        qs_layout.setContentsMargins(8, 8, 8, 8)
        qs_layout.setSpacing(8)

        # 파티션 데이터 존재 여부 확인
        if not self._check_partition_data_exists():
            # 데이터 없음 - 다운로드 UI 표시
            self._create_download_ui(qs_layout)
        else:
            # 데이터 있음 - 검색 UI 표시
            self._create_search_ui(qs_layout)

        # 탭 삽입 (인덱스 0 = 가장 왼쪽)
        self.main_tabs.insertTab(0, qs_widget, "🔍 퀵 서치")

        # 퀵 서치 탭을 기본 선택
        self.main_tabs.setCurrentIndex(0)

    def _check_partition_data_exists(self) -> bool:
        """파티션 데이터 존재 여부 확인"""
        if not QUICK_SEARCH_DIR.exists():
            return False

        if not PARTITION_METADATA_FILE.exists():
            return False

        # 최소 파티션 파일 확인 (예: s_1girl_solo.tgp)
        tgp_files = list(QUICK_SEARCH_DIR.glob("*.tgp"))
        return len(tgp_files) >= 10  # 최소 10개 파티션

    def _create_download_ui(self, parent_layout: QVBoxLayout):
        """데이터 다운로드 UI 생성"""
        # 중앙 정렬 컨테이너
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 아이콘/제목
        title_label = QLabel("🔍 Quick Search")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(24)}px;
                font-weight: bold;
            }}
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(title_label)

        # 설명
        desc_label = QLabel("태그 이벤트 데이터가 필요합니다.\n약 127MB의 데이터를 다운로드합니다.")
        desc_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(desc_label)

        center_layout.addSpacing(20)

        # 다운로드 버튼
        self.qs_download_btn = QPushButton("📥 데이터 다운로드")
        self.qs_download_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: 8px;
                padding: 16px 32px;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.qs_download_btn.clicked.connect(self._on_qs_download_clicked)
        center_layout.addWidget(self.qs_download_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # 진행 상태 레이블
        self.qs_progress_label = QLabel("")
        self.qs_progress_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        self.qs_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.qs_progress_label)

        parent_layout.addStretch()
        parent_layout.addWidget(center_widget)
        parent_layout.addStretch()

    def _on_qs_download_clicked(self):
        """다운로드 버튼 클릭"""
        self.qs_download_btn.setEnabled(False)
        self.qs_download_btn.setText("다운로드 중...")
        self.qs_progress_label.setText("준비 중...")

        # 워커 생성 및 시작
        self._qs_download_worker = PartitionDataDownloadWorker(
            HUGGINGFACE_DATA_URL,
            QUICK_SEARCH_DIR,
            self
        )
        self._qs_download_worker.progress_updated.connect(self._on_qs_download_progress)
        self._qs_download_worker.download_finished.connect(self._on_qs_download_finished)
        self._qs_download_worker.start()

    def _on_qs_download_progress(self, percent: int, message: str):
        """다운로드 진행 상태 업데이트"""
        self.qs_progress_label.setText(message)
        self.qs_download_btn.setText(f"다운로드 중... {percent}%")

    def _on_qs_download_finished(self, success: bool, message: str):
        """다운로드 완료 처리"""
        if success:
            self.qs_progress_label.setText("완료! 페이지를 새로고침합니다...")
            # 탭 재생성
            QTimer.singleShot(1000, self._reload_quick_search_tab)
        else:
            self.qs_download_btn.setEnabled(True)
            self.qs_download_btn.setText("📥 데이터 다운로드")
            self.qs_progress_label.setText(f"오류: {message}")
            self._show_warning("다운로드 실패", message)

    def _reload_quick_search_tab(self):
        """Quick Search 탭 재생성"""
        # 기존 탭 제거
        for i in range(self.main_tabs.count()):
            if self.main_tabs.tabText(i) == "🔍 퀵 서치":
                self.main_tabs.removeTab(i)
                break

        # 새 탭 생성
        self._create_quick_search_tab()

    def _create_search_ui(self, parent_layout: QVBoxLayout):
        """검색 UI 생성 (데이터 로드됨)"""
        # 스토어 로드
        self._load_partition_store()

        # === 접기/펼치기 가능한 Rating/인원 선택 영역 ===
        self.qs_selection_collapsed = False  # 초기: 펼쳐진 상태

        # 토글 헤더 버튼
        self.qs_selection_toggle_btn = QPushButton("▼ Rating / 인원 선택")
        self.qs_selection_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.qs_selection_toggle_btn.clicked.connect(self._toggle_qs_selection_area)
        parent_layout.addWidget(self.qs_selection_toggle_btn)

        # 접을 수 있는 컨테이너
        self.qs_selection_container = QWidget()
        selection_container_layout = QVBoxLayout(self.qs_selection_container)
        selection_container_layout.setContentsMargins(0, 0, 0, 0)
        selection_container_layout.setSpacing(get_scaled_size(6))

        # === 상단: Rating 선택 (EZMode 스타일) - 마진 축소 ===
        rating_frame = QFrame()
        rating_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: 4px;
            }}
        """)
        rating_layout = QVBoxLayout(rating_frame)
        rating_layout.setContentsMargins(6, 4, 6, 4)
        rating_layout.setSpacing(get_scaled_size(4))

        # Rating 제목
        rating_title = QLabel("Rating 선택")
        rating_title.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        rating_layout.addWidget(rating_title)

        # Rating 버튼 그룹
        self.qs_rating_group = QButtonGroup(self)
        self.qs_rating_group.setExclusive(True)
        self.qs_rating_buttons: Dict[str, QPushButton] = {}

        rating_buttons_layout = QHBoxLayout()
        rating_buttons_layout.setSpacing(get_scaled_size(8))

        # Rating 버튼 정의 (EZMode와 동일한 색상)
        rating_info = [
            ('g', 'General', '#4CAF50'),      # 녹색
            ('s', 'Sensitive', '#2196F3'),    # 파란색
            ('q', 'Questionable', '#FF9800'), # 주황색
            ('e', 'Explicit', '#F44336')      # 빨간색
        ]

        for rating_key, rating_label, color in rating_info:
            button = QPushButton(rating_label)
            button.setCheckable(True)
            button.setProperty('rating', rating_key)
            button.setMinimumHeight(get_scaled_size(28))

            # 버튼 스타일 (EZMode 패턴) - 마진 축소
            button.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(14)}px;
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 2px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(4)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                    border-color: {color};
                }}
                QPushButton:checked {{
                    background-color: {color};
                    color: white;
                    border-color: {color};
                    font-weight: bold;
                }}
            """)

            button.clicked.connect(self._on_qs_rating_button_clicked)
            self.qs_rating_group.addButton(button)
            rating_buttons_layout.addWidget(button)
            self.qs_rating_buttons[rating_key] = button

            # 기본 선택
            if rating_key == self.qs_selected_rating:
                button.setChecked(True)

        rating_layout.addLayout(rating_buttons_layout)
        selection_container_layout.addWidget(rating_frame)

        # === Person Category 선택 (EZMode 스타일) - 마진 축소 ===
        person_frame = QFrame()
        person_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: 4px;
            }}
        """)
        person_main_layout = QVBoxLayout(person_frame)
        person_main_layout.setContentsMargins(6, 4, 6, 4)
        person_main_layout.setSpacing(get_scaled_size(4))

        # 인원 선택 제목
        person_title = QLabel("인원 선택")
        person_title.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        person_main_layout.addWidget(person_title)

        # Person 버튼 그룹 (5x3 그리드)
        self.qs_person_group = QButtonGroup(self)
        self.qs_person_group.setExclusive(True)
        self.qs_person_buttons: Dict[str, QPushButton] = {}

        person_grid_layout = QGridLayout()
        person_grid_layout.setSpacing(get_scaled_size(4))

        # Person 버튼 색상 (카테고리별)
        person_color = '#9C27B0'  # 보라색 기본

        for i, pc in enumerate(PERSON_CATEGORIES):
            row = i // 5  # 5열
            col = i % 5

            button = QPushButton(PERSON_LABELS.get(pc, pc))
            button.setCheckable(True)
            button.setProperty('person', pc)
            button.setMinimumHeight(get_scaled_size(26))

            # 버튼 스타일 (Rating과 동일한 패턴) - 마진 축소
            button.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(12)}px;
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 2px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(3)}px;
                    padding: {get_scaled_size(2)}px {get_scaled_size(2)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                    border-color: {person_color};
                }}
                QPushButton:checked {{
                    background-color: {person_color};
                    color: white;
                    border-color: {person_color};
                    font-weight: bold;
                }}
            """)

            button.clicked.connect(self._on_qs_person_button_clicked)
            self.qs_person_group.addButton(button)
            self.qs_person_buttons[pc] = button
            person_grid_layout.addWidget(button, row, col)

            # 기본 선택
            if pc == self.qs_selected_person:
                button.setChecked(True)

        person_main_layout.addLayout(person_grid_layout)
        selection_container_layout.addWidget(person_frame)

        parent_layout.addWidget(self.qs_selection_container)

        # === 파티션 정보 (총 이벤트 / 매칭 이벤트) - 전체 너비 차지 ===
        partition_info_row = QHBoxLayout()
        partition_info_row.setSpacing(get_scaled_size(8))

        # 총 이벤트 수 (진회색 배경) - stretch 1로 전체 너비의 절반 차지
        self.qs_total_events_label = QLabel("총 이벤트 수 : 0")
        self.qs_total_events_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qs_total_events_label.setStyleSheet(f"""
            QLabel {{
                background-color: #555555;
                color: white;
                font-size: {get_scaled_font_size(17)}px;
                font-weight: bold;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        partition_info_row.addWidget(self.qs_total_events_label, 1)

        # 매칭 이벤트 수 (연노랑 배경, 검은 글씨) - stretch 1로 전체 너비의 절반 차지
        # 기본 색상 저장 (피드백용)
        self._qs_matching_default_bg = "#FFF59D"  # 연노랑
        self._qs_matching_highlight_bg = "#FFCC80"  # 연한 주황색 (변경 피드백)

        self.qs_matching_events_label = QLabel("매칭 이벤트 수 : 0")
        self.qs_matching_events_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qs_matching_events_label.setStyleSheet(f"""
            QLabel {{
                background-color: {self._qs_matching_default_bg};
                color: black;
                font-size: {get_scaled_font_size(17)}px;
                font-weight: bold;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        partition_info_row.addWidget(self.qs_matching_events_label, 1)

        parent_layout.addLayout(partition_info_row)

        # === 태그 검색 ===
        search_row = QHBoxLayout()
        self.qs_tag_search_input = QLineEdit()
        self.qs_tag_search_input.setPlaceholderText("태그 검색... (Enter로 추가)")
        self.qs_tag_search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        self.qs_tag_search_input.setProperty("autocomplete_ignore", True)
        self.qs_tag_search_input.textChanged.connect(self._on_qs_tag_search_changed)
        self.qs_tag_search_input.returnPressed.connect(self._on_qs_tag_search_enter)
        search_row.addWidget(self.qs_tag_search_input)

        clear_btn = QPushButton("초기화")
        clear_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        clear_btn.setFixedWidth(130)
        clear_btn.clicked.connect(self._on_qs_clear_tags)
        search_row.addWidget(clear_btn)
        parent_layout.addLayout(search_row)

        # === Include 태그 영역 (진회색 배경) ===
        include_frame = QFrame()
        include_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        include_frame_layout = QVBoxLayout(include_frame)
        include_frame_layout.setContentsMargins(6, 4, 6, 4)
        include_frame_layout.setSpacing(2)

        include_header = QLabel("✓ 포함 태그 (마우스 좌클릭) :")
        include_header.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(13)}px;
                color: {DARK_COLORS['success']};
                font-weight: bold;
            }}
        """)
        include_frame_layout.addWidget(include_header)

        # Include 태그 스크롤 영역 (FlowLayout 사용)
        self.qs_include_scroll = QScrollArea()
        self.qs_include_scroll.setWidgetResizable(True)
        self.qs_include_scroll.setFixedHeight(get_scaled_size(55))
        self.qs_include_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.qs_include_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.qs_include_scroll.setStyleSheet(f"QScrollArea {{ border: none; background-color: {DARK_COLORS['bg_secondary']}; }}")

        self.qs_include_widget = QWidget()
        self.qs_include_widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        self.qs_include_layout = FlowLayout(self.qs_include_widget, margin=0, spacing=get_scaled_size(4))
        self.qs_include_scroll.setWidget(self.qs_include_widget)
        include_frame_layout.addWidget(self.qs_include_scroll)

        parent_layout.addWidget(include_frame)

        # === Exclude 태그 영역 (진회색 배경) ===
        exclude_frame = QFrame()
        exclude_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        exclude_frame_layout = QVBoxLayout(exclude_frame)
        exclude_frame_layout.setContentsMargins(6, 4, 6, 4)
        exclude_frame_layout.setSpacing(2)

        exclude_header = QLabel("✗ 제외 태그 (마우스 우클릭) :")
        exclude_header.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(13)}px;
                color: {DARK_COLORS['error']};
                font-weight: bold;
            }}
        """)
        exclude_frame_layout.addWidget(exclude_header)

        # Exclude 태그 스크롤 영역 (FlowLayout 사용)
        self.qs_exclude_scroll = QScrollArea()
        self.qs_exclude_scroll.setWidgetResizable(True)
        self.qs_exclude_scroll.setFixedHeight(get_scaled_size(40))
        self.qs_exclude_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.qs_exclude_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.qs_exclude_scroll.setStyleSheet(f"QScrollArea {{ border: none; background-color: {DARK_COLORS['bg_secondary']}; }}")

        self.qs_exclude_widget = QWidget()
        self.qs_exclude_widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        self.qs_exclude_layout = FlowLayout(self.qs_exclude_widget, margin=0, spacing=get_scaled_size(4))
        self.qs_exclude_scroll.setWidget(self.qs_exclude_widget)
        exclude_frame_layout.addWidget(self.qs_exclude_scroll)

        parent_layout.addWidget(exclude_frame)

        # === 추천 태그 라벨 ===
        self.qs_recommend_label = QLabel("추천 태그:")
        self.qs_recommend_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(13)}px;
                color: {DARK_COLORS['text_primary']};
                font-weight: bold;
            }}
        """)
        parent_layout.addWidget(self.qs_recommend_label)

        # === 추천 태그 리스트 (스크롤, 3열 그리드, 진회색 배경) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        self.qs_tag_list_widget = QWidget()
        self.qs_tag_list_widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        self.qs_tag_list_layout = QGridLayout(self.qs_tag_list_widget)
        self.qs_tag_list_layout.setContentsMargins(4, 4, 4, 4)
        self.qs_tag_list_layout.setSpacing(4)

        # 3열 균등 분배를 위한 column stretch 설정
        self.qs_tag_list_layout.setColumnStretch(0, 1)
        self.qs_tag_list_layout.setColumnStretch(1, 1)
        self.qs_tag_list_layout.setColumnStretch(2, 1)

        scroll_area.setWidget(self.qs_tag_list_widget)
        parent_layout.addWidget(scroll_area, 1)

        # === 하단: 버튼 영역 (왼쪽: 미리보기+페이지, 오른쪽: 자동생성/생성) ===
        bottom_frame = QFrame()
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(0, get_scaled_size(8), 0, 0)
        bottom_layout.setSpacing(get_scaled_size(8))

        # 왼쪽: 프롬프트 미리보기 버튼
        self.qs_preview_btn = QPushButton("프롬프트 미리보기")
        self.qs_preview_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.qs_preview_btn.clicked.connect(self._on_qs_show_preview_popup)
        bottom_layout.addWidget(self.qs_preview_btn)

        # 페이지 네비게이션 (< 페이지정보 >)
        nav_style = f"""
            QPushButton {{
                font-size: {get_scaled_font_size(14)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                min-width: {get_scaled_size(28)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:disabled {{
                color: {DARK_COLORS['text_disabled']};
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
        """

        self.qs_page_prev_btn = QPushButton("<")
        self.qs_page_prev_btn.setStyleSheet(nav_style)
        self.qs_page_prev_btn.setFixedWidth(get_scaled_size(32))
        self.qs_page_prev_btn.clicked.connect(self._on_qs_page_prev)
        self.qs_page_prev_btn.setEnabled(False)  # 초기: 비활성화
        bottom_layout.addWidget(self.qs_page_prev_btn)

        self.qs_page_label = QLabel("1 / 1")
        self.qs_page_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(12)}px;
                color: {DARK_COLORS['text_secondary']};
                padding: 0 {get_scaled_size(4)}px;
            }}
        """)
        bottom_layout.addWidget(self.qs_page_label)

        self.qs_page_next_btn = QPushButton(">")
        self.qs_page_next_btn.setStyleSheet(nav_style)
        self.qs_page_next_btn.setFixedWidth(get_scaled_size(32))
        self.qs_page_next_btn.clicked.connect(self._on_qs_page_next)
        self.qs_page_next_btn.setEnabled(False)  # 초기: 비활성화
        bottom_layout.addWidget(self.qs_page_next_btn)

        # Stretch - 중앙 공백
        bottom_layout.addStretch()

        # 오른쪽: 자동생성 체크박스
        self.qs_auto_generate_check = QCheckBox("자동 생성 ")
        self.qs_auto_generate_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.qs_auto_generate_check.stateChanged.connect(self._on_qs_auto_generate_changed)
        bottom_layout.addWidget(self.qs_auto_generate_check)

        # 오른쪽: 생성 시작 버튼
        self.qs_generate_btn = QPushButton("▶️ 생성 시작")
        self.qs_generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.qs_generate_btn.setFixedWidth(get_scaled_size(150))
        self.qs_generate_btn.clicked.connect(self._on_qs_generate_start)
        bottom_layout.addWidget(self.qs_generate_btn)

        parent_layout.addWidget(bottom_frame)

        # 미리보기 팝업 참조 초기화
        self.qs_preview_popup = None
        self._qs_auto_generate_pending = False

        # 초기 데이터 로드
        self._update_qs_partition_info()
        self._apply_qs_auto_tags()
        self._refresh_qs_tag_list()

    def _load_partition_store(self):
        """파티션 스토어 로드 (TGPS 바이너리 포맷)"""
        TGPS_MAGIC = b'TGPS'

        try:
            if not PARTITION_METADATA_FILE.exists():
                print(f"[QuickSearch] 메타데이터 파일 없음: {PARTITION_METADATA_FILE}")
                self._init_empty_metadata()
                return

            with open(PARTITION_METADATA_FILE, 'rb') as f:
                # 매직 넘버 확인
                magic = f.read(4)
                if magic != TGPS_MAGIC:
                    print(f"[QuickSearch] 잘못된 파일 포맷: {magic}")
                    self._init_empty_metadata()
                    return

                # 버전 읽기
                version = struct.unpack('<H', f.read(2))[0]

                # 압축 데이터 길이 및 데이터 읽기
                compressed_len = struct.unpack('<I', f.read(4))[0]
                compressed = f.read(compressed_len)

            # LZMA 압축 해제 및 pickle 로드
            data = lzma.decompress(compressed)
            metadata = pickle.loads(data)

            self.qs_tag_to_id = metadata.get('tag_to_id', {})
            self.qs_id_to_tag = {int(k): v for k, v in metadata.get('id_to_tag', {}).items()}
            self.qs_tag_freq = metadata.get('tag_freq', {})
            self.qs_partition_info = metadata.get('partitions', {})

            print(f"[QuickSearch] 메타데이터 로드 완료 (v{version}): {len(self.qs_tag_to_id)} 태그, {len(self.qs_partition_info)} 파티션")

        except Exception as e:
            print(f"[QuickSearch] 메타데이터 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            self._init_empty_metadata()

    def _init_empty_metadata(self):
        """빈 메타데이터 초기화"""
        self.qs_tag_to_id = {}
        self.qs_id_to_tag = {}
        self.qs_tag_freq = {}
        self.qs_partition_info = {}

    def _on_qs_rating_button_clicked(self):
        """Rating 버튼 클릭 이벤트 (EZMode 스타일)"""
        button = self.sender()
        if button and button.isChecked():
            rating = button.property('rating')
            self._on_qs_rating_changed(rating)
            print(f"[QuickSearch] Rating selected: {rating}")

    def _on_qs_rating_changed(self, rating: str):
        """Rating 변경"""
        self.qs_selected_rating = rating
        self._update_qs_partition_info()
        self._refresh_qs_tag_list()

    def _on_qs_person_button_clicked(self):
        """Person 버튼 클릭 이벤트 (EZMode 스타일)"""
        button = self.sender()
        if button and button.isChecked():
            person = button.property('person')
            self._on_qs_person_changed(person)
            print(f"[QuickSearch] Person selected: {person}")

    def _on_qs_person_changed(self, person: str):
        """Person Category 변경"""
        self.qs_selected_person = person
        self._apply_qs_auto_tags()
        self._update_qs_partition_info()
        self._refresh_qs_tag_list()

    def _apply_qs_auto_tags(self, reset_all: bool = False):
        """자동 태그 적용

        Args:
            reset_all: True면 모든 태그 초기화, False면 자동 태그만 교체 (사용자 태그 유지)
        """
        # 모든 인원 카테고리의 자동 태그 집합
        all_auto_tags = set()
        for tags in PERSON_AUTO_TAGS.values():
            all_auto_tags.update(tags)

        # 현재 선택된 인원의 자동 태그
        new_auto_tags = set(PERSON_AUTO_TAGS.get(self.qs_selected_person, []))

        if reset_all:
            # 전체 초기화: 새 자동 태그만 적용
            self.qs_include_tags = list(new_auto_tags)
            self.qs_exclude_tags = set()
        else:
            # 자동 태그만 교체: 사용자 선택 태그 유지
            # 1. 기존 자동 태그 제거 (현재 include에서 all_auto_tags에 해당하는 것만 제거)
            user_tags = [t for t in self.qs_include_tags if t not in all_auto_tags]

            # 2. 새 자동 태그를 앞에 추가 + 사용자 태그
            self.qs_include_tags = list(new_auto_tags) + user_tags

            # Exclude에서도 새 자동 태그는 제거 (충돌 방지)
            self.qs_exclude_tags -= new_auto_tags

        self._update_qs_tag_labels()

    def _update_qs_partition_info(self):
        """파티션 정보 업데이트"""
        partition_key = f"{self.qs_selected_rating}_{self.qs_selected_person}"

        # 총 이벤트 수 업데이트
        if partition_key in self.qs_partition_info:
            info = self.qs_partition_info[partition_key]
            total_count = info.get('num_events', 0)
        else:
            total_count = 0

        self.qs_total_events_label.setText(f"총 이벤트 수 : {total_count:,}")

        # 파티션 변경 시 파티션 로드
        if partition_key != self.qs_current_partition_key:
            self._load_qs_partition(partition_key)

        # 필터링 수행 및 매칭 이벤트 수 업데이트
        self._update_qs_matching_events()

        # Person 버튼 카운트 업데이트
        for pc, btn in self.qs_person_buttons.items():
            pk = f"{self.qs_selected_rating}_{pc}"
            if pk in self.qs_partition_info:
                count = self.qs_partition_info[pk].get('num_events', 0)
                btn.setText(f"{PERSON_LABELS.get(pc, pc)} ({count:,})")
            else:
                btn.setText(f"{PERSON_LABELS.get(pc, pc)} (0)")

    def _load_qs_partition(self, partition_key: str):
        """파티션 파일 로드"""
        if not HAS_NUMPY:
            print("[QuickSearch] NumPy가 없어 파티션 로드 불가")
            self.qs_current_partition = None
            self.qs_current_partition_key = None
            return

        partition_file = QUICK_SEARCH_DIR / f"{partition_key}.tgp"
        if not partition_file.exists():
            print(f"[QuickSearch] 파티션 파일 없음: {partition_file}")
            self.qs_current_partition = None
            self.qs_current_partition_key = None
            return

        try:
            self.qs_current_partition = SinglePartitionStore.load(str(partition_file))
            self.qs_current_partition_key = partition_key
            print(f"[QuickSearch] 파티션 로드 완료: {partition_key} ({self.qs_current_partition.num_events:,} events)")
        except Exception as e:
            print(f"[QuickSearch] 파티션 로드 실패: {e}")
            self.qs_current_partition = None
            self.qs_current_partition_key = None

    def _update_qs_matching_events(self):
        """필터링된 매칭 이벤트 수 업데이트"""
        if self.qs_current_partition is None or not HAS_NUMPY:
            # 파티션 없음 - 총 이벤트 수 표시
            partition_key = f"{self.qs_selected_rating}_{self.qs_selected_person}"
            if partition_key in self.qs_partition_info:
                total_count = self.qs_partition_info[partition_key].get('num_events', 0)
            else:
                total_count = 0
            self.qs_matching_events_label.setText(f"매칭 이벤트 수 : {total_count:,}")
            self.qs_matching_indices = []
            return

        # 필터링 수행
        required_tags = set(self.qs_include_tags) if self.qs_include_tags else None
        excluded_tags = self.qs_exclude_tags if self.qs_exclude_tags else None

        self.qs_matching_indices = self.qs_current_partition.filter_events(
            required_tags=required_tags,
            excluded_tags=excluded_tags,
            tag_to_id=self.qs_tag_to_id
        )

        matching_count = len(self.qs_matching_indices)
        self.qs_matching_events_label.setText(f"매칭 이벤트 수 : {matching_count:,}")

        # 태그 카운트 업데이트 (매칭된 이벤트 기준)
        if len(self.qs_matching_indices) > 0:
            self.qs_tag_counts = self.qs_current_partition.get_tag_counts(
                self.qs_matching_indices,
                id_to_tag=self.qs_id_to_tag
            )
        else:
            self.qs_tag_counts = {}

    def _toggle_qs_selection_area(self):
        """Rating/인원 선택 영역 접기/펼치기"""
        self.qs_selection_collapsed = not self.qs_selection_collapsed

        if self.qs_selection_collapsed:
            self.qs_selection_container.hide()
            self.qs_selection_toggle_btn.setText("▶ Rating / 인원 선택")
        else:
            self.qs_selection_container.show()
            self.qs_selection_toggle_btn.setText("▼ Rating / 인원 선택")

    def _on_qs_tag_search_enter(self):
        """태그 검색 Enter 입력 - 태그 직접 추가"""
        search_text = self.qs_tag_search_input.text().strip()
        if not search_text:
            return

        # 이미 선택되어 있는지 확인
        if search_text in self.qs_include_tags:
            print(f"[QuickSearch] Tag already in include: {search_text}")
            self.qs_tag_search_input.clear()
            return

        # Include 태그에 추가
        self.qs_include_tags.append(search_text)
        self._update_qs_tag_labels()
        self.qs_tag_search_input.clear()
        self._flash_qs_matching_label()  # 피드백 효과
        self._update_qs_matching_events()  # 필터링 업데이트
        self._refresh_qs_tag_list()
        print(f"[QuickSearch] Tag added via Enter: {search_text}")

    def _update_qs_tag_labels(self):
        """태그 선택 라벨 업데이트 (FlowLayout 기반)"""
        auto_tags = set(PERSON_AUTO_TAGS.get(self.qs_selected_person, []))

        # Include 레이아웃 초기화
        while self.qs_include_layout.count():
            item = self.qs_include_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Include 태그 버튼 생성
        for tag in self.qs_include_tags:
            # 자동 태그는 보라색, 일반 태그는 파란색
            if tag in auto_tags:
                bg_color = "#9B59B6"  # 보라색 (자동 태그)
            else:
                bg_color = DARK_COLORS['accent_blue']  # 파란색

            tag_btn = QPushButton(f"✕ {tag}")
            tag_btn.setProperty('tag', tag)
            tag_btn.setProperty('is_include', True)
            tag_btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(14)}px;
                    background-color: {bg_color};
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(3)}px;
                    padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['error']};
                }}
            """)
            tag_btn.clicked.connect(self._on_qs_remove_tag)
            self.qs_include_layout.addWidget(tag_btn)

        # Exclude 레이아웃 초기화
        while self.qs_exclude_layout.count():
            item = self.qs_exclude_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Exclude 태그 버튼 생성
        for tag in sorted(self.qs_exclude_tags):
            tag_btn = QPushButton(f"✕ {tag}")
            tag_btn.setProperty('tag', tag)
            tag_btn.setProperty('is_include', False)
            tag_btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(14)}px;
                    background-color: {DARK_COLORS['error']};
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(3)}px;
                    padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                }}
                QPushButton:hover {{
                    background-color: #d32f2f;
                }}
            """)
            tag_btn.clicked.connect(self._on_qs_remove_tag)
            self.qs_exclude_layout.addWidget(tag_btn)

    def _on_qs_remove_tag(self):
        """태그 제거 버튼 클릭"""
        button = self.sender()
        tag = button.property('tag')
        is_include = button.property('is_include')

        removed = False
        if is_include:
            if tag in self.qs_include_tags:
                self.qs_include_tags.remove(tag)
                print(f"[QuickSearch] Include tag removed: {tag}")
                removed = True
        else:
            if tag in self.qs_exclude_tags:
                self.qs_exclude_tags.remove(tag)
                print(f"[QuickSearch] Exclude tag removed: {tag}")
                removed = True

        if removed:
            self._flash_qs_matching_label()  # 피드백 효과

        self._update_qs_tag_labels()
        self._update_qs_matching_events()  # 필터링 업데이트
        self._refresh_qs_tag_list()

    def _on_qs_tag_search_changed(self, text: str):
        """태그 검색 텍스트 변경"""
        self._refresh_qs_tag_list(text)

    def _on_qs_clear_tags(self):
        """태그 초기화 (모든 태그 리셋)"""
        self._apply_qs_auto_tags(reset_all=True)  # 전체 초기화
        self.qs_tag_search_input.clear()
        self._update_qs_matching_events()  # 필터링 업데이트
        self._refresh_qs_tag_list()

    def _refresh_qs_tag_list(self, search_filter: str = "", reset_page: bool = True):
        """태그 리스트 새로고침 (3열 그리드 레이아웃 + 페이지네이션)

        Args:
            search_filter: 검색 필터 텍스트
            reset_page: True면 페이지를 0으로 리셋 (새 검색/필터 시)
        """
        # 기존 아이템 제거
        while self.qs_tag_list_layout.count():
            item = self.qs_tag_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 필터링된 태그 카운트 사용 (없으면 전체 빈도 사용)
        if self.qs_tag_counts:
            # 필터링된 이벤트 기준 태그 빈도
            tag_source = self.qs_tag_counts
        else:
            # 전체 태그 빈도 (파티션 없거나 필터링 미적용)
            tag_source = self.qs_tag_freq

        # 태그 빈도순 정렬
        sorted_tags = sorted(
            tag_source.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # 검색 필터 적용
        if search_filter:
            search_lower = search_filter.lower()
            sorted_tags = [(t, f) for t, f in sorted_tags if search_lower in t.lower()]

        # 이미 선택된 태그는 제외
        selected_set = set(self.qs_include_tags) | self.qs_exclude_tags
        sorted_tags = [(t, f) for t, f in sorted_tags if t not in selected_set]

        # 매칭 이벤트 수와 동일한 빈도의 태그 제외 (필터링 효과 없음)
        matching_count = len(self.qs_matching_indices) if hasattr(self, 'qs_matching_indices') else 0
        if matching_count > 0:
            sorted_tags = [(t, f) for t, f in sorted_tags if f < matching_count]

        # 전체 필터링된 태그 저장
        self.qs_total_filtered_tags = sorted_tags

        # 페이지 리셋 (새 검색/필터 시)
        if reset_page:
            self.qs_tag_page = 0

        # 페이지네이션 계산
        total_tags = len(sorted_tags)
        total_pages = max(1, (total_tags + self.qs_tags_per_page - 1) // self.qs_tags_per_page)

        # 페이지 범위 보정
        if self.qs_tag_page >= total_pages:
            self.qs_tag_page = max(0, total_pages - 1)

        start_idx = self.qs_tag_page * self.qs_tags_per_page
        end_idx = min(start_idx + self.qs_tags_per_page, total_tags)
        page_tags = sorted_tags[start_idx:end_idx]

        # 3열 그리드로 표시
        row = 0
        col = 0
        max_cols = 3

        for tag, freq in page_tags:
            item_widget = self._create_qs_tag_item(tag, freq)
            self.qs_tag_list_layout.addWidget(item_widget, row, col)

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        # 추천 태그 라벨 업데이트
        matching_count = len(self.qs_matching_indices) if hasattr(self, 'qs_matching_indices') else 0
        if search_filter:
            self.qs_recommend_label.setText(f"검색 결과 ({total_tags}개 중 {len(page_tags)}개 표시):")
        else:
            self.qs_recommend_label.setText(f"추천 태그 ({total_tags}개 / 매칭 {matching_count:,}건 기준):")

        # 페이지 네비게이션 업데이트
        self._update_qs_page_nav(total_pages)

    def _update_qs_page_nav(self, total_pages: int):
        """페이지 네비게이션 UI 업데이트"""
        current_page = self.qs_tag_page + 1  # 1-based 표시

        # 페이지 라벨 업데이트
        self.qs_page_label.setText(f"{current_page} / {total_pages}")

        # 버튼 활성화/비활성화
        self.qs_page_prev_btn.setEnabled(self.qs_tag_page > 0)
        self.qs_page_next_btn.setEnabled(self.qs_tag_page < total_pages - 1)

    def _on_qs_page_prev(self):
        """이전 페이지"""
        if self.qs_tag_page > 0:
            self.qs_tag_page -= 1
            search_filter = self.qs_tag_search_input.text().strip() if hasattr(self, 'qs_tag_search_input') else ""
            self._refresh_qs_tag_list(search_filter, reset_page=False)

    def _on_qs_page_next(self):
        """다음 페이지"""
        total_tags = len(self.qs_total_filtered_tags)
        total_pages = max(1, (total_tags + self.qs_tags_per_page - 1) // self.qs_tags_per_page)

        if self.qs_tag_page < total_pages - 1:
            self.qs_tag_page += 1
            search_filter = self.qs_tag_search_input.text().strip() if hasattr(self, 'qs_tag_search_input') else ""
            self._refresh_qs_tag_list(search_filter, reset_page=False)

    def _create_qs_tag_item(self, tag: str, freq: int) -> QPushButton:
        """태그 아이템 위젯 생성 (EZMode STEP4 스타일 버튼)"""
        # 빈도 형식
        freq_str = f"({freq:,})" if freq < 1000000 else f"({freq/1000000:.1f}M)"

        button = QPushButton(f"{tag} {freq_str}")
        button.setProperty('tag', tag)
        button.setMinimumHeight(get_scaled_size(30))

        # 3열 그리드에서 균등한 너비를 위해 확장 정책 설정
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        button.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(16)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                padding: {get_scaled_size(4)}px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        button.clicked.connect(self._on_qs_recommend_tag_clicked)

        # 우클릭으로 Exclude 추가
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda pos, t=tag: self._on_qs_add_exclude_tag(t)
        )

        return button

    def _on_qs_recommend_tag_clicked(self):
        """추천 태그 클릭 시 Include에 추가"""
        button = self.sender()
        tag = button.property('tag')
        self._on_qs_add_include_tag(tag)

    def _on_qs_add_include_tag(self, tag: str):
        """Include 태그 추가"""
        if tag not in self.qs_include_tags:
            self.qs_include_tags.append(tag)
            print(f"[QuickSearch] Include tag added: {tag}")
            self._flash_qs_matching_label()  # 피드백 효과
        if tag in self.qs_exclude_tags:
            self.qs_exclude_tags.remove(tag)
        self._update_qs_tag_labels()
        self._update_qs_matching_events()  # 필터링 업데이트
        self._refresh_qs_tag_list()

    def _on_qs_add_exclude_tag(self, tag: str):
        """Exclude 태그 추가 (좌클릭: Include, 우클릭: Exclude)"""
        auto_tags = set(PERSON_AUTO_TAGS.get(self.qs_selected_person, []))
        if tag in auto_tags:
            return  # 자동 태그는 제외 불가

        if tag not in self.qs_exclude_tags:
            self.qs_exclude_tags.add(tag)
            print(f"[QuickSearch] Exclude tag added: {tag}")
            self._flash_qs_matching_label()  # 피드백 효과
        if tag in self.qs_include_tags:
            self.qs_include_tags.remove(tag)
        self._update_qs_tag_labels()
        self._update_qs_matching_events()  # 필터링 업데이트
        self._refresh_qs_tag_list()

    def _generate_qs_random_prompt(self) -> str:
        """랜덤 프롬프트 생성 (문자열 반환)"""
        # Include 태그 + 랜덤 태그 조합
        result_tags = list(self.qs_include_tags)

        # 필터링된 태그 카운트 사용 (없으면 전체 빈도 사용)
        if self.qs_tag_counts:
            tag_source = self.qs_tag_counts
        else:
            tag_source = self.qs_tag_freq

        # 랜덤 태그 추가 (상위 빈도 태그에서)
        available_tags = [
            t for t, f in sorted(tag_source.items(), key=lambda x: x[1], reverse=True)[:500]
            if t not in result_tags and t not in self.qs_exclude_tags
        ]

        # 5-15개 랜덤 추가
        num_random = random.randint(5, 15)
        if available_tags:
            random_tags = random.sample(available_tags, min(num_random, len(available_tags)))
            result_tags.extend(random_tags)

        # 셔플 (자동 태그 제외)
        auto_tags = PERSON_AUTO_TAGS.get(self.qs_selected_person, [])
        non_auto = [t for t in result_tags if t not in auto_tags]
        random.shuffle(non_auto)

        final_tags = list(auto_tags) + non_auto

        # Rating에 따른 태그 추가 (프롬프트 끝에)
        rating_suffix_tags = {
            'g': ['rating:general'],
            's': ['rating:sensitive'],
            'q': ['rating:questionable'],
            'e': ['rating:explicit', 'nsfw']
        }
        suffix_tags = rating_suffix_tags.get(self.qs_selected_rating, [])
        final_tags.extend(suffix_tags)

        return ", ".join(final_tags)

    def _on_qs_show_preview_popup(self):
        """프롬프트 미리보기 팝업 표시"""
        # 랜덤 프롬프트 생성
        prompt = self._generate_qs_random_prompt()

        # 팝업이 이미 표시 중이면 숨기고 종료 (토글 동작)
        if self.qs_preview_popup is not None:
            try:
                if self.qs_preview_popup.isVisible():
                    self.qs_preview_popup.hide()
                    return
            except RuntimeError:
                # C++ 객체가 삭제된 경우
                self.qs_preview_popup = None

        # 팝업이 없거나 삭제된 경우 새로 생성
        if self.qs_preview_popup is None:
            self.qs_preview_popup = QsPreviewPopup(prompt, self)
            self.qs_preview_popup.generate_requested.connect(self._on_qs_preview_generate)
            self.qs_preview_popup.refresh_requested.connect(self._on_qs_preview_refresh)
        else:
            # 기존 팝업 재사용 - 프롬프트만 업데이트
            self.qs_preview_popup.set_prompt(prompt)

        # 버튼 위치 기준으로 팝업 위치 계산
        btn_pos = self.qs_preview_btn.mapToGlobal(QPoint(0, 0))
        popup_x = btn_pos.x()
        popup_y = btn_pos.y() - self.qs_preview_popup.sizeHint().height() - 10

        # 화면 경계 확인
        if popup_y < 0:
            popup_y = btn_pos.y() + self.qs_preview_btn.height() + 10

        self.qs_preview_popup.move(popup_x, popup_y)
        self.qs_preview_popup.show()

    def _on_qs_preview_refresh(self):
        """미리보기 팝업 새로고침"""
        if self.qs_preview_popup:
            new_prompt = self._generate_qs_random_prompt()
            self.qs_preview_popup.set_prompt(new_prompt)

    def _on_qs_preview_generate(self, prompt: str):
        """미리보기 팝업에서 생성 요청"""
        # 팝업 숨기기 (삭제하지 않음)
        if self.qs_preview_popup:
            self.qs_preview_popup.hide()

        # virtual row 생성 및 즉시 생성
        self._execute_qs_generation(prompt)

    def _on_qs_auto_generate_changed(self, state):
        """자동 생성 체크박스 변경"""
        if state == Qt.CheckState.Checked.value:
            print("[QuickSearch] 자동 생성 활성화")
        else:
            print("[QuickSearch] 자동 생성 비활성화")

    def _on_qs_generate_start(self):
        """생성 시작 버튼 클릭"""
        # 매칭된 이벤트가 없으면 경고
        if not hasattr(self, 'qs_matching_indices') or len(self.qs_matching_indices) == 0:
            self._show_warning("알림", "매칭된 이벤트가 없습니다. 태그 조건을 조정해주세요.")
            return

        # 자동 생성이 활성화되어 있으면 플래그 설정
        if self.qs_auto_generate_check.isChecked():
            self._qs_auto_generate_pending = True

        # 랜덤 프롬프트 생성 및 실행
        prompt = self._generate_qs_random_prompt()
        self._execute_qs_generation(prompt)

    def _execute_qs_generation(self, prompt: str):
        """virtual row 생성 및 생성 파이프라인 실행"""
        import pandas as pd

        # virtual source_row 생성
        source_row_dict = {
            'general': prompt,
            'rating': self.qs_selected_rating,
            'character': '',
            'artist': '',
            'copyright': '',
            'meta': '',
            'quality': '',
        }

        # parent_app을 통해 생성 요청
        if hasattr(self, 'parent_app') and self.parent_app:
            if hasattr(self.parent_app, 'on_generate_with_image_requested'):
                # on_generate_with_image_requested 사용
                self.parent_app.on_generate_with_image_requested(source_row_dict)
                print(f"[QuickSearch] 생성 요청: {prompt[:50]}...")
            elif hasattr(self.parent_app, 'on_instant_generation_requested'):
                # 폴백: on_instant_generation_requested
                source_row = pd.Series(source_row_dict)
                self.parent_app.on_instant_generation_requested(source_row)
                print(f"[QuickSearch] 생성 요청 (폴백): {prompt[:50]}...")
            else:
                self._show_warning("오류", "생성 기능을 사용할 수 없습니다.")
        else:
            self._show_warning("오류", "parent_app이 연결되지 않았습니다.")

    def _flash_qs_matching_label(self):
        """매칭 이벤트 수 라벨에 연한 주황색 피드백 효과"""
        # 연한 주황색으로 변경
        self.qs_matching_events_label.setStyleSheet(f"""
            QLabel {{
                background-color: {self._qs_matching_highlight_bg};
                color: black;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        # 300ms 후 원래 색상으로 복원
        QTimer.singleShot(300, self._restore_qs_matching_label_style)

    def _restore_qs_matching_label_style(self):
        """매칭 이벤트 수 라벨 스타일 복원"""
        self.qs_matching_events_label.setStyleSheet(f"""
            QLabel {{
                background-color: {self._qs_matching_default_bg};
                color: black;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
