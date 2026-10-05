"""기본 스냅샷 - 배포판에 실린 스냅샷을 사용자의 보관함에 **한 번만** 놓는다(사용자 지정 2026-10-05).

묶음은 `app_data_template/snapshots/<모드>/<id>/{snapshot.json, image.webp}` 에 실린다. `<id>` 는 영문 폴더 이름이고
(압축 · 경로 문제를 피한다) 보이는 이름은 `snapshot.json` 의 `name` 이다. `seed_folder` 는 놓을 분류의 이름이다 -
분류 id 는 기계마다 달라 싣지 않는다.

지키는 것
  · **한 번만.** 놓았든 건너뛰었든 `<보관함>/_seeded.json` 에 그 id 를 적는다 - 사용자가 지우면 다시 생기지 않는다.
  · **사용자의 것을 덮지 않는다.** 같은 이름의 스냅샷이 이미 있으면 건너뛴다(적기는 한다).
  · **막지 않는다.** 묶음이 깨졌거나 쓰지 못해도 스냅샷 화면은 그대로 뜬다 - 그 id 는 적지 않아 다음에 다시 해 본다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.snapshot_store import SnapshotStore, sanitize_snapshot_name

TEMPLATE_DIR = ("app_data_template", "snapshots")
SEEDED_MARKER = "_seeded.json"       # `_` 로 시작한다 - 스냅샷 이름이 될 수 없고 목록이 건너뛴다


def _seeded_ids(store: SnapshotStore) -> set[str]:
    try:
        data = json.loads((store.root / SEEDED_MARKER).read_text(encoding="utf-8"))
        rows = data.get("seeded") if isinstance(data, dict) else None
        return {row for row in rows if isinstance(row, str)} if isinstance(rows, list) else set()
    except (OSError, ValueError, TypeError):
        return set()


def seed_default_snapshots(store: SnapshotStore, template_dir: str | Path) -> list[str]:
    """`template_dir`(한 모드의 묶음 폴더) 아래의 기본 스냅샷을 놓는다. 이번에 놓은 이름들을 돌려준다."""
    source = Path(template_dir)
    if not source.is_dir():
        return []
    done = _seeded_ids(store)
    bundles = [entry for entry in sorted(source.iterdir()) if entry.is_dir() and entry.name not in done]
    if not bundles:
        return []
    made: list[str] = []
    marked = set(done)
    store.root.mkdir(parents=True, exist_ok=True)
    for bundle in bundles:
        try:
            data: Any = json.loads((bundle / "snapshot.json").read_text(encoding="utf-8"))
            image = (bundle / "image.webp").read_bytes()
            if not isinstance(data, dict):
                raise ValueError("snapshot.json is not an object")
            name = sanitize_snapshot_name(data.get("name"))
            if not name:
                raise ValueError("invalid snapshot name")
            folder_name = str(data.pop("seed_folder", "") or "").strip()
            if not store.directory(name).exists():
                data["folder"] = store.create_folder(folder_name)["id"] if folder_name else ""
                store.write(name, data, image)
                made.append(name)
            marked.add(bundle.name)
        except Exception as exc:  # noqa: BLE001 - 기본 스냅샷은 덤이다
            print(f"[snapshot] default {ascii(bundle.name)} was not placed: {ascii(exc)}", flush=True)
    if marked != done:
        try:
            store._atomic_json(store.root / SEEDED_MARKER, {"seeded": sorted(marked)})
        except OSError as exc:
            print(f"[snapshot] could not record placed defaults: {ascii(exc)}", flush=True)
    return made
