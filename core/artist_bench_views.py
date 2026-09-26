# -*- coding: utf-8 -*-
"""Artist bench views — '보기 모드' 하나 = 작가 썸네일을 뽑는 **벤치 설정 한 벌**.

사용자 결정(2026-09-26):
- 보기는 **공용**이다. '앞모습' · '옆모습' · 'nsfw' 를 한 번 만들어 두면 어느 그룹에서든 고른다.
  그룹(관심 작가 그룹 포함)은 **마지막으로 고른 보기만** 기억한다(`group_views`).
- 보기는 비교가 되도록 **조건 전부**를 쥔다 - prefix/postfix/네거티브 · 캐릭터 프롬프트 ·
  해상도 · 생성 설정(믹스 조합과 같은 여섯 키) · 시드(-1 = 매번 랜덤). 보기마다 제 글을 가진다.
- 만들 때 **지금 설정**을 복사해 온다: 글은 지금 PE 프리셋의 prefix/postfix(작가·앵커는 걷고),
  캐릭터는 지금 굴려 둔 스냅숏. 고치는 길은 둘(사용자 지정) - '지금 설정으로 갱신' 과 전용 편집기.
- 그 보기로 뽑은 그림은 작가마다 한 장, `bench_views/<보기>/` 에 산다(서비스가 맡는다).

⚠️ 그룹 파일(`artist_groups.json`)에 넣지 않는다. 그 파일의 `_normalize_group` 은 모르는 키를
   버리고 레코드를 통째로 다시 쓴다 - 옛 판으로 내려간 사용자의 보기 기록이 다음 쓰기에
   사라진다. 그래서 자기 파일, 자기 잠금이다.
⚠️ 못 읽는 파일은 **덮어쓰지 않는다**(그룹 저장소와 같은 규칙) - 읽기가 예외를 올리고 원본은
   그대로 남는다.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from core.artist_mixes import ArtistMixError, _clean_settings

SCHEMA_VERSION = 1
MAX_VIEWS = 50
MAX_NAME_LEN = 40
MAX_TEXT_LEN = 8000
MAX_CHARACTERS = 6
# 캐릭터 프롬프트를 어디서 가져오나(사용자 지정 2026-09-26):
#   main = 생성 순간 **메인 화면의 캐릭터**(보기의 캐릭터 목록은 쓰지 않는다)
#   own  = 보기가 가진 캐릭터만(비어 있으면 캐릭터 없음 - 메인 화면의 캐릭터가 끼어들지 못한다)
# 이 칸이 없던 옛 보기는 own - 그때의 동작 그대로다.
CHARACTER_MODES = ("main", "own")
API_MODES = ("NAI", "WEBUI", "COMFYUI")


class ArtistBenchViewError(ValueError):
    """Bad request against the view store (maps to HTTP 400/404/409)."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ArtistBenchViewError("view name is required")
    if len(name) > MAX_NAME_LEN:
        raise ArtistBenchViewError(f"view name is longer than {MAX_NAME_LEN} characters")
    return name


def _clean_text(value: Any) -> str:
    text = str(value or "")
    if len(text) > MAX_TEXT_LEN:
        raise ArtistBenchViewError(f"text is longer than {MAX_TEXT_LEN} characters")
    return text


def _clean_size(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ArtistBenchViewError(f"invalid {field}") from None
    if not 64 <= number <= 4096 or number % 8:
        raise ArtistBenchViewError(f"invalid {field}: {number}")
    return number


def _clean_seed(value: Any) -> int:
    if value is None or value == "":
        return -1
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ArtistBenchViewError("invalid seed") from None
    if number < -1 or number > 2 ** 32 - 1:
        raise ArtistBenchViewError("invalid seed")
    return number


def _clean_characters(raw: Any) -> list[dict]:
    """캐릭터 프롬프트 슬롯들. 빈 슬롯은 버린다(나가지 않을 칸을 들고 있을 이유가 없다)."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ArtistBenchViewError("characters must be a list")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ArtistBenchViewError("each character must be an object")
        prompt = _clean_text(item.get("prompt")).strip()
        if not prompt:
            continue
        out.append({"prompt": prompt, "uc": _clean_text(item.get("uc")).strip()})
    if len(out) > MAX_CHARACTERS:
        raise ArtistBenchViewError(f"too many characters (max {MAX_CHARACTERS})")
    return out


def clean_spec(raw: Any) -> dict:
    """보기의 **조건** 부분(이름 제외). 만들기·고치기 모두 이것 하나로 거른다."""
    if not isinstance(raw, dict):
        raise ArtistBenchViewError("view spec object is required")
    api_mode = str(raw.get("api_mode") or "").strip().upper()
    if api_mode not in API_MODES:
        raise ArtistBenchViewError(f"api_mode must be one of {list(API_MODES)}")
    try:
        settings = _clean_settings(raw.get("settings"))
    except ArtistMixError as exc:
        raise ArtistBenchViewError(str(exc)) from None
    return {
        "api_mode": api_mode,
        "prefix": _clean_text(raw.get("prefix")),
        "postfix": _clean_text(raw.get("postfix")),
        "negative": _clean_text(raw.get("negative")),
        "characters": _clean_characters(raw.get("characters")),
        "character_mode": (str(raw.get("character_mode") or "own").strip().lower()
                           if str(raw.get("character_mode") or "own").strip().lower() in CHARACTER_MODES else "own"),
        # 어느 PE 프리셋에서 떴는지(보여 주기용 - 조건이 아니다).
        "source_preset": str(raw.get("source_preset") or "").strip()[:200],
        "width": _clean_size(raw.get("width"), "width"),
        "height": _clean_size(raw.get("height"), "height"),
        "settings": settings,
        "seed": _clean_seed(raw.get("seed")),
    }


class ArtistBenchViewStore:
    """Thread-safe owner of ``artist_bench_views.json``."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self.root / "artist_bench_views.json"

    # ── 디스크 ────────────────────────────────────────────────────────────
    def _read(self) -> dict:
        path = self.path
        if not path.exists():
            return {"views": [], "group_views": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 원본을 지키는 것이 우선이다
            raise RuntimeError(f"bench views file is unreadable: {path}: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("views"), list):
            raise RuntimeError(f"bench views file has no 'views' list: {path}")
        views = []
        for raw in data["views"]:
            try:
                vid = str(raw.get("id") or "").strip()
                if not vid:
                    continue
                views.append({"id": vid, "name": _clean_name(raw.get("name")), **clean_spec(raw),
                              "created": int(raw.get("created") or 0), "updated": int(raw.get("updated") or 0)})
            except (ArtistBenchViewError, AttributeError):
                continue      # 한 줄이 상해도 나머지는 산다
        ids = {v["id"] for v in views}
        mapping = data.get("group_views") if isinstance(data.get("group_views"), dict) else {}
        group_views = {str(g): str(v) for g, v in mapping.items() if str(v) in ids}
        return {"views": views, "group_views": group_views}

    def _write(self, data: dict) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": SCHEMA_VERSION, **data}, ensure_ascii=False, indent=2) + "\n"
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        try:
            os.replace(temp_path, path)
        except PermissionError:
            path.write_text(payload, encoding="utf-8")
            try:
                temp_path.unlink(missing_ok=True)
            except PermissionError:
                pass

    # ── 조회 ──────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            return self._read()

    def get(self, view_id: Any) -> dict:
        vid = str(view_id or "").strip()
        for view in self.snapshot()["views"]:
            if view["id"] == vid:
                return view
        raise ArtistBenchViewError(f"view not found: {vid}", status=404)

    @staticmethod
    def _find(data: dict, view_id: Any) -> dict:
        vid = str(view_id or "").strip()
        for view in data["views"]:
            if view["id"] == vid:
                return view
        raise ArtistBenchViewError(f"view not found: {vid}", status=404)

    @staticmethod
    def _name_taken(data: dict, name: str, *, except_id: str = "") -> bool:
        folded = name.casefold()
        return any(v["name"].casefold() == folded and v["id"] != except_id for v in data["views"])

    # ── 바꾸기 ────────────────────────────────────────────────────────────
    def create(self, name: Any, spec: Any) -> dict:
        with self._lock:
            data = self._read()
            clean = _clean_name(name)
            if self._name_taken(data, clean):
                raise ArtistBenchViewError(f"a view named '{clean}' already exists", status=409)
            if len(data["views"]) >= MAX_VIEWS:
                raise ArtistBenchViewError(f"too many views (max {MAX_VIEWS})")
            now = int(time.time())
            view = {"id": f"v_{uuid.uuid4().hex[:12]}", "name": clean, **clean_spec(spec),
                    "created": now, "updated": now}
            data["views"].append(view)
            self._write(data)
            return {"view": view, **data}

    def update(self, view_id: Any, spec: Any) -> dict:
        """조건을 바꾼다. ⚠️ 이미 뽑은 그림은 **옛 조건의 것**이다 - 지우지 않는다(돈이 든 결과다).
        화면이 '조건이 바뀐 뒤 뽑은 것인지' 를 가릴 수 있게 `updated` 를 올린다."""
        with self._lock:
            data = self._read()
            view = self._find(data, view_id)
            view.update(clean_spec(spec))
            view["updated"] = int(time.time())
            self._write(data)
            return {"view": view, **data}

    def rename(self, view_id: Any, name: Any) -> dict:
        with self._lock:
            data = self._read()
            view = self._find(data, view_id)
            clean = _clean_name(name)
            if self._name_taken(data, clean, except_id=view["id"]):
                raise ArtistBenchViewError(f"a view named '{clean}' already exists", status=409)
            view["name"] = clean
            self._write(data)
            return {"view": view, **data}

    def delete(self, view_id: Any) -> dict:
        """기록만 지운다. 그 보기로 뽑은 그림 폴더는 서비스가 판단한다(여기는 파일을 모른다)."""
        with self._lock:
            data = self._read()
            view = self._find(data, view_id)
            data["views"] = [v for v in data["views"] if v["id"] != view["id"]]
            data["group_views"] = {g: v for g, v in data["group_views"].items() if v != view["id"]}
            self._write(data)
            return {"deleted": view["id"], **data}

    def set_group_view(self, group_id: Any, view_id: Any) -> dict:
        """그룹이 고른 보기. 빈 값 = 기본 썸네일(보기 없음)."""
        gid = str(group_id or "").strip()
        if not gid:
            raise ArtistBenchViewError("group id is required")
        with self._lock:
            data = self._read()
            vid = str(view_id or "").strip()
            if vid:
                self._find(data, vid)
                data["group_views"][gid] = vid
            else:
                data["group_views"].pop(gid, None)
            self._write(data)
            return data
