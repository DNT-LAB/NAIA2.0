"""
EZ Mode Data Downloader

Hugging Face에서 EZ Mode matrices 데이터를 다운로드하고 압축 해제
"""

import os
import zipfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import List
from PyQt6.QtCore import QThread, pyqtSignal


class EZModeDownloadWorker(QThread):
    """EZ Mode matrices 다운로드 워커 스레드"""

    progress_updated = pyqtSignal(int, str)  # percent, message
    download_finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, target_dir: Path, parent=None):
        super().__init__(parent)
        self.target_dir = Path(target_dir)

        # Hugging Face URL
        self.zip_url = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/tags_70_tags_129_matrices.zip"

        # 임시 다운로드 경로
        self.temp_zip_path = self.target_dir.parent / "ezmode_matrices_temp.zip"

    def run(self):
        """다운로드 및 압축 해제 실행"""
        try:
            # 디렉터리 생성
            self.target_dir.mkdir(parents=True, exist_ok=True)
            self.progress_updated.emit(0, "다운로드 준비 중...")

            # 1. ZIP 파일 다운로드
            success, message = self._download_zip()
            if not success:
                self.download_finished.emit(False, message)
                return

            # 2. ZIP 파일 압축 해제
            self.progress_updated.emit(90, "압축 해제 중...")
            success, message = self._extract_zip()
            if not success:
                self.download_finished.emit(False, message)
                return

            # 3. 임시 파일 정리
            self._cleanup()

            self.progress_updated.emit(100, "다운로드 완료!")
            self.download_finished.emit(True, message)

        except Exception as e:
            error_msg = f"다운로드 실패: {str(e)}"
            self.download_finished.emit(False, error_msg)

    def _download_zip(self):
        """ZIP 파일 다운로드"""
        try:
            # 헤더 설정
            headers = {
                'User-Agent': 'NAIA/2.0.0 EZ Mode Matrices Downloader'
            }

            request = urllib.request.Request(self.zip_url, headers=headers)

            # 진행률 표시를 위한 다운로드
            def progress_hook(block_num, block_size, total_size):
                if total_size > 0:
                    percent = min(85, (block_num * block_size * 100) // total_size)
                    downloaded_mb = (block_num * block_size) / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024)
                    self.progress_updated.emit(
                        percent,
                        f"다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)"
                    )
                else:
                    downloaded_mb = (block_num * block_size) / (1024 * 1024)
                    self.progress_updated.emit(50, f"다운로드 중... {downloaded_mb:.1f} MB")

            # 임시 파일로 다운로드
            urllib.request.urlretrieve(self.zip_url, self.temp_zip_path, reporthook=progress_hook)

            # 파일 크기 검증
            file_size = self.temp_zip_path.stat().st_size
            file_size_mb = file_size / (1024 * 1024)

            if file_size < (10 * 1024 * 1024):  # 10MB 미만이면 오류
                if self.temp_zip_path.exists():
                    self.temp_zip_path.unlink()
                return False, f"다운로드된 파일이 너무 작습니다 ({file_size_mb:.2f} MB)"

            return True, f"다운로드 완료 ({file_size_mb:.2f} MB)"

        except urllib.error.HTTPError as e:
            error_msg = f"HTTP 오류 {e.code}: {e.reason}"
            if e.code == 404:
                error_msg += " (파일이 저장소에 존재하지 않습니다)"
            elif e.code == 403:
                error_msg += " (접근 권한 문제)"
            return False, error_msg

        except urllib.error.URLError as e:
            return False, f"네트워크 오류: {e.reason}"

        except Exception as e:
            return False, f"다운로드 오류: {str(e)}"

    def _extract_zip(self):
        """ZIP 파일 압축 해제"""
        try:
            if not self.temp_zip_path.exists():
                return False, "ZIP 파일이 존재하지 않습니다"

            extracted_count = 0

            with zipfile.ZipFile(self.temp_zip_path, 'r') as zip_ref:
                # ZIP 파일 내용 확인
                file_list = zip_ref.namelist()

                # matrices 폴더 생성
                matrices_dir = self.target_dir / 'matrices'
                matrices_dir.mkdir(parents=True, exist_ok=True)

                print(f"[DEBUG] ZIP 파일 내 총 {len(file_list)}개 항목")

                # 압축 해제 - 모든 파일을 matrices/ 폴더에 추출
                for file_name in file_list:
                    # 디렉터리는 건너뛰기
                    if file_name.endswith('/'):
                        continue

                    # 파일명만 추출 (경로 제거)
                    file_basename = file_name.split('/')[-1]

                    # data/.ezmode/matrices/ 에 직접 추출
                    target_path = matrices_dir / file_basename

                    with zip_ref.open(file_name) as source, open(target_path, 'wb') as target:
                        target.write(source.read())

                    extracted_count += 1

                    # 진행 상황 출력 (100개마다)
                    if extracted_count % 100 == 0:
                        print(f"[EXTRACT] {extracted_count}개 파일 추출됨...")

                if extracted_count == 0:
                    return False, "ZIP 파일에 파일이 없습니다"

                print(f"[OK] 압축 해제 완료: {extracted_count}개 파일")
                return True, f"압축 해제 완료 ({extracted_count}개 파일)"

        except zipfile.BadZipFile:
            return False, "손상된 ZIP 파일입니다"
        except Exception as e:
            return False, f"압축 해제 오류: {str(e)}"

    def _cleanup(self):
        """임시 파일 정리"""
        try:
            if self.temp_zip_path.exists():
                self.temp_zip_path.unlink()
        except Exception as e:
            print(f"[WARN] 임시 파일 정리 실패: {e}")


class EZModeDownloader:
    """EZ Mode 데이터 다운로더 (호환성 유지용 래퍼)"""

    def __init__(self, save_dir='data/.ezmode'):
        self.save_dir = Path(save_dir)
        self.worker = None

    def start_download(self, progress_callback=None, finished_callback=None):
        """다운로드 시작 (QThread 사용)

        Args:
            progress_callback: 진행률 콜백 (percent, message)
            finished_callback: 완료 콜백 (success, message)
        """
        self.worker = EZModeDownloadWorker(self.save_dir)

        if progress_callback:
            self.worker.progress_updated.connect(progress_callback)

        if finished_callback:
            self.worker.download_finished.connect(finished_callback)

        self.worker.start()

        return self.worker


def check_dependencies() -> List[str]:
    """필수 의존성 확인

    Returns:
        List[str]: 누락된 패키지 목록
    """
    missing = []

    try:
        import scipy
    except ImportError:
        missing.append('scipy')

    try:
        import numpy
    except ImportError:
        missing.append('numpy')

    try:
        import pandas
    except ImportError:
        missing.append('pandas')

    return missing


def check_ezmode_data_exists(data_dir='data/ezmode') -> bool:
    """EZ Mode 데이터 존재 여부 및 무결성 확인

    Args:
        data_dir: 데이터 디렉터리 경로 (JSON 파일용, 기본: data/ezmode)

    Returns:
        bool: 모든 필수 파일이 존재하고 무결성 검증을 통과하면 True
    """
    data_path = Path(data_dir)
    matrices_path = Path('data/.ezmode/matrices')  # Hugging Face 전용 경로

    required_files = [
        data_path / 'category_index.json',
        data_path / 'output.json',
        matrices_path  # matrices는 .ezmode에 있음
    ]

    # 1. 기본 파일 존재 확인
    basic_exists = all(f.exists() for f in required_files)

    if not basic_exists:
        print(f"[MISSING] EZ Mode data not found")
        for f in required_files:
            status = "[OK]" if f.exists() else "[MISSING]"
            print(f"  {status} {f}")
        return False

    # 2. 무결성 검증 (matrices 폴더)
    if matrices_path.exists():
        # build_summary.json 존재 확인
        build_summary_path = matrices_path / 'build_summary.json'
        if not build_summary_path.exists():
            print(f"[MISSING] build_summary.json not found in matrices/")
            print(f"  데이터가 완전하지 않습니다. 재다운로드가 필요합니다.")
            return False

        # 전체 파일 수 확인 (1645개 예상)
        all_files = list(matrices_path.glob('*'))
        file_count = len(all_files)
        expected_count = 1645  # 411 카테고리 × 4 파일 + build_summary.json = 1645

        if file_count < expected_count:
            print(f"[WARNING] Matrices 파일 수 부족: {file_count}/{expected_count}")
            print(f"  일부 파일이 누락되었습니다. 재다운로드를 권장합니다.")
            # 80% 이상이면 허용 (일부 누락 허용)
            if file_count < expected_count * 0.8:
                print(f"  파일 수가 너무 적습니다. 재다운로드가 필요합니다.")
                return False
            else:
                print(f"  최소 요구사항을 충족하여 계속 진행합니다.")
        else:
            print(f"[OK] EZ Mode data verified")
            print(f"  JSON files: {data_dir}")
            print(f"  Matrices: {matrices_path} ({file_count} files)")

    return True


def get_data_directory_info(data_dir='data/ezmode') -> dict:
    """데이터 디렉터리 정보 조회

    Args:
        data_dir: JSON 파일 디렉터리 경로 (기본: data/ezmode)

    Returns:
        dict: 디렉터리 정보
            - exists: 디렉터리 존재 여부
            - category_index_exists: category_index.json 존재 여부
            - output_json_exists: output.json 존재 여부
            - matrices_exists: matrices/ 디렉터리 존재 여부
            - build_summary_exists: build_summary.json 존재 여부
            - matrices_count: 전체 매트릭스 파일 수
            - expected_count: 예상 파일 수 (1645)
            - is_complete: 데이터 완전성 여부
    """
    data_path = Path(data_dir)
    matrices_path = Path('data/.ezmode/matrices')  # Hugging Face 전용 경로
    build_summary_path = matrices_path / 'build_summary.json'
    expected_count = 1645  # 411 카테고리 × 4 파일 + build_summary.json

    info = {
        'exists': data_path.exists(),
        'category_index_exists': (data_path / 'category_index.json').exists(),
        'output_json_exists': (data_path / 'output.json').exists(),
        'matrices_exists': matrices_path.exists(),
        'build_summary_exists': build_summary_path.exists(),
        'matrices_count': 0,
        'expected_count': expected_count,
        'is_complete': False
    }

    # 매트릭스 파일 수 카운트 (전체)
    if info['matrices_exists']:
        all_files = list(matrices_path.glob('*'))
        info['matrices_count'] = len(all_files)

        # 완전성 체크: build_summary 존재 + 파일 수 80% 이상
        info['is_complete'] = (
            info['build_summary_exists'] and
            info['matrices_count'] >= expected_count * 0.8
        )

    return info
