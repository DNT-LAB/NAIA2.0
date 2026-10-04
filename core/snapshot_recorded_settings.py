"""전역 설정은 캡처만 한다. 복원 경로에서 호출할 쓰기 기능을 두지 않는다."""

from __future__ import annotations

import copy
import json
from typing import Any


def capture_recorded_settings(context: Any) -> dict[str, Any]:
    def read_file(filename):
        data = json.loads(context._existing_save_path(filename).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid settings file")
        return data

    def category_filters():
        from core.prompt_engineering_settings import load_category_filter_overrides

        # 로더의 기본값 폴백을 실제 기록으로 오인하지 않도록 읽을 수 있는 파일인지 먼저 본다.
        read_file("pp_category_filters.json")
        return load_category_filter_overrides(save_root=context._save_path())

    def boost_settings():
        from core.boost_v2 import SETTINGS_FILE, load_boost_v2_settings

        read_file(SETTINGS_FILE)
        return load_boost_v2_settings(save_root=context._save_path())

    def hires_overlay():
        from core.prompt_engineering_settings import (
            get_prompt_engineering_store, is_synthetic_preset_name, sanitize_preset_name,
        )

        name = get_prompt_engineering_store(context).state()["current_preset"]
        if not name or is_synthetic_preset_name(name) or sanitize_preset_name(name) != name:
            raise ValueError("No file preset overlay")
        # NAI 캡처에서 WEBUI의 동명 프리셋을 빌려 오지 않는다. 현재 모드에 실제 있는 사본만 기록한다.
        path = context._existing_save_path("presets", context.get_api_mode(), f"{name}.hires.json")
        return json.loads(path.read_text(encoding="utf-8"))

    readers = (
        ("category_filters", category_filters), ("boost_v2_settings", boost_settings),
        ("e621_global", lambda: read_file("e621_boost_user.json")),
        ("danbooru_weight_global", lambda: read_file("danbooru_auto_weight_user.json")),
        ("ollama_auto_boost", lambda: bool(context.ollama_auto_boost)),
        ("hires_overlay", hires_overlay),
    )
    recorded = {}
    for key, read in readers:
        try:
            value = read()
            json.dumps(value, allow_nan=False)
            recorded[key] = copy.deepcopy(value)
        except Exception:
            # 한 파일의 부재/손상 때문에 다른 설정의 근거까지 잃지 않게 키별로 격리한다.
            continue
    return recorded
