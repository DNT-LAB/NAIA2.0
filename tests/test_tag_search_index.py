import pandas as pd

from core.tag_search_index import TagSearchIndex


def test_tag_search_index_matches_korean_event_keywords(tmp_path):
    kr_path = tmp_path / "KR_tags.parquet"
    pd.DataFrame(
        [
            {
                "tag": "sitting",
                "count": 100,
                "category": "신체 > 자세",
                "desc": "의자나 바닥 등에 엉덩이를 대고 앉아있음.",
                "keywords": "<앉기>, 앉은 자세",
            },
            {
                "tag": "holding cup",
                "count": 50,
                "category": "행위 > 잡기",
                "desc": "컵을 들고 있는 모습임.",
                "keywords": "<컵들기>, 컵 잡기",
            },
            {
                "tag": "cafe",
                "count": 20,
                "category": "건물 > 상업",
                "desc": "카페 장소임.",
                "keywords": "<카페>",
            },
        ]
    ).to_parquet(kr_path, index=False)

    assets = {
        "tag_catalog.parquet": pd.DataFrame(
            [
                {"tag_id": 1, "tag_name": "sitting", "freq": 100},
                {"tag_id": 2, "tag_name": "holding cup", "freq": 50},
                {"tag_id": 3, "tag_name": "cafe", "freq": 20},
            ]
        ),
        "tag_category.parquet": pd.DataFrame(
            [
                {
                    "tag_id": 1,
                    "tag_name": "sitting",
                    "category": "event",
                    "source": "test",
                    "confidence": 1.0,
                    "priority_rank": 1,
                    "is_event": True,
                    "is_expression": False,
                    "is_clothing": False,
                    "is_color": False,
                },
                {
                    "tag_id": 2,
                    "tag_name": "holding cup",
                    "category": "event",
                    "source": "test",
                    "confidence": 1.0,
                    "priority_rank": 1,
                    "is_event": True,
                    "is_expression": False,
                    "is_clothing": False,
                    "is_color": False,
                },
                {
                    "tag_id": 3,
                    "tag_name": "cafe",
                    "category": "other",
                    "source": "test",
                    "confidence": 1.0,
                    "priority_rank": 5,
                    "is_event": False,
                    "is_expression": False,
                    "is_clothing": False,
                    "is_color": False,
                },
            ]
        ),
    }

    index = TagSearchIndex.from_event_preset_assets(assets, kr_tags_path=kr_path)

    assert index.search_tags("앉기", require_event=True)[:1] == ["sitting"]
    assert index.search_tags("컵들기", require_event=True)[:1] == ["holding cup"]
    assert index.search_tags("카페", require_event=True) == []
    assert index.search_tags("zzzz", require_event=True) == []

