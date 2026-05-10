from core.event_preset_service import EventPresetService


def test_event_preview_keeps_main_item_when_combo_omits_anchor():
    service = EventPresetService.__new__(EventPresetService)
    event = {
        "id": "looking_back",
        "tag": "looking back",
        "label": "looking back",
        "promptAtoms": ["looking back"],
        "observedCombos": [
            {
                "id": "combo-0",
                "prompt": "sitting, wariza",
                "tags": ["sitting", "wariza"],
            }
        ],
        "recommendedTags": [],
        "directRecommendedTags": [],
        "slots": {},
    }

    prompt = service._build_preview_from_event(
        event,
        "combo-0",
        [],
        rating="",
        person="",
    )

    assert prompt == "looking back, sitting, wariza"


def test_event_preview_does_not_duplicate_main_item_variant():
    service = EventPresetService.__new__(EventPresetService)
    event = {
        "id": "looking_back",
        "tag": "looking back",
        "label": "looking back",
        "promptAtoms": ["looking back"],
        "observedCombos": [
            {
                "id": "combo-0",
                "prompt": "looking_back, sitting",
                "tags": ["looking_back", "sitting"],
            }
        ],
        "recommendedTags": [],
        "directRecommendedTags": [],
        "slots": {},
    }

    prompt = service._build_preview_from_event(
        event,
        "combo-0",
        [],
        rating="",
        person="",
    )

    assert prompt == "looking_back, sitting"
