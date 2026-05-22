"""Headless Auto Save and Save Directory module state service."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import re

from core import result_image_payload_service as result_images


AUTO_SAVE_DEFAULTS = {
    "auto_save": False,
    "save_as_webp": False,
    "history_limit_enabled": False,
    "max_history_length": 2000,
    "memory_action": 1,
}
AUTO_SAVE_MEMORY_ACTION_OPTIONS = [
    {"value": 1, "label": "[1] 1장씩 자동저장+정리"},
    {"value": 2, "label": "[2] 1장씩 저장없이 삭제"},
    {"value": 3, "label": "[3] 자동생성 중단"},
]
SAVE_DIRECTORY_FILENAME_OPTIONS = [
    {"value": "number_only", "label": "번호만 (00001.png)"},
    {"value": "time_number", "label": "시간_번호 (143052_00001.png)"},
    {"value": "datetime", "label": "날짜_시간 (20250108_143052.png)"},
    {"value": "prompt", "label": "프롬프트 (prompt.png)"},
    {"value": "wildcard", "label": "와일드카드 (wildcard.png)"},
]
SAVE_DIRECTORY_CLASSIFICATION_OPTIONS = [
    {"value": "none", "label": "분류 없음"},
    {"value": "prompt_recognition", "label": "프롬프트 인식"},
]


class HeadlessSaveService:
    def __init__(self, context: Any):
        self.context = context

    def auto_save_state_payload(self) -> dict[str, Any]:
        context = self.context
        state = dict(AUTO_SAVE_DEFAULTS)
        state.update({
            key: context.auto_save_state.get(key)
            for key in AUTO_SAVE_DEFAULTS
            if key in context.auto_save_state
        })
        state["auto_save"] = bool(state["auto_save"])
        state["save_as_webp"] = bool(state["save_as_webp"])
        state["history_limit_enabled"] = bool(state["history_limit_enabled"])
        state["max_history_length"] = int(state["max_history_length"] or 2000)
        state["memory_action"] = int(state["memory_action"] or 1)
        state["unsaved_history_count"] = context.result_store.unsaved_history_count()
        state["memory_action_options"] = list(AUTO_SAVE_MEMORY_ACTION_OPTIONS)
        return context._module_state_payload("auto_save", state)

    def save_directory_state_payload(self, client_host: str | None = None) -> dict[str, Any]:
        context = self.context
        base_path = str(context.save_directory_state.get("base_path") or "output")
        use_timestamp_folder = context._coerce_bool(
            context.save_directory_state.get("use_timestamp_folder", True)
        )
        control_allowed = True if client_host is None else context._is_loopback_host(client_host)
        control_reason = "" if control_allowed else "Save directory control is local-only."
        state = {
            "base_path": base_path,
            "current_save_directory": str(self.current_save_directory(base_path, use_timestamp_folder)),
            "session_timestamp": context.session_timestamp,
            "use_timestamp_folder": use_timestamp_folder,
            "save_counter": int(context.save_directory_state.get("save_counter", 1) or 1),
            "filename_format": str(context.save_directory_state.get("filename_format") or "number_only"),
            "filename_format_options": list(SAVE_DIRECTORY_FILENAME_OPTIONS),
            "classification_method": str(context.save_directory_state.get("classification_method") or "none"),
            "classification_method_options": list(SAVE_DIRECTORY_CLASSIFICATION_OPTIONS),
            "classification_rules": str(context.save_directory_state.get("classification_rules") or ""),
            "control_allowed": control_allowed,
            "control_block_reason": control_reason,
            "browse_allowed": control_allowed,
            "browse_block_reason": control_reason,
        }
        return context._module_state_payload("save_directory", state)

    def set_auto_save_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        if key in {"auto_save", "save_as_webp", "history_limit_enabled"}:
            context.auto_save_state[key] = context._coerce_bool(value)
            if key == "auto_save":
                context.remote_options["auto_save"] = bool(context.auto_save_state[key])
        elif key == "max_history_length":
            context.auto_save_state[key] = context._coerce_int(
                value,
                default=2000,
                minimum=100,
                maximum=10000,
            )
        elif key == "memory_action":
            context.auto_save_state[key] = context._coerce_int(value, default=1, minimum=1, maximum=3)
        else:
            return None
        return self.auto_save_state_payload()

    def set_save_directory_param(
        self,
        key: str,
        value: Any,
        *,
        client_host: str | None = None,
    ) -> dict[str, Any] | None:
        context = self.context
        if client_host is not None and not context._is_loopback_host(client_host):
            return self.save_directory_state_payload(client_host)
        if key == "base_path":
            path_value = str(value or "").strip()
            if path_value:
                context.save_directory_state[key] = path_value
        elif key == "use_timestamp_folder":
            context.save_directory_state[key] = context._coerce_bool(value)
        elif key == "filename_format":
            allowed = {item["value"] for item in SAVE_DIRECTORY_FILENAME_OPTIONS}
            if str(value or "") in allowed:
                context.save_directory_state[key] = str(value)
        elif key == "classification_method":
            allowed = {item["value"] for item in SAVE_DIRECTORY_CLASSIFICATION_OPTIONS}
            if str(value or "") in allowed:
                context.save_directory_state[key] = str(value)
        elif key == "classification_rules":
            context.save_directory_state[key] = str(value or "")
        else:
            return None
        return self.save_directory_state_payload(client_host)

    def save_unsaved_history(self) -> dict[str, Any]:
        context = self.context
        items = context.result_store.unsaved_items()
        if not items:
            return {"saved": 0, "remaining": 0, "paths": []}
        save_as_webp = context._coerce_bool(self.auto_save_state_payload().get("save_as_webp"))
        directory = self.current_save_directory()
        directory.mkdir(parents=True, exist_ok=True)
        saved_paths: list[str] = []
        for item in list(items):
            extension = "webp" if save_as_webp else "png"
            filename = self.next_save_filename(item, extension)
            target = self.unique_output_path(directory / filename)
            if save_as_webp:
                target.write_bytes(item.webp_bytes)
            else:
                png_bytes, _ = result_images.history_item_png_payload(item, label=item.filename)
                target.write_bytes(png_bytes)
            context.result_store.mark_saved(item, target)
            saved_paths.append(str(target))
        return {
            "saved": len(saved_paths),
            "remaining": context.result_store.unsaved_history_count(),
            "paths": saved_paths,
            "current_save_directory": str(directory),
        }

    def current_save_directory(
        self,
        base_path: str | None = None,
        use_timestamp_folder: bool | None = None,
    ) -> Path:
        context = self.context
        raw_base = str(base_path or context.save_directory_state.get("base_path") or "output")
        base = Path(raw_base).expanduser()
        if not base.is_absolute():
            if raw_base.strip() in {"", "output"}:
                base = context._output_root()
            else:
                base = context._output_root() / base
        if use_timestamp_folder is None:
            use_timestamp_folder = context._coerce_bool(
                context.save_directory_state.get("use_timestamp_folder", True)
            )
        return base / context.session_timestamp if use_timestamp_folder else base

    def next_save_filename(self, item: Any, extension: str) -> str:
        context = self.context
        counter = int(context.save_directory_state.get("save_counter", 1) or 1)
        filename_format = str(context.save_directory_state.get("filename_format") or "number_only")
        if filename_format == "time_number":
            stem = f"{datetime.now().strftime('%H%M%S')}_{counter:05d}"
        elif filename_format == "datetime":
            stem = datetime.now().strftime("%Y%m%d_%H%M%S")
        elif filename_format == "prompt":
            prompt = ""
            params = getattr(item, "generation_params", {}) or {}
            if isinstance(params, dict):
                prompt = str(params.get("input") or params.get("prompt") or "")
            stem = self.safe_filename_stem(prompt or "prompt")
        elif filename_format == "wildcard":
            stem = self.safe_filename_stem(Path(getattr(item, "filename", "") or "wildcard").stem)
        else:
            stem = f"{counter:05d}"
        context.save_directory_state["save_counter"] = counter + 1
        return f"{stem}.{extension}"

    @staticmethod
    def safe_filename_stem(value: str, *, max_length: int = 120) -> str:
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", str(value or "")).strip(" ._")
        clean = re.sub(r"\s+", " ", clean)
        return (clean[:max_length].strip(" ._") or "naia-result")

    @staticmethod
    def unique_output_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        index = 1
        while True:
            candidate = parent / f"{stem} ({index}){suffix}"
            if not candidate.exists():
                return candidate
            index += 1
