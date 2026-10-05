"""캐릭터 슬롯을 담고 통째로 갈아 끼우는 일 — V5 Scene 과 Snapshot 이 같이 쓴다.

프롬프트 꾸미기(PE 다시 입히기)와 씬의 배역 이월은 부르는 쪽의 일이다. 여기는 슬롯만 다룬다.
"""

from __future__ import annotations

import copy
from typing import Any

from core.character_settings import (
    _frame_uuid,
    _new_character_uuid,
    active_character_frames,
    clear_character_roll_snapshot,
    kept_by_user,
)


def capture_character_state(settings: dict[str, Any]) -> dict[str, Any]:
    """지금 **실제로 나가는** 슬롯을 담는다(끈 슬롯 · 비활성 · 히스토리는 담지 않는다).

    ⚠️ 캐릭터는 **원문**을 담는다(`character_frames` 의 prompt/uc 그대로). 전개된 결과를 담으면
       되돌렸을 때 와일드카드가 다시 굴려지지 않는다 - 한 장의 사진이 된다.
    ⚠️ Connect 는 uuid 를 **번호**로 바꿔 담는다 - 담긴 무리 안의 1-based 자리다(0 = 연결 없음).
       uuid 는 그 설치본 안에서만 뜻이 있어, 파일을 옮기거나 슬롯을 다시 만들면 가리킬 곳이 없다.
    """
    frames = active_character_frames(settings)
    order = {str(_frame_uuid(frame) or ""): index for index, frame in enumerate(frames)}
    characters = []
    for frame in frames:
        link_index = order.get(str(frame.get("connect_to") or ""))
        characters.append({
            "prompt": str(frame.get("prompt") or ""),
            "uc": str(frame.get("uc") or ""),
            "custom_name": str(frame.get("custom_name") or ""),
            "position": copy.deepcopy(frame.get("position")),
            # 저장은 1-based 번호. 못 찾으면 0(연결 없음).
            "connect_to": (link_index + 1) if link_index is not None else 0,
        })
    return {
        "is_active": bool(settings.get("is_active")),
        "position_mode": str(settings.get("position_mode") or "auto"),
        "frames": characters,
    }


def replace_character_state(
    context: Any, mode: str, characters: list[dict[str, Any]],
    position_mode: str, *, is_active: bool | None = None,
) -> None:
    """`mode` 의 활성 슬롯을 `characters` 로 **통째 교체**한다. 새 uuid 를 만들고 번호 링크를 그 uuid 로 되살린다.

    `is_active` 를 안 주면 넣은 슬롯이 있을 때 켠다(씬의 규약). 스냅샷은 담을 때의 값을 준다.

    ⚠️ **설정을 넘겨받지 않는다.** 스냅샷 불러오기는 작업 스레드에서 도는데(데이터셋을 옮긴다), 그동안 WS 명령은
       이벤트 루프에서 같은 설정을 고친다. 부르는 쪽이 미리 집어 든 설정으로 저장하면 그 사이에 보관한 것을 옛
       사본으로 덮는다(Codex 리뷰 2026-10-05). 읽기부터 저장까지 `set_param` 과 **같은 잠금** 안에서 하고,
       그 안에서 `mode` 의 지금 설정을 읽는다 - '지금 API 모드' 가 아니다(그 사이에 모드를 바꿀 수 있다).
    """
    service = context._character_service()
    with service._commit_lock:
        settings = copy.deepcopy(service.settings_for(mode))
        uuids = [_new_character_uuid() for _ in characters]
        fresh = []
        for index, item in enumerate(characters):
            link = item.get("connect_to") or 0
            fresh.append({
                "uuid": uuids[index],
                "prompt": item["prompt"],
                "uc": item["uc"],
                "custom_name": item["custom_name"],
                "position": item["position"],
                "connect_to": uuids[link - 1] if 1 <= link <= len(uuids) else "",
                "slot_state": "active", "is_enabled": True, "is_muted": False,
                # 이 칸은 씬 · 스냅샷이 만든 것이다 - **다음에 불러올 때 버릴 대상**이 된다.
                "from_scene": True,
            })
        kept = []
        for frame in settings.get("character_frames") or []:
            if not isinstance(frame, dict):
                continue
            # ⚠️ **버릴 것을 고른다**: 이전 씬 · 스냅샷이 남긴 칸 가운데 **사용자가 남기지 않은 것**만.
            #    예전엔 전부 비활성으로 남겼는데(아무것도 잃지 않으려고), 잇달아 부르면 비활성 무리에 찌꺼기가
            #    끝없이 쌓였다(사용자 제보). 손으로 만든 칸은 그대로 남기고 씬이 만든 것만 고른다 - 표식이
            #    없으면 어느 것이 사용자 작업인지 구분할 방법이 없다.
            # ⚠️ 즐겨찾기 · 그룹으로 보관한 칸은 씬이 만들었어도 **사용자의 것**이다. 이것을 안 보면 씬의
            #    캐릭터를 ★ 해 두어도 다음 불러오기에서 사라진다(2026-10-05 재현). 예전에는 Cold 로 보낸 칸만
            #    지켰는데 그 상태는 2026-09-02 에 폐기돼, 지키는 조건이 죽어 있었다.
            if frame.get("from_scene") and not kept_by_user(frame):
                continue
            if str(frame.get("slot_state") or "").strip().lower() != "active":
                kept.append(frame)          # 보관함은 손대지 않는다 - 씬이 내리는 것은 지금 슬롯뿐이다
                continue
            # 비활성으로 밀린 슬롯의 링크는 정리한다 - 그대로 두면 정규화가 "앞만 가리킨다" 규칙으로
            # 지우거나, 새 활성 슬롯을 엉뚱하게 가리킨다.
            frame.update(slot_state="inactive", is_enabled=False, connect_to="")
            kept.append(frame)
        settings["character_frames"] = fresh + kept
        settings["is_active"] = bool(fresh) if is_active is None else bool(is_active)
        settings["position_mode"] = position_mode
        service.save_settings(mode, settings)
    clear_character_roll_snapshot(context, mode)
