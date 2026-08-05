#!/usr/bin/env python3
"""Focused regression test for selected-history WebP save and batch delete."""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.backend.server import result_display_routes  # noqa: E402
from core.headless_result_service import HeadlessHistoryItem, HeadlessResultStore  # noqa: E402
from core.headless_save_service import HeadlessSaveService  # noqa: E402


def make_item(color: tuple[int, int, int]) -> HeadlessHistoryItem:
    image = Image.new("RGB", (5, 4), color)
    png_buffer = io.BytesIO()
    image.save(png_buffer, format="PNG")
    webp_buffer = io.BytesIO()
    image.save(webp_buffer, format="WEBP", quality=85)
    return HeadlessHistoryItem(
        image=image,
        raw_bytes=png_buffer.getvalue(),
        webp_bytes=webp_buffer.getvalue(),
        generation_params={},
        prompt_context={},
    )


def build_client(store: HeadlessResultStore, save_dir: Path) -> tuple[TestClient, SimpleNamespace]:
    app = FastAPI()
    context = SimpleNamespace(
        result_store=store,
        save_directory_state={
            "base_path": str(save_dir),
            "use_timestamp_folder": False,
            "save_counter": 1,
            "filename_format": "number_only",
            "classification_method": "none",
            "classification_rules": "",
        },
        auto_save_state={"save_as_webp": False},
        session_timestamp="test-session",
        remote_options={},
        save_remote_ui_state=lambda: None,
        auto_save_state_payload=lambda: {"type": "module_state", "module_id": "auto_save"},
        _coerce_bool=lambda value: str(value).lower() in {"1", "true", "yes", "on"} if isinstance(value, str) else bool(value),
        _output_root=lambda: save_dir,
    )
    save_service = HeadlessSaveService(context)
    context._current_save_directory = save_service.current_save_directory
    context.save_history_items = save_service.save_history_items

    async def run_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def broadcast_json(_clients, _payload):
        return None

    result_display_routes.register_result_display_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=set(),
        broadcast_json=broadcast_json,
    )
    return TestClient(app), context


def main() -> int:
    evidence: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="naia-selected-history-test-") as temp_dir:
        save_dir = Path(temp_dir) / "same-result-folder"
        store = HeadlessResultStore(max_items=10)
        first = make_item((255, 0, 0))
        second = make_item((0, 255, 0))
        store._items = [first, second]
        store._set_latest_item(first)

        client, context = build_client(store, save_dir)
        with client:
            # 형식은 **Auto Save 설정을 따른다.** 예전에는 라우트가 WebP 를 강제했는데,
            # 같은 버튼이 상황에 따라 다른 형식으로 저장하면 나중에 파일을 못 찾는다.
            # 스텁은 save_as_webp=False 이므로 PNG 가 나와야 한다.
            assert context.auto_save_state["save_as_webp"] is False
            saved = client.post(
                "/api/history/selected/save",
                json={"paths": [first.rel_path, second.rel_path]},
            )
            assert saved.status_code == 200, saved.text
            saved_payload = saved.json()
            assert saved_payload["ok"] is True, saved_payload
            assert saved_payload["saved"] == 2, saved_payload
            assert saved_payload["format"] == "png", saved_payload
            saved_paths = [Path(value) for value in saved_payload["paths"]]
            assert len(saved_paths) == 2
            assert {path.parent for path in saved_paths} == {save_dir}
            assert all(path.suffix.lower() == ".png" for path in saved_paths)
            for path in saved_paths:
                with Image.open(path) as opened:
                    assert opened.format == "PNG"
            evidence["format_follows_setting"] = saved_payload["format"]
            evidence["same_folder"] = str(save_dir)

            # **이미 저장된 것은 다시 쓰지 않는다.** 가드가 없으면 두 번 누를 때마다
            # 파일이 늘고 원본이 고아로 남는다(병합 전 필수 #1).
            again = client.post(
                "/api/history/selected/save",
                json={"paths": [first.rel_path, second.rel_path]},
            )
            assert again.status_code == 200, again.text
            again_payload = again.json()
            assert again_payload["saved"] == 0, again_payload
            assert again_payload["skipped"] == 2, again_payload
            # 건너뜀은 실패가 아니다 — ok 는 참이어야 한다.
            assert again_payload["ok"] is True, again_payload
            assert not again_payload["failed"], again_payload
            evidence["skip_already_saved"] = again_payload["skipped"]

            # 설정을 WebP 로 바꾸면 그때는 WebP 로 나간다(강제가 아니라 반영).
            third = make_item((0, 0, 255))
            store._items.append(third)
            context.auto_save_state["save_as_webp"] = True
            webp = client.post(
                "/api/history/selected/save",
                json={"paths": [third.rel_path]},
            )
            assert webp.status_code == 200, webp.text
            webp_payload = webp.json()
            assert webp_payload["format"] == "webp", webp_payload
            webp_path = Path(webp_payload["paths"][0])
            assert webp_path.suffix.lower() == ".webp"
            with Image.open(webp_path) as opened:
                assert opened.format == "WEBP"
            context.auto_save_state["save_as_webp"] = False
            evidence["webp_when_setting_on"] = str(webp_path.name)

            traversal = client.post(
                "/api/history/selected/save",
                json={"paths": ["__history_item__/../outside.png"]},
            )
            assert traversal.status_code == 404, traversal.text
            assert traversal.json()["error"] == "invalid history path"
            evidence["path_traversal_blocked"] = True

            second_path = Path(second.filepath)
            history_only = client.post(
                "/api/history/selected/delete",
                json={"paths": [second.rel_path], "keep_file": True},
            )
            assert history_only.status_code == 200, history_only.text
            assert history_only.json()["deleted"] == 1
            assert second_path.is_file(), "history-only delete must retain the saved WebP"
            assert store.get_item(second.history_id) is None
            evidence["history_only_delete_kept_file"] = True

            first_path = Path(first.filepath)
            original_move_to_trash = result_display_routes._move_to_trash

            def fake_move_to_trash(path: Path) -> bool:
                path.unlink()
                return True

            result_display_routes._move_to_trash = fake_move_to_trash
            try:
                disk_delete = client.post(
                    "/api/history/selected/delete",
                    json={"paths": [first.rel_path], "keep_file": False},
                )
            finally:
                result_display_routes._move_to_trash = original_move_to_trash
            assert disk_delete.status_code == 200, disk_delete.text
            assert disk_delete.json()["deleted"] == 1
            assert disk_delete.json()["removed"][0]["trashed"] is True
            assert not first_path.exists()
            assert store.get_item(first.history_id) is None
            evidence["disk_delete_uses_trash_path"] = True

    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
