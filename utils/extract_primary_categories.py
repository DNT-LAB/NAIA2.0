"""
1차 카테고리 추출 스크립트

KR_tags.parquet의 category 필드에서 " > " 이전의 1차 카테고리를 추출하고,
각 1차 카테고리에 속하는 태그 목록을 역인덱스 형태로 저장합니다.

출력 형식:
{
  "General": ["1girl", "solo", "breasts", ...],
  "Artist": ["artist_name", "artist:foo", ...],
  ...
}

성능 최적화:
- 필터링 시 O(1) 시간복잡도로 카테고리 확인 가능
- 메모리 효율적 (태그명만 저장, 중복 없음)
"""

import pandas as pd
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set


def extract_primary_category(category_text: str) -> str:
    """
    category 필드에서 1차 카테고리 추출

    Args:
        category_text: 카테고리 문자열 (예: "General > Body", "Artist")

    Returns:
        1차 카테고리 (예: "General", "Artist")
    """
    if not isinstance(category_text, str):
        return "Unknown"

    # " > " 기준으로 분리
    if ' > ' in category_text:
        return category_text.split(' > ')[0].strip()
    else:
        return category_text.strip()


def extract_primary_categories():
    """
    KR_tags.parquet에서 1차 카테고리별 태그 목록 추출

    출력 파일: data/ezmode/category_tags_index.json
    형식: {"카테고리명": ["태그1", "태그2", ...], ...}
    """

    print("=" * 60)
    print("1st Category Extraction Script Started")
    print("=" * 60)

    # KR_tags.parquet 로드
    kr_tags_path = Path("data/KR_tags.parquet")
    if not kr_tags_path.exists():
        print(f"[ERROR] {kr_tags_path} file not found.")
        print("        Please check if data/KR_tags.parquet exists.")
        return

    print(f"\n[1/4] Loading KR_tags.parquet...")
    try:
        df = pd.read_parquet(kr_tags_path)
        print(f"      [OK] Loaded: {len(df):,} tags")
    except Exception as e:
        print(f"[ERROR] 파일 로드 실패: {e}")
        return

    # category 필드 확인
    if 'category' not in df.columns:
        print("[ERROR] 'category' 필드가 KR_tags.parquet에 없습니다.")
        print(f"        사용 가능한 컬럼: {df.columns.tolist()}")
        return

    if 'tag' not in df.columns:
        print("[ERROR] 'tag' 필드가 KR_tags.parquet에 없습니다.")
        print(f"        사용 가능한 컬럼: {df.columns.tolist()}")
        return

    # 1차 카테고리별 태그 수집
    print("\n[2/4] Extracting 1st categories and collecting tags...")
    category_tags_map: Dict[str, Set[str]] = defaultdict(set)
    total_categorized = 0
    no_category_count = 0

    for idx, row in df.iterrows():
        tag = row.get('tag')
        category = row.get('category')

        # tag가 없으면 건너뛰기
        if pd.isna(tag) or not isinstance(tag, str):
            continue

        # category가 없으면 "Unknown"으로 처리
        if pd.isna(category):
            category_tags_map["Unknown"].add(tag)
            no_category_count += 1
        else:
            primary_category = extract_primary_category(category)
            category_tags_map[primary_category].add(tag)
            total_categorized += 1

        # 진행 상황 출력 (10,000개마다)
        if (idx + 1) % 10000 == 0:
            print(f"      Processing... {idx + 1:,} / {len(df):,} ({(idx+1)/len(df)*100:.1f}%)")

    print(f"      [OK] Processing complete:")
    print(f"         - Categorized: {total_categorized:,} tags")
    print(f"         - No category: {no_category_count:,} tags (Unknown)")

    # Set을 List로 변환 및 정렬 (JSON 직렬화 가능하도록)
    print("\n[3/4] Sorting and converting data...")
    category_tags_list: Dict[str, List[str]] = {}
    category_counts: Dict[str, int] = {}

    for category, tags_set in category_tags_map.items():
        # 알파벳 순으로 정렬
        sorted_tags = sorted(list(tags_set))
        category_tags_list[category] = sorted_tags
        category_counts[category] = len(sorted_tags)

    # 카테고리를 태그 개수 기준 내림차순 정렬
    sorted_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)

    print(f"      [OK] {len(category_tags_list)} categories extracted")

    # 통계 정보
    print("\n      [Stats] Tags per category (Top 15):")
    for i, (cat, count) in enumerate(sorted_categories[:15], 1):
        print(f"         {i:2d}. {cat:30s}: {count:6,} tags")

    if len(sorted_categories) > 15:
        print(f"         ... and {len(sorted_categories) - 15} more categories")

    # JSON 저장
    print("\n[4/4] Saving JSON file...")
    output_dir = Path("data/ezmode")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "category_tags_index.json"

    # 저장할 데이터 구조
    output_data = {
        # 메인 데이터: 카테고리 → 태그 목록 (역인덱스)
        "index": category_tags_list,

        # 메타데이터
        "metadata": {
            "total_tags": len(df),
            "categorized_tags": total_categorized,
            "uncategorized_tags": no_category_count,
            "total_categories": len(category_tags_list),
            "category_counts": category_counts,
            "sorted_categories": [cat for cat, count in sorted_categories]
        }
    }

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        # 파일 크기 확인
        file_size = output_path.stat().st_size
        file_size_mb = file_size / 1024 / 1024

        print(f"      [OK] Saved: {output_path}")
        print(f"         File size: {file_size:,} bytes ({file_size_mb:.2f} MB)")

    except Exception as e:
        print(f"[ERROR] Failed to save file: {e}")
        return

    # 요약
    print("\n" + "=" * 60)
    print("[SUCCESS] 1st Category Extraction Complete")
    print("=" * 60)
    print(f"Output file: {output_path}")
    print(f"")
    print(f"[Summary]")
    print(f"   - Total tags: {len(df):,}")
    print(f"   - Categories: {len(category_tags_list):,}")
    print(f"   - Categorized tags: {total_categorized:,}")
    print(f"   - Unknown tags: {no_category_count:,}")
    print(f"")
    print(f"[Usage]")
    print(f"   1. Load category_tags_index.json in ezmode_step4.py")
    print(f"   2. Query: index[category] -> get all tags (O(1))")
    print(f"   3. Check: tag in index[category] -> belongs to category (O(n))")
    print(f"")
    print(f"[Performance]")
    print(f"   - Fast lookup using inverted index")
    print(f"   - Memory efficient (tag names only)")
    print("=" * 60)


def main():
    """메인 실행 함수"""
    extract_primary_categories()


if __name__ == "__main__":
    main()
