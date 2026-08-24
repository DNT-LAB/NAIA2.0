"""Scene 저장소 — 한 장면을 통째로 담고 되살린다.

**Event > Scene** 두 층이다(사용자 지정). 이벤트는 만화 한 편, 씬은 그 안의 한 컷이다.
사용자는 이벤트를 먼저 만들고 그 안에 컷을 쌓는다.

    save/v5_scenes/
    └── <이벤트>/
        ├── _event.json      # 이름 · 컷 순서(order)
        ├── <씬>.json
        └── <씬>.webp

씬이 담는 것은 **구도**다(사용자 지정):

    메인 프롬프트 · 캐릭터(프롬프트·UC·좌표·Connect·이름) · 해상도 · POS 모드

**네거티브는 안 담는다**(사용자 지정) - 되돌리기가 사용자의 네거티브를 통째로 덮어쓰는
것은 치명적이다. 네거티브는 씬을 넘나드는 사용자의 기본 설정이지 구도의 일부가 아니다.
구도가 무언가를 빼야 한다면 `-태그` 로 적는다(연결된 슬롯에서 물려받은 태그를 지우는
문법 — `character_settings._apply_minus_tags`).

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
# 2 = **프롬프트에 구도만 담긴다**(프롬프트 엔지니어링은 저장 시점에 걷어낸다).
# 1 이하는 조립된 프롬프트를 통째로 들고 있어 읽을 때 되짚어야 한다.
# ⚠️ 이 판 구분이 없으면 되짚기가 새 씬에도 걸려, 사용자가 직접 친 세 문단을
#    `prefix/main/postfix` 로 오인해 가운데만 남기고 버린다(Codex CONCERN
#    2026-08-25 재현: `castle\n\nnight\n\nrain` -> `night`).
SCENE_SCHEMA_VERSION = 2
# 이벤트 폴더 안의 메타 파일. `_` 로 시작해 씬 파일(`*.json`)과 섞이지 않는다.
EVENT_META_NAME = "_event.json"
EVENT_SCHEMA_VERSION = 1
# 평면으로 저장돼 있던 옛 씬들을 담을 이벤트 이름(공통 접두사를 못 뽑을 때).
LEGACY_EVENT_NAME = "이전 씬"
# 파일명으로 못 쓰는 문자. `prompt_engineering_settings.sanitize_preset_name` 과 같은 목록.
_FORBIDDEN_NAME_CHARS = '<>:"/\\|?*'


def sanitize_scene_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    sanitized = name.strip()
    for char in _FORBIDDEN_NAME_CHARS:
        sanitized = sanitized.replace(char, "")
    sanitized = sanitized.strip().strip(".")
    # `_` 로 시작하는 이름은 메타 파일(`_event.json`)과 부딪힌다. 앞의 `_` 만 걷어낸다.
    return sanitized.lstrip("_").strip()


# 이벤트 이름도 같은 규칙이다 - 둘 다 파일 시스템 이름이 된다.
sanitize_event_name = sanitize_scene_name


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


def _root_dirs(save_root: str | Path | None = None) -> list[Path]:
    """읽을 때 훑는 뿌리들. 쓰기는 언제나 첫 번째에만 한다."""
    primary = scene_dir(save_root)
    dirs = [primary]
    legacy = (Path("save") / SCENE_DIR_NAME).resolve()
    if _legacy_save_fallback_enabled() and legacy != primary.resolve():
        dirs.append(legacy)
    return dirs


# ── 이벤트 ───────────────────────────────────────────────────────────────
# 이벤트 = **폴더**다. 씬은 그 안의 파일이고, 순서는 `_event.json` 의 `order` 배열이다.
#
# 폴더로 나눈 이유: 이 기능이 지원하는 조작 셋 중 하나가 **폴더 열기**라, 사용자가
# 파일을 직접 다루는 것이 규약이다. 그러면 파일 구조가 곧 화면이어야 한다. 덤으로 씬
# 이름이 이벤트 안에서만 유일하면 되니 `1컷`·`2컷` 을 이벤트마다 재사용할 수 있다.
#
# ⚠️ `order` 에 없는 파일은 **뒤에 붙인다.** 폴더에 파일을 떨궈 넣는 것이 그대로
#    동작해야 한다 - 안 그러면 직접 넣은 씬이 조용히 사라진 것처럼 보인다.


def event_dir(event: str, save_root: str | Path | None = None) -> Path | None:
    clean = sanitize_event_name(event)
    if not clean:
        return None
    return scene_dir(save_root) / clean


def _event_read_dirs(event: str, save_root: str | Path | None = None) -> list[Path]:
    clean = sanitize_event_name(event)
    if not clean:
        return []
    return [base / clean for base in _root_dirs(save_root)]


def list_event_names(save_root: str | Path | None = None) -> list[str]:
    """이벤트(=폴더) 이름들. 먼저 평면 씬이 남아 있으면 한 이벤트로 옮긴다."""
    migrate_flat_scenes(save_root)
    names: list[str] = []
    seen: set[str] = set()
    for base in _root_dirs(save_root):
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir()):
            if not path.is_dir():
                continue
            clean = sanitize_event_name(path.name)
            if clean and clean not in seen:
                seen.add(clean)
                names.append(clean)
    return names


def read_event(event: str, save_root: str | Path | None = None) -> dict[str, Any] | None:
    """이벤트 메타. `order` 는 **실제 파일과 화해된** 순서다.

    없는 씬은 빠지고, 폴더에만 있는 씬은 뒤에 붙는다.
    """
    clean = sanitize_event_name(event)
    if not clean:
        return None
    dirs = [path for path in _event_read_dirs(clean, save_root) if path.is_dir()]
    if not dirs:
        return None
    stored: list[str] = []
    for base in dirs:
        meta = base / EVENT_META_NAME
        if not meta.exists():
            continue
        try:
            raw = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict) and isinstance(raw.get("order"), list):
            stored = [sanitize_scene_name(item) for item in raw["order"]]
            break
    present = _scene_stems(clean, save_root)
    order = [name for name in stored if name in present]
    seen = set(order)
    for name in present:
        if name not in seen:
            seen.add(name)
            order.append(name)
    return {"version": EVENT_SCHEMA_VERSION, "name": clean, "order": order}


def _scene_stems(event: str, save_root: str | Path | None = None) -> list[str]:
    """폴더에 실제로 있는 씬 파일 이름들(정렬). 메타 파일은 뺀다."""
    names: list[str] = []
    seen: set[str] = set()
    for base in _event_read_dirs(event, save_root):
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.json")):
            if path.name == EVENT_META_NAME:
                continue
            stem = sanitize_scene_name(path.stem)
            if stem and stem not in seen:
                seen.add(stem)
                names.append(stem)
    return names


def write_event_order(event: str, order: list[str], save_root: str | Path | None = None) -> bool:
    base = event_dir(event, save_root)
    if base is None:
        return False
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": EVENT_SCHEMA_VERSION,
        "name": sanitize_event_name(event),
        "order": [sanitize_scene_name(item) for item in order if sanitize_scene_name(item)],
    }
    try:
        (base / EVENT_META_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return False
    return True


def create_event(name: str, save_root: str | Path | None = None) -> str | None:
    """빈 이벤트를 만든다. 이미 있으면 그 이름을 그대로 돌려준다(덮지 않는다)."""
    clean = sanitize_event_name(name)
    if not clean:
        return None
    base = event_dir(clean, save_root)
    if base is None:
        return None
    existed = base.is_dir()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if not existed:
        write_event_order(clean, [], save_root)
    return clean


def move_scene(event: str, name: str, delta: int, save_root: str | Path | None = None) -> bool:
    """씬을 순서에서 위/아래로 한 칸 옮긴다(`delta` = -1 / +1)."""
    meta = read_event(event, save_root)
    if meta is None:
        return False
    order = list(meta["order"])
    clean = sanitize_scene_name(name)
    if clean not in order:
        return False
    index = order.index(clean)
    target = index + int(delta)
    if not (0 <= target < len(order)):
        return False
    order[index], order[target] = order[target], order[index]
    return write_event_order(event, order, save_root)


def _longest_common_prefix(names: list[str]) -> str:
    if not names:
        return ""
    prefix = names[0]
    for name in names[1:]:
        while prefix and not name.startswith(prefix):
            prefix = prefix[:-1]
    # 접두사가 낱말 중간에서 끊기면 이름이 이상해진다 - 구분자에서 자른다.
    return prefix.strip().rstrip("-_ .,").strip()


def migrate_flat_scenes(save_root: str | Path | None = None) -> str | None:
    """이벤트가 생기기 전에 평면으로 저장된 씬들을 이벤트 하나로 옮긴다(사용자 지정).

    ⚠️ **쓰기 뿌리에 있는 것만 옮긴다.** 레거시 폴백 경로는 읽기 전용이라 손대면
       다른 설치본의 파일을 움직이게 된다.
    이름은 씬들의 공통 접두사에서 뽑고, 못 뽑으면 `이전 씬`. 이미 옮길 것이 없으면 None.
    """
    base = scene_dir(save_root)
    if not base.is_dir():
        return None
    loose = [path for path in base.glob("*.json") if path.name != EVENT_META_NAME]
    if not loose:
        return None
    # ⚠️ 순서는 **만든 시각**을 따른다. 이름순으로 두면 `제목 - 2` 가 `제목` 보다 앞에
    #    온다(' ' < '.'). 만화의 컷 순서가 거꾸로 들어가는 셈이라 눈에 띄게 틀린다.
    # ⚠️ mtime 이 아니라 **생성 시각**이다. 파일을 한 번이라도 고쳐 쓰면 mtime 이 다 같이
    #    밀려 순서가 뭉개진다(실측: 두 씬을 일괄 정리했더니 0.4초 차이로 붙었다).
    def _made_at(path: Path) -> tuple:
        try:
            stat = path.stat()
        except OSError:
            return (0.0, path.name)
        made = getattr(stat, "st_birthtime", None)
        if made is None:
            made = stat.st_ctime if os.name == "nt" else stat.st_mtime
        return (float(made), path.name)

    loose.sort(key=_made_at)
    stems = [path.stem for path in loose]
    event = sanitize_event_name(_longest_common_prefix(stems)) or LEGACY_EVENT_NAME
    # 같은 이름의 폴더가 이미 있으면 그 안에 합친다 - 새 이름을 지어내면 사용자가 못 찾는다.
    target = base / event
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    # ⚠️ **`Path.replace` 는 말없이 덮어쓴다.** 합치는 폴더에 같은 이름의 컷이 이미 있으면
    #    사용자의 진짜 작업물이 사라진다(Codex 리뷰 BLOCK - 재현 완료: 이벤트 안의
    #    `Comic - 1` 이 평면의 동명 파일로 통째로 바뀌었다). 부딪히는 것은 **옮기지 않고
    #    그 자리에 둔다** - 자동 정리가 사용자 데이터를 지우는 일은 없어야 한다.
    #    남겨진 파일은 다음에 다시 이 함수를 타므로 기회를 잃지도 않는다.
    moved: list[Path] = []
    for path in loose:
        dest = target / path.name
        if dest.exists():
            continue
        thumb = path.with_suffix(THUMB_SUFFIX)
        dest_thumb = target / thumb.name
        try:
            path.replace(dest)
        except OSError:
            continue
        moved.append(path)
        if thumb.exists() and not dest_thumb.exists():
            try:
                thumb.replace(dest_thumb)
            except OSError:
                pass       # 그림 하나를 못 옮긴 것이 컷을 잃을 이유는 아니다
    if not moved:
        return None
    # 순서는 **옮긴 것만** 이어 붙인다. `read_event` 가 폴더에 있는 것과 화해시키므로
    # 이미 있던 컷도 빠지지 않는다.
    existing = read_event(event, save_root)
    order = list(existing["order"]) if existing else []
    for path in moved:
        if path.stem not in order:
            order.append(path.stem)
    write_event_order(event, order, save_root)
    return event


def scene_path(event: str, name: str, save_root: str | Path | None = None) -> Path | None:
    """쓸 자리. 이름이 비면 None."""
    clean = sanitize_scene_name(name)
    base = event_dir(event, save_root)
    if not clean or base is None:
        return None
    return base / f"{clean}.json"


def _existing_scene_path(event: str, name: str, save_root: str | Path | None = None) -> Path | None:
    clean = sanitize_scene_name(name)
    if not clean:
        return None
    for base in _event_read_dirs(event, save_root):
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
    # ⚠️ **네거티브는 담지 않는다**(사용자 지정). 되돌리기가 사용자의 네거티브를 통째로
    #    덮어쓰는 것은 치명적이다 - 네거티브는 씬을 넘나드는 사용자의 기본 설정이지
    #    구도의 일부가 아니다. 구도가 무언가를 빼야 한다면 `-태그` 로 적는다(연결된
    #    캐릭터 슬롯에서 물려받은 태그를 지우는 문법 — `character_settings._apply_minus_tags`).
    #    옛 씬이 들고 있던 값은 여기서 조용히 버린다.
    # 되짚기는 **옛 판에만** 건다. 새 판은 이미 구도만 담고 있으므로 손대면 사용자가
    # 직접 친 여러 문단을 조립된 프롬프트로 오인해 버린다.
    try:
        raw_version = int(data.get("version") or 0)
    except (TypeError, ValueError):
        raw_version = 0
    prompt = (str(data.get("prompt") or "") if raw_version >= SCENE_SCHEMA_VERSION
              else _normalized_prompt(data.get("prompt")))
    return {
        "version": SCENE_SCHEMA_VERSION,
        "name": sanitize_scene_name(data.get("name")),
        "mode": mode,
        "prompt": prompt,
        "resolution": str(data.get("resolution") or ""),
        "position_mode": position_mode,
        "characters": characters,
    }


def _normalized_prompt(raw: Any) -> str:
    """옛 씬이 담고 있는 **조립된** 프롬프트를 구도만 남게 되돌린다.

    프롬프트 엔지니어링을 빼고 담기 시작하기 전에 저장된 씬은 작가·품질·연도까지
    통째로 들고 있다. 구조가 다르므로(`prefix \\n\\n main \\n\\n postfix`) 알아볼 수
    있고, 읽을 때마다 걷어내면 따로 마이그레이션 도구를 둘 필요가 없다.
    담긴 값 자체는 다음 저장 때 정리된 모습으로 덮인다.

    ⚠️ **덩어리가 셋 이상일 때만 손댄다.** 조립된 프롬프트는 언제나
       `prefix \\n\\n main \\n\\n postfix` 셋이다. 둘짜리는 사용자가 직접 친 두 문단일
       뿐인데, 예전엔 그것까지 되짚어 **통째로 날려 먹었다**(Codex 리뷰 CONCERN -
       재현: `'castle\\n\\nnight'` -> `''`). 애매하면 손대지 않는 쪽이 맞다 - 못 알아본
       옛 씬은 화면에 길게 보일 뿐이지만, 뭉갠 프롬프트는 되돌릴 방법이 없다.
    """
    text = str(raw or "")
    if len(text.split("\n\n")) < 3:
        return text
    return bare_from_text(text)


def tags_of(text: Any) -> list[str]:
    """조립된 프롬프트 조각에서 태그만 뽑는다. 주석(`#...`) 줄은 태그가 아니다."""
    out = []
    for part in str(text or "").replace("\n", ",").split(","):
        tag = part.strip()
        if tag and not tag.startswith("#"):
            out.append(tag)
    return out


def bare_from_text(text: Any) -> str:
    """조립된 글에서 **사용자의 구도**만 구조로 되짚는다.

    최종 포맷의 산출물은 `prefix \\n\\n main \\n\\n postfix` 다(`_inject_boost_at_main`
    이 같은 규약을 쓴다). 덩어리가 셋이면 가운데가 사용자 몫이고, 앞 덩어리에서는
    **인물 수 태그만** 데려온다 - 그건 옮겨졌을 뿐 원래 사용자 것이다
    (`prompt_processor._step_final_format` 이 main -> prefix 로 옮긴다).
    덩어리 경계가 없으면(손으로 친 프롬프트) 통째로 사용자 것이다.
    """
    from core.prompt_processor import ALL_PERSON_TAGS

    raw = str(text or "")
    blocks = raw.split("\n\n")
    if len(blocks) < 2:
        return ", ".join(tags_of(raw))
    # 앞=prefix, 뒤=postfix, 나머지 가운데가 main. 덩어리가 둘뿐이면 main 이 비었던 것이라
    # 가운데는 없고 인물 태그만 남는다.
    head, middle = blocks[0], blocks[1:-1] if len(blocks) > 2 else []
    person = [tag for tag in tags_of(head) if tag in ALL_PERSON_TAGS]
    body = []
    for block in middle:
        body.extend(tags_of(block))
    return ", ".join(person + body)


def list_scene_names(event: str, save_root: str | Path | None = None) -> list[str]:
    """이벤트 안의 씬 이름들. **`_event.json` 의 순서**를 따른다."""
    meta = read_event(event, save_root)
    return list(meta["order"]) if meta else []


def read_scene(event: str, name: str, save_root: str | Path | None = None) -> dict[str, Any] | None:
    path = _existing_scene_path(event, name, save_root)
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scene = normalize_scene(raw)
    # 파일명이 곧 이름이다 - 안쪽 name 이 비었거나 어긋나도 파일명을 따른다.
    scene["name"] = sanitize_scene_name(path.stem) or scene["name"]
    scene["event"] = sanitize_event_name(event)
    return scene


def write_scene(event: str, scene: dict[str, Any], save_root: str | Path | None = None) -> Path | None:
    # ⚠️ 쓰는 값은 **이미 구도만** 담고 있다(서비스가 저장 시점에 프롬프트 엔지니어링을
    #    걷어내 넘긴다). 판을 안 찍어 주면 `normalize_scene` 이 이걸 옛 씬으로 보고
    #    되짚기를 걸어, 문단이 셋인 사용자 프롬프트를 가운데만 남기고 버린다.
    incoming = dict(scene) if isinstance(scene, dict) else {}
    incoming["version"] = SCENE_SCHEMA_VERSION
    normalized = normalize_scene(incoming)
    path = scene_path(event, normalized["name"], save_root)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    # 새 씬은 순서의 **끝**에 붙는다. 이미 있으면 자리를 지킨다 - 덮어쓰기가 순서를
    # 흔들면 3컷을 고쳤을 뿐인데 만화 순서가 바뀐다.
    meta = read_event(event, save_root)
    if meta is not None:
        write_event_order(event, meta["order"], save_root)
    return path


def delete_scene(event: str, name: str, save_root: str | Path | None = None) -> bool:
    """지운다. **쓰기 루트에 있는 것만** 지운다 - 레거시 폴백은 읽기 전용으로 둔다.

    썸네일도 함께 지운다 - 남겨 두면 같은 이름으로 새 씬을 만들 때 남의 그림이 붙는다.
    """
    path = scene_path(event, name, save_root)
    existed = bool(path is not None and path.exists())
    if existed:
        try:
            path.unlink()
        except OSError:
            return False
    delete_scene_thumb(event, name, save_root)
    if existed:
        meta = read_event(event, save_root)
        if meta is not None:
            write_event_order(event, meta["order"], save_root)
    return existed


# ── 썸네일 ───────────────────────────────────────────────────────────────
# 씬 옆에 같은 이름의 그림을 둔다(`<name>.json` + `<name>.webp`). 구도를 담는 기능이라
# **말보다 그림이 빠르다** — 목록에서 "2인 · 832 x 1216" 만 봐서는 어느 구도인지 모른다.
#
# ⚠️ 리비전은 **내용에서 뽑는다**(mtime_ns + size). 이름이 같은 파일을 갈아치워도 URL 이
#    달라져야 브라우저가 옛 그림을 안 보여 준다 — 이 저장소가 이미 한 번 밟은 함정이다
#    (캐릭터 뷰어 썸네일).
THUMB_SUFFIX = ".webp"


def scene_thumb_path(event: str, name: str, save_root: str | Path | None = None) -> Path | None:
    clean = sanitize_scene_name(name)
    base = event_dir(event, save_root)
    if not clean or base is None:
        return None
    return base / f"{clean}{THUMB_SUFFIX}"


def existing_scene_thumb(event: str, name: str, save_root: str | Path | None = None) -> Path | None:
    clean = sanitize_scene_name(name)
    if not clean:
        return None
    for base in _event_read_dirs(event, save_root):
        candidate = base / f"{clean}{THUMB_SUFFIX}"
        if candidate.exists():
            return candidate
    return None


def scene_thumb_revision(event: str, name: str, save_root: str | Path | None = None) -> str:
    """URL 에 붙일 리비전. 썸네일이 없으면 빈 문자열."""
    path = existing_scene_thumb(event, name, save_root)
    if path is None:
        return ""
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def write_scene_thumb(event: str, name: str, data: bytes,
                      save_root: str | Path | None = None) -> Path | None:
    """썸네일을 쓴다. 임시 파일에 쓴 뒤 바꿔치기해 **반쯤 쓰인 그림**이 안 남게 한다."""
    path = scene_thumb_path(event, name, save_root)
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


def delete_scene_thumb(event: str, name: str, save_root: str | Path | None = None) -> bool:
    path = scene_thumb_path(event, name, save_root)
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
