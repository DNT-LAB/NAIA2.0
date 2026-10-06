#!/usr/bin/env python3
"""WEBUI 사용자 제보 두 건의 회귀 테스트.

1. 실제 시드 반영: Seed Fix OFF 면 WEBUI 에 seed=-1 이 나가고 실제 시드는 응답 `info` 로만 온다.
   그 값이 저장 메타(generation_params) · image_meta · 메타데이터 보기에 -1 대신 들어가야 하고,
   화면 동기화용 `executed_seed_sync` 는 **요청 해상도**를 싣고 이번 방송분에만 있어야 한다.
   사용자가 고정한 시드(>=0)는 덮지 않는다.
2. Hiresfix Assist 복원: 끄고 쓰던 사용자가 재시작하면 Assist 가 **꺼진 채로** 돌아와야 한다.
   (예전에는 빈 상태의 기본값 '켜짐' 으로 보고되어, 화면이 hires-fix 를 켜고 Res Preset 을 껐다.)

`python tools/test_webui_seed_and_hiresfix_assist.py`
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REAL_SEED = 3141592653


class _NullTokenStore:
    """토큰 저장소 자리표시자 - 이 테스트는 토큰을 쓰지 않는다."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _start_fake_webui() -> tuple[HTTPServer, dict]:
    """seed=-1 을 받으면 REAL_SEED 를 썼다고 info 로 답하는 가짜 A1111 WebUI."""
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, "PNG")
    image_b64 = base64.b64encode(buffer.getvalue()).decode()
    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send_json(self, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send_json({})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            received["seed"] = payload.get("seed")
            requested = int(payload.get("seed", -1))
            actual = requested if requested >= 0 else REAL_SEED
            info = json.dumps({
                "seed": actual,
                "all_seeds": [actual],
                "infotexts": [f"1girl\nSteps: 20, Seed: {actual}, Size: 1024x1024"],
            })
            self._send_json({"images": [image_b64], "info": info})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


def check_webui_actual_seed(context, evidence: dict) -> None:
    from core.api_service import APIService
    from core.headless_result_service import HeadlessResultStore

    server, received = _start_fake_webui()
    try:
        api = APIService(context)
        base_params = {
            "credential": f"http://127.0.0.1:{server.server_port}",
            "input": "1girl",
            "negative_prompt": "",
            "width": 1024,
            "height": 1024,
            "steps": 20,
            "cfg_scale": 7,
            "sampler": "Euler a",
        }

        # Seed Fix OFF: -1 로 나가고, 실제 시드가 모든 조회면에 들어가야 한다.
        params = {**base_params, "seed": -1}
        api_result = api._call_webui_api(dict(params))
        assert received["seed"] == -1, received
        assert api_result.get("actual_seed") == REAL_SEED, api_result.get("actual_seed")
        store = HeadlessResultStore(max_items=5)
        stored = store.add_api_result(api_result, SimpleNamespace(params=dict(params), source_row=None))
        assert stored.item.generation_params["seed"] == REAL_SEED
        assert stored.image_meta["seed"] == REAL_SEED
        summary = (stored.metadata_payload or {}).get("summary") or {}
        assert summary.get("seed") == REAL_SEED, summary.get("seed")
        sync = stored.image_meta.get("executed_seed_sync")
        assert sync == {"seed": REAL_SEED, "width": 1024, "height": 1024, "interactive_mode_request": False}, sync
        # 화면 동기화 신호는 새 결과 방송분에만 - 재접속 때 다시 만드는 메타에 남으면 시드 박스를 또 덮는다.
        assert "executed_seed_sync" not in store._build_image_meta(store.latest_item)
        assert "executed_seed_sync" not in (stored.metadata_payload or {})
        evidence["seed_fix_off_records_actual_seed"] = True

        # 사용자가 고정한 시드는 그대로 둔다.
        params = {**base_params, "seed": 777}
        api_result = api._call_webui_api(dict(params))
        stored = HeadlessResultStore(max_items=5).add_api_result(
            api_result, SimpleNamespace(params=dict(params), source_row=None))
        assert stored.item.generation_params["seed"] == 777
        assert "executed_seed_sync" not in stored.image_meta
        evidence["pinned_seed_untouched"] = True
    finally:
        server.shutdown()


def check_hiresfix_assist_survives_restart(make_context, evidence: dict) -> None:
    context = make_context()
    context.set_api_mode("WEBUI")
    # 첫 실행 추천 프리셋을 미리 만들어 둔다 - 안 그러면 재시작 때 다시 적용되어 상태를 덮는다.
    context._prompt_engineering_service().ensure_first_run_recommended_preset()
    # 사용자가 Res Preset 을 켰을 때 화면이 보내는 순서 그대로.
    context.set_module_param("webui_hiresfix_assist", "enabled", "false")
    context.set_param("enable_hr", "false")
    context.set_param("resolution_preset_enabled", "true")
    context.set_param("resolution", "1792 x 1216")
    assert context._webui_hiresfix_assist_module_state()["enabled"] is False

    restarted = make_context()
    assert restarted.current_api_mode == "WEBUI"
    state = restarted._webui_hiresfix_assist_module_state()
    assert state["enabled"] is False, state
    assert restarted.remote_params.get("resolution") == "1792 x 1216"
    evidence["assist_off_survives_restart"] = True


def main() -> int:
    evidence: dict = {}
    with tempfile.TemporaryDirectory(prefix="naia-webui-seed-") as user_data:
        os.environ["NAIA_USER_DATA_DIR"] = user_data
        from core.web_session_context import WebSessionContext

        def make_context():
            return WebSessionContext(token_manager=_NullTokenStore())

        check_webui_actual_seed(make_context(), evidence)
        check_hiresfix_assist_survives_restart(make_context, evidence)

    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
