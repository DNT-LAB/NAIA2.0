"""Regressions from the final Boost trial; no inference or network required."""

import pytest

from core import scene_boost as sb
from core import ollama_tag_assist_service as assist


def classify(tag):
    if tag in {"gloves", "hoodie", "dress", "vest", "shirt"}:
        return frozenset({sb.CLOTHING})
    if tag in {"fabric", "bag", "duck"}:
        return frozenset({sb.OBJECT})
    return frozenset()


def filtered(prompt, description, *, material=True):
    parsed = sb.parse_prompt(prompt)
    return sb.filter_descriptions(
        [description], parsed["all_words"], sb.SCENE_BOOST_LEVELS["rich"],
        input_tags=parsed["descriptive"], classify_axes=classify,
        style_options={"allow_material_style": material, "allow_light_style": False},
    )


@pytest.mark.parametrize("prompt,description", [
    ("red gloves, holding hands", "Red glove fabric stretches tight across the knuckles while holding hands"),
    ("hoodie, clenched hand", "The fabric of the hoodie bunches tightly where the clenched hand presses against the side seam"),
    ("black vest", "The vest's fabric gathers in deep folds around the shoulders"),
])
def test_existing_garment_fabric_is_material(prompt, description):
    assert filtered(prompt, description) == [description]
    assert filtered(prompt, description, material=False) == []


@pytest.mark.parametrize("prompt,description", [
    ("red gloves, holding hands", "The fabric of a bag presses against the red gloves"),
    ("red gloves, holding hands", "Red glove fabric folds around a duck"),
    ("red gloves, holding hands", "Red glove fabric brushes a second piece of fabric"),
    ("hoodie", "The shirt fabric bunches near the hoodie"),
    ("sitting, train interior", "The fabric of the shirt gathers at the seated hip"),
    ("red gloves", "Blue glove fabric gathers tightly around the fingers"),
    ("red gloves", "Red glove fabric catches glowing light around the fingers"),
])
def test_fabric_does_not_disable_other_guards(prompt, description):
    assert filtered(prompt, description) == []


@pytest.fixture
def no_rating_distribution(monkeypatch):
    monkeypatch.setattr(assist, "_load_rating_dist", lambda: {})


@pytest.mark.parametrize("tag", ["canal", "canal bridge", "analog clock", "analysis", "canal_bridge"])
def test_neutral_words_do_not_trigger_anal_rating(tag, no_rating_distribution):
    assert not assist._is_sexual_tag(tag)
    assert assist._tag_rating(tag) == "g"


@pytest.mark.parametrize("tag", [
    "anal", "anal insertion", "anal_insertion", "penetration", "masturbation",
    "cumshot", "autofellatio", "nipples",
])
def test_existing_rating_signals_remain(tag, no_rating_distribution):
    assert assist._is_sexual_tag(tag)
    assert assist._tag_rating(tag) == ("q" if tag == "nipples" else "e")


def test_real_service_boost_does_not_inject_legacy_substring_guard(no_rating_distribution, monkeypatch):
    monkeypatch.setattr(sb, "_VALIDATE_CACHE", {})
    calls = []

    def chat(instruction, schema, **kwargs):
        calls.append(kwargs)
        return {"descriptions": [], "composition_tags": []}

    svc = assist.OllamaTagAssistService(
        base_url="http://127.0.0.1:1", default_model="mock",
        searcher=lambda *a, **k: [], chat=chat,
    )
    monkeypatch.setattr(svc, "_get_axis_classifier", lambda: classify)
    for prompt, rating in [("town, canal, bridge", "g"), ("anal insertion", "e")]:
        result = svc.scene_boost(prompt)
        assert result["ok"]
        assert result["rating"] == rating
        assert result["prompt"] == prompt
    assert len(calls) == 2
    assert all(call["think"] is False for call in calls)
