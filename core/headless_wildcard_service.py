"""Headless Wildcard module state and file-browser service."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any


class HeadlessWildcardService:
    def __init__(self, context: Any):
        self.context = context

    def state(self) -> dict[str, Any]:
        wildcard_count = 0
        manager = self.context.wildcard_manager
        for attr in ("wildcard_dict_tree", "wildcard_dict", "instant_wildcard_dict"):
            value = getattr(manager, attr, None) if manager is not None else None
            if isinstance(value, dict):
                wildcard_count += len(value)
        history, sequential_state = self._collect_runtime_state()
        # NOTE: 필드명을 "state"로 두면 module_state_payload 가 payload["state"]=전체 dict 로
        # 덮어써(키 충돌) 프론트에서 순차 배열이 사라진다. "sequential_state" 로 분리한다.
        return self.context._module_state_payload("wildcard", {
            "history": history,
            "sequential_state": sequential_state,
            "prompt_squeeze": bool(self.context.prompt_squeeze_enabled),
            "wildcard_count": wildcard_count,
            "file_browser_available": True,
        })

    def _collect_runtime_state(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """직전 생성의 PromptContext에서 사용된 와일드카드/순차·종속 상태를 수집한다.

        - Used Wildcards: `wildcard_history` {key: [chosen lines]} → 가장 최근 선택값.
        - Sequential / Dependent State: `wildcard_state` {key: {current, total, ...}}.
        (순차 `__*name__` 와 종속 `__$master:slave__` 둘 다 wildcard_state 에 기록됨)
        """
        ctx = getattr(self.context, "current_prompt_context", None)
        history: list[dict[str, Any]] = []
        sequential_state: list[dict[str, Any]] = []
        if ctx is None:
            return history, sequential_state
        wc_history = getattr(ctx, "wildcard_history", None) or {}
        if isinstance(wc_history, dict):
            for name, values in wc_history.items():
                if not values:
                    continue
                chosen = values[-1] if isinstance(values, (list, tuple)) else values
                history.append({"name": str(name), "value": str(chosen)})
        wc_state = getattr(ctx, "wildcard_state", None) or {}
        if isinstance(wc_state, dict):
            for name, info in wc_state.items():
                if not isinstance(info, dict):
                    continue
                entry = {
                    "name": str(name),
                    "current": int(info.get("current", 0) or 0),
                    "total": int(info.get("total", 0) or 0),
                }
                master = info.get("master_name")
                if master and str(master) not in {"", "unknown"}:
                    entry["master"] = str(master)
                sequential_state.append(entry)
        return history, sequential_state

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        if key == "prompt_squeeze":
            context.prompt_squeeze_enabled = context._coerce_bool(value)
            return self.state()
        if key in {"reset_sequential", "reload"}:
            self.reload_manager()
            return self.state()
        if key == "get_file_tree":
            return {"type": "wildcard_manager", "action": "file_tree", "tree": self.scan_tree()}
        if key == "read_file":
            content = self.read_file(str(value or ""))
            if content is None:
                return context._toast("Wildcard file not found", level="error")
            return {
                "type": "wildcard_manager",
                "action": "file_content",
                "path": str(value or ""),
                "content": content,
            }
        if key == "save_file":
            try:
                payload = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                return context._toast("Invalid wildcard save payload", level="error")
            return self.save_file(
                str(payload.get("path") or ""),
                str(payload.get("content") or ""),
            )
        if key == "delete_file":
            return self.delete_file(str(value or ""))
        if key == "create_file":
            return self.create_file(str(value or ""))
        if key == "preview_wildcard":
            return {
                "type": "wildcard_manager",
                "action": "preview_result",
                "name": str(value or ""),
                "result": self.preview(str(value or "")),
            }
        return context._toast(f"Wildcard action is not supported in this runtime: {key}", level="info")

    def base_dir(self) -> Path:
        manager = self.context.wildcard_manager
        base = getattr(manager, "wildcards_dir", None) if manager is not None else None
        if base:
            return Path(base)
        if os.environ.get("NAIA_USER_DATA_DIR") or os.environ.get("NAIA_PORTABLE"):
            runtime_paths = getattr(self.context, "runtime_paths", None)
            runtime_base = getattr(runtime_paths, "wildcards_dir", None) if runtime_paths is not None else None
            if runtime_base:
                return Path(runtime_base)
        return Path(self.context.repo_root) / "wildcards"

    def validate_path(self, rel_path: str) -> Path | None:
        clean = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
        if not clean:
            return None
        base = self.base_dir().resolve()
        target = (base / clean).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return None
        return target

    def scan_tree(self) -> list[dict[str, Any]]:
        base = self.base_dir()
        if not base.exists():
            return []
        tree: list[dict[str, Any]] = []
        for item in sorted(base.iterdir(), key=lambda path: path.name.lower()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                folder = {"name": item.name, "type": "folder", "files": []}
                for path in sorted(item.rglob("*.txt"), key=lambda path: str(path).lower()):
                    try:
                        lines = len(path.read_text(encoding="utf-8").splitlines())
                    except Exception:
                        lines = 0
                    folder["files"].append({
                        "name": path.name,
                        "path": str(path.relative_to(base)).replace("\\", "/"),
                        "lines": lines,
                    })
                if folder["files"]:
                    tree.append(folder)
            elif item.suffix.lower() == ".txt":
                try:
                    lines = len(item.read_text(encoding="utf-8").splitlines())
                except Exception:
                    lines = 0
                tree.append({"name": item.name, "type": "file", "path": item.name, "lines": lines})
        return tree

    def read_file(self, rel_path: str) -> str | None:
        target = self.validate_path(rel_path)
        if target is None or not target.is_file() or target.suffix.lower() != ".txt":
            return None
        return target.read_text(encoding="utf-8")

    def save_file(self, rel_path: str, content: str) -> dict[str, Any]:
        if not str(rel_path or "").endswith(".txt"):
            return self.context._toast("Wildcard filename must end with .txt", level="error")
        target = self.validate_path(rel_path)
        if target is None:
            return self.context._toast("Invalid wildcard path", level="error")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.reload_manager()
        return {
            "type": "wildcard_manager",
            "action": "file_content",
            "path": str(rel_path).replace("\\", "/"),
            "content": content,
        }

    def delete_file(self, rel_path: str) -> dict[str, Any]:
        target = self.validate_path(rel_path)
        if target is None or not target.is_file() or target.suffix.lower() != ".txt":
            return self.context._toast("Wildcard file not found", level="error")
        target.unlink()
        self.reload_manager()
        return {
            "type": "wildcard_manager",
            "action": "file_deleted",
            "path": str(rel_path).replace("\\", "/"),
        }

    def create_file(self, rel_path: str) -> dict[str, Any]:
        clean = str(rel_path or "").strip()
        if not clean.endswith(".txt"):
            clean += ".txt"
        target = self.validate_path(clean)
        if target is None:
            return self.context._toast("Invalid wildcard path", level="error")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("", encoding="utf-8")
        self.reload_manager()
        return {
            "type": "wildcard_manager",
            "action": "file_content",
            "path": clean.replace("\\", "/"),
            "content": "",
        }

    def preview(self, name: str) -> str:
        clean = str(name or "").strip().replace("\\", "/")
        if clean.endswith(".txt"):
            clean = clean[:-4]
        entries = []
        manager = self.context.wildcard_manager
        tree = getattr(manager, "wildcard_dict_tree", {}) if manager is not None else {}
        if isinstance(tree, dict):
            entries = list(tree.get(clean, []))
        if not entries:
            file_content = self.read_file(f"{clean}.txt")
            if file_content is None:
                file_content = self.read_file(f"{clean.replace('/', '-')}.txt")
            entries = [(1, line.strip()) for line in str(file_content or "").splitlines() if line.strip()]
        if not entries:
            return f"Wildcard '{clean}' not found"
        weights = []
        texts = []
        for entry in entries:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                weights.append(float(entry[0]) if str(entry[0]).replace(".", "", 1).isdigit() else 1.0)
                texts.append(str(entry[1]))
            else:
                weights.append(1.0)
                texts.append(str(entry))
        return "\n".join(f"#{index + 1}: {random.choices(texts, weights=weights, k=1)[0]}" for index in range(5))

    def reload_manager(self) -> None:
        manager = self.context.wildcard_manager
        if manager is not None and hasattr(manager, "reload_wildcards"):
            try:
                manager.reload_wildcards()
            except Exception:
                pass
