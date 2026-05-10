from pathlib import Path
import sys

import pytest

from core.clothes_preset_service import ClothesPresetService


def _fake_service(monkeypatch):
    pytest.importorskip("pyarrow")
    service = ClothesPresetService(Path.cwd())
    service._ensure_modules()
    modules = service._modules
    assert modules is not None

    combo_cls = modules.data_manager.ComboSummary
    combos = [
        combo_cls("shirt, skirt", 10, 2, ("shirt", "skirt")),
        combo_cls("shirt, long sleeves", 8, 2, ("long sleeves", "shirt")),
    ]
    service._combo_summaries = combos
    service._combo_summaries_ge2 = combos
    service._combo_tag_to_ids = {
        "shirt": {0, 1},
        "skirt": {0},
        "long sleeves": {1},
    }
    service._combo_id_lookup = {service._combo_id(c.clothing_combo): c for c in combos}
    service._combo_text_lookup = {c.clothing_combo: c for c in combos}

    service._assigned_slot_by_tag = {
        "hair ornament": "HEAD_NECK_FACE",
        "shirt": "UPPER_BODY",
        "long sleeves": "UPPER_BODY",
        "skirt": "WAIST_HIP",
    }
    service._assigned_group_by_tag = {
        "hair ornament": "hair accessories",
        "shirt": "tops",
        "long sleeves": "sleeves",
        "skirt": "bottoms",
    }
    region_cls = modules.data_manager.RegionTag
    region_rows = {
        "hair ornament": region_cls("hair ornament", "HEAD", "accessories", 6000, 1.0, "test"),
        "shirt": region_cls("shirt", "UPPER_BODY", "attire", 12000, 1.0, "test"),
        "long sleeves": region_cls("long sleeves", "UPPER_BODY", "attire", 9000, 1.0, "test"),
        "skirt": region_cls("skirt", "WAIST", "attire", 11000, 1.0, "test"),
    }
    service._assigned_row_by_tag = region_rows
    service._slot_rows_cache = {slot: [] for slot in modules.engines.DISPLAY_SLOTS}
    service._slot_rows_cache["HEAD_NECK_FACE"] = [region_rows["hair ornament"]]
    service._slot_rows_cache["UPPER_BODY"] = [region_rows["shirt"], region_rows["long sleeves"]]
    service._slot_rows_cache["WAIST_HIP"] = [region_rows["skirt"]]
    service._tag_to_region = {}
    service._reco_by_seed = {}
    service._avoid_by_seed = {}
    service._pair_by_seed = {}
    service._conflict_pairs = set()
    service._conflict_exclusion_score = {}
    monkeypatch.setattr(service, "_ensure_ready", lambda: None)
    return service


def test_status_does_not_import_desktop_clothes_window():
    if "ui.clothes_preset.clothes_preset_window" in sys.modules:
        pytest.skip("desktop Clothes window already imported by another test")
    service = ClothesPresetService(Path.cwd())
    service.status()
    assert "ui.clothes_preset.clothes_preset_window" not in sys.modules


def test_bootstrap_does_not_import_desktop_clothes_window_when_data_available():
    if "ui.clothes_preset.clothes_preset_window" in sys.modules:
        pytest.skip("desktop Clothes window already imported by another test")
    service = ClothesPresetService(Path.cwd())
    if service.status()["dataAvailability"]["main"] != "ready":
        pytest.skip("real Clothes Preset data is not available")

    service.bootstrap({"comboLimit": 1, "itemLimit": 1})

    assert "ui.clothes_preset.clothes_preset_window" not in sys.modules


def test_prompt_fragment_stages_combo_tags_with_sources(monkeypatch):
    service = _fake_service(monkeypatch)
    combo_id = service._combo_id("shirt, skirt")

    result = service.prompt_fragment({
        "comboId": combo_id,
        "applyComboTags": True,
        "stagedItems": [
            {"tag": "hair ornament", "source": "direct"},
        ],
    })

    fragment = result["promptFragment"]
    assert fragment["tags"] == ["hair ornament", "shirt", "skirt"]
    assert fragment["prompt"] == "hair ornament, shirt, skirt"
    assert fragment["sources"]["combo"] == 2
    assert fragment["sources"]["direct"] == 1
    assert "1girl" not in fragment["tags"]


def test_bootstrap_defaults_browser_to_upper_body(monkeypatch):
    service = _fake_service(monkeypatch)

    result = service.bootstrap({"itemLimit": 5})

    assert result["selected"]["categoryId"] == "UPPER_BODY"
    assert result["browser"]["selected"]["categoryId"] == "UPPER_BODY"
    assert any(category["id"] == "UPPER_BODY" and category["selected"] for category in result["browser"]["categories"])


def test_browser_search_keeps_zero_match_clothes_groups(monkeypatch):
    service = _fake_service(monkeypatch)

    result = service.bootstrap({
        "categoryId": "UPPER_BODY",
        "subcategoryId": "sleeves",
        "itemSearch": "shirt",
        "itemLimit": 5,
    })

    upper_body = next(category for category in result["browser"]["categories"] if category["id"] == "UPPER_BODY")
    assert upper_body["count"] == 2
    assert upper_body["matchedCount"] == 1
    assert upper_body["disabled"] is False

    subcategories = {item["id"]: item for item in result["browser"]["subcategories"]}
    assert result["browser"]["selected"]["subcategoryId"] == "tops"
    assert result["browser"]["subcategories"][0]["id"] == "tops"
    assert subcategories["tops"]["count"] == 1
    assert subcategories["tops"]["matchedCount"] == 1
    assert subcategories["tops"]["disabled"] is False
    assert subcategories["sleeves"]["count"] == 1
    assert subcategories["sleeves"]["matchedCount"] == 0
    assert subcategories["sleeves"]["disabled"] is True
    assert [item["tag"] for item in result["browser"]["items"]] == ["shirt"]


def test_browser_search_moves_from_zero_match_clothes_category(monkeypatch):
    service = _fake_service(monkeypatch)

    result = service.bootstrap({
        "categoryId": "HEAD_NECK_FACE",
        "itemSearch": "shirt",
        "itemLimit": 5,
    })

    assert result["browser"]["selected"]["categoryId"] == "UPPER_BODY"
    head = next(category for category in result["browser"]["categories"] if category["id"] == "HEAD_NECK_FACE")
    upper = next(category for category in result["browser"]["categories"] if category["id"] == "UPPER_BODY")
    assert head["disabled"] is True
    assert upper["disabled"] is False
    assert [item["tag"] for item in result["browser"]["items"]] == ["shirt"]


def test_browser_all_slot_search_returns_cross_slot_items(monkeypatch):
    service = _fake_service(monkeypatch)

    result = service.bootstrap({
        "categoryId": "HEAD_NECK_FACE",
        "itemSearch": "irt",
        "searchScope": "all",
        "itemLimit": 10,
    })

    tags = [item["tag"] for item in result["browser"]["items"]]
    assert result["browser"]["searchScope"] == "all"
    assert "shirt" in tags
    assert "skirt" in tags
    assert result["browser"]["selected"]["categoryId"] == "UPPER_BODY"


def test_combo_focus_does_not_stage_combo_tags(monkeypatch):
    service = _fake_service(monkeypatch)
    combo_id = service._combo_id("shirt, skirt")

    result = service.select({
        "action": "focusCombo",
        "comboId": combo_id,
        "stagedItems": [
            {"tag": "hair ornament", "source": "direct"},
        ],
        "comboLimit": 5,
    })

    assert result["selected"]["comboId"] == combo_id
    assert result["staged"]["tags"] == ["hair ornament"]
    assert result["promptFragment"]["tags"] == ["hair ornament"]


def test_combo_rows_hide_exact_staged_combo(monkeypatch):
    service = _fake_service(monkeypatch)
    combo_id = service._combo_id("shirt, skirt")

    result = service.combo_rows({
        "comboId": combo_id,
        "applyComboTags": True,
        "comboLimit": 5,
    })

    assert result["comboRows"]["hiddenExact"] == 1
    assert result["comboRows"]["shown"] == 0
    assert result["staged"]["tags"] == ["shirt", "skirt"]


def test_lucky_returns_combo_without_staging(monkeypatch):
    service = _fake_service(monkeypatch)
    modules = service._modules
    assert modules is not None
    combo_cls = modules.data_manager.ComboSummary
    lucky_combo = combo_cls(
        "hat, gloves, boots, cape",
        12,
        4,
        ("hat", "gloves", "boots", "cape"),
    )
    service._combo_summaries.append(lucky_combo)
    service._combo_id_lookup[service._combo_id(lucky_combo.clothing_combo)] = lucky_combo

    result = service.lucky({})

    assert result["lucky"]["tags"] == ["hat", "gloves", "boots", "cape"]
    assert result["lucky"]["basis"] == "global"
    assert result["promptFragment"]["tags"] == ["hat", "gloves", "boots", "cape"]
    assert "staged" not in result


def test_lucky_raises_when_staged_seed_has_no_combo(monkeypatch):
    service = _fake_service(monkeypatch)
    modules = service._modules
    assert modules is not None
    combo_cls = modules.data_manager.ComboSummary
    lucky_combo = combo_cls(
        "hat, gloves, boots, cape",
        12,
        4,
        ("hat", "gloves", "boots", "cape"),
    )
    service._combo_summaries.append(lucky_combo)

    with pytest.raises(ValueError, match="staged items"):
        service.lucky({
            "stagedItems": [
                {"tag": "hair ornament", "source": "direct"},
            ],
        })


def test_lucky_uses_staged_items_as_seed(monkeypatch):
    service = _fake_service(monkeypatch)
    modules = service._modules
    assert modules is not None
    combo_cls = modules.data_manager.ComboSummary
    seeded_combo = combo_cls(
        "shirt, jacket, necktie, long sleeves",
        25,
        4,
        ("jacket", "long sleeves", "necktie", "shirt"),
    )
    global_combo = combo_cls(
        "hat, gloves, boots, cape",
        12,
        4,
        ("hat", "gloves", "boots", "cape"),
    )
    seeded_index = len(service._combo_summaries)
    service._combo_summaries.extend([seeded_combo, global_combo])
    service._combo_id_lookup[service._combo_id(seeded_combo.clothing_combo)] = seeded_combo
    service._combo_id_lookup[service._combo_id(global_combo.clothing_combo)] = global_combo
    for tag in seeded_combo.tags:
        service._combo_tag_to_ids.setdefault(tag, set()).add(seeded_index)

    result = service.lucky({
        "stagedItems": [
            {"tag": "shirt", "source": "direct"},
        ],
    })

    assert result["lucky"]["tags"] == ["jacket", "long sleeves", "necktie", "shirt"]
    assert result["lucky"]["basis"] == "staged"
    assert result["lucky"]["seedTags"] == ["shirt"]
    assert result["lucky"]["matchedTags"] == ["shirt"]
    assert result["promptFragment"]["tags"] == ["jacket", "long sleeves", "necktie", "shirt"]
    assert "staged" not in result
