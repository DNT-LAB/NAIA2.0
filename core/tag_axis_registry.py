from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AXIS_OVERRIDES_PATH = PROJECT_ROOT / "data" / "tag_index" / "tag_axis_overrides.json"

PRIMARY_AXES = (
    "expression",
    "pose_action",
    "location",
    "meta",
    "object",
    "clothing",
    "characteristic",
    "sexual_or_nsfw",
)

AUXILIARY_AXES = (
    "person_count",
    "person_focus",
)

SPECIAL_AXES = (
    "uncategorized",
)

ALL_AXES = PRIMARY_AXES + AUXILIARY_AXES + SPECIAL_AXES
CLASSIFIED_AXES = PRIMARY_AXES + AUXILIARY_AXES

_PERSON_COUNT_RE = re.compile(r"^(\d+\+?)(boy|girl|other)s?$")
PERSON_COUNT_ORDER = {"boy": 0, "girl": 1, "other": 2}


@dataclass(frozen=True)
class AxisOverride:
    tag: str
    axis: str
    source: str = ""
    action: str = ""
    confidence: float = 0.0
    uncategorized_count: int = 0
    reason: str = ""


@dataclass(frozen=True)
class AxisOverrideApplyResult:
    records_loaded: int
    applied: int
    added: int
    changed: int
    unchanged: int
    skipped_axis: int


def normalize_tag(tag: str) -> str:
    return " ".join(str(tag).replace("_", " ").strip().lower().split())


def person_count_sort_key(tag: str) -> tuple[int, str]:
    match = _PERSON_COUNT_RE.match(normalize_tag(tag))
    if not match:
        return (99, normalize_tag(tag))
    return (PERSON_COUNT_ORDER[match.group(2)], normalize_tag(tag))


def is_person_count_tag(tag: str) -> bool:
    return _PERSON_COUNT_RE.match(normalize_tag(tag)) is not None


def load_axis_override_records(
    path: str | Path | None = None,
    *,
    strict: bool = True,
) -> dict[str, AxisOverride]:
    override_path = Path(path) if path is not None else DEFAULT_AXIS_OVERRIDES_PATH
    if not override_path.exists():
        return {}

    payload = json.loads(override_path.read_text(encoding="utf-8"))
    raw_tag_to_axis = payload.get("tag_to_axis", {})
    records: dict[str, AxisOverride] = {}

    for raw_tag, raw_value in raw_tag_to_axis.items():
        tag = normalize_tag(raw_tag)
        if isinstance(raw_value, str):
            axis = raw_value
            meta = {}
        elif isinstance(raw_value, Mapping):
            axis = str(raw_value.get("axis", ""))
            meta = raw_value
        else:
            if strict:
                raise ValueError(f"Invalid axis override entry for {raw_tag!r}: {type(raw_value).__name__}")
            continue

        if axis not in CLASSIFIED_AXES:
            if strict:
                raise ValueError(f"Invalid axis {axis!r} for tag {raw_tag!r}")
            continue

        records[tag] = AxisOverride(
            tag=tag,
            axis=axis,
            source=str(meta.get("source", "")),
            action=str(meta.get("action", "")),
            confidence=float(meta.get("confidence", 0.0) or 0.0),
            uncategorized_count=int(meta.get("uncategorized_count", 0) or 0),
            reason=str(meta.get("reason", "")),
        )

    return records


def load_tag_axis_overrides(path: str | Path | None = None) -> dict[str, str]:
    return {tag: record.axis for tag, record in load_axis_override_records(path).items()}


def apply_axis_overrides(
    lookup: MutableMapping[str, str],
    path: str | Path | None = None,
    *,
    allowed_axes: set[str] | None = None,
) -> AxisOverrideApplyResult:
    records = load_axis_override_records(path)
    applied = 0
    added = 0
    changed = 0
    unchanged = 0
    skipped_axis = 0

    for tag, record in records.items():
        if allowed_axes is not None and record.axis not in allowed_axes:
            skipped_axis += 1
            continue

        previous = lookup.get(tag)
        if previous is None:
            added += 1
        elif previous == record.axis:
            unchanged += 1
        else:
            changed += 1

        lookup[tag] = record.axis
        applied += 1

    return AxisOverrideApplyResult(
        records_loaded=len(records),
        applied=applied,
        added=added,
        changed=changed,
        unchanged=unchanged,
        skipped_axis=skipped_axis,
    )


class TagAxisRegistry:
    def __init__(
        self,
        base_lookup: Mapping[str, str] | None = None,
        *,
        override_path: str | Path | None = None,
        fallback_axis: str = "uncategorized",
    ) -> None:
        if fallback_axis not in ALL_AXES:
            raise ValueError(f"Invalid fallback axis: {fallback_axis!r}")
        self.fallback_axis = fallback_axis
        self.base_lookup = {
            normalize_tag(tag): axis
            for tag, axis in (base_lookup or {}).items()
            if axis in CLASSIFIED_AXES
        }
        self.overrides = load_tag_axis_overrides(override_path)

    def axis_for(self, tag: str) -> str:
        normalized = normalize_tag(tag)
        if not normalized:
            return self.fallback_axis
        if is_person_count_tag(normalized):
            return "person_count"
        return self.overrides.get(normalized) or self.base_lookup.get(normalized) or self.fallback_axis

    def classify_many(self, tags: list[str]) -> dict[str, list[str]]:
        buckets: dict[str, list[str]] = {axis: [] for axis in ALL_AXES}
        person_count_entries: list[tuple[tuple[int, int, str], str]] = []

        for raw_index, raw_tag in enumerate(tags):
            tag = normalize_tag(raw_tag)
            axis = self.axis_for(tag)
            if axis == "person_count":
                if is_person_count_tag(tag):
                    person_order, _ = person_count_sort_key(tag)
                    person_count_entries.append(((0, person_order, tag), tag))
                else:
                    person_count_entries.append(((1, raw_index, tag), tag))
            else:
                buckets[axis].append(tag)

        if person_count_entries:
            person_count_entries.sort(key=lambda item: item[0])
            buckets["person_count"].extend(tag for _, tag in person_count_entries)

        return buckets
