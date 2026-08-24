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
    bare_from_text,
    create_event,
    delete_scene,
    existing_scene_thumb,
    list_event_names,
    list_scene_names,
    move_scene,
    normalize_scene,
    read_scene,
    sanitize_event_name,
    sanitize_scene_name,
    scene_summary,
    scene_thumb_revision,
    tags_of,
    write_scene,
    write_scene_thumb,
)


def bare_prompt(context: Any) -> str:
    """씬에 담을 **사용자의 구도**만 남긴다 - 프롬프트 엔지니어링이 덧댄 것은 뺀다.

    화면의 프롬프트 상자에는 조립된 결과가 들어 있다(Random/생성이 되돌려 씀).
    거기엔 작가·품질·연도처럼 **그때의 취향**이 섞여 있다. 씬은 구도를 담는 것이라
    그걸 같이 담으면 나중에 불러왔을 때 남의 취향이 따라온다 - 그래서 뺀다.
    되돌릴 때 지금 설정으로 다시 입힌다(`redecorate`).

    ⚠️ **중간 덩어리만 떼면 `1girl` 을 잃는다.** 최종 포맷이 인물 수 태그를
       main -> prefix 맨 앞으로 옮기기 때문이다(`prompt_processor._step_final_format`).
       사용자가 남기라고 짚은 것도 `1girl, 3koma, silent comic` 이었다.
       그래서 파이프라인이 **옮기기 전에** 남긴 스냅샷을 먼저 쓴다.
    """
    box = str(getattr(context, "prompt_text", "") or "")
    run = getattr(context, "current_prompt_context", None)
    meta = getattr(run, "metadata", None)
    if isinstance(meta, dict):
        tags = meta.get("boost_main_tags")
        final = str(getattr(run, "final_prompt", "") or "")
        # ⚠️ 스냅샷은 **마지막 파이프라인 실행**의 것이다. 그 뒤에 사용자가 상자를
        #    손으로 고쳤으면 낡은 구도를 담게 된다 - 상자와 산출물이 같을 때만 믿는다.
        if tags and final.strip() == box.strip():
            return ", ".join(str(tag).strip() for tag in tags if str(tag).strip())
    return bare_from_text(box)


def redecorate(context: Any, bare: str) -> str:
    """저장된 구도를 **지금의** 프롬프트 엔지니어링 설정으로 다시 입힌다(사용자 지정).

    상자에 든 글은 생성 경로에서 파이프라인을 타지 않으므로
    (`HeadlessGenerationService._expand_input_wildcards`), 여기서 입혀 두지 않으면
    구도만 덩그러니 남아 작가도 품질 태그도 없이 나간다.

    ⚠️ **전체 파이프라인을 돌리지 않는다.** `PromptProcessor.process()` 는 와일드카드를
       굴리고 해상도를 맞추고 캐릭터 훅까지 깨운다 - 되돌리기 한 번에 그만한 부작용을
       낼 이유가 없다. 프롬프트 엔지니어링 훅과 최종 포맷만 태운다.
    ⚠️ **auto_hide 는 무시한다**(사용자 지정). 씬의 태그는 이미 고른 것이라
       자동 숨김을 다시 걸면 방금 되돌린 구도에서 태그가 사라진다.
    """
    tags = tags_of(bare)
    if not tags:
        return str(bare or "")
    try:
        import pandas as pd

        from core.prompt_context import PromptContext
        from core.prompt_engineering_runtime import PromptEngineeringHeadlessPostHook
        from core.prompt_processor import PromptProcessor

        run = PromptContext(
            # 빈 행이다 - 씬에는 DB 행이 없다. 작가/작품/캐릭터를 넣으면 프롬프트
            # 엔지니어링이 **그 행의** 작가를 앞에 꽂는다(씬에는 없는 정보).
            source_row=pd.Series({"general": ", ".join(tags)}),
            settings={"api_mode": context.get_api_mode()},
            main_tags=list(tags),
        )
        previous = getattr(context, "skip_prompt_engineering_auto_hide", False)
        context.skip_prompt_engineering_auto_hide = True
        try:
            run = PromptEngineeringHeadlessPostHook(context).execute_pipeline_hook(run)
            return PromptProcessor(context)._step_final_format(run)
        finally:
            context.skip_prompt_engineering_auto_hide = previous
    except Exception:
        # 입히기 실패가 되돌리기를 막지 않는다 - 구도라도 돌려주는 편이 낫다.
        return str(bare or "")


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
    def state(self, event: str = "") -> dict[str, Any]:
        """이벤트 목록 + **열린 이벤트 하나**의 컷들.

        ⚠️ 어느 이벤트가 열려 있는지는 **백엔드가 안 든다.** 프론트가 기억하고
           요청마다 실어 보낸다 - 서버가 들면 새로고침·재접속·창 두 개에서 어긋난다.
           못 받으면 첫 이벤트를 연다.
        """
        root = self._save_root()
        events = list_event_names(save_root=root)
        active = sanitize_event_name(event)
        if active not in events:
            active = events[0] if events else ""
        scenes = []
        for name in (list_scene_names(active, save_root=root) if active else []):
            scene = read_scene(active, name, save_root=root)
            if scene is None:
                continue
            revision = scene_thumb_revision(active, scene["name"], save_root=root)
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
                    f"/api/v5-scene/thumbnail?event={quote(active)}"
                    f"&name={quote(scene['name'])}&v={revision}"
                    if revision else ""
                ),
            })
        return {
            "type": "module_state",
            "module_id": "v5_scene",
            "available": True,
            "runtime": "web",
            "events": events,
            "event": active,
            "scenes": scenes,
            "scene_count": len(scenes),
            "current_mode": self.context.get_api_mode(),
        }

    # ── 담기 ─────────────────────────────────────────────────────────────
    def capture(self, event: str, name: str) -> dict[str, Any]:
        """지금 화면을 **열린 이벤트 안의** 한 컷으로 담는다.

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
        clean_event = sanitize_event_name(event)
        if not clean_event:
            return context._toast("이벤트를 먼저 만드세요", level="error")
        if not clean:
            return context._toast("컷 이름을 입력하세요", level="error")

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
            # 프롬프트 엔지니어링이 덧댄 것은 담지 않는다 - 되돌릴 때 지금 설정으로
            # 다시 입힌다(사용자 지정).
            # ⚠️ **네거티브는 담지 않는다**(사용자 지정) - 사유는 `v5_scene_store.normalize_scene`.
            "prompt": bare_prompt(context),
            "resolution": str(params.get("resolution") or ""),
            "position_mode": str(settings.get("position_mode") or "auto"),
            "characters": characters,
        }
        path = write_scene(clean_event, scene, save_root=self._save_root())
        if path is None:
            return context._toast("컷을 저장하지 못했습니다", level="error")
        self._capture_thumb(clean_event, clean)
        return self.state(clean_event)

    def _capture_thumb(self, event: str, name: str) -> None:
        """지금 화면의 결과 그림을 씬 썸네일로 붙인다.

        ⚠️ 썸네일 실패가 씬 저장을 막지 않는다. 그림이 없을 수도 있고(아직 한 장도 안
           만든 상태) 그건 오류가 아니다 - `_attach_interactive_snapshot_thumb` 와 같은 규약.
        """
        try:
            store = getattr(self.context, "result_store", None)
            data = getattr(store, "latest_webp", None)
            if data:
                write_scene_thumb(event, name, bytes(data), save_root=self._save_root())
        except Exception as exc:                       # pragma: no cover - 방어
            print(f"[v5-scene] thumb attach skipped: {exc}")

    def thumbnail_payload(self, event: str, name: str) -> tuple[bytes, str] | None:
        """`(bytes, media_type)` 또는 없으면 None. HTTP 라우트가 쓴다."""
        path = existing_scene_thumb(event, name, save_root=self._save_root())
        if path is None:
            return None
        try:
            return path.read_bytes(), "image/webp"
        except OSError:
            return None

    # ── 배역 이월 ────────────────────────────────────────────────────────
    def _live_cast(self, settings: dict, mode: str) -> dict[int, str]:
        """살아있는 슬롯의 **배역**(`&connect: … &end` 구간)을 순번으로 모은다.

        같은 이벤트 안에서 컷을 넘길 때, 사용자가 이미 배역을 걸어 뒀으면 그 값을
        이어 쓴다(사용자 지정). 이벤트가 배역을 소유하지는 않는다 - 살아있는 화면이
        기준이다.

        ⚠️ 배역이 **와일드카드면 뽑힌 결과**를 이어야 한다(사용자 지정). 다시 굴리면
           컷마다 다른 인물이 나와 만화가 성립하지 않는다. 그 값은 롤 스냅샷의
           `shares` 에 있다 - 전개 때 이미 계산해 둔 "아래로 물려주는 몫"이다.
        ⚠️ 마커가 없는 슬롯은 건너뛴다. `_split_connect_region` 은 마커가 없으면 전체를
           공유로 보므로, 안 거르면 그 슬롯의 연기까지 배역으로 오해한다.
        """
        from core.character_settings import (
            _frame_uuid,
            _split_connect_region,
            active_character_frames,
            has_connect_region,
            read_character_shares,
        )

        shares = read_character_shares(self.context, mode)
        cast: dict[int, str] = {}
        for index, frame in enumerate(active_character_frames(settings), 1):
            raw = str(frame.get("prompt") or "")
            if not has_connect_region(raw):
                continue
            rolled = str(shares.get(str(_frame_uuid(frame) or "")) or "").strip()
            if not rolled:
                rolled = _split_connect_region(raw)[1].strip()
            if rolled:
                cast[index] = rolled
        return cast

    @staticmethod
    def _wear_cast(text: str, cast: str) -> str:
        """씬 슬롯의 배역 자리만 갈아 끼운다. 연기(앞뒤)는 그대로 둔다."""
        from core.character_settings import _split_connect_region

        head, _, tail = _split_connect_region(text)
        return f"{head}&connect: {cast} &end{tail}"

    # ── 되돌리기 ─────────────────────────────────────────────────────────
    def apply(self, event: str, name: str) -> dict[str, Any]:
        """씬을 화면에 되돌린다. **통째 교체**하되 기존 캐릭터는 비활성으로 남긴다
        (`apply_bulk_characters` 와 같은 규약 - 아무것도 잃지 않는다).

        ⚠️ Cold 슬롯은 건드리지 않는다. 사용자가 일부러 치워 둔 것이다.
        ⚠️ 모드가 다르면 **적용하지 않는다.** NAI 씬의 캐릭터 캡션을 COMFYUI 에 얹으면
           뜻이 없고, 해상도만 맞아 보여 더 헷갈린다.
        """
        from core.character_settings import (
            _new_character_uuid,
            clear_character_roll_snapshot,
            has_connect_region,
        )

        context = self.context
        clean_event = sanitize_event_name(event)
        scene = read_scene(clean_event, name, save_root=self._save_root())
        if scene is None:
            return context._toast(f"컷을 찾지 못했습니다: {name}", level="error")

        mode = context.get_api_mode()
        if scene["mode"] and scene["mode"] != mode:
            return context._toast(
                f"이 컷은 {scene['mode']} 용입니다 (지금은 {mode})", level="error")

        # 1) 캐릭터 - 새 uuid 를 만들고 번호 링크를 그 uuid 로 되살린다.
        character_service = context._character_service()
        settings = character_service.settings_cache()
        # ⚠️ **배역은 슬롯을 갈아엎기 전에 걷는다.** 아래에서 frames 를 비활성으로 밀면
        #    `active_character_frames` 가 빈 목록이 되어 이월할 것이 사라진다.
        # ⚠️ 이월은 **같은 이벤트 안에서 컷을 넘길 때만** 걸린다(사용자 지정). 다른
        #    이벤트에서 넘어왔거나 처음 여는 이벤트면 그 컷에 담긴 배역을 그대로 쓴다 -
        #    안 그러면 남의 만화 주인공이 따라 들어온다.
        same_event = bool(clean_event) and (
            getattr(context, "_v5_scene_last_event", "") == clean_event)
        cast = self._live_cast(settings, mode) if same_event else {}
        frames = settings.setdefault("character_frames", [])
        uuids = [_new_character_uuid() for _ in scene["characters"]]
        fresh = []
        worn = 0
        for index, item in enumerate(scene["characters"]):
            link = item.get("connect_to") or 0
            prompt = item["prompt"]
            # 살아있는 배역이 있고, 이 컷도 배역 자리를 열어 뒀을 때만 갈아 끼운다.
            # 자리가 없는 컷에 끼우면 그 컷의 연기를 통째로 덮어쓴다.
            carried = cast.get(index + 1)
            if carried and has_connect_region(prompt):
                prompt = self._wear_cast(prompt, carried)
                worn += 1
            fresh.append({
                "uuid": uuids[index],
                "prompt": prompt,
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
        # 담을 때 뺀 프롬프트 엔지니어링을 여기서 **지금 설정으로** 다시 입힌다.
        # ⚠️ **네거티브는 건드리지 않는다**(사용자 지정). 사용자의 네거티브를 통째로
        #    덮어쓰는 것은 치명적이다 - 구도가 무언가를 빼야 한다면 `-태그` 로 적는다.
        context.prompt_text = redecorate(context, scene["prompt"])
        if scene["resolution"]:
            context.set_param("resolution", scene["resolution"])
        context.save_remote_ui_state()
        context.publish("remote_params_changed", context.generation_param_schema_payload())
        # 다음 컷이 배역을 이어받을 수 있게 어느 이벤트에서 왔는지 남긴다(런타임 전용).
        context._v5_scene_last_event = clean_event
        state = self.state(clean_event)
        # ⚠️ **`publish` 로는 브라우저에 아무것도 안 간다.** 그건 내부 이벤트 버스이고
        #    WebSocket 이 아니다 - 이걸 몰라서 되돌리기가 백엔드만 바꾸고 화면은 옛 글을
        #    든 채였다(재접속해야 보였다). 모듈 응답에 실어 보내는 것이 규약이다.
        # ⚠️ **force 도 함께 필요하다.** `syncPrompts` 는 사용자가 프롬프트를 만지는 중이면
        #    서버 값을 버린다(치던 글 보호). 되돌리기는 사용자가 직접 누른 **의도된 교체**라
        #    그 보호를 넘어야 한다 - 모드 전환·`get_prompt` 와 같은 이유다(`session_commands`).
        # ⚠️ **캐릭터 패널도 같이 밀어 줘야 한다.** 슬롯을 통째로 갈아치웠는데 화면은 옛
        #    슬롯을 들고 있었다(실측) - 저장은 됐지만 사용자가 보는 것은 그대로라
        #    "안 불러와졌다" 로 읽힌다. 되돌리기 하나가 두 패널을 건드리므로 둘 다 보낸다.
        extra: list[dict[str, Any]] = []
        try:
            extra.append(context.module_state_payload("character"))
        except Exception as exc:                       # pragma: no cover - 방어
            print(f"[v5-scene] character state push skipped: {exc}")
        extra.append({
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            # 네거티브는 **지금 값 그대로** 실어 보낸다 - 되돌리는 게 아니라 상자가
            # 어긋나지 않게 하려는 것이다(씬은 네거티브를 담지 않는다).
            "negative": context.negative_prompt_text,
            "negative_prompt": context.negative_prompt_text,
            "force": True,
        })
        state["_headless_extra_messages"] = extra
        if worn:
            state["_headless_extra_messages"].append(
                context._toast(f"배역 {worn}칸을 이어받았습니다", level="info"))
        return state

    # ── 커맨드 ───────────────────────────────────────────────────────────
    @staticmethod
    def _payload(value: Any) -> dict[str, Any]:
        """조작은 `{"event": …, "name": …}` 꼴을 받는다.

        WS 는 값에 dict 를 그대로 실을 수 있고(`module_commands` 가 `command.get("value")`
        를 넘긴다), 옛 호출이나 손으로 보낸 문자열도 JSON 으로 한 번 풀어 본다.
        """
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        payload = self._payload(value)
        event = str(payload.get("event") or "")
        name = str(payload.get("name") or "")
        if key == "refresh":
            return self.state(event)
        if key == "event_create":
            created = create_event(str(payload.get("name") or value or ""), save_root=self._save_root())
            if not created:
                return context._toast("이벤트 이름을 입력하세요", level="error")
            return self.state(created)
        if key == "save":
            return self.capture(event, name)
        if key == "apply":
            return self.apply(event, name)
        if key == "move":
            try:
                delta = int(payload.get("delta") or 0)
            except (TypeError, ValueError):
                delta = 0
            if delta and move_scene(event, name, delta, save_root=self._save_root()):
                return self.state(event)
            return self.state(event)
        if key == "delete":
            if delete_scene(event, name, save_root=self._save_root()):
                return self.state(event)
            return context._toast("컷을 지우지 못했습니다", level="error")
        if key == "open_folder":
            return self.open_folder(event)
        if key == "rename":
            return self.rename(event, str(payload.get("old") or ""), str(payload.get("new") or ""))
        return context._toast(f"V5 Scene action is not supported in this runtime: {key}", level="info")

    def open_folder(self, event: str = "") -> dict[str, Any]:
        """폴더를 OS 탐색기에서 연다(없으면 만든다). 이벤트가 열려 있으면 **그 폴더**를.

        지우기·이름 바꾸기 버튼을 두지 않는다(사용자 지정) - 그 대신 폴더를 열어 주면
        파일을 직접 다루면 된다. `wildcard.open_folder` 와 같은 규약. 컷 순서를 바꾸는
        것도 여기서 `_event.json` 의 `order` 를 고치면 된다.
        """
        import os
        import subprocess
        import sys

        from core.v5_scene_store import event_dir, scene_dir

        context = self.context
        base = event_dir(event, self._save_root()) if sanitize_event_name(event) else None
        if base is None:
            base = scene_dir(self._save_root())
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return context._toast(f"폴더를 만들지 못했습니다: {exc}", level="error")
        try:
            if os.name == "nt":
                os.startfile(str(base))  # type: ignore[attr-defined]
            elif sys.platform.startswith("darwin"):
                subprocess.Popen(["open", str(base)])
            else:
                subprocess.Popen(["xdg-open", str(base)])
        except Exception as exc:
            return context._toast(f"폴더 열기 실패: {exc}", level="error")
        return context._toast("폴더를 탐색기에서 열었어요.", level="info")

    def rename(self, event: str, old: str, new: str) -> dict[str, Any]:
        context = self.context
        scene = read_scene(event, old, save_root=self._save_root())
        if scene is None:
            return context._toast(f"컷을 찾지 못했습니다: {old}", level="error")
        clean = sanitize_scene_name(new)
        if not clean:
            return context._toast("새 이름을 입력하세요", level="error")
        scene["name"] = clean
        if write_scene(event, scene, save_root=self._save_root()) is None:
            return context._toast("컷 이름을 바꾸지 못했습니다", level="error")
        # 새 이름으로 쓴 **뒤에** 지운다 - 순서를 뒤집으면 쓰기가 실패했을 때 원본이 없다.
        if sanitize_scene_name(old) != clean:
            delete_scene(event, old, save_root=self._save_root())
        return self.state(event)

    # 외부에서 씬 딕셔너리를 그대로 넣고 싶을 때(가져오기 등). 지금은 미사용.
    def import_scene(self, event: str, raw: Any) -> dict[str, Any] | None:
        scene = normalize_scene(raw)
        if not scene["name"]:
            return None
        write_scene(event, scene, save_root=self._save_root())
        return self.state(event)
