#!/usr/bin/env python3
"""프리셋 미리보기(/api/prompt-engineering/preset-detail)가 저장된 네거티브를 보여 주는지 확인한다.

사용자 제보(2026-10-08): 퀵 프리셋에 네거티브가 저장되지 않는 것처럼 보였다. 실제로는 저장 · 적용 모두
정상이었고, 미리보기 라우트만 `negative_prompt` 키를 읽었다(저장하는 쪽은 `negative` 키).

- 프리셋을 실제 경로(set_module_param preset_create)로 만들고 라우트가 그 네거티브를 돌려주는지 본다.
- 예전 파일처럼 `negative_prompt` 만 있는 프리셋도 보여야 한다.

`python tools/test_preset_detail_negative.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _NullTokenStore:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


async def _run_in_thread(func, *args, **kwargs):
    return func(*args, **kwargs)


async def _noop(*args, **kwargs):
    return None


def main() -> int:
    evidence: dict = {}
    with tempfile.TemporaryDirectory(prefix="naia-preset-detail-") as user_data:
        os.environ["NAIA_USER_DATA_DIR"] = user_data
        from app.backend.server.prompt_tools_routes import register_prompt_tools_routes
        from core.web_session_context import WebSessionContext

        context = WebSessionContext(token_manager=_NullTokenStore())
        context.set_api_mode("WEBUI")
        context._prompt_engineering_service().ensure_first_run_recommended_preset()

        # 화면이 저장 직전에 보내는 것과 같다: set_prompt(본문 · 네거티브) -> preset_create
        context.prompt_text = "1girl, solo"
        context.negative_prompt_text = "MY_NEGATIVE, lowres"
        context.set_module_param("prompt_engineering", "preset_create", "myquick")

        app = FastAPI()
        register_prompt_tools_routes(
            app, context, run_in_thread=_run_in_thread, clients=set(),
            broadcast_json=_noop, start_generation_runner=_noop,
        )
        client = TestClient(app)

        response = client.get("/api/prompt-engineering/preset-detail", params={"mode": "WEBUI", "name": "myquick"})
        assert response.status_code == 200, response.text
        fields = response.json()["fields"]
        assert fields["negative"] == "MY_NEGATIVE, lowres", fields
        assert fields["main"] == "1girl, solo", fields
        evidence["negative_shown_for_new_preset"] = True

        # 예전 파일: main_settings 에 `negative_prompt` 만 있다
        preset_dir = Path(context.runtime_paths.save_dir) / "presets" / "WEBUI"
        legacy_path = preset_dir / "myquick.json"
        data = json.loads(legacy_path.read_text(encoding="utf-8"))
        main_settings = data["main_settings"]
        main_settings["negative_prompt"] = main_settings.pop("negative")
        (preset_dir / "legacy.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        response = client.get("/api/prompt-engineering/preset-detail", params={"mode": "WEBUI", "name": "legacy"})
        assert response.status_code == 200, response.text
        assert response.json()["fields"]["negative"] == "MY_NEGATIVE, lowres", response.json()
        evidence["legacy_negative_prompt_key_shown"] = True

    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
