import os
import json
import base64
import hashlib
import io
import re
import ssl
import urllib.request
import urllib.error
from pathlib import Path

# SSL 인증서 검증을 위한 certifi 사용
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    # certifi가 없으면 기본 컨텍스트 사용
    SSL_CONTEXT = ssl.create_default_context()
from typing import Dict, List, Optional, Tuple

# TODO(web-dialog): blocking QMessageBox 대체용 stub. .exec() 호출 시 print 만 수행하고
# QMessageBox.StandardButton.No (=65536) 반환하여 destructive confirm 을 안전 차단.
# Web Shell 토스트/모달로 재구현 시 이 stub 제거하고 호출처를 명시적 비동기 패턴으로 교체.
class _PrintMessageBoxStub:
    def __init__(self, title="", text=""):
        self._title = str(title or "")
        self._text = str(text or "")
        self._info = ""
        self._detail = ""
    def setText(self, t): self._text = str(t or "")
    def setWindowTitle(self, t): self._title = str(t or "")
    def setIcon(self, *a, **kw): pass
    def setStyleSheet(self, *a, **kw): pass
    def setStandardButtons(self, *a, **kw): pass
    def setDefaultButton(self, *a, **kw): pass
    def setInformativeText(self, t): self._info = str(t or "")
    def setDetailedText(self, t): self._detail = str(t or "")
    def addButton(self, *a, **kw): return None
    def clickedButton(self): return None
    def standardButton(self, *a, **kw):
        from PyQt6.QtWidgets import QMessageBox as _QMB
        return _QMB.StandardButton.No
    def exec(self):
        suffix = ""
        if self._info: suffix += f" | info: {self._info}"
        if self._detail: suffix += f" | detail: {self._detail}"
        print(f"[Dialog] {self._title}: {self._text}{suffix}")
        from PyQt6.QtWidgets import QMessageBox as _QMB
        return _QMB.StandardButton.No  # destructive confirm 안전 차단

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QLabel, QFileDialog, QMessageBox,
    QPushButton, QFrame, QScrollArea, QMenu, QApplication, QWidgetAction, QComboBox,
    QProgressDialog, QTextEdit, QSizePolicy, QDialog, QDialogButtonBox, QInputDialog,
    QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QPoint, QThread, QBuffer, QIODevice
from PyQt6.QtGui import QPixmap, QPainter, QImage, QAction, QKeyEvent, QColor

from PIL import Image
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from artist_dictionary import artist_dict


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


ARTIST_THUMB_MODES = {
    "NAID4.5F-31000": {
        "path": Path("data/artist_thumbnail_nai.json"),
        "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID4.5_artist_thumbnail_31000/artist_thumbnail_nai",
    },
    "NoobNAI-XL-33000": {
        "path": Path("data/artist_thumbnail.json"),
        "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Noob_artist_thumbnail_33000/artist_thumbnail",
    },
    "ANIMA-22000": {
        "path": Path("data/artist_thumbnail_anima.json"),
        "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima.json",
        "expected_size": 2656390724,
        "sha256": "C831A5B186176AEBED394F320C3E5B75B3ACEB78AF2D97B84D04C277C276252E",
    },
    "ANIMA-44000": {
        "path": Path("data/artist_thumbnail_anima_bucket2.json"),
        "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima_bucket2.json",
        "expected_size": 2604574500,
        "sha256": "3B581E8A5C596B4E2AE001C8842B486BF4D7BC36485D23B0861B0200C41017E2",
    },
    "ANIMA-60000": {
        "path": Path("data/artist_thumbnail_anima_bucket3.json"),
        "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima_bucket3.json",
        "expected_size": 1882040677,
        "sha256": "C564F0A473F32A81DEA43696FBF1CAA477184C957C7C1A8B5B2B21781334FB7B",
    },
}
ARTIST_THUMB_OPTION_MODES = ("NAI", "WEBUI", "COMFYUI")


class StableImageWidget(QWidget):
    """
    이미지 표시 위젯 - Assets Tab에서 가져옴
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._pil_image = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def setPixmap(self, pixmap: QPixmap):
        if pixmap and not pixmap.isNull():
            self._pixmap = pixmap
            self._convert_to_pil()
        else:
            self._pixmap = None
            self._pil_image = None
        self.update()
    
    def _convert_to_pil(self):
        """Convert QPixmap to PIL Image preserving transparency"""
        if not self._pixmap:
            self._pil_image = None
            return
        
        # Convert QPixmap to QImage first to ensure RGBA format
        q_image = self._pixmap.toImage()
        q_image = q_image.convertToFormat(QImage.Format.Format_RGBA8888)
        
        # Save QImage to buffer as PNG
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        q_image.save(buffer, 'PNG')
        
        # Get bytes from QBuffer
        byte_array = buffer.data()
        buffer.close()
        
        # Convert bytes to PIL Image and ensure RGBA
        pil_buffer = io.BytesIO(byte_array.data())
        self._pil_image = Image.open(pil_buffer)
        if self._pil_image.mode != 'RGBA':
            self._pil_image = self._pil_image.convert('RGBA')
    
    def setPilImage(self, pil_image: Image.Image):
        """Set image from PIL Image"""
        if pil_image:
            self._pil_image = pil_image
            # Convert to QPixmap
            from PIL.ImageQt import ImageQt
            q_image = ImageQt(pil_image.convert("RGBA"))
            self._pixmap = QPixmap.fromImage(q_image)
        else:
            self._pixmap = None
            self._pil_image = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(DARK_COLORS['bg_secondary']))
        
        if not self._pixmap:
            painter.setPen(QColor(DARK_COLORS['text_secondary']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "생성된 이미지가 여기에 표시됩니다...")
            return

        widget_size = self.size()
        
        # 위젯 크기에 맞춰 이미지를 스케일링 (폭을 꽉 채우도록)
        scaled_pixmap = self._pixmap.scaled(
            widget_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # 중앙 정렬
        x = (widget_size.width() - scaled_pixmap.width()) // 2
        y = (widget_size.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(x, y, scaled_pixmap)
        painter.end()
    
    def show_context_menu(self, pos: QPoint):
        """Show right-click context menu"""
        if not self._pixmap or not self._pil_image:
            return
        
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        
        copy_action = QAction("📋 이미지 복사", self)
        copy_action.triggered.connect(self.copy_to_clipboard)
        menu.addAction(copy_action)
        
        save_action = QAction("💾 이미지 저장", self)
        save_action.triggered.connect(self.save_image)
        menu.addAction(save_action)
        
        menu.exec(self.mapToGlobal(pos))
    
    def copy_to_clipboard(self):
        """Copy image to clipboard"""
        if self._pixmap:
            QApplication.clipboard().setPixmap(self._pixmap)
    
    def save_image(self):
        """Save image to file"""
        if self._pil_image:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "이미지 저장", "", "PNG Files (*.png);;All Files (*)"
            )
            if file_path:
                self._pil_image.save(file_path)



class JsonLoadWorker(QThread):
    """대용량 JSON 파일 로드 워커 스레드"""
    load_finished = pyqtSignal(object, str)  # data (dict or None), error_message

    def __init__(self, file_path: Path, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            self.load_finished.emit(data, "")
        except Exception as e:
            self.load_finished.emit(None, str(e))


class ThumbnailDownloadWorker(QThread):
    """썸네일 데이터 다운로드 워커 스레드"""
    progress_updated = pyqtSignal(int, str)  # percent, message
    download_finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, mode: str, target_path: Path, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.target_path = target_path
        self._cancelled = False  # 취소 플래그

        self.urls = {
            mode: str(info.get("url") or "")
            for mode, info in ARTIST_THUMB_MODES.items()
        }

    def cancel(self):
        """다운로드 취소"""
        self._cancelled = True

    def run(self):
        """다운로드 실행"""
        try:
            url = self.urls.get(self.mode)
            if not url:
                if self.mode in self.urls:
                    self.download_finished.emit(False, f"다운로드 URL이 아직 설정되지 않았습니다: {self.mode}")
                else:
                    self.download_finished.emit(False, f"알 수 없는 모드: {self.mode}")
                return
                
            self.progress_updated.emit(0, "다운로드 준비 중...")
            
            # 헤더 설정
            headers = {
                'User-Agent': 'NAIA/2.0.0 ArtistThumb Module'
            }
            
            request = urllib.request.Request(url, headers=headers)

            # 임시 파일로 다운로드 (SSL 컨텍스트 사용)
            temp_path = self.target_path.with_suffix('.tmp')

            # urlopen with SSL context for certificate verification
            with urllib.request.urlopen(request, context=SSL_CONTEXT) as response:
                total_size = int(response.headers.get('content-length', 0))
                block_size = 8192
                downloaded = 0

                with open(temp_path, 'wb') as out_file:
                    while True:
                        # 취소 확인
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

                        # 진행률 업데이트
                        if total_size > 0:
                            percent = min(100, (downloaded * 100) // total_size)
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            self.progress_updated.emit(percent, f"다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)")
                        else:
                            downloaded_mb = downloaded / (1024 * 1024)
                            self.progress_updated.emit(50, f"다운로드 중... {downloaded_mb:.1f} MB")
            
            # 파일 크기 검증
            file_size = temp_path.stat().st_size
            if file_size < (1024 * 1024):  # 1MB 미만이면 오류
                temp_path.unlink()
                self.download_finished.emit(False, f"다운로드된 파일이 너무 작습니다 ({file_size/1024:.1f} KB)")
                return
            expected_size = int(ARTIST_THUMB_MODES.get(self.mode, {}).get("expected_size") or 0)
            if expected_size and file_size != expected_size:
                temp_path.unlink()
                self.download_finished.emit(
                    False,
                    f"다운로드된 파일 크기가 예상과 다릅니다 ({file_size} / {expected_size} bytes)",
                )
                return
            expected_sha256 = str(ARTIST_THUMB_MODES.get(self.mode, {}).get("sha256") or "").upper()
            if expected_sha256:
                self.progress_updated.emit(99, "다운로드 파일을 검증하는 중...")
                actual_sha256 = _sha256_file(temp_path)
                if actual_sha256 != expected_sha256:
                    temp_path.unlink()
                    self.download_finished.emit(
                        False,
                        f"다운로드된 파일 해시가 예상과 다릅니다 ({actual_sha256})",
                    )
                    return
                
            # 임시 파일을 최종 경로로 이동
            temp_path.replace(self.target_path)
            
            self.progress_updated.emit(100, "다운로드 완료!")
            self.download_finished.emit(True, f"성공적으로 다운로드됨 ({file_size/(1024*1024):.1f} MB)")
            
        except urllib.error.HTTPError as e:
            error_msg = f"HTTP 오류 {e.code}: {e.reason}"
            self.download_finished.emit(False, error_msg)
        except urllib.error.URLError as e:
            error_msg = f"네트워크 오류: {e.reason}"
            self.download_finished.emit(False, error_msg)
        except Exception as e:
            error_msg = f"예상치 못한 오류: {str(e)}"
            self.download_finished.emit(False, error_msg)


def generate_artist_randomizer_string(rule_data, artist_list=None):
    """
    아티스트 랜더마이저 규칙에 따라 문자열 생성 (기존 호환성 유지)
    """
    result_list, _ = generate_artist_randomizer_string_with_selection(rule_data, artist_list, [])
    return result_list

def generate_artist_randomizer_string_with_selection(
    rule_data,
    artist_list=None,
    favorite_artists=None,
    anima_artist_syntax=False,
):
    """
    아티스트 랜더마이저 규칙에 따라 문자열 생성 및 선택된 아티스트 반환
    
    Args:
        rule_data: 규칙 데이터 (dict)
        artist_list: 전체 아티스트 목록 (list)
        favorite_artists: 관심 작가 목록 (list)
    
    Returns:
        tuple: (생성된 문자열 리스트, 선택된 아티스트 리스트)
    """
    import random
    import os
    
    if not rule_data:
        return [], []
    
    results = []
    selected_artists = []
    
    for rule in rule_data.get('rules', []):
        # 확률 체크
        probability = rule.get('probability', 100)
        if random.randint(1, 100) > probability:
            continue
        
        # 소스에 따른 아이템 선택
        source = rule.get('source', '전체 목록에서 랜덤')
        selected_item = None
        is_artist = False  # 아티스트인지 와일드카드인지 구분
        
        if source == '와일드카드에서 랜덤':
            # 와일드카드 파일에서 랜덤 선택
            wildcard_file = rule.get('wildcard_file', '')
            if wildcard_file and os.path.exists(wildcard_file):
                try:
                    with open(wildcard_file, 'r', encoding='utf-8') as f:
                        lines = [line.strip() for line in f.readlines() if line.strip()]
                    if lines:
                        selected_item = random.choice(lines)
                except Exception as e:
                    print(f"와일드카드 파일 읽기 오류: {e}")
                    continue
            else:
                continue
        else:
            # 아티스트 목록에서 선택
            if source == '관심 작가에서 랜덤':
                # 관심 작가에서만 선택
                if not favorite_artists:
                    continue
                available_artists = favorite_artists
            else:  # '전체 목록에서 랜덤'
                # 전체 목록에서 선택
                if not artist_list:
                    continue
                available_artists = artist_list
            
            if not available_artists:
                continue
                
            selected_item = random.choice(available_artists)
            is_artist = True
            selected_artists.append(selected_item)  # 선택된 아티스트 기록
        
        if not selected_item:
            continue
        
        # 가중치 계산
        weight_mode = rule.get('weight_mode', '랜덤 가중치')
        weight = 0.0  # 초기값을 0으로 설정
        
        # 정규화 계산 (아티스트인 경우에만 적용)
        if '정규화' in weight_mode and is_artist:
            from artist_dictionary import artist_dict
            
            if artist_dict:
                # 아티스트의 가중치 가져오기
                artist_weight = artist_dict.get(selected_item, 0)
                
                # 정규화 범위 가져오기
                normalize_range = rule.get('normalize_range', {})
                min_group = normalize_range.get('min', 1)
                max_group = normalize_range.get('max', 100)
                
                # 모든 아티스트의 가중치를 가져와서 정렬
                all_weights = sorted([artist_dict.get(a, 0) for a in available_artists if a in artist_dict], reverse=True)
                
                if all_weights and artist_weight > 0:
                    # 아티스트의 순위 찾기
                    try:
                        artist_rank = all_weights.index(artist_weight) + 1
                    except ValueError:
                        # 동일한 가중치가 여러 개일 수 있으므로 처리
                        artist_rank = len([w for w in all_weights if w > artist_weight]) + 1
                    
                    # 백분위 그룹 계산 (1이 최상위 1%, 100이 최하위 1%)
                    total_artists = len(all_weights)
                    percentile = (artist_rank - 1) / total_artists * 100  # 0-100 범위
                    group_number = min(100, max(1, int(percentile) + 1))
                    
                    # 지정된 범위 내에 있는지 확인
                    if min_group <= group_number <= max_group:
                        # 그룹 번호를 가중치로 변환 (1 → 0.01, 100 → 1.00)
                        normalized_weight = group_number * 0.01
                        
                        # 계수 적용
                        coefficient = rule.get('coefficient', 1.0)
                        weight = normalized_weight * coefficient
                        
                        print(f"정규화: {selected_item} (원본 가중치: {artist_weight}, 순위: {artist_rank}/{total_artists}, 그룹: {group_number}, 정규화: {normalized_weight:.2f}, 계수: {coefficient}, 최종: {weight:.2f})")
                    else:
                        # 범위 밖이면 스킵
                        continue
                else:
                    # 가중치가 없으면 기본값 사용
                    weight = 1.0 * rule.get('coefficient', 1.0)
        
        # 랜덤 가중치 추가
        if '랜덤' in weight_mode:
            random_weight = rule.get('random_weight', {})
            lower = random_weight.get('lower', 0.1)
            upper = random_weight.get('upper', 1.0)
            step = random_weight.get('step', 0.1)
            
            # 범위 내에서 랜덤 선택
            steps = int((upper - lower) / step) + 1
            random_val = lower + (random.randint(0, steps - 1) * step)
            
            # 정규화가 있으면 더하고, 없으면 랜덤값만 사용
            if '정규화' in weight_mode:
                weight += random_val
            else:
                weight = random_val
        
        # 고정 가중치 추가
        if '고정' in weight_mode:
            fixed_weight = rule.get('fixed_weight', 0.5)
            weight += fixed_weight
        
        # 정규화가 없고 다른 가중치도 없으면 기본값 1.0
        if weight == 0.0:
            weight = 1.0
        
        weight = round(weight, 2)
        
        # 적용 모드에 따른 문자열 생성 (전체 규칙에서 가져옴)
        app_mode = rule_data.get('application_mode', '1::NAI모드 ::')
        
        # 와일드카드에서 선택했고 artist: 적용 안함 체크된 경우
        is_wildcard = source == '와일드카드에서 랜덤'
        no_artist_prefix = rule.get('no_artist_prefix', False)
        
        if app_mode == '1::NAI모드 ::':
            # NAI 모드: f"{가중치}::artist:{랜덤아이템} ::" 또는 f"{가중치}::{랜덤아이템} ::"
            if is_wildcard and no_artist_prefix:
                result_str = f"{weight}::{selected_item} ::"
            else:
                result_str = f"{weight}::artist:{selected_item} ::"
        else:  # '(로컬모드:1)'
            # 로컬 모드: f"({랜덤아이템}:{가중치})"
            # 괄호 이스케이프 처리
            escaped_item = selected_item.replace('(', '\\(').replace(')', '\\)')
            if anima_artist_syntax and is_artist:
                escaped_item = f"@{escaped_item}"
            result_str = f"({escaped_item}:{weight})"
        
        results.append(result_str)
    
    return results, selected_artists


class ArtistRandomizerSettings(QDialog):
    """아티스트 랜더마이저 설정 창"""
    
    def __init__(self, parent=None, app_context=None):
        super().__init__(parent)
        self.app_context = app_context
        self.current_rule = None
        self.rule_frames = []  # 규칙 프레임들을 저장할 리스트
        
        self.setWindowTitle("🎲 아티스트 랜더마이저 규칙 설정")
        self.setModal(False)  # Non-modal dialog
        self.resize(get_scaled_size(1250), get_scaled_size(600))
        
        # 다크 테마 적용
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        self._init_ui()
        self._load_rule_files()
    
    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10),
                                 get_scaled_size(10), get_scaled_size(10))
        
        # 메인 수평 레이아웃
        main_layout = QHBoxLayout()
        
        # 왼쪽: 규칙 파일 리스트
        left_panel = self._create_left_panel()
        main_layout.addWidget(left_panel)
        
        # 오른쪽: 규칙 편집 영역
        right_panel = self._create_right_panel()
        main_layout.addWidget(right_panel, 1)  # stretch factor 1
        
        layout.addLayout(main_layout)
        
        # 하단 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # 이 규칙을 저장 버튼
        self.save_btn = QPushButton("💾 이 규칙을 저장")
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #66BB6A;
            }}
        """)
        self.save_btn.clicked.connect(self._save_rule)
        button_layout.addWidget(self.save_btn)
        
        # 이 규칙을 적용 버튼
        self.apply_btn = QPushButton("✅ 이 규칙을 적용")
        self.apply_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #42A5F5;
            }}
        """)
        self.apply_btn.clicked.connect(self._apply_rule)
        button_layout.addWidget(self.apply_btn)
        
        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #757575;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                font-size: {get_scaled_font_size(18)}px;
            }}
            QPushButton:hover {{
                background-color: #9E9E9E;
            }}
        """)
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _create_left_panel(self) -> QWidget:
        """왼쪽 패널: 규칙 파일 리스트"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setFixedWidth(get_scaled_size(250))
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8),
                                 get_scaled_size(8), get_scaled_size(8))
        
        # 제목
        title = QLabel("📂 규칙 파일 목록")
        title.setStyleSheet(f"""
            QLabel {{
                color: white;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                margin-bottom: {get_scaled_size(8)}px;
            }}
        """)
        layout.addWidget(title)
        
        # 파일 리스트
        self.file_list = QListWidget()
        self.file_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(6)}px;
                border-bottom: 1px solid {DARK_COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.file_list.itemSelectionChanged.connect(self._on_file_selected)
        layout.addWidget(self.file_list)
        
        # 새 규칙 파일 추가 버튼
        add_btn = QPushButton("➕ 새 규칙 파일")
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #66BB6A;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #81C784;
            }}
        """)
        add_btn.clicked.connect(self._add_new_rule_file)
        layout.addWidget(add_btn)
        
        return panel
    
    def _create_right_panel(self) -> QWidget:
        """오른쪽 패널: 규칙 편집 영역"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8),
                                 get_scaled_size(8), get_scaled_size(8))
        
        # 제목 영역
        title_layout = QHBoxLayout()
        
        self.rule_title = QLabel("규칙을 선택하세요")
        self.rule_title.setStyleSheet(f"""
            QLabel {{
                color: white;
                font-size: {get_scaled_font_size(20)}px;
                font-weight: bold;
            }}
        """)
        title_layout.addWidget(self.rule_title)
        
        # 적용 모드 레이블
        mode_label = QLabel("적용 모드:")
        mode_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px; margin-left: {get_scaled_size(20)}px;")
        title_layout.addWidget(mode_label)
        
        # 적용 모드 콤보박스
        self.application_mode_combo = QComboBox()
        self.application_mode_combo.addItems(["1::NAI모드 ::", "(로컬모드:1)"])
        self.application_mode_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(150)}px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: {get_scaled_size(5)}px solid transparent;
                border-right: {get_scaled_size(5)}px solid transparent;
                border-top: {get_scaled_size(5)}px solid black;
                margin-right: {get_scaled_size(5)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                color: black;
                selection-background-color: {DARK_COLORS['accent_blue']};
                selection-color: white;
            }}
        """)
        title_layout.addWidget(self.application_mode_combo)
        
        title_layout.addStretch()
        
        # 규칙 추가 버튼
        self.add_rule_btn = QPushButton("➕ 규칙 추가")
        self.add_rule_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #66BB6A;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #81C784;
            }}
        """)
        self.add_rule_btn.clicked.connect(self._add_rule_frame)
        self.add_rule_btn.setEnabled(False)
        title_layout.addWidget(self.add_rule_btn)
        
        layout.addLayout(title_layout)
        
        # 스크롤 영역 (규칙 프레임들을 담을 영역)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        
        # 스크롤 내용 위젯
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll)
        
        return panel
    
    def _load_rule_files(self):
        """save/artist_randomizer 폴더의 JSON 파일들 로드"""
        import os
        
        # 폴더 생성
        save_path = Path("save/artist_randomizer")
        save_path.mkdir(parents=True, exist_ok=True)
        
        # JSON 파일들 검색
        json_files = list(save_path.glob("*.json"))
        
        # 파일이 없으면 기본 파일 생성
        if not json_files:
            default_file = save_path / "default.json"
            default_data = {
                "name": "기본 규칙",
                "rules": []
            }
            with open(default_file, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)
            json_files = [default_file]
        
        # 파일 리스트에 추가
        for file_path in json_files:
            self.file_list.addItem(file_path.stem)
        
        # 첫 번째 항목 선택
        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(0)
    
    def _on_file_selected(self):
        """파일 선택 시"""
        current_item = self.file_list.currentItem()
        if not current_item:
            return
        
        file_name = current_item.text()
        file_path = Path(f"save/artist_randomizer/{file_name}.json")
        
        # 파일 로드
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.current_rule = json.load(f)
            
            # UI 업데이트
            self.rule_title.setText(f"📝 {self.current_rule.get('name', file_name)}")
            self.add_rule_btn.setEnabled(True)
            
            # 적용 모드 설정
            app_mode = self.current_rule.get('application_mode', '1::NAI모드 ::')
            if app_mode in ["1::NAI모드 ::", "(로컬모드:1)"]:
                self.application_mode_combo.setCurrentText(app_mode)
            
            # 기존 규칙 프레임들 제거
            self._clear_rule_frames()
            
            # 규칙들 표시
            rules = self.current_rule.get('rules', [])
            for rule_data in rules:
                self._add_rule_frame(rule_data)
            
        except Exception as e:
            msg = self._create_styled_messagebox("오류", f"파일 로드 실패: {str(e)}", QMessageBox.Icon.Critical)
            msg.exec()
    
    def _clear_rule_frames(self):
        """모든 규칙 프레임 제거"""
        for frame in self.rule_frames:
            frame.deleteLater()
        self.rule_frames.clear()
    
    def _add_rule_frame(self, rule_data=None):
        """규칙 프레임 추가"""
        from PyQt6.QtWidgets import QSpinBox, QDoubleSpinBox
        
        # 규칙 번호 계산
        rule_number = len(self.rule_frames) + 1
        
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: #2a2a2a;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
                margin-bottom: {get_scaled_size(8)}px;
            }}
        """)
        
        layout = QVBoxLayout(frame)
        
        # 규칙 제목 라인
        title_layout = QHBoxLayout()
        rule_title = QLabel(f"규칙 {rule_number}:")
        rule_title.setStyleSheet(f"""
            QLabel {{
                color: white;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
        """)
        title_layout.addWidget(rule_title)
        title_layout.addStretch()
        
        # 삭제 버튼
        delete_btn = QPushButton("🗑️ 삭제")
        delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #d32f2f;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(18)}px;
            }}
            QPushButton:hover {{
                background-color: #e53935;
            }}
        """)
        delete_btn.clicked.connect(lambda: self._remove_rule_frame(frame))
        title_layout.addWidget(delete_btn)
        
        layout.addLayout(title_layout)
        
        # 헤더: 확률 설정
        header_layout = QHBoxLayout()
        
        # 확률 레이블
        prob_label = QLabel("작동 확률:")
        prob_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        header_layout.addWidget(prob_label)
        
        # 확률 스핀박스 (0-100%)
        prob_spinbox = QSpinBox()
        prob_spinbox.setRange(0, 100)
        prob_spinbox.setValue(rule_data.get('probability', 100) if rule_data else 100)
        prob_spinbox.setSuffix("%")
        prob_spinbox.setStyleSheet(f"""
            QSpinBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(80)}px;
            }}
        """)
        header_layout.addWidget(prob_spinbox)
        
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # 첫 번째 라인: 소스 선택
        source_layout = QHBoxLayout()
        
        source_label = QLabel("소스 선택:")
        source_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        source_layout.addWidget(source_label)
        
        source_combo = QComboBox()
        source_combo.addItems(["전체 목록에서 랜덤", "관심 작가에서 랜덤", "와일드카드에서 랜덤"])
        if rule_data and 'source' in rule_data:
            source_combo.setCurrentText(rule_data['source'])
        source_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(200)}px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: {get_scaled_size(5)}px solid transparent;
                border-right: {get_scaled_size(5)}px solid transparent;
                border-top: {get_scaled_size(5)}px solid black;
                margin-right: {get_scaled_size(5)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                color: black;
                selection-background-color: {DARK_COLORS['accent_blue']};
                selection-color: white;
            }}
        """)
        source_layout.addWidget(source_combo)
        
        # 와일드카드 선택 버튼 (와일드카드에서 랜덤 선택시만 표시)
        wildcard_btn = QPushButton("📁 와일드카드 선택")
        wildcard_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: #66BB6A;
            }}
        """)
        wildcard_btn.clicked.connect(lambda: self._select_wildcard_file(frame))
        wildcard_btn.setVisible(False)  # 초기에는 숨김
        source_layout.addWidget(wildcard_btn)
        
        # 선택된 와일드카드 파일 표시 레이블
        wildcard_label = QLabel("")
        wildcard_label.setStyleSheet(f"color: #66BB6A; font-size: {get_scaled_font_size(14)}px;")
        wildcard_label.setVisible(False)
        source_layout.addWidget(wildcard_label)
        
        # 소스 콤보박스 변경 이벤트
        source_combo.currentTextChanged.connect(lambda text: self._on_source_changed(frame, text))
        
        source_layout.addStretch()
        
        layout.addLayout(source_layout)
        
        # 두 번째 라인: 가중치 모드 선택
        weight_layout = QHBoxLayout()
        
        weight_label = QLabel("가중치 모드:")
        weight_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        weight_layout.addWidget(weight_label)
        
        weight_combo = QComboBox()
        weight_combo.addItems(["정규화 + 랜덤 가중치", "정규화 + 고정 가중치", "랜덤 가중치", "랜덤 + 고정 가중치"])
        if rule_data and 'weight_mode' in rule_data:
            weight_combo.setCurrentText(rule_data['weight_mode'])
        weight_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(200)}px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: {get_scaled_size(5)}px solid transparent;
                border-right: {get_scaled_size(5)}px solid transparent;
                border-top: {get_scaled_size(5)}px solid black;
                margin-right: {get_scaled_size(5)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                color: black;
                selection-background-color: {DARK_COLORS['accent_blue']};
                selection-color: white;
            }}
        """)
        weight_layout.addWidget(weight_combo)
        
        # "artist:" 적용안함(NAI) 체크박스 (와일드카드 선택시만 표시)
        no_artist_prefix_check = QCheckBox("\"artist:\" 적용안함(NAI)")
        no_artist_prefix_check.setStyleSheet(f"""
            QCheckBox {{
                color: white;
                font-size: {get_scaled_font_size(16)}px;
                margin-left: {get_scaled_size(20)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(20)}px;
                height: {get_scaled_size(20)}px;
                background-color: white;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        no_artist_prefix_check.setVisible(False)  # 초기에는 숨김
        if rule_data and 'no_artist_prefix' in rule_data:
            no_artist_prefix_check.setChecked(rule_data['no_artist_prefix'])
        weight_layout.addWidget(no_artist_prefix_check)
        
        weight_layout.addStretch()
        
        layout.addLayout(weight_layout)
        
        # 가중치 설정 영역 (동적으로 변경되는 부분)
        weight_settings_widget = QWidget()
        weight_settings_layout = QVBoxLayout(weight_settings_widget)
        weight_settings_layout.setContentsMargins(0, 0, 0, 0)
        
        # 정규화 설정 위젯
        normalize_widget = QWidget()
        normalize_layout = QHBoxLayout(normalize_widget)
        normalize_layout.setContentsMargins(0, 0, 0, 0)
        
        # 정규화 범위 설정
        normalize_label = QLabel("정규화 구간 (0.01-1):")
        normalize_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        normalize_layout.addWidget(normalize_label)
        
        min_range = QSpinBox()
        min_range.setRange(1, 100)
        if rule_data and 'normalize_range' in rule_data:
            min_range.setValue(rule_data['normalize_range'].get('min', 1))
        else:
            min_range.setValue(1)
        min_range.setStyleSheet(f"""
            QSpinBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(60)}px;
            }}
        """)
        normalize_layout.addWidget(min_range)
        
        dash_label = QLabel("-")
        dash_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        normalize_layout.addWidget(dash_label)
        
        max_range = QSpinBox()
        max_range.setRange(1, 100)
        if rule_data and 'normalize_range' in rule_data:
            max_range.setValue(rule_data['normalize_range'].get('max', 100))
        else:
            max_range.setValue(100)
        max_range.setStyleSheet(f"""
            QSpinBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(60)}px;
            }}
        """)
        normalize_layout.addWidget(max_range)
        
        # 계수 설정
        coef_label = QLabel("* 계수:")
        coef_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px; margin-left: {get_scaled_size(20)}px;")
        normalize_layout.addWidget(coef_label)
        
        coef_spinbox = QDoubleSpinBox()
        coef_spinbox.setRange(0.1, 3.0)
        coef_spinbox.setValue(rule_data.get('coefficient', 1.0) if rule_data else 1.0)
        coef_spinbox.setSingleStep(0.1)
        coef_spinbox.setDecimals(2)
        coef_spinbox.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(80)}px;
            }}
        """)
        normalize_layout.addWidget(coef_spinbox)
        normalize_layout.addStretch()
        
        weight_settings_layout.addWidget(normalize_widget)
        
        # 랜덤 가중치 설정 위젯
        random_widget = QWidget()
        random_layout = QHBoxLayout(random_widget)
        random_layout.setContentsMargins(0, 0, 0, 0)
        
        random_label = QLabel("랜덤 가중치:")
        random_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        random_layout.addWidget(random_label)
        
        # 하한치
        lower_label = QLabel("하한:")
        lower_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(14)}px; margin-left: {get_scaled_size(10)}px;")
        random_layout.addWidget(lower_label)
        
        lower_spinbox = QDoubleSpinBox()
        lower_spinbox.setRange(0.1, 3.0)
        lower_spinbox.setSingleStep(0.1)
        lower_spinbox.setDecimals(2)
        if rule_data and 'random_weight' in rule_data:
            lower_spinbox.setValue(rule_data['random_weight'].get('lower', 0.1))
        else:
            lower_spinbox.setValue(0.1)
        lower_spinbox.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(80)}px;
            }}
        """)
        random_layout.addWidget(lower_spinbox)
        
        # 상한치
        upper_label = QLabel("상한:")
        upper_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(14)}px; margin-left: {get_scaled_size(10)}px;")
        random_layout.addWidget(upper_label)
        
        upper_spinbox = QDoubleSpinBox()
        upper_spinbox.setRange(0.1, 3.0)
        upper_spinbox.setSingleStep(0.1)
        upper_spinbox.setDecimals(2)
        if rule_data and 'random_weight' in rule_data:
            upper_spinbox.setValue(rule_data['random_weight'].get('upper', 1.0))
        else:
            upper_spinbox.setValue(1.0)
        upper_spinbox.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(80)}px;
            }}
        """)
        random_layout.addWidget(upper_spinbox)
        
        # 증감치
        step_label = QLabel("증감:")
        step_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(14)}px; margin-left: {get_scaled_size(10)}px;")
        random_layout.addWidget(step_label)
        
        step_spinbox = QDoubleSpinBox()
        step_spinbox.setRange(0.01, 1.0)
        step_spinbox.setSingleStep(0.01)
        step_spinbox.setDecimals(2)
        if rule_data and 'random_weight' in rule_data:
            step_spinbox.setValue(rule_data['random_weight'].get('step', 0.1))
        else:
            step_spinbox.setValue(0.1)
        step_spinbox.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(80)}px;
            }}
        """)
        random_layout.addWidget(step_spinbox)
        random_layout.addStretch()
        
        weight_settings_layout.addWidget(random_widget)
        
        # 고정 가중치 설정 위젯
        fixed_widget = QWidget()
        fixed_layout = QHBoxLayout(fixed_widget)
        fixed_layout.setContentsMargins(0, 0, 0, 0)
        
        fixed_label = QLabel("고정 가중치:")
        fixed_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        fixed_layout.addWidget(fixed_label)
        
        fixed_spinbox = QDoubleSpinBox()
        fixed_spinbox.setRange(0.1, 3.0)
        fixed_spinbox.setSingleStep(0.1)
        fixed_spinbox.setDecimals(2)
        fixed_spinbox.setValue(rule_data.get('fixed_weight', 0.5) if rule_data else 0.5)
        fixed_spinbox.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: white;
                color: black;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(100)}px;
            }}
        """)
        fixed_layout.addWidget(fixed_spinbox)
        fixed_layout.addStretch()
        
        weight_settings_layout.addWidget(fixed_widget)
        
        # 초기 상태 설정
        fixed_widget.hide()  # 초기에는 고정 가중치 숨김
        
        layout.addWidget(weight_settings_widget)
        
        # 가중치 모드 변경 시 UI 업데이트
        def update_weight_ui():
            mode = weight_combo.currentText()
            source = source_combo.currentText()
            
            # 정규화 옵션은 전체 목록 또는 관심 작가에서만 사용 가능
            can_normalize = source in ["전체 목록에서 랜덤", "관심 작가에서 랜덤"]
            
            if mode == "정규화 + 랜덤 가중치":
                normalize_widget.setVisible(can_normalize)
                random_widget.show()
                fixed_widget.hide()
            elif mode == "정규화 + 고정 가중치":
                normalize_widget.setVisible(can_normalize)
                random_widget.hide()
                fixed_widget.show()
            elif mode == "랜덤 가중치":
                normalize_widget.hide()
                random_widget.show()
                fixed_widget.hide()
            elif mode == "랜덤 + 고정 가중치":
                normalize_widget.hide()
                random_widget.show()
                fixed_widget.show()
            
            # 정규화 불가능한 소스인 경우 가중치 모드 제한
            if not can_normalize and mode in ["정규화 + 랜덤 가중치", "정규화 + 고정 가중치"]:
                weight_combo.setCurrentText("랜덤 가중치")
        
        weight_combo.currentTextChanged.connect(update_weight_ui)
        source_combo.currentTextChanged.connect(update_weight_ui)
        
        # 초기 UI 상태 설정
        update_weight_ui()
        
        # 프레임에 데이터 저장 (나중에 저장할 때 사용)
        frame.rule_title = rule_title  # 규칙 제목 레이블 저장
        frame.prob_spinbox = prob_spinbox
        frame.source_combo = source_combo
        frame.weight_combo = weight_combo
        frame.min_range = min_range
        frame.max_range = max_range
        frame.coef_spinbox = coef_spinbox
        frame.lower_spinbox = lower_spinbox
        frame.upper_spinbox = upper_spinbox
        frame.step_spinbox = step_spinbox
        frame.fixed_spinbox = fixed_spinbox
        frame.wildcard_btn = wildcard_btn
        frame.wildcard_label = wildcard_label
        frame.wildcard_file = rule_data.get('wildcard_file', '') if rule_data else ''
        frame.no_artist_prefix_check = no_artist_prefix_check
        
        # 와일드카드 파일이 있으면 표시
        if frame.wildcard_file:
            import os
            filename = os.path.basename(frame.wildcard_file)
            if filename:
                wildcard_label.setText(f"📄 {filename}")
                wildcard_label.setVisible(True)
        
        # 초기 소스 설정에 따른 UI 업데이트
        if rule_data:
            self._on_source_changed(frame, source_combo.currentText())
        
        # 프레임을 스크롤 레이아웃에 추가
        self.scroll_layout.addWidget(frame)
        self.rule_frames.append(frame)
    
    def _remove_rule_frame(self, frame):
        """규칙 프레임 제거"""
        if frame in self.rule_frames:
            self.rule_frames.remove(frame)
            frame.deleteLater()
            
            # 남은 프레임들의 번호 업데이트
            for i, remaining_frame in enumerate(self.rule_frames):
                if hasattr(remaining_frame, 'rule_title'):
                    remaining_frame.rule_title.setText(f"규칙 {i + 1}:")
    
    def _on_source_changed(self, frame, text):
        """소스 선택이 변경되었을 때"""
        # 와일드카드 관련 UI 표시/숨김
        is_wildcard = text == "와일드카드에서 랜덤"
        
        if hasattr(frame, 'wildcard_btn'):
            frame.wildcard_btn.setVisible(is_wildcard)
        
        if hasattr(frame, 'wildcard_label'):
            # wildcard_file이 비어있지 않은지 확인
            has_file = bool(getattr(frame, 'wildcard_file', ''))
            frame.wildcard_label.setVisible(is_wildcard and has_file)
        
        if hasattr(frame, 'no_artist_prefix_check'):
            frame.no_artist_prefix_check.setVisible(is_wildcard)
    
    def _select_wildcard_file(self, frame):
        """와일드카드 파일 선택"""
        from PyQt6.QtWidgets import QFileDialog
        import os
        
        # 와일드카드 폴더 경로 설정
        wildcard_dir = "wildcards"
        if not os.path.exists(wildcard_dir):
            wildcard_dir = "."
        
        # 파일 다이얼로그 열기
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "와일드카드 파일 선택",
            wildcard_dir,
            "Text Files (*.txt);;All Files (*.*)"
        )
        
        if file_path:
            # 파일 경로 저장
            frame.wildcard_file = file_path
            
            # 파일명 표시
            filename = os.path.basename(file_path)
            if hasattr(frame, 'wildcard_label'):
                frame.wildcard_label.setText(f"📄 {filename}")
                frame.wildcard_label.setVisible(True)
    
    def _add_new_rule_file(self):
        """새 규칙 파일 추가"""
        file_name, ok = QInputDialog.getText(
            self,
            "새 규칙 파일",
            "파일 이름을 입력하세요:",
            QLineEdit.EchoMode.Normal,
            "new_rule"
        )
        
        if ok and file_name:
            file_path = Path(f"save/artist_randomizer/{file_name}.json")
            if file_path.exists():
                msg = self._create_styled_messagebox("경고", "이미 존재하는 파일입니다.", QMessageBox.Icon.Warning)
                msg.exec()
                return
            
            # 새 파일 생성
            new_data = {
                "name": file_name,
                "rules": []
            }
            
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(new_data, f, ensure_ascii=False, indent=2)
                
                # 리스트에 추가
                self.file_list.addItem(file_name)
                
                # 새 항목 선택
                for i in range(self.file_list.count()):
                    if self.file_list.item(i).text() == file_name:
                        self.file_list.setCurrentRow(i)
                        break
                
            except Exception as e:
                msg = self._create_styled_messagebox("오류", f"파일 생성 실패: {str(e)}", QMessageBox.Icon.Critical)
                msg.exec()
    
    def _save_rule(self):
        """현재 규칙을 저장"""
        if not self.current_rule:
            msg = self._create_styled_messagebox("경고", "저장할 규칙이 선택되지 않았습니다.", QMessageBox.Icon.Warning)
            msg.exec()
            return
        
        # 현재 규칙 저장
        self._save_current_rule()
        
        rule_name = self.current_rule.get('name', 'Unknown')
        msg = self._create_styled_messagebox("성공", f"'{rule_name}' 규칙이 저장되었습니다.", QMessageBox.Icon.Information)
        msg.exec()
        print(f"💾 Artist Randomizer Rule Saved: {rule_name}")
    
    def _create_styled_messagebox(self, title, text, icon):
        """TODO(web-dialog): 원래 dark-themed QMessageBox — Web Shell 토스트로 재구현 필요.
        호출처가 .exec()/.exec()==Yes/.setStandardButtons 등 QMessageBox 메서드를 호출하므로
        stub 객체를 반환해 .exec() 시 print 만 수행하고 No 반환 (안전 기본값)."""
        return _PrintMessageBoxStub(title, text)
    
    def _apply_rule(self):
        """현재 규칙을 적용 (저장 포함)"""
        if not self.current_rule:
            msg = self._create_styled_messagebox("경고", "적용할 규칙이 선택되지 않았습니다.", QMessageBox.Icon.Warning)
            msg.exec()
            return
        
        # 현재 규칙 저장 (자동 저장)
        self._save_current_rule()
        
        # 현재 규칙을 app_context에 저장
        if self.app_context:
            self.app_context.artist_randomizer_rule = self.current_rule
            rule_name = self.current_rule.get('name', 'Unknown')
            
            # 저장과 적용이 모두 완료되었음을 알림
            msg = self._create_styled_messagebox(
                "성공", 
                f"'{rule_name}' 규칙이 저장되고 적용되었습니다.", 
                QMessageBox.Icon.Information
            )
            msg.exec()
            print(f"💾🎲 Artist Randomizer Rule Saved & Applied: {rule_name}")
    
    def _save_current_rule(self):
        """현재 편집 중인 규칙 저장"""
        if not self.current_rule:
            return
        
        current_item = self.file_list.currentItem()
        if not current_item:
            return
        
        file_name = current_item.text()
        file_path = Path(f"save/artist_randomizer/{file_name}.json")
        
        # 규칙 프레임들로부터 데이터 수집
        rules = []
        for frame in self.rule_frames:
            rule_data = self._extract_rule_data(frame)
            rules.append(rule_data)
        
        self.current_rule['rules'] = rules
        self.current_rule['application_mode'] = self.application_mode_combo.currentText()
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.current_rule, f, ensure_ascii=False, indent=2)
        except Exception as e:
            msg = self._create_styled_messagebox("오류", f"파일 저장 실패: {str(e)}", QMessageBox.Icon.Critical)
            msg.exec()
    
    def _extract_rule_data(self, frame):
        """프레임에서 규칙 데이터 추출"""
        rule_data = {
            'probability': frame.prob_spinbox.value(),
            'source': frame.source_combo.currentText(),
            'weight_mode': frame.weight_combo.currentText(),
            'normalize_range': {
                'min': frame.min_range.value(),
                'max': frame.max_range.value()
            },
            'coefficient': frame.coef_spinbox.value(),
            'random_weight': {
                'lower': frame.lower_spinbox.value(),
                'upper': frame.upper_spinbox.value(),
                'step': frame.step_spinbox.value()
            },
            'fixed_weight': frame.fixed_spinbox.value()
        }
        
        # 와일드카드 설정 추가
        if hasattr(frame, 'wildcard_file'):
            rule_data['wildcard_file'] = frame.wildcard_file
        
        if hasattr(frame, 'no_artist_prefix_check'):
            rule_data['no_artist_prefix'] = frame.no_artist_prefix_check.isChecked()
        
        return rule_data


class ArtistThumbModule(BaseTabModule):
    """아티스트 스타일 썸네일 뷰어 탭 모듈"""
    
    # 시그널 정의
    artist_selected = pyqtSignal(str)  # 아티스트 이름 전달
    copy_requested = pyqtSignal(str)   # 클립보드 복사 요청
    
    def __init__(self):
        super().__init__()
        self.widget = None
        self.artist_data = {}
        self.nai_data = {}
        self.noob_data = {}
        self.thumbnail_mode_data = {}
        self.artist_list = []
        self.current_artist = None
        self.search_popup = None      # ✅ QListWidget 팝업
        self.max_suggestions = 20     # ✅ 원하는 추천 개수
        self.current_mode = None      # 현재 선택된 썸네일 모드
        self.tab_initialized = False  # 탭 초기화 여부
        self.mode_placeholder_text = "모드를 선택하세요..."
        self._previous_mode = self.mode_placeholder_text
        self._download_canceled = False  # 다운로드 취소 플래그
        self._generate_options_mode = "NAI"
        self._last_auto_artist_tag_by_mode = {}
        
        # 관심/제외 작가 리스트
        self.favorite_artists = []
        self.banned_artists = []
        self.filter_mode = "전체 목록 보기"  # 필터링 모드
        
    def get_tab_title(self) -> str:
        return "🎨 Artists"
    
    def get_tab_order(self) -> int:
        return 50  # 중간 위치
    
    def get_tab_type(self) -> str:
        return 'core'  # 시작 시 자동 로드
    
    def get_artist_data(self) -> dict:
        """다른 모듈에서 아티스트 데이터에 접근할 수 있도록 제공"""
        return self.artist_data.copy()
    
    def get_artist_list(self) -> list:
        """다른 모듈에서 아티스트 리스트에 접근할 수 있도록 제공"""
        return self.artist_list.copy()
    
    def on_tab_activated(self):
        """탭이 활성화될 때 호출 (사용자가 탭을 클릭했을 때)"""
        if not self.tab_initialized and hasattr(self, 'mode_combo'):
            self._check_and_initialize_data()
            self.tab_initialized = True
    
    def _check_and_initialize_data(self):
        """데이터 파일 체크 및 콤보박스 초기 상태 구성 (로드는 사용자 모드 선택 시)"""
        # 콤보박스 구성 — 항상 플레이스홀더로 시작
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        self.mode_combo.addItems([
            self.mode_placeholder_text,
            *ARTIST_THUMB_MODES.keys(),
        ])
        self.mode_combo.setCurrentText(self.mode_placeholder_text)
        self.mode_combo.blockSignals(False)

        self.current_mode = None
        self._previous_mode = self.mode_placeholder_text

        # artist_dict fallback: 썸네일 미로드 상태에서도 아티스트 목록 표시
        if artist_dict:
            self.artist_list = sorted(
                artist_dict.keys(),
                key=lambda k: artist_dict.get(k, 0),
                reverse=True
            )
            self._update_listbox(
                [a for a in self.artist_list if a not in self.banned_artists]
            )
        else:
            self._update_listbox([])

        self._show_default_thumbnail()
    
    def create_widget(self, parent: QWidget) -> QWidget:
        """메인 위젯 생성"""
        self.widget = QWidget(parent)
        
        # autocomplete_manager 무시 설정
        self.widget.setProperty("autocomplete_ignore", True)
        
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10), 
                                 get_scaled_size(10), get_scaled_size(10))
        
        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 상단 툴바
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        # 메인 수평 레이아웃 (좌측: 리스트, 우측: 미리보기)
        main_horizontal_layout = QHBoxLayout()
        main_horizontal_layout.setSpacing(get_scaled_size(2))
        
        # 좌측 패널 (검색 + 리스트) - 250픽셀 고정
        left_panel = self._create_left_panel(dynamic_styles)
        left_panel.setFixedWidth(250)
        main_horizontal_layout.addWidget(left_panel)
        
        # 우측 패널 (이미지 미리보기)
        right_panel = self._create_right_panel()
        main_horizontal_layout.addWidget(right_panel)
        
        layout.addLayout(main_horizontal_layout)
        
        # 하단 정보 패널
        info_panel = self._create_info_panel()
        layout.addWidget(info_panel)
        
        # 검색 팝업만 초기화 (데이터 로드는 탭 활성화 시)
        self._init_search_popup()
        
        # 관심/제외 작가 목록 로드
        self._load_artist_lists()
        self._subscribe_api_mode_changed()
        
        # artist_dict만으로 기본 리스트 초기화
        if artist_dict:
            self.artist_list = sorted(
                artist_dict.keys(),
                key=lambda k: artist_dict.get(k, 0),
                reverse=True
            )
            # 제외된 작가를 필터링한 리스트 표시
            filtered_list = [artist for artist in self.artist_list if artist not in self.banned_artists]
            self._update_listbox(filtered_list)
        
        return self.widget
    
    def _create_toolbar(self) -> QWidget:
        """상단 툴바 생성"""
        toolbar = QFrame()
        toolbar.setFrameStyle(QFrame.Shape.NoFrame)
        toolbar.setFixedHeight(get_scaled_size(40))
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 썸네일 모드 선택 레이블
        mode_label = QLabel("썸네일 모드 선택:")
        mode_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(mode_label)
        
        # 썸네일 모드 콤보박스
        self.mode_combo = QComboBox()
        self.mode_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(200)}px;
            }}
            QComboBox:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: {get_scaled_size(5)}px solid transparent;
                border-right: {get_scaled_size(5)}px solid transparent;
                border-top: {get_scaled_size(5)}px solid {DARK_COLORS['text_primary']};
                margin-right: {get_scaled_size(5)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['bg_hover']};
                padding: {get_scaled_size(4)}px;
            }}
            QComboBox QAbstractItemView::item {{
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(4)}px;
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        # 초기에는 기본 항목만 추가 (파일 체크는 탭 활성화 시)
        self.mode_combo.addItems([self.mode_placeholder_text, *ARTIST_THUMB_MODES.keys()])
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        layout.addStretch()

        return toolbar
    
    def _create_left_panel(self, dynamic_styles: dict) -> QWidget:
        """좌측 패널 (검색 + 리스트) 생성"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8),
                                 get_scaled_size(8), get_scaled_size(8))
        
        # 검색 필드
        search_label = QLabel("🔍 아티스트 검색:")
        search_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setObjectName("artist_search_input")  # autocomplete 무시용
        self.search_input.setProperty("autocomplete_ignore", True)
        self.search_input.setPlaceholderText("아티스트 이름 입력...")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QLineEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.search_input.textChanged.connect(self._perform_search)
        layout.addWidget(self.search_input)
        
        # 아티스트 리스트
        list_label = QLabel("📋 아티스트 목록:")
        list_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: {DARK_COLORS['text_primary']}; margin-top: {get_scaled_size(10)}px;")
        layout.addWidget(list_label)
        
        self.artist_listbox = QListWidget()
        self.artist_listbox.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                padding: {get_scaled_size(4)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(4)}px;
                border-bottom: 1px solid {DARK_COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.artist_listbox.itemSelectionChanged.connect(self._on_artist_selected)
        layout.addWidget(self.artist_listbox)
        
        # 필터 콤보박스 추가 (라벨 없이)
        self.filter_combo = QComboBox()
        
        # 기본 필터 항목들
        filter_items = ["전체 목록 보기", "관심 작가 보기", "제외 작가 보기"]
        
        # artist_thumb 폴더에서 사용자 정의 필터 파일들 로드
        if os.path.exists('artist_thumb'):
            custom_files = [f for f in os.listdir('artist_thumb') 
                          if f.endswith('.txt') and f != 'banned_artist.txt']
            for file in custom_files:
                display_name = file.replace('.txt', '')
                filter_items.append(display_name)
        
        # TODO: 분류 그룹 추가 기능 - 현재 숨김 처리
        # filter_items.append("+ 분류 그룹 추가")
        
        self.filter_combo.addItems(filter_items)
        self.filter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(14)}px;
                margin-top: {get_scaled_size(8)}px;
            }}
            QComboBox:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: {get_scaled_size(5)}px solid transparent;
                border-right: {get_scaled_size(5)}px solid transparent;
                border-top: {get_scaled_size(5)}px solid {DARK_COLORS['text_primary']};
                margin-right: {get_scaled_size(5)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['bg_hover']};
                selection-color: white;
                padding: {get_scaled_size(4)}px;
            }}
            QComboBox QAbstractItemView::item {{
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(4)}px;
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {DARK_COLORS['bg_hover']};
                color: white;
            }}
        """)
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self.filter_combo)
        
        return panel
    
    def _create_right_panel(self) -> QWidget:
        """우측 패널 (2차 분할 구조) 생성"""
        # 메인 컨테이너
        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 서브 수평 레이아웃 (썸네일/프롬프트 : 생성 이미지)
        self.sub_horizontal_layout = QHBoxLayout()
        self.sub_horizontal_layout.setSpacing(get_scaled_size(2))

        # 왼쪽: 썸네일 + 프롬프트 (인스턴스 변수로 저장)
        self.prompt_panel = self._create_prompt_panel()

        # 오른쪽: 생성 이미지 (832x1216 고정)
        generation_panel = self._create_generation_panel()

        self.sub_horizontal_layout.addWidget(self.prompt_panel)
        self.sub_horizontal_layout.addWidget(generation_panel)
        self.sub_horizontal_layout.setStretchFactor(self.prompt_panel, 0)  # 썸네일 패널은 고정 크기
        self.sub_horizontal_layout.setStretchFactor(generation_panel, 1)  # 생성 패널이 나머지 공간 차지

        main_layout.addLayout(self.sub_horizontal_layout)
        return main_panel
    
    def _create_prompt_panel(self) -> QWidget:
        """왼쪽 서브패널: 썸네일 + 프롬프트 입력"""
        # 썸네일 이미지 (3:3.8 비율)
        # 3:3.8 비율 = 너비:높이 = 1:1.267
        thumbnail_width = get_scaled_size(350)
        thumbnail_height = int(thumbnail_width * 3.8 / 3.0)

        # 패널 너비를 썸네일 너비 + 패딩으로 설정
        panel_padding = get_scaled_size(8)
        panel_width = thumbnail_width + (panel_padding * 2)

        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        # 패널 크기 고정
        panel.setFixedWidth(panel_width)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(panel_padding, panel_padding,
                                 panel_padding, panel_padding)
        layout.setSpacing(get_scaled_size(6))

        dynamic_styles = get_dynamic_styles()

        # 썸네일 컨테이너 (썸네일 + 미리보기 버튼)
        thumbnail_container = QWidget()
        thumbnail_container_layout = QVBoxLayout(thumbnail_container)
        thumbnail_container_layout.setContentsMargins(0, 0, 0, 0)
        thumbnail_container_layout.setSpacing(get_scaled_size(4))

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
            }}
        """)
        # 호환 헬퍼 기반 크기로 설정
        self.thumbnail_label.setFixedSize(thumbnail_width, thumbnail_height)
        self.thumbnail_label.setScaledContents(False)
        self._show_default_thumbnail()
        thumbnail_container_layout.addWidget(self.thumbnail_label)

        # 크게 보기 토글 버튼
        self.large_preview_btn = QPushButton("🔍 크게 보기")
        self.large_preview_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.large_preview_btn.setCheckable(True)
        self.large_preview_btn.clicked.connect(self._toggle_large_preview)
        thumbnail_container_layout.addWidget(self.large_preview_btn)

        layout.addWidget(thumbnail_container)

        self.positive_prompt = QTextEdit()
        self.positive_prompt.setAcceptRichText(False)
        self.positive_prompt.setPlaceholderText("아티스트 스타일과 함께 사용할 프롬프트...")
        self.positive_prompt.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        self.positive_prompt.setFixedHeight(get_scaled_size(100))
        layout.addWidget(self.positive_prompt)

        # Generate 버튼
        self.generate_btn = QPushButton("🎨 Generate (832x1216)")
        self.generate_btn.setStyleSheet(dynamic_styles.get('primary_button', ''))
        self.generate_btn.setFixedHeight(get_scaled_size(36))
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        layout.addWidget(self.generate_btn)

        # 작가태그 앞에 들어갈 텍스트
        prefix_label = QLabel("작가태그 앞에 들어갈 텍스트:")
        prefix_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(15)}px;")
        layout.addWidget(prefix_label)

        self.prefix_textedit = QTextEdit()
        self.prefix_textedit.setAcceptRichText(False)
        self.prefix_textedit.setPlaceholderText("1girl, usada pekora, ...")
        self.prefix_textedit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        self.prefix_textedit.setFixedHeight(get_scaled_size(80))
        layout.addWidget(self.prefix_textedit)

        # 작가태그 뒤에 들어갈 텍스트
        postfix_label = QLabel("작가태그 뒤에 들어갈 텍스트:")
        postfix_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(15)}px;")
        layout.addWidget(postfix_label)

        self.postfix_textedit = QTextEdit()
        self.postfix_textedit.setAcceptRichText(False)
        self.postfix_textedit.setPlaceholderText("no text, best quality, masterpiece, year 2024, ...")
        self.postfix_textedit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        self.postfix_textedit.setFixedHeight(get_scaled_size(80))
        layout.addWidget(self.postfix_textedit)

        # 관심 작가 및 제외 버튼 추가
        button_layout = QHBoxLayout()
        button_layout.setSpacing(get_scaled_size(5))

        # 공통 버튼 스타일 (높이 통일)
        button_height = get_scaled_size(32)
        button_font_size = get_scaled_font_size(13)

        self.favorite_button = QPushButton("⭐ 관심 작가 등록")
        self.favorite_button.setFixedHeight(button_height)
        self.favorite_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                font-size: {button_font_size}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        self.favorite_button.clicked.connect(self._toggle_favorite)
        self.favorite_button.setEnabled(False)
        button_layout.addWidget(self.favorite_button)

        self.ban_button = QPushButton("🚫 작가명 제거")
        self.ban_button.setFixedHeight(button_height)
        self.ban_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #8B0000;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                font-size: {button_font_size}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #A52A2A;
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        self.ban_button.clicked.connect(self._ban_artist)
        self.ban_button.setEnabled(False)
        button_layout.addWidget(self.ban_button)

        layout.addLayout(button_layout)

        # 갤러리 버튼과 위 버튼들 사이 마진
        layout.addSpacing(get_scaled_size(10))

        # 갤러리 버튼 (별도 줄, 강조 스타일)
        gallery_btn_font_size = button_font_size + 3
        self.gallery_button = QPushButton("🖼️ 갤러리 보기")
        self.gallery_button.setFixedHeight(get_scaled_size(38))
        self.gallery_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid white;
                border-radius: {get_scaled_size(6)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {gallery_btn_font_size}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.gallery_button.clicked.connect(self._open_gallery_window)
        layout.addWidget(self.gallery_button)

        layout.addStretch()

        return panel
    
    def _create_generation_panel(self) -> QWidget:
        """오른쪽 서브패널: 생성 이미지 표시"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8),
                                 get_scaled_size(8), get_scaled_size(8))
        
        # StableImageWidget 사용 - 레이아웃을 꽉 채우도록 설정
        self.generation_image = StableImageWidget()
        self.generation_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.generation_image.setMinimumSize(416, 608)  # 832x1216의 절반 크기
        layout.addWidget(self.generation_image, 1)  # stretch factor 1로 설정하여 여유 공간 모두 차지
        
        return panel
    
    def _show_default_thumbnail(self):
        """기본 썸네일 이미지 표시"""
        # 빈 이미지 생성 (512x512)
        pixmap = QPixmap(512, 512)
        pixmap.fill(Qt.GlobalColor.darkGray)

        # 텍스트 추가
        painter = QPainter(pixmap)
        painter.setPen(Qt.GlobalColor.white)
        font = painter.font()
        font.setPointSize(24)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter,
                        "아티스트\n썸네일")
        painter.end()

        # 호환 헬퍼 기반 썸네일 크기로 스케일링
        if hasattr(self, 'thumbnail_label'):
            padding = get_scaled_size(4) * 2  # 양쪽 패딩
            thumbnail_width = get_scaled_size(350)
            target_width = thumbnail_width - padding
            target_height = int(thumbnail_width * 3.8 / 3.0) - padding

            scaled_pixmap = pixmap.scaled(
                target_width,
                target_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(scaled_pixmap)

    def _toggle_large_preview(self):
        """크게 보기 토글 - thumbnail_label 숨기고 generation_image에 썸네일 표시"""
        if not hasattr(self, '_large_preview_mode'):
            self._large_preview_mode = False

        self._large_preview_mode = not self._large_preview_mode

        if self._large_preview_mode:
            # 크게 보기 모드 활성화
            self.large_preview_btn.setText("🔍 작게 보기")
            self.thumbnail_label.hide()

            # 현재 썸네일을 generation_image에 표시
            self._show_thumbnail_in_generation_panel()

            # TextEdit 크기 2배로 확장
            self._expand_textedit_sizes()
        else:
            # 크게 보기 모드 비활성화
            self.large_preview_btn.setText("🔍 크게 보기")
            self.thumbnail_label.show()

            # generation_image 초기화 (기존 생성 이미지가 있으면 복원)
            if hasattr(self, '_last_generated_image') and self._last_generated_image:
                self.generation_image.setPilImage(self._last_generated_image)
            else:
                self.generation_image.setPixmap(None)

            # TextEdit 크기 원래대로 복원
            self._restore_textedit_sizes()

    def _show_thumbnail_in_generation_panel(self):
        """현재 썸네일을 generation_image에 크게 표시"""
        if not self._large_preview_mode:
            return

        if self.current_artist and self.artist_data:
            img_data_list = self.artist_data.get(self.current_artist, [])
            if img_data_list and img_data_list[0]:
                try:
                    # base64 디코딩
                    img_bytes = base64.b64decode(img_data_list[0])

                    # PIL 이미지로 변환
                    pil_image = Image.open(io.BytesIO(img_bytes))

                    # 좌우 85픽셀씩 잘라내기 (검은색 썸네일 영역 제거)
                    if pil_image.width > 170:
                        pil_image = pil_image.crop((
                            85,
                            0,
                            pil_image.width - 85,
                            pil_image.height
                        ))

                    # StableImageWidget에 표시
                    self.generation_image.setPilImage(pil_image)
                except Exception as e:
                    print(f"크게 보기 이미지 로드 오류: {e}")
                    self.generation_image.setPixmap(None)

    def _expand_textedit_sizes(self):
        """크게 보기 모드에서 TextEdit 크기 2배로 확장"""
        # 원래 크기 저장 (최초 1회만)
        if not hasattr(self, '_original_textedit_heights'):
            self._original_textedit_heights = {
                'positive_prompt': self.positive_prompt.height(),
                'prefix_textedit': self.prefix_textedit.height(),
                'postfix_textedit': self.postfix_textedit.height()
            }

        # 크기 확장 (positive: 1배, prefix: 2.5배, postfix: 4배)
        self.positive_prompt.setFixedHeight(int(self._original_textedit_heights['positive_prompt'] * 1))
        self.prefix_textedit.setFixedHeight(int(self._original_textedit_heights['prefix_textedit'] * 2.5))
        self.postfix_textedit.setFixedHeight(int(self._original_textedit_heights['postfix_textedit'] * 4))

    def _restore_textedit_sizes(self):
        """TextEdit 크기 원래대로 복원"""
        if hasattr(self, '_original_textedit_heights'):
            self.positive_prompt.setFixedHeight(self._original_textedit_heights['positive_prompt'])
            self.prefix_textedit.setFixedHeight(self._original_textedit_heights['prefix_textedit'])
            self.postfix_textedit.setFixedHeight(self._original_textedit_heights['postfix_textedit'])
    
    def _create_info_panel(self) -> QWidget:
        """하단 정보 패널 생성"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(10)}px;
            }}
        """)
        panel.setFixedHeight(get_scaled_size(50))

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(12))

        # 현재 선택된 아티스트 정보만 표시
        self.info_label = QLabel("아티스트를 선택하세요")
        self.info_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        self.info_label.setMinimumWidth(get_scaled_size(200))
        layout.addWidget(self.info_label)

        layout.addStretch()

        # 체크박스 공통 폰트 사이즈
        checkbox_font_size = get_scaled_font_size(13)
        checkbox_indicator_size = get_scaled_size(16)

        # 연속생성 체크박스
        self.continuous_generation_checkbox = QCheckBox("연속생성")
        self.continuous_generation_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {checkbox_font_size}px;
                padding: {get_scaled_size(2)}px;
            }}
            QCheckBox::indicator {{
                width: {checkbox_indicator_size}px;
                height: {checkbox_indicator_size}px;
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QCheckBox::indicator:checked {{
                background-color: #ff6b6b;
                border-color: #ff6b6b;
            }}
            QCheckBox::indicator:hover {{
                border-color: #ff6b6b;
            }}
        """)
        self.continuous_generation_checkbox.setToolTip("연속생성: 이미지 생성이 완료되면 1초 후 자동으로 다시 생성")
        layout.addWidget(self.continuous_generation_checkbox)

        self.randomizer_checkbox = QCheckBox("랜더마이저")
        self.randomizer_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {checkbox_font_size}px;
                padding: {get_scaled_size(2)}px;
            }}
            QCheckBox::indicator {{
                width: {checkbox_indicator_size}px;
                height: {checkbox_indicator_size}px;
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QCheckBox::indicator:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.randomizer_checkbox.setToolTip("아티스트 랜더마이저 활성화")
        self.randomizer_checkbox.stateChanged.connect(self._on_randomizer_toggled)
        layout.addWidget(self.randomizer_checkbox)

        # 규칙 설정 버튼
        self.randomizer_settings_btn = QPushButton("⚙️ 규칙")
        self.randomizer_settings_btn.setFixedHeight(get_scaled_size(28))
        self.randomizer_settings_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(10)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)
        self.randomizer_settings_btn.setToolTip("아티스트 랜더마이저 규칙 설정")
        self.randomizer_settings_btn.clicked.connect(self._open_randomizer_settings)
        layout.addWidget(self.randomizer_settings_btn)

        return panel
    
    def _thumbnail_mode_file_state(self, mode: str) -> dict:
        mode_info = ARTIST_THUMB_MODES.get(mode) or {}
        if not mode_info:
            return {
                "path": Path(),
                "exists": False,
                "available": False,
                "needs_update": False,
                "size": 0,
                "expected_size": 0,
            }
        file_path = Path(mode_info.get("path") or "")
        exists = file_path.exists()
        size = file_path.stat().st_size if exists else 0
        expected_size = int(mode_info.get("expected_size") or 0)
        needs_update = bool(expected_size and (not exists or size != expected_size))
        return {
            "path": file_path,
            "exists": exists,
            "available": bool(exists and not needs_update),
            "needs_update": needs_update,
            "size": size,
            "expected_size": expected_size,
        }
    
    def _update_artist_list_from_data(self):
        """현재 artist_data로부터 아티스트 리스트 업데이트"""
        if self.artist_data:
            # artist_dict와 매칭되는 아티스트만 필터링
            self.artist_list = sorted(
                [key for key in self.artist_data if key in artist_dict],
                key=lambda k: artist_dict.get(k, 0),
                reverse=True
            )
            self._update_listbox(self.artist_list)
    
    def _on_mode_changed(self, mode: str):
        """썸네일 모드 변경 시 처리"""
        if mode == self.mode_placeholder_text:
            return

        file_state = self._thumbnail_mode_file_state(mode)
        if mode in self.thumbnail_mode_data and file_state["available"]:
            self.current_mode = mode
            self.artist_data = self.thumbnail_mode_data[mode]
            self._previous_mode = mode
            self._update_artist_list_from_data()
            return
        if mode in self.thumbnail_mode_data and not file_state["available"]:
            self.thumbnail_mode_data.pop(mode, None)

        # 파일 경로 결정
        mode_info = ARTIST_THUMB_MODES.get(mode)
        if not mode_info:
            return
        file_path = file_state["path"]

        # 파일 존재 확인
        if not file_state["available"]:
            status = "업데이트 필요" if file_state["needs_update"] else "데이터 없음"
            # TODO(web-dialog): 원래 QMessageBox(Yes/No) 다운로드 confirm (~2.6GB) — Web Shell confirm 모달로 재구현 필요.
            # 안전 기본값: 다운로드 차단, 이전 모드로 복귀.
            print(f"[Dialog/CONFIRM(skipped→No)] 썸네일 데이터 {status} ({mode}) — Web Shell 재구현 예정")
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentText(self._previous_mode)
            self.mode_combo.blockSignals(False)
        else:
            # 파일이 있으면 로드 (current_mode, _previous_mode는 로드 성공 시 갱신)
            self._load_thumbnail_data(mode, file_path)
    
    def _download_thumbnail_data(self, mode: str, file_path: Path):
        """썸네일 데이터 다운로드"""
        # 진행률 다이얼로그 생성
        self.progress_dialog = QProgressDialog(self.widget)
        self.progress_dialog.setWindowTitle("다운로드 중")
        self.progress_dialog.setLabelText("썸네일 데이터를 다운로드하는 중...")
        self.progress_dialog.setRange(0, 100)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setCancelButtonText("취소")  # 취소 버튼 활성화
        self.progress_dialog.setMinimumDuration(0)

        # 다운로드 워커 생성
        self.download_worker = ThumbnailDownloadWorker(mode, file_path)
        self.download_worker.progress_updated.connect(self._on_download_progress)
        self.download_worker.download_finished.connect(self._on_download_finished)

        # 취소 버튼 연결
        self.progress_dialog.canceled.connect(self._on_download_canceled)

        self.download_worker.start()
        self.progress_dialog.show()

    def _on_download_canceled(self):
        """다운로드 취소 처리"""
        self._download_canceled = True
        if hasattr(self, 'download_worker') and self.download_worker:
            self.download_worker.cancel()
        # 콤보박스를 이전 상태로 복원
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentText(self._previous_mode)
        self.mode_combo.blockSignals(False)
        self.current_mode = self._previous_mode if self._previous_mode != self.mode_placeholder_text else None
    
    def _on_download_progress(self, percent: int, message: str):
        """다운로드 진행률 업데이트"""
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(message)
    
    def _on_download_finished(self, success: bool, message: str):
        """다운로드 완료 처리"""
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()

        if hasattr(self, 'download_worker'):
            self.download_worker.deleteLater()

        # 사용자가 이미 취소한 경우 중복 처리 방지
        if self._download_canceled:
            self._download_canceled = False
            return

        if success:
            QMessageBox.information(self.widget, "다운로드 완료", message)
            # 파일 로드
            mode_info = ARTIST_THUMB_MODES.get(self.current_mode)
            if mode_info:
                self._load_thumbnail_data(self.current_mode, Path(mode_info["path"]))
        else:
            QMessageBox.critical(self.widget, "다운로드 실패", f"다운로드 중 오류가 발생했습니다:\n{message}")
            # 실패 시 콤보박스 및 current_mode 롤백
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentText(self._previous_mode)
            self.mode_combo.blockSignals(False)
            self.current_mode = self._previous_mode if self._previous_mode != self.mode_placeholder_text else None
    
    def _load_thumbnail_data(self, mode: str, file_path: Path):
        """썸네일 데이터 파일 로드 (비동기)"""
        file_state = self._thumbnail_mode_file_state(mode)
        if not file_state["available"]:
            status = "업데이트가 필요합니다" if file_state["needs_update"] else "파일이 없습니다"
            QMessageBox.warning(self.widget, "데이터 로드 불가", f"{mode} 썸네일 데이터 {status}.")
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentText(self._previous_mode)
            self.mode_combo.blockSignals(False)
            self.current_mode = self._previous_mode if self._previous_mode != self.mode_placeholder_text else None
            return

        # 로딩 다이얼로그 표시
        self._load_dialog = QProgressDialog(self.widget)
        self._load_dialog.setWindowTitle("데이터 로드")
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        self._load_dialog.setLabelText(f"데이터를 읽는 중입니다... ({file_size_mb:.0f} MB)\n잠시만 기다려주세요.")
        self._load_dialog.setRange(0, 0)  # Indeterminate
        self._load_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._load_dialog.setCancelButton(None)
        self._load_dialog.setMinimumDuration(0)
        self._load_dialog.setMinimumWidth(400)
        # [X] 닫기 버튼 비활성화
        self._load_dialog.setWindowFlags(
            self._load_dialog.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )
        self._load_dialog.show()
        QApplication.processEvents()

        # 이전 로드 워커가 실행 중이면 시그널 해제 (결과 무시)
        if hasattr(self, '_json_load_worker') and self._json_load_worker:
            self._json_load_worker.load_finished.disconnect(self._on_json_load_finished)
            self._json_load_worker.deleteLater()
            self._json_load_worker = None

        # 워커 스레드 시작
        self._load_mode = mode
        self._json_load_worker = JsonLoadWorker(file_path)
        self._json_load_worker.load_finished.connect(self._on_json_load_finished)
        self._json_load_worker.start()

    def _on_json_load_finished(self, data, error_message: str):
        """JSON 로드 완료 처리"""
        # 다이얼로그 닫기
        if hasattr(self, '_load_dialog') and self._load_dialog:
            self._load_dialog.close()
            self._load_dialog = None

        # 워커 정리
        if hasattr(self, '_json_load_worker') and self._json_load_worker:
            self._json_load_worker.deleteLater()
            self._json_load_worker = None

        # 에러 발생
        if data is None:
            QMessageBox.critical(self.widget, "오류", f"파일을 열 수 없습니다:\n{error_message}")
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentText(self._previous_mode)
            self.mode_combo.blockSignals(False)
            self.current_mode = self._previous_mode if self._previous_mode != self.mode_placeholder_text else None
            return

        # 데이터 저장 + 상태 갱신
        mode = self._load_mode
        self.thumbnail_mode_data[mode] = data
        if mode == "NAID4.5F-31000":
            self.nai_data = data
        elif mode == "NoobNAI-XL-33000":
            self.noob_data = data
        self.artist_data = data

        self.current_mode = mode
        self._previous_mode = mode

        # 리스트 업데이트
        self._update_artist_list_from_data()
    
    
    def _update_listbox(self, items: List[str]):
        """리스트박스 업데이트 - 아티스트명만 표시"""
        self.artist_listbox.clear()
        
        for item in items:
            # 아티스트명만 표시
            list_item = QListWidgetItem(item)
            
            # 가중치는 툴팁으로만 표시
            weight = artist_dict.get(item, 0)
            list_item.setToolTip(f"아티스트: {item}\n가중치: {weight:,}")
            
            self.artist_listbox.addItem(list_item)
    
    def _perform_search(self):
        """검색 결과를 포커스를 훔치지 않는 QListWidget 팝업으로 표시"""
        search_text = self.search_input.text().strip().lower()
        
        # 최소 1글자 이상일 때만 검색 수행
        if len(search_text) < 1:
            if self.search_popup and self.search_popup.isVisible():
                self.search_popup.hide()
            # 빈 검색어일 때는 전체 리스트 업데이트 하지 않음 (성능 문제 방지)
            return

        results = []

        # 시작 매치 우선
        for artist in self.artist_list:
            al = artist.lower()
            if al.startswith(search_text):
                value = artist_dict.get(artist, 0)
                results.append((artist, value, 0))
                if len(results) >= self.max_suggestions:
                    break

        # 포함 매치 (모자라면)
        if len(results) < self.max_suggestions:
            for artist in self.artist_list:
                al = artist.lower()
                if search_text in al and not al.startswith(search_text):
                    value = artist_dict.get(artist, 0)
                    results.append((artist, value, 1))
                    if len(results) >= self.max_suggestions:
                        break

        # 정렬: 매치 타입 → 가중치
        results.sort(key=lambda x: (x[2], -x[1]))
        results = results[:self.max_suggestions]

        # 팝업 채우기/표시
        if results:
            self.search_popup.clear()
            for artist, weight, _ in results:
                # 가중치 짧게
                wtxt = f"{weight/1000:.1f}k" if weight >= 1000 else str(weight)
                # 고정폭 폰트를 위해 적절한 패딩 추가
                padding = max(50 - len(artist), 4)  # 최소 4칸 간격
                display_text = f"{artist}{' ' * padding}{wtxt}"
                item = QListWidgetItem(display_text)
                # 정렬용 실제 값 보관
                item.setData(Qt.ItemDataRole.UserRole, artist)
                self.search_popup.addItem(item)

            # 첫 항목 선택
            if self.search_popup.count() > 0:
                self.search_popup.setCurrentRow(0)

            # 위치/크기
            line = self.search_input
            global_pos = line.mapToGlobal(QPoint(0, line.height()))
            self.search_popup.move(global_pos)
            # 너비는 검색창보다 넓게, 높이는 최대 10개 항목
            self.search_popup.resize(max(line.width(), get_scaled_size(400)),
                                    self.search_popup.sizeHintForRow(0) * min(self.search_popup.count(), 10) + get_scaled_size(8))
            self.search_popup.show()
            # 포커스는 계속 라인에디트에
            self.search_input.setFocus()
        else:
            if self.search_popup.isVisible():
                self.search_popup.hide()


    
    def _on_artist_selected(self):
        """아티스트 선택 시"""
        current_item = self.artist_listbox.currentItem()
        
        if not current_item:
            return
        
        # 이제 리스트에는 아티스트명만 있으므로 직접 사용
        previous_artist = self.current_artist
        artist_name = current_item.text()
        self.current_artist = artist_name

        # 썸네일 표시
        self._display_artist_thumbnail(artist_name)

        # 크게 보기 모드가 활성화되어 있으면 generation_image도 업데이트
        if hasattr(self, '_large_preview_mode') and self._large_preview_mode:
            self._show_thumbnail_in_generation_panel()

        # 정보 업데이트
        weight = artist_dict.get(artist_name, 0) if artist_dict else 0
        self.info_label.setText(f"선택된 아티스트: {artist_name} (가중치: {weight})")

        # 관심/제외 버튼 활성화 및 상태 업데이트
        self.favorite_button.setEnabled(True)
        self.ban_button.setEnabled(True)
        
        # 관심 작가 여부에 따라 버튼 텍스트 및 스타일 변경
        if artist_name in self.favorite_artists:
            self.favorite_button.setText("⭐ 관심 작가 해제")
            # 관심 작가인 경우 회색 배경
            self.favorite_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: #666666;
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(6)}px;
                    font-size: {get_scaled_font_size(15)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #777777;
                }}
                QPushButton:disabled {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_secondary']};
                }}
            """)
        else:
            self.favorite_button.setText("⭐ 관심 작가 등록")
            # 관심 작가가 아닌 경우 파란색 배경
            self.favorite_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(6)}px;
                    font-size: {get_scaled_font_size(15)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['accent_blue_hover']};
                }}
                QPushButton:disabled {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_secondary']};
                }}
            """)
        
        # 프롬프트에 아티스트명 추가 (랜더마이저가 비활성 상태일 때만)
        if hasattr(self, 'positive_prompt'):
            # 랜더마이저가 활성화되어 있으면 프롬프트 업데이트 하지 않음
            if hasattr(self, 'randomizer_checkbox') and self.randomizer_checkbox.isChecked():
                print(f"🎲 랜더마이저 활성 상태 - 아티스트 태그 자동 추가 비활성")
            else:
                current_positive = self.positive_prompt.toPlainText()
                current_mode = self._current_options_mode()
                previous_auto_tag = self._last_auto_artist_tag_by_mode.get(current_mode, "")
                lines = [line.strip() for line in current_positive.split(',')]
                if previous_auto_tag:
                    lines = [line for line in lines if line != previous_auto_tag]
                elif previous_artist:
                    previous_tags = set(self._artist_prompt_tag_variants(previous_artist))
                    lines = [line for line in lines if line not in previous_tags]
                else:
                    lines = [line for line in lines if not line.startswith('artist:')]
                lines = [line for line in lines if line]
                # 새 아티스트 태그 추가
                artist_tag = self._format_artist_prompt_tag(artist_name)
                self._last_auto_artist_tag_by_mode[current_mode] = artist_tag
                if lines:
                    self.positive_prompt.setPlainText(f"{artist_tag}, {', '.join(lines)}")
                else:
                    self.positive_prompt.setPlainText(artist_tag)
        
        # 시그널 발생
        self.artist_selected.emit(artist_name)
    
    def _display_artist_thumbnail(self, artist_name: str):
        """아티스트 썸네일 표시"""
        img_data_list = self.artist_data.get(artist_name, [])

        if img_data_list and img_data_list[0]:
            try:
                # base64 디코딩
                img_bytes = base64.b64decode(img_data_list[0])

                # QPixmap으로 직접 변환
                pixmap = QPixmap()
                pixmap.loadFromData(img_bytes)

                if hasattr(self, 'thumbnail_label'):
                    # 좌우 85픽셀씩 잘라내기 (검은색 썸네일 영역 제거)
                    if pixmap.width() > 170:  # 최소 170픽셀 이상일 때만 크롭
                        cropped_pixmap = pixmap.copy(
                            85,  # x 시작점
                            0,   # y 시작점
                            pixmap.width() - 170,  # 너비 (양쪽 85픽셀씩 제거)
                            pixmap.height()  # 높이 유지
                        )
                    else:
                        cropped_pixmap = pixmap

                    # 호환 헬퍼 기반 썸네일 크기 사용
                    padding = get_scaled_size(4) * 2  # 양쪽 패딩
                    thumbnail_width = get_scaled_size(350)
                    target_width = thumbnail_width - padding
                    target_height = int(thumbnail_width * 3.8 / 3.0) - padding

                    # 계산된 크기로 스케일링
                    scaled_pixmap = cropped_pixmap.scaled(
                        target_width,
                        target_height,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.thumbnail_label.setPixmap(scaled_pixmap)

            except Exception as e:
                print(f"썸네일 표시 오류: {e}")
                if hasattr(self, 'thumbnail_label'):
                    self._show_default_thumbnail()
        else:
            if hasattr(self, 'thumbnail_label'):
                self._show_default_thumbnail()
    
    def _on_popup_item_clicked(self, item):
        artist = item.data(Qt.ItemDataRole.UserRole)
        self._accept_suggestion(artist)

    def _accept_suggestion(self, artist: str):
        """선택한 추천어를 적용"""
        self.search_input.setText(artist)

        # 메인 리스트에서 해당 아티스트 선택
        for i in range(self.artist_listbox.count()):
            if self.artist_listbox.item(i).text() == artist:
                self.artist_listbox.setCurrentRow(i)
                self.artist_listbox.scrollToItem(self.artist_listbox.item(i))
                break

        if self.search_popup.isVisible():
            self.search_popup.hide()
        self.search_input.setFocus()

    def _init_search_popup(self):
        """QListWidget 기반 검색 팝업 초기화 (포커스 훔치지 않음)"""
        from PyQt6.QtWidgets import QListWidget
        self.search_popup = QListWidget(self.widget)
        self.search_popup.setWindowFlags(Qt.WindowType.ToolTip)
        # 포커스 훔치지 않기
        self.search_popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.search_popup.setMouseTracking(True)
        self.search_popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_popup.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.search_popup.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 2px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(14)}px;
                font-family: 'Consolas', 'Courier New', monospace;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(6)}px {get_scaled_size(8)}px;
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.search_popup.itemClicked.connect(self._on_popup_item_clicked)

        # 라인에디트에서 키를 가로채 팝업 제어
        self.search_input.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.search_input and event.type() == event.Type.KeyPress:
            key = event.key()
            # 팝업이 열려 있을 때만 네비게이션
            if self.search_popup and self.search_popup.isVisible():
                if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    current = self.search_popup.currentRow()
                    if key == Qt.Key.Key_Down:
                        current = min(current + 1, self.search_popup.count() - 1)
                    else:
                        current = max(current - 1, 0)
                    self.search_popup.setCurrentRow(current)
                    return True  # ✅ 라인에디트로 전달하지 않음

                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                    item = self.search_popup.currentItem()
                    if item:
                        self._accept_suggestion(item.data(Qt.ItemDataRole.UserRole))
                    return True  # ✅ 기본 탭 이동/엔터 입력 막음

                if key == Qt.Key.Key_Escape:
                    self.search_popup.hide()
                    return True

            # 팝업이 닫혀있고 ↓면 팝업을 열고 첫 항목 선택
            if key == Qt.Key.Key_Down and self.search_popup and not self.search_popup.isVisible():
                self._perform_search()
                return True

        return super().eventFilter(obj, event)
    
    def _on_generate_clicked(self):
        """Generate 버튼 클릭 시 이미지 생성"""
        if not self.app_context:
            QMessageBox.warning(self.widget, "오류", "앱 컨텍스트가 없습니다.")
            return
        
        # 랜더마이저 처리
        randomizer_string = ""
        selected_artists = []
        if hasattr(self, 'randomizer_checkbox') and self.randomizer_checkbox.isChecked():
            randomizer_string, selected_artists = self.get_randomized_artist_string()
            
            # 선택된 아티스트가 있으면 리스트박스 업데이트
            if selected_artists and hasattr(self, 'artist_listbox'):
                # 리스트박스 비우기
                self.artist_listbox.clear()
                # 선택된 아티스트들로 업데이트
                for artist in selected_artists:
                    self.artist_listbox.addItem(artist)
                print(f"🎲 랜더마이저 선택 아티스트: {', '.join(selected_artists)}")
                
                # 리스트 길이가 1 이상이면 첫번째 아이템 자동 선택
                if self.artist_listbox.count() > 0:
                    self.artist_listbox.setCurrentRow(0)
                    # 선택 이벤트 트리거
                    self._on_artist_selected()
            
            # positive_prompt에 랜더마이저 문자열 업데이트
            if randomizer_string:
                self.positive_prompt.setPlainText(randomizer_string)
        
        # Positive 프롬프트 가져오기 (랜더마이저 적용 후)
        positive = self.positive_prompt.toPlainText().strip()
        
        # Prefix와 Postfix 가져오기
        prefix = self.prefix_textedit.toPlainText().strip()
        postfix = self.postfix_textedit.toPlainText().strip()
        
        # 생성 옵션 저장
        self._save_generate_options()
        
        # 최종 프롬프트 조합: prefix + positive + postfix
        final_prompt_parts = []
        if prefix:
            final_prompt_parts.append(prefix)
        if positive:
            final_prompt_parts.append(positive)
        if postfix:
            final_prompt_parts.append(postfix)
        
        final_positive = ", ".join(final_prompt_parts)
        
        # Negative 프롬프트는 메인 윈도우에서 가져오기
        negative = ""
        if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'negative_prompt_text'):
            negative = self.app_context.main_window.negative_prompt_text.toPlainText().strip()
        
        if not final_positive:
            QMessageBox.warning(self.widget, "경고", "프롬프트를 입력하세요.")
            return
        
        # 오버라이드 파라미터 준비
        override_params = {
            'input': final_positive,
            'negative_prompt': negative,
            'width': 832,
            'height': 1216,
            'random_resolution': False,
            'artist_thumb_request': True  # ArtistThumb 전용 식별자
        }
        
        # 자동 생성 체크박스 해제 (필요한 경우)
        if hasattr(self.app_context, 'main_window'):
            auto_generate_checkbox = self.app_context.main_window.generation_checkboxes.get("자동 생성")
            if auto_generate_checkbox and auto_generate_checkbox.isChecked():
                auto_generate_checkbox.setChecked(False)
        
        # ArtistThumb 전용 생성 완료 이벤트 구독
        # 구독 중복 방지 후 구독
        try:
            subs = getattr(self.app_context, 'subscribers', {}).get("generation_completed_for_artist_thumb", [])
            if self._on_generation_completed not in subs:
                self.app_context.subscribe("generation_completed_for_artist_thumb", self._on_generation_completed)
        except Exception:
            self.app_context.subscribe("generation_completed_for_artist_thumb", self._on_generation_completed)
        
        # Generate 버튼 비활성화
        self.generate_btn.setEnabled(False)
        if hasattr(self, 'continuous_generation_checkbox') and self.continuous_generation_checkbox.isChecked():
            self.generate_btn.setText("🔄 연속생성 중...")
        else:
            self.generate_btn.setText("🔄 생성 중...")
        
        # generation_controller의 execute_generation_pipeline 호출
        if hasattr(self.app_context, 'main_window'):
            gen_controller = self.app_context.main_window.generation_controller
            gen_controller.execute_generation_pipeline(overrides=override_params)
            print(f"🎨 ArtistThumb: 이미지 생성 시작 (832x1216)")
        else:
            print("⚠️ generation_controller를 찾을 수 없습니다.")
            # 오류 발생 시 버튼 복원
            self.generate_btn.setEnabled(True)
            self.generate_btn.setText("🎨 Generate (832x1216)")
    
    def _on_generation_completed(self, result):
        """이미지 생성 완료 콜백"""
        try:
            # result가 PIL Image인지 확인
            image_object = result
            if hasattr(image_object, 'mode'):  # PIL Image 확인
                # 생성된 이미지 저장 (크게 보기 토글 해제 시 복원용)
                self._last_generated_image = image_object

                # StableImageWidget에 생성 결과 표시 (크게 보기 모드 여부와 무관하게 항상 표시)
                if hasattr(self, 'generation_image'):
                    self.generation_image.setPilImage(image_object)
                    print("✅ ArtistThumb: 이미지 생성 완료")

                # 상태바 메시지
                if hasattr(self.app_context, 'main_window'):
                    self.app_context.main_window.status_bar.showMessage(
                        "✅ ArtistThumb: 이미지 생성 완료", 3000
                    )

                # 연속생성이 활성화되어 있으면 1초 후 다시 생성
                if hasattr(self, 'continuous_generation_checkbox') and self.continuous_generation_checkbox.isChecked():
                    print("🔄 연속생성 모드: 1초 후 다시 생성")
                    # QTimer 사용하여 1초 후 생성 호출
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(1000, self._trigger_continuous_generation)
            else:
                print(f"⚠️ 예상과 다른 결과 타입: {type(result)}")
                
        except Exception as e:
            print(f"❌ 생성 완료 처리 중 오류: {e}")
            print(f"결과 타입: {type(result)}")
        finally:
            # 연속생성 모드가 아닐 때만 정리
            if not (hasattr(self, 'continuous_generation_checkbox') and self.continuous_generation_checkbox.isChecked()):
                # 항상 구독 해제 및 버튼 복원 (finally 블록에서 안전하게 처리)
                self._cleanup_generation()
            else:
                # 연속생성 모드에서는 구독만 해제하고 버튼은 비활성 상태 유지
                self._cleanup_generation_subscription_only()
    
    def _trigger_continuous_generation(self):
        """연속생성을 위한 생성 트리거"""
        # 연속생성이 여전히 활성화되어 있는지 확인
        if hasattr(self, 'continuous_generation_checkbox') and self.continuous_generation_checkbox.isChecked():
            print("🔄 연속생성: 새로운 생성 시작")
            self._on_generate_clicked()
    
    def _cleanup_generation_subscription_only(self):
        """구독만 해제 (버튼 상태는 유지)"""
        try:
            # ArtistThumb 전용 구독 해제 (AppContext에 unsubscribe가 없으므로 수동 제거)
            if hasattr(self, 'app_context') and self.app_context and "generation_completed_for_artist_thumb" in self.app_context.subscribers:
                subs = self.app_context.subscribers["generation_completed_for_artist_thumb"]
                if self._on_generation_completed in subs:
                    subs.remove(self._on_generation_completed)
                    print("✅ ArtistThumb 생성 완료 이벤트 구독 해제")
        except Exception as e:
            print(f"⚠️ 구독 해제 중 오류: {e}")
    
    def _cleanup_generation(self):
        """생성 관련 정리 작업"""
        try:
            # ArtistThumb 전용 구독 해제
            if hasattr(self, 'app_context') and self.app_context and "generation_completed_for_artist_thumb" in self.app_context.subscribers:
                if self._on_generation_completed in self.app_context.subscribers["generation_completed_for_artist_thumb"]:
                    self.app_context.subscribers["generation_completed_for_artist_thumb"].remove(self._on_generation_completed)
        except Exception as e:
            print(f"⚠️ 구독 해제 중 오류: {e}")
        
        # Generate 버튼 복원
        if hasattr(self, 'generate_btn'):
            self.generate_btn.setEnabled(True)
            self.generate_btn.setText("🎨 Generate (832x1216)")
    
    def cleanup(self):
        """탭 종료 시 정리"""
        self._save_generate_options()
        self._unsubscribe_api_mode_changed()

        # 연속생성 중지
        if hasattr(self, 'continuous_generation_checkbox'):
            self.continuous_generation_checkbox.setChecked(False)
        
        # 검색 팝업 정리
        if self.search_popup and self.search_popup.isVisible():
            self.search_popup.hide()
        
        # 생성 관련 정리
        self._cleanup_generation()
        
        # 다운로드 워커 정리
        if hasattr(self, 'download_worker') and self.download_worker:
            self.download_worker.quit()
            self.download_worker.wait(1000)
            self.download_worker.deleteLater()

        # JSON 로드 워커 정리
        for attr in ('_json_load_worker',):
            worker = getattr(self, attr, None)
            if worker:
                if hasattr(worker, 'cancel'):
                    worker.cancel()
                worker.quit()
                worker.wait(3000)
                worker.deleteLater()
                setattr(self, attr, None)
    
    def _load_artist_lists(self):
        """파일에서 관심/제외 작가 목록 로드"""
        # wildcards 폴더 생성
        os.makedirs('wildcards', exist_ok=True)
        # artist_thumb 폴더 생성
        os.makedirs('artist_thumb', exist_ok=True)
        
        # 관심 작가 파일 로드
        favorite_file = os.path.join('wildcards', 'favorite_artist.txt')
        if os.path.exists(favorite_file):
            with open(favorite_file, 'r', encoding='utf-8') as f:
                self.favorite_artists = [line.strip() for line in f if line.strip()]
        else:
            # 파일이 없으면 생성
            with open(favorite_file, 'w', encoding='utf-8') as f:
                pass
        
        # 제외 작가 파일 로드
        banned_file = os.path.join('artist_thumb', 'banned_artist.txt')
        if os.path.exists(banned_file):
            with open(banned_file, 'r', encoding='utf-8') as f:
                self.banned_artists = [line.strip() for line in f if line.strip()]
        else:
            # 파일이 없으면 생성
            with open(banned_file, 'w', encoding='utf-8') as f:
                pass
        
        # 생성 옵션 파일 로드
        self._load_generate_options()
    
    def _save_favorite_artists(self):
        """관심 작가 목록을 파일에 저장"""
        favorite_file = os.path.join('wildcards', 'favorite_artist.txt')
        with open(favorite_file, 'w', encoding='utf-8') as f:
            for artist in self.favorite_artists:
                f.write(f"{artist}\n")
    
    def _save_banned_artists(self):
        """제외 작가 목록을 파일에 저장"""
        banned_file = os.path.join('artist_thumb', 'banned_artist.txt')
        with open(banned_file, 'w', encoding='utf-8') as f:
            for artist in self.banned_artists:
                f.write(f"{artist}\n")
    
    def _current_options_mode(self, mode: str = "") -> str:
        mode_key = str(mode or "").strip().upper()
        if mode_key in ARTIST_THUMB_OPTION_MODES:
            return mode_key
        current_mode = str(self._current_api_mode() or "").strip().upper()
        if current_mode in ARTIST_THUMB_OPTION_MODES:
            return current_mode
        return "NAI"

    def _normalize_generate_options(self, data, mode: str = "") -> dict:
        source = data if isinstance(data, dict) else {}
        legacy = {
            'prefix': str(source.get('prefix') or ''),
            'postfix': str(source.get('postfix') or ''),
        }
        raw_modes = source.get('modes') if isinstance(source.get('modes'), dict) else {}
        modes = {}
        for mode_key in ARTIST_THUMB_OPTION_MODES:
            values = raw_modes.get(mode_key) if isinstance(raw_modes.get(mode_key), dict) else {}
            prefix = values.get('prefix') if 'prefix' in values else legacy['prefix']
            postfix = values.get('postfix') if 'postfix' in values else legacy['postfix']
            modes[mode_key] = {
                'prefix': str(prefix or ''),
                'postfix': str(postfix or ''),
            }
        mode_key = self._current_options_mode(mode)
        selected = modes.get(mode_key, modes['NAI'])
        return {
            'version': 2,
            'mode': mode_key,
            'prefix': selected['prefix'],
            'postfix': selected['postfix'],
            'modes': modes,
        }

    def _load_generate_options(self, mode: str = ""):
        """생성 옵션 파일 로드"""
        mode_key = self._current_options_mode(mode)
        options = self._normalize_generate_options({}, mode_key)
        options_file = os.path.join('artist_thumb', 'generate_options.json')
        if os.path.exists(options_file):
            try:
                with open(options_file, 'r', encoding='utf-8') as f:
                    options = self._normalize_generate_options(json.load(f), mode_key)
            except Exception as e:
                print(f"생성 옵션 로드 실패: {e}")
        if hasattr(self, 'prefix_textedit'):
            self.prefix_textedit.setPlainText(options.get('prefix', ''))
        if hasattr(self, 'postfix_textedit'):
            self.postfix_textedit.setPlainText(options.get('postfix', ''))
        self._generate_options_mode = mode_key
    
    def _save_generate_options(self, mode: str = ""):
        """생성 옵션을 파일에 저장"""
        if not (hasattr(self, 'prefix_textedit') or hasattr(self, 'postfix_textedit')):
            return
        os.makedirs('artist_thumb', exist_ok=True)
        options_file = os.path.join('artist_thumb', 'generate_options.json')
        mode_key = self._current_options_mode(mode or self._generate_options_mode)
        current = {}
        if os.path.exists(options_file):
            try:
                with open(options_file, 'r', encoding='utf-8') as f:
                    current = json.load(f)
            except Exception as e:
                print(f"생성 옵션 기존 파일 로드 실패: {e}")
        options = self._normalize_generate_options(current, mode_key)
        mode_values = options['modes'].setdefault(mode_key, {'prefix': '', 'postfix': ''})
        if hasattr(self, 'prefix_textedit'):
            mode_values['prefix'] = self.prefix_textedit.toPlainText().strip()
        if hasattr(self, 'postfix_textedit'):
            mode_values['postfix'] = self.postfix_textedit.toPlainText().strip()
        selected = options['modes'][mode_key]
        options['version'] = 2
        options['mode'] = mode_key
        options['prefix'] = selected.get('prefix', '')
        options['postfix'] = selected.get('postfix', '')

        try:
            with open(options_file, 'w', encoding='utf-8') as f:
                json.dump(options, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception as e:
            print(f"생성 옵션 저장 실패: {e}")

    def _subscribe_api_mode_changed(self):
        try:
            if not self.app_context or not hasattr(self.app_context, 'subscribe'):
                return
            subs = getattr(self.app_context, 'subscribers', {}).get('api_mode_changed', [])
            if self._on_api_mode_changed not in subs:
                self.app_context.subscribe('api_mode_changed', self._on_api_mode_changed)
        except Exception as e:
            print(f"API 모드 변경 구독 실패: {e}")

    def _unsubscribe_api_mode_changed(self):
        try:
            if not self.app_context:
                return
            if hasattr(self.app_context, 'unsubscribe'):
                self.app_context.unsubscribe('api_mode_changed', self._on_api_mode_changed)
                return
            subs = getattr(self.app_context, 'subscribers', {}).get('api_mode_changed', [])
            while self._on_api_mode_changed in subs:
                subs.remove(self._on_api_mode_changed)
        except Exception as e:
            print(f"API 모드 변경 구독 해제 실패: {e}")

    def _on_api_mode_changed(self, payload=None):
        if not (hasattr(self, 'prefix_textedit') or hasattr(self, 'postfix_textedit')):
            return
        data = payload if isinstance(payload, dict) else {}
        old_mode = self._current_options_mode(data.get('old_mode') or self._generate_options_mode)
        new_mode = self._current_options_mode(data.get('new_mode'))
        if old_mode == new_mode:
            return
        self._save_generate_options(old_mode)
        self._load_generate_options(new_mode)
    
    def _open_gallery_window(self):
        """갤러리 윈도우 열기 - filter_combo 옵션에 따라 다른 아티스트 리스트 표시"""
        from tabs.artist_thumb.gallery_window import ArtistGalleryWindow
        from artist_dictionary import artist_dict

        # 현재 필터 옵션 확인
        current_filter = self.filter_combo.currentText()

        # 필터에 따른 아티스트 리스트 생성
        if current_filter == "관심 작가 보기":
            # 관심 작가만 표시
            base_list = [a for a in self.favorite_artists if a in self.artist_data and a in artist_dict]
            window_title_suffix = " (관심 작가)"
        elif current_filter == "제외 작가 보기":
            # 제외 작가만 표시
            base_list = [a for a in self.banned_artists if a in self.artist_data and a in artist_dict]
            window_title_suffix = " (제외 작가)"
        elif current_filter not in ["전체 목록 보기", "+ 분류 그룹 추가"]:
            # 커스텀 필터 파일에서 아티스트 로드
            filter_file = os.path.join('artist_thumb', f"{current_filter}.txt")
            custom_artists = []
            if os.path.exists(filter_file):
                try:
                    with open(filter_file, 'r', encoding='utf-8') as f:
                        custom_artists = [line.strip() for line in f if line.strip()]
                except Exception as e:
                    print(f"필터 파일 로드 실패: {e}")
            base_list = [a for a in custom_artists if a in self.artist_data and a in artist_dict]
            window_title_suffix = f" ({current_filter})"
        else:
            # 전체 목록 보기
            base_list = [key for key in self.artist_data if key in artist_dict]
            window_title_suffix = ""

        # 가중치 기준 내림차순 정렬
        artist_list = sorted(
            base_list,
            key=lambda k: artist_dict.get(k, 0),
            reverse=True
        )

        if not artist_list:
            from PyQt6.QtWidgets import QMessageBox
            if not self.artist_data:
                QMessageBox.warning(self.widget, "경고", "썸네일 모드를 먼저 선택해주세요.\n(썸네일 데이터가 로드되지 않았습니다)")
            else:
                QMessageBox.warning(self.widget, "경고", f"표시할 아티스트가 없습니다.\n(필터: {current_filter})")
            return

        self.gallery_window = ArtistGalleryWindow(
            artist_data=self.artist_data,
            artist_list=artist_list,
            favorite_artists=self.favorite_artists,
            current_mode=self.current_mode,
            parent=None,  # 듀얼 모니터 z-order 분리: 메인 창과 독립적으로 떠있음
            title_suffix=window_title_suffix,
            app_context=self.app_context
        )
        # 독립 창이지만 메인 종료 시 함께 닫히도록
        # DeleteOnClose=True: 닫힐 때 Qt가 자동으로 aboutToQuit 연결까지 해제 → 누수 방지
        self.gallery_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.gallery_window.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        _app = QApplication.instance()
        if _app is not None:
            _app.aboutToQuit.connect(self.gallery_window.close)

        # 시그널 연결
        self.gallery_window.favorite_toggled.connect(self._on_gallery_favorite_toggled)
        self.gallery_window.artist_clicked.connect(self._on_gallery_artist_clicked)
        self.gallery_window.generate_requested.connect(self._on_gallery_generate_requested)
        self.gallery_window.custom_generate_requested.connect(self._on_gallery_custom_generate_requested)

        self.gallery_window.show()

    def _on_gallery_favorite_toggled(self, artist_name: str, is_favorite: bool):
        """갤러리에서 관심 작가 토글"""
        if is_favorite and artist_name not in self.favorite_artists:
            self.favorite_artists.append(artist_name)
        elif not is_favorite and artist_name in self.favorite_artists:
            self.favorite_artists.remove(artist_name)

        self._save_favorite_artists()

        # 현재 선택된 아티스트면 버튼 상태 업데이트
        if self.current_artist == artist_name:
            self._update_favorite_button_state()

        # 필터가 관심 작가 보기인 경우 리스트 업데이트
        if self.filter_combo.currentText() == "관심 작가 보기":
            self._update_listbox(self.favorite_artists)

    def _on_gallery_artist_clicked(self, artist_name: str):
        """갤러리에서 아티스트 클릭 - 메인 리스트에서 선택"""
        # 현재 필터 모드 확인
        current_filter = self.filter_combo.currentText()

        # 전체 목록 보기로 전환 (해당 아티스트가 현재 필터에 없을 수 있음)
        if current_filter != "전체 목록 보기":
            self.filter_combo.setCurrentText("전체 목록 보기")

        # 리스트박스에서 해당 아티스트 찾아 선택
        for i in range(self.artist_listbox.count()):
            if self.artist_listbox.item(i).text() == artist_name:
                self.artist_listbox.setCurrentRow(i)
                self.artist_listbox.scrollToItem(self.artist_listbox.item(i))
                break

    def _on_gallery_generate_requested(self, artist_name: str):
        """갤러리에서 생성 요청 - 해당 아티스트 선택 후 생성"""
        # 현재 필터 모드 확인 및 전체 목록으로 전환
        current_filter = self.filter_combo.currentText()
        if current_filter != "전체 목록 보기":
            self.filter_combo.setCurrentText("전체 목록 보기")

        # 리스트박스에서 해당 아티스트 찾아 선택
        for i in range(self.artist_listbox.count()):
            if self.artist_listbox.item(i).text() == artist_name:
                self.artist_listbox.setCurrentRow(i)
                break

        # 선택 이벤트 처리 후 생성 버튼 클릭
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self._on_generate_clicked)

    def _on_gallery_custom_generate_requested(self, custom_tags: str):
        """갤러리에서 커스텀 작가 태그 조합으로 생성 요청"""
        # 기존 내용 백업
        original_text = self.positive_prompt.toPlainText()

        # positive_prompt에 커스텀 태그 덮어쓰기
        self.positive_prompt.setPlainText(custom_tags)

        # 생성 버튼 클릭 후 원래 내용 복원
        from PyQt6.QtCore import QTimer

        def restore_and_generate():
            self._on_generate_clicked()
            # 생성 요청 후 원래 내용 복원
            QTimer.singleShot(200, lambda: self.positive_prompt.setPlainText(original_text))

        QTimer.singleShot(100, restore_and_generate)

    def _update_favorite_button_state(self):
        """현재 선택된 아티스트에 맞춰 관심 작가 버튼 상태 업데이트"""
        if not self.current_artist:
            return

        if self.current_artist in self.favorite_artists:
            self.favorite_button.setText("⭐ 관심 작가 해제")
            self.favorite_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: #666666;
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(6)}px;
                    font-size: {get_scaled_font_size(15)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #777777;
                }}
                QPushButton:disabled {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_secondary']};
                }}
            """)
        else:
            self.favorite_button.setText("⭐ 관심 작가 등록")
            self.favorite_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(6)}px;
                    font-size: {get_scaled_font_size(15)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['accent_blue_hover']};
                }}
                QPushButton:disabled {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_secondary']};
                }}
            """)

    def _toggle_favorite(self):
        """관심 작가 등록/해제 토글"""
        if not self.current_artist:
            return

        if self.current_artist in self.favorite_artists:
            # 이미 관심 작가인 경우 해제
            self.favorite_artists.remove(self.current_artist)
            self.favorite_button.setText("⭐ 관심 작가 등록")
            # 버튼 배경색을 원래대로
            self.favorite_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(6)}px;
                    font-size: {get_scaled_font_size(15)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['accent_blue_hover']};
                }}
                QPushButton:disabled {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_secondary']};
                }}
            """)
            self._save_favorite_artists()
            # 다이얼로그 제거 - 시각적 피드백만 제공
        else:
            # 관심 작가에 추가
            self.favorite_artists.append(self.current_artist)
            self.favorite_button.setText("⭐ 관심 작가 해제")
            # 버튼 배경색을 회색으로 변경
            self.favorite_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: #666666;
                    color: white;
                    border: none;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(6)}px;
                    font-size: {get_scaled_font_size(15)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #777777;
                }}
                QPushButton:disabled {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_secondary']};
                }}
            """)
            self._save_favorite_artists()
            # 다이얼로그 제거 - 시각적 피드백만 제공
        
        # 필터가 관심 작가 보기인 경우 리스트 업데이트
        if self.filter_combo.currentText() == "관심 작가 보기":
            self._apply_filter()
    
    def _ban_artist(self):
        """현재 선택된 작가를 제외 목록에 추가"""
        if not self.current_artist:
            return
        
        # 현재 아이템의 인덱스 저장
        current_index = -1
        for i in range(self.artist_listbox.count()):
            if self.artist_listbox.item(i).text() == self.current_artist:
                current_index = i
                break
        
        # 제외 목록에 추가
        if self.current_artist not in self.banned_artists:
            self.banned_artists.append(self.current_artist)
            self._save_banned_artists()
        
        # 관심 목록에서 제거
        if self.current_artist in self.favorite_artists:
            self.favorite_artists.remove(self.current_artist)
            self._save_favorite_artists()
        
        # 리스트에서 제거
        if current_index >= 0:
            self.artist_listbox.takeItem(current_index)
            
            # 다음 아이템 선택 (있으면)
            if self.artist_listbox.count() > 0:
                # 같은 인덱스를 선택하거나, 마지막이었다면 이전 아이템 선택
                new_index = min(current_index, self.artist_listbox.count() - 1)
                self.artist_listbox.setCurrentRow(new_index)
                # 선택 이벤트 수동 트리거
                self._on_artist_selected()
            else:
                # 리스트가 비었을 때
                self.current_artist = None
                self.favorite_button.setEnabled(False)
                self.ban_button.setEnabled(False)
                self._show_default_thumbnail()
    
    def _on_filter_changed(self, filter_mode: str):
        """필터 모드 변경 시 처리"""
        if filter_mode == "+ 분류 그룹 추가":
            # 파일명 입력 다이얼로그
            filename, ok = QInputDialog.getText(
                self.widget,
                "분류 그룹 추가",
                "새 분류 그룹 파일명을 입력하세요:\n(artist_thumb 폴더에 .txt 파일로 저장됩니다)",
                QLineEdit.EchoMode.Normal,
                ""
            )
            
            if ok and filename:
                # 파일명 검증
                filename = filename.strip()
                if not filename:
                    QMessageBox.warning(self.widget, "경고", "파일명을 입력해주세요.")
                    # 이전 선택으로 복원
                    self.filter_combo.blockSignals(True)
                    self.filter_combo.setCurrentText(self.filter_mode)
                    self.filter_combo.blockSignals(False)
                    return
                
                # .txt 확장자 추가 (없으면)
                if not filename.endswith('.txt'):
                    filename += '.txt'
                
                # 파일 경로
                os.makedirs('artist_thumb', exist_ok=True)
                file_path = os.path.join('artist_thumb', filename)
                
                # 파일이 이미 존재하는지 확인
                if os.path.exists(file_path):
                    QMessageBox.warning(self.widget, "경고", f"{filename} 파일이 이미 존재합니다.")
                    # 이전 선택으로 복원
                    self.filter_combo.blockSignals(True)
                    self.filter_combo.setCurrentText(self.filter_mode)
                    self.filter_combo.blockSignals(False)
                    return
                
                # 빈 파일 생성
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        pass
                    
                    # 콤보박스에 새 항목 추가 (+ 분류 그룹 추가 앞에)
                    display_name = filename.replace('.txt', '')
                    self.filter_combo.blockSignals(True)
                    
                    # 기존 항목들 가져오기
                    items = []
                    for i in range(self.filter_combo.count()):
                        items.append(self.filter_combo.itemText(i))
                    
                    # "+ 분류 그룹 추가" 제거
                    if "+ 분류 그룹 추가" in items:
                        items.remove("+ 분류 그룹 추가")
                    
                    # 새 항목 추가
                    items.append(display_name)
                    
                    # "+ 분류 그룹 추가" 다시 추가
                    items.append("+ 분류 그룹 추가")
                    
                    # 콤보박스 재구성
                    self.filter_combo.clear()
                    self.filter_combo.addItems(items)
                    
                    # 새로 추가된 항목 선택
                    self.filter_combo.setCurrentText(display_name)
                    self.filter_combo.blockSignals(False)
                    
                    # 필터 모드 업데이트
                    self.filter_mode = display_name
                    self._apply_filter()
                    
                    QMessageBox.information(self.widget, "성공", f"{display_name} 분류 그룹이 생성되었습니다.")
                    
                except Exception as e:
                    QMessageBox.critical(self.widget, "오류", f"파일 생성 중 오류가 발생했습니다:\n{str(e)}")
                    # 이전 선택으로 복원
                    self.filter_combo.blockSignals(True)
                    self.filter_combo.setCurrentText(self.filter_mode)
                    self.filter_combo.blockSignals(False)
            else:
                # 취소된 경우 이전 선택으로 복원
                self.filter_combo.blockSignals(True)
                self.filter_combo.setCurrentText(self.filter_mode)
                self.filter_combo.blockSignals(False)
            return
        
        self.filter_mode = filter_mode
        self._apply_filter()
    
    def _apply_filter(self):
        """현재 필터 모드에 따라 리스트 업데이트"""
        self.artist_listbox.clear()
        
        if self.filter_mode == "전체 목록 보기":
            # 제외된 작가를 제외한 전체 목록 표시
            filtered_list = [artist for artist in self.artist_list if artist not in self.banned_artists]
            self._update_listbox(filtered_list)
        
        elif self.filter_mode == "관심 작가 보기":
            # 관심 작가만 표시
            self._update_listbox(self.favorite_artists)
        
        elif self.filter_mode == "제외 작가 보기":
            # 제외된 작가만 표시
            self._update_listbox(self.banned_artists)
        
        else:
            # 사용자 정의 분류 그룹
            custom_file = os.path.join('artist_thumb', f'{self.filter_mode}.txt')
            if os.path.exists(custom_file):
                with open(custom_file, 'r', encoding='utf-8') as f:
                    custom_artists = [line.strip() for line in f if line.strip()]
                self._update_listbox(custom_artists)
    
    def _on_randomizer_toggled(self, checked: bool):
        """아티스트 랜더마이저 체크박스 토글 시"""
        # 규칙 설정 버튼은 항상 활성화 상태 유지
        
        # 랜더마이저 활성/비활성 상태를 app_context에 저장
        if hasattr(self, 'app_context') and self.app_context:
            self.app_context.artist_randomizer_enabled = checked
            print(f"🎲 Artist Randomizer: {'Enabled' if checked else 'Disabled'}")
    
    def _open_randomizer_settings(self):
        """아티스트 랜더마이저 설정 창 열기"""
        if not hasattr(self, 'randomizer_settings_window') or not self.randomizer_settings_window:
            self.randomizer_settings_window = ArtistRandomizerSettings(self.widget, self.app_context)
        self.randomizer_settings_window.show()
        self.randomizer_settings_window.raise_()
        self.randomizer_settings_window.activateWindow()
    
    def get_randomized_artist_string(self):
        """
        랜더마이저가 활성화된 경우 아티스트 문자열 생성
        
        Returns:
            tuple: (생성된 아티스트 문자열, 선택된 아티스트 리스트)
        """
        # 랜더마이저가 활성화되어 있는지 확인
        if not hasattr(self, 'randomizer_checkbox') or not self.randomizer_checkbox.isChecked():
            return "", []
        
        # app_context에서 현재 규칙 가져오기
        if not hasattr(self, 'app_context') or not self.app_context:
            return "", []
        
        rule_data = getattr(self.app_context, 'artist_randomizer_rule', None)
        if not rule_data:
            return "", []
        
        # 아티스트 목록 준비
        artist_list = self.artist_list if hasattr(self, 'artist_list') else []
        favorite_artists = self.favorite_artists if hasattr(self, 'favorite_artists') else []
        
        # 문자열과 선택된 아티스트 생성
        result_list, selected_artists = generate_artist_randomizer_string_with_selection(
            rule_data,
            artist_list,
            favorite_artists,
            anima_artist_syntax=self._uses_anima_artist_syntax(),
        )
        
        # ", "로 연결하여 반환
        return ", ".join(result_list), selected_artists

    def _current_api_mode(self) -> str:
        try:
            if self.app_context and hasattr(self.app_context, 'get_api_mode'):
                return str(self.app_context.get_api_mode() or '').upper()
            return str(getattr(self.app_context, 'current_api_mode', '') or '').upper()
        except Exception:
            return ''

    def _current_model_name(self) -> str:
        try:
            main_window = getattr(self.app_context, 'main_window', None)
            model_combo = getattr(main_window, 'model_combo', None)
            if model_combo is not None:
                return str(model_combo.currentText() or '')
        except Exception:
            pass
        return ''

    def _uses_anima_artist_syntax(self) -> bool:
        mode = self._current_api_mode()
        if mode == "WEBUI":
            return "anima" in self._current_model_name().lower()
        if mode == "COMFYUI":
            try:
                main_window = getattr(self.app_context, 'main_window', None)
                anima_radio = getattr(main_window, 'anima_radio', None)
                return bool(anima_radio and anima_radio.isChecked())
            except Exception:
                return False
        return False

    def _artist_prompt_tag_variants(self, artist_name: str) -> list[str]:
        name = str(artist_name or '').strip()
        if not name:
            return []
        escaped = name.replace('(', '\\(').replace(')', '\\)')
        return [f"artist:{name}", escaped, f"@{escaped}"]

    def _format_artist_prompt_tag(self, artist_name: str) -> str:
        name = str(artist_name or '').strip()
        if not name:
            return ''
        if self._current_api_mode() == "NAI":
            return f"artist:{name}"
        escaped = name.replace('(', '\\(').replace(')', '\\)')
        if self._uses_anima_artist_syntax():
            return f"@{escaped}"
        return escaped
