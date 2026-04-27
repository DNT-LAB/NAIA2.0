import json

import pandas as pd

from core.tag_knowledge import apply_translation_overrides, merge_parquet_tag_records


def test_parquet_merge_replaces_english_interactive_description(tmp_path):
    kr_path = tmp_path / "KR_tags.parquet"
    pd.DataFrame(
        [
            {
                "tag": "striped",
                "count": 1000,
                "category": "패턴",
                "desc": "줄무늬 패턴.",
                "keywords": "<무늬>, 줄무늬",
            },
            {
                "tag": "black_skirt",
                "count": 2000,
                "category": "패션 > 하의",
                "desc": "검은색 스커트.",
                "keywords": "<스커트>, 검은 치마",
            },
        ]
    ).to_parquet(kr_path, index=False)

    raw = {
        "striped": {
            "_tag": "striped",
            "freq": 900,
            "description": "This tag is too broad.",
            "keywords_kr": "",
            "group": "Clothing_Wear",
            "subgroup": "patterns",
            "relations": {"children": ["striped shirt"]},
        },
        "black skirt": {
            "_tag": "black skirt",
            "freq": 1800,
            "description": "",
            "keywords_kr": "",
            "group": "Clothing_Wear",
            "subgroup": "attire",
        },
    }

    stats = merge_parquet_tag_records(raw, [(kr_path, 1)])

    assert stats.added == 0
    assert stats.records_updated == 2
    assert stats.description_replaced == 1
    assert stats.description_filled == 1
    assert stats.keywords_filled == 2
    assert raw["striped"]["description"] == "줄무늬 패턴."
    assert raw["striped"]["keywords_kr"] == "<무늬>, 줄무늬"
    assert raw["striped"]["relations"] == {"children": ["striped shirt"]}
    assert raw["black skirt"]["description"] == "검은색 스커트."
    assert raw["black skirt"]["_kw_lower"] == "스커트, 검은 치마"


def test_parquet_merge_preserves_existing_korean_description(tmp_path):
    kr_path = tmp_path / "KR_tags.parquet"
    pd.DataFrame(
        [
            {
                "tag": "striped shirt",
                "count": 100,
                "category": "패션 > 상의",
                "desc": "다른 한국어 설명.",
                "keywords": "<셔츠>, 스트라이프 셔츠",
            }
        ]
    ).to_parquet(kr_path, index=False)

    raw = {
        "striped shirt": {
            "_tag": "striped shirt",
            "description": "줄무늬 패턴이 있는 셔츠임.",
            "keywords_kr": "<셔츠>, 줄무늬 셔츠",
        }
    }

    stats = merge_parquet_tag_records(raw, [(kr_path, 1)])

    assert stats.records_updated == 0
    assert raw["striped shirt"]["description"] == "줄무늬 패턴이 있는 셔츠임."
    assert raw["striped shirt"]["keywords_kr"] == "<셔츠>, 줄무늬 셔츠"


def test_translation_overrides_patch_missing_parquet_base_tags(tmp_path):
    overrides_path = tmp_path / "tag_translation_overrides.json"
    overrides_path.write_text(
        json.dumps(
            {
                "translations": {
                    "striped": {
                        "description": "줄무늬 패턴.",
                        "keywords_kr": "<무늬>, 줄무늬",
                        "source": "test",
                    },
                    "manual only": {
                        "description": "수동 추가 태그.",
                        "keywords_kr": "<수동>",
                        "group": "meta",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    raw = {
        "striped": {
            "_tag": "striped",
            "description": "This tag is too broad.",
            "keywords_kr": "",
            "group": "Clothing_Wear",
        }
    }

    stats = apply_translation_overrides(raw, overrides_path)

    assert stats.records_seen == 2
    assert stats.updated == 1
    assert stats.added == 1
    assert raw["striped"]["description"] == "줄무늬 패턴."
    assert raw["striped"]["keywords_kr"] == "<무늬>, 줄무늬"
    assert raw["manual only"]["description"] == "수동 추가 태그."
    assert raw["manual only"]["group"] == "meta"
