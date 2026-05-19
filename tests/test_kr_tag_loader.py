import json

from core.kr_tag_loader import load_kr_tag_records


def test_kr_tag_loader_uses_legacy_interactive_fallback(tmp_path):
    interactive = tmp_path / "legacy_desktop" / "ui" / "interactive"
    interactive.mkdir(parents=True)
    (interactive / "interactive").write_text(
        json.dumps({
            "test tag": {
                "freq": 7,
                "description": "fallback tag",
                "group": "general",
                "keywords_kr": "테스트",
            }
        }),
        encoding="utf-8",
    )

    result = load_kr_tag_records(tmp_path)

    assert result.interactive_count == 1
    assert result.raw["test tag"]["_tag"] == "test tag"
    assert not result.warnings
