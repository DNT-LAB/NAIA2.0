from core import remote_api_server
from core.remote_api_server import RemoteBridge


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
    ]


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
    assert [row["tag"] for row in merged] == ["soccer ball", "kicking", "foot"]


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
    ]


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
    ]


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
    assert [row["tag"] for row in merged] == ["legs apart"]

    merged, _ = RemoteBridge._search_kr_tags_with_translation(
        bridge,
        "팬티를 억지로 잡아 내리다",
        8,
    )
    assert [row["tag"] for row in merged] == [
        "panty pull",
        "pulling own clothes",
        "pulling another's clothes",
    ]

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
    ]
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
    assert [row["tag"] for row in merged] == ["looking at screen"]
    assert calls == [
        "화면을 바라보다",
        "look at the screen",
        "looking at screen",
    ]


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
    bridge._search_kr_metadata_fallback = lambda query, limit=20: [
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
