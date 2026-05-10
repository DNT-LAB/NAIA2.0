import pandas as pd

from core.tag_search_index import TagSearchEntry, TagSearchIndex, normalize_search_query


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


def test_tag_search_index_builds_from_remote_raw_records():
    index = TagSearchIndex.from_raw_tag_records(
        {
            "sitting": {
                "_tag": "sitting",
                "freq": 100,
                "description": "의자나 바닥 등에 엉덩이를 대고 앉아있음.",
                "group": "Expression_Action",
                "subgroup": "posture",
                "keywords_kr": "<앉기>, 앉은 자세",
            },
            "hatsune miku": {
                "_tag": "hatsune miku",
                "_cat": "character",
                "freq": 200,
                "group": "character",
                "subgroup": "vocaloid",
                "keywords_kr": "하츠네 미쿠",
            },
            "mika pikazo": {
                "_tag": "mika pikazo",
                "_cat": "artist",
                "freq": 50,
                "group": "artist",
                "keywords_kr": "미카 피카조",
            },
        }
    )

    assert index.search_tags("앉기")[:1] == ["sitting"]
    assert index.search_tags("miku", cats={"character"}) == ["hatsune miku"]
    assert index.search_tags("miku", cats={"artist"}) == []


def test_tag_search_index_prefers_korean_metadata_for_normalized_duplicates():
    index = TagSearchIndex(
        [
            TagSearchEntry(
                tag="3_3",
                freq=112,
                category="Expression_Action",
                desc="Eyes that appear as kissy lips or a number three.",
                search_blob="3_3 Eyes that appear as kissy lips or a number three.",
            ),
            TagSearchEntry(
                tag="3 3",
                freq=0,
                category="표정/행동",
                desc="입술 모양이나 숫자 3처럼 보이는 눈.",
                keywords=("찡그린 눈",),
                search_blob="3 3 입술 모양 찡그린 눈",
            ),
        ]
    )

    entry = index._entries["3 3"]
    assert entry.freq == 112
    assert entry.desc == "입술 모양이나 숫자 3처럼 보이는 눈."
    assert index.search_tags("찡그린") == ["3 3"]


def test_tag_search_index_uses_candidate_index_for_keyword_queries(monkeypatch):
    entries = [
        TagSearchEntry(tag=f"noise tag {idx}", search_blob="unrelated filler")
        for idx in range(1000)
    ]
    entries.append(
        TagSearchEntry(
            tag="striped shirt",
            freq=200,
            source="KR_tags",
            desc="줄무늬가 있는 셔츠.",
            keywords=("줄무늬", "줄무늬 셔츠"),
            search_blob="striped shirt 줄무늬 줄무늬 셔츠",
        )
    )
    index = TagSearchIndex(entries)

    calls = 0
    original_score = TagSearchIndex._score

    def counting_score(*args):
        nonlocal calls
        calls += 1
        return original_score(*args)

    monkeypatch.setattr(TagSearchIndex, "_score", staticmethod(counting_score))

    assert index.search_tags("줄무늬")[:1] == ["striped shirt"]
    assert calls < 20


def test_tag_search_index_ignores_prompt_weight_fragments(monkeypatch):
    index = TagSearchIndex(
        [
            TagSearchEntry(tag="monochrome", freq=100),
            TagSearchEntry(tag="artist collaboration", freq=50),
        ]
    )

    calls = 0
    original_score = TagSearchIndex._score

    def counting_score(*args):
        nonlocal calls
        calls += 1
        return original_score(*args)

    monkeypatch.setattr(TagSearchIndex, "_score", staticmethod(counting_score))

    assert normalize_search_query("0.4") == ""
    assert normalize_search_query("0.4::") == ""
    assert normalize_search_query("-1.5::") == ""
    assert normalize_search_query(".4::") == ""
    assert normalize_search_query("-0.45:: monochrome") == "monochrome"
    assert index.search_tags("0.4") == []
    assert index.search_tags("0.4::") == []
    assert index.search_tags("-1.5::") == []
    assert index.search_tags("-0.45:: monochrome") == ["monochrome"]
    assert calls == 1


def test_tag_search_index_does_not_expand_category_tokens(monkeypatch):
    entries = [
        TagSearchEntry(
            tag=f"sample creator {idx}",
            freq=idx,
            cat="artist",
            category="artist",
            search_blob=f"sample creator {idx} artist",
        )
        for idx in range(1000)
    ]
    entries.append(TagSearchEntry(tag="artist name", freq=100, search_blob="artist name"))
    index = TagSearchIndex(entries)

    calls = 0
    original_score = TagSearchIndex._score

    def counting_score(*args):
        nonlocal calls
        calls += 1
        return original_score(*args)

    monkeypatch.setattr(TagSearchIndex, "_score", staticmethod(counting_score))

    assert index.search_tags("artist") == ["artist name"]
    assert calls < 20


def test_tag_search_index_drops_fast_cache_misses_without_scoring(monkeypatch):
    index = TagSearchIndex(
        [
            TagSearchEntry(tag=f"known tag {idx}", search_blob=f"known tag {idx}")
            for idx in range(1000)
        ]
    )

    calls = 0
    original_score = TagSearchIndex._score

    def counting_score(*args):
        nonlocal calls
        calls += 1
        return original_score(*args)

    monkeypatch.setattr(TagSearchIndex, "_score", staticmethod(counting_score))

    assert index.search_tags("artlimorino831") == []
    assert calls == 0


def test_tag_search_index_prioritizes_korean_keyword_over_description_text():
    index = TagSearchIndex(
        [
            TagSearchEntry(
                tag="multicolored hair",
                freq=408728,
                desc="두 가지 이상의 색으로 이루어진 머리.",
                keywords=("여러 색 머리",),
                search_blob="multicolored hair 두 가지 이상의 색으로 이루어진 머리",
            ),
            TagSearchEntry(
                tag="eggplant",
                freq=1112,
                desc="보라색 가지 열매.",
                keywords=("가지",),
                search_blob="eggplant 가지",
            ),
            TagSearchEntry(
                tag="branch",
                freq=20000,
                desc="나무에서 뻗은 가지.",
                keywords=("나뭇가지",),
                search_blob="branch 나뭇가지",
            ),
        ]
    )

    assert index.search_tags("가지", limit=5)[0] == "eggplant"


def test_tag_search_index_matches_compact_hangul_keywords_without_losing_spaced_rank():
    index = TagSearchIndex(
        [
            TagSearchEntry(
                tag="fishnets",
                freq=69403,
                desc="다이아몬드 모양의 그물망 소재임.",
                keywords=("망사스타킹", "피쉬넷"),
                search_blob="fishnets 망사스타킹 피쉬넷",
            ),
            TagSearchEntry(
                tag="fishnet pantyhose",
                freq=29781,
                desc="그물 모양으로 짜인 팬티스타킹임.",
                keywords=("팬티스타킹", "망사 스타킹"),
                search_blob="fishnet pantyhose 팬티스타킹 망사 스타킹",
            ),
            TagSearchEntry(
                tag="fishnet bodystocking",
                freq=754,
                desc="망사 소재로 된 바디 스타킹.",
                keywords=("바디 스타킹", "망사 바디 스타킹"),
                search_blob="fishnet bodystocking 망사 바디 스타킹",
            ),
        ]
    )

    compact_results = index.search_tags("망사스타킹", limit=5)
    assert compact_results[:2] == ["fishnets", "fishnet pantyhose"]
    assert index.search_tags("망사 스타킹", limit=5)[0] == "fishnet pantyhose"


def test_tag_search_entrypoints_split_fast_and_semantic_recall():
    entries = [
        TagSearchEntry(
            tag=f"large breasts variant {idx}",
            freq=100 - idx,
            search_blob=f"large breasts variant {idx}",
        )
        for idx in range(40)
    ]
    entries.append(
        TagSearchEntry(
            tag="medium support meme",
            freq=500,
            desc="A meme referencing [[large_breasts]] support.",
            search_blob="A meme referencing [[large_breasts]] support.",
        )
    )
    index = TagSearchIndex(entries)

    fast_tags = index.search_tags("large breasts", limit=5)
    semantic_tags = [result.tag for result in index.search_semantic("large breasts", limit=None)]

    assert "medium support meme" not in fast_tags
    assert "medium support meme" in semantic_tags


def test_event_semantic_entrypoint_requires_event_by_default():
    index = TagSearchIndex(
        [
            TagSearchEntry(
                tag="sitting",
                freq=100,
                is_event=True,
                keywords=("앉기",),
                search_blob="sitting 앉기",
            ),
            TagSearchEntry(
                tag="cafe",
                freq=200,
                is_event=False,
                keywords=("카페",),
                search_blob="cafe 카페",
            ),
        ]
    )

    assert index.search_tags("카페") == ["cafe"]
    assert index.search_event_semantic("카페") == []
    assert [result.tag for result in index.search_event_semantic("앉기")] == ["sitting"]
