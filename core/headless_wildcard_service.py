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

    def state(self, *, live_update: bool = False) -> dict[str, Any]:
        wildcard_count = 0
        manager = self.context.wildcard_manager
        for attr in ("wildcard_dict_tree", "wildcard_dict", "instant_wildcard_dict"):
            value = getattr(manager, attr, None) if manager is not None else None
            if isinstance(value, dict):
                wildcard_count += len(value)
        history, sequential_state = self._collect_runtime_state()
        # NOTE: 필드명을 "state"로 두면 module_state_payload 가 payload["state"]=전체 dict 로
        # 덮어써(키 충돌) 프론트에서 순차 배열이 사라진다. "sequential_state" 로 분리한다.
        payload = {
            "history": history,
            "sequential_state": sequential_state,
            "prompt_squeeze": bool(self.context.prompt_squeeze_enabled),
            "wildcard_count": wildcard_count,
            "file_browser_available": True,
            "frozen": self._frozen_state(),
        }
        # live_update=True 면 프론트가 파일 브라우저 통째 재구축 없이 런타임 섹션
        # (Used/Sequential)만 in-place 갱신한다(깜빡임/get_file_tree 재요청 회피). Jump 처럼
        # 즉시 반영이 필요한 경로에서 사용. (생성 라이브 틱과 동일 계약 — generation_commands.)
        if live_update:
            payload["live_update"] = True
        return self.context._module_state_payload("wildcard", payload)

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
                # observer(종속) 항목은 wildcard_state 에 master_name 키를 갖는다(미해결 master
                # 면 'unknown'). 선택이 master 사이클에서 파생돼 카운터 직접 점프가 무효이므로,
                # 표시값 유무와 무관하게 dependent 로 표식한다 → 프론트가 Jump 버튼을 숨긴다.
                if "master_name" in info:
                    entry["dependent"] = True
                master = info.get("master_name")
                if master and str(master) not in {"", "unknown"}:
                    entry["master"] = str(master)
                sequential_state.append(entry)
        return history, sequential_state

    @staticmethod
    def _freeze_value_preview(value: Any) -> str:
        if isinstance(value, list):
            return str(value[0] if value else "")
        return str(value or "")

    def _frozen_state(self) -> dict[str, Any]:
        overrides = getattr(self.context, "wildcard_override", None)
        locations: list[dict[str, str]] = []
        legacy: list[dict[str, str]] = []
        if isinstance(overrides, dict):
            for location, value in sorted(overrides.items(), key=lambda item: str(item[0])):
                if isinstance(value, dict):
                    for name, frozen_value in sorted(value.items(), key=lambda item: str(item[0])):
                        locations.append({
                            "location": str(location),
                            "name": str(name),
                            "value": self._freeze_value_preview(frozen_value),
                        })
                else:
                    legacy.append({
                        "name": str(location),
                        "value": self._freeze_value_preview(value),
                    })
        try:
            from core.character_settings import frozen_character_slots_payload

            characters = frozen_character_slots_payload(self.context)
        except Exception:
            characters = []
        return {"locations": locations, "legacy": legacy, "characters": characters}

    def _freeze_location(self, payload: dict[str, Any]) -> bool:
        location = str(payload.get("location") or "").strip()
        name = str(payload.get("key") or payload.get("name") or "").strip()
        value = str(payload.get("value") or "")
        if not location or not name:
            return False
        overrides = getattr(self.context, "wildcard_override", None)
        if not isinstance(overrides, dict):
            overrides = {}
            self.context.wildcard_override = overrides
        scoped = overrides.setdefault(location, {})
        if not isinstance(scoped, dict):
            scoped = {}
            overrides[location] = scoped
        scoped[name] = value
        return True

    def _unfreeze_location(self, payload: dict[str, Any]) -> bool:
        location = str(payload.get("location") or "").strip()
        name = str(payload.get("key") or payload.get("name") or "").strip()
        overrides = getattr(self.context, "wildcard_override", None)
        if not isinstance(overrides, dict) or not name:
            return False
        if location:
            scoped = overrides.get(location)
            if isinstance(scoped, dict):
                changed = scoped.pop(name, None) is not None
                if not scoped:
                    overrides.pop(location, None)
                return changed
            return False
        return overrides.pop(name, None) is not None

    def freeze(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(payload.get("kind") or payload.get("type") or "").strip().lower()
        if kind == "character" or payload.get("slot"):
            from core.character_settings import set_frozen_character_slot

            ok = set_frozen_character_slot(
                self.context,
                payload.get("slot"),
                payload.get("prompt"),
                payload.get("uc", ""),
            )
            if not ok:
                return self.context._toast("Invalid character wildcard freeze payload", level="error")
            return self.state(live_update=True)
        if not self._freeze_location(payload):
            return self.context._toast("Invalid wildcard freeze payload", level="error")
        return self.state(live_update=True)

    def unfreeze(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(payload.get("kind") or payload.get("type") or "").strip().lower()
        if kind == "character" or payload.get("slot"):
            from core.character_settings import clear_frozen_character_slot

            clear_frozen_character_slot(self.context, payload.get("slot"))
            return self.state(live_update=True)
        self._unfreeze_location(payload)
        return self.state(live_update=True)


    def set_sequential(self, name: str, index: Any) -> dict[str, Any]:
        """순차 와일드카드 카운터를 강제로 점프시킨다(사용자 요청 [Jump]).

        1.5에서 "생성 N회 예약 후 취소"로 순차 위치를 맞추던 방식을 대체 — 1-based `index`를
        주면 *다음 생성*의 `__*name__`이 그 위치(=index 번째 항목)를 내도록 카운터를 맞춘다.
        카운터는 PromptContext.sequential_counters 에 저장되고 매 생성마다
        prompt_generation_service._create_initial_context 가 직전 컨텍스트에서 복사해 이어가므로,
        살아있는 current_prompt_context 의 카운터를 직접 세팅하면 다음 생성에 반영된다.

        종속(slave, master 보유) 항목은 master 사이클에서 파생되므로 직접 점프를 막는다.
        """
        wildcard_name = str(name or "").strip()
        if not wildcard_name:
            return self.context._toast("Jump 대상 와일드카드가 없습니다.", level="error")
        ctx = getattr(self.context, "current_prompt_context", None)
        if ctx is None or not isinstance(getattr(ctx, "sequential_counters", None), dict):
            return self.context._toast("순차 상태가 없습니다. 먼저 한 번 생성하세요.", level="error")
        state = getattr(ctx, "wildcard_state", None)
        info = state.get(wildcard_name) if isinstance(state, dict) else None
        # 종속(observer)은 wildcard_state 에 master_name 키를 갖는다(미해결 master 면 'unknown').
        # 어느 경우든 slave 선택은 master 사이클에서 파생돼 카운터 직접 점프가 무효이므로,
        # 'unknown' 포함 master_name 키가 있으면 모두 거부한다(Codex #4: unknown-master no-op 트랩 차단).
        if isinstance(info, dict) and "master_name" in info:
            return self.context._toast(
                "종속(slave) 와일드카드는 직접 점프할 수 없습니다. master 와일드카드를 조정하세요.",
                level="info",
            )
        total = int(info.get("total", 0) or 0) if isinstance(info, dict) else 0
        if total <= 0:
            total = len(self._resolve_entries(wildcard_name))
        if total <= 0:
            return self.context._toast(f"'{wildcard_name}' 항목을 찾을 수 없습니다.", level="error")
        try:
            target = int(index)
        except (TypeError, ValueError):
            return self.context._toast("Jump 위치가 올바르지 않습니다.", level="error")
        target = max(1, min(target, total))
        # 다음 생성: counter=target-1 → entries[(target-1)%total] = target 번째 항목.
        ctx.sequential_counters[wildcard_name] = target - 1
        # 패널에 즉시 반영(생성 전이라도 점프 위치를 보여준다 — 다음 생성이 이 값을 유지).
        if isinstance(info, dict):
            info["current"] = target
            info["total"] = total
        else:
            state = state if isinstance(state, dict) else {}
            state[wildcard_name] = {"current": target, "total": total}
            ctx.wildcard_state = state
        return self.state(live_update=True)

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        if key == "prompt_squeeze":
            context.prompt_squeeze_enabled = context._coerce_bool(value)
            return self.state()
        if key in {"reset_sequential", "reload"}:
            self.reload_manager()
            return self.state()
        if key == "set_sequential":
            try:
                payload = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            return self.set_sequential(str(payload.get("name") or ""), payload.get("index"))
        if key in {"wildcard_freeze", "wildcard_unfreeze"}:
            try:
                payload = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            if key == "wildcard_freeze":
                return self.freeze(payload)
            return self.unfreeze(payload)
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
        if key == "open_folder":
            return self.open_folder()
        if key == "preview_wildcard":
            return {
                "type": "wildcard_manager",
                "action": "preview_result",
                "name": str(value or ""),
                "result": self.preview(str(value or "")),
            }
        if key == "inspect":
            try:
                payload = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            return self.inspect(
                str(payload.get("name") or ""),
                str(payload.get("slave") or ""),
                payload.get("n", 12),
            )
        return context._toast(f"Wildcard action is not supported in this runtime: {key}", level="info")

    def open_folder(self) -> dict[str, Any]:
        """와일드카드 폴더를 OS 파일 탐색기에서 연다(없으면 생성).

        사용자가 NAIA-Portable/user-data/wildcards 경로를 몰라 와일드카드 파일을
        배치하지 못하던 문제 해소용. vibe_transfer.open_storage_location 과 동일한
        로컬 전용 동작(set_param 경로로만 호출)이며, base_dir() 로 포터블/개발 경로를
        일관되게 해석한다. 프론트가 오른쪽 브라우저에서 버튼으로 호출한다."""
        context = self.context
        base = self.base_dir()
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return context._toast(f"와일드카드 폴더를 만들지 못했습니다: {exc}", level="error")
        try:
            import subprocess
            import sys

            if os.name == "nt":
                os.startfile(str(base))  # type: ignore[attr-defined]
            elif sys.platform.startswith("darwin"):
                subprocess.Popen(["open", str(base)])
            else:
                subprocess.Popen(["xdg-open", str(base)])
        except Exception as exc:
            return context._toast(f"폴더 열기 실패: {exc}", level="error")
        return context._toast("와일드카드 폴더를 탐색기에서 열었어요.", level="info")

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

    def _resolve_entries(self, name: str) -> list[tuple[float, str]]:
        """Resolve a wildcard name to its (weight, text) entries (fuzzy key + .txt fallback)."""
        clean = str(name or "").strip().replace("\\", "/")
        if clean.endswith(".txt"):
            clean = clean[:-4]
        manager = self.context.wildcard_manager
        tree = getattr(manager, "wildcard_dict_tree", {}) if manager is not None else {}
        raw: list[Any] = []
        if isinstance(tree, dict):
            raw = list(tree.get(clean, []))
            if not raw:
                for key in tree:
                    if key == clean or key.endswith("/" + clean) or key.endswith("\\" + clean):
                        raw = list(tree[key])
                        break
        if not raw:
            content = self.read_file(f"{clean}.txt")
            if content is None:
                content = self.read_file(f"{clean.replace('/', '-')}.txt")
            raw = [(100, line.strip()) for line in str(content or "").splitlines() if line.strip()]
        entries: list[tuple[float, str]] = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    weight = float(item[0])
                except (TypeError, ValueError):
                    weight = 1.0
                entries.append((weight, str(item[1])))
            elif str(item).strip():
                entries.append((1.0, str(item)))
        return entries

    def inspect(self, name: str, slave: str, n: Any) -> dict[str, Any]:
        """Non-destructive single-wildcard inspect for the tabbed preview/assembly UI.

        Returns the master wildcard's item count + a random roll + the items in order,
        and (when a slave is given) the dependent-cycle math: a master that advances
        every generation needs ``count`` gens per full cycle (= one slave step), and
        ``count * slave_count`` gens to walk every slave value. Reads only — no live
        wildcard/generation state is mutated.
        """
        try:
            count_n = int(n)
        except (TypeError, ValueError):
            count_n = 12
        count_n = max(1, min(count_n, 50))

        entries = self._resolve_entries(name)
        if not entries:
            return self.context._toast(f"Wildcard '{name}' not found", level="error")
        texts = [text for _, text in entries]
        weights = [weight for weight, _ in entries]
        count = len(entries)
        random_roll = [random.choices(texts, weights=weights, k=1)[0] for _ in range(count_n)]
        ordered = texts[:count_n]

        payload: dict[str, Any] = {
            "type": "wildcard_manager",
            "action": "inspect_result",
            "name": str(name),
            "count": count,
            "random": random_roll,
            "ordered": ordered,
        }
        slave_name = str(slave or "").strip()
        if slave_name:
            slave_count = len(self._resolve_entries(slave_name))
            payload.update({
                "slave": slave_name,
                "slave_count": slave_count,
                "cycle": count,                 # gens for master to complete one cycle (= one slave step)
                "total": count * slave_count,   # gens to walk every slave value
            })
        return payload

    def reload_manager(self) -> None:
        manager = self.context.wildcard_manager
        if manager is not None and hasattr(manager, "reload_wildcards"):
            try:
                manager.reload_wildcards()
            except Exception:
                pass
