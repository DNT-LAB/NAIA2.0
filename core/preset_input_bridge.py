"""Autocomplete/load bridge for ``preset:`` prompt tokens.

The bridge is intentionally UI-free. It parses a partially typed preset path
and returns the next set of selectable items so desktop/web inputs can later
present the same interaction pattern.
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote


PRESET_PREFIX = "preset:"
PRESET_AXES: tuple[dict[str, str], ...] = (
    {"id": "events", "label": "Events", "desc": "Event Preset taxonomy"},
    {"id": "clothes", "label": "Clothes", "desc": "Clothes Preset combos"},
    {"id": "expressions", "label": "Expressions", "desc": "Expression Preset catalog"},
    {"id": "custom", "label": "Custom", "desc": "User-defined preset bridge slot"},
)
RATING_OPTIONS: tuple[dict[str, str], ...] = (
    {"id": "g", "label": "G", "name": "General"},
    {"id": "s", "label": "S", "name": "Sensitive"},
    {"id": "q", "label": "Q", "name": "Questionable"},
    {"id": "e", "label": "E", "name": "Explicit"},
)
EVENT_SHORTCUT_NOISE_TAGS: frozenset[str] = frozenset({
    "looking at viewer",
    "solo",
    "simple background",
    "white background",
    "transparent background",
    "upper body",
    "portrait",
    "cowboy shot",
    "full body",
})
EVENT_SHORTCUT_IDENTITY_TAGS: frozenset[str] = frozenset({
    "1girl",
    "1boy",
    "2girls",
    "2boys",
    "multiple girls",
    "multiple boys",
    "multiple girls multiple boys",
    "1girl 1boy",
})


class PresetInputBridge:
    """Resolve ``preset:`` path tokens into load/status/suggestion payloads."""

    DEFAULT_CONTEXT = {"ratingId": "s", "personId": "1girl_solo"}

    def __init__(
        self,
        repo_root: Path | str,
        *,
        event_service: Any | None = None,
        clothes_service: Any | None = None,
        expression_service: Any | None = None,
        context: dict[str, str] | None = None,
    ):
        self.repo_root = Path(repo_root)
        self._event_service = event_service
        self._clothes_service = clothes_service
        self._expression_service = expression_service
        self.context = {**self.DEFAULT_CONTEXT, **(context or {})}

    def suggest(self, token: str, limit: int = 24) -> dict[str, Any]:
        """Return the next completion layer for a partially typed ``preset:`` token."""
        parsed = self.parse_token(token)
        if not parsed["active"]:
            return {"ok": True, "active": False, "suggestions": []}

        axis = parsed["axis"]
        if not axis:
            return self._axis_payload(parsed, limit)

        if axis == "custom":
            return {
                **self._base_payload(parsed, "custom"),
                "dataReady": True,
                "loadState": {"main": "ready", "message": "Custom preset path selected."},
                "suggestions": [],
            }

        status = self._axis_status(axis)
        ready = self._status_ready(status)
        if not ready:
            return self._loading_payload(parsed, axis, status)

        if axis == "events":
            return self._event_payload(parsed, limit, status)
        if axis == "clothes":
            return self._clothes_payload(parsed, limit, status)
        if axis == "expressions":
            return self._expression_payload(parsed, limit, status)

        return self._axis_payload(parsed, limit)

    def resolve_prompt_token(self, token: str, chooser: Any | None = None) -> dict[str, Any]:
        """Resolve a ``preset:`` token into prompt tags for generation time.

        Event category/subcategory/item paths intentionally collapse to one
        observed combo at prompt-processing time. This keeps incomplete preset
        paths usable as wildcard-like prompts without requiring GUI selection.
        """
        parsed = self.parse_token(token)
        if not parsed["active"]:
            return {"ok": True, "applied": False, "reason": "inactive", "token": token}
        if parsed.get("axis") != "events":
            return {"ok": True, "applied": False, "reason": "unsupported_axis", "token": token}

        status = self._axis_status("events")
        if not self._status_ready(status):
            return {
                "ok": True,
                "applied": False,
                "reason": "not_ready",
                "token": token,
                "loadState": self._load_state(status),
            }

        chooser = chooser or random.choice
        selected = self._resolve_event_selection(parsed, chooser)
        if not selected.get("event"):
            return {"ok": True, "applied": False, "reason": selected.get("reason") or "not_found", "token": token}

        service = self._event_service or self._make_event_service()
        event = selected["event"]
        _, combos = self._event_detail_for_selection(service, selected, event)
        if selected.get("stage") in {"category", "subcategory"}:
            alternate = self._resolve_observed_event_selection(service, selected, chooser)
            if alternate:
                selected = alternate["selected"]
                event = selected["event"]
                combos = alternate["combos"]
        if not combos:
            tags = event.get("promptAtoms") or [event.get("tag") or event.get("id")]
            prompt = self._join_tags(tags)
            return {
                "ok": True,
                "applied": bool(prompt),
                "reason": "event_fallback",
                "token": token,
                "axis": "events",
                "stage": selected["stage"],
                "tags": self._split_prompt(prompt),
                "prompt": prompt,
                "selected": self._selected_event_payload(selected),
            }

        combo = self._resolve_combo(parsed, combos, chooser, event=event)
        if not combo:
            return {"ok": True, "applied": False, "reason": "combo_not_found", "token": token}
        prompt = self._join_tags(combo.get("tags") or combo.get("prompt"))
        return {
            "ok": True,
            "applied": bool(prompt),
            "reason": "",
            "token": token,
            "axis": "events",
            "stage": selected["stage"],
            "tags": self._split_prompt(prompt),
            "prompt": prompt,
            "selected": self._selected_event_payload(selected),
            "combo": {
                "id": combo.get("id") or "",
                "label": combo.get("label") or "",
                "prompt": combo.get("prompt") or prompt,
            },
        }

    def parse_token(self, token: str) -> dict[str, Any]:
        raw = str(token or "").strip()
        if not raw.lower().startswith(PRESET_PREFIX):
            return {"active": False}

        body = raw[len(PRESET_PREFIX):]
        parts = body.split("/") if body else [""]
        axis_query = parts[0].strip().lower()
        axis = self._axis_id(axis_query)
        return {
            "active": True,
            "raw": raw,
            "body": body,
            "axis": axis,
            "axisQuery": axis_query,
            "segments": [unquote(part.strip()) for part in parts[1:]],
            "trailingSlash": body.endswith("/"),
        }

    def _axis_payload(self, parsed: dict[str, Any], limit: int) -> dict[str, Any]:
        query = parsed.get("axisQuery") or ""
        items = []
        for axis in PRESET_AXES:
            axis_id = axis["id"]
            label = axis["label"]
            if query and query not in axis_id and query not in label.lower():
                continue
            items.append({
                "tag": label,
                "value": f"{PRESET_PREFIX}{axis_id}",
                "count": 0,
                "desc": axis["desc"],
                "group": "preset",
                "cat": "axis",
                "_wc_type": "preset_path",
                "axis": axis_id,
                "stage": "axis",
            })
        return {
            **self._base_payload(parsed, "axis"),
            "dataReady": True,
            "loadState": {"main": "ready", "message": "Preset axes are available."},
            "suggestions": items[:limit],
        }

    def _event_payload(self, parsed: dict[str, Any], limit: int, status: dict[str, Any]) -> dict[str, Any]:
        service = self._event_service or self._make_event_service()
        data = service.bootstrap(
            rating_id=self.context["ratingId"],
            person_id=self.context["personId"],
            limit=8000,
        )
        event_context = self._event_context_payload(data)
        categories = [item for item in data.get("categories") or [] if isinstance(item, dict)]
        segments = parsed["segments"]

        category = self._match_node(categories, segments[0] if len(segments) >= 1 else "")
        if len(segments) < 1 or not category:
            return self._with_event_context(
                self._suggest_nodes(parsed, status, "category", categories, "events", limit),
                event_context,
            )

        subcategories = [item for item in category.get("subcategories") or [] if isinstance(item, dict)]
        subcategory = self._match_node(subcategories, segments[1] if len(segments) >= 2 else "")
        if len(segments) < 2 or not subcategory:
            return self._with_event_context(
                self._suggest_nodes(
                    parsed,
                    status,
                    "subcategory",
                    subcategories,
                    "events",
                    limit,
                    parent_segments=[category["id"]],
                ),
                event_context,
            )

        events = [item for item in subcategory.get("events") or [] if isinstance(item, dict)]
        event = self._match_node(events, segments[2] if len(segments) >= 3 else "")
        if len(segments) < 3 or not event:
            return self._with_event_context(
                self._suggest_nodes(
                    parsed,
                    status,
                    "item",
                    events,
                    "events",
                    limit,
                    parent_segments=[category["id"], subcategory["id"]],
                ),
                event_context,
            )

        selected = service.select({
            "ratingId": self.context["ratingId"],
            "personId": self.context["personId"],
            "categoryId": category["id"],
            "subcategoryId": subcategory["id"],
            "eventId": event.get("id") or event.get("tag"),
        })
        event_detail = selected.get("event") if isinstance(selected, dict) else None
        combos = event_detail.get("observedCombos") if isinstance(event_detail, dict) else []
        suggestions = []
        for combo in self._rank_event_combos(event, combos or []):
            if not isinstance(combo, dict):
                continue
            combo_id = str(combo.get("id") or "")
            path = self._path("events", [category["id"], subcategory["id"], event.get("id") or event.get("tag"), combo_id])
            suggestions.append({
                "tag": combo.get("label") or combo.get("prompt") or combo_id,
                "value": path,
                "count": self._count(combo),
                "desc": combo.get("prompt") or "",
                "group": "preset/events",
                "cat": "combo",
                "_wc_type": "preset_path",
                "axis": "events",
                "stage": "combo",
                "final": True,
                "comboId": combo_id,
                "prompt": combo.get("prompt") or "",
                "tags": combo.get("tags") or [],
            })

        return {
            **self._base_payload(parsed, "combo"),
            "dataReady": True,
            "loadState": self._load_state(status),
            "lockInput": True,
            **event_context,
            "selected": {
                "axis": "events",
                "categoryId": category["id"],
                "subcategoryId": subcategory["id"],
                "eventId": event.get("id") or event.get("tag"),
            },
            "suggestions": suggestions[:limit],
        }

    def _clothes_payload(self, parsed: dict[str, Any], limit: int, status: dict[str, Any]) -> dict[str, Any]:
        service = self._clothes_service or self._make_clothes_service()
        data = service.bootstrap({
            "ratingId": self.context["ratingId"],
            "personId": self.context["personId"],
            "comboLimit": limit,
        })
        combo_rows = data.get("comboRows") if isinstance(data, dict) else {}
        suggestions = []
        for row in (combo_rows or {}).get("rows") or []:
            if not isinstance(row, dict):
                continue
            combo_id = str(row.get("id") or "")
            suggestions.append({
                "tag": row.get("comboText") or row.get("prompt") or combo_id,
                "value": self._path("clothes", [combo_id]),
                "count": self._count(row),
                "desc": row.get("prompt") or "",
                "group": "preset/clothes",
                "cat": "combo",
                "_wc_type": "preset_path",
                "axis": "clothes",
                "stage": "combo",
                "final": True,
                "comboId": combo_id,
                "prompt": row.get("prompt") or row.get("comboText") or "",
                "tags": row.get("tags") or [],
            })
        return {
            **self._base_payload(parsed, "combo"),
            "dataReady": True,
            "loadState": self._load_state(status),
            "lockInput": True,
            "suggestions": suggestions[:limit],
        }

    def _expression_payload(self, parsed: dict[str, Any], limit: int, status: dict[str, Any]) -> dict[str, Any]:
        service = self._expression_service or self._make_expression_service()
        data = service.bootstrap({
            "ratingId": self.context["ratingId"],
            "personId": self.context["personId"],
            "limit": 50000,
        })
        categories = [item for item in data.get("categories") or [] if isinstance(item, dict)]
        segments = parsed["segments"]
        category = self._match_node(categories, segments[0] if len(segments) >= 1 else "")
        if len(segments) < 1 or not category:
            return self._suggest_nodes(parsed, status, "category", categories, "expressions", limit)
        subcategories = [item for item in category.get("subcategories") or [] if isinstance(item, dict)]
        subcategory = self._match_node(subcategories, segments[1] if len(segments) >= 2 else "")
        if len(segments) < 2 or not subcategory:
            return self._suggest_nodes(
                parsed,
                status,
                "subcategory",
                subcategories,
                "expressions",
                limit,
                parent_segments=[category["id"]],
            )
        items = [
            item
            for item in [*(subcategory.get("items") or []), *(subcategory.get("moreItems") or [])]
            if isinstance(item, dict)
        ]
        return self._suggest_nodes(
            parsed,
            status,
            "item",
            items,
            "expressions",
            limit,
            parent_segments=[category["id"], subcategory["id"]],
            final=True,
        )

    def _suggest_nodes(
        self,
        parsed: dict[str, Any],
        status: dict[str, Any],
        stage: str,
        nodes: list[dict[str, Any]],
        axis: str,
        limit: int,
        parent_segments: list[str] | None = None,
        final: bool = False,
    ) -> dict[str, Any]:
        query = self._current_query(parsed, stage)
        suggestions = []
        for node in nodes:
            if not self._matches_node(node, query):
                continue
            node_id = str(node.get("id") or node.get("tag") or node.get("label") or "")
            path = self._path(axis, [*(parent_segments or []), node_id])
            label = self._display_label(node)
            suggestions.append({
                "tag": label,
                "value": path,
                "count": self._count(node),
                "desc": self._node_desc(node, stage),
                "group": f"preset/{axis}",
                "cat": stage,
                "_wc_type": "preset_path",
                "axis": axis,
                "stage": stage,
                "final": final,
                "id": node_id,
                "rawLabel": node.get("label") or node.get("tag") or node_id,
                "tags": node.get("tags") or node.get("promptAtoms") or [],
                "prompt": self._prompt_from_node(node),
            })
        return {
            **self._base_payload(parsed, stage),
            "dataReady": True,
            "loadState": self._load_state(status),
            "lockInput": True,
            "suggestions": suggestions[:limit],
        }

    def _axis_status(self, axis: str) -> dict[str, Any]:
        if axis == "events":
            return (self._event_service or self._make_event_service()).status()
        if axis == "clothes":
            return (self._clothes_service or self._make_clothes_service()).status()
        if axis == "expressions":
            return (self._expression_service or self._make_expression_service()).status()
        return {"dataAvailability": {"main": "ready", "message": ""}}

    def _resolve_event_selection(self, parsed: dict[str, Any], chooser: Any) -> dict[str, Any]:
        service = self._event_service or self._make_event_service()
        data = service.bootstrap(
            rating_id=self.context["ratingId"],
            person_id=self.context["personId"],
            limit=8000,
        )
        categories = [item for item in data.get("categories") or [] if isinstance(item, dict)]
        segments = self._non_empty_segments(parsed)
        category = self._match_node(categories, segments[0] if len(segments) >= 1 else "")
        if not category:
            return {"reason": "category_not_found"}

        subcategories = [item for item in category.get("subcategories") or [] if isinstance(item, dict)]
        if len(segments) >= 2:
            subcategory = self._match_node(subcategories, segments[1])
            if not subcategory:
                return {"reason": "subcategory_not_found"}
        else:
            subcategory = self._choose_non_empty(subcategories, "events", chooser)
            if not subcategory:
                return {"reason": "empty_category"}

        events = [item for item in subcategory.get("events") or [] if isinstance(item, dict)]
        if len(segments) >= 3:
            event = self._match_node(events, segments[2])
            if not event:
                return {"reason": "event_not_found"}
            stage = "item"
        else:
            event = chooser(events) if events else None
            if not event:
                return {"reason": "empty_subcategory"}
            stage = "subcategory" if len(segments) >= 2 else "category"

        return {
            "stage": stage,
            "category": category,
            "subcategory": subcategory,
            "event": event,
            "categoryId": category.get("id") or "",
            "subcategoryId": subcategory.get("id") or "",
            "eventId": event.get("id") or event.get("tag") or "",
        }

    def _resolve_combo(
        self,
        parsed: dict[str, Any],
        combos: list[dict[str, Any]],
        chooser: Any,
        *,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        segments = self._non_empty_segments(parsed)
        if len(segments) >= 4:
            combo = self._match_node(combos, segments[3])
            if combo:
                return combo
            for item in combos:
                if str(item.get("id") or "").lower() == str(segments[3] or "").lower():
                    return item
            return None
        ranked = self._rank_event_combos(event or {}, combos)
        return self._choose_shortcut_item(ranked, chooser)

    def _resolve_observed_event_selection(
        self,
        service: Any,
        selected: dict[str, Any],
        chooser: Any,
    ) -> dict[str, Any] | None:
        candidates = []
        category = selected.get("category") if isinstance(selected.get("category"), dict) else None
        subcategory = selected.get("subcategory") if isinstance(selected.get("subcategory"), dict) else None
        subcategories = []
        if selected.get("stage") == "category" and category:
            subcategories = [
                item for item in category.get("subcategories") or []
                if isinstance(item, dict)
            ]
        elif selected.get("stage") == "subcategory" and subcategory:
            subcategories = [subcategory]

        for candidate_subcategory in subcategories:
            events = [
                item for item in candidate_subcategory.get("events") or []
                if isinstance(item, dict)
            ]
            for event in events:
                candidate = {
                    **selected,
                    "subcategory": candidate_subcategory,
                    "event": event,
                    "subcategoryId": candidate_subcategory.get("id") or "",
                    "eventId": event.get("id") or event.get("tag") or "",
                }
                _, combos = self._event_detail_for_selection(service, candidate, event)
                if combos:
                    ranked_combos = self._rank_event_combos(event, combos)
                    if not ranked_combos:
                        continue
                    candidates.append({
                        "selected": candidate,
                        "combos": ranked_combos,
                        "_shortcutScore": float(ranked_combos[0].get("_shortcutScore", 0.0) or 0.0),
                        "_shortcutEligible": bool(ranked_combos[0].get("_shortcutEligible")),
                    })
        ranked_candidates = sorted(
            candidates,
            key=lambda item: (
                0 if item.get("_shortcutEligible") else 1,
                -float(item.get("_shortcutScore", 0.0) or 0.0),
            ),
        )
        return self._choose_shortcut_item(ranked_candidates, chooser)

    def _rank_event_combos(self, event: dict[str, Any], combos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = []
        for index, combo in enumerate(combos or []):
            if not isinstance(combo, dict):
                continue
            profile = self._event_combo_shortcut_profile(event, combo)
            item = dict(combo)
            item["_shortcutScore"] = profile["score"]
            item["_shortcutEligible"] = profile["eligible"]
            item["_shortcutReason"] = profile["reason"]
            item["_shortcutTags"] = profile["tags"]
            item["_shortcutOriginalIndex"] = index
            ranked.append(item)
        ranked.sort(
            key=lambda item: (
                0 if item.get("_shortcutEligible") else 1,
                -float(item.get("_shortcutScore", 0.0) or 0.0),
                -self._count(item),
                int(item.get("_shortcutOriginalIndex", 0) or 0),
            )
        )
        return ranked

    def _event_combo_shortcut_profile(self, event: dict[str, Any], combo: dict[str, Any]) -> dict[str, Any]:
        tags = self._combo_tags(combo)
        tag_keys = []
        seen = set()
        for tag in tags:
            key = self._tag_key(tag)
            if not key or key in seen:
                continue
            seen.add(key)
            tag_keys.append(key)

        anchors = self._event_anchor_keys(event)
        anchor_hits = [tag for tag in tag_keys if tag in anchors]
        noise_hits = [
            tag for tag in tag_keys
            if tag in EVENT_SHORTCUT_NOISE_TAGS and tag not in anchors
        ]
        identity_hits = [
            tag for tag in tag_keys
            if tag in EVENT_SHORTCUT_IDENTITY_TAGS and tag not in anchors
        ]
        informative_tags = [
            tag for tag in tag_keys
            if tag not in anchors
            and tag not in EVENT_SHORTCUT_NOISE_TAGS
            and tag not in EVENT_SHORTCUT_IDENTITY_TAGS
        ]
        singleton = len(tag_keys) <= 1
        eligible = len(tag_keys) >= 2 and bool(informative_tags)
        score = (
            math.log1p(max(0, self._count(combo)))
            + len(informative_tags) * 4.0
            + len(anchor_hits) * 2.0
            + min(len(tag_keys), 6) * 0.2
            - len(noise_hits) * 2.5
            - len(identity_hits) * 1.5
            - (9.0 if singleton else 0.0)
            - (3.0 if not anchor_hits else 0.0)
        )
        reason = "shortcut"
        if singleton:
            reason = "single_tag"
        elif not informative_tags:
            reason = "low_information"
        return {
            "score": round(score, 4),
            "eligible": eligible,
            "reason": reason,
            "tags": tag_keys,
        }

    @staticmethod
    def _choose_shortcut_item(items: list[dict[str, Any]], chooser: Any) -> dict[str, Any] | None:
        if not items:
            return None
        scored = [
            item for item in items
            if isinstance(item, dict) and item.get("_shortcutScore") is not None
        ]
        if not scored:
            return chooser(items[:12])
        eligible = [item for item in scored if item.get("_shortcutEligible")]
        if eligible:
            scored = eligible
        best = float(scored[0].get("_shortcutScore", 0.0) or 0.0)
        pool = [
            item for item in scored
            if float(item.get("_shortcutScore", 0.0) or 0.0) >= best - 2.5
        ][:12]
        return chooser(pool or scored[:12])

    @staticmethod
    def _combo_tags(combo: dict[str, Any]) -> list[str]:
        tags = combo.get("tags")
        if isinstance(tags, (list, tuple, set)):
            clean = []
            for tag in tags:
                if isinstance(tag, str) and "," in tag:
                    clean.extend(PresetInputBridge._split_prompt(tag))
                elif str(tag or "").strip():
                    clean.append(str(tag).strip())
            if clean:
                return clean
        for key in ("prompt", "comboText", "label", "tag", "id"):
            value = combo.get(key)
            if value:
                split = PresetInputBridge._split_prompt(value)
                return split or [str(value).strip()]
        return []

    @staticmethod
    def _event_anchor_keys(event: dict[str, Any]) -> set[str]:
        values = []
        for key in ("id", "tag", "label", "canonicalLabel", "prompt"):
            value = event.get(key)
            if value:
                values.extend(PresetInputBridge._split_prompt(value) or [str(value)])
        atoms = event.get("promptAtoms")
        if isinstance(atoms, (list, tuple, set)):
            values.extend(str(item) for item in atoms if str(item or "").strip())
        return {
            key for key in (PresetInputBridge._tag_key(value) for value in values)
            if key
        }

    @staticmethod
    def _tag_key(value: Any) -> str:
        text = unquote(str(value or "")).strip().lower()
        if "::" in text:
            text = text.split("::")[-1]
        text = text.replace("_", " ").replace("-", " ")
        return " ".join(text.split())

    def _event_detail_for_selection(
        self,
        service: Any,
        selected: dict[str, Any],
        event: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        event_payload = service.select({
            "ratingId": self.context["ratingId"],
            "personId": self.context["personId"],
            "categoryId": selected.get("categoryId") or "",
            "subcategoryId": selected.get("subcategoryId") or "",
            "eventId": event.get("id") or event.get("tag"),
        })
        event_detail = event_payload.get("event") if isinstance(event_payload, dict) else None
        combos = event_detail.get("observedCombos") if isinstance(event_detail, dict) else []
        return event_detail, [item for item in combos or [] if isinstance(item, dict)]

    @staticmethod
    def _choose_non_empty(nodes: list[dict[str, Any]], child_key: str, chooser: Any) -> dict[str, Any] | None:
        candidates = [
            node for node in nodes
            if isinstance(node, dict) and any(isinstance(item, dict) for item in node.get(child_key) or [])
        ]
        return chooser(candidates) if candidates else None

    @staticmethod
    def _non_empty_segments(parsed: dict[str, Any]) -> list[str]:
        return [
            str(segment or "").strip()
            for segment in parsed.get("segments") or []
            if str(segment or "").strip()
        ]

    @staticmethod
    def _selected_event_payload(selected: dict[str, Any]) -> dict[str, str]:
        return {
            "axis": "events",
            "categoryId": str(selected.get("categoryId") or ""),
            "subcategoryId": str(selected.get("subcategoryId") or ""),
            "eventId": str(selected.get("eventId") or ""),
        }

    def _loading_payload(self, parsed: dict[str, Any], axis: str, status: dict[str, Any]) -> dict[str, Any]:
        load_result = self._begin_axis_load(axis, parsed)
        if load_result["started"]:
            load_state = self._load_state(status)
            load_state["main"] = "loading"
            load_state["message"] = load_result["message"] or load_state.get("message", "")
            return {
                **self._base_payload(parsed, "loading"),
                "dataReady": False,
                "loadState": load_state,
                "lockInput": True,
                "loadStarted": True,
                "loadAction": load_result["action"],
                "suggestions": [],
            }
        return {
            **self._base_payload(parsed, "unavailable"),
            "dataReady": False,
            "loadState": self._load_state(status),
            "lockInput": False,
            "loadStarted": False,
            "suggestions": [],
        }

    def _begin_axis_load(self, axis: str, parsed: dict[str, Any]) -> dict[str, Any]:
        service = None
        if axis == "events":
            service = self._event_service or self._make_event_service()
        elif axis == "clothes":
            service = self._clothes_service or self._make_clothes_service()
        elif axis == "expressions":
            service = self._expression_service or self._make_expression_service()
        if service is None:
            return {"started": False, "action": "", "message": ""}

        for action in ("start_loading", "request_load", "begin_load"):
            method = getattr(service, action, None)
            if not callable(method):
                continue
            result = method({"axis": axis, "token": parsed.get("raw", "")})
            return {
                "started": True,
                "action": action,
                "message": self._load_message(result),
            }
        return {"started": False, "action": "", "message": ""}

    def _event_context_payload(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = data.get("selected") if isinstance(data, dict) else {}
        persons = data.get("persons") if isinstance(data, dict) else []
        rating_id = str((selected or {}).get("ratingId") or self.context["ratingId"] or "s")
        person_id = str((selected or {}).get("personId") or self.context["personId"] or "1girl_solo")
        person_options = []
        for person in persons or []:
            if not isinstance(person, dict):
                continue
            option_id = str(person.get("id") or person.get("value") or person.get("label") or "").strip()
            if not option_id:
                continue
            person_options.append({
                "id": option_id,
                "label": str(person.get("label") or person.get("name") or option_id).replace("_", " "),
            })
        if not person_options:
            person_options = [{"id": person_id, "label": person_id.replace("_", " ")}]
        return {
            "presetContext": {
                "ratingId": rating_id,
                "personId": person_id,
                "ratingOptions": [dict(item) for item in RATING_OPTIONS],
                "personOptions": person_options,
            }
        }

    @staticmethod
    def _with_event_context(payload: dict[str, Any], event_context: dict[str, Any]) -> dict[str, Any]:
        return {**payload, **event_context}

    def _make_event_service(self):
        from core.event_preset_service import EventPresetService

        self._event_service = EventPresetService(self.repo_root)
        return self._event_service

    def _make_clothes_service(self):
        from core.clothes_preset_service import ClothesPresetService

        self._clothes_service = ClothesPresetService(self.repo_root)
        return self._clothes_service

    def _make_expression_service(self):
        from core.expression_preset_service import ExpressionPresetService

        self._expression_service = ExpressionPresetService(self.repo_root)
        return self._expression_service

    @staticmethod
    def _load_message(result: Any) -> str:
        if isinstance(result, dict):
            return str(result.get("message") or "")
        if isinstance(result, str):
            return result
        return ""

    @staticmethod
    def _base_payload(parsed: dict[str, Any], stage: str) -> dict[str, Any]:
        return {
            "ok": True,
            "active": True,
            "mode": "preset",
            "token": parsed.get("raw", ""),
            "axis": parsed.get("axis") or "",
            "stage": stage,
            "lockInput": False,
        }

    @staticmethod
    def _axis_id(value: str) -> str:
        for axis in PRESET_AXES:
            if axis["id"] == value:
                return axis["id"]
        return ""

    @staticmethod
    def _status_ready(status: dict[str, Any]) -> bool:
        availability = status.get("dataAvailability") if isinstance(status, dict) else None
        if isinstance(availability, dict):
            return availability.get("main") == "ready"
        return bool(status.get("dataReady")) if isinstance(status, dict) else False

    @staticmethod
    def _load_state(status: dict[str, Any]) -> dict[str, Any]:
        availability = status.get("dataAvailability") if isinstance(status, dict) else None
        if isinstance(availability, dict):
            return {
                "main": str(availability.get("main") or ""),
                "message": str(availability.get("message") or ""),
            }
        return {
            "main": "ready" if status.get("dataReady") else "missing",
            "message": str(status.get("message") or ""),
        } if isinstance(status, dict) else {"main": "missing", "message": ""}

    @staticmethod
    def _count(node: dict[str, Any]) -> int:
        for key in ("count", "postCount", "confidence"):
            try:
                value = node.get(key)
                if value is not None:
                    return int(float(value))
            except (TypeError, ValueError):
                continue
        return 0

    @staticmethod
    def _match_node(nodes: list[dict[str, Any]], value: str) -> dict[str, Any] | None:
        needle = str(value or "").strip()
        if not needle:
            return None
        needle_lower = PresetInputBridge._normalize_match(needle)
        for node in nodes:
            if needle_lower in {
                PresetInputBridge._normalize_match(candidate)
                for candidate in PresetInputBridge._node_match_candidates(node)
                if candidate
            }:
                return node
        return None

    @staticmethod
    def _matches_node(node: dict[str, Any], query: str) -> bool:
        needle = PresetInputBridge._normalize_match(query)
        if not needle:
            return True
        return any(
            needle in PresetInputBridge._normalize_match(candidate)
            for candidate in PresetInputBridge._node_match_candidates(node)
            if candidate
        )

    @staticmethod
    def _node_match_candidates(node: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in ("id", "tag", "label"):
            raw = str(node.get(key) or "")
            if not raw:
                continue
            values.append(raw)
            if "::" in raw:
                values.append(raw.split("::")[-1])
        return values

    @staticmethod
    def _normalize_match(value: Any) -> str:
        text = unquote(str(value or "")).strip().lower()
        if "::" in text:
            text = text.split("::")[-1]
        for char in ("_", "-"):
            text = text.replace(char, " ")
        return " ".join(text.split())

    @staticmethod
    def _current_query(parsed: dict[str, Any], stage: str) -> str:
        segments = parsed.get("segments") or []
        index = {"category": 0, "subcategory": 1, "item": 2, "combo": 3}.get(stage, 0)
        if len(segments) > index:
            return str(segments[index] or "")
        return ""

    @staticmethod
    def _node_desc(node: dict[str, Any], stage: str) -> str:
        if stage == "category":
            return f"{len(node.get('subcategories') or [])} subcategories"
        if stage == "subcategory":
            return f"{len(node.get('events') or node.get('items') or [])} items"
        return str(node.get("prompt") or node.get("canonicalLabel") or "")

    @staticmethod
    def _display_label(node: dict[str, Any]) -> str:
        raw = str(node.get("label") or node.get("tag") or node.get("id") or "").strip()
        if "::" in raw:
            raw = raw.split("::")[-1]
        raw = raw.replace("_", " ").strip()
        return raw[:1].upper() + raw[1:] if raw else ""

    @staticmethod
    def _prompt_from_node(node: dict[str, Any]) -> str:
        if node.get("prompt"):
            return str(node.get("prompt") or "")
        tags = node.get("tags") or node.get("promptAtoms") or []
        if isinstance(tags, (list, tuple)):
            return ", ".join(str(item) for item in tags if str(item).strip())
        return str(tags or "")

    @staticmethod
    def _join_tags(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return ", ".join(PresetInputBridge._split_prompt(value))
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    @staticmethod
    def _split_prompt(value: Any) -> list[str]:
        if value is None:
            return []
        return [part.strip() for part in str(value or "").split(",") if part.strip()]

    @staticmethod
    def _path_segment(value: Any) -> str:
        text = unquote(str(value or "")).strip()
        if "::" in text:
            text = text.split("::")[-1]
        return "_".join(text.split())

    @staticmethod
    def _path(axis: str, segments: list[Any]) -> str:
        clean_segments = [
            quote(PresetInputBridge._path_segment(segment), safe="")
            for segment in segments
            if PresetInputBridge._path_segment(segment)
        ]
        return f"{PRESET_PREFIX}{axis}" + ("/" + "/".join(clean_segments) if clean_segments else "")


def search_preset_paths(
    token: str,
    limit: int = 24,
    root: Path | str | None = None,
    **services: Any,
) -> list[dict[str, Any]]:
    """Vibe-style convenience function that returns only suggestion rows."""
    bridge = PresetInputBridge(root or Path.cwd(), **services)
    return bridge.suggest(token, limit=limit).get("suggestions", [])
