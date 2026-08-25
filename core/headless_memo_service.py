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


# ── 기본 메모 ────────────────────────────────────────────────────────────
# 처음 켰을 때(파일이 아직 없을 때) 심는 메모들. 사용자가 고치거나 지우면 그대로 둔다 -
# 다시 심지 않는다. **`memo.json` 을 지우면 다시 온다** - 되돌리는 길은 그것 하나다.
#
# ⚠️ 여기 있는 것은 사용자 데이터가 아니라 **앱이 들고 다니는 내용**이다. `data/` 가
#    아니라 이 모듈에 두는 이유는 릴리즈 매니페스트가 `core/**` 를 통째로 싣기
#    때문이다 - 데이터 파일로 빼면 매니페스트에 한 줄을 빠뜨리는 순간 조용히 죽는다
#    (이 저장소가 harmony JSON 에서 한 번 밟은 함정).
DEFAULT_NOTES: tuple[tuple[str, str], ...] = (
    ("naiaquality", """퀄리티 태그 (v5)

퀄리티 태그는 생성되는 이미지의 전반적인 품질에 영향을 주는 데 사용되어요. 

best quality (추천)
amazing quality (추천) 
great quality
normal quality
bad quality
worst quality

생성된 이미지를 미적으로 더 보기 좋게, 또는 덜 보기 좋게 만드는 태그들이에요

masterpiece 
very aesthetic (추천)
aesthetic
aesthetic
displeasing
very displeasing

연도태그

year 2026, year 2025, year 2024, ... , year 1980 등. 

작가태그 조합이 어지러울 때

-0.8::artist collaboration :: 같은 태그를 넣어보세요

NAI 공식 퀄리티 태그 (v5) 

standard::  very aesthetic, masterpiece, no text
Light::  very aesthetic, amazing quality, no text"""),
    ("naianegative", """네거티브 (v5)

추천 값이 아니라, Novel AI 공식 홈페이지의 설정값이에요. 

Heavy::  lowres, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, multiple views, logo, too many watermarks, negative space, blank page


Light::  lowres, bad hands, bad anatomy, artistic error, sepia, white haze, worst quality, very displeasing, jpeg artifacts, 0 :: ai-generated ::

Human focus::  lowres, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, multiple views, logo, too many watermarks, negative space, blank page, @_@, mismatched pupils, glowing eyes, bad anatomy"""),
    ("naispecial", """특수 프롬프트 (v5)

depthness - 음영에 깊이감을 더합니다. depth of field의 상위 버전 ? 

low complexity, medium complexity, high complexity, ultra complexity - 모델에 이미지의 복잡도(충실도)를 설명합니다. NAI 권장은 high complexity지만, 신체의 질감이 중요하면 medium complexity 도 좋은 것 같아요. 

meta:novel era - 조금 더 고전적인 느낌을 주게 하는 vibe한 태그래요
meta:golden era - 조금 더 현대적인 느낌을 주게 하는 vibe한 태그래요

visual novel art - 모르겠어요
visual novel bg - 백그라운드에 더 집중해요
visual novel cg - 생성물이 조금 더 깔끔해져요
visual novel chibi - 치비 캐릭터를 어딘가에 박아줘요
visual novel sprite - 미연시의 대사창 같은걸 생각하면 좋을 것 같아요

has alpha - 생성 이미지에 투명도를 부여해요.
"""),
)

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
        seed = False
        try:
            path = self._path()
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                items = raw.get("notes") if isinstance(raw, dict) else None
                for item in (items if isinstance(items, list) else [])[:MAX_NOTES]:
                    note = self._normalize(item)
                    if note:
                        notes.append(note)
            else:
                # 처음 켰다 - 기본 메모를 심는다. ⚠️ **파일이 없을 때만** 심는다.
                #    비어 있는 파일은 "다 지웠다" 는 뜻이라 다시 심으면 안 된다.
                notes = self._seed_notes()
                seed = True
        except Exception as exc:  # noqa: BLE001 - 메모를 못 읽는다고 앱이 멈추면 안 된다
            print(f"[warn] memo load failed: {exc}", flush=True)
        self._notes = notes
        if seed:
            try:
                self._save()
            except Exception as exc:  # noqa: BLE001 - 못 써도 화면에는 보인다
                print(f"[warn] memo seed write failed: {exc}", flush=True)
        return notes

    @staticmethod
    def _seed_notes() -> list[dict[str, Any]]:
        """기본 메모. 목록이 `updated` 내림차순이라 **앞의 것이 위로** 오게 시간을 벌린다."""
        base = _now()
        return [
            {"id": note_id, "body": body, "updated": base - index}
            for index, (note_id, body) in enumerate(DEFAULT_NOTES)
        ]

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
                # 디스크는 건드리지 않는다. ⚠️ 그렇다고 None 을 돌려주면 안 된다 -
                # 모듈 디스패치가 그것을 "지원하지 않는 동작" 으로 읽어
                # `Module parameter is not supported in this runtime.` 을 띄운다.
                state = self.state()
                state["written_id"] = note_id
                return state
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
