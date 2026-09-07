"""Whole-tag light evidence and explicit full-body framing must survive Boost."""

import pytest

from core import scene_boost as sb


@pytest.fixture(autouse=True)
def isolated_validation_cache(monkeypatch):
    monkeypatch.setattr(sb, "_VALIDATE_CACHE", {})


def run_boost(prompt, *, light=False):
    seen = {}

    def chat(instruction, schema, **kwargs):
        seen["instruction"] = instruction
        seen["candidates"] = schema["properties"]["composition_tags"]["items"]["enum"]
        lighting = [t for t, label in sb._COMPOSITION_POOL
                    if label in {"bright", "moody"} and t in seen["candidates"]]
        return {"composition_tags": lighting[:1] + ["portrait", "from side", "depth of field"],
                "descriptions": ["Gentle sunlight illuminates the fabric folds of the dress"]}

    result = sb.run_scene_boost(
        prompt, {"level": "rich", "allow_light_style": light},
        chat=chat, default_model="mock", tag_rating=lambda t: "g",
        is_sexual=lambda t: False, is_hardcore=lambda t: False,
        validate_tag=lambda t: {"tag": t}, tag_allowed=lambda t, r: True,
        classify_axes=lambda t: frozenset(),
    )
    assert result["ok"]
    return result, seen


@pytest.mark.parametrize("tag", [
    "light smile", "light blush", "light frown", "light brown hair", "eye shadow",
    "manta ray", "ray gun", "shadow the hedgehog", "moonlight butterfly",
    "lighting cigarette", "light machine gun", "sunlight print",
])
def test_nonlighting_tag_cannot_unlock_lighting(tag):
    result, seen = run_boost(f"dress, {tag}")
    lighting = {t for t, label in sb._COMPOSITION_POOL if label in {"bright", "moody"}}
    assert not lighting.intersection(seen["candidates"])
    assert not lighting.intersection(result["additions"]["composition_tags"])
    assert result["additions"]["descriptions"] == []
    assert "You MAY add lighting, time-of-day" not in seen["instruction"]


@pytest.mark.parametrize("tag", [
    "sunlight", "dappled sunlight", "moonlight", "backlighting", "rim lighting",
    "dim lighting", "glowing", "glowing eyes", "golden hour",
    "DAPPLED_SUNLIGHT", "1.2::sunlight::", "(rim_lighting:1.2)",
])
def test_actual_lighting_tag_keeps_existing_source_exception(tag):
    result, seen = run_boost(f"dress, {tag}")
    assert "You MAY add lighting, time-of-day" in seen["instruction"]
    assert result["additions"]["descriptions"]


def test_light_option_on_still_allows_new_lighting():
    result, seen = run_boost("dress, light smile", light=True)
    assert "You MAY add lighting, time-of-day" in seen["instruction"]
    assert result["additions"]["descriptions"]


@pytest.mark.parametrize("full_body", ["full body", "FULL_BODY", "1.2::full body::", "(full_body:1.2)"])
def test_full_body_is_preserved_before_and_after_model_selection(full_body):
    prompt = f"dress, smile, {full_body}"
    result, seen = run_boost(prompt)
    assert not {"portrait", "close-up", "upper body", "cowboy shot", "wide shot"}.intersection(seen["candidates"])
    assert not {"portrait", "close-up", "upper body", "cowboy shot", "wide shot"}.intersection(result["additions"]["composition_tags"])
    assert {"from side", "from below", "from above", "from behind", "dutch angle"}.intersection(seen["candidates"])
    assert {"depth of field", "bokeh", "blurry background", "motion blur"}.intersection(seen["candidates"])
    assert result["prompt"].startswith(prompt)


def test_full_body_guard_also_rejects_conflicting_supplied_candidates():
    picks = ["portrait", "upper body", "from side", "depth of field"]
    assert sb.filter_composition(picks, picks, ["full body"], sb.SCENE_BOOST_LEVELS["rich"]) == [
        "from side", "depth of field",
    ]
