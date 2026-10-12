"""레퍼런스 인셋 Storage - 사용자가 **명시적으로 저장한** 레퍼런스 그림의 보관함(사용자 지정 2026-10-10).

인셋 칸에 붙여넣은 그림은 앱을 끄면 사라진다. 다시 쓸 것은 인셋 창의 [저장] 으로 여기에 넣어 두고 [Storage] 에서
꺼낸다. 기억하는 것은 **그림뿐**이다 - 배치(경계선 · 그림 자리 · 크기)는 꺼낼 때마다 기본으로 놓인다.

저장소: `<save>/reference_inset/storage/<id>.png` + `thumbs/<id>.jpg`. id = 그림 바이트의 sha1 앞 16자라
같은 그림을 두 번 저장해도 한 장이다.

카테고리(사용자 지시 2026-10-12): **사용자가 만들고 · 이름을 바꾸고 · 지운다**(고정 목록이 없다). 그림 한 장은
한 카테고리에만 든다(폴더처럼) - 없으면 '미분류'다. 카테고리를 지워도 그림은 남고 미분류로 간다.
기록은 `index.json` 한 장: `{"categories": [{"id", "name"}], "items": {"<그림 id>": {"category": "<카테고리 id>"}}}`.
그림 파일은 그대로다 - 색인이 없거나 깨져도 그림은 전부 미분류로 보인다. Assets 의 재사용 자산이 같은 저장소를 본다(계획).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any

STORAGE_DIR_NAME = "reference_inset"
# 그림을 직접 넣어 쌓는 자리가 됐다(2026-10-12) - 200 에서 올렸다.
STORAGE_LIMIT = 500
THUMB_SIDE_PX = 256
_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
INDEX_FILE_NAME = "index.json"
CATEGORY_LIMIT = 40
CATEGORY_NAME_MAX = 24
_CATEGORY_ID_PATTERN = re.compile(r"^c[0-9a-f]{8}$")
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

    # ------------------------------------------------------------------ 색인(카테고리)
    def _read_index(self) -> dict[str, Any]:
        """색인을 읽는다. 없거나 깨졌으면 빈 색인이다 - 그림은 전부 미분류로 보인다."""
        try:
            raw = json.loads((self.root / INDEX_FILE_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        listed = raw.get("categories") if isinstance(raw.get("categories"), list) else []
        placed = raw.get("items") if isinstance(raw.get("items"), dict) else {}
        categories = []
        seen = set()
        for entry in listed:
            if not isinstance(entry, dict):
                continue
            key, name = str(entry.get("id") or ""), str(entry.get("name") or "").strip()
            if _CATEGORY_ID_PATTERN.match(key) and name and key not in seen:
                seen.add(key)
                categories.append({"id": key, "name": name[:CATEGORY_NAME_MAX]})
        items = {}
        for key, entry in placed.items():
            category = str(entry.get("category") or "") if isinstance(entry, dict) else ""
            if _ID_PATTERN.match(str(key)) and category in seen:
                items[str(key)] = {"category": category}
        return {"categories": categories, "items": items}

    def _write_index(self, index: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _write_atomically(
            self.root / INDEX_FILE_NAME,
            json.dumps(index, ensure_ascii=False, indent=1).encode("utf-8"),
        )

    @staticmethod
    def _category_name(name: Any, taken: list[str]) -> str:
        value = " ".join(str(name or "").split())
        if not value:
            raise ValueError("카테고리의 이름을 적어 주세요.")
        if len(value) > CATEGORY_NAME_MAX:
            raise ValueError(f"카테고리의 이름은 {CATEGORY_NAME_MAX}자까지입니다.")
        if value.casefold() in {other.casefold() for other in taken} or value in ("전체", "미분류"):
            raise ValueError("같은 이름의 카테고리가 있습니다.")
        return value

    def categories(self) -> list[dict[str, Any]]:
        """사용자가 만든 카테고리들(만든 차례) - 각자 그림이 몇 장인지와 함께."""
        index = self._read_index()
        present = {path.stem for path in self.root.glob("*.png")} if self.root.is_dir() else set()
        counts: dict[str, int] = {}
        for key, entry in index["items"].items():
            if key in present:
                counts[entry["category"]] = counts.get(entry["category"], 0) + 1
        return [{**category, "count": counts.get(category["id"], 0)} for category in index["categories"]]

    def add_category(self, name: Any) -> dict[str, Any]:
        with _WRITE_LOCK:
            index = self._read_index()
            if len(index["categories"]) >= CATEGORY_LIMIT:
                raise ValueError(f"카테고리는 {CATEGORY_LIMIT}개까지 만들 수 있습니다.")
            category = {"id": "c" + uuid.uuid4().hex[:8],
                        "name": self._category_name(name, [item["name"] for item in index["categories"]])}
            index["categories"].append(category)
            self._write_index(index)
        return category

    def rename_category(self, category_id: Any, name: Any) -> dict[str, Any]:
        key = str(category_id or "")
        with _WRITE_LOCK:
            index = self._read_index()
            target = next((item for item in index["categories"] if item["id"] == key), None)
            if target is None:
                raise FileNotFoundError("그 카테고리가 없습니다.")
            target["name"] = self._category_name(
                name, [item["name"] for item in index["categories"] if item["id"] != key])
            self._write_index(index)
        return dict(target)

    def delete_category(self, category_id: Any) -> bool:
        """카테고리를 지운다. **그림은 지우지 않는다** - 미분류로 간다."""
        key = str(category_id or "")
        with _WRITE_LOCK:
            index = self._read_index()
            kept = [item for item in index["categories"] if item["id"] != key]
            if len(kept) == len(index["categories"]):
                return False
            index["categories"] = kept
            index["items"] = {item: entry for item, entry in index["items"].items() if entry["category"] != key}
            self._write_index(index)
        return True

    def set_category(self, item_id: Any, category_id: Any) -> str:
        """그림 한 장을 카테고리로 옮긴다. 빈 값이면 미분류다. 옮긴 뒤의 카테고리 id 를 돌려준다."""
        checked = self._checked(item_id)
        key = str(category_id or "")
        with _WRITE_LOCK:
            if not self._path(checked).is_file():
                raise FileNotFoundError("저장된 그림을 찾지 못했습니다.")
            self._set_category_locked(checked, key)
        return key

    def _set_category_locked(self, item_id: str, category_id: str) -> None:
        index = self._read_index()
        if category_id and category_id not in {item["id"] for item in index["categories"]}:
            raise FileNotFoundError("그 카테고리가 없습니다.")
        if category_id:
            index["items"][item_id] = {"category": category_id}
        elif item_id in index["items"]:
            del index["items"][item_id]
        else:
            return                      # 이미 미분류다 - 색인을 다시 쓰지 않는다
        self._write_index(index)

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
        placed = self._read_index()["items"]
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
            items.append({"id": path.stem, "width": int(width), "height": int(height), "saved_at": stamp,
                          "category": placed.get(path.stem, {}).get("category", "")})
        items.sort(key=lambda item: item["saved_at"], reverse=True)
        return items

    def save(self, png_bytes: bytes, category: Any = None) -> dict[str, Any]:
        """그림 한 장을 넣는다. 이미 있는 그림이면 그 항목을 돌려준다(두 장이 되지 않는다).

        ``category`` 를 주면 그 카테고리에 넣는다(이미 있는 그림이면 그리로 옮긴다). ``None`` 이면 새 그림은 미분류,
        있던 그림은 있던 자리 그대로다.
        """
        from PIL import Image

        data = bytes(png_bytes or b"")
        if not data:
            raise ValueError("저장할 그림이 없습니다.")
        item_id = self.image_id(data)
        path = self._path(item_id)
        with Image.open(io.BytesIO(data)) as opened:
            width, height = opened.size
        with _WRITE_LOCK:
            if category is not None and str(category or ""):
                # 없는 카테고리에는 넣지 않는다 - 그림을 쓰기 **전에** 거른다.
                if str(category) not in {item["id"] for item in self._read_index()["categories"]}:
                    raise FileNotFoundError("그 카테고리가 없습니다.")
            if not path.is_file():
                # 장수만 센다(치수를 읽으려고 그림을 하나씩 열지 않는다).
                count = sum(1 for other in self.root.glob("*.png") if _ID_PATTERN.match(other.stem)) \
                    if self.root.is_dir() else 0
                if count >= STORAGE_LIMIT:
                    raise ValueError(f"Storage 가 가득 찼습니다({STORAGE_LIMIT}장). 안 쓰는 그림을 지워 주세요.")
                self.root.mkdir(parents=True, exist_ok=True)
                _write_atomically(path, data)
            if category is not None:
                self._set_category_locked(item_id, str(category or ""))
            saved_at = path.stat().st_mtime
            placed = self._read_index()["items"].get(item_id, {}).get("category", "")
        return {"id": item_id, "width": int(width), "height": int(height), "saved_at": saved_at, "category": placed}

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
            index = self._read_index()
            if checked in index["items"]:
                del index["items"][checked]
                self._write_index(index)
        return existed
