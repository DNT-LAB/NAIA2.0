"""레퍼런스 인셋 Storage - 사용자가 **명시적으로 저장한** 레퍼런스 그림의 보관함(사용자 지정 2026-10-10).

인셋 칸에 붙여넣은 그림은 앱을 끄면 사라진다. 다시 쓸 것은 인셋 창의 [저장] 으로 여기에 넣어 두고 [Storage] 에서
꺼낸다. 기억하는 것은 **그림뿐**이다 - 배치(경계선 · 그림 자리 · 크기)는 꺼낼 때마다 기본으로 놓인다.

저장소: `<save>/reference_inset/storage/<id>.png` + `thumbs/<id>.jpg`. id = 그림 바이트의 sha1 앞 16자라
같은 그림을 두 번 저장해도 한 장이다.
"""
from __future__ import annotations

import hashlib
import io
import re
import threading
import uuid
from pathlib import Path
from typing import Any

STORAGE_DIR_NAME = "reference_inset"
STORAGE_LIMIT = 200
THUMB_SIDE_PX = 256
_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
# 저장 · 지우기는 한 번에 하나만(프로세스 하나에 저장소도 하나다). 안 잠그면 한계 검사와 쓰기 사이에 다른 저장이
# 끼어 한계를 넘고, 같은 그림을 동시에 저장하면 한쪽의 임시 파일을 다른 쪽이 먼저 옮겨 실패한다(Codex 리뷰 2026-10-10).
_WRITE_LOCK = threading.Lock()


def _write_atomically(target: Path, data: bytes) -> None:
    """요청마다 다른 임시 파일에 쓴 뒤 옮긴다 - 쓰다 만 파일이 그림으로 읽히지 않게."""
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(target)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


class ReferenceInsetStorage:
    def __init__(self, root: Path):
        self.root = Path(root) / "storage"
        self.thumbs = self.root / "thumbs"

    @staticmethod
    def image_id(png_bytes: bytes) -> str:
        return hashlib.sha1(bytes(png_bytes)).hexdigest()[:16]

    @staticmethod
    def _checked(item_id: Any) -> str:
        value = str(item_id or "").strip().lower()
        if not _ID_PATTERN.match(value):
            raise ValueError("저장된 그림의 id 가 올바르지 않습니다.")
        return value

    def _path(self, item_id: str) -> Path:
        return self.root / f"{item_id}.png"

    def has(self, item_id: Any) -> bool:
        try:
            return self._path(self._checked(item_id)).is_file()
        except ValueError:
            return False

    def list(self) -> list[dict[str, Any]]:
        """저장한 그림들, 최근에 저장한 것부터."""
        from PIL import Image

        if not self.root.is_dir():
            return []
        items = []
        for path in self.root.glob("*.png"):
            if not _ID_PATTERN.match(path.stem):
                continue
            try:
                with Image.open(path) as opened:      # 머리만 읽는다 - 치수를 알려고 그림을 풀지 않는다
                    width, height = opened.size
                stamp = path.stat().st_mtime
            except Exception:      # noqa: BLE001 - 깨진 한 장이 목록을 막지 않는다
                continue
            items.append({"id": path.stem, "width": int(width), "height": int(height), "saved_at": stamp})
        items.sort(key=lambda item: item["saved_at"], reverse=True)
        return items

    def save(self, png_bytes: bytes) -> dict[str, Any]:
        """그림 한 장을 넣는다. 이미 있는 그림이면 그 항목을 돌려준다(두 장이 되지 않는다)."""
        from PIL import Image

        data = bytes(png_bytes or b"")
        if not data:
            raise ValueError("저장할 그림이 없습니다.")
        item_id = self.image_id(data)
        path = self._path(item_id)
        with Image.open(io.BytesIO(data)) as opened:
            width, height = opened.size
        with _WRITE_LOCK:
            if not path.is_file():
                if len(self.list()) >= STORAGE_LIMIT:
                    raise ValueError(f"Storage 가 가득 찼습니다({STORAGE_LIMIT}장). 안 쓰는 그림을 지워 주세요.")
                self.root.mkdir(parents=True, exist_ok=True)
                _write_atomically(path, data)
            saved_at = path.stat().st_mtime
        return {"id": item_id, "width": int(width), "height": int(height), "saved_at": saved_at}

    def read(self, item_id: Any) -> bytes:
        path = self._path(self._checked(item_id))
        if not path.is_file():
            raise FileNotFoundError("저장된 그림을 찾지 못했습니다.")
        return path.read_bytes()

    def thumb(self, item_id: Any) -> bytes:
        """목록에 놓을 작은 그림(JPEG). 없으면 그 자리에서 만들어 둔다."""
        from PIL import Image

        checked = self._checked(item_id)
        target = self.thumbs / f"{checked}.jpg"
        if target.is_file():
            return target.read_bytes()
        with Image.open(io.BytesIO(self.read(checked))) as opened:
            image = opened.convert("RGB")
            image.thumbnail((THUMB_SIDE_PX, THUMB_SIDE_PX), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
        data = buffer.getvalue()
        try:
            with _WRITE_LOCK:
                # 만드는 사이에 지워졌으면 작은 그림을 남기지 않는다(주인 없는 파일이 된다).
                if self._path(checked).is_file():
                    self.thumbs.mkdir(parents=True, exist_ok=True)
                    _write_atomically(target, data)
        except OSError:      # 못 적어도 이번 응답은 준다
            pass
        return data

    def delete(self, item_id: Any) -> bool:
        checked = self._checked(item_id)
        path = self._path(checked)
        with _WRITE_LOCK:
            existed = path.is_file()
            for target in (path, self.thumbs / f"{checked}.jpg"):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
        return existed
