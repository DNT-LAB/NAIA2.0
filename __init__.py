import os
import sys
import urllib.request
import urllib.error
import zipfile
import shutil
from pathlib import Path
import time
from typing import List, Tuple

# NAIA 프로젝트 버전 정보
__version__ = "2.0.1"
__author__ = "NAIA"

class TagDataDownloader:
    """태그 데이터 파일 자동 다운로더 및 압축해제"""
    
    def __init__(self):
        # Hugging Face 저장소의 zip 파일 URL
        self.zip_url = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/naia_tags.zip"
        
        # 프로젝트 루트 경로 설정
        self.project_root = Path(__file__).parent
        self.data_dir = self.project_root / "data" / "tags"
        self.temp_zip_path = self.project_root / "temp_naia_tags.zip"
        
        # 예상되는 파일 범위 (tags_00.parquet ~ tags_149.parquet)
        self.expected_file_count = 150
        
        print(f"🚀 NAIA v{__version__} 초기화 중...")
        print(f"📁 데이터 디렉토리: {self.data_dir}")
        print(f"🤗 Hugging Face ZIP 파일: naia_tags.zip")
    
    def ensure_data_directory(self) -> None:
        """데이터 디렉토리가 존재하지 않으면 생성"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ 데이터 디렉토리 준비 완료: {self.data_dir}")
        except Exception as e:
            print(f"❌ 데이터 디렉토리 생성 실패: {e}")
            raise
    
    def check_existing_files(self) -> Tuple[bool, int]:
        """
        기존 파일들이 있는지 확인합니다.

        Returns:
            Tuple[bool, int]: (충분한 파일이 있는지, 현재 파일 개수)
        """
        if not self.data_dir.exists():
            return False, 0

        parquet_files = list(self.data_dir.glob("tags_*.parquet"))
        file_count = len(parquet_files)

        print(f"📊 현재 태그 파일 개수: {file_count}/{self.expected_file_count}")

        # 정확히 예상 파일 개수와 일치할 때만 충분하다고 판단
        sufficient = file_count >= self.expected_file_count

        if file_count < self.expected_file_count:
            print(f"⚠️ 파일이 부족합니다. {self.expected_file_count - file_count}개 파일이 더 필요합니다.")

        return sufficient, file_count
    
    def download_zip_file(self) -> Tuple[bool, str]:
        """
        ZIP 파일을 다운로드합니다.
        
        Returns:
            Tuple[bool, str]: (성공 여부, 메시지)
        """
        try:
            print(f"📦 ZIP 파일 다운로드 시작...")
            print(f"🔗 URL: {self.zip_url}")
            
            # Hugging Face에서 파일 다운로드를 위한 헤더 설정
            headers = {
                'User-Agent': 'NAIA/2.0.1 (https://github.com/naia-project)'
            }
            
            # urllib 요청 객체 생성 및 헤더 설정
            request = urllib.request.Request(self.zip_url, headers=headers)
            
            # 진행률 표시를 위한 다운로드 함수
            def progress_hook(block_num, block_size, total_size):
                if total_size > 0:
                    percent = min(100, (block_num * block_size * 100) // total_size)
                    downloaded = block_num * block_size
                    total_mb = total_size / (1024 * 1024)
                    downloaded_mb = downloaded / (1024 * 1024)
                    print(f"\r   진행률: {percent:3d}% ({downloaded_mb:.1f} / {total_mb:.1f} MB)", end="")
                else:
                    # 파일 크기를 알 수 없는 경우
                    downloaded = block_num * block_size
                    downloaded_mb = downloaded / (1024 * 1024)
                    print(f"\r   다운로드 중: {downloaded_mb:.1f} MB", end="")
            
            # 파일 다운로드 실행
            urllib.request.urlretrieve(self.zip_url, self.temp_zip_path, reporthook=progress_hook)
            print(f"\n✅ ZIP 파일 다운로드 완료!")
            
            # 파일 크기 검증
            file_size = self.temp_zip_path.stat().st_size
            file_size_mb = file_size / (1024 * 1024)
            
            if file_size < (1024 * 1024):  # 1MB 미만이면 오류로 간주
                self.temp_zip_path.unlink()  # 파일 삭제
                return False, f"다운로드된 ZIP 파일이 너무 작습니다 ({file_size_mb:.2f} MB)"
            
            return True, f"성공적으로 다운로드됨 ({file_size_mb:.2f} MB)"
            
        except urllib.error.HTTPError as e:
            error_msg = f"HTTP 오류 {e.code}: {e.reason}"
            if e.code == 404:
                error_msg += " (ZIP 파일이 저장소에 존재하지 않을 수 있습니다)"
            elif e.code == 403:
                error_msg += " (접근 권한 문제일 수 있습니다)"
            print(f"\n❌ ZIP 파일 다운로드 실패: {error_msg}")
            return False, error_msg
            
        except urllib.error.URLError as e:
            error_msg = f"네트워크 오류: {e.reason}"
            print(f"\n❌ ZIP 파일 다운로드 실패: {error_msg}")
            return False, error_msg
            
        except Exception as e:
            error_msg = f"예상치 못한 오류: {str(e)}"
            print(f"\n❌ ZIP 파일 다운로드 실패: {error_msg}")
            return False, error_msg
    
    def extract_zip_file(self) -> Tuple[bool, str, int]:
        """
        ZIP 파일을 압축해제합니다.
        
        Returns:
            Tuple[bool, str, int]: (성공 여부, 메시지, 추출된 파일 개수)
        """
        try:
            if not self.temp_zip_path.exists():
                return False, "ZIP 파일이 존재하지 않습니다", 0
            
            print(f"📂 ZIP 파일 압축해제 시작...")
            
            extracted_count = 0
            
            with zipfile.ZipFile(self.temp_zip_path, 'r') as zip_ref:
                # ZIP 파일 내용 확인
                file_list = zip_ref.namelist()
                parquet_files = [f for f in file_list if f.endswith('.parquet')]
                
                print(f"📋 ZIP 파일 내 parquet 파일 개수: {len(parquet_files)}")
                
                if len(parquet_files) == 0:
                    return False, "ZIP 파일에 parquet 파일이 없습니다", 0
                
                # 기존 파일 백업 (필요시)
                if self.data_dir.exists() and any(self.data_dir.glob("*.parquet")):
                    backup_dir = self.data_dir.parent / "tags_backup"
                    if backup_dir.exists():
                        shutil.rmtree(backup_dir)
                    shutil.copytree(self.data_dir, backup_dir)
                    print(f"📦 기존 파일들을 백업했습니다: {backup_dir}")
                
                # 압축해제 실행
                for i, file_info in enumerate(zip_ref.infolist(), 1):
                    if file_info.filename.endswith('.parquet'):
                        # 진행률 표시
                        percent = (i * 100) // len(parquet_files)
                        print(f"\r   압축해제 진행률: {percent:3d}% ({i}/{len(parquet_files)})", end="")
                        
                        # 파일명만 추출 (경로 제거)
                        filename = Path(file_info.filename).name
                        target_path = self.data_dir / filename
                        
                        # 파일 추출
                        with zip_ref.open(file_info) as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                        
                        extracted_count += 1
                
                print(f"\n✅ 압축해제 완료: {extracted_count}개 파일 추출됨")
                
            return True, f"{extracted_count}개의 parquet 파일이 성공적으로 추출됨", extracted_count
            
        except zipfile.BadZipFile:
            error_msg = "손상된 ZIP 파일입니다"
            print(f"\n❌ 압축해제 실패: {error_msg}")
            return False, error_msg, 0
            
        except PermissionError as e:
            error_msg = f"파일 권한 오류: {e}"
            print(f"\n❌ 압축해제 실패: {error_msg}")
            return False, error_msg, 0
            
        except Exception as e:
            error_msg = f"예상치 못한 오류: {str(e)}"
            print(f"\n❌ 압축해제 실패: {error_msg}")
            return False, error_msg, 0
    
    def cleanup_temp_files(self) -> None:
        """임시 파일들을 정리합니다"""
        try:
            if self.temp_zip_path.exists():
                self.temp_zip_path.unlink()
                print(f"🧹 임시 ZIP 파일 삭제 완료")
        except Exception as e:
            print(f"⚠️ 임시 파일 삭제 중 오류: {e}")

    def cleanup_backup_files(self) -> None:
        """백업 디렉토리의 tags_ 파일들을 정리합니다"""
        try:
            backup_dir = self.data_dir.parent / "tags_backup"
            if backup_dir.exists():
                # tags_ 로 시작하는 parquet 파일들만 삭제
                backup_tags = list(backup_dir.glob("tags_*.parquet"))
                if backup_tags:
                    for file_path in backup_tags:
                        file_path.unlink()
                    print(f"🧹 백업 디렉토리의 tags_ 파일 {len(backup_tags)}개 삭제 완료")

                    # 디렉토리가 비었으면 디렉토리도 삭제
                    remaining_files = list(backup_dir.iterdir())
                    if not remaining_files:
                        backup_dir.rmdir()
                        print(f"🧹 빈 백업 디렉토리 삭제 완료")
        except Exception as e:
            print(f"⚠️ 백업 파일 삭제 중 오류: {e}")
    
    def verify_data_integrity(self) -> Tuple[bool, int]:
        """
        압축해제된 데이터의 무결성을 검증합니다.
        
        Returns:
            Tuple[bool, int]: (검증 성공 여부, 유효한 파일 개수)
        """
        print("\n🔍 데이터 무결성 검증 중...")
        
        try:
            import pandas as pd
        except ImportError:
            print("⚠️ pandas가 설치되지 않아 무결성 검증을 건너뜁니다.")
            # pandas 없이도 파일 존재 여부는 확인
            parquet_files = list(self.data_dir.glob("tags_*.parquet"))
            return len(parquet_files) > 0, len(parquet_files)
        
        try:
            valid_files = 0
            total_files = 0
            total_rows = 0
            
            parquet_files = list(self.data_dir.glob("tags_*.parquet"))
            
            for file_path in parquet_files:
                total_files += 1
                try:
                    # parquet 파일 읽기 테스트
                    df = pd.read_parquet(file_path)
                    if len(df) > 0:  # 데이터가 있는지 확인
                        valid_files += 1
                        total_rows += len(df)
                    else:
                        print(f"⚠️ {file_path.name}: 데이터가 비어있음")
                except Exception as e:
                    print(f"❌ {file_path.name}: 손상된 파일 ({e})")
            
            print(f"📈 검증 결과: {valid_files}/{total_files} 파일이 유효함")
            print(f"📊 총 데이터 행 수: {total_rows:,}개")

            # 90% 이상의 파일이 유효하고, 최소 expected_file_count와 일치해야 성공
            required_valid_files = int(self.expected_file_count * 0.9)
            success = valid_files >= required_valid_files and total_files >= self.expected_file_count

            if success:
                print("✅ 태그 데이터가 정상적으로 준비되었습니다!")
            else:
                print(f"⚠️ 데이터 무결성 검증 실패: {valid_files}/{self.expected_file_count}개 (최소 {required_valid_files}개 필요)")

            return success, valid_files
                
        except Exception as e:
            print(f"❌ 무결성 검증 중 오류 발생: {e}")
            return False, 0
    
    def download_and_extract(self) -> Tuple[bool, int]:
        """
        전체 다운로드 및 압축해제 프로세스를 실행합니다.
        
        Returns:
            Tuple[bool, int]: (성공 여부, 추출된 파일 개수)
        """
        try:
            # 1. 데이터 디렉토리 생성
            self.ensure_data_directory()
            
            # 2. 기존 파일 확인
            has_sufficient_files, current_count = self.check_existing_files()
            
            if has_sufficient_files:
                print("✅ 충분한 태그 데이터 파일이 이미 존재합니다.")
                print("   다운로드를 건너뜁니다.")
                return True, current_count
            
            print(f"📥 태그 데이터 다운로드가 필요합니다...")
            
            # 3. ZIP 파일 다운로드
            download_success, download_msg = self.download_zip_file()
            
            if not download_success:
                print(f"❌ 다운로드 실패: {download_msg}")
                return False, 0
            
            # 4. ZIP 파일 압축해제
            extract_success, extract_msg, extracted_count = self.extract_zip_file()
            
            if not extract_success:
                print(f"❌ 압축해제 실패: {extract_msg}")
                self.cleanup_temp_files()
                return False, 0
            
            # 5. 임시 파일 정리
            self.cleanup_temp_files()
            
            # 6. 데이터 무결성 검증
            verify_success, valid_count = self.verify_data_integrity()

            if verify_success:
                # 7. 백업 파일 정리 (검증 성공 시)
                self.cleanup_backup_files()

                print(f"\n🎉 태그 데이터 설치가 성공적으로 완료되었습니다!")
                print(f"   📊 사용 가능한 파일: {valid_count}개")
                return True, valid_count
            else:
                print(f"\n⚠️ 일부 파일에 문제가 있지만 기본 사용은 가능합니다.")
                print(f"   💡 백업 파일은 보존됩니다: {self.data_dir.parent / 'tags_backup'}")
                return True, valid_count  # 부분적 성공도 True로 처리
                
        except Exception as e:
            print(f"\n❌ 다운로드 및 압축해제 중 치명적 오류 발생: {e}")
            self.cleanup_temp_files()
            return False, 0


def initialize_naia_data() -> bool:
    """
    NAIA 프로젝트 데이터 초기화 메인 함수
    
    Returns:
        bool: 초기화 성공 여부
    """
    try:
        downloader = TagDataDownloader()
        
        # 다운로드 및 압축해제 실행
        success, file_count = downloader.download_and_extract()
        
        if success and file_count > 0:
            print(f"\n🎉 NAIA 데이터 초기화가 성공적으로 완료되었습니다!")
            print(f"   📁 데이터 위치: {downloader.data_dir}")
            print(f"   📊 파일 개수: {file_count}개")
            return True
        else:
            print(f"\n⚠️ 데이터 초기화에 실패했습니다.")
            print(f"   💡 인터넷 연결을 확인하거나 수동으로 다시 시도해보세요.")
            return False
            
    except Exception as e:
        print(f"\n❌ 데이터 초기화 중 치명적 오류 발생: {e}")
        return False


# 모듈 import 시 자동 실행
if __name__ == "__main__":
    # 직접 실행된 경우
    print("🔧 NAIA 데이터 초기화를 수동으로 실행합니다...")
    success = initialize_naia_data()
    sys.exit(0 if success else 1)
else:
    # 모듈로 import된 경우 자동 실행
    try:
        # 환경 변수로 자동 다운로드 비활성화 가능
        if os.environ.get("NAIA_SKIP_AUTO_DOWNLOAD", "false").lower() != "true":
            initialize_naia_data()
    except Exception as e:
        print(f"⚠️ 자동 데이터 초기화 중 오류 발생: {e}")
        print(f"   수동으로 python __init__.py를 실행해보세요.")


# 프로젝트에서 사용할 수 있는 유틸리티 함수들
def get_data_path() -> Path:
    """태그 데이터 디렉토리 경로를 반환"""
    return Path(__file__).parent / "data" / "tags"

def get_tag_file_path(index: int) -> Path:
    """특정 인덱스의 태그 파일 경로를 반환"""
    if not 0 <= index <= 149:
        raise ValueError(f"인덱스는 0-149 범위여야 합니다. 입력값: {index}")

    filename = f"tags_{index:02d}.parquet"
    return get_data_path() / filename

def check_data_availability() -> Tuple[bool, int, int]:
    """
    데이터 가용성을 체크합니다.
    
    Returns:
        Tuple[bool, int, int]: (충분한 파일 존재 여부, 존재하는 파일 수, 예상 파일 수)
    """
    data_path = get_data_path()
    
    if not data_path.exists():
        return False, 0, 130
    
    parquet_files = list(data_path.glob("tags_*.parquet"))
    existing_count = len(parquet_files)
    expected_count = 150  # tags_00.parquet ~ tags_149.parquet

    # 정확히 예상 파일 개수와 일치할 때만 충분하다고 판단
    sufficient = existing_count >= expected_count

    return sufficient, existing_count, expected_count

def force_download() -> bool:
    """
    강제로 데이터를 다시 다운로드합니다.
    
    Returns:
        bool: 다운로드 성공 여부
    """
    print("🔄 강제 데이터 다운로드를 시작합니다...")
    
    try:
        downloader = TagDataDownloader()
        
        # 기존 데이터 디렉토리 백업
        if downloader.data_dir.exists():
            backup_dir = downloader.data_dir.parent / "tags_old_backup"
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.move(str(downloader.data_dir), str(backup_dir))
            print(f"📦 기존 데이터를 백업했습니다: {backup_dir}")
        
        # 새로 다운로드
        success, file_count = downloader.download_and_extract()
        
        if success:
            print(f"✅ 강제 다운로드 완료: {file_count}개 파일")
            return True
        else:
            # 실패 시 백업 복원
            if backup_dir.exists():
                shutil.move(str(backup_dir), str(downloader.data_dir))
                print(f"🔄 백업 데이터를 복원했습니다.")
            return False
            
    except Exception as e:
        print(f"❌ 강제 다운로드 중 오류: {e}")
        return False


# 프로젝트 정보 출력
print(f"📚 NAIA v{__version__} - AI 이미지 생성 도구")
print(f"📁 프로젝트 경로: {Path(__file__).parent}")

# 데이터 상태 확인
sufficient, existing_count, expected_count = check_data_availability()
if sufficient:
    print(f"✅ 태그 데이터: {existing_count}개 파일 준비 완료")
else:
    print(f"⚠️ 태그 데이터: {existing_count}/{expected_count}개 파일 (다운로드 필요)")