"""
Clothes Preset Download Worker — HuggingFace 다운로드 + 프로그레스 다이얼로그

naia_clothes_preset 데이터셋을 HuggingFace에서 다운로드.
패턴 참조: ui/event_preset/download_worker.py
"""
from __future__ import annotations

import ssl
import urllib.request
import zipfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QStyleFactory, QVBoxLayout,
)

from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

# ---------------------------------------------------------------------------
# SSL 컨텍스트
# ---------------------------------------------------------------------------
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

# ---------------------------------------------------------------------------
# 다운로드 URL
# ---------------------------------------------------------------------------
DOWNLOAD_URL = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/naia_clothes_preset"


class ClothesPresetDownloadWorker(QThread):
    """naia_clothes_preset 다운로드 워커 (QThread)."""

    progress_updated = pyqtSignal(int, str)     # (percent, message)
    download_finished = pyqtSignal(bool, str)   # (success, message)

    def __init__(self, target_path: Path, parent=None):
        super().__init__(parent)
        self._target_path = target_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self.progress_updated.emit(5, "다운로드 준비 중...")

            if self._target_path.exists():
                if self._validate_zip(self._target_path):
                    self.download_finished.emit(True, "데이터가 이미 존재합니다.")
                    return
                self._target_path.unlink(missing_ok=True)

            self.progress_updated.emit(10, "다운로드 시작...")

            headers = {'User-Agent': 'NAIA/2.0.0 ClothesPreset Module'}
            request = urllib.request.Request(DOWNLOAD_URL, headers=headers)

            temp_path = self._target_path.with_suffix(".download_tmp")

            with urllib.request.urlopen(request, context=SSL_CONTEXT) as response:
                total_size = int(response.headers.get('content-length', 0))
                block_size = 8192
                downloaded = 0

                with open(temp_path, 'wb') as out_file:
                    while True:
                        if self._cancelled:
                            out_file.close()
                            temp_path.unlink(missing_ok=True)
                            self.download_finished.emit(False, "다운로드가 취소되었습니다.")
                            return

                        block = response.read(block_size)
                        if not block:
                            break
                        downloaded += len(block)
                        out_file.write(block)

                        if total_size > 0:
                            percent = min(90, 10 + (downloaded * 80) // total_size)
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            self.progress_updated.emit(
                                percent,
                                f"다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)"
                            )

            self.progress_updated.emit(92, "검증 중...")
            if not self._validate_zip(temp_path):
                temp_path.unlink(missing_ok=True)
                self.download_finished.emit(False, "다운로드된 파일이 손상되었습니다.")
                return

            self.progress_updated.emit(95, "설치 중...")
            temp_path.rename(self._target_path)

            self.progress_updated.emit(100, "완료!")
            self.download_finished.emit(True, "Clothes Preset 데이터 다운로드 완료")

        except urllib.error.HTTPError as e:
            self.download_finished.emit(False, f"HTTP 오류 {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            self.download_finished.emit(False, f"네트워크 오류: {e.reason}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.download_finished.emit(False, f"오류: {str(e)}")

    @staticmethod
    def _validate_zip(path: Path) -> bool:
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                return any(f.endswith(".parquet") for f in zf.namelist())
        except (zipfile.BadZipFile, Exception):
            return False


class ClothesPresetDownloadDialog(QDialog):
    """NAIA 테마 다운로드 프로그레스 다이얼로그."""

    canceled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clothes Preset 데이터 다운로드")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedSize(get_scaled_size(450), get_scaled_size(160))

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(10))
        layout.setContentsMargins(
            get_scaled_size(16), get_scaled_size(16),
            get_scaled_size(16), get_scaled_size(16),
        )

        self.label = QLabel("다운로드 준비 중...")
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                border: none;
            }}
        """)
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyle(QStyleFactory.create("Fusion"))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                text-align: center;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
                height: {get_scaled_size(22)}px;
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(3)}px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setFixedWidth(get_scaled_size(80))
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(16)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def update_progress(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
        self.label.setText(message)

    def mark_finished(self):
        self._finished = True
        self.accept()

    def _on_cancel(self):
        self.cancel_btn.setEnabled(False)
        self.label.setText("취소 중...")
        self.canceled.emit()

    def closeEvent(self, event):
        if getattr(self, '_finished', False):
            event.accept()
        else:
            self.canceled.emit()
            event.ignore()
