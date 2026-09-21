# -*- coding: utf-8 -*-
"""저장된 믹스 조합 — 믹스 띠에 쌓은 작가·가중치·묶음을 이름 붙여 남긴다.

`artist_mixes.json` 으로 따로 산다(`artist_groups.json` 과 같은 폴더, 다른 파일).
그 파일이 왜 자기 파일이어야 하는지는 `core/artist_groups.py` 머리말에 적혀 있고
여기도 같은 이유다 - 레코드 전체를 다시 쓰는 좁은 writer 옆에 얹으면 조용히 지워진다.

## ⚠️ 프리셋에 매달리지 않는다

사용자는 **다른 프리셋에서도** 이 조합을 불러온다(사용자 지정 2026-09-20). 그래서
여기에는 프리셋을 가리키는 것이 하나도 없다. 앵커 아이디는 같은 레코드의
`text` 안 표식만 가리킨다. 아티스트만 복원하면 새로 발급하고, 글도 복원하면
그 내부 참조와 위치를 함께 되살린다.

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

import hashlib
import io
import json
import re
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
MAX_MIXES = 300
MAX_BLOCKS = 400
MAX_NAME_LEN = 40
MAX_ARTIST_LEN = 200
MAX_TEXT_LEN = 20000
WEIGHT_MIN = -5.0
WEIGHT_MAX = 5.0
SLOTS = ("pre", "post")
TEXT_FIELDS = ("pre", "post")
ANCHOR_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MIX_ID = re.compile(r"^[a-f0-9]{12}$")
THUMB_FILE = re.compile(r"^(?:a|main)_[a-f0-9]{24}\.webp$")


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
            **({"id": str(raw["id"])} if ANCHOR_ID.fullmatch(str(raw.get("id", ""))) else {}),
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
    """빈 칸도 복원 대상이다. 두 키를 반드시 남긴다."""
    raw = raw if isinstance(raw, dict) else {}
    return {key: (raw[key][:MAX_TEXT_LEN] if isinstance(raw.get(key), str) else "")
            for key in TEXT_FIELDS}


def _internal_anchors(blocks: list[dict], text: dict) -> None:
    # 짝 없는/중복 아이디는 떼고 구조는 남긴다. 복원 때 그 칸 앞에 새 표식을 넣는다.
    seen = set()
    for block in blocks:
        if block["kind"] != "anchor" or "id" not in block:
            continue
        anchor_id = block["id"]
        if anchor_id in seen or f"<anchor:{anchor_id}>" not in text[block["slot"]]:
            block.pop("id")
        else:
            seen.add(anchor_id)


def _clean_thumbs(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    artists = raw.get("artists") if isinstance(raw.get("artists"), dict) else {}
    return {
        "main": str(raw.get("main") or "") if THUMB_FILE.fullmatch(str(raw.get("main") or "")) else "",
        "fallback": "empty" if raw.get("fallback") == "empty" else "mosaic",
        "artists": {str(a): f for a, f in artists.items() if isinstance(f, str) and THUMB_FILE.fullmatch(f)},
    }


def _webp(payload: bytes, edge: int) -> bytes:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(payload)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, "WEBP", quality=82)
        return output.getvalue()


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
        if not MIX_ID.fullmatch(mix_id):
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
        record["text"] = text
        _internal_anchors(blocks, text)
        record["thumbs"] = _clean_thumbs(raw.get("thumbs"))
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

    @staticmethod
    def _summaries(mixes: list[dict]) -> list[dict]:
        return [{key: mix[key] for key in ("id", "name", "updated", "thumbs")} for mix in mixes]

    def summaries(self) -> list[dict]:
        with self._lock:
            return self._summaries(self._read())

    def one(self, mix_id: Any) -> dict:
        with self._lock:
            return self._find(self._read(), mix_id)

    def _thumb_dir(self, mix_id: str) -> Path:
        if not MIX_ID.fullmatch(mix_id):
            raise ArtistMixError("invalid mix id")
        base = (self.root / "artist_mixes").resolve()
        folder = base / mix_id
        # 심볼릭 링크/정션을 따라 조합 폴더 밖을 읽거나 지우지 않는다.
        if base.parent != self.root.resolve() or folder.resolve().parent != base:
            raise ArtistMixError("invalid thumbnail directory")
        return folder

    @staticmethod
    def _thumb_names(thumbs: dict) -> set[str]:
        return {name for name in [thumbs.get("main"), *thumbs.get("artists", {}).values()] if name}

    def thumbnail(self, mix_id: Any, filename: Any) -> bytes:
        with self._lock:
            record = self._find(self._read(), mix_id)
            # 문법만 통과해도 안 된다. 이 레코드가 실제로 소유하는 파일만 제공한다.
            if filename not in self._thumb_names(record["thumbs"]):
                raise ArtistMixError("thumbnail not found", status=404)
            folder = self._thumb_dir(record["id"])
            path = folder / filename
            if path.resolve().parent != folder.resolve() or not path.is_file():
                raise ArtistMixError("thumbnail not found", status=404)
            return path.read_bytes()

    def _put_thumb(self, mix_id: str, prefix: str, payload: bytes, edge: int) -> str:
        data = _webp(payload, edge)
        # 내용 해시: JSON 쓰기가 실패해도 기존 그림을 덮지 않고, 브라우저 캐시도 정확하다.
        filename = f"{prefix}_{hashlib.sha256(data).hexdigest()[:24]}.webp"
        folder = self._thumb_dir(mix_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / filename
        if path.resolve().parent != folder.resolve():
            raise ArtistMixError("invalid thumbnail path")
        temp = folder / f"{uuid.uuid4().hex}.tmp"
        temp.write_bytes(data)
        os.replace(temp, path)
        return filename

    def _prune_thumbs(self, mix_id: str, keep: set[str]) -> None:
        folder = self._thumb_dir(mix_id)
        if not folder.is_dir():
            return
        for path in folder.iterdir():
            if (path.name not in keep and THUMB_FILE.fullmatch(path.name)
                    and path.resolve().parent == folder.resolve() and path.is_file()):
                path.unlink()
        if not any(folder.iterdir()):
            folder.rmdir()

    # ── 변경 ──────────────────────────────────────────────────────────────
    def save(self, name: Any, blocks: Any, *, text: Any = None, mix_id: Any = None,
             artist_images: dict[str, bytes] | None = None, fallback: str = "mosaic",
             main_image: bytes | None = None) -> dict:
        """새로 만들거나, `mix_id` 가 있으면 그것을 덮어쓴다.

        ⚠️ **같은 이름이 있으면 그 자리를 덮는다.** 이름이 같은 조합이 둘 쌓이면
           목록에서 어느 쪽이 방금 것인지 알 수가 없다 - 저장은 덮어쓰기가 맞고,
           다른 것으로 남기고 싶으면 이름을 달리 적으면 된다.
        """
        clean_name = _clean_name(name)
        clean_blocks = _clean_blocks(blocks)
        clean_text = _clean_text(text)
        _internal_anchors(clean_blocks, clean_text)
        warnings = [f"{key}: {MAX_TEXT_LEN}자까지 저장했습니다. 앵커 위치를 확인하세요."
                    for key in TEXT_FIELDS if isinstance(text, dict)
                    and isinstance(text.get(key), str) and len(text[key]) > MAX_TEXT_LEN]
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
            target["text"] = clean_text
            thumbs = _clean_thumbs({"fallback": fallback})
            for artist, payload in (artist_images or {}).items():
                try:
                    thumbs["artists"][artist] = self._put_thumb(target["id"], "a", payload, 192)
                except (OSError, ValueError) as exc:
                    warnings.append(f"{artist}: 썸네일을 담지 못했습니다 ({exc})")
            if main_image:
                thumbs["main"] = self._put_thumb(target["id"], "main", main_image, 512)
            target["thumbs"] = thumbs
            self._write(mixes)
            self._prune_thumbs(target["id"], self._thumb_names(thumbs))
            return {"mixes": self._summaries(mixes), "id": target["id"], "warnings": warnings}

    def set_main(self, mix_id: Any, *, main_image: bytes | None, fallback: str = "mosaic") -> dict:
        with self._lock:
            mixes = self._read()
            target = self._find(mixes, mix_id)
            thumbs = target["thumbs"]
            thumbs["main"] = self._put_thumb(target["id"], "main", main_image, 512) if main_image else ""
            thumbs["fallback"] = "empty" if fallback == "empty" else "mosaic"
            target["updated"] = int(time.time())
            self._write(mixes)
            self._prune_thumbs(target["id"], self._thumb_names(thumbs))
            return {"mix": target}

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
            return {"mixes": self._summaries(mixes), "id": target["id"]}

    def delete(self, mix_id: Any) -> dict:
        with self._lock:
            mixes = self._read()
            target = self._find(mixes, mix_id)
            mixes = [m for m in mixes if m is not target]
            self._write(mixes)
            self._prune_thumbs(target["id"], set())
            return {"mixes": self._summaries(mixes), "id": target["id"]}
