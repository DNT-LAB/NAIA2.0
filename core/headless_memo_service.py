"""Memo — 앱 안에서 쓰는 메모장.

프롬프트를 만들다 보면 "다음에 이 조합" · "이 작가는 이 해상도" 같은 것을 적어 둘
곳이 필요한데, 지금까지는 앱 밖(메모장·디스코드)으로 나가야 했다. Tag Search 와
같은 자리·같은 모양으로 붙인다(사용자 지정 2026-08-25).

⚠️ **브라우저가 아니라 서버에 둔다.** LAN 링크로 폰에서 여는 일이 흔해서
   localStorage 에 두면 기기마다 다른 메모가 생긴다. 저장 위치는 사용자 save 루트의
   `memo.json` 하나 - 캐시를 비워도, 다른 기기에서 열어도 같은 것이 보인다.

⚠️ **새 WS 메시지 타입을 만들지 않는다.** 기존 모듈 디스패치(`get_module_state` /
   `set_module_param`)를 그대로 탄다 - 웹 스모크 계약이 메시지 타입을 순서대로 세기
   때문에 타입 하나만 더해도 그 뒤가 전부 밀린다.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

MEMO_FILENAME = "memo.json"
MEMO_VERSION = 1
MAX_NOTES = 300
MAX_BODY_CHARS = 40000
_ID_RE = re.compile(r"^[a-z0-9]{1,32}$")


def _now() -> float:
    return time.time()


def _title_of(body: str) -> str:
    """첫 줄이 제목이다 - 따로 제목 칸을 두면 적으러 들어와서 두 칸을 채워야 한다."""
    for line in str(body or "").splitlines():
        text = line.strip()
        if text:
            return text[:80]
    return ""


class HeadlessMemoService:
    def __init__(self, context: Any):
        self.context = context
        self._notes: list[dict[str, Any]] | None = None

    # ── 저장소 ────────────────────────────────────────────────────────────
    def _path(self) -> Path:
        runtime_paths = getattr(self.context, "runtime_paths", None)
        save_dir = getattr(runtime_paths, "save_dir", None)
        if save_dir is None:
            raise RuntimeError("runtime_paths.save_dir is required for memo storage")
        return Path(save_dir) / MEMO_FILENAME

    def _load(self) -> list[dict[str, Any]]:
        if self._notes is not None:
            return self._notes
        notes: list[dict[str, Any]] = []
        try:
            path = self._path()
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                items = raw.get("notes") if isinstance(raw, dict) else None
                for item in (items if isinstance(items, list) else [])[:MAX_NOTES]:
                    note = self._normalize(item)
                    if note:
                        notes.append(note)
        except Exception as exc:  # noqa: BLE001 - 메모를 못 읽는다고 앱이 멈추면 안 된다
            print(f"[warn] memo load failed: {exc}", flush=True)
        self._notes = notes
        return notes

    def _save(self) -> None:
        notes = self._load()
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": MEMO_VERSION, "notes": notes}
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)

    @staticmethod
    def _normalize(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        note_id = str(raw.get("id") or "").strip().lower()
        if not _ID_RE.fullmatch(note_id):
            return None
        body = str(raw.get("body") or "")[:MAX_BODY_CHARS]
        try:
            updated = float(raw.get("updated") or 0.0)
        except (TypeError, ValueError):
            updated = 0.0
        return {"id": note_id, "body": body, "updated": updated}

    def _new_id(self) -> str:
        used = {note["id"] for note in self._load()}
        # 시각 기반이라 정렬해도 만든 순서를 잃지 않는다. 충돌하면 뒤에 한 글자를 붙인다.
        base = format(int(_now() * 1000), "x")
        candidate = base
        suffix = 0
        while candidate in used:
            suffix += 1
            candidate = f"{base}{suffix:x}"
        return candidate

    # ── 상태 ──────────────────────────────────────────────────────────────
    def state(self) -> dict[str, Any]:
        notes = self._load()
        # 최근에 고친 것이 위로. 적으려고 열었을 때 손이 가는 것은 대개 방금 것이다.
        ordered = sorted(notes, key=lambda note: note.get("updated") or 0.0, reverse=True)
        return {
            "type": "module_state",
            "module_id": "memo",
            "available": True,
            "runtime": "web",
            "notes": [{
                "id": note["id"],
                "title": _title_of(note["body"]),
                "body": note["body"],
                "updated": note["updated"],
            } for note in ordered],
            "note_count": len(ordered),
            "max_notes": MAX_NOTES,
        }

    # ── 동작 ──────────────────────────────────────────────────────────────
    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        payload = value if isinstance(value, dict) else {}
        note_id = str(payload.get("id") or "").strip().lower()
        try:
            if key == "refresh":
                self._notes = None
                return self.state()
            if key == "create":
                body = payload.get("body") if isinstance(value, dict) else value
                return self._create(str(body or ""))
            if key == "write":
                return self._write(note_id, str(payload.get("body") or ""))
            if key == "delete":
                return self._delete(note_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] memo action failed ({key}): {exc}", flush=True)
            return context._toast("메모를 저장하지 못했습니다", level="error")
        return context._toast(f"Memo action is not supported in this runtime: {key}", level="info")

    def _create(self, body: str) -> dict[str, Any]:
        notes = self._load()
        if len(notes) >= MAX_NOTES:
            return self.context._toast(f"메모는 최대 {MAX_NOTES}개까지 둘 수 있습니다", level="error")
        note = {"id": self._new_id(), "body": str(body or "")[:MAX_BODY_CHARS], "updated": _now()}
        notes.append(note)
        self._save()
        state = self.state()
        state["focus_id"] = note["id"]
        return state

    def _write(self, note_id: str, body: str) -> dict[str, Any] | None:
        notes = self._load()
        for note in notes:
            if note["id"] != note_id:
                continue
            clean = str(body or "")[:MAX_BODY_CHARS]
            if note["body"] == clean:
                return None                     # 바뀐 게 없으면 디스크를 건드리지 않는다
            note["body"] = clean
            note["updated"] = _now()
            self._save()
            # ⚠️ 목록만 다시 그리게 두면 **타이핑 중에 커서가 튄다.** 어느 메모를
            #    쓰고 있었는지 함께 알려 화면이 그 칸을 건드리지 않게 한다.
            state = self.state()
            state["written_id"] = note_id
            return state
        return self.context._toast("메모를 찾지 못했습니다", level="error")

    def _delete(self, note_id: str) -> dict[str, Any]:
        notes = self._load()
        remaining = [note for note in notes if note["id"] != note_id]
        if len(remaining) == len(notes):
            return self.context._toast("메모를 찾지 못했습니다", level="error")
        self._notes = remaining
        self._save()
        return self.state()
