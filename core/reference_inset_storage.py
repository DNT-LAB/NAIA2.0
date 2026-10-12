"""레퍼런스 인셋 Storage - 사용자가 **명시적으로 저장한** 레퍼런스 그림의 보관함(사용자 지정 2026-10-10).

인셋 칸에 붙여넣은 그림은 앱을 끄면 사라진다. 다시 쓸 것은 인셋 창의 [저장] 으로 여기에 넣어 두고 [Storage] 에서
꺼낸다. 기억하는 것은 **그림뿐**이다 - 배치(경계선 · 그림 자리 · 크기)는 꺼낼 때마다 기본으로 놓인다.

저장소: `<save>/reference_inset/storage/<id>.png` + `thumbs/<id>.jpg`. id = 그림 바이트의 sha1 앞 16자라
같은 그림을 두 번 저장해도 한 장이다.

카테고리(사용자 지시 2026-10-12): **사용자가 만들고 · 이름을 바꾸고 · 지운다**(고정 목록이 없다). 그림 한 장은
한 카테고리에만 든다(폴더처럼) - 없으면 '미분류'다. 카테고리를 지워도 그림은 남고 미분류로 간다.
기록은 `index.json` 한 장:
`{"categories": [{"id", "name"}], "items": {"<그림 id>": {"category", "name", "width", "height"}}}`.
그림 파일은 그대로다 - 색인이 없거나 깨져도 그림은 전부 미분류로 보인다. Assets 의 재사용 자산이 같은 저장소를 본다(계획).

장수의 한도는 없다(사용자 지시 2026-10-12 - 그림을 쌓아 두는 자리다). 그래서 **목록은 그림을 열지 않는다**:
치수와 이름은 색인에 적어 두고, 목록은 폴더를 한 번 훑을 뿐이다. 색인에 치수가 없는 그림(예전에 넣은 것 · 폴더에
직접 넣은 것)만 그때 한 번 머리를 읽어 색인에 채운다. 화면은 이름으로 먼저 거르고, 그림은 보일 때 받아 간다.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

STORAGE_DIR_NAME = "reference_inset"
THUMB_SIDE_PX = 256
_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
INDEX_FILE_NAME = "index.json"
CATEGORY_LIMIT = 40
CATEGORY_NAME_MAX = 24
ITEM_NAME_MAX = 80
_CATEGORY_ID_PATTERN = re.compile(r"^c[0-9a-f]{8}$")
# 저장 · 지우기는 한 번에 하나만(프로세스 하나에 저장소도 하나다). 안 잠그면 같은 그림을 동시에 저장할 때 한쪽의
# 임시 파일을 다른 쪽이 먼저 옮겨 실패하고, 색인을 읽고 쓰는 사이에 다른 쓰기가 끼면 그 쓰기가 사라진다(Codex 리뷰 2026-10-10).
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


def clean_item_name(name: Any) -> str:
    """그림의 이름: 파일 이름에서 왔으면 확장자를 떼고, 공백을 한 칸으로 줄이고, 길이를 자른다. 없으면 빈 문자열."""
    value = " ".join(str(name or "").split())
    value = re.sub(r"\.(png|jpe?g|webp|gif|bmp|avif|tiff?)$", "", value, flags=re.IGNORECASE)
    return value[:ITEM_NAME_MAX].strip()


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

    def _present(self) -> dict[str, float]:
        """폴더에 있는 그림들 `{id: 저장한 때}`. 폴더를 한 번 훑을 뿐이다 - 그림을 열지 않는다."""
        found: dict[str, float] = {}
        try:
            with os.scandir(self.root) as entries:
                for entry in entries:
                    stem, dot, suffix = entry.name.rpartition(".")
                    if dot and suffix == "png" and _ID_PATTERN.match(stem):
                        try:
                            if entry.is_file():
                                found[stem] = entry.stat().st_mtime
                        except OSError:
                            continue
        except OSError:
            return {}
        return found

    # ------------------------------------------------------------------ 색인(카테고리 · 이름 · 치수)
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
        items: dict[str, dict[str, Any]] = {}
        for key, entry in placed.items():
            if not _ID_PATTERN.match(str(key)) or not isinstance(entry, dict):
                continue
            record: dict[str, Any] = {}
            category = str(entry.get("category") or "")
            if category in seen:
                record["category"] = category
            name = clean_item_name(entry.get("name"))
            if name:
                record["name"] = name
            try:
                width, height = int(entry.get("width") or 0), int(entry.get("height") or 0)
            except (TypeError, ValueError):
                width = height = 0
            if width > 0 and height > 0:
                record["width"], record["height"] = width, height
            if record:
                items[str(key)] = record
        return {"categories": categories, "items": items}

    def _write_index(self, index: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _write_atomically(
            self.root / INDEX_FILE_NAME,
            json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
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
        present = self._present()
        counts: dict[str, int] = {}
        for key, entry in index["items"].items():
            category = entry.get("category")
            if category and key in present:
                counts[category] = counts.get(category, 0) + 1
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
        """카테고리를 지운다. **그림은 지우지 않는다** - 미분류로 간다(이름 · 치수는 남는다)."""
        key = str(category_id or "")
        with _WRITE_LOCK:
            index = self._read_index()
            kept = [item for item in index["categories"] if item["id"] != key]
            if len(kept) == len(index["categories"]):
                return False
            index["categories"] = kept
            for entry in index["items"].values():
                if entry.get("category") == key:
                    del entry["category"]
            index["items"] = {item: entry for item, entry in index["items"].items() if entry}
            self._write_index(index)
        return True

    def set_category(self, item_id: Any, category_id: Any) -> str:
        """그림 한 장을 카테고리로 옮긴다. 빈 값이면 미분류다. 옮긴 뒤의 카테고리 id 를 돌려준다."""
        checked = self._checked(item_id)
        key = str(category_id or "")
        with _WRITE_LOCK:
            if not self._path(checked).is_file():
                raise FileNotFoundError("저장된 그림을 찾지 못했습니다.")
            index = self._read_index()
            if self._place(index, checked, category=key):
                self._write_index(index)
        return key

    def rename(self, item_id: Any, name: Any) -> str:
        """그림의 이름을 바꾼다(빈 값이면 이름을 지운다). 정리된 이름을 돌려준다."""
        checked = self._checked(item_id)
        with _WRITE_LOCK:
            if not self._path(checked).is_file():
                raise FileNotFoundError("저장된 그림을 찾지 못했습니다.")
            index = self._read_index()
            cleaned = clean_item_name(name)
            if self._place(index, checked, name=cleaned):
                self._write_index(index)
        return cleaned

    @staticmethod
    def _place(index: dict[str, Any], item_id: str, *, category: str | None = None, name: str | None = None,
               size: tuple[int, int] | None = None) -> bool:
        """색인의 한 그림을 고친다(준 것만). 바뀐 것이 있으면 True - 없으면 색인을 다시 쓰지 않는다."""
        if category and category not in {item["id"] for item in index["categories"]}:
            raise FileNotFoundError("그 카테고리가 없습니다.")
        entry = dict(index["items"].get(item_id, {}))
        before = dict(entry)
        if category is not None:
            if category:
                entry["category"] = category
            else:
                entry.pop("category", None)
        if name is not None:
            if name:
                entry["name"] = name
            else:
                entry.pop("name", None)
        if size is not None and size[0] > 0 and size[1] > 0:
            entry["width"], entry["height"] = int(size[0]), int(size[1])
        if entry == before:
            return False
        if entry:
            index["items"][item_id] = entry
        else:
            index["items"].pop(item_id, None)
        return True

    def has(self, item_id: Any) -> bool:
        try:
            return self._path(self._checked(item_id)).is_file()
        except ValueError:
            return False

    def list(self) -> list[dict[str, Any]]:
        """저장한 그림들, 최근에 저장한 것부터. **그림을 열지 않는다** - 치수 · 이름은 색인에서 온다.

        색인에 치수가 없는 그림(예전에 넣은 것 · 폴더에 직접 넣은 것)만 여기서 한 번 머리를 읽어 색인에 채운다.
        """
        from PIL import Image

        present = self._present()
        if not present:
            return []
        placed = self._read_index()["items"]
        unknown = [key for key in present if "width" not in placed.get(key, {})]
        measured: dict[str, tuple[int, int]] = {}
        for key in unknown:
            try:
                with Image.open(self._path(key)) as opened:      # 머리만 읽는다 - 그림을 풀지 않는다
                    measured[key] = (int(opened.size[0]), int(opened.size[1]))
            except Exception:      # noqa: BLE001 - 깨진 한 장이 목록을 막지 않는다(목록에서 빠진다)
                continue
        if measured:
            with _WRITE_LOCK:
                index = self._read_index()
                changed = [self._place(index, key, size=size) for key, size in measured.items()]
                if any(changed):
                    try:
                        self._write_index(index)
                    except OSError:      # 못 적어도 이번 목록은 준다(다음에 다시 잰다)
                        pass
                placed = index["items"]
        items = []
        for key, stamp in present.items():
            entry = placed.get(key, {})
            size = (entry.get("width"), entry.get("height")) if "width" in entry else measured.get(key)
            if not size:
                continue                                           # 열리지 않는 파일이다
            items.append({"id": key, "width": int(size[0]), "height": int(size[1]), "saved_at": stamp,
                          "category": entry.get("category", ""), "name": entry.get("name", "")})
        items.sort(key=lambda item: item["saved_at"], reverse=True)
        return items

    def save(self, png_bytes: bytes, category: Any = None, name: Any = None) -> dict[str, Any]:
        """그림 한 장을 넣는다. 이미 있는 그림이면 그 항목을 돌려준다(두 장이 되지 않는다).

        ``category`` 를 주면 그 카테고리에 넣는다(이미 있는 그림이면 그리로 옮긴다). ``None`` 이면 새 그림은 미분류,
        있던 그림은 있던 자리 그대로다. ``name`` 은 이름이 아직 없는 그림에만 붙는다(붙여 둔 이름을 덮지 않는다).
        """
        from PIL import Image

        data = bytes(png_bytes or b"")
        if not data:
            raise ValueError("저장할 그림이 없습니다.")
        item_id = self.image_id(data)
        path = self._path(item_id)
        with Image.open(io.BytesIO(data)) as opened:
            width, height = opened.size
        wanted = None if category is None else str(category or "")
        label = clean_item_name(name)
        with _WRITE_LOCK:
            index = self._read_index()
            keeps_name = bool(index["items"].get(item_id, {}).get("name"))
            # 없는 카테고리에는 넣지 않는다 - 그림을 쓰기 **전에** 거른다(`_place` 가 던진다).
            changed = self._place(index, item_id, category=wanted, size=(int(width), int(height)),
                                  name=None if keeps_name or not label else label)
            if not path.is_file():
                self.root.mkdir(parents=True, exist_ok=True)
                _write_atomically(path, data)
            if changed:
                self._write_index(index)
            saved_at = path.stat().st_mtime
            entry = index["items"].get(item_id, {})
        return {"id": item_id, "width": int(width), "height": int(height), "saved_at": saved_at,
                "category": entry.get("category", ""), "name": entry.get("name", "")}

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
