"""
EZ Mode Main Window

EZ Mode의 메인 윈도우 - 의존성 확인, 데이터 다운로드, UI 통합
"""

from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QMessageBox,
                              QProgressDialog, QVBoxLayout, QLabel)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
from ui.ezmode.ezmode_controller import EZModeController
from ui.ezmode.ezmode_data_manager import EZModeDataManager
from ui.ezmode.ezmode_downloader import (check_dependencies, check_ezmode_data_exists,
                                         EZModeDownloader, get_data_directory_info)
from ui.scaling_manager import get_scaled_size, get_scaled_font_size
import pandas as pd


class EZModeWindow(QMainWindow):
    """EZ Mode 메인 윈도우"""

    # MainWindow로 전달될 시그널 (pandas.Series 전달)
    instant_generation_requested = pyqtSignal(object)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context

        # 윈도우 설정
        self.setWindowTitle("EZ Mode - Easy Prompt Generation")
        self.resize(get_scaled_size(900), get_scaled_size(1200))  # 너비 25% 감소, 높이 1.5배 증가 (800 → 1200)

        # 의존성 및 데이터 확인
        if not self._check_prerequisites():
            # 전제 조건 미충족 시 임시 안내 UI 표시
            self._show_setup_required_ui()
            return

        # 데이터 매니저
        self.data_manager = EZModeDataManager()

        # UI 초기화
        self.init_ui()

        # 데이터 로드
        if not self.data_manager.load_initial_data():
            QMessageBox.critical(self, "오류", "데이터 로딩에 실패했습니다.\n프로그램을 재시작하세요.")
            return

        # KR_tags 로드 (Tooltip용)
        self.data_manager.load_kr_tags()

        print("[OK] EZ Mode Window initialized")

    def _check_prerequisites(self) -> bool:
        """의존성 및 데이터 확인

        Returns:
            bool: 모든 전제 조건이 충족되면 True
        """
        # 1. 의존성 확인
        missing = check_dependencies()
        if missing:
            self._show_dependency_dialog(missing)
            return False

        # 2. 데이터 존재 확인
        if not check_ezmode_data_exists():
            # 데이터 정보 조회
            data_info = get_data_directory_info()

            # 다운로드 여부 묻기
            reply = self._show_download_dialog(data_info)
            if reply:
                # 실제 다운로드 시작
                download_success = self._start_download()
                if not download_success:
                    return False
                # 다운로드 성공 시 다시 체크
                return check_ezmode_data_exists()
            else:
                return False

        return True

    def _show_dependency_dialog(self, missing_packages: list):
        """의존성 누락 안내"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("의존성 패키지 누락")

        package_list = '\n'.join([f"  • {pkg}" for pkg in missing_packages])

        msg.setText(
            "EZ Mode를 사용하려면 다음 Python 패키지가 필요합니다:\n\n"
            f"{package_list}\n\n"
            "터미널에서 다음 명령어를 실행하여 설치하세요:"
        )

        install_cmd = f"pip install {' '.join(missing_packages)}"

        msg.setDetailedText(install_cmd)
        msg.setInformativeText(
            "설치 후 NAIA 2.0을 재시작하세요.\n\n"
            "설치 명령어를 복사하려면 'Show Details'를 클릭하세요."
        )

        msg.exec()

    def _show_download_dialog(self, data_info: dict) -> bool:
        """데이터 다운로드 안내

        Args:
            data_info: 데이터 디렉터리 정보

        Returns:
            bool: 사용자가 다운로드를 선택하면 True
        """
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("EZ Mode 데이터 다운로드")

        # 상태 메시지 생성
        status_lines = []
        if not data_info['category_index_exists']:
            status_lines.append("  [X] category_index.json 없음")
        if not data_info['output_json_exists']:
            status_lines.append("  [X] output.json 없음")
        if not data_info['matrices_exists']:
            status_lines.append("  [X] matrices/ 디렉터리 없음")
        elif data_info['matrices_count'] == 0:
            status_lines.append("  [X] 매트릭스 파일 없음")
        elif not data_info['build_summary_exists']:
            status_lines.append(f"  [!] build_summary.json 없음")
            status_lines.append(f"  [!] 파일: {data_info['matrices_count']}/{data_info['expected_count']} (불완전)")
        elif not data_info['is_complete']:
            status_lines.append(f"  [!] 파일 수 부족: {data_info['matrices_count']}/{data_info['expected_count']}")
            status_lines.append(f"  [!] 일부 파일이 누락되었습니다")

        status_text = '\n'.join(status_lines)

        # 다운로드 필요 여부에 따라 메시지 변경
        if data_info['matrices_exists'] and data_info['matrices_count'] > 0:
            main_text = (
                "EZ Mode 데이터가 불완전합니다.\n\n"
                f"{status_text}\n\n"
                "데이터를 재다운로드하시겠습니까? (약 2.8GB)"
            )
        else:
            main_text = (
                "EZ Mode 데이터셋이 없습니다.\n\n"
                f"{status_text}\n\n"
                "Hugging Face에서 데이터셋을 다운로드해야 합니다. (약 2.8GB)\n"
                "다운로드하시겠습니까?"
            )

        msg.setText(main_text)

        msg.setInformativeText(
            "다운로드는 최초 1회만 필요하며, 수 분이 소요될 수 있습니다."
        )

        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)

        return msg.exec() == QMessageBox.StandardButton.Yes

    def _start_download(self) -> bool:
        """EZ Mode 데이터 다운로드 시작

        Returns:
            bool: 다운로드 성공 여부
        """
        from PyQt6.QtCore import QEventLoop
        import shutil

        # 기존 matrices 폴더 정리 (불완전한 데이터 제거)
        matrices_path = Path('data/.ezmode/matrices')
        if matrices_path.exists():
            try:
                print(f"[INFO] 기존 matrices 폴더 삭제 중...")
                shutil.rmtree(matrices_path)
                print(f"[OK] 기존 데이터 정리 완료")
            except Exception as e:
                print(f"[WARN] 기존 폴더 삭제 실패: {e}")

        # 진행 다이얼로그 생성
        progress_dialog = QProgressDialog(
            "EZ Mode 데이터 다운로드 준비 중...",
            "취소",
            0, 100,
            self
        )
        progress_dialog.setWindowTitle("데이터 다운로드")
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setMinimumDuration(0)  # 즉시 표시
        progress_dialog.setValue(0)

        download_success = False
        download_message = ""
        event_loop = QEventLoop()

        def on_progress(percent: int, message: str):
            """진행률 업데이트"""
            progress_dialog.setValue(percent)
            progress_dialog.setLabelText(message)

        def on_finished(success: bool, message: str):
            """다운로드 완료"""
            nonlocal download_success, download_message
            download_success = success
            download_message = message
            progress_dialog.setValue(100)
            progress_dialog.close()
            event_loop.quit()  # 이벤트 루프 종료

        # 다운로더 생성 및 시작
        downloader = EZModeDownloader()
        worker = downloader.start_download(
            progress_callback=on_progress,
            finished_callback=on_finished
        )

        # 취소 버튼 비활성화 (다운로드 중단 시 데이터 손상 방지)
        progress_dialog.setCancelButton(None)

        # 워커 완료까지 대기 (이벤트 루프 실행)
        event_loop.exec()

        # 결과 메시지 표시
        if download_success:
            QMessageBox.information(
                self,
                "다운로드 완료",
                f"EZ Mode 데이터 다운로드가 완료되었습니다.\n\n{download_message}"
            )
        else:
            QMessageBox.critical(
                self,
                "다운로드 실패",
                f"EZ Mode 데이터 다운로드에 실패했습니다.\n\n오류: {download_message}\n\n"
                f"네트워크 연결을 확인하거나 Hugging Face 저장소를 확인해주세요."
            )

        return download_success

    def _show_setup_required_ui(self):
        """설정 필요 안내 UI (임시)"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label = QLabel(
            "[!] EZ Mode 설정 필요\n\n"
            "의존성 패키지를 설치하거나\n"
            "데이터셋을 다운로드한 후\n"
            "다시 시도하세요."
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(18)}px;
            color: #e0e0e0;
            padding: {get_scaled_size(20)}px;
        """)

        layout.addWidget(label)

        self.setStyleSheet("background-color: #2a2a2a;")

    def init_ui(self):
        """UI 초기화"""
        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 레이아웃
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 컨트롤러 (전체 100%)
        self.controller = EZModeController(self.data_manager, self.app_context)
        layout.addWidget(self.controller)

        # 즉시 생성 시그널 연결 (Controller → EZModeWindow → MainWindow)
        self.controller.instant_generation_requested.connect(self.instant_generation_requested)

        # 배경색
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
        """)

    def closeEvent(self, event):
        """윈도우 닫기 이벤트"""
        # 매트릭스 캐시 정리
        if hasattr(self, 'data_manager'):
            self.data_manager.clear_cache()

        print("EZ Mode Window 종료")
        event.accept()
