# -*- coding: utf-8 -*-
"""저장된 믹스 조합 — 믹스 띠에 쌓은 작가·가중치·묶음을 이름 붙여 남긴다.

`artist_mixes.json` 으로 따로 산다(`artist_groups.json` 과 같은 폴더, 다른 파일).
그 파일이 왜 자기 파일이어야 하는지는 `core/artist_groups.py` 머리말에 적혀 있고
여기도 같은 이유다 - 레코드 전체를 다시 쓰는 좁은 writer 옆에 얹으면 조용히 지워진다.

## ⚠️ 프리셋에 매달리지 않는다

사용자는 **다른 프리셋에서도** 이 조합을 불러온다(사용자 지정 2026-09-20). 그래서
여기에는 프리셋을 가리키는 것이 하나도 없다. 특히 **앵커 아이디를 저장하지 않는다** -
`<anchor:3>` 은 *지금 그 글에 박힌 주소*지 조합의 속성이 아니다. 저장하는 것은
**묶음의 구조**(몇 묶음인지 · 각 묶음이 prefix 로 가는지 postfix 로 가는지 ·
가중치 동기화 여부)이고, 표식은 불러올 때 **새로 발급**한다.

## 저장 모양

띠가 들고 있는 **납작한 차례 그대로** 담는다. 앵커도 한 칸을 차지하므로
"첫 앵커 앞 = Artist Prompt" 같은 규칙이 저절로 따라온다 - 화면 모델과 저장 모양이
같으면 한쪽만 고쳐 어긋나는 일이 없다.

    blocks: [
      {"kind": "artist", "artist": "x", "weight": 1.2, "with_prefix": true, "enabled": true},
      {"kind": "anchor", "slot": "pre", "sync": true},
      {"kind": "collab", "weight": -1.0, "enabled": false},
    ]

⚠️ **같은 작가가 두 번 들어갈 수 있다**(사용자 지정 스펙). 그룹 저장소와 달리 여기서는
   절대 합치지 않는다 - 같은 작가를 가중치만 달리해 두 번 쌓는 것이 쓰임새다.
⚠️ `temp`(임시 칸)는 담지 않는다. 그건 고르는 중이라는 표시지 조합의 일부가 아니다 -
   불러오면 고정된 칸으로 선다.

`text` 는 저장 시점의 prefix/postfix 원문이다. **지금은 아무도 안 쓴다** - 2단계에서
"앵커 자리까지 통째로 복원" 을 붙일 때 쓸 자리를 미리 비워 둔 것이다(사용자 지정).
나중에 담기 시작하면 그 전에 저장한 조합은 영영 복원할 수 없으므로 지금부터 담는다.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_MIXES = 300
MAX_BLOCKS = 400
MAX_NAME_LEN = 40
MAX_ARTIST_LEN = 200
MAX_TEXT_LEN = 20000
WEIGHT_MIN = -5.0
WEIGHT_MAX = 5.0
SLOTS = ("pre", "post")
TEXT_FIELDS = ("pre", "post")


class ArtistMixError(ValueError):
    """Bad request against the mix store (maps to HTTP 400/404/409)."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ArtistMixError("mix name is required")
    if len(name) > MAX_NAME_LEN:
        raise ArtistMixError(f"mix name is longer than {MAX_NAME_LEN} characters")
    return name


def _clean_artist(value: Any) -> str:
    # 작가 이름은 이 앱에서 공백을 쓴다. `artist:` 접두어는 서식이라 여기 안 남는다.
    artist = " ".join(str(value or "").split())
    if artist.lower().startswith("artist:"):
        artist = artist[len("artist:"):].strip()
    if not artist or len(artist) > MAX_ARTIST_LEN:
        return ""
    return artist


def _clean_weight(value: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return round(max(WEIGHT_MIN, min(WEIGHT_MAX, number)), 2)


def _clean_block(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "artist").strip()
    if kind == "anchor":
        slot = str(raw.get("slot") or "pre").strip()
        return {
            "kind": "anchor",
            "slot": slot if slot in SLOTS else "pre",
            "sync": bool(raw.get("sync")),
        }
    if kind == "collab":
        # 이름도 `with_prefix` 도 화면이 쥐고 있는 고정값이다 - 여기선 상태만 담는다.
        return {
            "kind": "collab",
            "weight": _clean_weight(raw.get("weight"), -1.0),
            "enabled": bool(raw.get("enabled")),
        }
    artist = _clean_artist(raw.get("artist"))
    if not artist:
        return None
    return {
        "kind": "artist",
        "artist": artist,
        "weight": _clean_weight(raw.get("weight")),
        # 없으면 붙이는 쪽이 기본이다(띠가 만드는 칸의 기본값과 같다).
        "with_prefix": raw.get("with_prefix", True) is not False,
        "enabled": raw.get("enabled", True) is not False,
    }


def _clean_blocks(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        raise ArtistMixError("blocks list is required")
    blocks = [b for b in (_clean_block(item) for item in raw) if b]
    # ⚠️ 작가가 하나도 없으면 조합이 아니다. 앵커만 남은 레코드를 불러오면 사용자는
    #    "빈 것이 저장됐다" 를 보게 된다 - 저장 자체를 막는 편이 친절하다.
    if not any(b["kind"] == "artist" for b in blocks):
        raise ArtistMixError("a mix needs at least one artist")
    return blocks[:MAX_BLOCKS]


def _clean_text(raw: Any) -> dict:
    """저장 시점의 prefix/postfix 원문. 2단계(자리까지 복원)가 쓸 자리다."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in TEXT_FIELDS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value[:MAX_TEXT_LEN]
    return out


class ArtistMixStore:
    """Thread-safe owner of ``artist_mixes.json``. Every mutation returns the full list."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._lock = threading.RLock()

    # ── 디스크 ────────────────────────────────────────────────────────────
    @property
    def path(self) -> Path:
        return self.root / "artist_mixes.json"

    def _read(self) -> list[dict]:
        path = self.path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 원본을 지키는 것이 우선이다
            raise RuntimeError(f"artist mixes file is unreadable: {path}: {exc}") from exc
        mixes = data.get("mixes") if isinstance(data, dict) else None
        if not isinstance(mixes, list):
            raise RuntimeError(f"artist mixes file has no 'mixes' list: {path}")
        return [m for m in (self._normalize(raw) for raw in mixes) if m]

    def _write(self, mixes: list[dict]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": SCHEMA_VERSION, "mixes": mixes},
                             ensure_ascii=False, indent=2) + "\n"
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        try:
            os.replace(temp_path, path)
        except PermissionError:
            # 백신·색인기가 잠깐 쥐고 있는 경우 - 이웃 저장소와 같은 퇴로.
            path.write_text(payload, encoding="utf-8")
            try:
                temp_path.unlink(missing_ok=True)
            except PermissionError:
                pass

    @staticmethod
    def _normalize(raw: Any) -> dict | None:
        if not isinstance(raw, dict):
            return None
        mix_id = str(raw.get("id") or "").strip()
        if not mix_id:
            return None
        try:
            name = _clean_name(raw.get("name"))
            blocks = _clean_blocks(raw.get("blocks"))
        except ArtistMixError:
            return None
        now = int(time.time())
        record = {
            "id": mix_id,
            "name": name,
            "blocks": blocks,
            "created": int(raw.get("created") or now),
            "updated": int(raw.get("updated") or now),
        }
        text = _clean_text(raw.get("text"))
        if text:
            record["text"] = text
        return record

    # ── 조회 ──────────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        with self._lock:
            return self._read()

    @staticmethod
    def _find(mixes: list[dict], mix_id: Any) -> dict:
        key = str(mix_id or "").strip()
        for mix in mixes:
            if mix["id"] == key:
                return mix
        raise ArtistMixError(f"mix not found: {key}", status=404)

    # ── 변경 ──────────────────────────────────────────────────────────────
    def save(self, name: Any, blocks: Any, *, text: Any = None, mix_id: Any = None) -> dict:
        """새로 만들거나, `mix_id` 가 있으면 그것을 덮어쓴다.

        ⚠️ **같은 이름이 있으면 그 자리를 덮는다.** 이름이 같은 조합이 둘 쌓이면
           목록에서 어느 쪽이 방금 것인지 알 수가 없다 - 저장은 덮어쓰기가 맞고,
           다른 것으로 남기고 싶으면 이름을 달리 적으면 된다.
        """
        clean_name = _clean_name(name)
        clean_blocks = _clean_blocks(blocks)
        clean_text = _clean_text(text)
        now = int(time.time())
        with self._lock:
            mixes = self._read()
            target = None
            if mix_id:
                target = self._find(mixes, mix_id)
            else:
                key = clean_name.casefold()
                target = next((m for m in mixes if m["name"].casefold() == key), None)
            if target is None:
                if len(mixes) >= MAX_MIXES:
                    raise ArtistMixError(f"too many mixes (max {MAX_MIXES})")
                target = {"id": uuid.uuid4().hex[:12], "created": now}
                mixes.append(target)
            target["name"] = clean_name
            target["blocks"] = clean_blocks
            target["updated"] = now
            if clean_text:
                target["text"] = clean_text
            else:
                target.pop("text", None)
            self._write(mixes)
            return {"mixes": mixes, "id": target["id"]}

    def rename(self, mix_id: Any, name: Any) -> dict:
        clean_name = _clean_name(name)
        with self._lock:
            mixes = self._read()
            target = self._find(mixes, mix_id)
            key = clean_name.casefold()
            if any(m is not target and m["name"].casefold() == key for m in mixes):
                raise ArtistMixError(f"a mix named '{clean_name}' already exists", status=409)
            target["name"] = clean_name
            target["updated"] = int(time.time())
            self._write(mixes)
            return {"mixes": mixes, "id": target["id"]}

    def delete(self, mix_id: Any) -> dict:
        with self._lock:
            mixes = self._read()
            target = self._find(mixes, mix_id)
            mixes = [m for m in mixes if m is not target]
            self._write(mixes)
            return {"mixes": mixes, "id": target["id"]}
