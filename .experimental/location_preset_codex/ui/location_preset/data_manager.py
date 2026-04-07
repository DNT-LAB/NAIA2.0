from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LocationPresetDataManager:
    """Thin loader around the generated location preset catalog."""

    def __init__(
        self,
        catalog_path: Path | None = None,
        effect_catalog_path: Path | None = None,
    ):
        if catalog_path is None:
            catalog_path = Path(__file__).resolve().parents[2] / "data" / "location_preset_catalog.json"
        if effect_catalog_path is None:
            effect_catalog_path = Path(__file__).resolve().parents[2] / "data" / "location_state_effect_catalog.json"
        self.catalog_path = Path(catalog_path)
        self.effect_catalog_path = Path(effect_catalog_path)
        self._payload: dict[str, Any] | None = None
        self._effect_payload: dict[str, Any] | None = None
        self._group_map: dict[tuple[str, str], dict[str, Any]] | None = None

    def is_data_available(self) -> bool:
        return self.catalog_path.exists()

    def is_effect_data_available(self) -> bool:
        return self.effect_catalog_path.exists()

    def load(self) -> dict[str, Any]:
        if self._payload is None:
            self._payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if self._group_map is None:
            self._group_map = {
                (group["environment"], group["place"]): group
                for group in self._payload.get("groups", [])
            }
        return self._payload

    def load_effects(self) -> dict[str, Any]:
        if self._effect_payload is None:
            self._effect_payload = json.loads(self.effect_catalog_path.read_text(encoding="utf-8"))
        return self._effect_payload

    def get_summary(self) -> dict[str, Any]:
        return self.load().get("summary", {})

    def get_effect_summary(self) -> dict[str, Any]:
        data = self.load_effects()
        return {
            "effect_group_count": len(data.get("effect_groups", [])),
            "sample_case_count": len(data.get("sample_cases", [])),
        }

    def get_groups(self) -> list[dict[str, Any]]:
        return list(self.load().get("groups", []))

    def get_effect_groups(self) -> list[dict[str, Any]]:
        return list(self.load_effects().get("effect_groups", []))

    def get_environments(self) -> list[str]:
        envs = {group["environment"] for group in self.get_groups()}
        return sorted(envs)

    def get_places(self, environment: str | None = None) -> list[str]:
        groups = self.get_groups()
        if environment:
            groups = [group for group in groups if group["environment"] == environment]
        return sorted(group["place"] for group in groups)

    def get_group(self, environment: str, place: str) -> dict[str, Any] | None:
        self.load()
        assert self._group_map is not None
        return self._group_map.get((environment, place))

    def get_states(self, environment: str, place: str) -> list[dict[str, Any]]:
        group = self.get_group(environment, place)
        if not group:
            return []
        return list(group.get("states", []))

    def get_effect_suggestions(self, environment: str, place: str) -> list[dict[str, Any]]:
        for sample in self.load_effects().get("sample_cases", []):
            if sample.get("environment") == environment and sample.get("place") == place:
                return list(sample.get("supported_effects", []))
        return []

    def search_places(self, query: str, environment: str | None = None) -> list[dict[str, Any]]:
        query_norm = " ".join(str(query or "").strip().lower().replace("_", " ").split())
        if not query_norm:
            return self.get_groups()

        groups = self.get_groups()
        if environment:
            groups = [group for group in groups if group["environment"] == environment]

        results = []
        for group in groups:
            place_norm = " ".join(group["place"].strip().lower().replace("_", " ").split())
            if query_norm in place_norm:
                results.append(group)
                continue

            for state in group.get("states", []):
                state_norm = " ".join(state["tag"].strip().lower().replace("_", " ").split())
                if query_norm in state_norm:
                    results.append(group)
                    break
        return results
