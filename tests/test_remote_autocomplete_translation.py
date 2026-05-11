from core import remote_api_server
from core.remote_api_server import RemoteBridge


def assert_autocomplete_candidate_schema(
    row,
    candidate_type,
    source,
    insert_policy,
    *,
    confidence=None,
):
    assert row["candidateType"] == candidate_type
    assert row["source"] == source
    assert row["insertPolicy"] == insert_policy
    assert row["candidate"]["type"] == candidate_type
    assert row["candidate"]["source"] == source
    assert row["candidate"]["insertPolicy"] == insert_policy
    assert row["candidate"]["confidence"] == row["confidence"]
    assert row["candidate"]["score"] == row["autocompleteScore"]
    if confidence is not None:
        assert row["confidence"] == confidence


def assert_translation_hints_are_tail(rows):
    first_hint = next(
        (index for index, row in enumerate(rows) if row["candidateType"] == "translation_hint"),
        None,
    )
    assert first_hint is not None
    assert all(row["candidateType"] != "translation_hint" for row in rows[:first_hint])
    assert all(row["candidateType"] == "translation_hint" for row in rows[first_hint:])


def assert_prompt_phrase(row, tag):
    assert row["tag"] == tag
    assert_autocomplete_candidate_schema(
        row,
        "prompt_phrase",
        "phrase_normalizer",
        "default",
    )


def test_phrase_normalizer_eval_promotes_quality_phrases(monkeypatch):
    samples = [
        {
            "query": "팔을 들어올리다",
            "translation": "raise one arms",
            "must_include": ["arms raised", "raising arms"],
            "must_not_top": "raise one arms",
        },
        {
            "query": "와인잔을 들고 있음",
            "translation": "holding a wine glass in hand",
            "must_include": ["holding wine glass"],
            "must_not_top": "holding a wine glass in hand",
        },
        {
            "query": "손목에 따로 달린 소매",
            "translation": "separate sleeves attached to the wrist",
            "must_include": ["detached sleeves", "wrist cuffs"],
            "must_not_top": "separate sleeves attached to the wrist",
        },
    ]

    translations = {sample["query"]: sample["translation"] for sample in samples}
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: translations.get(query, ""),
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    bridge._search_kr_tags = lambda query, limit=20: []
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: []

    for sample in samples:
        merged, translated = RemoteBridge._search_kr_tags_with_translation(
            bridge,
            sample["query"],
            8,
        )

        assert translated == sample["translation"]
        tags = [row["tag"] for row in merged]
        assert tags[0] != sample["must_not_top"]
        assert all(tag in tags for tag in sample["must_include"])
        for tag in sample["must_include"]:
            row = next(item for item in merged if item["tag"] == tag)
            assert_prompt_phrase(row, tag)
        hint = next(item for item in merged if item["tag"] == sample["must_not_top"])
        assert hint["candidateType"] == "translation_hint"
        assert hint["insertPolicy"] == "manual"
        assert min(
            row["autocompleteScore"]
            for row in merged
            if row["candidateType"] == "prompt_phrase"
        ) > hint["autocompleteScore"]
        assert_translation_hints_are_tail(merged)


def test_autocomplete_translation_merges_delayed_english_candidates(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "fishnet stockings",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}

    rows = {
        "망사스타킹": [
            {"tag": f"base{i}", "count": 100 - i, "desc": "", "group": "", "cat": ""}
            for i in range(8)
        ],
        "fishnet stockings": [],
        "fishnet": [
            {
                "tag": "fishnet pantyhose",
                "count": 10,
                "desc": "translated",
                "group": "legwear",
                "cat": "",
            }
        ],
        "stockings": [
            {
                "tag": "stockings only",
                "count": 5,
                "desc": "translated",
                "group": "misc",
                "cat": "",
            }
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "망사스타킹",
        12,
    )

    assert translated == "fishnet stockings"
    assert [row["tag"] for row in merged] == [
        "base0",
        "base1",
        "base2",
        "base3",
        "base4",
        "base5",
        "fishnet pantyhose",
        "stockings only",
        "base6",
        "base7",
        "fishnet stockings",
    ]
    assert_autocomplete_candidate_schema(
        merged[0],
        "tag_exact",
        "tag_index",
        "default",
        confidence=1.0,
    )
    assert_autocomplete_candidate_schema(
        merged[6],
        "tag_translated",
        "translation_search",
        "default",
        confidence=0.75,
    )
    assert "rankScore" in merged[6]["candidate"]
    assert merged[-1]["_wc_type"] == "fallback_recommended"
    assert_autocomplete_candidate_schema(
        merged[-1],
        "translation_hint",
        "translation_fallback",
        "manual",
        confidence=0.2,
    )


def test_autocomplete_translation_result_cache_reuses_scored_rows(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "fishnet stockings",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    bridge._autocomplete_result_cache = {}

    calls = []
    rows = {
        "망사스타킹": [],
        "fishnet stockings": [],
        "fishnet": [
            {
                "tag": "fishnet pantyhose",
                "count": 10,
                "desc": "translated",
                "group": "legwear",
                "cat": "",
            }
        ],
    }

    def search(query, limit=20):
        calls.append((query, limit))
        return [dict(row) for row in rows.get(query, [])[:limit]]

    bridge._search_kr_tags = search
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: []

    first, first_translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "망사스타킹",
        12,
    )
    call_count = len(calls)
    first[0]["tag"] = "mutated"

    second, second_translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "망사스타킹",
        12,
    )

    assert first_translated == second_translated == "fishnet stockings"
    assert len(calls) == call_count
    assert second[0]["tag"] == "fishnet pantyhose"
    assert second is not first
    assert second[0] is not first[0]


def test_autocomplete_translation_filters_noisy_categories_for_hangul_queries(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    bridge._autocomplete_result_cache = {}
    bridge._search_kr_tags = lambda query, limit=20: [
        {
            "tag": "white shirt",
            "count": 100,
            "desc": "",
            "group": "패션 > 상의",
            "cat": "",
        },
        {
            "tag": "sample character",
            "count": 100000,
            "desc": "",
            "group": "캐릭터 > 테스트",
            "cat": "character",
        },
    ]
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: []

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "흰 셔츠",
        12,
    )

    assert translated == ""
    assert [row["tag"] for row in merged] == ["white shirt"]


def test_autocomplete_translation_expands_sentence_to_phrase_and_action(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "kick a soccer ball with foot",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}

    rows = {
        "발로 축구공을 차다": [],
        "kick a soccer ball with foot": [],
        "soccer ball": [
            {
                "tag": "soccer ball",
                "count": 100,
                "desc": "",
                "group": "object",
                "cat": "",
            }
        ],
        "kicking": [
            {
                "tag": "kicking",
                "count": 50,
                "desc": "",
                "group": "action",
                "cat": "",
            }
        ],
        "foot": [
            {
                "tag": "foot",
                "count": 25,
                "desc": "",
                "group": "body",
                "cat": "",
            }
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]

    assert RemoteBridge._translation_search_queries(
        bridge,
        "kick a soccer ball with foot",
    )[:4] == [
        "kick a soccer ball with foot",
        "kicking soccer ball",
        "soccer ball",
        "kicking",
    ]

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "발로 축구공을 차다",
        12,
    )

    assert translated == "kick a soccer ball with foot"
    assert [row["tag"] for row in merged] == [
        "soccer ball",
        "kicking",
        "foot",
        "kicking soccer ball",
        "kick a soccer ball with foot",
    ]
    assert_prompt_phrase(merged[3], "kicking soccer ball")
    assert merged[-1]["_wc_type"] == "fallback_recommended"
    assert_translation_hints_are_tail(merged)


def test_autocomplete_translation_expands_pose_relation_and_alias(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "he placed his hands on his waist.",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}

    rows = {
        "자신의 허리 위에 손을 올림": [],
        "he placed his hands on his waist": [],
        "placed hands on waist": [],
        "hands on own hips": [
            {
                "tag": "hands on own hips",
                "count": 100,
                "desc": "",
                "group": "pose",
                "cat": "",
            }
        ],
        "hands on hips": [
            {
                "tag": "hands on hips",
                "count": 75,
                "desc": "",
                "group": "pose",
                "cat": "",
            }
        ],
        "hands on waist": [
            {
                "tag": "hands on another's waist",
                "count": 25,
                "desc": "",
                "group": "pose",
                "cat": "",
            }
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]

    queries = RemoteBridge._translation_search_queries(
        bridge,
        "he placed his hands on his waist.",
    )
    assert queries[:8] == [
        "he placed his hands on his waist",
        "placed hands on waist",
        "hands on own hips",
        "hands on own hip",
        "hands on hips",
        "hands on hip",
        "hands on own waist",
        "hands on waist",
    ]
    assert "his hands" not in queries
    assert "placed his" not in queries

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "자신의 허리 위에 손을 올림",
        12,
    )

    assert translated == "he placed his hands on his waist."
    assert [row["tag"] for row in merged] == [
        "hands on own hips",
        "hands on hips",
        "hands on another's waist",
        "placed hands on waist",
    ]
    assert merged[-1]["_wc_type"] == "fallback_recommended"


def test_autocomplete_translation_handles_headless_relation_samples(monkeypatch):
    assert RemoteBridge._translation_search_queries(
        None,
        "hold a flower and blow on it",
    ) == [
        "hold a flower and blow on it",
        "hold flower blow",
        "holding flower",
        "blowing",
        "holding",
        "flower",
    ]

    assert RemoteBridge._translation_search_queries(
        None,
        "sing a song with a blue umbrella",
    ) == [
        "sing a song with a blue umbrella",
        "singing",
        "blue umbrella",
        "blue",
        "umbrella",
    ]

    bird_queries = RemoteBridge._translation_search_queries(
        None,
        "a little bird is chirping on my hand",
    )
    assert bird_queries[:5] == [
        "a little bird is chirping on my hand",
        "little bird chirping on hand",
        "bird on hand",
        "little bird",
        "bird on",
    ]
    assert "chirping on hand" not in bird_queries
    assert "bird on own hand" not in bird_queries

    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "hold a flower and blow on it",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "꽃을 들고 입김을 불다": [],
        "holding flower": [
            {
                "tag": "holding flower",
                "count": 100,
                "desc": "",
                "group": "pose",
                "cat": "",
            }
        ],
        "holding": [
            {"tag": "holding ball", "count": 90, "desc": "", "group": "", "cat": ""},
            {"tag": "holding wand", "count": 80, "desc": "", "group": "", "cat": ""},
            {"tag": "holding paper", "count": 70, "desc": "", "group": "", "cat": ""},
        ],
        "blowing": [
            {"tag": "blowing", "count": 60, "desc": "", "group": "action", "cat": ""}
        ],
        "flower": [
            {"tag": "flower", "count": 50, "desc": "", "group": "object", "cat": ""}
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "꽃을 들고 입김을 불다",
        8,
    )

    assert translated == "hold a flower and blow on it"
    assert [row["tag"] for row in merged] == [
        "holding flower",
        "blowing",
        "hold flower and blow on",
    ]
    assert merged[-1]["_wc_type"] == "fallback_recommended"


def test_autocomplete_translation_handles_nsfw_domain_samples(monkeypatch):
    assert RemoteBridge._translation_search_queries(
        None,
        "forcing a woman's legs apart",
    ) == [
        "forcing a woman's legs apart",
        "forcing legs apart",
        "legs apart",
        "legs",
    ]

    assert RemoteBridge._translation_search_queries(
        None,
        "pull down one's panties by force",
    )[:7] == [
        "pull down one's panties by force",
        "pull down panties force",
        "panty pull",
        "pulling own clothes",
        "pulling another's clothes",
        "pulling pants down",
        "pulling panties",
    ]

    assert RemoteBridge._translation_search_queries(
        None,
        "lightly caress the male organ with one's hand",
    )[:5] == [
        "lightly caress the male organ with one's hand",
        "lightly caress male organ hand",
        "touching penis",
        "hand on penis",
        "penis",
    ]

    assert RemoteBridge._translation_search_queries(
        None,
        "express breast milk from the breast",
    )[:4] == [
        "express breast milk from the breast",
        "breast milking",
        "lactation",
        "breast milk",
    ]

    translations = {
        "여성의 다리를 강제로 벌림": "forcing a woman's legs apart",
        "팬티를 억지로 잡아 내리다": "pull down one's panties by force",
        "남성기를 손으로 가볍게 어루만지다": "lightly caress the male organ with one's hand",
        "가슴에서 모유를 짜다": "express breast milk from the breast",
    }
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: translations.get(query, ""),
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "여성의 다리를 강제로 벌림": [],
        "legs apart": [
            {"tag": "legs apart", "count": 100, "desc": "", "group": "", "cat": ""}
        ],
        "팬티를 억지로 잡아 내리다": [],
        "panty pull": [
            {"tag": "panty pull", "count": 100, "desc": "", "group": "", "cat": ""}
        ],
        "pulling own clothes": [
            {
                "tag": "pulling own clothes",
                "count": 90,
                "desc": "",
                "group": "",
                "cat": "",
            }
        ],
        "pulling another's clothes": [
            {
                "tag": "pulling another's clothes",
                "count": 80,
                "desc": "",
                "group": "",
                "cat": "",
            }
        ],
        "남성기를 손으로 가볍게 어루만지다": [],
        "touching penis": [
            {"tag": "touching penis", "count": 100, "desc": "", "group": "", "cat": ""}
        ],
        "hand on penis": [
            {"tag": "hand on penis", "count": 90, "desc": "", "group": "", "cat": ""}
        ],
        "penis": [
            {"tag": "penis nipples", "count": 80, "desc": "", "group": "", "cat": ""},
            {"tag": "penis", "count": 70, "desc": "", "group": "", "cat": ""},
        ],
        "가슴에서 모유를 짜다": [],
        "breast milking": [
            {"tag": "breast milking", "count": 100, "desc": "", "group": "", "cat": ""}
        ],
        "lactation": [
            {"tag": "lactation", "count": 90, "desc": "", "group": "", "cat": ""}
        ],
        "breast milk": [
            {
                "tag": "iced latte with breast milk (meme)",
                "count": 80,
                "desc": "",
                "group": "",
                "cat": "",
            },
            {"tag": "breast milk", "count": 70, "desc": "", "group": "", "cat": ""},
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]

    merged, _ = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "여성의 다리를 강제로 벌림",
        8,
    )
    assert [row["tag"] for row in merged] == [
        "legs apart",
        "forcing a woman's legs apart",
    ]
    assert merged[-1]["_wc_type"] == "fallback_recommended"

    merged, _ = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "팬티를 억지로 잡아 내리다",
        8,
    )
    assert [row["tag"] for row in merged] == [
        "panty pull",
        "pulling own clothes",
        "pulling another's clothes",
        "pulling pants down",
        "pulling panties",
        "pull down one panties by force",
    ]
    assert_prompt_phrase(merged[3], "pulling pants down")
    assert_prompt_phrase(merged[4], "pulling panties")
    assert merged[-1]["_wc_type"] == "fallback_recommended"
    assert_translation_hints_are_tail(merged)

    merged, _ = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "남성기를 손으로 가볍게 어루만지다",
        8,
    )
    assert [row["tag"] for row in merged[:4]] == [
        "touching penis",
        "hand on penis",
        "penis",
        "penis nipples",
    ]

    merged, _ = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "가슴에서 모유를 짜다",
        8,
    )
    assert [row["tag"] for row in merged[:4]] == [
        "breast milking",
        "lactation",
        "breast milk",
        "iced latte with breast milk (meme)",
    ]


def test_autocomplete_translation_handles_action_object_samples():
    samples = {
        "hold a cup in hand": [
            "hold a cup in hand",
            "holding cup",
            "holding",
            "cup",
            "hand",
        ],
        "walk in the rain holding an umbrella": [
            "walk in the rain holding an umbrella",
            "walking in rain",
            "holding umbrella",
            "walking",
            "holding",
            "rain",
            "umbrella",
        ],
        "hold a gun and aim": [
            "hold a gun and aim",
            "holding gun",
            "aiming",
            "holding",
            "gun",
        ],
        "lie on bed and sleep": [
            "lie on bed and sleep",
            "lying on bed",
            "sleeping",
            "lying",
            "bed",
        ],
        "put hand on chest": [
            "put hand on chest",
            "hand on chest",
            "hand on",
            "on chest",
            "hand",
            "chest",
        ],
        "look at the screen": [
            "look at the screen",
            "looking at screen",
            "looking",
            "screen",
        ],
    }

    for translated, expected in samples.items():
        queries = RemoteBridge._translation_search_queries(None, translated)
        assert queries == expected
        assert "rain holding" not in queries
        assert "putting hand" not in queries


def test_autocomplete_translation_falls_back_by_query_level(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "pulling the hem of clothes",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "옷 끝자락을 잡아당기기": [],
        "pulling the hem of clothes": [],
        "pulling hem": [],
        "pulling clothes": [
            {"tag": "pulling own clothes", "count": 100, "desc": "", "group": "", "cat": ""},
            {"tag": "pulling another's clothes", "count": 80, "desc": "", "group": "", "cat": ""},
        ],
        "pulling": [
            {"tag": "pulling", "count": 70, "desc": "", "group": "", "cat": ""},
        ],
        "hem": [
            {"tag": "hemokinesis", "count": 60, "desc": "", "group": "", "cat": ""},
        ],
        "clothes": [
            {"tag": "clothes grab", "count": 50, "desc": "", "group": "", "cat": ""},
        ],
    }
    calls = []

    def fake_search(query, limit=20):
        calls.append(query)
        return rows.get(query, [])[:limit]

    bridge._search_kr_tags = fake_search

    assert RemoteBridge._translation_search_queries(
        None,
        "pulling the hem of clothes",
    ) == [
        "pulling the hem of clothes",
        "pulling hem",
        "pulling clothes",
        "pulling",
        "hem",
        "clothes",
    ]

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "옷 끝자락을 잡아당기기",
        12,
    )

    assert translated == "pulling the hem of clothes"
    assert [row["tag"] for row in merged] == [
        "pulling own clothes",
        "pulling another's clothes",
        "pulling hem",
        "pulling clothes",
        "pulling the hem of clothes",
    ]
    assert_prompt_phrase(merged[2], "pulling hem")
    assert_prompt_phrase(merged[3], "pulling clothes")
    assert merged[-1]["_wc_type"] == "fallback_recommended"
    assert_translation_hints_are_tail(merged)
    assert calls == [
        "옷 끝자락을 잡아당기기",
        "pulling the hem of clothes",
        "pulling hem",
        "pulling clothes",
    ]


def test_autocomplete_translation_generates_action_relation_query(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "look at the screen",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "화면을 바라보다": [],
        "look at the screen": [],
        "looking at screen": [
            {"tag": "looking at screen", "count": 100, "desc": "", "group": "", "cat": ""},
        ],
        "looking": [
            {"tag": "looking at viewer", "count": 90, "desc": "", "group": "", "cat": ""},
        ],
    }
    calls = []

    def fake_search(query, limit=20):
        calls.append(query)
        return rows.get(query, [])[:limit]

    bridge._search_kr_tags = fake_search

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "화면을 바라보다",
        12,
    )

    assert translated == "look at the screen"
    assert [row["tag"] for row in merged] == ["looking at screen", "look at the screen"]
    assert merged[-1]["_wc_type"] == "fallback_recommended"
    assert calls == [
        "화면을 바라보다",
        "look at the screen",
        "looking at screen",
    ]


def test_autocomplete_translation_keeps_recommended_tail_when_results_fill_limit(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "black book and crystal ball",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "검은 책과 수정구": [],
        "black book and crystal ball": [
            {"tag": "crystal ball", "count": 811, "desc": "", "group": "Food_Object", "cat": ""},
            {"tag": "grief seed", "count": 87, "desc": "", "group": "Food_Object", "cat": ""},
            {"tag": "dark orb (madoka magica)", "count": 366, "desc": "", "group": "copyright", "cat": ""},
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: []

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "검은 책과 수정구",
        3,
    )

    assert translated == "black book and crystal ball"
    assert [row["tag"] for row in merged] == [
        "crystal ball",
        "grief seed",
        "black book and crystal ball",
    ]
    assert merged[-1]["_wc_type"] == "fallback_recommended"


def test_autocomplete_translation_tail_recommended_skips_duplicate_exact_match(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "fishnet stockings",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "망사 스타킹": [],
        "fishnet stockings": [
            {"tag": "fishnet stockings", "count": 100, "desc": "", "group": "", "cat": ""},
            {"tag": "fishnet pantyhose", "count": 80, "desc": "", "group": "", "cat": ""},
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: []

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "망사 스타킹",
        3,
    )

    assert translated == "fishnet stockings"
    assert [row["tag"] for row in merged] == [
        "fishnet stockings",
        "fishnet pantyhose",
        "fishnet",
    ]
    assert merged[-1]["_wc_type"] == "fallback_recommended"


def test_autocomplete_translation_reranks_metadata_over_low_level_generic_match(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "a small harp-like instrument",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "작은 하프 같은 악기": [],
        "a small harp like instrument": [],
        "small harp like": [],
        "harp like instrument": [],
        "harp": [
            {"tag": "harp", "count": 20000, "desc": "", "group": "", "cat": ""},
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: [
        {
            "tag": "lyre",
            "count": 798,
            "desc": "작은 현악기. 하프보다 작고 U자형인 경우가 많음.",
            "group": "Food_Object",
            "cat": "",
            "_metadata": True,
            "_metadata_score": 520,
        }
    ]

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "작은 하프 같은 악기",
        8,
    )

    assert translated == "a small harp-like instrument"
    assert [row["tag"] for row in merged[:2]] == ["lyre", "harp"]


def test_autocomplete_translation_prepends_recommended_for_actor_phrase_without_strong_tag(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "girl in white clothes",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "흰 의복을 입은 소녀": [],
        "girl in white clothes": [],
        "white clothes": [
            {"tag": "clothes", "count": 100, "desc": "", "group": "", "cat": ""},
            {"tag": "white camisole", "count": 80, "desc": "", "group": "", "cat": ""},
        ],
        "girl": [
            {"tag": "girl sandwich", "count": 50, "desc": "", "group": "", "cat": ""},
        ],
        "white": [
            {"tag": "white neckerchief", "count": 40, "desc": "", "group": "", "cat": ""},
        ],
        "clothes": [
            {"tag": "clothes", "count": 100, "desc": "", "group": "", "cat": ""},
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: [
        {
            "tag": "full-length zipper",
            "count": 1247,
            "desc": "목부터 배꼽 아래까지 이어지는 전체 길이 지퍼가 달린 원피스 의복을 입은 이미지.",
            "group": "Clothing_Wear",
            "cat": "",
            "_metadata": True,
            "_metadata_score": 725,
        }
    ]

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "흰 의복을 입은 소녀",
        8,
    )

    assert translated == "girl in white clothes"
    assert [row["tag"] for row in merged] == [
        "full-length zipper",
        "clothes",
        "white camisole",
        "girl in white clothes",
        "white clothes",
    ]
    assert_translation_hints_are_tail(merged)
    metadata_row = merged[0]
    assert_autocomplete_candidate_schema(
        metadata_row,
        "tag_metadata",
        "kr_metadata",
        "default",
        confidence=0.85,
    )
    assert metadata_row["candidate"]["rankScore"] == 725.0
    assert_autocomplete_candidate_schema(
        merged[-2],
        "translation_hint",
        "translation_fallback",
        "manual",
        confidence=0.2,
    )
    assert_autocomplete_candidate_schema(
        merged[-1],
        "translation_hint",
        "translation_fallback",
        "manual",
        confidence=0.2,
    )
    assert "girl" not in [row["tag"] for row in merged[:3]]


def test_autocomplete_translation_prepends_simple_recommended_for_short_noun_phrase(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "witch trial",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "마녀 재판": [],
        "witch trial": [],
        "witch": [
            {"tag": "witch hat", "count": 100, "desc": "", "group": "", "cat": ""},
        ],
        "trial": [
            {"tag": "trial of the sword", "count": 80, "desc": "", "group": "", "cat": ""},
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: []

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "마녀 재판",
        8,
    )

    assert translated == "witch trial"
    assert [row["tag"] for row in merged] == [
        "witch hat",
        "trial of the sword",
        "witch trial",
    ]
    assert_translation_hints_are_tail(merged)
    assert_autocomplete_candidate_schema(
        merged[-1],
        "translation_hint",
        "translation_fallback",
        "manual",
        confidence=0.2,
    )


def test_autocomplete_translation_prepends_simple_recommended_for_single_word_noun_translation(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "inquisition",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "이단 심문": [],
        "inquisition": [
            {
                "tag": "dragon age: inquisition",
                "count": 13,
                "desc": "",
                "group": "copyright",
                "cat": "",
            },
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: []

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "이단 심문",
        8,
    )

    assert translated == "inquisition"
    assert [row["tag"] for row in merged] == ["inquisition"]
    assert_translation_hints_are_tail(merged)
    assert merged[-1]["_wc_type"] == "fallback_recommended"


def test_autocomplete_translation_simple_recommended_removes_pronouns_but_keeps_actor_nouns(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "he is a boy witch trial",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "소년 마녀 재판": [],
        "he is a boy witch trial": [],
        "boy witch trial": [],
        "boy": [
            {"tag": "boy", "count": 100, "desc": "", "group": "", "cat": ""},
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]
    bridge._search_kr_metadata_fallback = lambda query, limit=20, allow_build=True: []

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "소년 마녀 재판",
        8,
    )

    assert translated == "he is a boy witch trial"
    assert [row["tag"] for row in merged] == ["boy", "boy witch trial"]
    assert_translation_hints_are_tail(merged)
    assert merged[-1]["_wc_type"] == "fallback_recommended"
    assert "he is a boy witch trial" not in [row["tag"] for row in merged]


def test_autocomplete_translation_does_not_build_metadata_index_on_live_path(monkeypatch):
    monkeypatch.setattr(
        remote_api_server,
        "korean_to_english",
        lambda query: "a sharp spear is aimed at the girl.",
    )
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._autocomplete_translation_cache = {}
    rows = {
        "날카로운 창이 소녀에게 노려지고 있음": [],
        "a sharp spear is aimed at the girl": [],
        "sharp spear": [],
        "spear": [
            {"tag": "spear", "count": 100, "desc": "", "group": "", "cat": ""},
        ],
        "sharp": [
            {"tag": "sharp teeth", "count": 80, "desc": "", "group": "", "cat": ""},
        ],
        "girl": [
            {"tag": "girl sandwich", "count": 50, "desc": "", "group": "", "cat": ""},
        ],
    }
    bridge._search_kr_tags = lambda query, limit=20: rows.get(query, [])[:limit]
    calls = []

    def fake_metadata(query, limit=20, *, allow_build=True):
        calls.append(allow_build)
        if allow_build:
            raise AssertionError("live autocomplete should not build metadata fallback index")
        return []

    bridge._search_kr_metadata_fallback = fake_metadata

    merged, translated = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "날카로운 창이 소녀에게 노려지고 있음",
        8,
    )

    assert translated == "a sharp spear is aimed at the girl."
    assert calls == [False]
    assert [row["candidateType"] for row in merged[:3]] == [
        "tag_translated",
        "tag_translated",
        "tag_translated",
    ]
    assert [row["tag"] for row in merged[-2:]] == [
        "a sharp spear is aimed at the girl",
        "sharp spear",
    ]
    assert_translation_hints_are_tail(merged)
