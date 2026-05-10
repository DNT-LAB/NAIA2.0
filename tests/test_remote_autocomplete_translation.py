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
