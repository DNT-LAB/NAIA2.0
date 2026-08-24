from __future__ import annotations

import json
import math
import os
import random
import re
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor, split_tags_smart


def _default_save_root() -> Path:
    user_data_dir = os.environ.get("NAIA_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir).expanduser().resolve() / "save"
    return Path("save")


def _coerce_save_root(save_root: Path | str | None = None) -> Path:
    return Path(save_root).expanduser().resolve() if save_root is not None else _default_save_root()


def _legacy_save_fallback_enabled() -> bool:
    if os.environ.get("NAIA_DISABLE_LEGACY_SAVE_FALLBACK") == "1":
        return False
    if os.environ.get("NAIA_ELECTRON") == "1":
        return False
    return True


def _existing_character_settings_path(mode: str = "NAI", *, save_root: Path | str | None = None) -> Path:
    primary = character_settings_path(mode, save_root=save_root)
    if primary.exists():
        return primary
    legacy = Path("save").resolve() / primary.name
    if _legacy_save_fallback_enabled() and legacy != primary.resolve() and legacy.exists():
        return legacy
    return primary


def _save_root_from_context(app_context: Any) -> Path | None:
    runtime_paths = getattr(app_context, "runtime_paths", None)
    save_dir = getattr(runtime_paths, "save_dir", None)
    return Path(save_dir) if save_dir is not None else None


def character_settings_path(mode: str = "NAI", *, save_root: Path | str | None = None) -> Path:
    return _coerce_save_root(save_root) / f"CharacterModule_{str(mode or 'NAI').upper()}.json"


def default_character_settings() -> dict:
    return {
        "is_active": False,
        "reroll_on_generate": False,
        "character_frames": [],
    }


def normalize_slot_state(value: Any, is_enabled: bool = False) -> str:
    state = str(value or "").strip().lower()
    if state in {"active", "inactive", "cold"}:
        return state
    return "active" if is_enabled else "inactive"


def _new_character_uuid() -> str:
    return uuid.uuid4().hex


def _frame_uuid(frame: dict[str, Any], *, create: bool = False) -> str:
    for key in ("uuid", "slot_uuid"):
        value = str(frame.get(key) or "").strip()
        if value:
            return value
    legacy = frame.get("id")
    if isinstance(legacy, str):
        value = legacy.strip()
        if value and not value.isdigit():
            return value
    return _new_character_uuid() if create else ""


def _prune_character_links(frames: list[dict]) -> list[dict]:
    """끊어진 Connect 링크를 지운다. **정렬 뒤에 부른다** — 유효성이 순서에 달렸다.

    지우는 경우 셋:
      · 자기 자신을 가리킴
      · 없는 uuid 를 가리킴 (슬롯이 지워졌다)
      · **자기보다 뒤에 있는 슬롯을 가리킴** (▲▼ 로 순서가 뒤집혔다)

    마지막 것이 이 기능의 안전장치다. 참조 대상이 항상 앞에 있어야 전개 루프
    (`_expanded_character_pairs`)가 한 번 훑는 동안 값이 확정돼 있고, 순환이
    원천적으로 생기지 않는다. 뒤를 가리키게 된 링크는 **조용히 무시하지 않고
    지운다** — 남겨 두면 화면에는 연결로 보이는데 생성물에는 안 실린다.
    """
    order = {}
    for index, frame in enumerate(frames):
        uuid = str(_frame_uuid(frame) or "")
        if uuid:
            order[uuid] = index
    for index, frame in enumerate(frames):
        link = str(frame.get("connect_to") or "")
        if not link:
            continue
        source_index = order.get(link)
        if source_index is None or source_index >= index:
            frame["connect_to"] = ""
    return frames


def _normalize_character_settings_with_migration(raw: dict | None) -> tuple[dict, bool]:
    data = raw if isinstance(raw, dict) else {}
    settings = default_character_settings()
    settings["is_active"] = bool(data.get("is_active", settings["is_active"]))
    settings["reroll_on_generate"] = bool(data.get("reroll_on_generate", settings["reroll_on_generate"]))
    frames = data.get("character_frames", [])
    normalized_frames = []
    migrated = False
    if isinstance(frames, list):
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            is_enabled = bool(frame.get("is_enabled", False))
            slot_state = normalize_slot_state(frame.get("slot_state"), is_enabled)
            # ⚠️ 슬롯은 **두 축**이다(NAI 공식 구현과 같다).
            #   · slot_state - 목록의 어느 무리에 있나 (▲/▼ · Cold)
            #   · is_muted   - 활성 무리 안에서 이번 생성에 나가나 (✔/✘)
            # 끈 슬롯은 **제자리에 남는다.** C3 을 꺼도 화면에서는 C3 이고 C4 는
            # C4 다 - 페이로드에서만 C4 가 2번지로 당겨진다.
            #
            # 예전에는 축이 하나뿐이라 "끄기" 가 곧 비활성 무리로 보내기였고
            # (`char_active_N`), 무리를 나누면서 그 조작이 사라져 제자리에서 끌
            # 방법이 없어졌다(사용자 제보).
            is_muted = bool(frame.get("is_muted", False))
            frame_uuid = _frame_uuid(frame, create=True)
            if frame.get("uuid") != frame_uuid:
                migrated = True
            normalized_frames.append({
                "uuid": frame_uuid,
                "prompt": str(frame.get("prompt") or ""),
                "uc": str(frame.get("uc") or ""),
                # `is_enabled` 는 **파생값**이다 - "이 슬롯이 실제로 나가는가".
                # 읽는 곳이 많은데(조건부·에셋·프리뷰·배지) 뜻이 그대로라서,
                # 새 축을 여기에 접어 넣으면 기존 독자가 자동으로 옳아진다.
                "is_enabled": slot_state == "active" and not is_muted,
                "is_muted": is_muted,
                "slot_state": slot_state,
                "return_slot_state": str(frame.get("return_slot_state") or ""),
                "custom_name": str(frame.get("custom_name") or frame.get("slot_name") or ""),
                "position": normalize_position(frame.get("position")),
                # Connect - 앞선 활성 슬롯의 **전개 결과**를 물려받는다. 값은 그 슬롯의
                # uuid 다(표시 번호가 아니다).
                #
                # ⚠️ 번호로 저장하면 안 된다. `sort_character_frames` 가 무리별로 다시
                #    묶고 ▲▼·비활성화가 번호를 밀기 때문에, C1 을 가리키던 링크가 어느
                #    날 조용히 다른 캐릭터를 가리킨다. "자기보다 낮은 번호만" 은 화면에서
                #    거는 제약이고, 저장은 안정 uuid 로 한다.
                "connect_to": str(frame.get("connect_to") or ""),
            })
    settings["character_frames"] = _prune_character_links(sort_character_frames(normalized_frames))
    # POS 는 세 상태다(사용자 지정 2026-08-23): AUTO -> CUSTOM -> RAND -> AUTO.
    #   · AUTO   - `auto_character_positions` 가 구운 고정 자리
    #   · CUSTOM - 슬롯이 기억하고 있는 사용자 좌표
    #   · RAND   - 생성 요청마다 새로 굽는 무작위 배치
    #
    # ⚠️ **AUTO/RAND 로 옮겨가도 슬롯의 position 은 지우지 않는다**(사용자 지정:
    #    "각 슬롯은 삭제되기 전까지 사용자가 설정한 POS 를 기억해야 한다").
    #    CUSTOM 으로 되돌아오면 그대로 살아난다.
    settings["position_mode"] = normalize_position_mode(
        data.get("position_mode"), data.get("use_custom_positions")
    )
    # ⚠️ Connect 가 하나라도 걸려 있으면 POS 는 **강제로 CUSTOM** 이다(사용자 지정).
    #    이 기능은 2koma 처럼 같은 캐릭터를 칸마다 손으로 앉히려고 쓰는 것이라,
    #    AUTO/RAND 가 자리를 대신 정해 버리면 쓰는 목적 자체가 사라진다.
    #    여기서 세우면 `save_settings` 의 `_seed_missing_positions` 도 따라 돌아
    #    좌표 없는 슬롯이 씨앗을 받는다(정규화 뒤에 도는 순서라 이 순서가 맞다).
    if any(str(frame.get("connect_to") or "") for frame in settings["character_frames"]):
        settings["position_mode"] = "custom"
    # 옛 불리언 키는 **파생값**으로만 남긴다 - 읽는 곳이 여럿이라 지우면 흩어져
    # 깨지고, 권위를 주면 새 값과 싸운다. 언제나 `position_mode` 가 이긴다.
    settings["use_custom_positions"] = settings["position_mode"] == "custom"
    return settings, migrated


def normalize_position(value: Any) -> dict[str, float] | None:
    """`{'x','y'}` 를 0.0~1.0 소수 3자리로. 좌표가 아니면 None.

    3자리는 NAI 웹이 보내는 형식이다(실측 2026-08-22). 좌상단이 원점이고
    x 는 왼->오, y 는 위->아래로 증가한다.
    """
    if not isinstance(value, dict):
        return None
    try:
        x = float(value.get("x"))
        y = float(value.get("y"))
    except (TypeError, ValueError):
        return None
    return {"x": round(min(1.0, max(0.0, x)), 3), "y": round(min(1.0, max(0.0, y)), 3)}


POSITION_MODES = ("auto", "custom", "random")


def normalize_position_mode(value: Any, legacy_flag: Any = None) -> str:
    """POS 모드 하나를 고른다. 모르는 값이면 AUTO.

    ⚠️ 옛 저장본에는 `position_mode` 가 없고 불리언 `use_custom_positions` 뿐이다.
    그때만 그 값을 본다 - `position_mode` 가 유효하면 **언제나 그쪽이 이긴다.**
    둘 다 권위를 가지면 한쪽만 담아 보내는 호출자가 상대를 조용히 되돌린다.
    """
    text = str(value or "").strip().lower()
    if text in POSITION_MODES:
        return text
    return "custom" if bool(legacy_flag) else "auto"


# POS: RAND 의 규약 (사용자 지정 2026-08-23).
#
#   0.1~0.9 안에서 뽑고, 이미 놓인 자리와 유클리드 거리 0.2 이상을 지킨다.
#   한 슬롯당 5회까지 다시 뽑고, 다 실패하면 **마지막에 뽑은 값을 그대로 쓴다.**
#
# ⚠️ 판정은 **반올림한 뒤** 한다. 보내는 값과 재는 값이 달라지면 "0.2 이상" 이
#    보장되지 않는다(소수 3자리로 나가므로 그 값으로 재야 한다).
_RAND_LO, _RAND_HI = 0.1, 0.9
_RAND_MIN_DIST = 0.2
_RAND_TRIES = 5


def random_character_positions(count: int, rng: Any = None) -> list[dict[str, float]]:
    """POS: RAND 의 자리. **생성 요청마다 새로 굽는다** - 저장하지 않는다.

    한 슬롯씩 물리는 방식이다(전체를 통째로 다시 뽑지 않는다). 통째로 뽑으면
    인원이 늘수록 다섯 번 안에 성공할 확률이 급격히 떨어져 "마지막 값" 폴백이
    사실상 기본값이 되고, 그 값은 겹침을 전혀 안 본 배치다.
    """
    if count <= 0:
        return []
    source = rng if rng is not None else random
    placed: list[dict[str, float]] = []
    for _ in range(count):
        spot = {"x": 0.5, "y": 0.5}
        for _attempt in range(_RAND_TRIES):
            spot = {
                "x": round(source.uniform(_RAND_LO, _RAND_HI), 3),
                "y": round(source.uniform(_RAND_LO, _RAND_HI), 3),
            }
            if all(math.hypot(spot["x"] - other["x"], spot["y"] - other["y"]) >= _RAND_MIN_DIST
                   for other in placed):
                break
        placed.append(spot)     # 5회 다 실패하면 마지막 값 그대로 (사용자 지정)
    return placed


# POS: AUTO 의 배치 순서 (사용자 지정 2026-08-23).
#
#   중앙 -> 왼쪽 -> 오른쪽 -> 위 -> 아래 -> 왼쪽위 -> 오른쪽위 -> 왼쪽아래 -> 오른쪽아래
#   -> (중앙을 빼고) 왼쪽 -> 오른쪽 -> 위 -> ... 되풀이
#
# ⚠️ **NAI 에 맡기지 않고 우리가 정한다**(사용자 지정). NAI 의 AI's Choice 는
#    좌표를 안 보내야 도는데, 그러면 화면의 원과 실제 배치가 갈리고 1인일 때는
#    좌표가 조용히 무시되기까지 한다. AUTO 도 좌표를 보내되 값을 여기서 굽는다.
#
# 벌림폭 0.2 는 사용자 실측 페이로드에서 온다 - 3인 AI's Choice 가
# (0.5,0.5) (0.3,0.5) (0.7,0.5) 였다. 좌상단 원점이라 "위"는 y 가 작은 쪽이다.
_AUTO_C, _AUTO_LO, _AUTO_HI = 0.5, 0.3, 0.7
_AUTO_RING = (
    {"x": _AUTO_C, "y": _AUTO_C},      # 중앙
    {"x": _AUTO_LO, "y": _AUTO_C},     # 왼쪽
    {"x": _AUTO_HI, "y": _AUTO_C},     # 오른쪽
    {"x": _AUTO_C, "y": _AUTO_LO},     # 위
    {"x": _AUTO_C, "y": _AUTO_HI},     # 아래
    {"x": _AUTO_LO, "y": _AUTO_LO},    # 왼쪽위
    {"x": _AUTO_HI, "y": _AUTO_LO},    # 오른쪽위
    {"x": _AUTO_LO, "y": _AUTO_HI},    # 왼쪽아래
    {"x": _AUTO_HI, "y": _AUTO_HI},    # 오른쪽아래
)


def fill_missing_positions(positions: list[dict | None]) -> list[dict[str, float]]:
    """빈 자리에 **아직 아무도 안 선** AUTO 자리를 채운다. 순서는 그대로.

    ⚠️ 순번대로 주면 자리가 겹친다(Codex 지적, 실측): 중앙/왼쪽/오른쪽에 셋을 놓고
    가운데를 지운 뒤 하나 더하면 새 슬롯이 index 2 라서 오른쪽을 받아, 이미 오른쪽에
    선 슬롯과 같은 점에 놓였다. 그래서 **비어 있는 자리부터** 준다.

    사용자가 링 위가 아닌 곳에 놓은 좌표는 링 자리를 소모하지 않는다 - 그 좌표는
    그대로 두고, 빈 슬롯은 링의 아홉 자리 중 아무도 안 쓰는 곳을 받는다.
    아홉이 다 차면 겹침을 피할 수 없으므로 그때만 순번으로 돌아간다.
    """
    taken = {(p["x"], p["y"]) for p in positions if p is not None}
    free = [spot for spot in auto_character_positions(len(_AUTO_RING))
            if (spot["x"], spot["y"]) not in taken]
    ordinal = auto_character_positions(len(positions))
    filled: list[dict[str, float]] = []
    for index, position in enumerate(positions):
        if position is not None:
            filled.append(dict(position))
        elif free:
            filled.append(free.pop(0))
        else:
            filled.append(dict(ordinal[index]))
    return filled


def auto_character_positions(count: int) -> list[dict[str, float]]:
    """AUTO 의 자리. 순서는 `_AUTO_RING`, 아홉을 넘으면 중앙만 빼고 되풀이한다.

    두 곳에서 같은 값을 쓴다 - 그래야 화면의 원과 실제로 나가는 좌표가 같다:
      · 생성 요청 단계(`character_positions_for_mode`)
      · CUSTOM 을 처음 켤 때 원의 출발 자리(빈 좌표 씨앗)

    ⚠️ 아홉을 넘으면 **자리가 겹친다.** 사용자 지정이다 - NAI 도 A1~E5 안에서만
    놓으므로 인원이 늘면 어차피 붙는다.
    """
    if count <= 0:
        return []
    out: list[dict[str, float]] = []
    for i in range(count):
        # 되풀이 구간은 중앙(0번)을 건너뛴다: 왼쪽 -> 오른쪽 -> 위 -> ...
        slot = i if i < len(_AUTO_RING) else 1 + (i - len(_AUTO_RING)) % (len(_AUTO_RING) - 1)
        out.append(dict(_AUTO_RING[slot]))
    return out


def character_positions_for_mode(app_context, mode: str = "NAI",
                                 count: int | None = None,
                                 *, use_conditional_mask: bool = True) -> list[dict[str, float]]:
    """이 모드의 활성 캐릭터 좌표. 페이로드 빌드가 부르는 입구다.

    좌표는 **굴림의 일부가 아니다**(와일드카드로 변하지 않는다) - 그래서 캐릭터
    스냅샷을 거치지 않고 설정에서 곧장 읽는다. 스냅샷에 얹으면 굴림마다 좌표가
    따라다녀야 하고, 재굴림 시 좌표가 옛 값에 묶인다.

    `count` 는 **실제로 나갈 캐릭터 수**다(조건부 규칙이 더하거나 뺀 뒤의 수).

    ⚠️ `use_conditional_mask` 는 **캐릭터를 조건부와 같은 눈으로 고른 호출자만**
    켜야 한다. 마스크는 "조건부가 본 슬롯 중 무엇이 나가나" 인데, 캐릭터 목록을
    다른 출처에서 확정한 경로(이벤트 스트림 freeze 는 얼린 리터럴을 쓴다)에
    그대로 씌우면 **남의 슬롯 좌표가 붙는다.** 개수가 같으면 아무도 못 알아챈다
    (Codex 지적, 실측: 얼린 C1,C2,C3 에 마스크가 고른 C1,C3,C4 의 좌표가 붙었다).
    """
    try:
        settings = load_character_settings(mode, save_root=_save_root_from_context(app_context))
        mask = _conditional_slot_mask(app_context) if use_conditional_mask else None
        return resolved_character_positions(settings, count=count, slot_mask=mask)
    except Exception:
        return []


def _conditional_slot_mask(app_context) -> list[bool] | None:
    """조건부가 이번 런에 끈 슬롯까지 반영한 마스크. 없으면 None.

    ⚠️ 이것이 좌표 문제의 열쇠다. 조건부 `char_set(N, disabled)` 은 캐릭터 목록을
    **짧게** 만들어서, 개수만 보면 어느 좌표가 누구 것인지 알 수 없었다 - 그래서
    사용자가 찍은 자리를 통째로 버리고 AUTO 로 떨어뜨렸다(실측: 3인 중 2번을 끄면
    1·3번이 자기 자리 대신 중앙·왼쪽으로 갔다).

    런타임이 남기는 `_conditional_character_slots` 는 **프레임과 위치가 1:1** 이고
    `active` 를 담는다(`conditional_prompt_runtime._character_slots`). 그러니
    버릴 필요가 없다 - 살아남은 슬롯이 자기 좌표를 그대로 들고 가면 된다.
    """
    context = getattr(app_context, "current_prompt_context", None)
    metadata = getattr(context, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    slots = metadata.get("_conditional_character_slots")
    if not isinstance(slots, list) or not slots:
        return None
    # `_store_character_overrides` 와 **같은 필터**여야 한다 - 그쪽은 active 이고
    # 프롬프트가 빈칸이 아닌 슬롯만 내보낸다. 어긋나면 좌표가 한 칸씩 밀린다.
    return [
        bool(slot.get("active")) and bool(str(slot.get("prompt") or "").strip())
        for slot in slots
        if isinstance(slot, dict)
    ]


def resolved_character_positions(settings: dict | None,
                                 count: int | None = None,
                                 slot_mask: list[bool] | None = None) -> list[dict[str, float]]:
    """생성 요청이 실제로 보낼 좌표. **어느 모드든 좌표는 나간다.**

      · CUSTOM - 슬롯이 기억하고 있는 사용자 좌표
      · AUTO   - 여기서 구운 `auto_character_positions` (사용자 지정)
      · RAND   - 부를 때마다 다시 굽는 `random_character_positions`

    ⚠️ RAND 는 **이 함수를 부를 때마다 값이 달라진다.** 그래서 화면 표시처럼
    여러 번 부르는 자리에서 쓰면 원이 흔들린다 - 이 함수는 생성 요청 빌드
    (`character_positions_for_mode`) 한 곳에서만 부른다.

    ⚠️ 빈 좌표가 섞여 있으면 **버리지 않고 채운다**(`fill_missing_positions`).
    예전에는 통째로 AUTO 로 떨어뜨렸는데, 그러면 **저장 파일이 이미 반쪽인 채로
    올라온 사용자가 자기 좌표를 영영 못 쓴다**(Codex 지적: 옛 빌드가 남긴 반쪽
    파일은 쓰기가 한 번 더 일어나기 전까지 안 고쳐진다). 채워 보내면 사용자가 정한
    자리는 지켜지고, 빈 슬롯만 자동 자리를 받는다.

    `slot_mask` 는 **전체 프레임과 위치가 1:1** 인 불리언 목록이다(조건부가 이번
    런에 끈 슬롯까지 반영). 주면 그것으로 나갈 슬롯을 고르므로, 살아남은 슬롯이
    **자기 좌표를 그대로** 들고 간다 - C3 을 끄면 C1·C4 는 원래 찍어 둔 자리를
    지키고 C4 만 페이로드 2번지로 당겨진다(NAI 공식 구현과 같다).

    ⚠️ 마스크가 없고 `count` 도 슬롯 수와 어긋나면 그때만 AUTO 배치로 떨어진다 -
    어느 좌표가 누구 것인지 알 길이 없는 경우다. 순서로 짐작해 어긋난 좌표를
    보내느니 개수가 맞는 자동 배치가 낫다.
    """
    normalized = normalize_character_settings(settings)
    all_frames = normalized.get("character_frames", []) or []
    if slot_mask is not None and len(slot_mask) == len(all_frames):
        # 마스크가 프레임과 자릿수까지 맞을 때만 믿는다. 어긋난 마스크를 쓰면
        # 좌표가 한 칸씩 밀려 **틀린 자리**로 나간다 - 차라리 옛 길로 간다.
        frames = [frame for frame, keep in zip(all_frames, slot_mask) if keep]
    else:
        frames = active_character_frames(normalized)
    total = len(frames) if count is None else max(0, int(count))
    if not total:
        return []
    # RAND 는 개수만 알면 된다 - 슬롯과 좌표를 짝지을 일이 없어 조건부로
    # 인원이 달라져도 그대로 굽는다(CUSTOM 과 달리 어긋날 좌표가 없다).
    if normalized.get("position_mode") == "random":
        return random_character_positions(total)
    if normalized.get("use_custom_positions") and total == len(frames):
        return fill_missing_positions(
            [normalize_position(frame.get("position")) for frame in frames]
        )
    return auto_character_positions(total)


def custom_character_positions(settings: dict | None) -> list[dict[str, float]]:
    """CUSTOM 일 때 슬롯이 기억하고 있는 좌표만. AUTO 이거나 하나라도 비면 빈 목록.

    "사용자가 정한 좌표가 온전한가" 를 묻는 자리다 - 생성이 실제로 보낼 좌표는
    `resolved_character_positions` 다(AUTO 배치까지 포함한다).
    """
    normalized = normalize_character_settings(settings)
    if not normalized.get("use_custom_positions"):
        return []
    frames = active_character_frames(normalized)
    positions = [normalize_position(frame.get("position")) for frame in frames]
    if not positions or any(position is None for position in positions):
        return []
    return [dict(position) for position in positions]


# 슬롯 정렬 불변식: [active...] [inactive...] [cold...]
#
# 화면이 활성/비활성 두 무리로 나뉘고 활성 무리 안에서 C1,C2.. 번호를 매기므로
# 배열 순서가 곧 화면 순서다. ⚠️ 프런트는 슬롯을 **인덱스로 주소 지정**한다
# (`remove_character_3` 등) - 저장 순서와 표시 순서가 어긋나면 명령이 엉뚱한
# 슬롯에 꽂힌다. 그래서 읽기·쓰기가 함께 지나는 이 정규화 지점 한 곳에서만 세운다.
#
# Cold 는 저장소로 격리한다(사용자 결정) - 맨 뒤로 몰아두고 Cold 패널만 본다.
_SLOT_ORDER = {"active": 0, "inactive": 1, "cold": 2}


def sort_character_frames(frames: list[dict]) -> list[dict]:
    """무리별로만 모은다. **무리 안의 상대 순서는 보존**한다(안정 정렬).

    사용자가 ▲/▼ 로 정한 순서가 다음 정규화에서 흐트러지면 안 된다.
    """
    return sorted(
        frames,
        key=lambda frame: _SLOT_ORDER.get(
            str(frame.get("slot_state") or "inactive").strip().lower(), 1
        ),
    )


def normalize_character_settings(raw: dict | None) -> dict:
    settings, _migrated = _normalize_character_settings_with_migration(raw)
    return settings


def _save_migrated_character_settings(path: Path, mode_key: str, settings: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({mode_key: settings}, ensure_ascii=False, indent=4), encoding="utf-8")
    except Exception as exc:
        print(f"[WARN] Character settings migration save failed: {exc}")


def _checked(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.isChecked())
    except Exception:
        return False


def loaded_character_module_has_widget_state(module: Any) -> bool:
    return getattr(module, "activate_checkbox", None) is not None


def loaded_character_module_is_active(module: Any) -> bool:
    return _checked(getattr(module, "activate_checkbox", None))


def loaded_character_module_reroll_on_generate(module: Any) -> bool:
    return (
        loaded_character_module_is_active(module)
        and _checked(getattr(module, "reroll_on_generate_checkbox", None))
    )


def load_character_settings(
    mode: str = "NAI",
    path: Path | str | None = None,
    *,
    save_root: Path | str | None = None,
) -> dict:
    mode_key = str(mode or "NAI").upper()
    target = Path(path) if path is not None else _existing_character_settings_path(mode_key, save_root=save_root)
    try:
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
            raw_settings = data.get(mode_key) if isinstance(data, dict) and isinstance(data.get(mode_key), dict) else data
            normalized, migrated = _normalize_character_settings_with_migration(raw_settings)
            if migrated:
                _save_migrated_character_settings(target, mode_key, normalized)
            return normalized
    except Exception as exc:
        print(f"[ERROR] Character settings load failed: {exc}")
    return default_character_settings()


def active_character_frames(settings: dict | None) -> list[dict]:
    normalized = normalize_character_settings(settings)
    if not normalized.get("is_active"):
        return []
    # ⚠️ 끈 슬롯(`is_muted`)은 활성 무리에 **남아 있지만 나가지 않는다.**
    #    `is_enabled` 가 그 둘을 이미 접어 둔 파생값이라 그것만 보면 된다.
    #
    # ⚠️ 빈 프롬프트는 원래 여기서 탈락한다. 그런데 Connect 를 쓰면 프롬프트 칸이
    #    "추가할" 칸이 되어 **비워 두는 것이 정상**이다(앞 슬롯을 그대로 물려받는
    #    경우). 링크가 있으면 통과시키지 않으면 그 슬롯은 화면에는 있는데 생성물에는
    #    없다. 링크 유효성은 `_prune_character_links` 가 이미 정리해 두었다.
    return [
        frame
        for frame in normalized.get("character_frames", [])
        if frame.get("is_enabled")
        and (str(frame.get("prompt") or "").strip() or str(frame.get("connect_to") or "").strip())
    ]


def _get_prompt_context(app_context, *, reuse_current_context: bool = True) -> PromptContext:
    existing = getattr(app_context, "current_prompt_context", None)
    if reuse_current_context and existing is not None:
        return existing
    source_row = getattr(app_context, "current_source_row", None)
    if source_row is None:
        source_row = pd.Series({}, name="character_headless")
    return PromptContext(source_row=source_row, settings={})


def _conditional_character_override(app_context, *, reuse_current_context: bool) -> dict | None:
    if not reuse_current_context:
        return None
    context = getattr(app_context, "current_prompt_context", None)
    metadata = getattr(context, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    override = metadata.get("conditional_character_overrides")
    if not isinstance(override, dict):
        return None
    if "characters" not in override:
        return None
    characters = [str(value) for value in override.get("characters") or [] if str(value).strip()]
    if not characters:
        return {"characters": None}
    raw_ucs = [str(value) for value in override.get("uc") or []]
    ucs = [raw_ucs[index] if index < len(raw_ucs) else "" for index in range(len(characters))]
    return {
        "characters": characters,
        "uc": ucs,
    }


def conditional_character_override_active(app_context) -> bool:
    """True if an active per-run conditional character override is present on the
    current prompt context (e.g. produced by `char:1+=__wc__` at after_wildcard).
    Such an override outranks the SSOT snapshot for the actual payload."""
    return _conditional_character_override(app_context, reuse_current_context=True) is not None


CHARACTER_FREEZE_STORE_ATTR = "_character_freeze_store"


def _character_freeze_store(app_context, *, create: bool = False) -> dict[str, dict[str, str]] | None:
    if app_context is None:
        return None
    store = getattr(app_context, CHARACTER_FREEZE_STORE_ATTR, None)
    if isinstance(store, dict):
        return store
    if not create:
        return None
    store = {}
    setattr(app_context, CHARACTER_FREEZE_STORE_ATTR, store)
    return store


def read_frozen_character_slots(app_context) -> dict[str, dict[str, str]]:
    store = _character_freeze_store(app_context)
    if not isinstance(store, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for slot, payload in store.items():
        if not isinstance(payload, dict):
            continue
        prompt = str(payload.get("prompt") or "")
        if not prompt.strip():
            continue
        out[str(slot)] = {"prompt": prompt, "uc": str(payload.get("uc") or "")}
    return out


def frozen_character_slots_payload(app_context) -> list[dict[str, Any]]:
    store = _character_freeze_store(app_context)
    if not isinstance(store, dict):
        return []
    out: list[dict[str, Any]] = []
    for slot, payload in sorted(store.items()):
        if not isinstance(payload, dict):
            continue
        prompt = str(payload.get("prompt") or "")
        if not prompt.strip():
            continue
        entry: dict[str, Any] = {"slot": str(slot), "prompt": prompt, "uc": str(payload.get("uc") or "")}
        # slot_label = the 1-based character number, so the bar can tell multiple
        # frozen characters apart ("캐릭터 1" vs "캐릭터 2") instead of a bare "캐릭터".
        if payload.get("slot_label") is not None:
            entry["slot_label"] = payload.get("slot_label")
        # Per-wildcard components let the front-end bar reroll one wildcard inside a
        # frozen character (e.g. just __의상__) — only surfaced when the character
        # actually decomposed into wildcards.
        components = payload.get("components")
        if isinstance(components, list) and components:
            comp = [
                {"name": str(c.get("name") or ""), "value": str(c.get("value") or "")}
                for c in components
                if isinstance(c, dict) and str(c.get("name") or "")
            ]
            if comp:
                entry["components"] = comp
        out.append(entry)
    return out


# ── Per-wildcard character freeze (slot-scoped overrides) ────────────────────
# A frozen character stays generation-side a single expanded blob (the snapshot
# overlay path is unchanged), but we ALSO capture its per-wildcard rolls so the
# bar can reroll one wildcard at a time. The captured rolls live slot-scoped in
# app_context.wildcard_override_character[slot] = {resolved_key: value}; on a
# per-component reroll we drop the target key, re-expand the frame (the others
# pinned via _consume_override, the target re-rolling fresh), and rewrite the blob.
CHARACTER_WC_OVERRIDE_ATTR = "wildcard_override_character"


def _character_wc_override_store(app_context, *, create: bool = False) -> dict[str, dict[str, str]] | None:
    if app_context is None:
        return None
    store = getattr(app_context, CHARACTER_WC_OVERRIDE_ATTR, None)
    if isinstance(store, dict):
        return store
    if not create:
        return None
    store = {}
    setattr(app_context, CHARACTER_WC_OVERRIDE_ATTR, store)
    return store


def _character_rolls_map(context, slot_key: str) -> dict[str, str]:
    """Newest-wins {resolved_key: value} of the character-block wildcard rolls the
    context recorded for this slot. Skips the synthetic '(frozen)' marker roll."""
    rolls = getattr(context, "wildcard_rolls", None)
    out: dict[str, str] = {}
    if not isinstance(rolls, list):
        return out
    for roll in rolls:
        if not isinstance(roll, dict):
            continue
        if str(roll.get("location") or "") != "character":
            continue
        if str(roll.get("slot") or "") != slot_key:
            continue
        key = str(roll.get("key") or "")
        if not key or key == "(frozen)":
            continue
        out[key] = str(roll.get("value") or "")
    return out


def _character_slot_label(context, slot_key: str) -> Any:
    """The 1-based character number recorded on this slot's rolls (all rolls for a
    slot share it), for a human-readable multi-character label. None if unknown."""
    rolls = getattr(context, "wildcard_rolls", None)
    if not isinstance(rolls, list):
        return None
    for roll in rolls:
        if not isinstance(roll, dict):
            continue
        if str(roll.get("location") or "") != "character":
            continue
        if str(roll.get("slot") or "") != slot_key:
            continue
        if roll.get("slot_label") is not None:
            return roll.get("slot_label")
    return None


def _write_character_freeze(
    app_context,
    slot_key: str,
    prompt: str,
    uc: str,
    components_map: dict[str, str],
    slot_label: Any = None,
) -> bool:
    store = _character_freeze_store(app_context, create=True)
    if store is None:
        return False
    payload: dict[str, Any] = {"prompt": prompt, "uc": str(uc or "")}
    if slot_label is not None:
        payload["slot_label"] = slot_label
    if components_map:
        payload["components"] = [{"name": k, "value": v} for k, v in components_map.items()]
    store[slot_key] = payload
    override_store = _character_wc_override_store(app_context, create=True)
    if override_store is not None:
        if components_map:
            override_store[slot_key] = dict(components_map)
        else:
            override_store.pop(slot_key, None)
    return True


def _explicit_character_components(components: Any) -> dict[str, str]:
    if isinstance(components, dict):
        return {
            str(name): str(value or "")
            for name, value in components.items()
            if str(name or "").strip() and str(name) != "(frozen)"
        }
    if not isinstance(components, list):
        return {}
    out: dict[str, str] = {}
    for item in components:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("key") or "").strip()
        if not name or name == "(frozen)":
            continue
        out[name] = str(item.get("value") or "")
    return out


def set_frozen_character_slot(
    app_context,
    slot: Any,
    prompt: Any,
    uc: Any = "",
    components: Any = None,
    slot_label: Any = None,
) -> bool:
    slot_key = str(slot or "").strip()
    prompt_text = str(prompt or "").strip()
    if not slot_key or not prompt_text:
        return False
    if components is not None:
        # Result-history callers provide the selected image's exact provenance.
        # An explicit empty list is meaningful: do not leak components from the
        # latest generation's current_prompt_context into an older image.
        components_map = _explicit_character_components(components)
        resolved_slot_label = slot_label
    else:
        # Backward-compatible live freeze: capture the current generation's
        # per-wildcard breakdown and display label.
        context = getattr(app_context, "current_prompt_context", None)
        components_map = _character_rolls_map(context, slot_key)
        resolved_slot_label = _character_slot_label(context, slot_key)
    return _write_character_freeze(
        app_context,
        slot_key,
        prompt_text,
        str(uc or ""),
        components_map,
        resolved_slot_label,
    )


def clear_frozen_character_slot(app_context, slot: Any | None = None) -> bool:
    store = _character_freeze_store(app_context)
    override_store = _character_wc_override_store(app_context)
    if slot is None:
        changed = bool(store) if isinstance(store, dict) else False
        if isinstance(store, dict):
            store.clear()
        if isinstance(override_store, dict):
            override_store.clear()
        return changed
    slot_key = str(slot or "").strip()
    if isinstance(override_store, dict):
        override_store.pop(slot_key, None)
    if not isinstance(store, dict):
        return False
    return store.pop(slot_key, None) is not None


def _find_character_frame(app_context, slot_key: str, mode: str, save_root) -> dict | None:
    # Character frames are a NAI concept; try the live mode first, then fall back
    # to NAI so a lingering freeze still resolves after a mode switch.
    for candidate_mode in _dedupe_modes(mode):
        normalized = load_character_settings(candidate_mode, save_root=save_root)
        frames = normalized.get("character_frames") if isinstance(normalized, dict) else []
        for candidate in frames or []:
            if isinstance(candidate, dict) and str(_frame_uuid(candidate)) == slot_key:
                return candidate
    return None


def reroll_frozen_character_slot(
    app_context,
    slot: Any,
    mode: str = "NAI",
    *,
    component_key: Any | None = None,
    save_root: Path | str | None = None,
) -> bool:
    """Re-roll a *frozen* character slot — whole, or one wildcard component.

    The source template (with wildcard tokens) still lives on the character frame,
    keyed by the same uuid we froze under. We re-expand it in a throwaway context
    (so live generation state is untouched). For a per-component reroll, the OTHER
    components are pinned via ``wildcard_override_character`` (consumed by
    ``_consume_override``) while the target key is dropped so it alone re-rolls;
    for a whole reroll everything re-rolls. The reassembled prompt becomes the new
    frozen blob (the generation path stays blob-based), and the fresh per-wildcard
    rolls become the new components.

    Returns False when the slot isn't frozen, its frame is gone, or the expansion
    is empty — the caller keeps the existing freeze and toasts.
    """
    slot_key = str(slot or "").strip()
    if not slot_key:
        return False
    store = _character_freeze_store(app_context)
    if not isinstance(store, dict) or slot_key not in store:
        return False
    if save_root is None:
        save_root = _save_root_from_context(app_context)
    frame = _find_character_frame(app_context, slot_key, mode, save_root)
    if frame is None:
        return False

    override_store = _character_wc_override_store(app_context, create=True)
    working = dict((override_store or {}).get(slot_key) or {})
    comp_key = str(component_key or "").strip()
    if comp_key:
        # Single component: drop just this pin so ONLY it re-rolls; keep the rest.
        # Tolerate a short token vs. the resolved (subfolder) key on either side.
        for existing in list(working.keys()):
            if existing == comp_key or existing.endswith("/" + comp_key) or existing.endswith("\\" + comp_key) \
                    or comp_key.endswith("/" + existing) or comp_key.endswith("\\" + existing):
                working.pop(existing, None)
    else:
        working = {}  # whole character: everything re-rolls
    if override_store is not None:
        override_store[slot_key] = working  # pin the fixed set for this re-expansion

    processor = None
    wildcard_manager = getattr(app_context, "wildcard_manager", None)
    if wildcard_manager is not None:
        processor = WildcardProcessor(wildcard_manager)
    context = _get_prompt_context(app_context, reuse_current_context=False)
    prompt = _expand_character_text(frame.get("prompt", ""), processor, context, slot=slot_key)
    if not str(prompt).strip():
        # restore the prior override map so a failed reroll doesn't strip the pin
        if override_store is not None and isinstance(store.get(slot_key), dict):
            prior = {c.get("name"): c.get("value") for c in store[slot_key].get("components") or [] if isinstance(c, dict)}
            override_store[slot_key] = {k: v for k, v in prior.items() if k}
        return False
    uc = _expand_character_text(frame.get("uc", ""), processor, context, slot=slot_key)
    # New components = fixed (pinned) + freshly re-rolled, straight from the rolls.
    new_map = _character_rolls_map(context, slot_key)
    prior_label = store[slot_key].get("slot_label") if isinstance(store.get(slot_key), dict) else None
    return _write_character_freeze(app_context, slot_key, prompt, uc, new_map, prior_label)


def _dedupe_modes(mode: Any) -> list[str]:
    ordered = [str(mode or "NAI").upper(), "NAI"]
    seen: list[str] = []
    for item in ordered:
        if item and item not in seen:
            seen.append(item)
    return seen


def _all_frame_slot_ids(settings: dict | None) -> list[str]:
    frames = settings.get("character_frames") if isinstance(settings, dict) else []
    if not isinstance(frames, list):
        return []
    return [str(_frame_uuid(frame) or index) for index, frame in enumerate(frames, 1) if isinstance(frame, dict)]


def _prune_frozen_character_slots(app_context, settings: dict | None) -> bool:
    store = _character_freeze_store(app_context)
    override_store = _character_wc_override_store(app_context)
    valid_slots = set(_all_frame_slot_ids(settings))
    # keep the per-wildcard override map in lockstep with the freeze store
    if isinstance(override_store, dict):
        for slot in list(override_store.keys()):
            if str(slot) not in valid_slots:
                override_store.pop(slot, None)
    if not isinstance(store, dict) or not store:
        return False
    removed = False
    for slot in list(store.keys()):
        if str(slot) not in valid_slots:
            store.pop(slot, None)
            removed = True
    return removed


def _active_frame_slot_ids(frames: list[dict]) -> list[str]:
    return [str(_frame_uuid(frame) or index) for index, frame in enumerate(frames, 1)]


def _frozen_character_roll(slot: Any, prompt: Any, slot_label: Any = None) -> dict[str, Any]:
    roll: dict[str, Any] = {
        "key": "(frozen)",
        "value": str(prompt or ""),
        "location": "character",
        "slot": str(slot or ""),
    }
    if slot_label is not None:
        roll["slot_label"] = slot_label
    return roll


def _append_frozen_character_roll(rolls: list, slot: Any, prompt: Any, slot_label: Any = None) -> None:
    rolls.append(_frozen_character_roll(slot, prompt, slot_label))


def _replace_frozen_character_roll(rolls: list[dict[str, Any]], slot: Any, prompt: Any, slot_label: Any = None) -> list[dict[str, Any]]:
    slot_key = str(slot or "")
    kept = [
        dict(roll)
        for roll in rolls
        if not (
            isinstance(roll, dict)
            and roll.get("location") == "character"
            and str(roll.get("slot") or "") == slot_key
        )
    ]
    kept.append(_frozen_character_roll(slot_key, prompt, slot_label))
    return kept


def _snapshot_result(snapshot: dict, frame_slot_ids: list[str]) -> dict:
    characters = [str(value) for value in snapshot.get("characters") or []]
    ucs = [str(value) for value in snapshot.get("uc") or []]
    ids = [str(value) for value in snapshot.get("character_ids") or [] if str(value).strip()]
    if not ids:
        ids = frame_slot_ids[:len(characters)]
    while len(ucs) < len(characters):
        ucs.append("")
    result = {"characters": characters, "uc": ucs, "character_ids": ids}
    rolls = snapshot.get("wildcard_rolls")
    if isinstance(rolls, list) and rolls:
        result["wildcard_rolls"] = [dict(roll) for roll in rolls if isinstance(roll, dict)]
    return result


def _overlay_frozen_character_slots(app_context, result: dict, frame_slot_ids: list[str]) -> dict:
    frozen = read_frozen_character_slots(app_context)
    if not frozen:
        return result
    characters = list(result.get("characters") or [])
    ucs = list(result.get("uc") or [])
    ids = [str(value) for value in result.get("character_ids") or []]
    if not ids:
        ids = frame_slot_ids[:len(characters)]
    id_to_index = {slot_id: index for index, slot_id in enumerate(ids) if slot_id}
    rolls = [dict(roll) for roll in result.get("wildcard_rolls") or [] if isinstance(roll, dict)]
    for frame_index, slot_id in enumerate(frame_slot_ids):
        payload = frozen.get(slot_id)
        if not payload:
            continue
        index = id_to_index.get(slot_id, frame_index if frame_index < len(characters) else None)
        if index is None:
            continue
        while len(characters) <= index:
            characters.append("")
        while len(ucs) <= index:
            ucs.append("")
        while len(ids) <= index:
            ids.append(frame_slot_ids[len(ids)] if len(ids) < len(frame_slot_ids) else slot_id)
        characters[index] = payload["prompt"]
        ucs[index] = payload.get("uc", "")
        ids[index] = slot_id
        rolls = _replace_frozen_character_roll(rolls, slot_id, payload["prompt"], frame_index + 1)
    merged = {"characters": characters, "uc": ucs, "character_ids": ids}
    if rolls:
        merged["wildcard_rolls"] = rolls
    return merged


def _character_rolls_from_context(context: PromptContext, start_index: int) -> list[dict[str, Any]]:
    rolls = getattr(context, "wildcard_rolls", None)
    if not isinstance(rolls, list) or len(rolls) <= start_index:
        return []
    return [
        dict(roll)
        for roll in rolls[start_index:]
        if isinstance(roll, dict) and roll.get("location") == "character"
    ]


def _replay_character_snapshot_rolls(app_context, snapshot: dict, *, reuse_current_context: bool) -> None:
    if not reuse_current_context:
        return
    rolls = snapshot.get("wildcard_rolls")
    if not isinstance(rolls, list) or not rolls:
        return
    context = getattr(app_context, "current_prompt_context", None)
    if context is None:
        return
    target_rolls = getattr(context, "wildcard_rolls", None)
    if isinstance(target_rolls, list):
        target_rolls.extend(dict(roll) for roll in rolls if isinstance(roll, dict))
    history = getattr(context, "wildcard_history", None)
    if isinstance(history, dict):
        for roll in rolls:
            if not isinstance(roll, dict):
                continue
            key = str(roll.get("key") or "")
            if key:
                history.setdefault(key, []).append(str(roll.get("value") or ""))


# Connect 공유 구간 마커. NAI 체계가 바뀌며 캐릭터 슬롯이 메인 프롬프트 역할까지
# 겸하게 되어, 슬롯 전체가 아니라 **일부만** 물려주고 싶은 경우가 생겼다(사용자 지정).
#
#   &connect: girl, original, black hair &end, extra prompts: 123, 456
#   └──────────── 물려주는 구간 ────────────┘  └─── 이 슬롯에만 남는다 ───┘
#
# 마커가 없으면 예전처럼 전체를 물려준다(하위 호환).
#
# ⚠️ 닫는 기호가 맨 `&` 가 아니라 `&end` 인 이유: `&` 하나로 닫으면 태그 안쪽의 `&`
#    (예: `preset:clothes/a&b&`)와 구분하려고 "태그를 끝내는 & 만 인정" 같은 추론을
#    해야 하고, 그 추론은 앞으로 들어올 문법마다 다시 틀린다. 낱말로 닫으면 그 문제가
#    통째로 사라진다(사용자 지정).
_CONNECT_OPEN_RE = re.compile(r"&connect\s*:?", re.IGNORECASE)
_CONNECT_CLOSE_RE = re.compile(r"&end", re.IGNORECASE)


def _split_connect_region(text: str) -> tuple[str, str, str]:
    """`(앞, 공유구간, 뒤)`. 마커가 없으면 `("", 전체, "")` — 전체가 공유다.

    `&end` 가 없으면 `&connect` 부터 끝까지가 공유 구간이다(뒤를 안 쓴 경우).
    """
    source = str(text or "")
    opened = _CONNECT_OPEN_RE.search(source)
    if not opened:
        return "", source, ""
    head = source[:opened.start()]
    rest = source[opened.end():]
    closed = _CONNECT_CLOSE_RE.search(rest)
    if not closed:
        return head, rest, ""
    return head, rest[:closed.start()], rest[closed.end():]


def has_connect_region(text: str) -> bool:
    return bool(_CONNECT_OPEN_RE.search(str(text or "")))


def wrap_connect_region(text: str) -> str:
    """전체를 `&connect: … &end` 로 감싼다. 이미 마커가 있거나 빈 칸이면 그대로.

    감싸는 것 자체는 **의미를 바꾸지 않는다**(마커 없음 = 전체 공유). 목적은 가르치는
    것이다 — 연결하는 순간 문법이 눈앞에 나타나고, 사용자는 `&end` 를 앞으로 당겨
    구간을 줄이기만 하면 된다(사용자 지정).
    """
    source = str(text or "").strip()
    if not source or has_connect_region(source):
        return str(text or "")
    return f"&connect: {source} &end"


def strip_connect_markers(text: str) -> str:
    """마커만 걷어내고 내용은 남긴다. 마커가 없으면 손대지 않는다.

    쉼표/공백 정리는 `_join_character_text` 에 맡긴다 — 이음매에서 생기는 `, ,` 나
    앞뒤에 남는 쉼표를 이미 처리하는 함수라, 여기서 정규식으로 다시 짜면 규칙이 둘로
    갈린다.
    """
    if not has_connect_region(text):
        return str(text or "")
    head, shared, tail = _split_connect_region(text)
    return _join_character_text(_join_character_text(head, shared), tail)


def _expand_connect_field(
    raw: str,
    inherited: str,
    processor: WildcardProcessor | None,
    context: PromptContext,
    slot,
    slot_label,
) -> tuple[str, str]:
    """한 칸(프롬프트 또는 UC)을 전개해 `(이 슬롯의 최종값, 아래로 물려줄 값)` 을 낸다.

    ⚠️ 세 토막을 **원문 순서대로** 전개한다. 공유 구간만 따로 전개하면 순차
       와일드카드(`__*wc__`)·종속(`__$m:s__`)의 카운터가 원문과 다른 순서로 돌아
       화면에 보이는 것과 다른 값이 나온다.

    물려주는 값 = **물려받은 것 + 공유 구간**. 물려받은 것은 언제나 흘려보낸다 —
    그게 이 사슬이 나르는 "캐릭터" 자체이고, 마커는 *내가 더한 것 중 무엇을 공유할지*
    만 정한다(마커가 없으면 더한 것 전부).
    """
    head, shared, tail = _split_connect_region(raw)
    expand = lambda text: _expand_character_text(  # noqa: E731
        text, processor, context, slot=slot, slot_label=slot_label)
    expanded_head = expand(head)
    expanded_shared = expand(shared)
    expanded_tail = expand(tail)
    own = _join_character_text(_join_character_text(expanded_head, expanded_shared), expanded_tail)
    return (
        _join_character_text(inherited, own),
        _join_character_text(inherited, expanded_shared),
    )


def _join_character_text(base: str, own: str) -> str:
    """물려받은 텍스트 뒤에 이 슬롯이 직접 쓴 것을 잇는다. 한쪽이 비면 다른 쪽 그대로."""
    left = str(base or "").strip().strip(",").strip()
    right = str(own or "").strip().strip(",").strip()
    if not left:
        return right
    if not right:
        return left
    return f"{left}, {right}"


def _expand_character_text(
    text: str,
    processor: WildcardProcessor | None,
    context: PromptContext,
    slot=None,
    slot_label=None,
) -> str:
    pieces = [piece.strip() for piece in split_tags_smart(str(text or ""))]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return ""
    if processor is None:
        return ", ".join(pieces)
    # location='character'(+slot)으로 캐릭터 블록 와일드카드 롤을 위치 인식 기록한다(Wildcard
    # Watch 블록별 뷰). slot은 안정 uuid, slot_label은 표시용 1-based 번호다.
    return ", ".join(processor.expand_tags(pieces, context, location='character', slot=slot, slot_label=slot_label))


def character_params_from_settings(
    app_context,
    mode: str = "NAI",
    settings: dict | None = None,
    *,
    reuse_current_context: bool = True,
    save_root: Path | str | None = None,
    prefer_snapshot: bool = False,
) -> dict:
    """Resolve the character params for this call, with the SSOT precedence:

      1. An active conditional character override (per-run, e.g. ``char:1+=__wc__``)
         ALWAYS wins — return it. The snapshot must never bypass it.
      2. No active frames (module disabled / all slots inactive/empty) → no
         characters. A stale snapshot is NOT consumed while inactive (it may still
         persist so re-enabling restores the roll).
      3. ``prefer_snapshot`` and a stored (mode-keyed) snapshot exists → reuse it
         verbatim (NO re-roll). This is how Generate (reroll OFF / Ollama) and the
         random prompt grounding stay identical to what was rolled.
      4. Otherwise perform ONE fresh wildcard expansion and return it.

    This function does NOT persist the snapshot — storage is explicit at the
    authoritative roll sites (Random / Generate / Refresh) via
    ``store_character_roll_snapshot``, so one-off callers (Seed Fan-out,
    event-stream freeze) can expand without clobbering the session snapshot.
    Steps 1 and 2 are pure reads and run for ALL callers, so a disabled module
    or an active conditional override is honored everywhere.
    """
    if save_root is None:
        save_root = _save_root_from_context(app_context)
    # (1) Conditional override is per-run and outranks the snapshot.
    # ⚠️ 불변식(재발 버그 영역 — "피곤한 버그"): 이 분기는 아래 step 4의
    # _expand_character_text(와일드카드 전개)를 *우회*한다. 조건부 훅은 after_wildcard
    # (파이프라인의 유일한 전개 패스 이후)에 돌기 때문에, override 생산자
    # (conditional_prompt_runtime._store_character_overrides)가 emit하는 모든 캐릭터
    # 텍스트의 와일드카드를 *스스로* 전개해 둬야 한다. 표면별로 하나씩 누락돼 5회 재발했다:
    #   S1 액션 주입(char:N+=__wc__) 5c72e6e6 · S2 char_replace 8dd8bb9e ·
    #   S3 슬롯 베이스(캐릭터 칸 직접 입력) 97572409.
    # override에는 raw 토큰을 절대 넣지 말 것. (로컬 상세: CONDITIONAL_CHAR_WILDCARD_TRAP.md)
    override = _conditional_character_override(app_context, reuse_current_context=reuse_current_context)
    if override is not None:
        return override
    normalized = (
        normalize_character_settings(settings)
        if settings is not None
        else load_character_settings(mode, save_root=save_root)
    )
    _prune_frozen_character_slots(app_context, normalized)
    # (2) Inactive / no active frames → never consume a stale snapshot.
    frames = active_character_frames(normalized)
    if not frames:
        return {"characters": None}

    frame_slot_ids = _active_frame_slot_ids(frames)

    # (3) Reuse the stored roll without re-rolling. Frozen slots overlay the
    # snapshot so a user pin wins without forcing unrelated slots to reroll.
    if prefer_snapshot:
        snapshot = read_character_roll_snapshot(app_context, mode)
        if snapshot is not None:
            result = _snapshot_result(snapshot, frame_slot_ids)
            result = _overlay_frozen_character_slots(app_context, result, frame_slot_ids)
            _replay_character_snapshot_rolls(app_context, result, reuse_current_context=reuse_current_context)
            return result

    # (4) Fresh expansion (not stored here — see docstring).
    processor = None
    wildcard_manager = getattr(app_context, "wildcard_manager", None)
    if wildcard_manager is not None:
        processor = WildcardProcessor(wildcard_manager)
    context = _get_prompt_context(app_context, reuse_current_context=reuse_current_context)
    roll_start = len(context.wildcard_rolls) if isinstance(getattr(context, "wildcard_rolls", None), list) else 0
    frozen = read_frozen_character_slots(app_context)

    characters = []
    ucs = []
    character_ids = []
    # Connect: 앞선 슬롯의 **전개 결과**를 물려받는다. 이 루프가 활성 프레임을 화면
    # 순서대로 한 번 훑고, 링크는 항상 앞을 가리키므로(`_prune_character_links`)
    # 참조 시점에 값이 이미 확정돼 있다. 별도의 패스도, 순서 뒤집기도 필요 없다.
    expanded_by_uuid: dict[str, tuple[str, str]] = {}
    for slot_index, frame in enumerate(frames, 1):
        slot = frame_slot_ids[slot_index - 1] if slot_index - 1 < len(frame_slot_ids) else str(slot_index)
        frozen_payload = frozen.get(slot)
        if frozen_payload:
            prompt = frozen_payload["prompt"]
            uc = frozen_payload.get("uc", "")
            rolls = getattr(context, "wildcard_rolls", None)
            if isinstance(rolls, list):
                _append_frozen_character_roll(rolls, slot, prompt, slot_index)
        else:
            # 물려받은 것이 앞, 이 슬롯이 직접 쓴 것이 뒤 (사용자 지정: 연결 중에는
            # 두 칸이 "추가할" 칸이 된다). 고정된 원본을 물려받으면 그 고정값이 온다 —
            # 원본이 어느 분기로 확정됐든 `expanded_by_uuid` 에는 결과만 담기기 때문.
            base_prompt, base_uc = expanded_by_uuid.get(str(frame.get("connect_to") or ""), ("", ""))
            prompt, share_prompt = _expand_connect_field(
                frame.get("prompt", ""), base_prompt, processor, context, slot, slot_index)
            uc, share_uc = _expand_connect_field(
                frame.get("uc", ""), base_uc, processor, context, slot, slot_index)
            expanded_by_uuid[slot] = (share_prompt, share_uc)
            if prompt:
                characters.append(prompt)
                ucs.append(uc)
                character_ids.append(slot)
            continue
        expanded_by_uuid[slot] = (prompt, uc)
        if prompt:
            characters.append(prompt)
            ucs.append(uc)
            character_ids.append(slot)

    if not characters:
        return {"characters": None}
    return {
        "characters": characters,
        "uc": ucs,
        "character_ids": character_ids,
        "wildcard_rolls": _character_rolls_from_context(context, roll_start),
    }



# ─────────────────────────────────────────────────────────────────────────────
# SSOT character roll snapshot
#
# The character-prompt wildcard roll has exactly ONE source of truth at runtime:
# ``app_context._character_roll_snapshot`` = {MODE: {"characters": [...], "uc": [...]}}.
# It is the only roll — preview, Random box, Ollama boost grounding, and the NAI
# Generate payload all read the SAME snapshot. It is RUNTIME ONLY and must never
# be written to CharacterModule_*.json.
#
# Mode-keyed: a NAI roll is stored under "NAI" and only read back under "NAI", so
# switching API mode (or a stray request carrying a different api_mode) can never
# apply another mode's characters. (NAI v4/v4.5 is the only consumer of char
# captions anyway — see api_service _call_nai_api — but mode-keying is a cheap
# extra guard and keeps per-mode previews independent.)
#
# Who rolls (authoritative writers): Random (when reroll_on_generate is False),
# the "Refresh Preview" button, and Generate (when reroll_on_generate is True or
# no snapshot exists yet). State reads (panel open / get_module_state / set_param
# echo / preview render) NEVER re-roll — they only read the snapshot.
# ─────────────────────────────────────────────────────────────────────────────

CHARACTER_ROLL_SNAPSHOT_ATTR = "_character_roll_snapshot"


def _snapshot_mode_key(mode: str | None) -> str:
    return str(mode or "NAI").upper()


def _snapshot_store(app_context) -> dict | None:
    store = getattr(app_context, CHARACTER_ROLL_SNAPSHOT_ATTR, None)
    return store if isinstance(store, dict) else None


def read_character_roll_snapshot(app_context, mode: str = "NAI") -> dict | None:
    """Return the stored SSOT roll snapshot for ``mode`` ({"characters", "uc"}) or None."""
    store = _snapshot_store(app_context)
    if store is None:
        return None
    snapshot = store.get(_snapshot_mode_key(mode))
    if isinstance(snapshot, dict) and snapshot.get("characters"):
        return snapshot
    return None


def store_character_roll_snapshot(app_context, params: dict | None, mode: str = "NAI") -> dict | None:
    """Store ``params`` (an expanded character roll) as the SSOT snapshot for ``mode``.

    Returns the stored snapshot. If ``params`` carries no characters this is a
    NO-OP — it does NOT clear an existing snapshot. (An empty result usually means
    the module went inactive or a conditional override produced nothing for this
    run; the persisted roll must survive so re-enabling restores it. Explicit
    invalidation on content edits goes through ``clear_character_roll_snapshot``.)
    """
    if app_context is None:
        return None
    if not (isinstance(params, dict) and params.get("characters")):
        return None
    store = _snapshot_store(app_context)
    if store is None:
        store = {}
        setattr(app_context, CHARACTER_ROLL_SNAPSHOT_ATTR, store)
    snapshot = {
        "characters": [str(value) for value in params.get("characters") or []],
        "uc": [str(value) for value in params.get("uc") or []],
    }
    character_ids = [str(value) for value in params.get("character_ids") or [] if str(value).strip()]
    if character_ids:
        snapshot["character_ids"] = character_ids
    rolls = params.get("wildcard_rolls")
    if isinstance(rolls, list) and rolls:
        snapshot["wildcard_rolls"] = [dict(roll) for roll in rolls if isinstance(roll, dict)]
    store[_snapshot_mode_key(mode)] = snapshot
    return snapshot


def clear_character_roll_snapshot(app_context, mode: str | None = None) -> None:
    """Invalidate the SSOT snapshot. With ``mode`` clears just that mode; otherwise
    clears every mode (used on character content edits — the active mode is what
    the panel edits, and clearing all is the safe superset)."""
    if app_context is None:
        return
    store = _snapshot_store(app_context)
    if store is None:
        return
    if mode is None:
        store.clear()
    else:
        store.pop(_snapshot_mode_key(mode), None)


def roll_character_params(
    app_context,
    mode: str = "NAI",
    settings: dict | None = None,
    *,
    reuse_current_context: bool = False,
    save_root: Path | str | None = None,
) -> dict:
    """Perform ONE fresh character-prompt wildcard expansion and store it as the
    SSOT snapshot for ``mode``. Used by Random (reroll OFF) and Refresh Preview.
    Returns the expanded params ({"characters", "uc"} or {"characters": None}).

    Honors the same precedence as ``character_params_from_settings``: an active
    conditional override or an inactive module short-circuits before any roll.
    A conditional override (reuse_current_context=True) is per-run and is NOT
    persisted as the snapshot.
    """
    params = character_params_from_settings(
        app_context,
        mode=mode,
        settings=settings,
        reuse_current_context=reuse_current_context,
        save_root=save_root,
        prefer_snapshot=False,
    )
    # Only persist a genuine fresh expansion. A conditional override (returned via
    # reuse_current_context=True) must not become the persistent snapshot.
    override_active = (
        reuse_current_context
        and _conditional_character_override(app_context, reuse_current_context=True) is not None
    )
    if not override_active:
        store_character_roll_snapshot(app_context, params, mode)
    return params


def read_reroll_on_generate(app_context, mode: str = "NAI") -> bool:
    """Read the "Process wildcards on Generate" flag from the HEADLESS character
    settings (settings cache → disk fallback). Not the desktop module helper.
    """
    if app_context is not None:
        getter = getattr(app_context, "_character_settings_cache", None)
        if callable(getter):
            try:
                cached = getter()
            except Exception:
                cached = None
            if isinstance(cached, dict):
                return bool(cached.get("reroll_on_generate", False))
    try:
        save_root = _save_root_from_context(app_context) if app_context is not None else None
        loaded = load_character_settings(mode, save_root=save_root)
        return bool(loaded.get("reroll_on_generate", False))
    except Exception:
        return False


def _format_processed_preview(characters: list[str], ucs: list[str]) -> str:
    display_text = []
    for i, (prompt, uc) in enumerate(zip(characters, ucs)):
        display_text.append(f"C{i + 1}: {prompt}")
        display_text.append(f"UC{i + 1}: {uc}\n")
    return "\n".join(display_text)


def character_state_from_settings(
    settings: dict | None,
    app_context=None,
    mode: str = "NAI",
    *,
    save_root: Path | str | None = None,
) -> dict:
    if save_root is None and app_context is not None:
        save_root = _save_root_from_context(app_context)
    normalized = (
        normalize_character_settings(settings)
        if settings is not None
        else load_character_settings(mode, save_root=save_root)
    )
    frames = normalized.get("character_frames", [])
    characters = []
    for idx, frame in enumerate(frames):
        slot_state = normalize_slot_state(frame.get("slot_state"), bool(frame.get("is_enabled")))
        characters.append({
            "id": idx + 1,
            "slot_uuid": str(_frame_uuid(frame) or ""),
            # 셋을 다 보낸다 - 화면이 구분해 그려야 한다.
            #   active  = 활성 무리에 있나 (자리)
            #   muted   = 그 안에서 꺼져 있나 (✘)
            #   enabled = 실제로 나가나 (active and not muted)
            # 끈 슬롯을 비활성 슬롯과 같게 그리면 "제자리에 남는다" 는 사실이
            # 화면에서 사라진다 - 그게 이 기능의 요점이다.
            "active": slot_state == "active",
            "muted": bool(frame.get("is_muted")),
            "enabled": bool(frame.get("is_enabled")),
            "slot_state": slot_state,
            "return_slot_state": str(frame.get("return_slot_state") or ""),
            "custom_name": str(frame.get("custom_name") or ""),
            "prompt": str(frame.get("prompt") or ""),
            "uc": str(frame.get("uc") or ""),
            "position": normalize_position(frame.get("position")),
            # Connect 원본의 uuid(빈 문자열이면 연결 없음). 끊어진 링크는
            # `_prune_character_links` 가 정규화에서 이미 지웠으므로 여기 오는 값은
            # **항상 앞선 슬롯**을 가리킨다.
            "connect_to": str(frame.get("connect_to") or ""),
        })

    # SSOT: the preview reads the stored roll snapshot for this mode — it NEVER
    # re-rolls. Opening the panel / any get_module_state / any set_param echo must
    # show the SAME roll that Random/Refresh/Generate produced. If no snapshot
    # exists yet (or the module has no active frames) the preview is empty (the
    # frontend shows the "Use Refresh Preview" placeholder). Gating on active
    # frames keeps the preview consistent with what Generate would actually send.
    processed_characters: list[str] = []
    processed_ucs: list[str] = []
    if app_context is not None and active_character_frames(normalized):
        snapshot = read_character_roll_snapshot(app_context, mode)
        if snapshot is not None:
            processed_characters = [str(value) for value in snapshot.get("characters") or []]
            processed_ucs = [str(value) for value in snapshot.get("uc") or []]

    return {
        "type": "module_state",
        "module_id": "character",
        "activated": bool(normalized.get("is_active")),
        "reroll_on_generate": bool(normalized.get("reroll_on_generate")),
        "position_mode": str(normalized.get("position_mode") or "auto"),
        # 파생 미러. 옛 프런트/외부 소비자가 아직 이 이름을 읽는다.
        "use_custom_positions": bool(normalized.get("use_custom_positions")),
        "characters": characters,
        "character_count": len(characters),
        "active_count": sum(1 for item in characters if item.get("active")),
        # ⚠️ **실제로 나가는 수**. `active_count` 는 활성 무리의 크기라 꺼 둔
        #    슬롯까지 센다 - 배지가 그걸 쓰면 셋을 다 꺼 페이로드가 비어도
        #    "3 Characters" 라고 말한다(Codex 지적).
        "enabled_count": sum(1 for item in characters if item.get("enabled")),
        "cold_count": sum(1 for item in characters if item.get("slot_state") == "cold"),
        "processed_characters": processed_characters,
        "processed_ucs": processed_ucs,
        "character_token_count": 0,
        "processed_preview_text": _format_processed_preview(processed_characters, processed_ucs),
    }
