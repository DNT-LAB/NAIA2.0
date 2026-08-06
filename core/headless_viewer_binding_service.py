"""뷰어 숏컷 바인딩 — 특정 버튼 하나로 보고 있는 그림을 정해 둔 폴더에 넘긴다.

Dev0714 의 데스크톱 뷰어(`ui/image_viewer_window.py`)가 갖고 있던 기능을 옮긴 것이다.
그쪽은 대상 폴더가 **하나**뿐이었지만 여기서는 바인딩마다 따로 둘 수 있다 —
"이 버튼은 이 폴더로"가 사용자가 원한 것이라서다. 폴더를 비워 두면 공용 폴더를 쓴다.

**경로는 클라이언트가 실행 시점에 주지 않는다.** 실행 요청은 `input_id` 만 보내고,
어디에 쓸지는 서버가 저장된 설정에서 찾는다. 이렇게 하지 않으면 "아무 경로에나 파일을
쓰는 라우트"가 생기고, LAN 으로 붙은 다른 사람도 그걸 부를 수 있다. 경로가 설정에만
있으면 그 표면이 저장 폴더 설정과 같은 등급으로 내려온다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

# 액션. Dev0714 의 copy/move/delete 와 같되, 삭제는 이름을 `trash` 로 못박는다 —
# 이 경로는 **휴지통으로만** 보내고 영구 삭제는 하지 않는다.
ACTION_COPY = "copy"
ACTION_MOVE = "move"
ACTION_TRASH = "trash"
VIEWER_ACTIONS = (ACTION_COPY, ACTION_MOVE, ACTION_TRASH)

ACTION_LABELS = {
    ACTION_COPY: "복사",
    ACTION_MOVE: "이동",
    ACTION_TRASH: "삭제 (휴지통)",
}

SETTINGS_FILENAME = "viewer_bindings.json"
MAX_BINDINGS = 12
MAX_INPUT_ID = 64


def _clean_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


class HeadlessViewerBindingService:
    def __init__(self, context: Any) -> None:
        self.context = context

    # ── 저장소 ──────────────────────────────────────────────────────────────
    def settings_path(self) -> Path:
        return self.context._save_path(SETTINGS_FILENAME)

    def load(self) -> dict[str, Any]:
        path = self.settings_path()
        raw: dict[str, Any] = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # 파일이 상했으면 기본값으로 시작한다 — 여기서 터지면 뷰어가 안 열린다.
                raw = {}
        if not isinstance(raw, dict):
            raw = {}
        return self._normalize(raw)

    def save(self, payload: Any) -> dict[str, Any]:
        normalized = self._normalize(payload if isinstance(payload, dict) else {})
        path = self.settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return normalized

    # ── 정규화 ──────────────────────────────────────────────────────────────
    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        bindings: list[dict[str, str]] = []
        seen: set[str] = set()
        for entry in raw.get("bindings") or []:
            if not isinstance(entry, dict):
                continue
            input_id = _clean_text(entry.get("input_id"), MAX_INPUT_ID)
            action = _clean_text(entry.get("action"), 16)
            if not input_id or action not in VIEWER_ACTIONS:
                continue
            # 한 입력에 두 가지 일을 시킬 수는 없다. 먼저 온 것을 남긴다.
            if input_id in seen:
                continue
            seen.add(input_id)
            bindings.append({
                "input_id": input_id,
                "action": action,
                "dest_path": self._clean_dest(entry.get("dest_path")),
            })
            if len(bindings) >= MAX_BINDINGS:
                break
        return {
            "bindings": bindings,
            "dest_path": self._clean_dest(raw.get("dest_path")),
            "use_session_folder": bool(raw.get("use_session_folder", True)),
            "actions": list(VIEWER_ACTIONS),
            "action_labels": dict(ACTION_LABELS),
        }

    @staticmethod
    def _clean_dest(value: Any) -> str:
        """대상 폴더는 **절대 경로만** 받는다.

        상대 경로를 허용하면 기준이 프로세스의 현재 디렉터리가 되는데, 그게 어디인지는
        실행 방식(포터블/소스/서비스)마다 다르다 — 사용자가 고른 곳이 아닌 데에 파일이
        쌓이게 된다. 앱에서는 폴더 선택 창이 늘 절대 경로를 준다.
        """
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            path = Path(text).expanduser()
        except (OSError, ValueError):
            return ""
        return str(path) if path.is_absolute() else ""

    # ── 실행 ────────────────────────────────────────────────────────────────
    def find_binding(self, input_id: str) -> dict[str, str] | None:
        wanted = _clean_text(input_id, MAX_INPUT_ID)
        if not wanted:
            return None
        for binding in self.load()["bindings"]:
            if binding["input_id"] == wanted:
                return binding
        return None

    def resolve_dest_dir(self, binding: dict[str, str]) -> Path:
        """이 바인딩이 쓸 폴더. 없으면 만든다."""
        settings = self.load()
        raw = binding.get("dest_path") or settings["dest_path"]
        if not raw:
            raise ValueError("대상 폴더가 정해져 있지 않습니다")
        base = Path(raw).expanduser()
        if settings["use_session_folder"]:
            stamp = str(getattr(self.context, "session_timestamp", "") or "")
            if stamp:
                base = base / stamp
        base.mkdir(parents=True, exist_ok=True)
        return base

    def copy_or_move(self, item: Any, binding: dict[str, str]) -> dict[str, Any]:
        """복사/이동. 실제로 옮긴 경로를 돌려준다.

        원본 파일이 없을 수도 있다(Auto Save 를 꺼 두면 그림이 메모리에만 있다).
        그때는 메모리에서 새로 쓴다 — "복사할 게 없다"고 거절하면, 정작 저장을 안 켜 둔
        사람에게 이 기능이 통째로 없는 것과 같아진다.
        """
        dest_dir = self.resolve_dest_dir(binding)
        action = binding["action"]
        source = str(getattr(item, "filepath", "") or "")
        src = Path(source) if source else None

        if src is not None and src.is_file():
            # **제자리 판정이 이름 짓기보다 먼저다.** 순서를 뒤집으면 `_unique` 가
            # "이미 있다"는 이유로 `shot_2.png` 를 내주고, 그 새 이름은 원본과
            # 절대 같아지지 않아 제자리 판정이 영원히 거짓이 된다 — 저장 폴더를
            # 그대로 대상으로 지정하면 누를 때마다 원본이 `_2`, `_3` 으로
            # 이름만 바뀐다(Codex 리뷰 P2).
            plain = dest_dir / src.name
            if plain.exists() and src.resolve() == plain.resolve():
                return {"ok": True, "path": str(plain), "mode": "noop"}
            target = self._unique(plain)
            if action == ACTION_MOVE:
                shutil.move(str(src), str(target))
                # 히스토리가 옛 경로를 가리키면 이후의 저장/삭제가 헛돈다.
                # 그림 자체는 메모리에서 나오므로 화면은 그대로다.
                self._point_at(item, target)
            else:
                shutil.copy2(str(src), str(target))
            return {"ok": True, "path": str(target), "mode": action}

        # 디스크에 원본이 없다 — 메모리에서 쓴다. `move` 는 옮길 것이 없으니 쓰기와 같다.
        from core import result_image_payload_service as result_images

        name = str(getattr(item, "filename", "") or "image.png")
        stem = Path(name).stem or "image"
        image_bytes, media_type = result_images.history_item_image_payload(item)
        suffix = ".webp" if "webp" in str(media_type) else ".png"
        target = self._unique(dest_dir / f"{stem}{suffix}")
        target.write_bytes(image_bytes)
        if action == ACTION_MOVE:
            # 여기서도 항목이 새 파일을 가리켜야 디스크에 원본이 있던 경우와 같아진다.
            # 안 가리키면 이 항목은 계속 '미저장'으로 남아(미저장 판정 = filepath 없음)
            # Save All 이 같은 그림을 한 벌 더 쓰고, 나중에 휴지통 숏컷을 눌러도
            # 방금 만든 파일은 남는다(Codex 리뷰 P2). `copy` 는 그대로 둔다 —
            # 사본을 하나 떠 놓은 것이지 저장한 것이 아니다.
            self._point_at(item, target)
        return {"ok": True, "path": str(target), "mode": "write"}

    @staticmethod
    def _point_at(item: Any, target: Path) -> None:
        try:
            item.filepath = str(target)
        except Exception:
            pass

    @staticmethod
    def _unique(path: Path) -> Path:
        """같은 이름이 있으면 덮어쓰지 않고 번호를 붙인다."""
        if not path.exists():
            return path
        stem, suffix, parent = path.stem, path.suffix, path.parent
        n = 2
        while True:
            candidate = parent / f"{stem}_{n}{suffix}"
            if not candidate.exists():
                return candidate
            n += 1
