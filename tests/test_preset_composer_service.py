from types import SimpleNamespace

from core.preset_composer_service import PresetComposerService
from core.remote_api_server import RemoteBridge


class _TokenManager:
    def get_token(self, _key):
        return ""


class _CheckBox:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _GenerationController:
    is_generating = False


def _bridge_context():
    return SimpleNamespace(
        secure_token_manager=_TokenManager(),
        cloudflared_active=False,
        cloudflared_tunnel_url="",
        cloudflared_status_text="",
        current_prompt_context=None,
        main_window=SimpleNamespace(
            generation_controller=_GenerationController(),
            generation_checkboxes={"자동 생성": _CheckBox(False)},
            trigger_random_prompt=lambda **_kwargs: None,
        ),
    )


def test_prompt_plan_dedupes_tags_in_first_occurrence_order():
    service = PresetComposerService()

    plan = service.compose_prompt_plan({
        "context": {"ratingId": "explicit", "personId": "solo"},
        "axes": {
            "events": {"enabled": True, "tags": ["solo", "looking at viewer"]},
            "clothes": {"enabled": True, "tags": ["shirt", "looking at viewer"]},
        },
        "manualTags": ["shirt", "masterpiece"],
    })

    assert plan["context"] == {"ratingId": "e", "personId": "1girl_solo"}
    assert plan["fragments"]["person"] == ["1girl", "solo"]
    assert plan["finalTags"] == [
        "1girl",
        "solo",
        "rating:explicit",
        "looking at viewer",
        "shirt",
        "masterpiece",
    ]
    assert plan["finalPrompt"] == (
        "1girl, solo, rating:explicit, looking at viewer, shirt, masterpiece"
    )


def test_expression_fragments_append_after_events_and_clothes():
    service = PresetComposerService()

    plan = service.compose_prompt_plan({
        "context": {"ratingId": "s", "personId": "1girl"},
        "axes": {
            "events": {"enabled": True, "tags": ["standing"]},
            "clothes": {"enabled": True, "tags": ["shirt"]},
            "expressions": {
                "enabled": True,
                "items": [
                    {"id": "blush-mouth", "tags": ["light blush", "open mouth"]},
                    {"id": "smile", "tags": ["smile"]},
                ],
            },
        },
        "manualTags": ["best quality"],
    })

    assert plan["fragments"]["expressions"] == ["light blush", "open mouth", "smile"]
    assert plan["finalTags"] == [
        "1girl",
        "rating:sensitive",
        "standing",
        "shirt",
        "light blush",
        "open mouth",
        "smile",
        "best quality",
    ]


def test_clothes_axis_provider_prompt_fragment_is_used():
    class ClothesProvider:
        def prompt_fragment(self, payload):
            assert payload["context"] == {"ratingId": "s", "personId": "1girl_solo"}
            assert payload["comboId"] == "combo-1"
            return {"ok": True, "promptFragment": {"tags": ["jacket", "pleated skirt"]}}

    service = PresetComposerService(axis_providers={"clothes": ClothesProvider()})

    plan = service.compose_prompt_plan({
        "context": {"ratingId": "s", "personId": "1girl_solo"},
        "axes": {
            "clothes": {"enabled": True, "comboId": "combo-1"},
        },
    })

    assert plan["fragments"]["clothes"] == ["jacket", "pleated skirt"]
    assert plan["warnings"] == []


def test_temporary_clothes_focus_extends_provider_fragment():
    class ClothesProvider:
        def prompt_fragment(self, payload):
            assert payload["temporaryFocus"] is True
            return {"ok": True, "promptFragment": {"tags": ["gem"]}}

    service = PresetComposerService(axis_providers={"clothes": ClothesProvider()})

    plan = service.compose_prompt_plan({
        "context": {"ratingId": "s", "personId": "1girl_solo"},
        "axes": {
            "clothes": {
                "enabled": True,
                "comboId": "combo-1",
                "temporaryFocus": True,
                "focusComboTags": ["chinese clothes", "fingerless gloves", "gem"],
            },
        },
    })

    assert plan["fragments"]["clothes"] == ["gem", "chinese clothes", "fingerless gloves"]


def test_composite_generation_source_uses_remote_preset_flags_only():
    service = PresetComposerService()

    result = service.generation_source({
        "requestId": "req-123",
        "context": {"ratingId": "q", "personId": "2girls"},
        "axes": {
            "events": {"enabled": True, "eventId": "tea party"},
            "clothes": {"enabled": True, "tags": ["dress"]},
            "expressions": {"enabled": True, "items": [{"tags": ["smile"]}]},
        },
    })

    assert result["sourceName"] == "preset:req-123"
    assert result["sourceRow"]["general"] == (
        "2girls, rating:questionable, tea party, dress, smile"
    )
    assert result["overrides"] == {
        "remote_preset_request": True,
        "remote_preset_request_id": "req-123",
        "remote_preset_axes": ["events", "clothes", "expressions"],
    }
    assert "event_preset_request" not in result["overrides"]
    assert "clothes_preset_request" not in result["overrides"]


def test_remote_bridge_preset_generate_queues_composite_without_legacy_flag_collision(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_bridge_context())

    result = bridge._preset_generate({
        "requestId": "bridge-req",
        "context": {"ratingId": "s", "personId": "1girl_solo"},
        "axes": {
            "events": {"enabled": True, "tags": ["window seat"]},
            "clothes": {"enabled": True, "tags": ["cardigan"]},
        },
    })

    assert result["status"] == "generation_requested"
    queued = bridge._pending_random_requests[-1]
    assert queued["source_row"].name == "preset:bridge-req"
    assert queued["source_row"]["general"] == (
        "1girl, solo, rating:sensitive, window seat, cardigan"
    )

    bridge._do_random()
    pending = bridge._pending_overrides[("preset", "bridge-req")]
    assert pending["source"] == "preset"
    assert pending["params"] == {
        "remote_preset_request": True,
        "remote_preset_request_id": "bridge-req",
        "remote_preset_axes": ["events", "clothes"],
    }
    assert "event_preset_request" not in pending["params"]
    assert "clothes_preset_request" not in pending["params"]
