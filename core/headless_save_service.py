"""Headless Auto Save and Save Directory module state service."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import re

from core import image_classification
from core import result_image_payload_service as result_images
from core.headless_payload_utils import is_loopback_host


AUTO_SAVE_DEFAULTS = {
    "auto_save": True,
    "save_as_webp": False,
    "history_limit_enabled": False,
    "max_history_length": 2000,
    "memory_action": 1,
    # Ctrl+S 빠른 저장. 보고 있는 이미지를 지정 경로로 따로 남긴다.
    #   quicksave_mode   Auto Save 가 켜져 있을 때 원본을 어떻게 할지
    #                    copy = 남긴다(기본) / move = 원본을 지운다
    #                    Auto Save 가 꺼져 있으면 원본이 없으므로 항상 새로 쓴다.
    #   quicksave_dir    빈 문자열이면 저장 폴더와 같은 곳을 쓴다
    #   quicksave_folder date = 세션 시작 일자 폴더 아래 / flat = 지정 경로 바로 아래
    "quicksave_mode": "copy",
    "quicksave_dir": "",
    "quicksave_folder": "date",
}
QUICKSAVE_MODE_OPTIONS = [
    {"value": "copy", "label": "복사 (원본 유지)"},
    {"value": "move", "label": "이동 (원본 삭제)"},
]
QUICKSAVE_FOLDER_OPTIONS = [
    {"value": "date", "label": "세션 일자 폴더 아래"},
    {"value": "flat", "label": "지정 경로 바로 아래"},
]
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
        state["auto_save"] = context._coerce_bool(state["auto_save"])
        state["save_as_webp"] = context._coerce_bool(state["save_as_webp"])
        state["history_limit_enabled"] = context._coerce_bool(state["history_limit_enabled"])
        state["max_history_length"] = int(state["max_history_length"] or 2000)
        state["memory_action"] = int(state["memory_action"] or 1)
        state["unsaved_history_count"] = context.result_store.unsaved_history_count()
        state["memory_action_options"] = list(AUTO_SAVE_MEMORY_ACTION_OPTIONS)
        state["quicksave_mode"] = (str(state.get("quicksave_mode") or "copy")
                                   if str(state.get("quicksave_mode")) in {"copy", "move"}
                                   else "copy")
        state["quicksave_folder"] = (str(state.get("quicksave_folder") or "date")
                                     if str(state.get("quicksave_folder")) in {"date", "flat"}
                                     else "date")
        state["quicksave_dir"] = str(state.get("quicksave_dir") or "")
        state["quicksave_mode_options"] = list(QUICKSAVE_MODE_OPTIONS)
        state["quicksave_folder_options"] = list(QUICKSAVE_FOLDER_OPTIONS)
        # 실제로 어디에 떨어지는지 보여 준다 — 경로를 비워 두면 저장 폴더를 따라간다.
        state["quicksave_resolved"] = str(self.quicksave_directory())
        return context._module_state_payload("auto_save", state)

    # ── Ctrl+S 빠른 저장 ────────────────────────────────────────────────────
    def quicksave_directory(self) -> Path:
        """빠른 저장이 떨어질 폴더. 경로가 비면 저장 폴더를 따라간다."""
        context = self.context
        raw = str(context.auto_save_state.get("quicksave_dir") or "").strip()
        if raw:
            base = Path(raw).expanduser()
            if not base.is_absolute():
                base = context._output_root() / base
        else:
            base = self.current_save_directory(use_timestamp_folder=False)
        folder = str(context.auto_save_state.get("quicksave_folder") or "date")
        return base / context.session_timestamp if folder == "date" else base

    def quicksave_filename(self, source_name: str) -> str:
        """`<세션시작시간>_<원래 이름>`. 이름 규칙은 강제다(사용자 지정).

        같은 세션에서 같은 파일을 두 번 저장해도 덮어쓰지 않도록 번호를 붙인다.
        """
        stem = Path(str(source_name or "image.png")).stem
        suffix = Path(str(source_name or "image.png")).suffix or ".png"
        base = f"{self.context.session_timestamp}_{stem}"
        directory = self.quicksave_directory()
        name = f"{base}{suffix}"
        n = 2
        while (directory / name).exists():
            name = f"{base}_{n}{suffix}"
            n += 1
        return name

    def save_directory_state_payload(self, client_host: str | None = None) -> dict[str, Any]:
        context = self.context
        base_path = str(context.save_directory_state.get("base_path") or "output")
        use_timestamp_folder = context._coerce_bool(
            context.save_directory_state.get("use_timestamp_folder", True)
        )
        control_allowed = True if client_host is None else is_loopback_host(client_host)
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

    def set_auto_save_param(
        self,
        key: str,
        value: Any,
        *,
        client_host: str | None = None,
    ) -> dict[str, Any] | None:
        context = self.context
        if key == "quicksave_dir":
            # 임의의 절대 경로를 받는 유일한 키다. save_directory 와 같은 경계를
            # 걸지 않으면 Cloudflare 로 노출된 세션이 서버 파일시스템 아무 곳에나
            # 쓸 수 있게 된다 — 원격에서는 값을 받지 않고 현재 상태만 돌려준다.
            if client_host is not None and not is_loopback_host(client_host):
                return self.auto_save_state_payload()
            context.auto_save_state[key] = str(value or "")
        elif key in {"quicksave_mode", "quicksave_folder"}:
            allowed = ({o["value"] for o in QUICKSAVE_MODE_OPTIONS}
                       if key == "quicksave_mode"
                       else {o["value"] for o in QUICKSAVE_FOLDER_OPTIONS})
            clean = str(value or "")
            if clean not in allowed:
                return None
            context.auto_save_state[key] = clean
        elif key in {"auto_save", "save_as_webp", "history_limit_enabled"}:
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
        context.save_remote_ui_state()
        return self.auto_save_state_payload()

    def set_save_directory_param(
        self,
        key: str,
        value: Any,
        *,
        client_host: str | None = None,
    ) -> dict[str, Any] | None:
        context = self.context
        if client_host is not None and not is_loopback_host(client_host):
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
        context.save_remote_ui_state()
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
            target = self._save_history_item_to_directory(item, directory, save_as_webp=save_as_webp)
            saved_paths.append(str(target))
        return {
            "saved": len(saved_paths),
            "remaining": context.result_store.unsaved_history_count(),
            "paths": saved_paths,
            "current_save_directory": str(directory),
        }

    def save_history_item(self, item: Any) -> dict[str, Any]:
        context = self.context
        existing_path = str(getattr(item, "filepath", "") or "")
        if existing_path and Path(existing_path).is_file():
            return {
                "saved": 0,
                "remaining": context.result_store.unsaved_history_count(),
                "paths": [existing_path],
                "path": existing_path,
                "current_save_directory": str(Path(existing_path).parent),
            }
        save_as_webp = context._coerce_bool(self.auto_save_state_payload().get("save_as_webp"))
        directory = self.current_save_directory()
        directory.mkdir(parents=True, exist_ok=True)
        target = self._save_history_item_to_directory(item, directory, save_as_webp=save_as_webp)
        return {
            "saved": 1,
            "remaining": context.result_store.unsaved_history_count(),
            "paths": [str(target)],
            "path": str(target),
            "current_save_directory": str(directory),
        }

    def quicksave_item(self, item: Any) -> dict[str, Any]:
        """보고 있는 이미지를 빠른 저장 경로로 남긴다(Ctrl+S).

        **원본이 이미 디스크에 있는 경우**(Auto Save 가 켜져 있었다)는 복사하거나
        옮긴다 — 다시 인코딩하면 메타데이터가 상하고 파일이 커진다.
        원본이 없으면(Auto Save 꺼짐) 메모리의 바이트를 그대로 쓴다.

        이름은 `<세션시작시간>_<원래 이름>` 으로 강제한다(사용자 지정).
        """
        import shutil

        context = self.context
        mode = str(context.auto_save_state.get("quicksave_mode") or "copy")
        directory = self.quicksave_directory()
        directory.mkdir(parents=True, exist_ok=True)

        # 이미 이 항목을 빠른 저장했는가. 이름을 먼저 짓고 비교하면 안 된다 —
        # quicksave_filename 은 충돌을 피하려 매번 새 이름을 내주므로 제자리 판정이
        # 영원히 거짓이 되고, 이동 모드에서는 누를 때마다 파일이 다시 옮겨진다.
        done = str(getattr(item, "quicksave_path", "") or "")
        if done and Path(done).is_file():
            return {"ok": True, "path": done, "mode": "noop",
                    "directory": str(Path(done).parent)}

        source = str(getattr(item, "filepath", "") or "")
        if source and Path(source).is_file():
            src = Path(source)
            target = directory / self.quicksave_filename(src.name)
            if src.resolve() == target.resolve():
                # 이미 그 자리다. 이동이었어도 지우면 안 된다.
                self._remember_quicksave(item, target)
                return {"ok": True, "path": str(target), "mode": "noop",
                        "directory": str(directory)}
            if mode == "move":
                shutil.move(str(src), str(target))
                # 히스토리가 옛 경로를 가리키면 뷰어가 깨진다. 새 경로로 돌린다.
                try:
                    item.filepath = str(target)
                except Exception:
                    pass
            else:
                shutil.copy2(str(src), str(target))
            self._remember_quicksave(item, target)
            return {"ok": True, "path": str(target), "mode": mode,
                    "directory": str(directory)}

        # 원본이 없다(Auto Save 꺼짐) — 메모리에서 새로 쓴다. `move` 는 의미가 없다.
        #
        # 일반 저장 헬퍼를 쓰면 안 된다: 그쪽은 filename_format/카운터/분류 하위
        # 폴더를 적용하고 항목을 saved 로 표시한다. 빠른 저장은 이름 규칙이 강제고
        # (`<세션시작시간>_<원래 이름>`) Auto Save 와는 별개의 사본이므로, 항목의
        # 저장 상태를 건드리면 미저장 개수가 어긋난다.
        save_as_webp = context._coerce_bool(
            context.auto_save_state.get("save_as_webp"))
        # item.filename 은 이미 `.png` 로 끝난다 — 그대로 쓰면 확장자가 겹친다.
        extension = ".webp" if save_as_webp else ".png"
        stem = Path(str(getattr(item, "filename", "") or "image")).stem or "image"
        target = directory / self.quicksave_filename(stem + extension)
        if save_as_webp:
            target.write_bytes(item.webp_bytes)
        else:
            png_bytes, _ = result_images.history_item_png_payload(item, label=item.filename)
            target.write_bytes(png_bytes)
        self._remember_quicksave(item, target)
        return {"ok": True, "path": str(target), "mode": "write",
                "directory": str(directory)}

    @staticmethod
    def _remember_quicksave(item: Any, target: Path) -> None:
        """이 항목을 어디에 빠른 저장했는지 기억한다(중복 저장/재이동 방지)."""
        try:
            item.quicksave_path = str(target)
        except Exception:
            pass

    def current_save_directory(
        self,
        base_path: str | None = None,
        use_timestamp_folder: bool | None = None,
        classification_subfolder: str | None = None,
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
        directory = base / context.session_timestamp if use_timestamp_folder else base
        # 분류 하위 폴더는 타임스탬프 폴더 뒤에 붙는다(데스크톱 get_save_directory와 동일 순서):
        #   timestamp ON : base/<timestamp>/<classification>/<file>
        #   timestamp OFF: base/<classification>/<file>
        if classification_subfolder:
            for part in Path(classification_subfolder).parts:
                directory = directory / part
        return directory

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

    def _classification_subfolder_for_item(self, item: Any) -> str | None:
        """이 아이템의 태그에 분류 규칙을 적용해 저장 하위 폴더를 결정합니다.

        method가 "none"/빈값이면 분류는 no-op(None)이며 기존 저장 경로가 그대로 유지됩니다.
        """
        context = self.context
        method = str(context.save_directory_state.get("classification_method") or "none")
        if method == "none":
            return None
        rules = str(context.save_directory_state.get("classification_rules") or "")
        # 분류는 켰지만 규칙이 비어/공백이면 분류하지 않는다(no-op). 안 그러면 빈 규칙에서
        # classify가 "misc"를 돌려줘 모든 이미지가 misc/ 로 쏠리는 footgun이 된다(Codex MEDIUM).
        # 규칙 없는 활성은 기존처럼 베이스 폴더에 저장.
        if not rules.strip():
            return None
        return image_classification.classify(
            self._item_classification_tags(item),
            method,
            rules,
        )

    @staticmethod
    def _item_classification_tags(item: Any) -> str:
        """분류에 사용할 프롬프트 문자열을 아이템에서 추출합니다.

        저장 메타와 일관되도록, add_api_result가 기록한 실행본 프롬프트를 우선 사용한다:
        prompt_context["main_prompt"]/["final_prompt"] → generation_params["input"]/["prompt"].
        분리는 image_classification.classify 내부에서 split_tags_smart로 수행한다.
        """
        prompt_context = getattr(item, "prompt_context", {}) or {}
        if isinstance(prompt_context, dict):
            for key in ("main_prompt", "final_prompt"):
                value = prompt_context.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        params = getattr(item, "generation_params", {}) or {}
        if isinstance(params, dict):
            for key in ("input", "prompt"):
                value = params.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return ""

    def _save_history_item_to_directory(self, item: Any, directory: Path, *, save_as_webp: bool) -> Path:
        context = self.context
        # 분류 하위 폴더(없으면 None)를 결정해 전달받은 기준 디렉터리 뒤에 붙인다.
        subfolder = self._classification_subfolder_for_item(item)
        if subfolder:
            for part in Path(subfolder).parts:
                directory = directory / part
            directory.mkdir(parents=True, exist_ok=True)
        extension = "webp" if save_as_webp else "png"
        filename = self.next_save_filename(item, extension)
        target = self.unique_output_path(directory / filename)
        if save_as_webp:
            target.write_bytes(item.webp_bytes)
        else:
            png_bytes, _ = result_images.history_item_png_payload(item, label=item.filename)
            target.write_bytes(png_bytes)
        context.result_store.mark_saved(item, target)
        context.save_remote_ui_state()
        return target

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
