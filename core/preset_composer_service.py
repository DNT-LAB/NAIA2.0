"""Composite Preset axis prompt composer for Remote Web."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

try:
    from core.event_preset.engines import PERSON_PARTITION_ORDER, PERSON_TAG_MAP
except Exception:  # pragma: no cover - fallback keeps tests isolated from event assets
    PERSON_PARTITION_ORDER = [
        "1girl_solo",
        "1girl",
        "1girl_1boy",
        "1girl_multiple_boys",
        "2girls",
        "multiple_girls",
        "1boy_solo",
        "1boy",
        "1boy_multiple_girls",
        "2boys",
        "multiple_boys",
        "multiple_girls_multiple_boys",
        "other",
    ]
    PERSON_TAG_MAP = {
        "1girl_solo": ["1girl", "solo"],
        "1girl": ["1girl"],
        "1girl_1boy": ["1girl", "1boy"],
        "1girl_multiple_boys": ["1girl", "multiple boys"],
        "2girls": ["2girls"],
        "multiple_girls": ["multiple girls"],
        "1boy_solo": ["1boy", "solo"],
        "1boy": ["1boy"],
        "1boy_multiple_girls": ["1boy", "multiple girls"],
        "2boys": ["2boys"],
        "multiple_boys": ["multiple boys"],
        "multiple_girls_multiple_boys": ["multiple girls", "multiple boys"],
        "other": [],
    }


RATING_TAGS = {
    "g": "rating:general",
    "s": "rating:sensitive",
    "q": "rating:questionable",
    "e": "rating:explicit",
}
RATING_ALIASES = {
    "general": "g",
    "rating:general": "g",
    "sensitive": "s",
    "safe": "s",
    "rating:sensitive": "s",
    "question": "q",
    "questionable": "q",
    "rating:questionable": "q",
    "explicit": "e",
    "rating:explicit": "e",
}
PERSON_ALIASES = {
    "all": "1girl_solo",
    "solo": "1girl_solo",
    "1girl solo": "1girl_solo",
    "pair": "2girls",
    "group": "multiple_girls",
}
PROMPT_ORDER = ("person", "rating", "events", "clothes", "expressions", "manual")
AXIS_ORDER = ("events", "clothes", "expressions")


@dataclass(frozen=True)
class PresetContext:
    rating_id: str = "s"
    person_id: str = "1girl_solo"

    def to_api_dict(self) -> dict[str, str]:
        return {"ratingId": self.rating_id, "personId": self.person_id}


class PresetComposerService:
    """Build source-separated prompt plans and composite generation metadata."""

    def __init__(self, event_service: Any | None = None, axis_providers: Mapping[str, Any] | None = None):
        self.event_service = event_service
        self.axis_providers = dict(axis_providers or {})

    def normalize_context(self, payload: Mapping[str, Any] | None = None) -> PresetContext:
        payload = payload if isinstance(payload, Mapping) else {}
        raw_context = payload.get("context")
        context = raw_context if isinstance(raw_context, Mapping) else {}
        rating = self._normalize_rating(context.get("ratingId") or payload.get("ratingId") or "s")
        person = self._normalize_person(context.get("personId") or payload.get("personId") or "1girl_solo")
        return PresetContext(rating, person)

    def prompt_preview(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = payload if isinstance(payload, Mapping) else {}
        prompt_plan = self.compose_prompt_plan(payload)
        return {
            "ok": True,
            "requestId": self._request_id(payload),
            "context": prompt_plan["context"],
            "promptPlan": prompt_plan,
        }

    def generation_source(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = payload if isinstance(payload, Mapping) else {}
        request_id = self._request_id(payload) or uuid.uuid4().hex
        prompt_plan = self.compose_prompt_plan(payload)
        final_prompt = str(prompt_plan.get("finalPrompt") or "").strip()
        if not final_prompt:
            raise ValueError("Preset prompt is empty.")

        context = prompt_plan["context"]
        active_axes = list(prompt_plan.get("activeAxes") or [])
        source_row = {
            "general": final_prompt,
            "rating": context["ratingId"],
            "character": None,
            "copyright": None,
            "artist": None,
            "meta": None,
            "remote_preset_request_id": request_id,
            "remote_preset_axes": ",".join(active_axes),
            "remote_preset_context": json.dumps(context, ensure_ascii=False),
        }
        overrides = {
            "remote_preset_request": True,
            "remote_preset_request_id": request_id,
            "remote_preset_axes": active_axes,
        }
        return {
            "ok": True,
            "requestId": request_id,
            "promptPlan": prompt_plan,
            "sourceName": f"preset:{request_id}",
            "sourceRow": source_row,
            "overrides": overrides,
        }

    def compose_prompt_plan(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = payload if isinstance(payload, Mapping) else {}
        context = self.normalize_context(payload)
        axes = payload.get("axes") if isinstance(payload.get("axes"), Mapping) else {}
        warnings: list[dict[str, str]] = []

        fragments = {
            "person": list(PERSON_TAG_MAP.get(context.person_id, [])),
            "rating": [RATING_TAGS[context.rating_id]],
            "events": self._axis_tags("events", axes.get("events"), context, warnings),
            "clothes": self._axis_tags("clothes", axes.get("clothes"), context, warnings),
            "expressions": self._axis_tags("expressions", axes.get("expressions"), context, warnings),
            "manual": self._manual_tags(payload),
        }
        active_axes = [
            axis_id
            for axis_id in AXIS_ORDER
            if fragments[axis_id] or self._axis_enabled(axes.get(axis_id))
        ]
        composed_tags = self.dedupe_tags(
            tag
            for fragment_id in PROMPT_ORDER
            for tag in fragments.get(fragment_id, [])
        )
        final_tags = composed_tags
        final_prompt = ", ".join(composed_tags)
        prompt_override = str(payload.get("promptOverride") or "").strip()
        if prompt_override:
            final_prompt = prompt_override
            final_tags = self.dedupe_tags(self._split_tags(prompt_override))

        return {
            "context": context.to_api_dict(),
            "order": list(PROMPT_ORDER),
            "fragments": fragments,
            "finalTags": final_tags,
            "finalPrompt": final_prompt,
            "activeAxes": active_axes,
            "warnings": warnings,
            "overridden": bool(prompt_override),
        }

    @staticmethod
    def dedupe_tags(tags: Any) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in tags or []:
            tag = str(value or "").strip()
            key = tag.lower()
            if not tag or key in seen:
                continue
            seen.add(key)
            result.append(tag)
        return result

    def _axis_tags(
        self,
        axis_id: str,
        axis_payload: Any,
        context: PresetContext,
        warnings: list[dict[str, str]],
    ) -> list[str]:
        axis_payload = axis_payload if isinstance(axis_payload, Mapping) else {}
        if not self._axis_enabled(axis_payload):
            return []
        provider = self.axis_providers.get(axis_id)
        if provider is not None and hasattr(provider, "prompt_fragment"):
            try:
                fragment_payload = dict(axis_payload)
                fragment_payload.setdefault("context", context.to_api_dict())
                fragment = provider.prompt_fragment(fragment_payload)
                provider_tags = self._tags_from_fragment(fragment)
                if provider_tags:
                    if axis_id == "clothes":
                        return self.dedupe_tags([*provider_tags, *self._clothes_focus_tags(axis_payload)])
                    return provider_tags
            except Exception as exc:
                warnings.append({"axisId": axis_id, "message": f"{axis_id} fragment failed: {exc}"})
        if axis_id == "events":
            return self._event_tags(axis_payload, context, warnings)
        if axis_id == "clothes":
            return self._clothes_tags(axis_payload)
        if axis_id == "expressions":
            return self._expression_tags(axis_payload)
        return self._tags_from_fragment(axis_payload)

    def _event_tags(
        self,
        axis_payload: Mapping[str, Any],
        context: PresetContext,
        warnings: list[dict[str, str]],
    ) -> list[str]:
        explicit = self._tags_from_fragment(axis_payload)
        if explicit:
            return explicit
        event_id = str(axis_payload.get("eventId") or axis_payload.get("eventTag") or "").strip()
        if self.event_service is not None and event_id:
            select_payload = {
                "ratingId": context.rating_id,
                "personId": context.person_id,
                "categoryId": axis_payload.get("categoryId") or "",
                "subcategoryId": axis_payload.get("subcategoryId") or "",
                "eventId": event_id,
                "comboId": axis_payload.get("comboId") or "",
                "search": axis_payload.get("search") or "",
            }
            try:
                selected = self.event_service.select(select_payload)
                event = selected.get("event") if isinstance(selected, Mapping) else None
                if isinstance(event, Mapping):
                    combo_id = str((selected.get("selected") or {}).get("comboId") or axis_payload.get("comboId") or "")
                    combo = next(
                        (
                            item
                            for item in event.get("observedCombos", []) or []
                            if isinstance(item, Mapping) and str(item.get("id") or "") == combo_id
                        ),
                        None,
                    )
                    combo_tags = self._split_tags(combo.get("prompt")) if isinstance(combo, Mapping) else []
                    return combo_tags or self._coerce_tags(event.get("promptAtoms")) or [event_id]
            except Exception as exc:
                warnings.append({"axisId": "events", "message": f"Event fragment failed: {exc}"})
        return [event_id] if event_id else []

    def _clothes_tags(self, axis_payload: Mapping[str, Any]) -> list[str]:
        tags: list[str] = []
        tags.extend(self._split_tags(axis_payload.get("comboPrompt")))
        tags.extend(self._coerce_tags(axis_payload.get("comboTags")))
        tags.extend(self._clothes_focus_tags(axis_payload))
        tags.extend(self._coerce_tags(axis_payload.get("tags")))
        tags.extend(self._coerce_tags(axis_payload.get("promptTags")))
        for item in axis_payload.get("items") or []:
            tags.extend(self._tags_from_item(item))
        for item in axis_payload.get("amendedItems") or []:
            tags.extend(self._tags_from_item(item))
        return [tag for tag in tags if tag]

    def _clothes_focus_tags(self, axis_payload: Mapping[str, Any]) -> list[str]:
        if not (
            axis_payload.get("temporaryFocus")
            or axis_payload.get("focusComboId")
            or axis_payload.get("focusedCombo")
        ):
            return []
        tags: list[str] = []
        tags.extend(self._coerce_tags(axis_payload.get("focusComboTags")))
        tags.extend(self._split_tags(axis_payload.get("focusComboText")))
        return [tag for tag in tags if tag]

    def _expression_tags(self, axis_payload: Mapping[str, Any]) -> list[str]:
        tags: list[str] = []
        for item in axis_payload.get("items") or []:
            tags.extend(self._tags_from_item(item))
        tags.extend(self._coerce_tags(axis_payload.get("tags")))
        tags.extend(self._coerce_tags(axis_payload.get("promptTags")))
        tags.extend(self._split_tags(axis_payload.get("prompt")))
        return [tag for tag in tags if tag]

    def _manual_tags(self, payload: Mapping[str, Any]) -> list[str]:
        tags = self._coerce_tags(payload.get("manualTags"))
        tags.extend(self._split_tags(payload.get("manualPrompt")))
        manual = payload.get("manual")
        if isinstance(manual, Mapping):
            tags.extend(self._tags_from_fragment(manual))
        return [tag for tag in tags if tag]

    def _tags_from_fragment(self, fragment: Any) -> list[str]:
        if isinstance(fragment, Mapping):
            if isinstance(fragment.get("fragment"), Mapping):
                nested = self._tags_from_fragment(fragment.get("fragment"))
                if nested:
                    return nested
            if isinstance(fragment.get("promptFragment"), Mapping):
                nested = self._tags_from_fragment(fragment.get("promptFragment"))
                if nested:
                    return nested
            tags: list[str] = []
            tags.extend(self._coerce_tags(fragment.get("tags")))
            tags.extend(self._coerce_tags(fragment.get("promptTags")))
            tags.extend(self._split_tags(fragment.get("prompt")))
            prompt_fragment = fragment.get("promptFragment")
            if not isinstance(prompt_fragment, Mapping):
                tags.extend(self._split_tags(prompt_fragment))
            return tags
        return self._coerce_tags(fragment)

    def _tags_from_item(self, item: Any) -> list[str]:
        if isinstance(item, Mapping):
            tags = self._coerce_tags(item.get("tags"))
            tags.extend(self._coerce_tags(item.get("promptTags")))
            tags.extend(self._split_tags(item.get("prompt")))
            tag = str(item.get("tag") or "").strip()
            if tag:
                tags.append(tag)
            return tags
        return self._coerce_tags(item)

    def _coerce_tags(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return self._split_tags(value)
        if isinstance(value, Mapping):
            return self._tags_from_fragment(value)
        if isinstance(value, (list, tuple, set)):
            tags: list[str] = []
            for item in value:
                if isinstance(item, Mapping):
                    tags.extend(self._tags_from_item(item))
                else:
                    text = str(item or "").strip()
                    if text:
                        tags.append(text)
            return tags
        text = str(value or "").strip()
        return [text] if text else []

    @staticmethod
    def _split_tags(value: Any) -> list[str]:
        if value is None:
            return []
        text = str(value or "").strip()
        if not text:
            return []
        result: list[str] = []
        current: list[str] = []
        angle_depth = 0
        for char in text:
            if char == "<":
                angle_depth += 1
                current.append(char)
            elif char == ">":
                angle_depth = max(0, angle_depth - 1)
                current.append(char)
            elif char == "," and angle_depth == 0:
                tag = "".join(current).strip()
                if tag:
                    result.append(tag)
                current = []
            else:
                current.append(char)
        tag = "".join(current).strip()
        if tag:
            result.append(tag)
        return result

    @staticmethod
    def _axis_enabled(axis_payload: Any) -> bool:
        if not isinstance(axis_payload, Mapping):
            return False
        if "enabled" in axis_payload:
            return bool(axis_payload.get("enabled"))
        return any(
            axis_payload.get(key)
            for key in (
                "eventId",
                "eventTag",
                "comboId",
                "comboPrompt",
                "comboTags",
                "tags",
                "prompt",
                "promptTags",
                "items",
                "amendedItems",
            )
        )

    @staticmethod
    def _normalize_rating(value: Any) -> str:
        raw = str(value or "s").strip().lower()
        if raw in RATING_TAGS:
            return raw
        return RATING_ALIASES.get(raw, "s")

    @staticmethod
    def _normalize_person(value: Any) -> str:
        raw = str(value or "1girl_solo").strip().lower().replace("-", "_")
        raw = PERSON_ALIASES.get(raw, raw.replace(" ", "_"))
        return raw if raw in PERSON_PARTITION_ORDER else "1girl_solo"

    @staticmethod
    def _request_id(payload: Mapping[str, Any]) -> str:
        return str(payload.get("requestId") or payload.get("request_id") or "").strip()
