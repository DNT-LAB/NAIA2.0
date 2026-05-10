from types import SimpleNamespace

from core.preset_input_bridge import PresetInputBridge, search_preset_paths
from core.prompt_context import PromptContext
from core.prompt_processor import PromptProcessor


class _EventService:
    def status(self):
        return {"dataAvailability": {"main": "ready", "message": "ready"}}

    def bootstrap(self, **_kwargs):
        return {
            "categories": [
                {
                    "id": "activity::standing",
                    "label": "Standing",
                    "count": 20,
                    "subcategories": [
                        {
                            "id": "activity::standing::solo",
                            "label": "Solo",
                            "count": 10,
                            "events": [
                                {
                                    "id": "standing",
                                    "tag": "standing",
                                    "label": "standing",
                                    "count": 10,
                                    "promptAtoms": ["standing"],
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    def select(self, _payload):
        return {
            "event": {
                "observedCombos": [
                    {
                        "id": "combo-0",
                        "label": "standing solo",
                        "prompt": "standing, solo, looking at viewer",
                        "tags": ["standing", "solo", "looking at viewer"],
                        "count": 7,
                    }
                ]
            }
        }


class _SparseEventService(_EventService):
    def bootstrap(self, **_kwargs):
        return {
            "categories": [
                {
                    "id": "activity",
                    "label": "Activity",
                    "subcategories": [
                        {
                            "id": "activity::solo",
                            "label": "Solo",
                            "events": [
                                {"id": "empty-event", "label": "empty-event"},
                                {"id": "combo-event", "label": "combo-event"},
                            ],
                        }
                    ],
                }
            ]
        }

    def select(self, payload):
        event_id = str(payload.get("eventId") or "")
        combos = []
        if event_id == "combo-event":
            combos = [
                {
                    "id": "combo-1",
                    "label": "combo event observed",
                    "prompt": "combo event, observed detail",
                    "tags": ["combo event", "observed detail"],
                    "count": 3,
                }
            ]
        return {"event": {"observedCombos": combos}}


class _NoisyComboEventService(_EventService):
    def bootstrap(self, **_kwargs):
        return {
            "categories": [
                {
                    "id": "gaze",
                    "label": "Gaze",
                    "subcategories": [
                        {
                            "id": "gaze_direction",
                            "label": "Gaze Direction",
                            "events": [
                                {
                                    "id": "looking_back",
                                    "tag": "looking_back",
                                    "label": "looking back",
                                    "promptAtoms": ["looking back"],
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    def select(self, _payload):
        return {
            "event": {
                "observedCombos": [
                    {
                        "id": "noise-single",
                        "label": "looking at viewer",
                        "prompt": "looking at viewer",
                        "tags": ["looking at viewer"],
                        "count": 100000,
                    },
                    {
                        "id": "noise-pair",
                        "label": "looking back, looking at viewer",
                        "prompt": "looking back, looking at viewer",
                        "tags": ["looking back", "looking at viewer"],
                        "count": 9000,
                    },
                    {
                        "id": "useful-pair",
                        "label": "looking back, sitting",
                        "prompt": "looking back, sitting",
                        "tags": ["looking back", "sitting"],
                        "count": 50,
                    },
                ]
            }
        }


class _NoisyWildcardEventService(_EventService):
    def bootstrap(self, **_kwargs):
        return {
            "categories": [
                {
                    "id": "gaze",
                    "label": "Gaze",
                    "subcategories": [
                        {
                            "id": "gaze_direction",
                            "label": "Gaze Direction",
                            "events": [
                                {"id": "viewer", "label": "looking at viewer"},
                                {
                                    "id": "looking_back",
                                    "label": "looking back",
                                    "promptAtoms": ["looking back"],
                                },
                            ],
                        }
                    ],
                }
            ]
        }

    def select(self, payload):
        event_id = str(payload.get("eventId") or "")
        combos = [
            {
                "id": "viewer-single",
                "label": "looking at viewer",
                "prompt": "looking at viewer",
                "tags": ["looking at viewer"],
                "count": 100000,
            }
        ]
        if event_id == "looking_back":
            combos = [
                {
                    "id": "looking-back-sitting",
                    "label": "looking back, sitting",
                    "prompt": "looking back, sitting",
                    "tags": ["looking back", "sitting"],
                    "count": 20,
                }
            ]
        return {"event": {"observedCombos": combos}}


class _NamespacedEventService(_EventService):
    def bootstrap(self, **_kwargs):
        return {
            "selected": {"ratingId": "e", "personId": "2girls"},
            "persons": [
                {"id": "1girl_solo", "label": "1girl solo"},
                {"id": "2girls", "label": "2girls"},
            ],
            "categories": [
                {
                    "id": "expression action::gaze",
                    "label": "expression action::gaze",
                    "subcategories": [],
                }
            ],
        }


class _UnavailableService:
    def status(self):
        return {"dataAvailability": {"main": "missing", "message": "not installed"}}


class _LoadingEventService(_EventService):
    def __init__(self):
        self.load_started = False

    def status(self):
        if self.load_started:
            return {"dataAvailability": {"main": "ready", "message": "ready"}}
        return {"dataAvailability": {"main": "missing", "message": "not installed"}}

    def start_loading(self, payload):
        self.load_payload = payload
        self.load_started = True
        return {"message": "loading started"}


class _ClothesService:
    def status(self):
        return {"dataAvailability": {"main": "ready", "message": "ready"}}

    def bootstrap(self, _payload):
        return {
            "comboRows": {
                "rows": [
                    {
                        "id": "combo-shirt",
                        "comboText": "shirt, long sleeves",
                        "prompt": "shirt, long sleeves",
                        "tags": ["shirt", "long sleeves"],
                        "count": 5,
                    }
                ]
            }
        }


class _ExpressionService:
    def status(self):
        return {"dataAvailability": {"main": "ready", "message": "ready"}}

    def bootstrap(self, _payload):
        return {
            "categories": [
                {
                    "id": "smile",
                    "label": "Smile",
                    "subcategories": [
                        {
                            "id": "mouth",
                            "label": "Mouth",
                            "items": [
                                {
                                    "id": "smile-open-mouth",
                                    "label": "smile, open mouth",
                                    "tags": ["smile", "open mouth"],
                                    "count": 11,
                                }
                            ],
                        }
                    ],
                }
            ]
        }


def _bridge(tmp_path, event_service=None):
    return PresetInputBridge(
        tmp_path,
        event_service=event_service or _EventService(),
        clothes_service=_ClothesService(),
        expression_service=_ExpressionService(),
    )


def test_preset_root_returns_four_axis_choices(tmp_path):
    result = _bridge(tmp_path).suggest("preset:")

    assert result["stage"] == "axis"
    assert [item["value"] for item in result["suggestions"]] == [
        "preset:events",
        "preset:clothes",
        "preset:expressions",
        "preset:custom",
    ]


def test_events_path_walks_category_subcategory_item_and_combo(tmp_path):
    bridge = _bridge(tmp_path)

    categories = bridge.suggest("preset:events")
    assert categories["stage"] == "category"
    assert categories["suggestions"][0]["value"] == "preset:events/standing"

    subcategories = bridge.suggest("preset:events/standing")
    assert subcategories["stage"] == "subcategory"
    assert subcategories["suggestions"][0]["value"] == "preset:events/standing/solo"

    items = bridge.suggest("preset:events/standing/solo")
    assert items["stage"] == "item"
    assert items["suggestions"][0]["value"].endswith("/standing")

    combos = bridge.suggest("preset:events/standing/solo/standing")
    assert combos["stage"] == "combo"
    assert combos["suggestions"][0]["final"] is True
    assert combos["suggestions"][0]["prompt"] == "standing, solo, looking at viewer"


def test_events_payload_exposes_context_and_hides_namespace_label(tmp_path):
    bridge = _bridge(tmp_path, event_service=_NamespacedEventService())

    result = bridge.suggest("preset:events")

    assert result["presetContext"]["ratingId"] == "e"
    assert result["presetContext"]["personId"] == "2girls"
    assert result["presetContext"]["personOptions"] == [
        {"id": "1girl_solo", "label": "1girl solo"},
        {"id": "2girls", "label": "2girls"},
    ]
    assert result["suggestions"][0]["tag"] == "Gaze"
    assert result["suggestions"][0]["value"] == "preset:events/gaze"


def test_event_category_subcategory_and_item_paths_resolve_to_observed_combo(tmp_path):
    bridge = _bridge(tmp_path)
    chooser = lambda items: items[0]

    category = bridge.resolve_prompt_token("preset:events/activity%3A%3Astanding", chooser=chooser)
    assert category["applied"] is True
    assert category["stage"] == "category"
    assert category["tags"] == ["standing", "solo", "looking at viewer"]

    trailing = bridge.resolve_prompt_token("preset:events/activity%3A%3Astanding/", chooser=chooser)
    assert trailing["applied"] is True
    assert trailing["stage"] == "category"

    subcategory = bridge.resolve_prompt_token(
        "preset:events/activity%3A%3Astanding/activity%3A%3Astanding%3A%3Asolo",
        chooser=chooser,
    )
    assert subcategory["applied"] is True
    assert subcategory["stage"] == "subcategory"
    assert subcategory["selected"]["eventId"] == "standing"

    item = bridge.resolve_prompt_token(
        "preset:events/activity%3A%3Astanding/activity%3A%3Astanding%3A%3Asolo/standing",
        chooser=chooser,
    )
    assert item["applied"] is True
    assert item["stage"] == "item"
    assert item["combo"]["id"] == "combo-0"


def test_incomplete_event_path_prefers_items_with_observed_combos(tmp_path):
    bridge = _bridge(tmp_path, event_service=_SparseEventService())
    chooser = lambda items: items[0]

    category = bridge.resolve_prompt_token("preset:events/activity", chooser=chooser)
    assert category["applied"] is True
    assert category["tags"] == ["combo event", "observed detail"]
    assert category["selected"]["eventId"] == "combo-event"

    subcategory = bridge.resolve_prompt_token("preset:events/activity/activity%3A%3Asolo", chooser=chooser)
    assert subcategory["applied"] is True
    assert subcategory["tags"] == ["combo event", "observed detail"]
    assert subcategory["selected"]["eventId"] == "combo-event"


def test_event_combo_shortcut_demotes_single_tag_and_global_noise(tmp_path):
    bridge = _bridge(tmp_path, event_service=_NoisyComboEventService())
    chooser = lambda items: items[0]

    suggestions = bridge.suggest("preset:events/gaze/gaze_direction/looking_back", limit=10)
    assert suggestions["suggestions"][0]["comboId"] == "useful-pair"

    resolved = bridge.resolve_prompt_token(
        "preset:events/gaze/gaze_direction/looking_back",
        chooser=chooser,
    )

    assert resolved["applied"] is True
    assert resolved["combo"]["id"] == "useful-pair"
    assert resolved["tags"] == ["looking back", "sitting"]


def test_incomplete_event_shortcut_chooses_item_with_useful_combo(tmp_path):
    bridge = _bridge(tmp_path, event_service=_NoisyWildcardEventService())
    chooser = lambda items: items[0]

    resolved = bridge.resolve_prompt_token("preset:events/gaze", chooser=chooser)

    assert resolved["applied"] is True
    assert resolved["selected"]["eventId"] == "looking_back"
    assert resolved["combo"]["id"] == "looking-back-sitting"
    assert resolved["tags"] == ["looking back", "sitting"]


def test_prompt_processor_expands_preset_event_token_during_wildcard_step(tmp_path):
    processor = PromptProcessor.__new__(PromptProcessor)
    processor.wildcard_processor = SimpleNamespace(expand_tags=lambda tags, _context: tags)
    processor._preset_bridge = _bridge(tmp_path)
    context = PromptContext(
        source_row={},
        settings={},
        main_tags=["best quality", "preset:events/standing"],
    )

    processor._step_3_expand_wildcards(context)

    assert context.main_tags == [
        "best quality",
        "standing",
        "solo",
        "looking at viewer",
    ]
    assert context.metadata["preset_prompt_resolutions"][0]["token"] == (
        "preset:events/standing"
    )


def test_unavailable_axis_returns_load_state_without_suggestions(tmp_path):
    result = _bridge(tmp_path, event_service=_UnavailableService()).suggest("preset:events")

    assert result["stage"] == "unavailable"
    assert result["dataReady"] is False
    assert result["loadState"] == {"main": "missing", "message": "not installed"}
    assert result["suggestions"] == []


def test_unloaded_axis_starts_loading_then_returns_loaded_suggestions(tmp_path):
    service = _LoadingEventService()
    bridge = _bridge(tmp_path, event_service=service)

    loading = bridge.suggest("preset:events")

    assert loading["stage"] == "loading"
    assert loading["lockInput"] is True
    assert loading["loadStarted"] is True
    assert loading["loadAction"] == "start_loading"
    assert loading["loadState"] == {"main": "loading", "message": "loading started"}
    assert service.load_payload == {"axis": "events", "token": "preset:events"}

    loaded = bridge.suggest("preset:events")

    assert loaded["stage"] == "category"
    assert loaded["dataReady"] is True
    assert loaded["suggestions"][0]["value"] == "preset:events/standing"


def test_loaded_clothes_and_expression_inputs_return_expected_final_rows(tmp_path):
    bridge = _bridge(tmp_path)

    clothes = bridge.suggest("preset:clothes")
    assert clothes["stage"] == "combo"
    assert clothes["suggestions"][0]["final"] is True
    assert clothes["suggestions"][0]["prompt"] == "shirt, long sleeves"

    expressions = bridge.suggest("preset:expressions/smile/mouth")
    assert expressions["stage"] == "item"
    assert expressions["suggestions"][0]["final"] is True
    assert expressions["suggestions"][0]["value"] == "preset:expressions/smile/mouth/smile-open-mouth"
    assert expressions["suggestions"][0]["tags"] == ["smile", "open mouth"]


def test_convenience_search_returns_vibe_style_rows(tmp_path):
    rows = search_preset_paths(
        "preset:clothes",
        root=tmp_path,
        clothes_service=_ClothesService(),
        event_service=_EventService(),
        expression_service=_ExpressionService(),
    )

    assert rows[0]["value"] == "preset:clothes/combo-shirt"
    assert rows[0]["_wc_type"] == "preset_path"
