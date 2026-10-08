"""설정 JSON 을 전원이 끊겨도 잃지 않게 쓰고 읽는다.

사용자 제보(2026-10-08): PC 가 멈춰 콘센트를 뽑았더니 퀵 프리셋과 설정이 전부 초기화됐다.
`app_settings.json` · `presets/last_used_preset.json` 은 Auto Gen 중 몇 초마다 다시 쓰이는데,
- 디스크에 실제로 내려쓰기(fsync)를 하지 않아 전원이 끊기면 빈 파일 · 0 으로 찬 파일로 남을 수 있었고,
- 읽는 쪽은 깨진 파일을 말없이 `{}` 로 보고 기본값으로 돌아갔으며,
- 다음 저장이 그 기본값으로 덮어써 되살릴 길이 없었다(백업 없음).

여기서는 그 셋을 막는다.
- 쓰기(`write_json_safely`): 임시 파일에 다 쓰고 fsync 한 뒤 바꿔 끼운다. 본 파일이 끝난 **다음에** 같은 내용을
  `<이름>.bak` 에도 같은 방식으로 쓴다. 본 파일을 쓰다 끊기면 .bak 에 직전 정상본이 있고, .bak 을 쓰다 끊기면
  본 파일은 이미 디스크에 다 내려가 있다 - 둘이 함께 깨지는 순간이 없다.
- 읽기(`read_json_safely`): 파일이 있는데 못 읽으면 그 파일을 `<이름>.corrupt-<시각>` 으로 남겨 두고 `.bak` 에서 되살린다.

`core/character_settings.py` 의 저장 방어선(`_swap_in`)과 같은 방식이다. 새로 자주 쓰는 설정 파일이 생기면 이 두 함수를 쓴다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

# Windows 는 누가 파일을 열고만 있어도 바꿔 끼우기를 막는다 - 잠깐씩 기다렸다 다시 해 본다(character_settings 와 같은 값).
_BUSY_RETRY_DELAYS = (0.0, 0.05, 0.1, 0.2)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def backup_path(path: Path | str) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".bak")


def _lock_for(path: Path) -> threading.Lock:
    """같은 파일을 두 스레드가 동시에 쓰지 않게 한다(이벤트 루프 · 작업 스레드 양쪽에서 저장한다)."""
    key = os.path.normcase(os.path.abspath(str(path)))
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.Lock()
        return lock


def _read_state(path: Path) -> tuple[str, Any]:
    """('ok', 값) · ('missing', None) · ('corrupt', None) 중 하나를 돌려준다."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing", None
    except (OSError, UnicodeDecodeError):
        return "corrupt", None
    # 전원이 끊긴 파일은 0 바이트이거나 NUL 로 차 있다 - 둘 다 깨진 것이다
    if not text.strip(" \t\r\n\x00"):
        return "corrupt", None
    try:
        return "ok", json.loads(text)
    except ValueError:
        return "corrupt", None


def _durable_write(target: Path, text: str) -> None:
    """임시 파일에 쓰고 fsync 한 뒤 바꿔 끼운다. 끝내 못 바꾸면 제자리에 쓴다(저장을 잃지 않는 쪽)."""
    temp = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(temp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        last: OSError | None = None
        for delay in _BUSY_RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                os.replace(temp, target)
                return
            except PermissionError as exc:
                last = exc
        print(f"[WARN] {target.name}: swap is blocked ({last}); writing in place", flush=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def write_json_safely(path: Path | str, data: Any, *, indent: int = 2) -> None:
    """`data` 를 JSON 으로 저장한다. 본 파일을 다 쓴 뒤 같은 내용을 `.bak` 에도 남긴다.

    ⚠️ 순서가 핵심이다: 본 파일 -> .bak. 거꾸로 하거나 .bak 을 '직전 내용' 으로 두면 프리셋을 A -> B 로
       바꾼 직후 끊겼을 때 A 로 되살아난다.
    """
    path = Path(path)
    text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"   # 직렬화 실패는 파일을 건드리기 전에 난다
    with _lock_for(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        _durable_write(path, text)
        _durable_write(backup_path(path), text)


def read_json_safely(path: Path | str) -> Any | None:
    """JSON 을 읽는다. 못 읽으면 `.bak` 에서 되살리고, 그것도 없으면 None.

    깨진 파일은 지우지 않고 `<이름>.corrupt-<시각>` 으로 남긴다 - 다음 저장이 덮어 증거가 사라지지 않게.
    """
    path = Path(path)
    state, data = _read_state(path)
    if state == "ok":
        return data
    backup = backup_path(path)
    backup_state, backup_data = _read_state(backup)
    if state == "corrupt":
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            os.replace(path, path.with_name(f"{path.name}.corrupt-{stamp}"))
        except OSError:
            pass
        print(f"[WARN] {path.name} is unreadable (kept as .corrupt-{stamp}); "
              f"{'restoring from ' + backup.name if backup_state == 'ok' else 'no backup to restore'}", flush=True)
    if backup_state != "ok":
        return None
    if state == "corrupt":
        try:
            with _lock_for(path):
                _durable_write(path, backup.read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"[WARN] {path.name}: restore from backup failed ({exc})", flush=True)
    return backup_data
