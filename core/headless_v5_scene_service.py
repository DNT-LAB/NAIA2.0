"""Scene 서비스 — 지금 화면의 구도를 씬으로 담고, 씬을 화면에 되돌린다.

담는 범위는 `core/scene_store` 의 머리 주석 참조(세 열쇠 + POS 모드).

⚠️ **새 WS 메시지 타입을 만들지 않는다.** 범용 `module_state` / `set_module_param`
   채널을 그대로 탄다 - 웹 스모크 계약이 메시지 타입을 **순서대로** 세기 때문에
   브로드캐스트를 하나 더하면 그 뒤가 전부 밀린다.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from core.v5_scene_store import (
    delete_scene,
    existing_scene_thumb,
    list_scene_names,
    normalize_scene,
    read_scene,
    sanitize_scene_name,
    scene_summary,
    scene_thumb_revision,
    write_scene,
    write_scene_thumb,
)


def _describe(scene: dict[str, Any]) -> str:
    """카드에 한 줄로 붙일 설명. 메인 프롬프트의 앞 태그를 쓴다.

    따로 적는 칸을 두지 않는다(사용자 지정: 지금은 검색·저장·폴더 열기만) - 대신
    프롬프트에서 뽑으면 적는 수고 없이 늘 최신이고, 검색어로도 그대로 쓰인다.
    """
    text = str(scene.get("prompt") or "")
    tags = [part.strip() for part in text.replace("\n", ",").split(",")]
    tags = [tag for tag in tags if tag and not tag.startswith("#")]
    return ", ".join(tags[:6])


class HeadlessV5SceneService:
    def __init__(self, context: Any):
        self.context = context

    # ── 저장 위치 ────────────────────────────────────────────────────────
    def _save_root(self):
        """`prompt_engineering` 과 같은 뿌리를 쓴다.

        `_save_path()` 는 인자가 없으면 save 루트 자체를 돌려준다
        (`headless_runtime_path_service.save_path`). 컨텍스트가 알려 주지 못하면
        `v5_scene_store` 의 기본 해석(`NAIA_USER_DATA_DIR` → `save/`)에 맡긴다.
        """
        getter = getattr(self.context, "_save_path", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    # ── 상태 ─────────────────────────────────────────────────────────────
    def state(self) -> dict[str, Any]:
        root = self._save_root()
        scenes = []
        for name in list_scene_names(save_root=root):
            scene = read_scene(name, save_root=root)
            if scene is None:
                continue
            revision = scene_thumb_revision(scene["name"], save_root=root)
            characters = scene["characters"]
            # **독립 슬롯**(Connect 로 물려받지 않는 것) 수를 따로 센다. 카드가
            # `2/3` 처럼 보여 준다 - 서로 다른 캐릭터가 몇이고 칸이 몇인지가 한눈에
            # 들어와야 어느 구도인지 알아본다(사용자 지정).
            independent = sum(1 for item in characters if not item.get("connect_to"))
            scenes.append({
                "name": scene["name"],
                "mode": scene["mode"],
                "summary": scene_summary(scene),
                "character_count": len(characters),
                "independent_count": independent,
                "description": _describe(scene),
                "resolution": scene["resolution"],
                # 카드를 눌렀을 때 펼칠 세부. 목록은 가볍게 두되 자세히 보고 싶을 때가
                # 있고, 그때마다 왕복하면 느리다 - 씬 하나가 작아 함께 실어 보낸다.
                "detail": {
                    "prompt": scene["prompt"],
                    "negative": scene["negative"],
                    "position_mode": scene["position_mode"],
                    "characters": [{
                        "prompt": item["prompt"],
                        "uc": item["uc"],
                        "custom_name": item["custom_name"],
                        "connect_to": item["connect_to"],
                        "position": item["position"],
                    } for item in characters],
                },
                # ⚠️ 리비전을 **URL 에 실어** 보낸다. 같은 이름의 씬을 다시 저장하면
                #    파일 경로는 그대로라, 이게 없으면 브라우저가 옛 그림을 계속 쓴다
                #    (이 저장소가 캐릭터 뷰어에서 한 번 밟은 함정).
                "thumbnail_url": (
                    f"/api/v5-scene/thumbnail?name={quote(scene['name'])}&v={revision}"
                    if revision else ""
                ),
            })
        return {
            "type": "module_state",
            "module_id": "v5_scene",
            "available": True,
            "runtime": "web",
            "scenes": scenes,
            "scene_count": len(scenes),
            "current_mode": self.context.get_api_mode(),
        }

    # ── 담기 ─────────────────────────────────────────────────────────────
    def capture(self, name: str) -> dict[str, Any]:
        """지금 화면을 씬으로 담는다.

        ⚠️ 캐릭터는 **원문**을 담는다(`character_frames` 의 prompt/uc 그대로).
           전개된 결과(`_character_roll_snapshot`)를 담으면 씬이 한 장의 사진이 된다.
        ⚠️ Connect 는 uuid 를 번호로 바꿔 담는다 - 활성 무리 안의 1-based 자리다.
           비활성/Cold 슬롯은 씬에 담지 않으므로 번호 체계가 활성 목록과 일치한다.
        """
        from core.character_settings import (
            _frame_uuid,
            active_character_frames,
            load_character_settings,
        )

        context = self.context
        clean = sanitize_scene_name(name)
        if not clean:
            return context._toast("씬 이름을 입력하세요", level="error")

        mode = context.get_api_mode()
        settings = load_character_settings(mode, save_root=self._save_root())
        frames = active_character_frames(settings)
        order = {str(_frame_uuid(frame) or ""): index for index, frame in enumerate(frames)}

        characters = []
        for frame in frames:
            link_uuid = str(frame.get("connect_to") or "")
            link_index = order.get(link_uuid)
            characters.append({
                "prompt": str(frame.get("prompt") or ""),
                "uc": str(frame.get("uc") or ""),
                "custom_name": str(frame.get("custom_name") or ""),
                "position": frame.get("position"),
                # 저장은 1-based 번호. 못 찾으면 0(연결 없음).
                "connect_to": (link_index + 1) if link_index is not None else 0,
            })

        params = dict(getattr(context, "remote_params", None) or {})
        scene = {
            "name": clean,
            "mode": mode,
            "prompt": str(getattr(context, "prompt_text", "") or ""),
            "negative": str(getattr(context, "negative_prompt_text", "") or ""),
            "resolution": str(params.get("resolution") or ""),
            "position_mode": str(settings.get("position_mode") or "auto"),
            "characters": characters,
        }
        path = write_scene(scene, save_root=self._save_root())
        if path is None:
            return context._toast("씬을 저장하지 못했습니다", level="error")
        self._capture_thumb(clean)
        return self.state()

    def _capture_thumb(self, name: str) -> None:
        """지금 화면의 결과 그림을 씬 썸네일로 붙인다.

        ⚠️ 썸네일 실패가 씬 저장을 막지 않는다. 그림이 없을 수도 있고(아직 한 장도 안
           만든 상태) 그건 오류가 아니다 - `_attach_interactive_snapshot_thumb` 와 같은 규약.
        """
        try:
            store = getattr(self.context, "result_store", None)
            data = getattr(store, "latest_webp", None)
            if data:
                write_scene_thumb(name, bytes(data), save_root=self._save_root())
        except Exception as exc:                       # pragma: no cover - 방어
            print(f"[v5-scene] thumb attach skipped: {exc}")

    def thumbnail_payload(self, name: str) -> tuple[bytes, str] | None:
        """`(bytes, media_type)` 또는 없으면 None. HTTP 라우트가 쓴다."""
        path = existing_scene_thumb(name, save_root=self._save_root())
        if path is None:
            return None
        try:
            return path.read_bytes(), "image/webp"
        except OSError:
            return None

    # ── 되돌리기 ─────────────────────────────────────────────────────────
    def apply(self, name: str) -> dict[str, Any]:
        """씬을 화면에 되돌린다. **통째 교체**하되 기존 캐릭터는 비활성으로 남긴다
        (`apply_bulk_characters` 와 같은 규약 - 아무것도 잃지 않는다).

        ⚠️ Cold 슬롯은 건드리지 않는다. 사용자가 일부러 치워 둔 것이다.
        ⚠️ 모드가 다르면 **적용하지 않는다.** NAI 씬의 캐릭터 캡션을 COMFYUI 에 얹으면
           뜻이 없고, 해상도만 맞아 보여 더 헷갈린다.
        """
        from core.character_settings import _new_character_uuid, clear_character_roll_snapshot

        context = self.context
        scene = read_scene(name, save_root=self._save_root())
        if scene is None:
            return context._toast(f"씬을 찾지 못했습니다: {name}", level="error")

        mode = context.get_api_mode()
        if scene["mode"] and scene["mode"] != mode:
            return context._toast(
                f"이 씬은 {scene['mode']} 용입니다 (지금은 {mode})", level="error")

        # 1) 캐릭터 - 새 uuid 를 만들고 번호 링크를 그 uuid 로 되살린다.
        character_service = context._character_service()
        settings = character_service.settings_cache()
        frames = settings.setdefault("character_frames", [])
        uuids = [_new_character_uuid() for _ in scene["characters"]]
        fresh = []
        for index, item in enumerate(scene["characters"]):
            link = item.get("connect_to") or 0
            fresh.append({
                "uuid": uuids[index],
                "prompt": item["prompt"],
                "uc": item["uc"],
                "custom_name": item["custom_name"],
                "position": item["position"],
                "connect_to": uuids[link - 1] if 1 <= link <= len(uuids) else "",
                "slot_state": "active",
                "is_enabled": True,
                "is_muted": False,
            })

        def is_cold(frame: Any) -> bool:
            return (isinstance(frame, dict)
                    and str(frame.get("slot_state") or "").strip().lower() == "cold")

        kept = []
        for frame in frames:
            if is_cold(frame):
                kept.append(frame)
                continue
            if not isinstance(frame, dict):
                continue
            frame["slot_state"] = "inactive"
            frame["is_enabled"] = False
            # 비활성으로 밀린 슬롯의 링크는 정리한다 - 그대로 두면 정규화가
            # "앞만 가리킨다" 규칙으로 지우거나, 새 활성 슬롯을 엉뚱하게 가리킨다.
            frame["connect_to"] = ""
            kept.append(frame)
        frames[:] = fresh + kept
        settings["is_active"] = bool(fresh)
        settings["position_mode"] = scene["position_mode"]
        character_service.save_settings(mode, settings)
        clear_character_roll_snapshot(context, mode)

        # 2) 프롬프트 · 해상도
        context.prompt_text = scene["prompt"]
        context.negative_prompt_text = scene["negative"]
        if scene["resolution"]:
            context.set_param("resolution", scene["resolution"])
        context.save_remote_ui_state()
        context.publish("remote_params_changed", context.generation_param_schema_payload())
        context.publish("prompt_sync", {
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            "negative_prompt": context.negative_prompt_text,
        })
        return self.state()

    # ── 커맨드 ───────────────────────────────────────────────────────────
    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        if key == "refresh":
            return self.state()
        if key == "save":
            return self.capture(str(value or ""))
        if key == "apply":
            return self.apply(str(value or ""))
        if key == "delete":
            if delete_scene(str(value or ""), save_root=self._save_root()):
                return self.state()
            return context._toast("씬을 지우지 못했습니다", level="error")
        if key == "open_folder":
            return self.open_folder()
        if key == "rename":
            try:
                payload = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            return self.rename(str(payload.get("old") or ""), str(payload.get("new") or ""))
        return context._toast(f"V5 Scene action is not supported in this runtime: {key}", level="info")

    def open_folder(self) -> dict[str, Any]:
        """씬 폴더를 OS 탐색기에서 연다(없으면 만든다).

        지금은 씬을 지우거나 이름을 바꾸는 버튼을 두지 않는다(사용자 지정) - 그 대신
        폴더를 열어 주면 파일을 직접 다루면 된다. `wildcard.open_folder` 와 같은 규약.
        """
        import os
        import subprocess
        import sys

        from core.v5_scene_store import scene_dir

        context = self.context
        base = scene_dir(self._save_root())
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return context._toast(f"씬 폴더를 만들지 못했습니다: {exc}", level="error")
        try:
            if os.name == "nt":
                os.startfile(str(base))  # type: ignore[attr-defined]
            elif sys.platform.startswith("darwin"):
                subprocess.Popen(["open", str(base)])
            else:
                subprocess.Popen(["xdg-open", str(base)])
        except Exception as exc:
            return context._toast(f"폴더 열기 실패: {exc}", level="error")
        return context._toast("씬 폴더를 탐색기에서 열었어요.", level="info")

    def rename(self, old: str, new: str) -> dict[str, Any]:
        context = self.context
        scene = read_scene(old, save_root=self._save_root())
        if scene is None:
            return context._toast(f"씬을 찾지 못했습니다: {old}", level="error")
        clean = sanitize_scene_name(new)
        if not clean:
            return context._toast("새 이름을 입력하세요", level="error")
        scene["name"] = clean
        if write_scene(scene, save_root=self._save_root()) is None:
            return context._toast("씬 이름을 바꾸지 못했습니다", level="error")
        # 새 이름으로 쓴 **뒤에** 지운다 - 순서를 뒤집으면 쓰기가 실패했을 때 원본이 없다.
        if sanitize_scene_name(old) != clean:
            delete_scene(old, save_root=self._save_root())
        return self.state()

    # 외부에서 씬 딕셔너리를 그대로 넣고 싶을 때(가져오기 등). 지금은 미사용.
    def import_scene(self, raw: Any) -> dict[str, Any] | None:
        scene = normalize_scene(raw)
        if not scene["name"]:
            return None
        write_scene(scene, save_root=self._save_root())
        return self.state()
