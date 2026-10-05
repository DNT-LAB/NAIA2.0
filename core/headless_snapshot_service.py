"""스냅샷의 선택 복원을 제공하고 전역 옵션은 기록만 남긴다."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any, Callable

from core.character_state_transfer import capture_character_state, replace_character_state
from core.nai_model_contract import nai_model_badge
from core.prompt_engineering_settings import get_prompt_engineering_store, is_snapshot_preset_name
from core.snapshot_store import (
    PRESET_SECTIONS, SNAPSHOT_SECTIONS, SnapshotStore, main_setting_section, snapshot_defaults, snapshot_parts,
)
from core.snapshot_reference_transfer import capture_reference_images


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _frames(value: Any) -> list[dict[str, Any]]:
    items = _dict(value).get("frames")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


class HeadlessSnapshotService:
    def __init__(self, context: Any):
        self.context = context
        self._lock = threading.RLock()
        self._reset_search_filter: Callable[[], None] | None = None
        self._rebuild_search_filter: Callable[[], Any] | None = None
        self._defaults_checked: set[str] = set()

    def register_search_runtime(self, *, reset_filter: Callable[[], None],
                                rebuild_filter: Callable[[], Any]) -> None:
        # backend 소유 동작은 경계에서 주입해 core 단독 시험/사용도 명시적으로 처리한다.
        self._reset_search_filter = reset_filter
        self._rebuild_search_filter = rebuild_filter

    def store(self) -> SnapshotStore:
        return get_prompt_engineering_store(self.context).snapshot_store(self.context.get_api_mode())

    def _place_default_snapshots(self, storage: SnapshotStore) -> None:
        """배포판에 실린 기본 스냅샷을 이 모드의 보관함에 놓는다 - 프로세스마다 모드당 한 번만 살핀다
        (놓을지 말지는 보관함의 기록이 정한다: `core.snapshot_defaults`). 실패해도 화면은 그대로 뜬다."""
        mode = str(self.context.get_api_mode() or "")
        if mode in self._defaults_checked:
            return
        self._defaults_checked.add(mode)
        try:
            from core.snapshot_defaults import TEMPLATE_DIR, seed_default_snapshots

            template = self.context.runtime_paths.resource_path(Path(*TEMPLATE_DIR) / mode)
            seed_default_snapshots(storage, template)
        except Exception as exc:  # noqa: BLE001
            print(f"[snapshot] default snapshots skipped: {ascii(exc)}", flush=True)

    def _support_blocker(self) -> str:
        if self.context.get_api_mode() != "NAI":
            return "mode"
        model = self.context.remote_params.get("model")
        return "" if nai_model_badge(model, self.context)["family"] in {"v4.5", "v5"} else "model"

    def state(self) -> dict[str, Any]:
        context = self.context
        storage = self.store()
        self._place_default_snapshots(storage)
        blocker = self._support_blocker()
        has_image = bool(getattr(context.result_store, "latest_webp", None))
        pe_store = get_prompt_engineering_store(context)
        active = ""
        if is_snapshot_preset_name(pe_store.state().get("current_preset")):
            active = str(pe_store.read_preset_data("*snapshot").get("source") or "")
        folders = storage.load_folders()
        rows = storage.list_summaries(lambda data: self._summary(data, storage), folders=folders)
        for row in rows:
            # 사용자 모델 레지스트리는 JSON 밖에서 바뀔 수 있어 작은 배지만 매번 갱신한다.
            badge = nai_model_badge(row["model_key"], context)
            row.update({f"model_{key}": badge[key] for key in ("key", "label", "family", "group", "variant")})
        return {
            "type": "module_state", "module_id": "snapshot", "available": True, "runtime": "web",
            "current_mode": context.get_api_mode(), "supported": not blocker,
            "has_image": has_image, "save_blocker": blocker or ("" if has_image else "no_image"),
            "active": active, "snapshot_count": len(rows), "snapshots": rows,
            "folders": folders,
        }

    def _summary(self, data: dict[str, Any], storage: SnapshotStore) -> dict[str, Any]:
        preset = _dict(data.get("preset"))
        main, module = _dict(preset.get("main_settings")), _dict(preset.get("module_settings"))
        characters = _frames(data.get("characters"))
        badge = nai_model_badge(data.get("model"), self.context)
        prompt = str(main.get("prompt") or "")
        tags = [tag.strip() for tag in prompt.replace("\n", ",").split(",")]
        search = _dict(data.get("search"))
        parts = snapshot_parts(data)
        return {
            "name": data["name"], "created_at": str(data.get("created_at") or ""),
            "folder": data.get("folder", ""),
            "saved_at": str(data.get("saved_at") or ""), "mode": data["mode"],
            **{f"model_{key}": badge[key] for key in ("key", "label", "family", "group", "variant")},
            "resolution": main.get("resolution", ""), "steps": main.get("steps", ""),
            "sampler": main.get("sampler", ""), "character_count": len(characters),
            "sections": [key for key in SNAPSHOT_SECTIONS if isinstance(parts.get(key), dict)],
            "vibe_count": sum(bool(frame.get("is_enabled")) for frame in _frames(data.get("vibe_transfer"))),
            "reference_count": sum(bool(frame.get("is_enabled")) for frame in _frames(data.get("character_reference"))),
            "conditional_enabled": bool(_dict(data.get("conditional")).get("enabled")),
            "search": ({"rows": search.get("rows", 0), "bytes": search.get("bytes", 0),
                        "summary": str(search.get("summary") or "")} if search else None),
            "description": ", ".join([tag for tag in tags if tag and not tag.startswith("#")][:6]),
            "thumbnail_url": storage.image_url(data["name"]),
            "detail": {
                "prompt": prompt, "negative": str(main.get("negative", main.get("negative_prompt", "")) or ""),
                "pre_prompt": str(module.get("pre_prompt") or ""),
                "post_prompt": str(module.get("post_prompt") or ""),
                "characters": [{key: frame.get(key) for key in
                                ("prompt", "uc", "custom_name", "connect_to", "position")}
                               for frame in characters],
            },
        }

    def _response(self, message: str, *, level: str = "info", **fields: Any) -> dict[str, Any]:
        state = self.state()
        state.update(fields)
        state["_headless_extra_messages"] = [self.context._toast(message, level=level)]
        return state

    def _picked_image(self, image_path: str) -> bytes:
        """지목한 그림을 스냅샷의 그림(WebP)으로. 결과 그림 우클릭 > [NAI] 스냅샷 저장이 쓴다.

        경로는 결과 뷰어가 쓰는 것 그대로다: `__history_item__/<id>`(히스토리 항목 - 저장 전의 그림도 된다)
        이거나 저장 폴더 기준의 상대 경로. 저장 폴더 **밖**을 가리키면 거부한다.
        """
        from core.headless_result_service import HISTORY_ITEM_PREFIX

        normalized = str(image_path or "").replace("\\", "/").strip("/")
        if normalized.startswith(HISTORY_ITEM_PREFIX):
            history_id = normalized[len(HISTORY_ITEM_PREFIX):].split("/", 1)[0]
            item = self.context.result_store.get_item(history_id)
            if item is None or not item.webp_bytes:
                raise FileNotFoundError("히스토리에서 사라진 그림입니다")
            return bytes(item.webp_bytes)
        save_dir = self.context._current_save_directory().resolve()
        target = (save_dir / normalized).resolve()
        target.relative_to(save_dir)                      # 밖이면 ValueError
        if not target.is_file() or target.suffix.lower() not in {".png", ".webp", ".jpg", ".jpeg"}:
            raise FileNotFoundError("저장 폴더에서 그림을 찾지 못했습니다")
        import io

        from PIL import Image

        # 히스토리의 그림과 같은 모양(WebP · 품질 85)으로 맞춘다 - 카드와 크게 보기가 한 형식만 다룬다.
        with Image.open(target) as opened:
            picture = opened.convert("RGBA" if opened.mode in ("RGBA", "LA", "P") else "RGB")
            buffer = io.BytesIO()
            picture.save(buffer, format="WEBP", quality=85, method=0)
        return buffer.getvalue()

    def save_preview(self) -> dict[str, Any]:
        """저장 창에 보일 **지금 담으면 무엇이 들어가나**. 읽기만 한다 - 아무것도 쓰지 않는다.

        수치는 카드 아래 한 줄(`_summary`)과 같은 잣대로 센다: 캐릭터 = 실제로 나가는 슬롯,
        Vibe · Reference = 켜 둔 것. 한 구역을 못 읽어도 나머지는 보낸다.
        """
        context = self.context
        badge = nai_model_badge(context.remote_params.get("model"), context)
        preview: dict[str, Any] = {f"model_{key}": badge[key] for key in ("key", "label", "family", "group", "variant")}

        def characters() -> int:
            from core.character_settings import load_character_settings

            settings = load_character_settings(context.get_api_mode(), save_root=context._save_path())
            return len(capture_character_state(settings)["frames"])

        def enabled(getter) -> int:
            return sum(bool(frame.get("is_enabled")) for frame in _frames(getter().capture_snapshot()))

        def search() -> dict[str, Any]:
            from core.temporary_search import is_temporary_search

            if is_temporary_search(context):
                return {"rows": 0, "blocker": "temporary"}
            # 담을 때(`capture_search`)와 같은 작업 뷰를 고른다.
            frame = getattr(context, "search_results_snapshot", None)
            if frame is None or getattr(frame, "empty", True):
                frame = getattr(context, "search_results_master_base_snapshot", None)
            if frame is None or getattr(frame, "empty", True):
                return {"rows": 0, "blocker": "empty"}
            return {"rows": len(frame), "blocker": ""}

        for key, read in (
            ("character_count", characters),
            ("conditional_enabled", lambda: bool(context._conditional_prompt_service().capture_snapshot()["enabled"])),
            ("vibe_count", lambda: enabled(context._vibe_transfer_service)),
            ("reference_count", lambda: enabled(context._character_reference_service)),
            ("search", search),
        ):
            try:
                preview[key] = read()
            except Exception:
                preview[key] = None
        state = self.state()
        state["save_preview"] = preview
        return state

    def capture(self, name: str, include_search: bool = False, overwrite: bool = False,
                folder: str = "", image_path: str = "", sections: list[str] | None = None,
                relocate: bool = False, skip_empty: list[str] | None = None) -> dict[str, Any]:
        prepared = self._prepare_capture(name, include_search, overwrite, folder, image_path, sections, relocate,
                                         skip_empty)
        return prepared() if callable(prepared) else prepared

    def begin_save(self, payload: Any) -> dict[str, Any] | Callable[[], dict[str, Any]]:
        """`save` 명령을 **모으기**까지 한다. 쓸 것이 있으면 쓰기를 맡은 함수를, 아니면 응답을 돌려준다.

        ⚠️ 둘로 나눈 까닭(Codex 리뷰 2026-10-05): 데이터셋을 담는 저장은 파일 쓰기가 길어 작업 스레드에서
           돈다. 그런데 **설정을 읽는 일까지** 스레드에서 하면, 그사이 이벤트 루프에서 다른 창의 프리셋 · 모드
           변경이 끼어든다 - 반쯤 바뀐 설정이 담긴다. 읽기는 부른 자리(이벤트 루프)에서 끝내고, 돌려준
           함수만 스레드로 넘긴다.

        `request_id` 를 주면 응답에 그 저장의 결과를 표시한다(`save_result` 또는 `overwrite_prompt.request_id`) -
        화면이 **자기가 보낸 저장의 답**을 다른 상태 응답(미리보기 등)과 구분한다.
        """
        payload = self._payload(payload)
        request_id = str(payload.get("request_id") or "")

        def stamp(state: dict[str, Any]) -> dict[str, Any]:
            if request_id:
                if isinstance(state.get("overwrite_prompt"), dict):
                    state["overwrite_prompt"]["request_id"] = request_id
                else:
                    state["save_result"] = {"request_id": request_id, "ok": bool(state.get("saved_name")),
                                            "name": str(state.get("saved_name") or "")}
            return state

        if "sections" in payload and not isinstance(payload["sections"], list):
            return stamp(self._response("Snapshot 항목 목록이 올바르지 않습니다", level="error"))
        coerce = self.context._coerce_bool
        prepared = self._prepare_capture(
            str(payload.get("name") or ""), coerce(payload.get("include_search", False)),
            coerce(payload.get("overwrite", False)), payload.get("folder", ""), str(payload.get("image") or ""),
            payload.get("sections"), coerce(payload.get("relocate", False)),
            payload.get("skip_empty") if isinstance(payload.get("skip_empty"), list) else None)
        if callable(prepared):
            return lambda: stamp(prepared())
        return stamp(prepared)

    def _prepare_capture(self, name: str, include_search: bool, overwrite: bool, folder: str, image_path: str,
                         sections: list[str] | None, relocate: bool,
                         skip_empty: list[str] | None = None) -> dict[str, Any] | Callable[[], dict[str, Any]]:
        # `skip_empty`: 켜 둔 것이 하나도 없으면 담지 않을 구역(Vibe · Reference 만 받는다). 저장 창은 그 판단을
        # 미리보기 수치로 하지 않고 **여기에 맡긴다** - 미리보기는 낡을 수 있어, 방금 켠 Vibe 가 빠지곤 했다
        # (Codex 2차 리뷰 2026-10-05). 담는 순간의 값으로 가린다.
        droppable = {key for key in (skip_empty or []) if key in ("vibe_transfer", "character_reference")}
        with self._lock:
            if self._support_blocker():
                return self._response("Snapshot은 NAI V4.5 / V5에서 지원됩니다", level="error")
            wanted: set[str] | None = None
            if sections is not None:
                # 저장 창에서 **고른 항목만** 담는다. 안 고른 항목은 파일에 아예 없다 - 불러올 때 목록에도
                # 안 나온다. 데이터셋도 이 목록이 정한다(`include_search` 는 목록이 없을 때만 본다).
                wanted = {key for key in SNAPSHOT_SECTIONS if key in sections}
                if not wanted:
                    return self._response("담을 항목을 하나 이상 고르세요", level="error")
                include_search = "search" in wanted
            if image_path:
                # 우클릭한 **그 그림**을 쓴다. 마지막 결과로 슬쩍 바꾸지 않는다 - 못 찾으면 담지 않는다.
                try:
                    image = self._picked_image(image_path)
                except Exception as exc:
                    return self._response(f"스냅샷에 넣을 그림을 찾지 못했습니다: {exc}", level="error")
            else:
                image = getattr(self.context.result_store, "latest_webp", None)
            if not image:
                return self._response("먼저 한 장을 생성하세요", level="error")
            storage = self.store()
            try:
                directory = storage.directory(name)
            except ValueError as exc:
                return self._response(str(exc), level="error")
            name = directory.name
            if directory.exists() and not overwrite:
                state = self.state()
                state["overwrite_prompt"] = {"name": name}
                return state
            context = self.context
            data: dict[str, Any] = {
                "mode": context.get_api_mode(), "model": str(context.remote_params.get("model") or ""),
                "app_version": "",
                "folder": folder,
            }
            skipped = []
            try:
                # 프리셋 넷(프롬프트 · 네거티브 · 생성 설정 · 프롬프트 엔지니어링)은 파일에서 한 구역이다.
                # 고른 것만 그 안에 남긴다 - 읽는 쪽(`snapshot_parts`)은 **있는 키**로 항목을 가른다.
                main_wanted = wanted is None or bool(wanted & set(PRESET_SECTIONS[:3]))
                module_wanted = wanted is None or "prompt_engineering" in wanted
                if main_wanted or module_wanted:
                    pe_store = get_prompt_engineering_store(context)
                    preset: dict[str, Any] = {"source_preset": pe_store.state()["current_preset"]}
                    if module_wanted:
                        preset["module_settings"] = copy.deepcopy(pe_store.state()["settings"])
                    if main_wanted:
                        main = context._prompt_engineering_service()._capture_main_settings()
                        main = {key: value for key, value in main.items() if not key.startswith("web_session_")}
                        for key in snapshot_defaults()["extra_main_keys"]:
                            if key in context.remote_params:
                                main[key] = context.remote_params[key]
                        if wanted is not None:
                            main = {key: value for key, value in main.items() if main_setting_section(key) in wanted}
                        preset["main_settings"] = copy.deepcopy(main)
                    json.dumps(preset, allow_nan=False)
                    data["preset"] = preset
            except Exception as exc:
                skipped.append(f"preset: {exc}")
            if wanted is None or "characters" in wanted:
                try:
                    from core.character_settings import load_character_settings

                    settings = load_character_settings(context.get_api_mode(), save_root=context._save_path())
                    characters = capture_character_state(settings)
                    json.dumps(characters, allow_nan=False)
                    data["characters"] = characters
                except Exception as exc:
                    skipped.append(f"characters: {exc}")
            reference_images = {}
            dropped: list[str] = []
            for key, getter in self._u2_services():
                if wanted is not None and key not in wanted:
                    continue
                try:
                    section = getter().capture_snapshot()
                    json.dumps(section, allow_nan=False)
                    if key in droppable and not any(frame.get("is_enabled") for frame in _frames(section)):
                        dropped.append(key)
                        continue
                    if key != "conditional":
                        reference_images.update(capture_reference_images(context, key, section))
                    data[key] = section
                except Exception as exc:
                    skipped.append(f"{key}: {exc}")
            if dropped and not include_search and not any(
                    key in data for key in ("preset", "characters", "conditional", "vibe_transfer", "character_reference")):
                # 고른 것이 전부 '켜 둔 것이 없어' 빠졌다. 저장 창은 이 판단을 여기에 맡긴다(미리보기는 낡을 수 있다) -
                # 그림만 든 빈 스냅샷을 만들지 않고 까닭을 알린다.
                return self._response("담을 것이 없습니다 — 고른 Vibe · Reference 에 켜 둔 것이 없습니다", level="error")
            from core.snapshot_recorded_settings import capture_recorded_settings

            data["recorded_only"] = capture_recorded_settings(context)

            def stage_search(stage):
                from core.snapshot_search_transfer import capture_search

                try:
                    return capture_search(context, stage)
                except Exception as exc:
                    skipped.append(f"search: {exc}")
                    return None

            def commit() -> dict[str, Any]:
                # 여기부터는 **파일 쓰기**다. 위에서 모은 것만 쓴다 - 세션을 다시 읽지 않는다(데이터셋 사본은 예외:
                # 풀은 제 잠금 `search_pool_state_guard` 아래에서 복사한다).
                with self._lock:
                    try:
                        storage.write(name, data, bytes(image), overwrite=overwrite, reference_images=reference_images,
                                      stage_search=stage_search if include_search else None)
                    except FileExistsError:
                        state = self.state()
                        state["overwrite_prompt"] = {"name": name}
                        return state
                    except (OSError, ValueError, TypeError) as exc:
                        return self._response(f"Snapshot 저장 실패: {exc}", level="error")
                    if overwrite and relocate:
                        # 덮어쓰기는 원래 자리를 지킨다(`store.write`). 저장 창에서는 사용자가 카테고리를 **직접
                        # 골랐으므로** 그 자리로 옮긴다. 저장이 끝난 뒤에만 한다 - 실패한 저장이 옛 스냅샷의 자리만
                        # 바꾸면 안 된다.
                        try:
                            storage.move(name, folder)
                        except (OSError, ValueError) as exc:
                            skipped.append(f"folder: {exc}")
                    suffix = " / ".join(skipped)
                    return self._response(f"Snapshot 저장: {name}" + (f" (건너뜀: {suffix})" if suffix else ""),
                                          level="warning" if skipped else "success", saved_name=name)

            return commit

    def _apply_toast(self, name: str, skipped: list, warnings: list) -> dict[str, Any]:
        return self.context._toast(
            f"Snapshot 불러오기: {name}" + (f" (건너뜀 {len(skipped)}개)" if skipped else "")
            + (f" (알림 {len(warnings)}개)" if warnings else ""),
            level="warning" if skipped or warnings else "success")

    def merge_apply(self, first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
        """둘로 나눠 부른 되돌리기(`part="session"` 뒤에 `part="dataset"`)를 **끝맺는다**. 이벤트 루프에서 부른다.

        반쪽들은 한 일만 돌려준다(`_apply_partial`). 화면 상태 저장 · 모듈 상태 모으기 · 알림은 여기서 **한 번** 한다 -
        데이터셋 반쪽이 작업 스레드에서 그것까지 하면, 그사이 다른 창이 모드를 바꿨을 때 먼저 읽은 모드에 나중의
        값이 섞여 저장된다(Codex 2차 리뷰 2026-10-05).
        둘째가 시작도 못 했으면(그사이 모드가 바뀌었다 등) 첫째가 한 일로 끝맺고 그 오류 알림을 덧붙인다.
        """
        first_report = _dict(first.get("apply_report"))
        second_report = _dict(second.get("apply_report"))
        name = str(first_report.get("name") or second_report.get("name") or "")
        restored = [*first_report.get("restored", []), *second_report.get("restored", [])]
        skipped = [*first_report.get("skipped", []), *second_report.get("skipped", [])]
        warnings = [*(first.get("apply_warnings") or []), *(second.get("apply_warnings") or [])]
        state = self._finish_apply(name, restored, skipped, warnings)
        if not second_report:
            state["_headless_extra_messages"].extend(
                message for message in second.get("_headless_extra_messages", []) if isinstance(message, dict))
        return state

    def _finish_apply(self, name: str, restored: list, skipped: list, warnings: list) -> dict[str, Any]:
        """되돌리기의 끝맺음: 화면 상태 저장 · 바뀐 것 알리기 · 모듈 상태 모으기 · 알림. **이벤트 루프에서만** 부른다."""
        context = self.context
        with self._lock:
            for section, action in (
                ("remote_ui_state", context.save_remote_ui_state),
                ("remote_params_changed", lambda: context.publish("remote_params_changed", context.generation_param_schema_payload())),
            ):
                try:
                    action()
                except Exception as exc:
                    warnings.append({"key": section, "reason": str(exc)})
            extra = []
            for module in ("prompt_engineering", "character", "conditional_prompt", "vibe_transfer", "character_reference"):
                try:
                    extra.append(context.module_state_payload(module))
                except Exception as exc:
                    warnings.append({"key": f"state.{module}", "reason": str(exc)})
            try:
                extra.insert(1, context.generation_param_schema_payload())
            except Exception as exc:
                warnings.append({"key": "state.params", "reason": str(exc)})
            extra.insert(2, {"type": "prompt_sync", "prompt": context.prompt_text,
                             "negative": context.negative_prompt_text, "negative_prompt": context.negative_prompt_text,
                             "force": True})
            if "search" in restored:
                try:
                    extra.append(context.search_state_payload())
                except Exception as exc:
                    warnings.append({"key": "state.search", "reason": str(exc)})
            extra.append(self._apply_toast(name, skipped, warnings))
            state = self.state()
            state["apply_report"] = {"name": name, "restored": restored, "skipped": skipped}
            if warnings:
                state["apply_warnings"] = warnings
            state["_headless_extra_messages"] = extra
            return state

    def apply(self, name: str, sections: list[str] | None = None, *, part: str = "") -> dict[str, Any]:
        """`part`: "" = 전부 · "session" = 데이터셋만 빼고 · "dataset" = 데이터셋만.

        ⚠️ 데이터셋을 되돌리는 명령은 둘로 나눠 부른다(`module_commands`): 세션에 값을 넣는 일(프리셋 ·
           캐릭터 · 조건부 · 참조)은 **이벤트 루프 위에서** 해야 다른 창의 프리셋 · 모드 변경과 차례가 지켜진다.
           통째로 작업 스레드에 넘기면 `*snapshot` 으로 넘어가는 도중에 다른 창이 프리셋을 바꿀 수 있고,
           그러면 스냅샷의 값이 그 프리셋에 섞여 저장된다(Codex 리뷰 2026-10-05). 긴 파일 읽기는 데이터셋뿐이다.
        """
        with self._lock:
            context = self.context
            if self._support_blocker():
                return self._response("Snapshot은 NAI V4.5 / V5에서 지원됩니다", level="error")
            try:
                data = self.store().read(name)
            except ValueError as exc:
                return self._response(str(exc), level="error")
            if data is None:
                return self._response(f"Snapshot을 찾지 못했습니다: {name}", level="error")
            if data["mode"] != context.get_api_mode():
                return self._response("Snapshot 모드가 현재 모드와 다릅니다", level="error")
            if nai_model_badge(data.get("model"), context)["family"] not in {"v4.5", "v5"}:
                return self._response("지원하지 않는 Snapshot 모델입니다", level="error")
            name = data["name"]
            parts = snapshot_parts(data)
            if sections is not None and not isinstance(sections, list):
                return self._response("Snapshot 항목 목록이 올바르지 않습니다", level="error")
            selected = [key for key in SNAPSHOT_SECTIONS if key in (parts if sections is None else sections)]
            if part:
                selected = [key for key in selected if (key == "search") == (part == "dataset")]
                if not selected:
                    # 나눠 부른 반쪽에 할 일이 없다 - 한 일이 없다고만 돌려준다(끝맺음은 `merge_apply`).
                    return {"apply_report": {"name": name, "restored": [], "skipped": []},
                            "apply_warnings": [], "_apply_partial": True}
            if not selected:
                return self._response("선택한 Snapshot 항목이 없습니다",
                                      apply_report={"name": name, "restored": [], "skipped": []})
            pe_store = get_prompt_engineering_store(context)
            restored: list[str] = []
            skipped: list[dict[str, str]] = []
            warnings: list[dict[str, str]] = []
            preset_selected = [key for key in PRESET_SECTIONS if key in selected]
            # 캐릭터만 골랐다면 떠나는 프리셋 저장도 작업본 전환도 하지 않는다.
            if preset_selected:
                # D1: 저장 실패 시 어떤 복원도 시작하지 않는다. 현재 값 캡처보다 먼저 저장한다.
                if not is_snapshot_preset_name(pe_store.state().get("current_preset")):
                    try:
                        pe_store.persist_active_settings()
                    except OSError as exc:
                        return self._response(f"현재 프리셋 저장 실패 — 불러오기를 취소했습니다: {exc}", level="error")
                valid = []
                for key in preset_selected:
                    if key not in parts:
                        skipped.append({"section": key, "reason": "missing"})
                    elif not isinstance(parts[key], dict):
                        skipped.append({"section": key, "reason": "Malformed snapshot section"})
                    else:
                        valid.append(key)
                try:
                    pe = context._prompt_engineering_service()
                    # 선택하지 않은 값은 살아 있는 세션에서 가져와 재시작/다음 저장의 오염을 막는다.
                    main = pe._capture_main_settings()
                    module = copy.deepcopy(pe_store.state()["settings"])
                    if "prompt_engineering" in valid:
                        module = copy.deepcopy(parts["prompt_engineering"])
                    picked_main = {}
                    for key in PRESET_SECTIONS[:3]:
                        if key in valid:
                            picked_main.update(parts[key])
                    if "negative" in valid:
                        # 작업본에는 정식 키 하나만 남겨 옛 별칭이 현재 값을 덮지 못하게 한다.
                        picked_main["negative"] = picked_main.pop("negative_prompt", picked_main.get("negative", ""))
                        main.pop("negative_prompt", None)
                    main.update(copy.deepcopy(picked_main))
                    pe_store.install_snapshot_working(name, module, main, context.get_api_mode())
                    failures = pe.apply_snapshot_main_settings(picked_main)
                    skipped.extend(failures)
                    failed_keys = {row["key"] for row in failures}
                    restored.extend(key for key in valid if key == "prompt_engineering" or
                                    any(("negative" if item == "negative_prompt" else item) not in failed_keys
                                        for item in parts[key]))
                    # 키별 실패/타입 정규화가 있어도 작업본과 실제 세션을 같은 값으로 유지한다.
                    try:
                        pe_store.write_preset_data("*snapshot", context.get_api_mode(), {
                            "source": name, "api_mode": context.get_api_mode(),
                            "module_settings": pe_store.collect_settings(), "main_settings": pe._capture_main_settings(),
                        })
                    except Exception as exc:
                        warnings.append({"key": "working_copy", "reason": str(exc)})
                except Exception as exc:
                    skipped.extend({"section": key, "reason": str(exc)} for key in valid)
                    if not valid:
                        warnings.append({"key": "working_copy", "reason": str(exc)})
            if "characters" in selected:
                if "characters" not in parts:
                    skipped.append({"section": "characters", "reason": "missing"})
                else:
                    try:
                        section = parts["characters"]
                        frames = self._validate_characters(section)
                        replace_character_state(context, context.get_api_mode(),
                                                frames, section["position_mode"], is_active=section["is_active"])
                        context._v5_scene_last_event = ""
                        restored.append("characters")
                    except Exception as exc:
                        skipped.append({"section": "characters", "reason": str(exc)})
            for key, getter in self._u2_services():
                if key not in selected:
                    continue
                if key not in parts:
                    skipped.append({"section": key, "reason": "missing"})
                    continue
                try:
                    if key == "conditional":
                        getter().restore_snapshot(parts[key], name,
                                                  save_user_presets=snapshot_defaults()["save_conditional_user_presets"])
                    else:
                        getter().restore_snapshot(parts[key], self.store().reference_directory(name, key))
                    restored.append(key)
                except Exception as exc:
                    skipped.append({"section": key, "reason": str(exc)})
            reference_keys = ("vibe_transfer", "character_reference")
            if any(key in restored for key in reference_keys):
                # 모델 적용보다 참조 복원이 뒤다. 재활성화된 미지원 도구를 같은 모델 가드로 정리한다.
                try:
                    disabled = context._remote_state_service()._disable_unsupported_reference_frames(
                        "model", modules=tuple(key for key in reference_keys if key in restored))
                    for key in disabled:
                        if key in restored and any(frame.get("is_enabled") for frame in _frames(parts[key])):
                            skipped.append({"section": key, "reason": f"Unsupported by current model: {context.remote_params.get('model')}"})
                except Exception as exc:
                    warnings.append({"key": "reference_model_guard", "reason": str(exc)})
                if all(key in restored and any(frame.get("is_enabled") for frame in _frames(parts[key]))
                       for key in reference_keys):
                    warnings.append({"key": "reference_mutual_exclusion",
                                     "reason": "Snapshot records both references enabled; preserved where the current model supports them"})
            if "search" in selected:
                if "search" not in parts:
                    skipped.append({"section": "search", "reason": "missing"})
                else:
                    try:
                        from core.snapshot_search_transfer import restore_search

                        persisted = restore_search(context, parts["search"], self.store().pool_path(name),
                                                   self._reset_search_filter, self._rebuild_search_filter)
                        restored.append("search")
                        if persisted is None:
                            warnings.append({"key": "search.persist_last_search", "reason": "Last-search persistence failed"})
                    except Exception as exc:
                        skipped.append({"section": "search", "reason": str(exc)})
            if part:
                # ⚠️ 나눠 부른 반쪽은 **끝맺음을 하지 않는다.** 데이터셋 반쪽은 작업 스레드에서 돈다 - 여기서 화면
                #    상태를 저장하거나 모듈 상태를 모으면 이벤트 루프의 모드 · 프리셋 변경과 섞인다. 한 일만 돌려주고,
                #    끝맺음은 `merge_apply` 가 이벤트 루프에서 한 번 한다.
                return {"apply_report": {"name": name, "restored": restored, "skipped": skipped},
                        "apply_warnings": warnings, "_apply_partial": True}
            return self._finish_apply(name, restored, skipped, warnings)

    def _u2_services(self):
        return (
            ("conditional", self.context._conditional_prompt_service),
            ("vibe_transfer", self.context._vibe_transfer_service),
            ("character_reference", self.context._character_reference_service),
        )

    @staticmethod
    def _validate_characters(section: Any) -> list[dict[str, Any]]:
        if (not isinstance(section, dict) or not isinstance(section.get("frames"), list)
                or not isinstance(section.get("is_active"), bool)
                or section.get("position_mode") not in {"auto", "custom", "random"}):
            raise ValueError("Missing or malformed characters section")
        frames = section["frames"]
        for frame in frames:
            if not isinstance(frame, dict) or not all(isinstance(frame.get(key), str)
                                                       for key in ("prompt", "uc", "custom_name")):
                raise ValueError("Malformed character frame")
            if not isinstance(frame.get("connect_to"), int):
                raise ValueError("Malformed character Connect number")
            if frame.get("position") is not None and not isinstance(frame["position"], dict):
                raise ValueError("Malformed character position")
        return frames

    def image_payload(self, name: str) -> tuple[bytes, str] | None:
        try:
            path = self.store().image_path(name)
            return (path.read_bytes(), "image/webp") if path else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _payload(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            return _dict(json.loads(str(value or "{}")))
        except (ValueError, TypeError):
            return {}

    def set_param(self, key: str, value: Any) -> dict[str, Any]:
        payload = self._payload(value)
        name = str(payload.get("name") or "")
        if key == "refresh":
            return self.state()
        if key == "preview":
            return self.save_preview()
        if key == "save":
            pending = self.begin_save(payload)
            return pending() if callable(pending) else pending
        if key == "apply":
            if "sections" in payload and not isinstance(payload["sections"], list):
                return self._response("Snapshot 항목 목록이 올바르지 않습니다", level="error")
            return self.apply(name, payload.get("sections"))
        with self._lock:
            try:
                if key == "folder_create":
                    row = self.store().create_folder(name, str(payload.get("parent") or ""))
                    state = self.state()
                    state["created_folder"] = {"id": row["id"], "parent": row["parent"]}
                    return state
                if key == "folder_rename":
                    self.store().rename_folder(str(payload.get("id") or ""), name)
                    return self.state()
                if key == "folder_delete":
                    self.store().delete_folder(str(payload.get("id") or ""))
                    return self.state()
                if key == "move":
                    self.store().move(name, payload.get("folder", ""))
                    return self.state()
                if key == "delete":
                    if not self.store().delete(name):
                        raise FileNotFoundError(name)
                    return self.state()
                if key == "rename":
                    self.store().rename(str(payload.get("old") or ""), str(payload.get("new") or ""))
                    state = self.state()
                    state["_headless_extra_messages"] = [self.context.module_state_payload("prompt_engineering")]
                    return state
                if key == "open_folder":
                    return self.open_folder(name)
            except (OSError, ValueError) as exc:
                return self._response(f"Snapshot {key}: {exc}", level="error")
        return self._response(f"Snapshot action is not supported: {key}")

    def open_folder(self, name: str = "") -> dict[str, Any]:
        import os
        import subprocess
        import sys

        storage = self.store()
        try:
            base = storage.directory(name) if name else storage.root
            base.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(base))
            elif sys.platform.startswith("darwin"):
                subprocess.Popen(["open", str(base)])
            else:
                subprocess.Popen(["xdg-open", str(base)])
        except (OSError, ValueError) as exc:
            return self._response(f"폴더 열기 실패: {exc}", level="error")
        return self._response("폴더를 탐색기에서 열었어요.")
