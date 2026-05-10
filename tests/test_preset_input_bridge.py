from types import SimpleNamespace

from core.preset_input_bridge import PresetInputBridge, preset_context_from_prompt, search_preset_paths
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


class _MissingAnchorComboEventService(_EventService):
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
                                    "label": "looking back",
                                    "promptAtoms": ["looking back"],
                                },
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
                        "id": "sitting-wariza",
                        "label": "sitting, wariza",
                        "prompt": "sitting, wariza",
                        "tags": ["sitting", "wariza"],
                        "count": 20,
                    }
                ]
            }
        }


class _ManyEventService(_EventService):
    def __init__(self):
        self.select_calls = 0

    def bootstrap(self, **_kwargs):
        events = [
            {"id": f"event-{index}", "label": f"event {index}", "count": 10 - index}
            for index in range(10)
        ]
        events.append({"id": "useful-event", "label": "useful event", "count": 100})
        return {
            "categories": [
                {
                    "id": "bulk",
                    "label": "Bulk",
                    "subcategories": [
                        {
                            "id": "bulk::many",
                            "label": "Many",
                            "events": events,
                        }
                    ],
                }
            ]
        }

    def select(self, payload):
        self.select_calls += 1
        event_id = str(payload.get("eventId") or "")
        combos = []
        if event_id == "useful-event":
            combos = [
                {
                    "id": "useful-combo",
                    "label": "useful event, detail",
                    "prompt": "useful event, detail",
                    "tags": ["useful event", "detail"],
                    "count": 10,
                }
            ]
        return {"event": {"observedCombos": combos}}


class _ContextEventService(_EventService):
    def __init__(self):
        self.bootstrap_calls = []
        self.select_payloads = []

    def bootstrap(self, **kwargs):
        self.bootstrap_calls.append(kwargs)
        return super().bootstrap(**kwargs)

    def select(self, payload):
        self.select_payloads.append(payload)
        return super().select(payload)


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
    def __init__(self):
        self.prompt_fragment_payloads = []
        self.bootstrap_payloads = []
        self.lucky_payloads = []

    def status(self):
        return {"dataAvailability": {"main": "ready", "message": "ready"}}

    def bootstrap(self, payload):
        self.bootstrap_payloads.append(dict(payload or {}))
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
            },
            "browser": {
                "selected": {
                    "categoryId": payload.get("categoryId") or "UPPER",
                    "subcategoryId": payload.get("subcategoryId") or "tops",
                },
                "categories": [
                    {"id": "UPPER", "label": "Upper", "subcategoryCount": 1, "count": 3},
                    {"id": "LEGS", "label": "Legs", "subcategoryCount": 1, "count": 1},
                ],
                "subcategories": [
                    {"id": "tops", "label": "tops", "count": 3},
                ],
                "items": [
                    {"id": "tag-shirt", "tag": "shirt", "label": "shirt", "postCount": 10},
                    {"id": "tag-long-sleeves", "tag": "long sleeves", "label": "long sleeves", "postCount": 8},
                    {"id": "tag-swimsuit", "tag": "swimsuit under clothes", "label": "swimsuit under clothes", "postCount": 4},
                    {"id": "tag-rabbit-hood", "tag": "rabbit hood", "label": "rabbit hood", "postCount": 2},
                ],
            },
            "staged": {
                "items": [
                    {"tag": item.get("tag"), "slot": item.get("slot") or "UPPER"}
                    for item in payload.get("stagedItems", [])
                    if isinstance(item, dict)
                ],
                "groups": [],
                "tags": [
                    item.get("tag")
                    for item in payload.get("stagedItems", [])
                    if isinstance(item, dict) and item.get("tag")
                ],
            },
        }

    def select(self, payload):
        if payload.get("comboId") == "combo-shirt":
            return {
                "combo": {
                    "id": "combo-shirt",
                    "comboText": "shirt, long sleeves",
                    "prompt": "shirt, long sleeves",
                    "tags": ["shirt", "long sleeves"],
                    "count": 5,
                }
            }
        return {"combo": None}

    def prompt_fragment(self, payload):
        self.prompt_fragment_payloads.append(dict(payload or {}))
        tags = [
            item.get("tag")
            for item in payload.get("stagedItems", [])
            if isinstance(item, dict) and item.get("tag")
        ]
        return {
            "ok": True,
            "promptFragment": {
                "tags": tags,
                "prompt": ", ".join(tags),
            },
        }

    def lucky(self, payload):
        self.lucky_payloads.append(dict(payload or {}))
        tags = [
            item.get("tag")
            for item in payload.get("stagedItems", [])
            if isinstance(item, dict) and item.get("tag")
        ]
        tags = [*tags, "random jacket"]
        return {
            "ok": True,
            "lucky": {
                "comboId": "combo-random",
                "tags": tags,
                "basis": "staged",
            },
            "promptFragment": {
                "tags": tags,
                "prompt": ", ".join(tags),
            },
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
                    "labelKo": "웃는 표정",
                    "subcategories": [
                        {
                            "id": "mouth",
                            "label": "Mouth",
                            "labelKo": "입 / 미소",
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


class _PlayfulExpressionService:
    def status(self):
        return {"dataAvailability": {"main": "ready", "message": "ready"}}

    def bootstrap(self, _payload):
        return {
            "categories": [
                {
                    "id": "playful_teasing",
                    "label": "Playful / Teasing",
                    "subcategories": [
                        {
                            "id": "playful_teasing-featured",
                            "label": "Featured",
                            "isVirtual": True,
                            "items": [
                                {
                                    "id": "expr-tongue",
                                    "label": "tongue out",
                                    "tags": ["tongue out"],
                                    "count": 1277,
                                    "featured": True,
                                }
                            ],
                        },
                        {
                            "id": "playful_teasing-mouth_smile",
                            "label": "Mouth / Smile",
                            "items": [
                                {
                                    "id": "expr-tongue",
                                    "label": "tongue out",
                                    "tags": ["tongue out"],
                                    "count": 1277,
                                },
                                {
                                    "id": "expr-fangs",
                                    "label": "fangs, open mouth",
                                    "tags": ["fangs", "open mouth"],
                                    "count": 410,
                                },
                            ],
                        },
                        {
                            "id": "playful_teasing-eyes_gaze",
                            "label": "Eyes / Gaze",
                            "items": [
                                {
                                    "id": "expr-wink",
                                    "label": ";p, one eye closed",
                                    "tags": [";p", "one eye closed"],
                                    "count": 38,
                                }
                            ],
                        },
                    ],
                }
            ]
        }


def _bridge(tmp_path, event_service=None, clothes_service=None):
    return PresetInputBridge(
        tmp_path,
        event_service=event_service or _EventService(),
        clothes_service=clothes_service or _ClothesService(),
        expression_service=_ExpressionService(),
    )


def test_preset_root_returns_three_visible_axis_choices(tmp_path):
    result = _bridge(tmp_path).suggest("preset:")

    assert result["stage"] == "axis"
    assert [item["value"] for item in result["suggestions"]] == [
        "preset:events(s|1girl_solo)",
        "preset:clothes",
        "preset:expressions",
    ]


def test_events_path_walks_category_subcategory_item_and_combo(tmp_path):
    bridge = _bridge(tmp_path)

    categories = bridge.suggest("preset:events")
    assert categories["stage"] == "category"
    assert categories["suggestions"][0]["value"] == "preset:events(s|1girl_solo)/standing"

    subcategories = bridge.suggest("preset:events(s|1girl_solo)/standing")
    assert subcategories["stage"] == "subcategory"
    assert subcategories["suggestions"][0]["value"] == "preset:events(s|1girl_solo)/standing/solo"

    items = bridge.suggest("preset:events(s|1girl_solo)/standing/solo")
    assert items["stage"] == "item"
    assert items["suggestions"][0]["value"].endswith("/standing")

    combos = bridge.suggest("preset:events(s|1girl_solo)/standing/solo/standing")
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
    assert result["suggestions"][0]["value"] == "preset:events(e|2girls)/gaze"


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


def test_event_resolution_uses_runtime_preset_context(tmp_path):
    service = _ContextEventService()
    bridge = _bridge(tmp_path, event_service=service)
    bridge.set_context({"ratingId": "q", "personId": "2girls"})

    resolved = bridge.resolve_prompt_token("preset:events/standing", chooser=lambda items: items[0])

    assert resolved["applied"] is True
    assert service.bootstrap_calls[-1]["rating_id"] == "q"
    assert service.bootstrap_calls[-1]["person_id"] == "2girls"
    assert service.select_payloads[-1]["ratingId"] == "q"
    assert service.select_payloads[-1]["personId"] == "2girls"
    assert resolved["selected"]["ratingId"] == "q"
    assert resolved["selected"]["personId"] == "2girls"


def test_event_token_embedded_context_overrides_runtime_context(tmp_path):
    service = _ContextEventService()
    bridge = _bridge(tmp_path, event_service=service)
    bridge.set_context({"ratingId": "s", "personId": "1girl_solo"})

    suggestions = bridge.suggest("preset:events(q|2girls)")
    resolved = bridge.resolve_prompt_token(
        "preset:events(q|2girls)/standing",
        chooser=lambda items: items[0],
    )

    assert suggestions["suggestions"][0]["value"] == "preset:events(q|2girls)/standing"
    assert service.bootstrap_calls[-1]["rating_id"] == "q"
    assert service.bootstrap_calls[-1]["person_id"] == "2girls"
    assert service.select_payloads[-1]["ratingId"] == "q"
    assert service.select_payloads[-1]["personId"] == "2girls"
    assert resolved["selected"]["ratingId"] == "q"
    assert resolved["selected"]["personId"] == "2girls"


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


def test_incomplete_event_shortcut_uses_bounded_detail_scan(tmp_path):
    service = _ManyEventService()
    bridge = _bridge(tmp_path, event_service=service)
    chooser = lambda items: items[0]

    resolved = bridge.resolve_prompt_token("preset:events/bulk/bulk%3A%3Amany", chooser=chooser)

    assert resolved["applied"] is True
    assert resolved["selected"]["eventId"] == "useful-event"
    assert resolved["combo"]["id"] == "useful-combo"
    assert service.select_calls <= 3


def test_event_shortcut_keeps_main_item_when_combo_omits_anchor(tmp_path):
    bridge = _bridge(tmp_path, event_service=_MissingAnchorComboEventService())
    chooser = lambda items: items[0]

    resolved = bridge.resolve_prompt_token(
        "preset:events/gaze/gaze_direction/looking_back",
        chooser=chooser,
    )

    assert resolved["applied"] is True
    assert resolved["combo"]["id"] == "sitting-wariza"
    assert resolved["tags"] == ["looking back", "sitting", "wariza"]
    assert resolved["combo"]["prompt"] == "looking back, sitting, wariza"


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


def test_prompt_processor_uses_shared_services_and_app_preset_context(tmp_path):
    service = _ContextEventService()
    processor = PromptProcessor.__new__(PromptProcessor)
    processor.app_context = SimpleNamespace(
        event_preset_service=service,
        clothes_preset_service=_ClothesService(),
        expression_preset_service=_ExpressionService(),
        preset_input_context={"ratingId": "e", "personId": "2girls"},
        preset_input_context_source="autocomplete",
        preset_input_context_fields={"ratingId", "personId"},
    )
    processor.wildcard_processor = SimpleNamespace(expand_tags=lambda tags, _context: tags)
    context = PromptContext(
        source_row={},
        settings={},
        main_tags=["preset:events/standing"],
    )

    processor._step_3_expand_wildcards(context)

    assert context.main_tags == ["standing", "solo", "looking at viewer"]
    assert service.bootstrap_calls[-1]["rating_id"] == "e"
    assert service.bootstrap_calls[-1]["person_id"] == "2girls"
    assert service.select_payloads[-1]["ratingId"] == "e"
    assert service.select_payloads[-1]["personId"] == "2girls"


def test_preset_context_uses_source_rating_and_prompt_person_without_explicit_ui_context():
    app_context = SimpleNamespace(
        preset_input_context={"ratingId": "s", "personId": "1girl_solo"},
        preset_input_context_source="default",
    )
    context = PromptContext(
        source_row={"rating": "e", "general": "2girls, preset:events/gaze"},
        settings={},
        main_tags=["2girls", "preset:events/gaze"],
    )

    assert preset_context_from_prompt(app_context, context) == {
        "ratingId": "e",
        "personId": "2girls",
    }


def test_preset_context_does_not_treat_rating_only_context_as_person_selection():
    app_context = SimpleNamespace(
        preset_input_context={"ratingId": "q", "personId": "1girl_solo"},
        preset_input_context_source="clothes_bootstrap",
        preset_input_context_fields={"ratingId"},
    )
    context = PromptContext(
        source_row={"rating": "e", "general": "2girls, preset:events/gaze"},
        settings={},
        main_tags=["2girls", "preset:events/gaze"],
    )

    assert preset_context_from_prompt(app_context, context) == {
        "ratingId": "q",
        "personId": "2girls",
    }


def test_prompt_processor_expands_preset_clothes_staged_token_during_wildcard_step(tmp_path):
    processor = PromptProcessor.__new__(PromptProcessor)
    processor.wildcard_processor = SimpleNamespace(expand_tags=lambda tags, _context: tags)
    processor._preset_bridge = _bridge(tmp_path)
    context = PromptContext(
        source_row={},
        settings={},
        main_tags=["best quality", "preset:clothes/shirt&swimsuit under clothes"],
    )

    processor._step_3_expand_wildcards(context)

    assert context.main_tags == [
        "best quality",
        "shirt",
        "swimsuit under clothes",
    ]
    assert context.metadata["preset_prompt_resolutions"][0]["axis"] == "clothes"
    assert context.metadata["preset_prompt_resolutions"][0]["resolveMode"] == "fixed_tags"


def test_prompt_processor_randomizes_trailing_clothes_staged_token(tmp_path):
    processor = PromptProcessor.__new__(PromptProcessor)
    processor.wildcard_processor = SimpleNamespace(expand_tags=lambda tags, _context: tags)
    processor._preset_bridge = _bridge(tmp_path)
    context = PromptContext(
        source_row={},
        settings={},
        main_tags=["preset:clothes/necktie&underwear&underwear only&"],
    )

    processor._step_3_expand_wildcards(context)

    assert context.main_tags == ["necktie", "underwear", "underwear only", "random jacket"]
    assert context.metadata["preset_prompt_resolutions"][0]["resolveMode"] == "random_seed"


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
    assert loaded["suggestions"][0]["value"] == "preset:events(s|1girl_solo)/standing"


def test_loaded_clothes_and_expression_inputs_return_expected_final_rows(tmp_path):
    bridge = _bridge(tmp_path)

    clothes = bridge.suggest("preset:clothes")
    assert clothes["stage"] == "category"
    assert clothes["suggestions"][0]["final"] is False
    assert clothes["suggestions"][0]["tag"] == "Upper"
    assert clothes["suggestions"][0]["value"] == "preset:clothes/UPPER"

    expressions = bridge.suggest("preset:expressions/smile/mouth")
    assert expressions["stage"] == "item"
    assert expressions["suggestions"][0]["final"] is True
    assert expressions["suggestions"][0]["value"] == "preset:expressions/smile + open mouth"
    assert expressions["suggestions"][0]["internalPath"] == "preset:expressions/smile/mouth/smile-open-mouth"
    assert expressions["suggestions"][0]["insertText"] == "smile, open mouth"
    assert expressions["suggestions"][0]["tags"] == ["smile", "open mouth"]


def test_expression_category_and_subcategory_suggestions_use_korean_labels(tmp_path):
    bridge = _bridge(tmp_path)

    categories = bridge.suggest("preset:expressions")
    assert categories["stage"] == "category"
    assert categories["suggestions"][0]["tag"] == "웃는 표정"
    assert categories["suggestions"][0]["labelKo"] == "웃는 표정"

    subcategories = bridge.suggest("preset:expressions/smile")
    assert subcategories["stage"] == "subcategory"
    assert subcategories["suggestions"][0]["tag"] == "입 / 미소"
    assert subcategories["suggestions"][0]["labelKo"] == "입 / 미소"


def test_expression_paths_resolve_to_prompt_tags(tmp_path):
    bridge = _bridge(tmp_path)

    root = bridge.resolve_prompt_token("preset:expressions")
    assert root["applied"] is True
    assert root["axis"] == "expressions"
    assert root["stage"] == "axis"
    assert root["tags"] == ["smile", "open mouth"]

    category = bridge.resolve_prompt_token("preset:expressions/smile")
    assert category["applied"] is True
    assert category["stage"] == "category"
    assert category["selected"]["categoryId"] == "smile"

    item = bridge.resolve_prompt_token("preset:expressions/smile/mouth/smile-open-mouth")
    assert item["applied"] is True
    assert item["stage"] == "item"
    assert item["prompt"] == "smile, open mouth"
    assert item["selected"]["itemId"] == "smile-open-mouth"

    direct = bridge.resolve_prompt_token("preset:expressions/smile + open mouth")
    assert direct["applied"] is True
    assert direct["stage"] == "item"
    assert direct["prompt"] == "smile, open mouth"
    assert direct["selected"]["itemId"] == "smile-open-mouth"


def test_expression_category_shortcut_randomizes_from_non_featured_items(tmp_path):
    bridge = PresetInputBridge(
        tmp_path,
        event_service=_EventService(),
        clothes_service=_ClothesService(),
        expression_service=_PlayfulExpressionService(),
    )

    resolved = bridge.resolve_prompt_token(
        "preset:expressions/playful_teasing",
        chooser=lambda items: items[-1],
    )

    assert resolved["applied"] is True
    assert resolved["stage"] == "category"
    assert resolved["selected"]["subcategoryId"] == "playful_teasing-eyes_gaze"
    assert resolved["selected"]["itemId"] == "expr-wink"
    assert resolved["prompt"] == ";p, one eye closed"


def test_expression_subcategory_shortcut_randomizes_items(tmp_path):
    bridge = PresetInputBridge(
        tmp_path,
        event_service=_EventService(),
        clothes_service=_ClothesService(),
        expression_service=_PlayfulExpressionService(),
    )

    resolved = bridge.resolve_prompt_token(
        "preset:expressions/playful_teasing/playful_teasing-mouth_smile",
        chooser=lambda items: items[-1],
    )

    assert resolved["applied"] is True
    assert resolved["stage"] == "subcategory"
    assert resolved["selected"]["itemId"] == "expr-fangs"
    assert resolved["prompt"] == "fangs, open mouth"


def test_expression_exact_item_shortcut_remains_fixed(tmp_path):
    bridge = PresetInputBridge(
        tmp_path,
        event_service=_EventService(),
        clothes_service=_ClothesService(),
        expression_service=_PlayfulExpressionService(),
    )

    resolved = bridge.resolve_prompt_token(
        "preset:expressions/playful_teasing/playful_teasing-mouth_smile/expr-tongue",
        chooser=lambda items: items[-1],
    )

    assert resolved["applied"] is True
    assert resolved["stage"] == "item"
    assert resolved["selected"]["itemId"] == "expr-tongue"
    assert resolved["prompt"] == "tongue out"


def test_prompt_processor_expands_preset_expression_token_during_wildcard_step(tmp_path):
    processor = PromptProcessor.__new__(PromptProcessor)
    processor.wildcard_processor = SimpleNamespace(expand_tags=lambda tags, _context: tags)
    processor._preset_bridge = _bridge(tmp_path)
    context = PromptContext(
        source_row={},
        settings={},
        main_tags=["best quality", "preset:expressions/smile + open mouth"],
    )

    processor._step_3_expand_wildcards(context)

    assert context.main_tags == ["best quality", "smile", "open mouth"]
    assert context.metadata["preset_prompt_resolutions"][0]["axis"] == "expressions"


def test_clothes_staged_token_parser_preserves_empty_and_active_segments(tmp_path):
    bridge = _bridge(tmp_path)
    token = "preset:clothes/shirt&swim&pants&"
    parsed = bridge.parse_clothes_token(token, caret_offset=token.index("swim") + 2)

    assert parsed["mode"] == "staged"
    assert parsed["activeIndex"] == 1
    assert parsed["activeQuery"] == "swim"
    assert parsed["stagedTags"] == ["shirt", "pants"]
    assert parsed["resolveTags"] == ["shirt", "swim", "pants"]
    assert parsed["randomizeOnResolve"] is True
    assert parsed["segments"][3]["empty"] is True

    deleted = bridge.parse_clothes_token("preset:clothes/shirt&&pants&", caret_offset=len("preset:clothes/shirt&"))
    assert deleted["activeIndex"] == 1
    assert deleted["segments"][1]["empty"] is True
    assert deleted["stagedTags"] == ["shirt", "pants"]


def test_clothes_single_trailing_ampersand_uses_empty_add_slot(tmp_path):
    bridge = _bridge(tmp_path)
    token = "preset:clothes/open clothes&"

    parsed = bridge.parse_clothes_token(token, caret_offset=token.index("open") + 2)
    rows = bridge.suggest(token, caret_offset=token.index("open") + 2)["suggestions"]

    assert parsed["activeIndex"] == 1
    assert parsed["activeQuery"] == ""
    assert parsed["stagedTags"] == ["open clothes"]
    assert rows[0]["stage"] == "category"


def test_clothes_staged_token_expands_through_prompt_fragment(tmp_path):
    service = _ClothesService()
    bridge = _bridge(tmp_path, clothes_service=service)

    resolved = bridge.resolve_prompt_token("preset:clothes/shirt&swimsuit under clothes")

    assert resolved["applied"] is True
    assert resolved["axis"] == "clothes"
    assert resolved["resolveMode"] == "fixed_tags"
    assert resolved["tags"] == ["shirt", "swimsuit under clothes"]
    assert service.prompt_fragment_payloads[-1]["stagedItems"] == [
        {"tag": "shirt", "source": "shortcut"},
        {"tag": "swimsuit under clothes", "source": "shortcut"},
    ]
    assert "personId" not in service.prompt_fragment_payloads[-1]
    assert service.lucky_payloads == []


def test_clothes_trailing_ampersand_resolves_with_lucky_seed(tmp_path):
    service = _ClothesService()
    bridge = _bridge(tmp_path, clothes_service=service)

    resolved = bridge.resolve_prompt_token("preset:clothes/necktie&underwear&underwear only&")

    assert resolved["applied"] is True
    assert resolved["stage"] == "staged_random"
    assert resolved["resolveMode"] == "random_seed"
    assert resolved["stagedTags"] == ["necktie", "underwear", "underwear only"]
    assert resolved["tags"] == ["necktie", "underwear", "underwear only", "random jacket"]
    assert service.lucky_payloads[-1]["stagedItems"] == [
        {"tag": "necktie", "source": "shortcut"},
        {"tag": "underwear", "source": "shortcut"},
        {"tag": "underwear only", "source": "shortcut"},
    ]
    assert service.prompt_fragment_payloads == []


def test_clothes_staged_token_ignores_empty_segments(tmp_path):
    resolved = _bridge(tmp_path).resolve_prompt_token("preset:clothes/shirt&&pants")

    assert resolved["applied"] is True
    assert resolved["tags"] == ["shirt", "pants"]
    assert resolved["stagedTags"] == ["shirt", "pants"]


def test_clothes_staged_token_does_not_apply_incomplete_category(tmp_path):
    bridge = _bridge(tmp_path)
    parsed = bridge.parse_clothes_token("preset:clothes/off shoulder&HEAD_NECK_FACE")

    assert parsed["stagedTags"] == ["off shoulder"]
    assert parsed["unresolvedSegments"][0]["raw"] == "HEAD_NECK_FACE"

    resolved = bridge.resolve_prompt_token("preset:clothes/off shoulder&HEAD_NECK_FACE")

    assert resolved["applied"] is True
    assert resolved["tags"] == ["off shoulder"]
    assert resolved["reason"] == "partial_unresolved"
    assert resolved["unresolvedSegments"][0]["raw"] == "HEAD_NECK_FACE"


def test_clothes_combo_token_expands_to_combo_tags(tmp_path):
    service = _ClothesService()
    resolved = _bridge(tmp_path, clothes_service=service).resolve_prompt_token("preset:clothes/combo-shirt")

    assert resolved["applied"] is True
    assert resolved["stage"] == "combo"
    assert resolved["tags"] == ["shirt", "long sleeves"]
    assert "personId" not in service.bootstrap_payloads[-1]


def test_clothes_combo_suggestion_uses_readable_token(tmp_path):
    row = _bridge(tmp_path).suggest("preset:clothes/combo-shirt")["suggestions"][0]

    assert row["stage"] == "combo"
    assert row["comboId"] == "combo-shirt"
    assert row["value"] == "preset:clothes/shirt&long sleeves&"
    assert row["clothesTokenValue"] == "preset:clothes/shirt&long sleeves&"


def test_clothes_item_suggestion_appends_staged_readable_token(tmp_path):
    token = "preset:clothes/shirt&swim&"
    row = _bridge(tmp_path).suggest(
        token,
        caret_offset=token.index("swim") + 2,
    )["suggestions"][0]

    assert row["stage"] == "item"
    assert row["clothesTokenValue"] == "preset:clothes/shirt&swimsuit under clothes&"


def test_clothes_item_suggestions_exclude_already_staged_tags(tmp_path):
    token = "preset:clothes/rabbit hood&"
    rows = _bridge(tmp_path).suggest(token)["suggestions"]

    assert all(row.get("clothesTag") != "rabbit hood" for row in rows)


def test_clothes_browse_segment_resolves_exact_item_and_reports_partial(tmp_path):
    service = _ClothesService()
    exact = _bridge(tmp_path, clothes_service=service).resolve_prompt_token("preset:clothes/shirt&UPPER/tops/swimsuit under clothes")

    assert exact["applied"] is True
    assert exact["tags"] == ["shirt", "swimsuit under clothes"]
    assert exact["resolvedSegments"][0]["tag"] == "swimsuit under clothes"
    assert "personId" not in service.bootstrap_payloads[-1]

    partial = _bridge(tmp_path, clothes_service=service).resolve_prompt_token("preset:clothes/shirt&UPPER/tops/swi")
    assert partial["applied"] is True
    assert partial["tags"] == ["shirt"]
    assert partial["reason"] == "partial_unresolved"
    assert partial["unresolvedSegments"][0]["raw"] == "UPPER/tops/swi"


def test_convenience_search_returns_vibe_style_rows(tmp_path):
    rows = search_preset_paths(
        "preset:clothes",
        root=tmp_path,
        clothes_service=_ClothesService(),
        event_service=_EventService(),
        expression_service=_ExpressionService(),
    )

    assert rows[0]["value"] == "preset:clothes/UPPER"
    assert rows[0]["_wc_type"] == "preset_path"
