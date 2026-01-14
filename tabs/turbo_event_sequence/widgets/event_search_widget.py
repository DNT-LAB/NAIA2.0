"""
Event Search Widget

이벤트 데이터셋 검색 UI - Parent/Child 분리 검색
"""

import sys
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QLineEdit, QPushButton, QButtonGroup,
    QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QProgressBar,
    QCheckBox, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot, QTimer
from PyQt6.QtGui import QColor, QBrush, QPixmap, QImage
import json
from pathlib import Path
import urllib.request
import ssl

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# .experimental 경로 추가
_experimental_path = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '.experimental'
)
sys.path.insert(0, _experimental_path)

# SSL 컨텍스트 설정
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

# 데이터셋 URL 및 파일 정보
DATASET_CONFIG = {
    'NAIA_1girl': {
        'filename': 'NAIA_event_dataset_1girl.parquet',
        'url': 'https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAIA_event_dataset_1girl.parquet',
        'description': '1girl 시퀀스만 포함'
    },
    'Favorites': {
        'filename': 'NAIA_event_dataset_personal.parquet',
        'url': None,  # 로컬 전용
        'description': '저장된 즐겨찾기'
    }
}


class DatasetDownloadWorker(QThread):
    """데이터셋 다운로드 워커"""
    progress_updated = pyqtSignal(int, str)  # percent, message
    download_finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, url: str, target_path: Path, parent=None):
        super().__init__(parent)
        self.url = url
        self.target_path = target_path
        self._cancelled = False

    def cancel(self):
        """다운로드 취소"""
        self._cancelled = True

    def run(self):
        """다운로드 실행"""
        try:
            self.progress_updated.emit(0, "다운로드 준비 중...")

            # 헤더 설정
            headers = {
                'User-Agent': 'NAIA/2.0.0 TurboEventSequence'
            }

            request = urllib.request.Request(self.url, headers=headers)

            # 대상 디렉토리 생성
            self.target_path.parent.mkdir(parents=True, exist_ok=True)

            # 임시 파일 경로
            temp_path = self.target_path.with_suffix('.tmp')

            # 다운로드
            with urllib.request.urlopen(request, context=SSL_CONTEXT) as response:
                total_size = int(response.headers.get('content-length', 0))
                block_size = 8192
                downloaded = 0

                with open(temp_path, 'wb') as out_file:
                    while True:
                        if self._cancelled:
                            out_file.close()
                            if temp_path.exists():
                                temp_path.unlink()
                            self.download_finished.emit(False, "다운로드가 취소되었습니다.")
                            return

                        block = response.read(block_size)
                        if not block:
                            break
                        downloaded += len(block)
                        out_file.write(block)

                        if total_size > 0:
                            percent = min(99, (downloaded * 99) // total_size)
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            self.progress_updated.emit(
                                percent,
                                f"다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)"
                            )

            # 임시 파일을 최종 파일로 이동
            if temp_path.exists():
                if self.target_path.exists():
                    self.target_path.unlink()
                temp_path.rename(self.target_path)

            self.progress_updated.emit(100, "완료!")
            self.download_finished.emit(True, f"데이터셋 다운로드 완료: {self.target_path.name}")

        except urllib.error.HTTPError as e:
            self.download_finished.emit(False, f"HTTP 오류 {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            self.download_finished.emit(False, f"네트워크 오류: {e.reason}")
        except Exception as e:
            self.download_finished.emit(False, f"오류: {str(e)}")


class DatasetLoaderThread(QThread):
    """데이터셋 로드 스레드"""
    loaded = pyqtSignal(object)  # EventSearcher 또는 None
    error = pyqtSignal(str)

    def __init__(self, parquet_path: str = None):
        super().__init__()
        self.parquet_path = parquet_path

    def run(self):
        try:
            from event_search_utils import EventSearcher
            if self.parquet_path and os.path.exists(self.parquet_path):
                searcher = EventSearcher(self.parquet_path)
                self.loaded.emit(searcher)
            else:
                self.error.emit(f"파일을 찾을 수 없음: {self.parquet_path}")
                self.loaded.emit(None)
        except Exception as e:
            self.error.emit(str(e))
            self.loaded.emit(None)


class EventSearchWidget(QWidget):
    """이벤트 검색 위젯"""

    # 시그널
    parent_selected = pyqtSignal(int, object)  # parent_id, sequence_df
    search_completed = pyqtSignal(int)  # result_count
    preview_image_ready = pyqtSignal(object)  # PIL Image 또는 None (이미지 뷰어에 표시)
    favorite_saved = pyqtSignal(int)  # Favorite 저장 완료 시 parent_id 전달
    continuous_generation_requested = pyqtSignal(int)  # 연속 생성 요청 시 다음 parent_id 전달

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.searcher = None
        self.current_results = None
        self.active_page_filters = set()  # 활성화된 페이지 필터
        self.current_mode = 'NAIA_1girl'  # 현재 모드
        self._download_worker = None  # 다운로드 워커
        self._preview_enabled = True  # 미리보기 활성화 상태
        self._current_selected_id = None  # 현재 선택된 Parent ID
        self._current_sequence_df = None  # 현재 선택된 시퀀스 데이터
        self._saved_favorites = set()  # 저장된 favorite ID 목록
        self._continuous_generation = False  # 연속 생성 모드
        self._countdown_timer = None  # 연속 생성 카운트다운 타이머
        self._countdown_seconds = 0  # 카운트다운 남은 초

        # data 폴더 경로
        self.data_dir = Path(os.path.dirname(__file__)).parent.parent.parent / 'data'
        # 저장된 그리드 이미지 폴더 경로
        self.grid_save_dir = Path("save/turbo_events")
        # Personal favorites JSON 경로
        self.personal_json_path = self.data_dir / 'NAIA_event_dataset_personal.json'

        self._load_saved_favorites()
        self._init_ui()
        self._check_and_load_dataset()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 검색 영역
        search_frame = self._create_search_frame()
        layout.addWidget(search_frame)

        # 결과 테이블
        self.result_table = self._create_result_table()
        layout.addWidget(self.result_table, stretch=1)

    def _create_search_frame(self) -> QFrame:
        """검색 프레임 생성 - Parent/Child 분리"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 헤더 행: 타이틀 + 모드 콤보 + 상태
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        title = QLabel("🔍 이벤트 검색")
        title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16) + 3}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        header_layout.addWidget(title)

        # 모드 선택 콤보박스
        self.mode_combo = QComboBox()
        for mode_name in DATASET_CONFIG.keys():
            self.mode_combo.addItem(mode_name)
        self.mode_combo.setCurrentText('NAIA_1girl')
        self.mode_combo.setStyleSheet(self._get_combo_style())
        self.mode_combo.setFixedWidth(get_scaled_size(120))
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        header_layout.addWidget(self.mode_combo)

        header_layout.addStretch()

        self.status_label = QLabel("로딩 중...")
        self.status_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13) + 3}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        header_layout.addWidget(self.status_label)
        layout.addLayout(header_layout)

        # 다운로드 프로그레스바 (숨김 상태로 시작)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(self._get_progress_style())
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Parent 검색 영역
        parent_layout = QHBoxLayout()
        parent_layout.setSpacing(6)

        parent_label = QLabel("Parent:")
        parent_label.setFixedWidth(get_scaled_size(55))
        parent_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13) + 3}px;
            color: {DARK_COLORS['text_primary']};
            font-weight: bold;
        """)
        parent_layout.addWidget(parent_label)

        self.parent_include_input = QLineEdit()
        self.parent_include_input.setPlaceholderText("Include 태그 (쉼표 구분)")
        self.parent_include_input.setStyleSheet(self._get_input_style())
        self.parent_include_input.returnPressed.connect(self._on_search_clicked)
        parent_layout.addWidget(self.parent_include_input, stretch=1)

        self.parent_exclude_input = QLineEdit()
        self.parent_exclude_input.setPlaceholderText("Exclude 태그")
        self.parent_exclude_input.setStyleSheet(self._get_input_style())
        self.parent_exclude_input.returnPressed.connect(self._on_search_clicked)
        parent_layout.addWidget(self.parent_exclude_input, stretch=1)

        layout.addLayout(parent_layout)

        # Child 검색 영역
        child_layout = QHBoxLayout()
        child_layout.setSpacing(6)

        child_label = QLabel("Child:")
        child_label.setFixedWidth(get_scaled_size(55))
        child_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13) + 3}px;
            color: {DARK_COLORS['text_primary']};
            font-weight: bold;
        """)
        child_layout.addWidget(child_label)

        self.child_include_input = QLineEdit()
        self.child_include_input.setPlaceholderText("Include 태그 (쉼표 구분)")
        self.child_include_input.setStyleSheet(self._get_input_style())
        self.child_include_input.returnPressed.connect(self._on_search_clicked)
        child_layout.addWidget(self.child_include_input, stretch=1)

        self.child_exclude_input = QLineEdit()
        self.child_exclude_input.setPlaceholderText("Exclude 태그")
        self.child_exclude_input.setStyleSheet(self._get_input_style())
        self.child_exclude_input.returnPressed.connect(self._on_search_clicked)
        child_layout.addWidget(self.child_exclude_input, stretch=1)

        layout.addLayout(child_layout)

        # 버튼 행
        button_layout = QHBoxLayout()
        button_layout.setSpacing(6)

        self.search_btn = QPushButton("🔍 검색")
        self.search_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.search_btn.clicked.connect(self._on_search_clicked)
        self.search_btn.setEnabled(False)
        button_layout.addWidget(self.search_btn)

        self.random_btn = QPushButton("🎲 랜덤")
        self.random_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.random_btn.clicked.connect(self._on_random_clicked)
        self.random_btn.setEnabled(False)
        button_layout.addWidget(self.random_btn)

        self.clear_btn = QPushButton("🗑️ 클리어")
        self.clear_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        button_layout.addWidget(self.clear_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # 페이지 필터 토글 버튼
        page_filter_layout = QHBoxLayout()
        page_filter_layout.setSpacing(4)

        page_label = QLabel("Pages:")
        page_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(12) + 3}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        page_filter_layout.addWidget(page_label)

        self.page_buttons = {}
        for page_count in [2, 3, 4, 5, 6]:
            btn = QPushButton(f"{page_count}p")
            btn.setCheckable(True)
            btn.setFixedWidth(get_scaled_size(40))
            btn.setStyleSheet(self._get_toggle_button_style())
            btn.clicked.connect(lambda checked, p=page_count: self._on_page_filter_toggled(p, checked))
            page_filter_layout.addWidget(btn)
            self.page_buttons[page_count] = btn

        # 🆕 미리보기 체크박스
        page_filter_layout.addWidget(QLabel(" │ "))  # 구분선
        self.preview_checkbox = QCheckBox("📷 미리보기")
        self.preview_checkbox.setChecked(True)
        self.preview_checkbox.setStyleSheet(self._get_checkbox_style())
        self.preview_checkbox.toggled.connect(self._on_preview_toggled)
        self.preview_checkbox.setToolTip("저장된 그리드 이미지가 있으면 이미지 뷰어에 표시")
        page_filter_layout.addWidget(self.preview_checkbox)

        page_filter_layout.addStretch()
        layout.addLayout(page_filter_layout)

        return frame

    def _get_toggle_button_style(self) -> str:
        """토글 버튼 스타일"""
        return f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(12) + 3}px;
            }}
            QPushButton:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """

    def _get_checkbox_style(self) -> str:
        """체크박스 스타일"""
        return f"""
            QCheckBox {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12) + 3}px;
                spacing: {get_scaled_size(4)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(14)}px;
                height: {get_scaled_size(14)}px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(2)}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(2)}px;
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """

    def _get_input_style(self) -> str:
        """입력 필드 스타일"""
        return f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(13) + 3}px;
            }}
            QLineEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QLineEdit::placeholder {{
                color: {DARK_COLORS['text_secondary']};
            }}
        """

    def _get_combo_style(self) -> str:
        """콤보박스 스타일"""
        return f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(12) + 3}px;
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
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """

    def _get_progress_style(self) -> str:
        """프로그레스바 스타일"""
        return f"""
            QProgressBar {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                text-align: center;
                font-size: {get_scaled_font_size(11) + 3}px;
                color: {DARK_COLORS['text_primary']};
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(3)}px;
            }}
        """

    def _create_result_table(self) -> QTableWidget:
        """결과 테이블 생성 - ID, Ratings, Pages, Tag Preview"""
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["ID", "Ratings", "Pages", "Tag Preview"])

        # 헤더 스타일
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        table.setColumnWidth(0, get_scaled_size(70))
        table.setColumnWidth(1, get_scaled_size(120))  # Ratings 컬럼 확장
        table.setColumnWidth(2, get_scaled_size(50))

        # 테이블 설정
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)

        # 스타일 - 폰트 크기 증가, 다크 테마
        table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                alternate-background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                gridline-color: {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(13) + 3}px;
            }}
            QTableWidget::item {{
                padding: {get_scaled_size(4)}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QTableWidget::item:alternate {{
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QTableWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
            QHeaderView::section {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(6)}px;
                border: none;
                border-bottom: 1px solid {DARK_COLORS['border']};
                font-weight: bold;
                font-size: {get_scaled_font_size(13) + 3}px;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_primary']};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        # 클릭 이벤트
        table.cellClicked.connect(self._on_table_cell_clicked)

        return table

    def _get_dataset_path(self, mode: str) -> Path:
        """모드에 따른 데이터셋 경로 반환"""
        config = DATASET_CONFIG.get(mode)
        if config and config.get('filename'):
            return self.data_dir / config['filename']
        return None

    def _check_and_load_dataset(self):
        """데이터셋 존재 여부 확인 후 로드 또는 다운로드"""
        dataset_path = self._get_dataset_path(self.current_mode)

        if dataset_path is None:
            # 파일명이 없는 경우
            self.status_label.setText("❌ 데이터셋 없음")
            self.search_btn.setEnabled(False)
            self.random_btn.setEnabled(False)
            return

        # Favorites 모드 특수 처리
        if self.current_mode == 'Favorites':
            if dataset_path.exists():
                self._load_dataset(str(dataset_path))
            else:
                self.status_label.setText("💖 Favorites 비어있음")
                self.search_btn.setEnabled(False)
                self.random_btn.setEnabled(False)
            return

        if dataset_path.exists():
            # 파일이 존재하면 로드
            self._load_dataset(str(dataset_path))
        else:
            # 파일이 없으면 다운로드
            self._start_download(self.current_mode)

    def _start_download(self, mode: str):
        """데이터셋 다운로드 시작"""
        config = DATASET_CONFIG.get(mode)
        if not config or not config.get('url'):
            self.status_label.setText("❌ 다운로드 URL 없음")
            return

        target_path = self._get_dataset_path(mode)
        if target_path is None:
            return

        self.status_label.setText("⬇️ 다운로드 시작...")
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.search_btn.setEnabled(False)
        self.random_btn.setEnabled(False)
        self.mode_combo.setEnabled(False)

        self._download_worker = DatasetDownloadWorker(config['url'], target_path)
        self._download_worker.progress_updated.connect(self._on_download_progress)
        self._download_worker.download_finished.connect(self._on_download_finished)
        self._download_worker.start()

    @pyqtSlot(int, str)
    def _on_download_progress(self, percent: int, message: str):
        """다운로드 진행률 업데이트"""
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    @pyqtSlot(bool, str)
    def _on_download_finished(self, success: bool, message: str):
        """다운로드 완료"""
        self.progress_bar.hide()
        self.mode_combo.setEnabled(True)

        if success:
            print(f"✅ {message}")
            # 다운로드 완료 후 로드
            dataset_path = self._get_dataset_path(self.current_mode)
            if dataset_path and dataset_path.exists():
                self._load_dataset(str(dataset_path))
        else:
            self.status_label.setText(f"❌ {message}")
            print(f"❌ Download failed: {message}")

    def _load_dataset(self, parquet_path: str):
        """데이터셋 비동기 로드"""
        self.status_label.setText("📂 로딩 중...")
        self.loader_thread = DatasetLoaderThread(parquet_path)
        self.loader_thread.loaded.connect(self._on_dataset_loaded)
        self.loader_thread.error.connect(self._on_dataset_error)
        self.loader_thread.start()

    @pyqtSlot(object)
    def _on_dataset_loaded(self, searcher):
        """데이터셋 로드 완료"""
        self.searcher = searcher
        if searcher:
            stats = searcher.get_stats()
            self.status_label.setText(
                f"✅ {stats['total_parents']:,} parents"
            )
            self.search_btn.setEnabled(True)
            self.random_btn.setEnabled(True)
            print(f"✅ Event dataset loaded: {stats['total_parents']:,} parents, "
                  f"{stats['total_children']:,} children")
        else:
            self.status_label.setText("❌ 로드 실패")

    @pyqtSlot(str)
    def _on_dataset_error(self, error_msg):
        """데이터셋 로드 에러"""
        self.status_label.setText(f"❌ {error_msg}")
        print(f"❌ Dataset load error: {error_msg}")

    def _on_mode_changed(self, mode: str):
        """모드 변경 시"""
        if mode == self.current_mode:
            return

        self.current_mode = mode
        self.searcher = None
        self.current_results = None
        self.result_table.setRowCount(0)

        # 새 모드에 맞는 데이터셋 로드
        self._check_and_load_dataset()

    def _on_search_clicked(self):
        """검색 버튼 클릭"""
        if not self.searcher:
            return

        # Parent 필터
        parent_include = self.parent_include_input.text().strip() or None
        parent_exclude = self.parent_exclude_input.text().strip() or None

        # Child 필터
        child_include = self.child_include_input.text().strip() or None
        child_exclude = self.child_exclude_input.text().strip() or None

        try:
            # 페이지 필터에 따라 min_children 결정
            # 2p = 1 child, 3p = 2 children, etc.
            if self.active_page_filters:
                min_children = min(p - 1 for p in self.active_page_filters)
            else:
                min_children = 1  # 기본값: 최소 1개 child (2p 이상)

            # Child 필터가 있으면 search_parents_by_child_tags 사용
            if child_include or child_exclude:
                results = self.searcher.search_parents_by_child_tags(
                    child_include=child_include,
                    child_exclude=child_exclude,
                    parent_include=parent_include,
                    parent_exclude=parent_exclude
                )
                # min_children 필터 추가 적용
                if min_children is not None:
                    results['children_count'] = results['id'].map(
                        self.searcher.children_counts
                    ).fillna(0).astype(int)
                    results = results[results['children_count'] >= min_children]
            else:
                # Parent만 검색
                results = self.searcher.search_parents(
                    include=parent_include,
                    exclude=parent_exclude,
                    min_children=min_children
                )

            self.current_results = results
            self._update_table(results)
            self.status_label.setText(f"🔍 {len(results):,}개 결과")
            self.search_completed.emit(len(results))

        except Exception as e:
            self.status_label.setText(f"❌ 검색 오류")
            print(f"Search error: {e}")
            import traceback
            traceback.print_exc()

    def _on_random_clicked(self):
        """랜덤 버튼 클릭"""
        if not self.searcher:
            return

        try:
            parent_include = self.parent_include_input.text().strip() or None
            parent_exclude = self.parent_exclude_input.text().strip() or None
            child_include = self.child_include_input.text().strip() or None
            child_exclude = self.child_exclude_input.text().strip() or None

            # 페이지 필터에 따라 min_children 결정
            if self.active_page_filters:
                min_children = min(p - 1 for p in self.active_page_filters)
            else:
                min_children = 1  # 기본값: 최소 1개 child (2p 이상)

            # Child 필터가 있으면 search_parents_by_child_tags 사용 후 랜덤 샘플
            if child_include or child_exclude:
                all_results = self.searcher.search_parents_by_child_tags(
                    child_include=child_include,
                    child_exclude=child_exclude,
                    parent_include=parent_include,
                    parent_exclude=parent_exclude
                )
                # min_children 필터 추가 적용
                if min_children is not None:
                    all_results['children_count'] = all_results['id'].map(
                        self.searcher.children_counts
                    ).fillna(0).astype(int)
                    all_results = all_results[all_results['children_count'] >= min_children]
                # 랜덤 샘플
                results = all_results.sample(min(50, len(all_results))) if len(all_results) > 0 else all_results
            else:
                results = self.searcher.get_random_parents(
                    n=50,
                    include=parent_include,
                    exclude=parent_exclude,
                    min_children=min_children
                )

            self.current_results = results
            self._update_table(results)
            self.status_label.setText(f"🎲 {len(results)}개 랜덤")

        except Exception as e:
            self.status_label.setText(f"❌ 오류")
            print(f"Random error: {e}")
            import traceback
            traceback.print_exc()

    def _on_clear_clicked(self):
        """클리어 버튼 클릭"""
        self.parent_include_input.clear()
        self.parent_exclude_input.clear()
        self.child_include_input.clear()
        self.child_exclude_input.clear()
        self.result_table.setRowCount(0)
        self.current_results = None
        self.status_label.setText("✅ 준비됨")

    def _on_page_filter_toggled(self, page_count: int, checked: bool):
        """페이지 필터 토글"""
        if checked:
            self.active_page_filters.add(page_count)
        else:
            self.active_page_filters.discard(page_count)

        # 현재 결과 다시 필터링
        if self.current_results is not None:
            self._update_table(self.current_results)

    def _get_sequence_ratings(self, parent_id: int) -> list:
        """시퀀스의 모든 rating 가져오기 (parent + children)"""
        if not self.searcher:
            return []

        try:
            sequence_df = self.searcher.get_sequence(parent_id)
            if sequence_df is None or len(sequence_df) == 0:
                return []

            ratings = []
            # Parent 먼저
            parent_row = sequence_df[sequence_df['has_children'] == True]
            if len(parent_row) > 0:
                ratings.append(str(parent_row.iloc[0].get('rating', '')).lower())

            # Children (ID 순서대로)
            children = sequence_df[sequence_df['has_children'] == False].sort_values('id')
            for _, child in children.iterrows():
                ratings.append(str(child.get('rating', '')).lower())

            return ratings
        except:
            return []

    def _update_table(self, df):
        """테이블 업데이트 - ID, Ratings, Pages, Tag Preview"""
        self.result_table.setRowCount(0)

        if df is None or len(df) == 0:
            return

        # Children count 계산 (없으면 추가)
        if 'children_count' not in df.columns:
            df = df.copy()
            df['children_count'] = df['id'].map(
                self.searcher.children_counts
            ).fillna(0).astype(int)

        # 페이지 필터 적용
        if self.active_page_filters:
            # pages = children_count + 1
            df = df[df['children_count'].apply(lambda x: (x + 1) in self.active_page_filters)]

        # 최대 500개만 표시
        display_df = df.head(500)

        for idx, row in display_df.iterrows():
            row_pos = self.result_table.rowCount()
            self.result_table.insertRow(row_pos)

            parent_id = int(row['id'])

            # ID (저장된 항목 표시)
            is_saved = parent_id in self._saved_favorites
            id_text = f"💖 {parent_id}" if is_saved else str(parent_id)
            id_item = QTableWidgetItem(id_text)
            id_item.setData(Qt.ItemDataRole.UserRole, parent_id)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.result_table.setItem(row_pos, 0, id_item)

            # Ratings (모든 rating 표시: s-s-s-q 형식)
            all_ratings = self._get_sequence_ratings(parent_id)
            ratings_item = QTableWidgetItem()
            ratings_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Rich text로 표시하기 위해 HTML 사용 불가, 대신 텍스트로 표시
            # 색상은 첫 번째 rating 기준으로 설정
            if all_ratings:
                ratings_text = "-".join(all_ratings)
                ratings_item.setText(ratings_text)

                # 가장 심한 rating 기준으로 색상 설정
                rating_priority = {'e': 3, 'q': 2, 's': 1, 'g': 0}
                max_rating = max(all_ratings, key=lambda r: rating_priority.get(r, -1))

                if max_rating == 'e':
                    ratings_item.setForeground(QColor('#ff6b6b'))
                elif max_rating == 'q':
                    ratings_item.setForeground(QColor('#ffa94d'))
                elif max_rating == 's':
                    ratings_item.setForeground(QColor('#69db7c'))
                else:  # g
                    ratings_item.setForeground(QColor('#74c0fc'))
            else:
                # fallback to parent rating only
                rating = str(row.get('rating', '')).lower()
                ratings_item.setText(rating)
                if rating == 'e':
                    ratings_item.setForeground(QColor('#ff6b6b'))
                elif rating == 'q':
                    ratings_item.setForeground(QColor('#ffa94d'))
                elif rating == 's':
                    ratings_item.setForeground(QColor('#69db7c'))
                else:
                    ratings_item.setForeground(QColor('#74c0fc'))

            self.result_table.setItem(row_pos, 1, ratings_item)

            # Pages (Children count + 1)
            pages = int(row.get('children_count', 0)) + 1
            pages_item = QTableWidgetItem(str(pages))
            pages_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.result_table.setItem(row_pos, 2, pages_item)

            # Tag Preview
            tags = str(row.get('general', ''))[:100]
            if len(str(row.get('general', ''))) > 100:
                tags += "..."
            self.result_table.setItem(row_pos, 3, QTableWidgetItem(tags))

    def _on_table_cell_clicked(self, row: int, col: int):
        """테이블 셀 클릭"""
        id_item = self.result_table.item(row, 0)
        if id_item:
            parent_id = id_item.data(Qt.ItemDataRole.UserRole)
            if parent_id and self.searcher:
                # 🆕 현재 선택된 ID 저장 및 미리보기 업데이트
                self._current_selected_id = parent_id
                self._update_preview(parent_id)

                sequence_df = self.searcher.get_sequence(parent_id)
                self._current_sequence_df = sequence_df

                # 🆕 Favorite 버튼 상태 업데이트 (외부 버튼 참조)
                self._update_favorite_button_state(parent_id)

                self.parent_selected.emit(parent_id, sequence_df)

    def _update_favorite_button_state(self, parent_id: int):
        """Favorite 버튼 상태 업데이트 (외부 버튼 참조)"""
        save_btn = getattr(self, '_external_save_btn', None)
        if save_btn:
            if parent_id in self._saved_favorites:
                save_btn.setText("💖 Favorite에 저장됨")
                save_btn.setEnabled(False)
            else:
                save_btn.setText("💖 Favorite에 저장")
                save_btn.setEnabled(True)

    # ===== 미리보기 관련 메서드 =====

    def _on_preview_toggled(self, checked: bool):
        """미리보기 체크박스 토글"""
        self._preview_enabled = checked
        if checked and self._current_selected_id:
            self._update_preview(self._current_selected_id)
        elif not checked:
            # 미리보기 해제 시 이미지 뷰어 클리어
            self.preview_image_ready.emit(None)

    def _get_preview_path(self, parent_id: int) -> Path:
        """미리보기 이미지 경로 반환 (확장자 없음)"""
        return self.grid_save_dir / f"{parent_id}"

    def _update_preview(self, parent_id: int):
        """미리보기 이미지 업데이트 - 이미지 뷰어에 표시"""
        if not self._preview_enabled:
            return

        preview_path = self._get_preview_path(parent_id)
        if preview_path.exists():
            try:
                from PIL import Image
                # PIL Image로 로드하여 시그널 발생
                preview_image = Image.open(str(preview_path))
                preview_image.load()
                self.preview_image_ready.emit(preview_image)
                print(f"📷 Preview loaded: {preview_path}")
                return
            except Exception as e:
                print(f"❌ Preview load error: {e}")

        # 미리보기 없음 - None 전달하지 않음 (기존 이미지 유지)

    def on_grid_saved(self, parent_id: int, save_path: str):
        """그리드 저장 완료 시 호출 (탭에서 호출)

        현재 선택된 Parent의 그리드가 저장되면 미리보기 업데이트
        """
        if self._current_selected_id == parent_id:
            self._update_preview(parent_id)

    def refresh_favorites(self):
        """Favorites 데이터셋 새로고침

        Favorite 저장 후 호출하여 데이터셋 다시 로드
        """
        if self.current_mode == 'Favorites':
            self._check_and_load_dataset()

    # ===== Favorite 관련 메서드 =====

    def _load_saved_favorites(self):
        """저장된 Favorites JSON 로드"""
        self._saved_favorites = set()
        if self.personal_json_path.exists():
            try:
                with open(self.personal_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._saved_favorites = set(data.get('saved_ids', []))
                print(f"💖 Loaded {len(self._saved_favorites)} saved favorites from JSON")
            except Exception as e:
                print(f"❌ Failed to load favorites JSON: {e}")

    def _save_favorites_json(self):
        """Favorites JSON 저장"""
        try:
            self.personal_json_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'saved_ids': list(self._saved_favorites)
            }
            with open(self.personal_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            print(f"💖 Saved {len(self._saved_favorites)} favorites to JSON")
        except Exception as e:
            print(f"❌ Failed to save favorites JSON: {e}")

    def set_current_sequence(self, parent_id: int, sequence_df):
        """현재 시퀀스 설정 (Favorite 저장용) - 탭에서 호출

        Args:
            parent_id: Parent ID
            sequence_df: pandas DataFrame (시퀀스 데이터)
        """
        self._current_selected_id = parent_id
        self._current_sequence_df = sequence_df

        # Favorite 버튼 활성화/비활성화 및 상태 업데이트 (외부 버튼 참조)
        save_btn = getattr(self, '_external_save_btn', None)
        if save_btn:
            if sequence_df is not None and len(sequence_df) > 0:
                if parent_id in self._saved_favorites:
                    save_btn.setText("💖 Favorite에 저장됨")
                    save_btn.setEnabled(False)
                else:
                    save_btn.setText("💖 Favorite에 저장")
                    save_btn.setEnabled(True)
            else:
                save_btn.setEnabled(False)

    def _on_save_favorite_clicked(self):
        """Favorite 저장 버튼 클릭"""
        if self._current_sequence_df is None or len(self._current_sequence_df) == 0:
            return

        parent_id = self._current_selected_id
        if parent_id is None:
            return

        # 이미 저장된 경우 무시
        if parent_id in self._saved_favorites:
            print(f"⚠️ 이미 Favorites에 저장된 시퀀스입니다 (ID: {parent_id})")
            return

        try:
            import pandas as pd

            # Parquet 파일 저장 경로
            personal_parquet_path = self.data_dir / 'NAIA_event_dataset_personal.parquet'

            # 기존 데이터 로드 또는 새 DataFrame 생성
            if personal_parquet_path.exists():
                existing_df = pd.read_parquet(personal_parquet_path)
            else:
                existing_df = pd.DataFrame()

            # 데이터 병합
            if len(existing_df) > 0:
                combined_df = pd.concat([existing_df, self._current_sequence_df], ignore_index=True)
            else:
                combined_df = self._current_sequence_df.copy()

            # Parquet 저장
            combined_df.to_parquet(personal_parquet_path, index=False)

            # JSON에 ID 추가
            self._saved_favorites.add(parent_id)
            self._save_favorites_json()

            # 버튼 상태 업데이트 (외부 버튼 참조)
            save_btn = getattr(self, '_external_save_btn', None)
            if save_btn:
                save_btn.setText("💖 Favorite에 저장됨")
                save_btn.setEnabled(False)

            # 통계
            parent_count = len(combined_df[combined_df['has_children'] == True])
            print(f"💖 Favorite 저장 완료: {personal_parquet_path} ({parent_count} parents)")

            # 시그널 발생
            self.favorite_saved.emit(parent_id)

            # Favorites 모드인 경우 새로고침
            if self.current_mode == 'Favorites':
                self._check_and_load_dataset()

            # 테이블 업데이트 (저장된 항목 표시)
            self._mark_saved_in_table(parent_id)

        except Exception as e:
            print(f"❌ Favorite 저장 오류: {e}")
            import traceback
            traceback.print_exc()

    def _mark_saved_in_table(self, parent_id: int):
        """테이블에서 저장된 항목 표시"""
        for row in range(self.result_table.rowCount()):
            id_item = self.result_table.item(row, 0)
            if id_item:
                item_id = id_item.data(Qt.ItemDataRole.UserRole)
                if item_id == parent_id:
                    # ID 앞에 💖 추가
                    id_item.setText(f"💖 {parent_id}")
                    break

    def is_favorite_saved(self, parent_id: int) -> bool:
        """해당 ID가 Favorites에 저장되었는지 확인"""
        return parent_id in self._saved_favorites

    # ===== 연속 생성 관련 메서드 =====

    # 🆕 UI 컨트롤 콜백 설정 (탭에서 설정)
    def set_ui_controls(self, save_btn, countdown_label, skip_checkbox_getter):
        """외부 UI 컨트롤 참조 설정 (탭에서 호출)

        Args:
            save_btn: Favorite 저장 버튼
            countdown_label: 카운트다운 라벨
            skip_checkbox_getter: skip_generated 체크박스 상태 getter 함수
        """
        self._external_save_btn = save_btn
        self._external_countdown_label = countdown_label
        self._skip_checkbox_getter = skip_checkbox_getter

    def is_continuous_generation_enabled(self) -> bool:
        """연속 생성 모드 활성화 여부"""
        return self._continuous_generation

    def is_skip_generated_enabled(self) -> bool:
        """이미 생성한 이벤트 건너뛰기 활성화 여부"""
        if hasattr(self, '_skip_checkbox_getter') and self._skip_checkbox_getter:
            return self._skip_checkbox_getter()
        return False

    def start_countdown_to_next(self):
        """다음 이벤트로의 카운트다운 시작 (5초)"""
        if not self._continuous_generation:
            return

        countdown_label = getattr(self, '_external_countdown_label', None)

        # 다음 이벤트 ID 찾기
        next_parent_id = self._find_next_parent_id()
        if next_parent_id is None:
            print("🏁 더 이상 생성할 이벤트가 없습니다")
            if countdown_label:
                countdown_label.setText("🏁 완료")
                countdown_label.show()
                QTimer.singleShot(2000, countdown_label.hide)
            return

        # 카운트다운 시작
        self._countdown_seconds = 5
        self._next_parent_id = next_parent_id
        if countdown_label:
            countdown_label.setText(f"⏳ {self._countdown_seconds}초 후 다음 이벤트...")
            countdown_label.show()

        # 타이머 시작
        if self._countdown_timer is None:
            self._countdown_timer = QTimer(self)
            self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_timer.start(1000)

    def _on_countdown_tick(self):
        """카운트다운 틱"""
        self._countdown_seconds -= 1
        countdown_label = getattr(self, '_external_countdown_label', None)

        if self._countdown_seconds <= 0:
            self._countdown_timer.stop()
            if countdown_label:
                countdown_label.hide()

            # 다음 이벤트 선택 및 생성 요청
            self._select_next_event(self._next_parent_id)
        else:
            if countdown_label:
                countdown_label.setText(f"⏳ {self._countdown_seconds}초 후 다음 이벤트...")

    def cancel_countdown(self):
        """카운트다운 취소"""
        if self._countdown_timer:
            self._countdown_timer.stop()
        countdown_label = getattr(self, '_external_countdown_label', None)
        if countdown_label:
            countdown_label.hide()
        print("⏹ 카운트다운 취소됨")

    def _find_next_parent_id(self) -> int:
        """다음 생성할 Parent ID 찾기

        Returns:
            int: 다음 Parent ID 또는 None
        """
        if self.current_results is None or len(self.current_results) == 0:
            return None

        current_id = self._current_selected_id
        if current_id is None:
            return None

        # 현재 결과에서 현재 ID의 위치 찾기
        try:
            ids_list = self.current_results['id'].tolist()
            if current_id not in ids_list:
                return None

            current_index = ids_list.index(current_id)

            # 다음 ID들 순회
            for i in range(current_index + 1, len(ids_list)):
                next_id = ids_list[i]

                # 이미 생성한 이벤트 건너뛰기 체크
                if self.is_skip_generated_enabled():
                    preview_path = self._get_preview_path(next_id)
                    if preview_path.exists():
                        print(f"⏭️ Skip (already generated): {next_id}")
                        continue

                return next_id

            return None

        except Exception as e:
            print(f"❌ Error finding next parent: {e}")
            return None

    def _select_next_event(self, parent_id: int):
        """다음 이벤트 선택 및 생성 요청"""
        if not self.searcher:
            return

        try:
            # 테이블에서 해당 ID 선택
            for row in range(self.result_table.rowCount()):
                id_item = self.result_table.item(row, 0)
                if id_item:
                    item_id = id_item.data(Qt.ItemDataRole.UserRole)
                    if item_id == parent_id:
                        self.result_table.selectRow(row)
                        break

            # 시퀀스 로드 및 선택 시그널 발생
            self._current_selected_id = parent_id
            self._update_preview(parent_id)

            sequence_df = self.searcher.get_sequence(parent_id)
            self._current_sequence_df = sequence_df

            # Favorite 버튼 상태 업데이트 (외부 버튼 참조)
            save_btn = getattr(self, '_external_save_btn', None)
            if save_btn:
                if parent_id in self._saved_favorites:
                    save_btn.setText("💖 Favorite에 저장됨")
                    save_btn.setEnabled(False)
                else:
                    save_btn.setText("💖 Favorite에 저장")
                    save_btn.setEnabled(True)

            self.parent_selected.emit(parent_id, sequence_df)

            # 연속 생성 요청 시그널 발생
            self.continuous_generation_requested.emit(parent_id)

            print(f"🎯 다음 이벤트 선택: {parent_id}")

        except Exception as e:
            print(f"❌ Error selecting next event: {e}")
            import traceback
            traceback.print_exc()
