"""
테스트 스크립트: E621 모듈 다운로드 기능 확인
"""
import sys
from pathlib import Path

# 데이터 파일 경로
data_path = Path(__file__).parent / "data" / "e621_data"

print(f"E621 데이터 파일 경로: {data_path}")
print(f"파일 존재 여부: {data_path.exists()}")

if data_path.exists():
    size_mb = data_path.stat().st_size / (1024 * 1024)
    print(f"파일 크기: {size_mb:.2f} MB")
else:
    print("❌ 파일이 존재하지 않습니다.")
    print("✅ 모듈을 펼치면 자동 다운로드 UI가 표시됩니다.")
