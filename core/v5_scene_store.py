"""Scene 저장소 — 한 장면을 통째로 담고 되살린다.

씬이 담는 것은 **구도**다(사용자 지정):

    메인 프롬프트 / 네거티브 · 캐릭터(프롬프트·UC·좌표·Connect·이름) · 해상도 · POS 모드

steps/cfg/sampler/model 은 **일부러 안 담는다.** 그건 Prompt Engineering 프리셋의
몫이라, 서로 직교하게 두면 "프리셋 × 씬" 을 조합할 수 있다. 시드도 안 담는다 — 씬은
보통 "이 구도로 **다른** 그림" 을 위한 것이고, 그 그림 그대로가 필요하면 시드 고정
알약이 따로 있다.

⚠️ **캐릭터 텍스트는 전개하지 않고 원문 그대로 담는다.** `__wc__` 나
   `&connect: … &end` 가 그대로 남아야 씬을 다시 불러올 때 새로 굴려진다. 전개된
   결과를 담으면 씬이 한 장의 사진이 되어 버린다.

⚠️ **Connect 링크는 uuid 가 아니라 번호로 담는다.** uuid 는 그 설치본 안에서만 뜻이
   있어서 씬 파일을 다른 기기로 옮기거나 슬롯을 다시 만들면 가리킬 곳이 없다.
   저장은 씬 안 배열의 1-based 번호(0 = 연결 없음), 복원할 때 새 uuid 로 되살린다.

저장 위치·경로 해석은 `prompt_engineering_settings` 와 같은 규약을 따른다
(`NAIA_USER_DATA_DIR` → `save/`, 레거시 `save/` 폴백).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SCENE_DIR_NAME = "v5_scenes"
SCENE_SCHEMA_VERSION = 1
# 파일명으로 못 쓰는 문자. `prompt_engineering_settings.sanitize_preset_name` 과 같은 목록.
_FORBIDDEN_NAME_CHARS = '<>:"/\\|?*'


def sanitize_scene_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    sanitized = name.strip()
    for char in _FORBIDDEN_NAME_CHARS:
        sanitized = sanitized.replace(char, "")
    return sanitized.strip()


def _default_save_root() -> Path:
    user_data_dir = os.environ.get("NAIA_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir).expanduser().resolve() / "save"
    return Path("save")


def _coerce_save_root(save_root: str | Path | None = None) -> Path:
    return Path(save_root).expanduser().resolve() if save_root is not None else _default_save_root()


def _legacy_save_fallback_enabled() -> bool:
    if os.environ.get("NAIA_DISABLE_LEGACY_SAVE_FALLBACK") == "1":
        return False
    if os.environ.get("NAIA_ELECTRON") == "1":
        return False
    return True


def scene_dir(save_root: str | Path | None = None) -> Path:
    return _coerce_save_root(save_root) / SCENE_DIR_NAME


def _read_dirs(save_root: str | Path | None = None) -> list[Path]:
    """읽을 때 훑는 디렉터리들. 쓰기는 언제나 첫 번째에만 한다."""
    primary = scene_dir(save_root)
    dirs = [primary]
    legacy = (Path("save") / SCENE_DIR_NAME).resolve()
    if _legacy_save_fallback_enabled() and legacy != primary.resolve():
        dirs.append(legacy)
    return dirs


def scene_path(name: str, save_root: str | Path | None = None) -> Path | None:
    """쓸 자리. 이름이 비면 None."""
    clean = sanitize_scene_name(name)
    if not clean:
        return None
    return scene_dir(save_root) / f"{clean}.json"


def _existing_scene_path(name: str, save_root: str | Path | None = None) -> Path | None:
    clean = sanitize_scene_name(name)
    if not clean:
        return None
    for base in _read_dirs(save_root):
        candidate = base / f"{clean}.json"
        if candidate.exists():
            return candidate
    return None


def normalize_position(value: Any) -> dict[str, float] | None:
    """`{'x','y'}` 를 0~1 소수 3자리로. 좌표가 아니면 None.

    `character_settings.normalize_position` 과 같은 규약이다. 그쪽을 import 하지 않는
    이유는 이 모듈이 저장 계층이라 캐릭터 모듈에 의존하지 않게 두기 위해서다.
    """
    if not isinstance(value, dict):
        return None
    try:
        x = float(value.get("x"))
        y = float(value.get("y"))
    except (TypeError, ValueError):
        return None
    return {"x": round(min(1.0, max(0.0, x)), 3), "y": round(min(1.0, max(0.0, y)), 3)}


def normalize_scene_character(raw: Any, *, count: int, index: int) -> dict[str, Any]:
    """씬 안의 캐릭터 한 칸.

    `connect_to` 는 **1-based 번호**이고 반드시 자기보다 앞을 가리켜야 한다
    (`character_settings._prune_character_links` 와 같은 규약). 어긋나면 0 으로 지운다 —
    씬을 불러온 뒤에 조용히 끊기는 것보다 담을 때 정리하는 편이 낫다.
    """
    data = raw if isinstance(raw, dict) else {}
    link = data.get("connect_to")
    try:
        link_index = int(link)
    except (TypeError, ValueError):
        link_index = 0
    if not (1 <= link_index <= count) or link_index >= index + 1:
        link_index = 0
    return {
        "prompt": str(data.get("prompt") or ""),
        "uc": str(data.get("uc") or ""),
        "custom_name": str(data.get("custom_name") or ""),
        "position": normalize_position(data.get("position")),
        "connect_to": link_index,
    }


def normalize_scene(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    characters_raw = data.get("characters")
    characters_raw = characters_raw if isinstance(characters_raw, list) else []
    count = len(characters_raw)
    characters = [
        normalize_scene_character(item, count=count, index=index)
        for index, item in enumerate(characters_raw)
    ]
    # 사슬 금지도 여기서 지킨다 - 이미 남을 물고 있는 칸은 원본이 될 수 없다.
    for index, character in enumerate(characters):
        link = character["connect_to"]
        if link and characters[link - 1]["connect_to"]:
            character["connect_to"] = 0
    mode = str(data.get("mode") or "NAI").upper()
    position_mode = str(data.get("position_mode") or "auto").strip().lower()
    if position_mode not in ("auto", "custom", "random"):
        position_mode = "auto"
    return {
        "version": SCENE_SCHEMA_VERSION,
        "name": sanitize_scene_name(data.get("name")),
        "mode": mode,
        "prompt": str(data.get("prompt") or ""),
        "negative": str(data.get("negative") or ""),
        "resolution": str(data.get("resolution") or ""),
        "position_mode": position_mode,
        "characters": characters,
    }


def list_scene_names(save_root: str | Path | None = None) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for base in _read_dirs(save_root):
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.json")):
            stem = path.stem
            if stem and stem not in seen:
                seen.add(stem)
                names.append(stem)
    return names


def read_scene(name: str, save_root: str | Path | None = None) -> dict[str, Any] | None:
    path = _existing_scene_path(name, save_root)
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scene = normalize_scene(raw)
    # 파일명이 곧 이름이다 - 안쪽 name 이 비었거나 어긋나도 파일명을 따른다.
    scene["name"] = sanitize_scene_name(path.stem) or scene["name"]
    return scene


def write_scene(scene: dict[str, Any], save_root: str | Path | None = None) -> Path | None:
    normalized = normalize_scene(scene)
    path = scene_path(normalized["name"], save_root)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def delete_scene(name: str, save_root: str | Path | None = None) -> bool:
    """지운다. **쓰기 루트에 있는 것만** 지운다 - 레거시 폴백은 읽기 전용으로 둔다.

    썸네일도 함께 지운다 - 남겨 두면 같은 이름으로 새 씬을 만들 때 남의 그림이 붙는다.
    """
    path = scene_path(name, save_root)
    existed = bool(path is not None and path.exists())
    if existed:
        try:
            path.unlink()
        except OSError:
            return False
    delete_scene_thumb(name, save_root)
    return existed


# ── 썸네일 ───────────────────────────────────────────────────────────────
# 씬 옆에 같은 이름의 그림을 둔다(`<name>.json` + `<name>.webp`). 구도를 담는 기능이라
# **말보다 그림이 빠르다** — 목록에서 "2인 · 832 x 1216" 만 봐서는 어느 구도인지 모른다.
#
# ⚠️ 리비전은 **내용에서 뽑는다**(mtime_ns + size). 이름이 같은 파일을 갈아치워도 URL 이
#    달라져야 브라우저가 옛 그림을 안 보여 준다 — 이 저장소가 이미 한 번 밟은 함정이다
#    (캐릭터 뷰어 썸네일).
THUMB_SUFFIX = ".webp"


def scene_thumb_path(name: str, save_root: str | Path | None = None) -> Path | None:
    clean = sanitize_scene_name(name)
    if not clean:
        return None
    return scene_dir(save_root) / f"{clean}{THUMB_SUFFIX}"


def existing_scene_thumb(name: str, save_root: str | Path | None = None) -> Path | None:
    clean = sanitize_scene_name(name)
    if not clean:
        return None
    for base in _read_dirs(save_root):
        candidate = base / f"{clean}{THUMB_SUFFIX}"
        if candidate.exists():
            return candidate
    return None


def scene_thumb_revision(name: str, save_root: str | Path | None = None) -> str:
    """URL 에 붙일 리비전. 썸네일이 없으면 빈 문자열."""
    path = existing_scene_thumb(name, save_root)
    if path is None:
        return ""
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def write_scene_thumb(name: str, data: bytes, save_root: str | Path | None = None) -> Path | None:
    """썸네일을 쓴다. 임시 파일에 쓴 뒤 바꿔치기해 **반쯤 쓰인 그림**이 안 남게 한다."""
    path = scene_thumb_path(name, save_root)
    if path is None or not data:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return None
    return path


def delete_scene_thumb(name: str, save_root: str | Path | None = None) -> bool:
    path = scene_thumb_path(name, save_root)
    if path is None or not path.exists():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def scene_summary(scene: dict[str, Any]) -> str:
    """목록에 한 줄로 보일 요약. 캐릭터 수와 해상도."""
    characters = scene.get("characters") or []
    parts: list[str] = [f"{len(characters)}인"]
    resolution = str(scene.get("resolution") or "").strip()
    if resolution:
        parts.append(resolution)
    linked = sum(1 for item in characters if item.get("connect_to"))
    if linked:
        parts.append(f"연결 {linked}")
    return " · ".join(parts)
