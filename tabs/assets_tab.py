import os
import json
import sys
import subprocess
import importlib.util
import threading
import time
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QTabWidget, 
    QLabel, QFrame, QTextEdit, QPushButton, QLineEdit, 
    QMessageBox, QSizePolicy, QTreeWidget, QTreeWidgetItem, QComboBox,
    QInputDialog, QMenu, QProgressDialog, QApplication
)
from PyQt6.QtGui import QPixmap, QPainter, QColor, QAction
from PyQt6.QtCore import Qt, QSize, QPoint, QThread, pyqtSignal, QTimer
from PIL import Image
from PIL.ImageQt import ImageQt

from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, CUSTOM, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


# RembgSessionManager 제거 - 일회성 subprocess 방식으로 변경


class EnvironmentChecker:
    """
    Python 환경 및 패키지 설치 환경을 확인하는 유틸리티 클래스
    """
    @staticmethod
    def is_venv_active():
        """가상환경이 활성화되어 있는지 확인"""
        return hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
    
    @staticmethod
    def get_python_info():
        """현재 Python 환경 정보 반환"""
        return {
            'executable': sys.executable,
            'version': sys.version,
            'prefix': sys.prefix,
            'base_prefix': getattr(sys, 'base_prefix', sys.prefix),
            'is_venv': EnvironmentChecker.is_venv_active()
        }
    
    @staticmethod
    def get_package_install_location():
        """패키지가 설치될 위치 확인 - 가상환경 전용"""
        import site
        try:
            # 가상환경이 활성화되어 있지 않으면 경고
            if not EnvironmentChecker.is_venv_active():
                return {
                    'error': 'NAIA는 가상환경에서만 실행되어야 합니다.',
                    'preferred_location': '가상환경이 감지되지 않음',
                    'is_venv_target': False
                }
            
            # 가상환경 site-packages 경로 확인
            site_packages = site.getsitepackages()
            
            # 가상환경 내부 site-packages 위치 결정
            if site_packages:
                preferred_location = site_packages[0]
            else:
                # Windows와 Unix 경로 구분
                lib_path = "Lib\\site-packages" if sys.platform == "win32" else "lib/site-packages"
                preferred_location = os.path.join(sys.prefix, lib_path)
            
            return {
                'site_packages': site_packages,
                'preferred_location': preferred_location,
                'is_venv_target': True,
                'venv_path': sys.prefix
            }
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def check_write_permissions():
        """패키지 설치 경로에 대한 쓰기 권한 확인"""
        import tempfile
        try:
            locations = EnvironmentChecker.get_package_install_location()
            if 'error' in locations:
                return False, locations['error']
            
            # 선호하는 설치 위치에 임시 파일 생성해서 권한 테스트
            test_location = Path(locations.get('preferred_location', ''))
            if test_location.exists():
                test_file = test_location / f"_temp_write_test_{os.getpid()}.tmp"
                try:
                    test_file.write_text("test")
                    test_file.unlink()
                    return True, "쓰기 권한 있음"
                except PermissionError:
                    return False, f"쓰기 권한 없음: {test_location}"
                except Exception as e:
                    return False, f"권한 확인 실패: {e}"
            else:
                return False, f"설치 경로 없음: {test_location}"
                
        except Exception as e:
            return False, f"권한 확인 중 오류: {e}"


class PackageInstallWorker(QThread):
    """
    백그라운드에서 패키지를 설치할 워커 클래스
    """
    progress_updated = pyqtSignal(str)  # 진행 상황 메시지
    installation_finished = pyqtSignal(bool, str)  # 성공 여부, 메시지
    
    def __init__(self, package_name, upgrade=True, parent_tab=None):
        super().__init__()
        self.package_name = package_name
        self.upgrade = upgrade
        self.parent_tab = parent_tab  # AssetsTab 인스턴스 참조
    
    def run(self):
        """간소화된 pip install 실행 (rembg[cpu] 전용)"""
        try:
            print(f"🚀 PackageInstallWorker 실행 시작: {self.package_name}")
            
            # 가상환경 확인
            venv_active = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
            if not venv_active:
                print("❌ 가상환경이 활성화되지 않음")
                self.installation_finished.emit(False, "가상환경에서만 설치 가능합니다.")
                return
            
            print(f"✅ 가상환경 확인 완료")
            self.progress_updated.emit(f"🔍 {self.package_name} 설치 시작...")
            
            # 단순한 pip install 실행
            print(f"🔧 pip 설치 명령 실행...")
            if self._install_package():
                print("✅ 설치 성공")
                self.progress_updated.emit("✅ 설치 완료")
                success_msg = f"{self.package_name} 설치가 성공적으로 완료되었습니다."
                self.installation_finished.emit(True, success_msg)
            else:
                print("❌ 설치 실패")
                error_msg = f"{self.package_name} 설치에 실패했습니다.\n\n"
                error_msg += "💡 해결 방법:\n"
                error_msg += "• Microsoft Visual C++ 재배포 패키지 설치\n"
                error_msg += "• Windows 업데이트 실행\n"
                error_msg += "• 관리자 권한으로 NAIA 실행\n"
                error_msg += "• 네트워크 연결 확인"
                self.installation_finished.emit(False, error_msg)
                
        except Exception as e:
            print(f"❌ PackageInstallWorker 예외: {e}")
            error_msg = f"{self.package_name} 설치 중 예외 발생:\n{str(e)}"
            self.installation_finished.emit(False, error_msg)
    
    def _install_package(self):
        """간소화된 패키지 설치"""
        try:
            # pip 명령 구성
            pip_cmd = [sys.executable, '-m', 'pip', 'install']
            
            if self.upgrade:
                pip_cmd.append('--upgrade')
            
            pip_cmd.append(self.package_name)
            
            print(f"🔨 실행할 명령: {' '.join(pip_cmd)}")
            self.progress_updated.emit(f"📦 설치 중: {self.package_name}")
            
            # pip 실행
            import subprocess
            print(f"📡 subprocess.run 실행 중...")
            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10분 타임아웃
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            print(f"📋 subprocess 완료 - return code: {result.returncode}")
            
            # 결과 확인
            if result.returncode == 0:
                print(f"✅ stdout: {result.stdout[-200:] if result.stdout else '(empty)'}")  # 마지막 200자만
                self.progress_updated.emit(f"✅ {self.package_name} 설치 성공")
                return True
            else:
                print(f"❌ stderr: {result.stderr}")
                print(f"❌ stdout: {result.stdout}")
                self.progress_updated.emit(f"❌ {self.package_name} 설치 실패")
                return False
                
        except subprocess.TimeoutExpired:
            print("⏰ 설치 시간 초과 (10분)")
            self.progress_updated.emit(f"⏰ {self.package_name} 설치 시간 초과")
            return False
        except Exception as e:
            print(f"💥 _install_package 예외: {e}")
            self.progress_updated.emit(f"❌ {self.package_name} 설치 중 예외: {e}")
            return False
    
    def _find_installed_package_location(self):
        """설치된 패키지의 위치 찾기"""
        try:
            import importlib.util
            spec = importlib.util.find_spec(self.package_name)
            if spec and spec.origin:
                return str(Path(spec.origin).parent)
            return None
        except Exception:
            return None
    
    def _analyze_installation_error(self, return_code, stderr_lines, stdout_lines):
        """설치 실패 원인 분석"""
        error_msg = f"{self.package_name} 설치 실패 (코드: {return_code})\n\n"
        
        # 일반적인 오류 패턴 확인
        all_output = '\n'.join(stderr_lines + stdout_lines).lower()
        
        if 'permission denied' in all_output or 'access is denied' in all_output:
            error_msg += "❌ 권한 오류: 관리자 권한이 필요하거나 파일이 사용 중일 수 있습니다.\n"
            error_msg += "해결방법: 관리자 모드로 실행하거나 다른 Python 환경을 사용해보세요."
        elif 'network' in all_output or 'connection' in all_output:
            error_msg += "❌ 네트워크 오류: 인터넷 연결을 확인해주세요.\n"
            error_msg += "해결방법: 인터넷 연결 상태를 확인하고 방화벽 설정을 검토해보세요."
        elif 'disk' in all_output or 'space' in all_output:
            error_msg += "❌ 디스크 공간 부족: 저장 공간이 부족합니다.\n"
            error_msg += "해결방법: 디스크 공간을 확보한 후 다시 시도해보세요."
        elif 'version' in all_output or 'compatibility' in all_output:
            error_msg += "❌ 호환성 문제: Python 버전 또는 의존성 충돌이 발생했습니다.\n"
            error_msg += "해결방법: Python 버전을 확인하고 다른 패키지와의 충돌을 검토해보세요."
        else:
            error_msg += "❌ 알 수 없는 오류가 발생했습니다.\n"
        
        # 상세 오류 정보 추가 (처음 5줄만)
        if stderr_lines:
            error_msg += f"\n상세 오류:\n"
            error_msg += '\n'.join(stderr_lines[:5])
            if len(stderr_lines) > 5:
                error_msg += f"\n... (총 {len(stderr_lines)}줄 중 처음 5줄)"
        
        return error_msg


class StableImageWidget(QWidget):
    """
    이미지 표시 위젯 - Storyteller에서 가져옴
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._pil_image = None  # Store PIL image for clipboard operations
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def setPixmap(self, pixmap: QPixmap):
        if pixmap and not pixmap.isNull():
            self._pixmap = pixmap
            # Convert to PIL image for clipboard operations
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
        from PyQt6.QtCore import QBuffer, QIODevice
        from PyQt6.QtGui import QImage
        import io
        
        # Convert QPixmap to QImage with RGBA format
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
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "출력 이미지가 여기에 표시됩니다...")
            return

        widget_size = self.size()
        square_size = min(widget_size.width(), widget_size.height())
        
        scaled_pixmap = self._pixmap.scaled(
            QSize(square_size, square_size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        x = (widget_size.width() - scaled_pixmap.width()) // 2
        y = (widget_size.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(x, y, scaled_pixmap)
        painter.end()
    
    def show_context_menu(self, pos: QPoint):
        """Show right-click context menu"""
        if not self._pixmap or not self._pil_image:
            return
        
        menu = QMenu(self)
        
        # Style menu with white text
        menu.setStyleSheet("""
            QMenu {
                background-color: #2b2b2b;
                color: white;
                border: 1px solid #555;
            }
            QMenu::item {
                padding: 5px 20px;
                color: white;
            }
            QMenu::item:selected {
                background-color: #4a4a4a;
            }
        """)
        
        # Copy to clipboard action (PNG only for transparency)
        copy_png_action = QAction("📋 클립보드에 복사", self)
        copy_png_action.triggered.connect(lambda: self.copy_image_to_clipboard())
        
        # Save as PNG action for better transparency support
        save_png_action = QAction("💾 PNG로 저장 (투명도 유지)", self)
        save_png_action.triggered.connect(lambda: self.save_image_as_png())
        
        menu.addAction(copy_png_action)
        menu.addSeparator()
        menu.addAction(save_png_action)
        
        menu.exec(self.mapToGlobal(pos))
    
    def copy_image_to_clipboard(self):
        """Copy image to clipboard with better compatibility"""
        if not self._pil_image:
            return
        
        import io
        from PyQt6.QtCore import QMimeData, QByteArray
        from PyQt6.QtGui import QImage
        
        try:
            # Ensure RGBA mode
            if self._pil_image.mode != 'RGBA':
                img_with_alpha = self._pil_image.convert('RGBA')
            else:
                img_with_alpha = self._pil_image
            
            # Method 1: Create QImage directly for better alpha handling
            # Convert PIL to bytes
            buf = io.BytesIO()
            img_with_alpha.save(buf, format='PNG')
            png_data = buf.getvalue()
            
            # Create QImage from PNG data (preserves alpha better)
            qimage = QImage()
            qimage.loadFromData(png_data)
            
            # Create QMimeData for multi-format clipboard
            mime_data = QMimeData()
            
            # Add as QImage (best for Qt apps and some Windows apps)
            mime_data.setImageData(qimage)
            
            # Also add raw PNG data (for web browsers and other apps)
            mime_data.setData('image/png', QByteArray(png_data))
            
            # Set to clipboard
            clipboard = QApplication.clipboard()
            clipboard.setMimeData(mime_data)
            
            print(f"✅ 이미지가 클립보드에 복사되었습니다. (PNG with transparency)")
            print(f"   - Image size: {img_with_alpha.size}")
            print(f"   - Mode: {img_with_alpha.mode}")
            print(f"   - Has transparency: {img_with_alpha.mode == 'RGBA'}")
            
            # Show status message if parent has status bar
            parent = self.parent()
            while parent:
                if hasattr(parent, 'app_context') and hasattr(parent.app_context, 'main_window'):
                    parent.app_context.main_window.status_bar.showMessage(
                        "✅ 이미지가 클립보드에 복사되었습니다. (투명도 지원)", 3000
                    )
                    break
                parent = parent.parent()
                
        except Exception as e:
            print(f"❌ 클립보드 복사 실패: {e}")
            QMessageBox.warning(self, "오류", f"클립보드 복사 실패: {e}")
    
    def save_image_as_png(self):
        """Save image as PNG file with transparency preserved"""
        if not self._pil_image:
            return
        
        from PyQt6.QtWidgets import QFileDialog
        from datetime import datetime
        
        try:
            # Ensure RGBA mode for transparency
            if self._pil_image.mode != 'RGBA':
                img_with_alpha = self._pil_image.convert('RGBA')
            else:
                img_with_alpha = self._pil_image
            
            # Generate default filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"image_{timestamp}.png"
            
            # Open save dialog
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "PNG 이미지 저장",
                default_filename,
                "PNG Images (*.png);;All Files (*.*)"
            )
            
            if file_path:
                # Save as PNG with transparency
                img_with_alpha.save(file_path, 'PNG')
                
                print(f"✅ 이미지가 저장되었습니다: {file_path}")
                print(f"   - Size: {img_with_alpha.size}")
                print(f"   - Mode: {img_with_alpha.mode} (투명도 유지)")
                
                # Show status message
                parent = self.parent()
                while parent:
                    if hasattr(parent, 'app_context') and hasattr(parent.app_context, 'main_window'):
                        parent.app_context.main_window.status_bar.showMessage(
                            f"✅ PNG 파일로 저장됨 (투명도 유지): {file_path}", 3000
                        )
                        break
                    parent = parent.parent()
                
        except Exception as e:
            print(f"❌ 이미지 저장 실패: {e}")
            QMessageBox.critical(self, "오류", f"이미지 저장 실패: {e}")


class AssetsTabModule(BaseTabModule):
    """Assets 탭 모듈"""
    
    def __init__(self):
        super().__init__()
        self.widget: AssetsTab = None
    
    def get_tab_title(self) -> str:
        return "📦 Assets"
    
    def get_tab_order(self) -> int:
        return 6  # Storyteller 다음
    
    def get_tab_type(self) -> str:
        return 'core'
    
    def create_widget(self, parent: QWidget) -> QWidget:
        if self.widget is None:
            self.widget = AssetsTab(self.app_context, parent)
        return self.widget


class AssetsTab(QWidget):
    
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.assets_base_dir = Path("tabs/assets")
        self.assets_base_dir.mkdir(parents=True, exist_ok=True)
        
        # 기본 폴더 생성
        default_folders = ["characters", "backgrounds", "items", "Preset"]
        for folder in default_folders:
            (self.assets_base_dir / folder).mkdir(exist_ok=True)
        
        # 프리셋 관련 초기화
        self.preset_dir = self.assets_base_dir / "Preset"
        self.current_preset = None
        self.loading_preset = False  # 프리셋 로딩 중 플래그
        
        self.current_image = None
        self.current_pixmap = None
        self.current_selected_image_path = None  # View 탭에서 선택된 이미지 경로
        
        # rembg 관련 초기화
        self.rembg_available = False
        self.rembg_installing = False
        self.rembg_checked = False  # 첫 번째 체크 여부
        
        # alpha matting 파라미터 (NAIA 최적화 값)
        self.alpha_matting_enabled = True
        self.alpha_matting_foreground_threshold = 282
        self.alpha_matting_background_threshold = 22
        self.alpha_matting_erode_structure_size = 10
        
        self.init_ui()
        self._initialize_default_preset()  # 기본 프리셋 초기화
        self._load_presets()  # 프리셋 초기 로드
        # rembg 체크는 버튼 첫 클릭 시에만 수행
    
    def init_ui(self):
        """메인 UI 초기화"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # 메인 스플리터 (좌우 분할)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setStyleSheet(CUSTOM.get("main_splitter", ""))
        
        # 좌측 패널 - TreeView
        left_panel = self._create_left_panel()
        
        # 우측 패널 - 탭 시스템
        right_panel = self._create_right_panel()
        
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([300, 700])
        
        main_layout.addWidget(main_splitter)
    
    def _create_left_panel(self) -> QWidget:
        """좌측 TreeView 패널 생성"""
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 헤더
        header_frame = QFrame()
        header_frame.setStyleSheet(DARK_STYLES.get('compact_card', ''))
        header_layout = QHBoxLayout(header_frame)
        
        title_label = QLabel("📁 Assets")
        title_label.setStyleSheet(f"""
            {DARK_STYLES.get('label_style', '')}
            font-size: {get_scaled_font_size(18)}px;
            font-weight: 600;
        """)
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setStyleSheet(DARK_STYLES.get('secondary_button', ''))
        refresh_btn.setFixedWidth(get_scaled_size(40))
        refresh_btn.clicked.connect(self._refresh_tree)
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(refresh_btn)
        
        # TreeWidget - 흰색 배경, 검은색 글씨
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabel("Assets")
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self._show_tree_context_menu)
        # 클릭 이벤트 연결
        self.tree_widget.itemClicked.connect(self._on_tree_item_clicked)
        self.tree_widget.setStyleSheet(f"""
            QTreeWidget {{
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QTreeWidget::item:selected {{
                background-color: #0078D4;
                color: #FFFFFF;
            }}
            QTreeWidget::item:hover {{
                background-color: #E5E5E5;
                color: #000000;
            }}
            QHeaderView::section {{
                background-color: #F0F0F0;
                color: #000000;
                padding: 5px;
                border: none;
                font-weight: bold;
            }}
        """)
        
        left_layout.addWidget(header_frame)
        left_layout.addWidget(self.tree_widget)
        
        # 초기 트리 로드
        self._load_tree()
        
        return left_widget
    
    def _create_right_panel(self) -> QWidget:
        """우측 탭 패널 생성"""
        tab_widget = QTabWidget()
        dynamic_styles = get_dynamic_styles()
        tab_widget.setStyleSheet(dynamic_styles.get('dark_tabs', DARK_STYLES.get('dark_tabs', '')))
        
        # Workshop 탭
        workshop_tab = self._create_workshop_ui()
        tab_widget.addTab(workshop_tab, "🔧 Workshop")
        
        # View 탭 - 이미지 뷰어 및 액션 버튼
        self.view_tab = self._create_view_tab()
        tab_widget.addTab(self.view_tab, "👁️ View")
        
        # Sketchbook 탭 - 다중 레이어 편집
        self.sketchbook_tab = self._create_sketchbook_tab()
        tab_widget.addTab(self.sketchbook_tab, "✏️ Sketchbook")
        
        # 탭 위젯 참조 저장 (자동 전환을 위해)
        self.tab_widget = tab_widget
        
        return tab_widget
    
    def _create_view_tab(self) -> QWidget:
        """View 탭 UI 생성 - 이미지 뷰어와 액션 버튼"""
        view_widget = QWidget()
        view_widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        main_layout = QVBoxLayout(view_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        dynamic_styles = get_dynamic_styles()
        
        # 상단: 현재 선택된 파일 경로 표시
        self.current_file_label = QLabel("이미지를 선택해주세요")
        self.current_file_label.setStyleSheet(f"""
            {dynamic_styles.get('label_style', DARK_STYLES.get('label_style', ''))}
            font-size: {get_scaled_font_size(14)}px;
            color: {DARK_COLORS['text_secondary']};
            padding: {get_scaled_size(8)}px;
        """)
        self.current_file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.current_file_label)
        
        # 중앙: 이미지 뷰어
        self.view_image_widget = StableImageWidget()
        self.view_image_widget.setMinimumHeight(400)
        main_layout.addWidget(self.view_image_widget)
        
        # 하단: 액션 버튼들
        button_layout = QHBoxLayout()
        button_layout.setSpacing(get_scaled_size(12))
        
        # Send to inpaint 버튼
        self.inpaint_btn = QPushButton("🎨 Send to inpaint")
        self.inpaint_btn.setStyleSheet(dynamic_styles.get('primary_button', DARK_STYLES.get('primary_button', '')))
        self.inpaint_btn.clicked.connect(self._send_to_inpaint)
        self.inpaint_btn.setEnabled(False)  # 이미지 선택 전까지 비활성화
        
        # Send to Sketchbook 버튼
        self.sketchbook_btn = QPushButton("✏️ Send to Sketchbook")
        self.sketchbook_btn.setStyleSheet(dynamic_styles.get('secondary_button', DARK_STYLES.get('secondary_button', '')))
        self.sketchbook_btn.clicked.connect(self._send_to_sketchbook)
        self.sketchbook_btn.setEnabled(False)  # 이미지 선택 전까지 비활성화
        
        # Add Character Prompt 버튼
        self.char_prompt_btn = QPushButton("👤 Add Character Prompt")
        self.char_prompt_btn.setStyleSheet(dynamic_styles.get('secondary_button', DARK_STYLES.get('secondary_button', '')))
        self.char_prompt_btn.clicked.connect(self._open_character_prompt_editor)
        self.char_prompt_btn.setEnabled(False)  # 이미지 선택 전까지 비활성화
        
        # Variations 콤보박스 (기본적으로 숨김)
        self.variations_combo = QComboBox()
        self.variations_combo.setMinimumWidth(get_scaled_size(150))
        self.variations_combo.setStyleSheet(dynamic_styles.get('compact_combobox', DARK_STYLES.get('compact_combobox', '')))
        self.variations_combo.currentTextChanged.connect(self._on_variation_selected)
        self.variations_combo.setVisible(False)  # 기본적으로 숨김
        self.current_variation = None  # 현재 선택된 variation 추적
        
        button_layout.addStretch()
        button_layout.addWidget(self.inpaint_btn)
        button_layout.addWidget(self.sketchbook_btn)
        button_layout.addWidget(self.char_prompt_btn)
        button_layout.addWidget(self.variations_combo)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        
        return view_widget
    
    def _create_sketchbook_tab(self) -> QWidget:
        """Sketchbook 탭 UI 생성 - 다중 레이어 이미지 편집"""
        try:
            # 지연 import로 순환 참조 방지
            from tabs.assets.sketchbook import SketchbookWidget
            
            self.sketchbook_widget = SketchbookWidget(self.app_context)
            return self.sketchbook_widget
            
        except Exception as e:
            print(f"❌ Sketchbook 탭 생성 실패: {e}")
            
            # 오류 시 플레이스홀더 반환
            error_widget = QWidget()
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"❌ Sketchbook 로드 실패\n\n{str(e)}")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet(f"""
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(16)}px;
            """)
            error_layout.addWidget(error_label)
            return error_widget
    
    def _create_workshop_ui(self) -> QWidget:
        """Workshop UI 생성"""
        workshop_widget = QWidget()
        workshop_widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        main_layout = QVBoxLayout(workshop_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        
        # 메인 스플리터 (좌우 분할)
        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.setStyleSheet(CUSTOM.get("main_splitter", ""))
        
        # 좌측: 입력 패널
        left_panel = self._create_input_panel()
        
        # 우측: 출력 패널
        self.output_image_widget = StableImageWidget()
        
        h_splitter.addWidget(left_panel)
        h_splitter.addWidget(self.output_image_widget)
        h_splitter.setSizes([400, 600])
        
        main_layout.addWidget(h_splitter)
        
        return workshop_widget
    
    def _create_input_panel(self) -> QWidget:
        """입력 패널 생성"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(get_scaled_size(8))
        
        dynamic_styles = get_dynamic_styles()
        
        # Positive Prompt
        pos_label = QLabel("Positive Prompt")
        pos_label.setStyleSheet(dynamic_styles.get('label_style', DARK_STYLES.get('label_style', '')))
        
        self.positive_prompt = QTextEdit()
        self.positive_prompt.setPlaceholderText("Positive prompt 입력...")
        self.positive_prompt.setStyleSheet(dynamic_styles.get('compact_textedit', DARK_STYLES.get('compact_textedit', '')))
        self.positive_prompt.setMinimumHeight(get_scaled_size(60))
        # Removed maximum height to allow resizing
        
        # Negative Prompt
        neg_label = QLabel("Negative Prompt")
        neg_label.setStyleSheet(dynamic_styles.get('label_style', DARK_STYLES.get('label_style', '')))
        
        self.negative_prompt = QTextEdit()
        self.negative_prompt.setPlaceholderText("Negative prompt 입력...")
        self.negative_prompt.setStyleSheet(dynamic_styles.get('compact_textedit', DARK_STYLES.get('compact_textedit', '')))
        self.negative_prompt.setMinimumHeight(get_scaled_size(60))
        # Removed maximum height to allow resizing
        
        # 해상도 선택
        resolution_label = QLabel("해상도 (오버라이드)")
        resolution_label.setStyleSheet(dynamic_styles.get('label_style', DARK_STYLES.get('label_style', '')))
        
        self.resolution_combo = QComboBox()
        self.resolution_combo.setStyleSheet(dynamic_styles.get('compact_combobox', DARK_STYLES.get('compact_combobox', '')))
        
        resolutions = [
            "1024 x 1024", "768 x 1344", "704 x 1472",  # 기본값
            "--- High Resolution ---",
            "1472 x 1472", "1088 x 1920", "1280 x 1664", "1344 x 1536",
            "1536 x 1344", "1664 x 1280", "1920 x 1088",
            "--- Medium Resolution ---",
            "1216 x 1216", "1024 x 1536", "1536 x 1024",
            "--- Standard Resolution ---",
            "960 x 1088", "896 x 1152", "832 x 1216",
            "1088 x 960", "1152 x 896", "1216 x 832"
        ]
        
        for res in resolutions:
            if res.startswith("---"):
                # 구분선은 비활성화
                self.resolution_combo.addItem(res)
                index = self.resolution_combo.count() - 1
                self.resolution_combo.model().item(index).setEnabled(False)
            else:
                self.resolution_combo.addItem(res)
        
        self.resolution_combo.setCurrentText("1024 x 1024")
        
        # Generate 버튼
        self.generate_btn = QPushButton("🎨 Generate")
        self.generate_btn.setStyleSheet(dynamic_styles.get('primary_button', DARK_STYLES.get('primary_button', '')))
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        
        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        
        # 저장 영역
        save_label = QLabel("💾 이미지 저장")
        save_label.setStyleSheet(f"""
            {dynamic_styles.get('label_style', DARK_STYLES.get('label_style', ''))}
            font-weight: bold;
        """)
        
        # 저장 경로 선택
        path_label = QLabel("저장 폴더")
        path_label.setStyleSheet(dynamic_styles.get('label_style', DARK_STYLES.get('label_style', '')))
        
        self.save_path_combo = QComboBox()
        self.save_path_combo.setStyleSheet(dynamic_styles.get('compact_combobox', DARK_STYLES.get('compact_combobox', '')))
        self._update_save_paths()
        
        # 파일명 입력
        filename_label = QLabel("파일명")
        filename_label.setStyleSheet(dynamic_styles.get('label_style', DARK_STYLES.get('label_style', '')))
        
        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText("파일명 입력 (확장자 제외)")
        self.filename_input.setStyleSheet(dynamic_styles.get('compact_lineedit', DARK_STYLES.get('compact_lineedit', '')))
        
        # 저장 버튼
        self.save_btn = QPushButton("💾 이미지 저장")
        self.save_btn.setStyleSheet(dynamic_styles.get('secondary_button', DARK_STYLES.get('secondary_button', '')))
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.save_btn.setEnabled(False)  # 초기에는 비활성화
        
        # 배경 제거 버튼
        self.remove_bg_btn = QPushButton("🗑️ 배경 제거")
        self.remove_bg_btn.setStyleSheet(dynamic_styles.get('secondary_button', DARK_STYLES.get('secondary_button', '')))
        self.remove_bg_btn.clicked.connect(self._on_remove_background_clicked)
        self.remove_bg_btn.setEnabled(True)  # 첫 클릭으로 체크 가능
        self.remove_bg_btn.setToolTip("배경 제거 기능 - 첫 클릭 시 패키지 상태를 확인합니다")
        
        # 구분선
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        
        # 프리셋 영역
        preset_label = QLabel("📋 프롬프트 프리셋")
        preset_label.setStyleSheet(f"""
            {dynamic_styles.get('label_style', DARK_STYLES.get('label_style', ''))}
            font-weight: bold;
        """)
        
        # 프리셋 콤보박스
        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet(dynamic_styles.get('compact_combobox', DARK_STYLES.get('compact_combobox', '')))
        self.preset_combo.setEditable(True)  # 새 프리셋 이름 입력 가능
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        
        # 프리셋 버튼들
        preset_btn_layout = QHBoxLayout()
        
        self.save_preset_btn = QPushButton("💾 저장")
        self.save_preset_btn.setStyleSheet(dynamic_styles.get('compact_button', DARK_STYLES.get('compact_button', '')))
        self.save_preset_btn.clicked.connect(self._save_preset)
        
        self.delete_preset_btn = QPushButton("🗑️ 삭제")
        self.delete_preset_btn.setStyleSheet(dynamic_styles.get('compact_button', DARK_STYLES.get('compact_button', '')))
        self.delete_preset_btn.clicked.connect(self._delete_preset)
        
        preset_btn_layout.addWidget(self.save_preset_btn)
        preset_btn_layout.addWidget(self.delete_preset_btn)
        
        # 프롬프트용 수직 Splitter 생성
        prompt_splitter = QSplitter(Qt.Orientation.Vertical)
        prompt_splitter.setChildrenCollapsible(False)
        
        # Positive prompt 위젯 그룹
        pos_widget = QWidget()
        pos_layout = QVBoxLayout(pos_widget)
        pos_layout.setContentsMargins(0, 0, 0, 0)
        pos_layout.setSpacing(2)
        pos_layout.addWidget(pos_label)
        pos_layout.addWidget(self.positive_prompt)
        
        # Negative prompt 위젯 그룹
        neg_widget = QWidget()
        neg_layout = QVBoxLayout(neg_widget)
        neg_layout.setContentsMargins(0, 0, 0, 0)
        neg_layout.setSpacing(2)
        neg_layout.addWidget(neg_label)
        neg_layout.addWidget(self.negative_prompt)
        
        # Splitter에 추가
        prompt_splitter.addWidget(pos_widget)
        prompt_splitter.addWidget(neg_widget)
        
        # 초기 비율 설정 (60:40)
        prompt_splitter.setSizes([200, 150])
        
        # 레이아웃 구성
        layout.addWidget(prompt_splitter)
        layout.addWidget(resolution_label)
        layout.addWidget(self.resolution_combo)
        layout.addWidget(self.generate_btn)
        layout.addWidget(separator)
        layout.addWidget(save_label)
        layout.addWidget(path_label)
        layout.addWidget(self.save_path_combo)
        layout.addWidget(filename_label)
        layout.addWidget(self.filename_input)
        
        # 저장 버튼 레이아웃
        save_buttons_layout = QHBoxLayout()
        save_buttons_layout.addWidget(self.save_btn)
        save_buttons_layout.addWidget(self.remove_bg_btn)
        layout.addLayout(save_buttons_layout)
        
        # Alpha Matting UI 제거 - 고정값 사용
        layout.addWidget(separator2)
        layout.addWidget(preset_label)
        layout.addWidget(self.preset_combo)
        layout.addLayout(preset_btn_layout)
        layout.addStretch()
        
        return panel
    
    def _load_tree(self):
        """TreeWidget에 폴더/파일 구조 로드"""
        self.tree_widget.clear()
        
        # 루트 아이템
        root_item = QTreeWidgetItem(self.tree_widget)
        root_item.setText(0, "📦 Assets")
        root_item.setExpanded(True)
        
        # assets 폴더 탐색
        self._populate_tree_item(root_item, self.assets_base_dir)
    
    def _populate_tree_item(self, parent_item: QTreeWidgetItem, path: Path):
        """재귀적으로 트리 아이템 채우기"""
        try:
            for item_path in sorted(path.iterdir()):
                if item_path.name.startswith('.'):
                    continue
                # Preset 폴더는 표시하지 않음
                if item_path.name == 'Preset' and item_path.is_dir():
                    continue
                if item_path.name == 'sketchbook' and item_path.is_dir():
                    continue
                if item_path.name == '__pycache__' and item_path.is_dir():
                    continue
                # JSON 파일은 표시하지 않음 (character prompt 파일들)
                if item_path.suffix.lower() == '.json':
                    continue
                if item_path.suffix.lower() == '.py':
                    continue
                # _variations 폴더는 표시하지 않음 (variation 이미지들)
                if item_path.is_dir() and '_variations' in item_path.name:
                    continue
                    
                tree_item = QTreeWidgetItem(parent_item)
                
                if item_path.is_dir():
                    tree_item.setText(0, f"📁 {item_path.name}")
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, str(item_path))
                    self._populate_tree_item(tree_item, item_path)
                elif item_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp']:
                    tree_item.setText(0, f"🖼️ {item_path.name}")
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, str(item_path))
        except Exception as e:
            print(f"트리 로드 오류: {e}")
    
    def _refresh_tree(self):
        """트리 새로고침"""
        self._load_tree()
        self._update_save_paths()
    
    def _update_save_paths(self):
        """저장 경로 ComboBox 업데이트"""
        self.save_path_combo.clear()
        
        # assets 하위 폴더들 찾기
        for folder in sorted(self.assets_base_dir.iterdir()):
            if folder.name == 'Preset' and folder.is_dir():
                continue
            if folder.name == '__pycache__' and folder.is_dir():
                continue
            if folder.is_dir() and not folder.name.startswith('.'):
                self.save_path_combo.addItem(folder.name)
    
    def _on_generate_clicked(self):
        """Generate 버튼 클릭 처리 - execute_generation_pipeline 사용"""
        try:
            # 프롬프트 가져오기
            positive = self.positive_prompt.toPlainText().strip()
            negative = self.negative_prompt.toPlainText().strip()
            
            if not positive:
                QMessageBox.warning(self, "경고", "Positive prompt를 입력해주세요.")
                return
            
            # 해상도 파싱
            resolution_text = self.resolution_combo.currentText()
            if " x " in resolution_text:
                width, height = resolution_text.split(" x ")
                width = int(width.strip())
                height = int(height.strip())
            else:
                width, height = 1024, 1024
            
            # 오버라이드 파라미터 준비 (Assets Workshop 전용 식별자 추가)
            override_params = {
                'input': positive,
                'negative_prompt': negative,
                'width': width,
                'height': height,
                'random_resolution': False,
                'assets_workshop_request': True  # Assets Workshop에서의 생성 요청 식별자
            }
            
            # 자동 생성 체크박스 해제 (필요한 경우)
            if hasattr(self.app_context, 'main_window'):
                auto_generate_checkbox = self.app_context.main_window.generation_checkboxes.get("자동 생성")
                if auto_generate_checkbox and auto_generate_checkbox.isChecked():
                    auto_generate_checkbox.setChecked(False)
            
            # Assets Workshop 전용 생성 완료 이벤트 구독
            self.app_context.subscribe("generation_completed_for_assets", self._on_generation_completed)
            
            # Generate 버튼 비활성화
            self.generate_btn.setEnabled(False)
            self.generate_btn.setText("🔄 생성 중...")
            
            # generation_controller의 execute_generation_pipeline 호출
            if hasattr(self.app_context, 'main_window'):
                gen_controller = self.app_context.main_window.generation_controller
                gen_controller.execute_generation_pipeline(overrides=override_params)
                print(f"🎨 Assets Workshop: 이미지 생성 시작 (해상도: {width}x{height})")
            else:
                print("⚠️ generation_controller를 찾을 수 없습니다.")
                # 오류 발생 시 버튼 복원
                self._restore_generate_button()
                
        except Exception as e:
            # 예외 발생 시 버튼 복원
            self._restore_generate_button()
            QMessageBox.critical(self, "오류", f"이미지 생성 중 오류 발생:\n{str(e)}")
    
    def _restore_generate_button(self):
        """Generate 버튼을 원래 상태로 복원"""
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("🎨 Generate")
    
    def _on_save_clicked(self):
        """저장 버튼 클릭 처리"""
        try:
            # 파일명 확인
            filename = self.filename_input.text().strip()
            if not filename:
                QMessageBox.warning(self, "경고", "파일명을 입력해주세요.")
                return
            
            # 저장 경로 확인
            folder_name = self.save_path_combo.currentText()
            if not folder_name:
                QMessageBox.warning(self, "경고", "저장 폴더를 선택해주세요.")
                return
            
            save_dir = self.assets_base_dir / folder_name
            save_dir.mkdir(exist_ok=True)
            
            # 파일 경로 생성
            save_path = save_dir / f"{filename}.png"
            
            # 덮어쓰기 확인
            if save_path.exists():
                reply = QMessageBox.question(
                    self, "확인",
                    f"'{filename}.png' 파일이 이미 존재합니다.\n덮어쓰시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            # 이미지 저장
            if self.current_image:
                self.current_image.save(str(save_path), "PNG")
                QMessageBox.information(self, "성공", f"이미지가 저장되었습니다:\n{save_path}")
                
                # 트리 새로고침
                self._refresh_tree()
                
                # 입력 필드 초기화
                self.filename_input.clear()
            else:
                QMessageBox.warning(self, "경고", "저장할 이미지가 없습니다.")
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"이미지 저장 중 오류 발생:\n{str(e)}")
    
    def update_generated_image(self, image):
        """생성된 이미지 업데이트 - WEBP → PNG 변환 포함"""
        try:
            if not image:
                self.current_image = None
                self.current_pixmap = None
                self.output_image_widget.setPixmap(None)
                self.save_btn.setEnabled(False)
                self.remove_bg_btn.setEnabled(False)
                return
            
            # PIL Image인지 확인
            if not hasattr(image, 'mode'):
                print(f"❌ 지원되지 않는 이미지 타입: {type(image)}")
                return
            
            # WEBP 이미지인 경우 PNG로 변환 (image_window와 동일한 처리)
            if hasattr(image, 'format') and image.format == 'WEBP':
                print("🔄 Assets Workshop: WEBP 이미지를 PNG로 변환 중...")
                
                import io
                png_buffer = io.BytesIO()
                
                try:
                    # RGBA 모드로 변환하여 투명도 정보 보존
                    if image.mode != 'RGBA':
                        image = image.convert('RGBA')
                    
                    # PNG로 저장하며 모든 비표준 메타데이터를 제거
                    image.save(png_buffer, format='PNG')
                    png_buffer.seek(0)
                    
                    # 정제된 PNG 데이터로부터 새로운 PIL Image 객체 생성
                    image = Image.open(png_buffer)
                    
                    # 이미지 로드 후 buffer를 안전하게 보관 (image가 buffer를 참조하므로)
                    # buffer 닫기는 image 사용이 완전히 끝난 후에 수행
                    image.load()  # 이미지 데이터를 메모리로 강제 로드
                    png_buffer.close()
                    
                    print("✅ Assets Workshop: WEBP → PNG 변환 완료")
                except Exception as e:
                    print(f"⚠️ WEBP 변환 중 오류: {e}")
                    try:
                        png_buffer.close()
                    except:
                        pass
                    # 변환 실패 시 원본 이미지 사용
            
            # Store PIL image and convert to pixmap
            self.current_image = image
            
            # Use setPilImage to properly store both PIL and QPixmap
            self.output_image_widget.setPilImage(image)
            
            # Also get the pixmap for backward compatibility
            q_image = ImageQt(image)
            pixmap = QPixmap.fromImage(q_image)
            
            if not pixmap.isNull():
                self.current_pixmap = pixmap
                self.save_btn.setEnabled(True)
                
                # rembg가 사용 가능하면 배경 제거 버튼도 활성화
                if self.rembg_available:
                    self.remove_bg_btn.setEnabled(True)
                print("✅ Assets Workshop: 이미지 표시 완료")
            else:
                print("❌ QPixmap 변환 실패")
                
        except Exception as e:
            print(f"❌ 이미지 업데이트 오류: {e}")
    
    def _on_generation_completed(self, result):
        """이미지 생성 완료 콜백"""
        try:
            # Assets Workshop 전용 구독 해제
            self.app_context.subscribers["generation_completed_for_assets"].remove(self._on_generation_completed)
            
            # Storyteller 방식과 동일하게 처리 - result 자체가 이미지
            image_object = result
            if hasattr(image_object, 'mode'):  # PIL Image 확인
                self.update_generated_image(image_object)
                print("✅ Assets Workshop: 이미지 생성 완료")
                
                # Generate 버튼 복원
                self._restore_generate_button()
                
                # 상태바 메시지
                if hasattr(self.app_context, 'main_window'):
                    self.app_context.main_window.status_bar.showMessage(
                        "✅ Assets Workshop: 이미지 생성 완료", 3000
                    )
            else:
                print(f"⚠️ 예상과 다른 결과 타입: {type(result)}")
                self._restore_generate_button()  # 오류 시에도 버튼 복원
                
        except Exception as e:
            print(f"❌ 생성 완료 처리 중 오류: {e}")
            print(f"결과 타입: {type(result)}")
            self._restore_generate_button()  # 예외 시에도 버튼 복원
    
    # =================== 프리셋 관련 메서드 ===================
    
    def _load_presets(self):
        """프리셋 디렉토리에서 모든 프리셋 로드"""
        self.preset_combo.clear()
        self.preset_combo.addItem("-- 새 프리셋 --")
        
        try:
            preset_files = sorted(self.preset_dir.glob("*.json"))
            default_index = -1
            for i, preset_file in enumerate(preset_files):
                preset_name = preset_file.stem
                self.preset_combo.addItem(preset_name)
                if preset_name == "Default":
                    default_index = i + 1  # +1 범위 "-- 새 프리셋 --" 때문에
            
            # Default 프리셋이 있으면 선택
            if default_index >= 0:
                self.preset_combo.setCurrentIndex(default_index)
                self.current_preset = "Default"
                self._load_preset("Default")
        except Exception as e:
            print(f"프리셋 로드 오류: {e}")
    
    def _on_preset_changed(self, preset_name: str):
        """프리셋 변경 시 처리"""
        if self.loading_preset:  # 로딩 중에는 무시
            return
            
        # 현재 프리셋 자동 저장 (변경 전)
        if self.current_preset and self.current_preset != "-- 새 프리셋 --":
            self._auto_save_current_preset()
        
        # 새 프리셋 로드
        if preset_name and preset_name != "-- 새 프리셋 --":
            self._load_preset(preset_name)
        else:
            # 새 프리셋 선택 시 프롬프트 초기화
            self.positive_prompt.clear()
            self.negative_prompt.clear()
        
        self.current_preset = preset_name
    
    def _auto_save_current_preset(self):
        """현재 프리셋 자동 저장"""
        if not self.current_preset or self.current_preset == "-- 새 프리셋 --":
            return
            
        try:
            preset_data = {
                "positive": self.positive_prompt.toPlainText(),
                "negative": self.negative_prompt.toPlainText()
            }
            
            preset_path = self.preset_dir / f"{self.current_preset}.json"
            with open(preset_path, 'w', encoding='utf-8') as f:
                json.dump(preset_data, f, ensure_ascii=False, indent=2)
            print(f"프리셋 자동 저장됨: {self.current_preset}")
        except Exception as e:
            print(f"프리셋 자동 저장 오류: {e}")
    
    def _load_preset(self, preset_name: str):
        """프리셋 로드"""
        try:
            preset_path = self.preset_dir / f"{preset_name}.json"
            if not preset_path.exists():
                return
                
            self.loading_preset = True  # 로딩 플래그 설정
            
            with open(preset_path, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)
            
            self.positive_prompt.setPlainText(preset_data.get("positive", ""))
            self.negative_prompt.setPlainText(preset_data.get("negative", ""))
            
            print(f"프리셋 로드됨: {preset_name}")
            
        except Exception as e:
            QMessageBox.warning(self, "오류", f"프리셋 로드 실패:\n{str(e)}")
        finally:
            self.loading_preset = False  # 로딩 플래그 해제
    
    def _save_preset(self):
        """현재 프롬프트를 프리셋으로 저장"""
        preset_name = self.preset_combo.currentText()
        
        if not preset_name or preset_name == "-- 새 프리셋 --":
            # 새 프리셋 이름 입력
            from PyQt6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(
                self, "프리셋 저장", "프리셋 이름을 입력하세요:"
            )
            if not ok or not name:
                return
            preset_name = name
        
        try:
            preset_data = {
                "positive": self.positive_prompt.toPlainText(),
                "negative": self.negative_prompt.toPlainText()
            }
            
            preset_path = self.preset_dir / f"{preset_name}.json"
            
            # 덮어쓰기 확인
            if preset_path.exists():
                reply = QMessageBox.question(
                    self, "확인",
                    f"'{preset_name}' 프리셋이 이미 존재합니다.\n덮어쓰시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            with open(preset_path, 'w', encoding='utf-8') as f:
                json.dump(preset_data, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(self, "성공", f"프리셋이 저장되었습니다: {preset_name}")
            
            # 콤보박스 업데이트
            if preset_name not in [self.preset_combo.itemText(i) for i in range(self.preset_combo.count())]:
                self.preset_combo.addItem(preset_name)
            self.preset_combo.setCurrentText(preset_name)
            self.current_preset = preset_name
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"프리셋 저장 실패:\n{str(e)}")
    
    def _delete_preset(self):
        """현재 선택된 프리셋 삭제"""
        preset_name = self.preset_combo.currentText()
        
        if not preset_name or preset_name == "-- 새 프리셋 --":
            QMessageBox.warning(self, "경고", "삭제할 프리셋을 선택하세요.")
            return
        
        reply = QMessageBox.question(
            self, "확인",
            f"'{preset_name}' 프리셋을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            preset_path = self.preset_dir / f"{preset_name}.json"
            if preset_path.exists():
                preset_path.unlink()
            
            # 콤보박스에서 제거
            index = self.preset_combo.findText(preset_name)
            if index >= 0:
                self.preset_combo.removeItem(index)
            
            # 첫 번째 항목(새 프리셋)으로 이동
            self.preset_combo.setCurrentIndex(0)
            self.current_preset = None
            
            QMessageBox.information(self, "성공", f"프리셋이 삭제되었습니다: {preset_name}")
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"프리셋 삭제 실패:\n{str(e)}")
    
    def _initialize_default_preset(self):
        """Default.json 프리셋 초기화 - 없으면 메인 윈도우에서 가져오기"""
        default_preset_path = self.preset_dir / "Default.json"
        
        if not default_preset_path.exists():
            try:
                # 메인 윈도우에서 현재 프롬프트 가져오기
                positive = ""
                negative = ""
                
                if hasattr(self.app_context, 'main_window'):
                    main_window = self.app_context.main_window
                    
                    # Positive prompt 가져오기
                    if hasattr(main_window, 'positive_prompt_input'):
                        positive = main_window.positive_prompt_input.toPlainText()
                    
                    # Negative prompt 가져오기
                    if hasattr(main_window, 'negative_prompt_input'):
                        negative = main_window.negative_prompt_input.toPlainText()
                
                # Default.json 생성
                default_data = {
                    "positive": positive,
                    "negative": negative
                }
                
                with open(default_preset_path, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, ensure_ascii=False, indent=2)
                
                print("Default.json 프리셋이 생성되었습니다.")
                
            except Exception as e:
                print(f"Default.json 생성 중 오류: {e}")
    
    def _show_tree_context_menu(self, position: QPoint):
        """TreeWidget 우클릭 컨텍스트 메뉴"""
        item = self.tree_widget.itemAt(position)
        if not item:
            return
        
        # 선택된 아이템의 경로 가져오기
        path_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_data:
            return
        
        item_path = Path(path_data)
        if not item_path:
            return
        
        # 컨텍스트 메뉴 생성
        menu = QMenu(self.tree_widget)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: 2px;
            }}
            QMenu::item:selected {{
                background-color: #0078D4;
                color: #FFFFFF;
            }}
        """)
        
        # 삭제 액션 추가
        delete_action = QAction("🗑️ 삭제", self.tree_widget)
        delete_action.triggered.connect(lambda: self._delete_tree_item(item_path, item))
        menu.addAction(delete_action)
        
        # 폴더인 경우 추가 옵션
        if item_path.is_dir():
            menu.addSeparator()
            open_folder_action = QAction("📂 폴더 열기", self.tree_widget)
            open_folder_action.triggered.connect(lambda: self._open_folder(item_path))
            menu.addAction(open_folder_action)
        
        # 메뉴 표시
        global_pos = self.tree_widget.mapToGlobal(position)
        menu.exec(global_pos)
    
    def _delete_tree_item(self, item_path: Path, tree_item: QTreeWidgetItem):
        """트리 아이템 삭제"""
        # 삭제 확인
        item_name = item_path.name
        if item_path.is_dir():
            msg = f"'{item_name}' 폴더와 모든 내용을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다."
        else:
            msg = f"'{item_name}' 파일을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다."
        
        reply = QMessageBox.question(
            self, "삭제 확인", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            # 파일/폴더 삭제
            if item_path.is_dir():
                import shutil
                shutil.rmtree(item_path)
                print(f"폴더 삭제됨: {item_path}")
            else:
                item_path.unlink()
                print(f"파일 삭제됨: {item_path}")
            
            # 트리에서 아이템 제거
            parent = tree_item.parent()
            if parent:
                parent.removeChild(tree_item)
            else:
                index = self.tree_widget.indexOfTopLevelItem(tree_item)
                if index >= 0:
                    self.tree_widget.takeTopLevelItem(index)
            
            # 저장 경로 콤보박스 업데이트 (폴더가 삭제된 경우)
            if item_path.is_dir():
                self._update_save_paths()
            
            QMessageBox.information(self, "성공", f"'{item_name}'이(가) 삭제되었습니다.")
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"삭제 실패:\n{str(e)}")
    
    def _open_folder(self, folder_path: Path):
        """탐색기에서 폴더 열기"""
        try:
            import os
            import subprocess
            import platform
            
            if platform.system() == 'Windows':
                os.startfile(str(folder_path))
            elif platform.system() == 'Darwin':  # macOS
                subprocess.Popen(['open', str(folder_path)])
            else:  # Linux
                subprocess.Popen(['xdg-open', str(folder_path)])
        except Exception as e:
            print(f"폴더 열기 실패: {e}")
    
    # =================== rembg 관련 메서드 ===================
    
    # Alpha Matting 파라미터는 고정값 사용 (UI 제거됨)
    
    
    # 일회성 subprocess 방식으로 변경 - 세션 관리 불필요

    def _check_rembg_availability(self, force_reload=False):
        """rembg 설치 여부 확인 (PyQt DLL 충돌 회피)"""
        try:
            if force_reload:
                # rembg 모듈 캐시 정리
                import site
                import importlib
                
                modules_to_remove = [k for k in sys.modules.keys() if 'rembg' in k]
                for module in modules_to_remove:
                    del sys.modules[module]
                
                site.main()
                importlib.invalidate_caches()
                print("🔄 rembg 모듈 캐시 정리 완료")
            
            # PyQt 환경에서 DLL 충돌 회피를 위한 별도 프로세스 테스트
            if self._test_rembg_in_clean_environment():
                self.rembg_available = True
                self.remove_bg_btn.setEnabled(self.current_image is not None)
                self.remove_bg_btn.setToolTip("배경을 제거하여 투명한 배경으로 만듭니다 (isnet-anime 모델)")
                print("✅ rembg 사용 가능 (별도 프로세스에서 확인)")
                return True
            else:
                print("❌ rembg 사용 불가")
                self.rembg_available = False
                self.remove_bg_btn.setEnabled(True)
                self.remove_bg_btn.setToolTip("❌ rembg 패키지가 필요합니다. 클릭하여 설치하세요.")
                return False
                
        except Exception as e:
            print(f"⚠️ rembg 확인 오류: {e}")
            self.rembg_available = False
            self.remove_bg_btn.setEnabled(True)
            self.remove_bg_btn.setToolTip("❌ rembg 패키지가 필요합니다. 클릭하여 설치하세요.")
            return False
    
    def _test_rembg_in_clean_environment(self):
        """별도 Python 프로세스에서 rembg 테스트 (DLL 충돌 회피)"""
        try:
            import subprocess
            
            # 간단한 rembg remove, new_session import 테스트 스크립트
            test_script = """
try:
    from rembg import remove, new_session
    print("REMBG_AVAILABLE")
except ImportError as e:
    print(f"REMBG_IMPORT_ERROR: {e}")
except Exception as e:
    print(f"REMBG_ERROR: {e}")
"""
            
            # 현재 가상환경의 Python 실행파일로 테스트
            result = subprocess.run(
                [sys.executable, '-c', test_script],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            # 결과 확인
            if "REMBG_AVAILABLE" in result.stdout:
                print("🎉 별도 프로세스에서 rembg 확인 성공")
                return True
            else:
                print(f"❌ 별도 프로세스에서 rembg 테스트 실패:")
                print(f"   stdout: {result.stdout}")
                print(f"   stderr: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("⏰ rembg 테스트 시간 초과")
            return False
        except Exception as e:
            print(f"💥 별도 프로세스 테스트 중 오류: {e}")
            return False
    
    def _on_remove_background_clicked(self):
        """
        배경 제거 버튼 클릭 처리 - 첫 클릭 시 패키지 체크
        """
        if self.rembg_installing:
            QMessageBox.information(self, "알림", "rembg 패키지 설치가 진행 중입니다. 잠시 기다려주세요.")
            return
        
        # 첫 번째 체크가 아직 안 되었다면 수행
        if not self.rembg_checked:
            self.rembg_checked = True
            self.remove_bg_btn.setText("🔄 확인 중...")
            self.remove_bg_btn.setEnabled(False)
            
            # 지연 체크 (UI가 업데이트될 시간을 줌)
            QTimer.singleShot(100, self._perform_delayed_rembg_check)
            return
        
        if not self.rembg_available:
            # rembg가 없다면 설치 안내
            self._show_rembg_install_dialog()
            return
        
        if not self.current_image:
            QMessageBox.warning(self, "경고", "배경을 제거할 이미지가 없습니다.")
            return
        
        try:
            # 배경 제거 실행
            self._remove_background_from_image()
        except Exception as e:
            QMessageBox.critical(self, "오류", f"배경 제거 중 오류 발생:\n{str(e)}")
    
    def _perform_delayed_rembg_check(self):
        """지연된 rembg 패키지 체크 수행"""
        try:
            if self._check_rembg_availability(force_reload=False):
                # 패키지 사용 가능
                self.remove_bg_btn.setText("🗑️ 배경 제거")
                self.remove_bg_btn.setEnabled(self.current_image is not None)
                print("✅ rembg 첫 체크 완료 - 사용 가능")
            else:
                # 패키지 없음 - 설치 필요
                self.remove_bg_btn.setText("📦 설치 필요")
                self.remove_bg_btn.setEnabled(True)
                self.remove_bg_btn.setToolTip("❌ rembg 패키지가 필요합니다. 클릭하여 설치하세요.")
                print("❌ rembg 첫 체크 완료 - 설치 필요")
        except Exception as e:
            # 체크 실패
            self.remove_bg_btn.setText("⚠️ 확인 실패")
            self.remove_bg_btn.setEnabled(True)
            self.remove_bg_btn.setToolTip(f"패키지 확인 실패: {e}")
            print(f"⚠️ rembg 첫 체크 실패: {e}")
    
    def _show_rembg_install_dialog(self):
        """rembg 설치 안내 다이얼로그 표시"""
        # 가상환경 확인
        venv_active = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
        if not venv_active:
            QMessageBox.critical(self, "환경 오류", 
                "NAIA는 가상환경에서만 실행되어야 합니다.\n"
                "가상환경을 활성화한 후 다시 실행해주세요.")
            return
            
        # 간소화된 설치 안내
        env_text = f"""rembg는 AI 기반 배경 제거 도구입니다.
Python {sys.version_info.major}.{sys.version_info.minor} 환경에서 다음이 설치됩니다:

• rembg[cpu] (CPU 최적화 버전, 의존성 자동 포함)

설치는 2-3분 정도 소요될 수 있습니다.
자동으로 설치하시겠습니까?

💡 참고:
• CPU 전용 버전으로 모든 의존성이 자동 설치됩니다
• Visual C++ 재배포 패키지가 필요할 수 있습니다"""
        
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("rembg 패키지 설치")
        msg.setText("배경 제거 기능을 위해 'rembg[cpu]' 패키지 설치가 필요합니다.")
        msg.setInformativeText(env_text)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)
        
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._start_rembg_installation()
    
    # DLL 진단 다이얼로그 제거됨 - 단순화
    
    def _start_rembg_installation(self):
        """rembg[cpu] 패키지 설치 시작"""
        if self.rembg_installing:
            return
        
        self.rembg_installing = True
        
        # 진행도 다이얼로그 생성
        self.progress_dialog = QProgressDialog(
            "rembg[cpu] 패키지를 설치하고 있습니다...",
            "취소", 0, 0, self
        )
        self.progress_dialog.setWindowTitle("rembg 설치")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.show()
        
        # 취소 단추 비활성화 (강제 종료 방지)
        self.progress_dialog.setCancelButton(None)
        
        # 간소화된 설치: rembg[cpu]만 설치 (의존성 자동 처리)
        print("🔍 rembg[cpu] 설치 시작 (의존성 자동 포함)")
        self.install_worker = PackageInstallWorker("rembg[cpu]", upgrade=True, parent_tab=self)
        self.install_worker.progress_updated.connect(self._on_install_progress)
        self.install_worker.installation_finished.connect(self._on_install_finished)
        self.install_worker.start()
        
        # 버튼 상태 변경
        self.remove_bg_btn.setText("🔄 설치 중...")
        self.remove_bg_btn.setEnabled(False)
    
    def _on_install_progress(self, message: str):
        """
        설치 진행 상황 업데이트
        """
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.setLabelText(message)
        QApplication.processEvents()  # UI 업데이트 강제 수행
    
    def _on_install_finished(self, success: bool, message: str):
        """
        설치 완료 시 처리
        """
        # 진행도 다이얼로그 닫기
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # 워커 정리
        if hasattr(self, 'install_worker') and self.install_worker:
            self.install_worker.deleteLater()
            self.install_worker = None
        
        self.rembg_installing = False
        
        if success:
            print("✅ 설치 성공 - 패키지 재확인 시작")
            
            # 설치 직후 약간의 지연을 두고 재확인 (UI 응답성을 위해)
            QTimer.singleShot(1000, self._verify_installation_complete)
        else:
            # 설치 실패
            self.remove_bg_btn.setText("🗑️ 배경 제거")
            self.remove_bg_btn.setEnabled(True)  # 재설치 시도 가능하도록 활성화
            QMessageBox.critical(self, "오류", f"설치 실패:\n{message}")
    
    def _verify_installation_complete(self):
        """설치 완료 후 패키지 확인 및 UI 업데이트"""
        try:
            print("🔍 설치 완료 후 패키지 재확인 중...")
            
            # 더 강력한 모듈 재로딩
            self._force_module_reload()
            
            # rembg 가용성 재검사
            if self._check_rembg_availability(force_reload=True):
                print("🎉 rembg 설치 및 확인 완료!")
                
                self.remove_bg_btn.setText("🗑️ 배경 제거")
                if self.current_image:
                    self.remove_bg_btn.setEnabled(True)
                else:
                    self.remove_bg_btn.setEnabled(False)
                
                QMessageBox.information(self, "성공", 
                    "rembg[cpu] 설치가 완료되었습니다!\n"
                    "이제 배경 제거 기능을 사용할 수 있습니다.")
            else:
                print("⚠️ 설치 후에도 rembg를 찾을 수 없음 - NAIA 재시작 권장")
                
                self.remove_bg_btn.setText("🗑️ 배경 제거")
                self.remove_bg_btn.setEnabled(True)
                
                QMessageBox.warning(self, "재시작 필요", 
                    "rembg 설치는 완료되었지만 모듈을 찾을 수 없습니다.\n\n"
                    "NAIA를 재시작하면 정상적으로 사용할 수 있습니다.\n"
                    "지금 NAIA를 재시작하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes)
            
        except Exception as e:
            print(f"❌ 설치 확인 중 오류: {e}")
            self.remove_bg_btn.setText("🗑️ 배경 제거")
            self.remove_bg_btn.setEnabled(True)
    
    def _force_module_reload(self):
        """강력한 모듈 재로딩"""
        try:
            print("🔄 강력한 모듈 캐시 정리 시작...")
            
            # Python 모듈 캐시 완전 정리
            import sys
            import site
            import importlib
            
            # rembg 관련 모든 모듈 제거
            modules_to_remove = [k for k in list(sys.modules.keys()) if 'rembg' in k.lower()]
            for module in modules_to_remove:
                del sys.modules[module]
                print(f"   모듈 제거: {module}")
            
            # importlib 캐시 무효화
            importlib.invalidate_caches()
            
            # site-packages 재스캔
            site.main()
            
            # sys.path 새로고침 시도
            if hasattr(site, 'getsitepackages'):
                for path in site.getsitepackages():
                    if path not in sys.path:
                        sys.path.insert(0, path)
            
            print("🔄 모듈 캐시 정리 완료")
            
        except Exception as e:
            print(f"⚠️ 모듈 재로딩 중 오류: {e}")
    
    def _remove_background_from_image(self):
        """
        이미지에서 배경 제거 수행 (별도 프로세스에서 실행, PyQt DLL 충돌 회피)
        """
        try:
            # 버튼 상태 변경
            original_text = self.remove_bg_btn.text()
            self.remove_bg_btn.setText("🔄 처리 중...")
            self.remove_bg_btn.setEnabled(False)
            
            # 임시 파일로 현재 이미지 저장
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_input:
                input_path = temp_input.name
                
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_output:
                output_path = temp_output.name
            
            try:
                # 현재 이미지를 임시 파일로 저장
                self.current_image.save(input_path, 'PNG')
                print(f"🖼️ 임시 입력 이미지: {input_path}")
                
                # 별도 프로세스에서 배경 제거 실행
                if self._run_rembg_process(input_path, output_path):
                    # 결과 이미지 로드
                    from PIL import Image
                    result_image = Image.open(output_path)
                    
                    # 이미지 업데이트
                    self.update_generated_image(result_image)
                    
                    # 성공 메시지
                    if hasattr(self.app_context, 'main_window'):
                        self.app_context.main_window.status_bar.showMessage("✅ 배경 제거 완료", 3000)
                    
                    print("✅ 배경 제거 성공")
                else:
                    raise Exception("배경 제거 처리에 실패했습니다.")
            
            finally:
                # 임시 파일 정리
                try:
                    if os.path.exists(input_path):
                        os.unlink(input_path)
                    if os.path.exists(output_path):
                        os.unlink(output_path)
                except:
                    pass
                
                # 버튼 복원
                self.remove_bg_btn.setText(original_text)
                self.remove_bg_btn.setEnabled(True)
            
        except Exception as e:
            # 오류 시 버튼 복원
            self.remove_bg_btn.setText(original_text)
            self.remove_bg_btn.setEnabled(True)
            raise e
    
    def _run_rembg_process(self, input_path: str, output_path: str) -> bool:
        """일회성 rembg subprocess 실행 (즉시 종료)"""
        try:
            print("📡 rembg subprocess 배경 제거 실행 중...")
            
            # 일회성 rembg 실행 스크립트 (isnet-anime 모델 사용)
            rembg_script = f'''
import sys
from rembg import remove, new_session
from PIL import Image

try:
    # 입력 이미지 로드
    input_image = Image.open(r"{input_path}")
    
    # isnet-anime 모델로 배경 제거 (alpha matting 포함)
    output_image = remove(
        input_image, 
        session=new_session('isnet-anime'),
        alpha_matting={self.alpha_matting_enabled},
        alpha_matting_foreground_threshold={self.alpha_matting_foreground_threshold},
        alpha_matting_background_threshold={self.alpha_matting_background_threshold},
        alpha_matting_erode_structure_size={self.alpha_matting_erode_structure_size}
    )
    
    # 결과 저장
    output_image.save(r"{output_path}")
    
    print("REMBG_SUCCESS")
    
except Exception as e:
    print(f"REMBG_ERROR: {{e}}")
    sys.exit(1)
'''
            
            # subprocess로 실행
            result = subprocess.run(
                [sys.executable, '-c', rembg_script],
                capture_output=True,
                text=True,
                timeout=120,  # 2분 타임아웃
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            if result.returncode == 0 and "REMBG_SUCCESS" in result.stdout:
                print("✅ rembg subprocess 배경 제거 성공")
                return True
            else:
                print(f"❌ rembg subprocess 실패:")
                print(f"   stdout: {result.stdout}")
                print(f"   stderr: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("⏰ rembg subprocess 타임아웃 (2분)")
            return False
        except Exception as e:
            print(f"💥 rembg subprocess 실행 중 오류: {e}")
            return False
    
    # =================== View 탭 기능 메서드 ===================
    
    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """트리 아이템 클릭 처리 - 이미지 파일인 경우 View 탭에서 표시"""
        try:
            # 클릭한 아이템의 파일 경로 가져오기
            item_path_str = item.data(0, Qt.ItemDataRole.UserRole)
            if not item_path_str:
                return
            
            item_path = Path(item_path_str)
            
            # 이미지 파일인지 확인
            if not item_path.is_file() or item_path.suffix.lower() not in ['.png', '.jpg', '.jpeg', '.webp']:
                return
            
            print(f"🖼️ 이미지 파일 선택: {item_path.name}")
            
            # View 탭으로 자동 전환
            self.tab_widget.setCurrentIndex(1)  # View 탭은 인덱스 1
            
            # 이미지 로드 및 표시
            self._load_and_display_image(item_path)
            
        except Exception as e:
            print(f"❌ 트리 아이템 클릭 처리 오류: {e}")
    
    def _load_and_display_image(self, image_path: Path):
        """이미지를 로드하여 View 탭에 표시"""
        try:
            # PIL로 이미지 로드
            pil_image = Image.open(image_path)
            
            # WEBP를 PNG로 변환 (Qt 호환성을 위해)
            if hasattr(pil_image, 'format') and pil_image.format == 'WEBP':
                import io
                png_buffer = io.BytesIO()
                pil_image = pil_image.convert('RGBA')
                pil_image.save(png_buffer, format='PNG')
                png_buffer.seek(0)
                pil_image = Image.open(png_buffer)
                pil_image.load()  # Force load data before closing buffer
                png_buffer.close()
            
            # Qt QPixmap으로 변환
            image_qt = ImageQt(pil_image)
            pixmap = QPixmap.fromImage(image_qt)
            
            # View 위젯에 표시
            self.view_image_widget.setPixmap(pixmap)
            
            # 파일 경로 라벨 업데이트
            self.current_file_label.setText(f"📁 {image_path.name}")
            
            # 현재 선택된 이미지 저장 (버튼 활성화를 위해)
            self.current_selected_image_path = image_path
            self.current_variation = None  # 새 이미지 선택 시 variation 초기화
            
            # 버튼 활성화
            self.inpaint_btn.setEnabled(True)
            self.sketchbook_btn.setEnabled(True)
            self.char_prompt_btn.setEnabled(True)
            
            # Variations 콤보박스 체크 및 설정
            self._check_and_setup_variations(image_path)
            
            print(f"✅ 이미지 View 탭에서 표시 완료: {image_path.name}")
            
        except Exception as e:
            print(f"❌ 이미지 로드 오류: {e}")
            self.current_file_label.setText(f"❌ 이미지 로드 실패: {image_path.name}")
            # 오류 시 버튼 비활성화
            self.inpaint_btn.setEnabled(False)
            self.sketchbook_btn.setEnabled(False)
            self.char_prompt_btn.setEnabled(False)
            self.variations_combo.setVisible(False)
    
    def _send_to_inpaint(self):
        """Send to inpaint 버튼 클릭 처리 - 메인 윈도우의 inpaint 팝업과 동일한 동작"""
        try:
            if not hasattr(self, 'current_selected_image_path') or not self.current_selected_image_path:
                QMessageBox.warning(self, "경고", "선택된 이미지가 없습니다.")
                return
            
            # 메인 윈도우에서 inpaint 기능 호출
            if hasattr(self.app_context, 'main_window'):
                main_window = self.app_context.main_window
                
                # PIL 이미지로 로드
                pil_image = Image.open(self.current_selected_image_path)
                
                # 메인 윈도우의 img2img 패널에 이미지 설정하고 inpaint 모드 활성화
                if hasattr(main_window, 'img2img_panel'):
                    # img2img 패널에 이미지 설정
                    main_window.img2img_panel.set_image(pil_image)
                    
                    # inpaint 모드로 전환
                    if hasattr(main_window.img2img_panel, 'mode_combo'):
                        # inpaint 모드 인덱스 찾기
                        for i in range(main_window.img2img_panel.mode_combo.count()):
                            if 'inpaint' in main_window.img2img_panel.mode_combo.itemText(i).lower():
                                main_window.img2img_panel.mode_combo.setCurrentIndex(i)
                                main_window.img2img_panel._on_mode_changed()  # 모드 변경 이벤트 호출
                                break
                    
                    # 메인 탭으로 전환 (사용자가 바로 작업할 수 있도록)
                    if hasattr(main_window, 'main_tab_widget'):
                        main_window.main_tab_widget.setCurrentIndex(0)  # 메인 탭
                    
                    print(f"🎨 Assets에서 inpaint 모드로 이미지 전송: {self.current_selected_image_path.name}")
                    QMessageBox.information(self, "성공", f"이미지가 inpaint 모드로 전송되었습니다.\n\n파일: {self.current_selected_image_path.name}")
                else:
                    QMessageBox.warning(self, "오류", "메인 윈도우의 img2img 패널을 찾을 수 없습니다.")
            else:
                QMessageBox.warning(self, "오류", "메인 윈도우에 접근할 수 없습니다.")
                
        except Exception as e:
            print(f"❌ Send to inpaint 오류: {e}")
            QMessageBox.critical(self, "오류", f"inpaint 모드 전송 실패:\n{str(e)}")
    
    def _send_to_sketchbook(self):
        """Send to Sketchbook 버튼 클릭 처리 - Sketchbook 탭에 이미지 추가"""
        try:
            if not hasattr(self, 'current_selected_image_path') or not self.current_selected_image_path:
                QMessageBox.warning(self, "경고", "선택된 이미지가 없습니다.")
                return
            
            # Check for accompanying JSON file with character prompt
            json_path = self.current_selected_image_path.with_suffix('.json')
            character_prompt_data = None
            selected_property = None  # Track selected variation property
            
            if json_path.exists():
                try:
                    import json
                    with open(json_path, 'r', encoding='utf-8') as f:
                        character_prompt_data = json.load(f)
                    print(f"✅ Loaded character prompt from: {json_path}")
                    
                    # If a variation is selected, get the property name
                    if self.current_variation and self.current_variation != "-- Default --":
                        selected_property = self.current_variation
                        print(f"   📌 Selected variation property: {selected_property}")
                except Exception as e:
                    print(f"⚠️ Failed to load character prompt: {e}")
            
            # Sketchbook 탭으로 전환
            self.tab_widget.setCurrentIndex(2)  # Sketchbook 탭은 인덱스 2
            
            # Sketchbook 위젯에 이미지 추가
            if hasattr(self, 'sketchbook_widget'):
                image_name = self.current_selected_image_path.stem  # 확장자 제외한 파일명
                
                # Determine which image path to use
                image_path_to_add = str(self.current_selected_image_path)
                
                # If variation is selected, use variation image path
                if selected_property:
                    variations_folder = self.current_selected_image_path.parent / f"{self.current_selected_image_path.stem}_variations"
                    variation_image = variations_folder / f"{selected_property}.png"
                    if variation_image.exists():
                        image_path_to_add = str(variation_image)
                        image_name = f"{self.current_selected_image_path.stem}_{selected_property}"
                        print(f"   🎨 Using variation image: {variation_image.name}")
                
                # Use new method if character prompt exists, otherwise use existing method
                if character_prompt_data:
                    self.sketchbook_widget.add_image_from_path_with_prompt(
                        image_path_to_add, 
                        image_name,
                        character_prompt_data,
                        selected_property  # Pass selected property for auto-check
                    )
                else:
                    self.sketchbook_widget.add_image_from_path(
                        image_path_to_add, 
                        image_name
                    )
                
                print(f"✏️ Sketchbook에 이미지 추가: {self.current_selected_image_path.name}")
                if character_prompt_data:
                    print(f"   📝 Character prompt attached")
                
                QMessageBox.information(
                    self, 
                    "성공", 
                    f"이미지가 Sketchbook에 새 레이어로 추가되었습니다.\n\n"
                    f"파일: {self.current_selected_image_path.name}\n"
                    f"레이어명: {image_name}" +
                    ("\n📝 Character prompt 포함" if character_prompt_data else "")
                )
            else:
                QMessageBox.warning(self, "오류", "Sketchbook 위젯을 찾을 수 없습니다.")
            
        except Exception as e:
            print(f"❌ Send to Sketchbook 오류: {e}")
            QMessageBox.critical(self, "오류", f"Sketchbook 전송 실패:\n{str(e)}")
    
    def _open_character_prompt_editor(self):
        """Open Character Prompt Editor for current image"""
        try:
            if not hasattr(self, 'current_selected_image_path') or not self.current_selected_image_path:
                QMessageBox.warning(self, "경고", "선택된 이미지가 없습니다.")
                return
            
            # Import and create editor window
            from tabs.character_prompt_editor import CharacterPromptEditor
            
            # Create and show editor
            self.char_editor = CharacterPromptEditor(str(self.current_selected_image_path), self)
            self.char_editor.saved.connect(self._on_character_prompt_saved)
            self.char_editor.show()
            
            print(f"✅ Opened character prompt editor for: {self.current_selected_image_path}")
            
        except Exception as e:
            print(f"❌ Character Prompt Editor 오류: {e}")
            QMessageBox.critical(self, "오류", f"Character Prompt Editor 열기 실패:\n{str(e)}")
    
    def _on_character_prompt_saved(self, json_path: str):
        """Handle character prompt save event"""
        print(f"✅ Character prompt saved: {json_path}")
        # Re-check variations when JSON is saved/updated
        if hasattr(self, 'current_selected_image_path') and self.current_selected_image_path:
            self._check_and_setup_variations(self.current_selected_image_path)
    
    def _check_and_setup_variations(self, image_path: Path):
        """Check if variations exist and setup combo box"""
        try:
            # Temporarily disconnect signal to avoid triggering during setup
            try:
                self.variations_combo.blockSignals(True)
            except:
                pass
            
            # Reset combo box
            self.variations_combo.clear()
            self.variations_combo.setVisible(False)
            
            # Check if JSON file exists
            json_path = image_path.with_suffix('.json')
            if not json_path.exists():
                return
            
            # Check if variations folder exists
            variations_folder = image_path.parent / f"{image_path.stem}_variations"
            if not variations_folder.exists() or not variations_folder.is_dir():
                return
            
            # Get all PNG files in variations folder
            variation_files = list(variations_folder.glob("*.png"))
            if not variation_files:
                return
            
            # Setup combo box
            self.variations_combo.addItem("-- Default --")
            
            for var_file in sorted(variation_files):
                self.variations_combo.addItem(var_file.stem)
            
            # Show combo box
            self.variations_combo.setVisible(True)
            
            # Re-enable signals after setup
            try:
                self.variations_combo.blockSignals(False)
            except:
                pass
            
            print(f"📂 Found {len(variation_files)} variations for {image_path.name}")
            
        except Exception as e:
            print(f"❌ Error checking variations: {e}")
            self.variations_combo.setVisible(False)
            # Re-enable signals even on error
            try:
                self.variations_combo.blockSignals(False)
            except:
                pass
    
    def _display_image_without_variation_check(self, image_path: Path):
        """Display image without checking for variations (to avoid infinite loop)"""
        try:
            # PIL로 이미지 로드
            pil_image = Image.open(image_path)
            
            # WEBP를 PNG로 변환 (Qt 호환성을 위해)
            if hasattr(pil_image, 'format') and pil_image.format == 'WEBP':
                import io
                png_buffer = io.BytesIO()
                pil_image = pil_image.convert('RGBA')
                pil_image.save(png_buffer, format='PNG')
                png_buffer.seek(0)
                pil_image = Image.open(png_buffer)
                pil_image.load()  # Force load data before closing buffer
                png_buffer.close()
            
            # Qt QPixmap으로 변환
            image_qt = ImageQt(pil_image)
            pixmap = QPixmap.fromImage(image_qt)
            
            # View 위젯에 표시
            self.view_image_widget.setPixmap(pixmap)
            
            # 파일 경로 라벨 업데이트
            self.current_file_label.setText(f"📁 {image_path.name}")
            
        except Exception as e:
            print(f"❌ Error displaying image: {e}")
            self.current_file_label.setText(f"❌ 이미지 로드 실패: {image_path.name}")
    
    def _on_variation_selected(self, text: str):
        """Handle variation selection from combo box"""
        try:
            if not text or not hasattr(self, 'current_selected_image_path'):
                return
            
            self.current_variation = text if text != "-- Default --" else None
            
            if text == "-- Default --":
                # Load original image without re-checking variations
                self._display_image_without_variation_check(self.current_selected_image_path)
                print(f"🔄 Switched to default image")
            else:
                # Load variation image
                variations_folder = self.current_selected_image_path.parent / f"{self.current_selected_image_path.stem}_variations"
                variation_image = variations_folder / f"{text}.png"
                
                if variation_image.exists():
                    # Load variation image but keep original path reference
                    try:
                        pil_image = Image.open(variation_image)
                        
                        # Convert to QPixmap
                        if hasattr(pil_image, 'format') and pil_image.format == 'WEBP':
                            import io
                            png_buffer = io.BytesIO()
                            pil_image = pil_image.convert('RGBA')
                            pil_image.save(png_buffer, format='PNG')
                            png_buffer.seek(0)
                            pil_image = Image.open(png_buffer)
                            pil_image.load()
                            png_buffer.close()
                        
                        image_qt = ImageQt(pil_image)
                        pixmap = QPixmap.fromImage(image_qt)
                        
                        # Display variation image
                        self.view_image_widget.setPixmap(pixmap)
                        
                        # Update label to show variation
                        self.current_file_label.setText(f"📁 {self.current_selected_image_path.name} → {text}")
                        
                        print(f"🎨 Switched to variation: {text}")
                    except Exception as e:
                        print(f"❌ Error loading variation image: {e}")
                        # Revert to default
                        self.variations_combo.setCurrentText("-- Default --")
                else:
                    print(f"⚠️ Variation image not found: {variation_image}")
                    # Revert to default
                    self.variations_combo.setCurrentText("-- Default --")
                    
        except Exception as e:
            print(f"❌ Error selecting variation: {e}")
        # Optionally refresh or update UI if needed