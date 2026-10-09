#!/usr/bin/env python3
"""NAI 요청의 총 대기 상한(Connection Lost) 회귀 테스트.

사용자 제보(2026-10-07): NAI 요청이 135초를 넘어도 Connection Lost 로 끝나지 않고 400초 넘게 기다렸다.
`requests` 의 timeout 은 '한 번 읽기' 상한이라 바이트가 조금씩 오면 끝나지 않았고, 실패하면 3회 재시도까지 했다.

가짜 NAI 서버로 call_generation_api 전체 경로를 탄다. 상한은 2초로 줄여서 본다.
- 정상 응답(스트리밍 · 비스트리밍)은 그대로 성공한다.
- 머리가 안 오거나 · 본문이 멎거나 · SSE 프레임이 조금씩 계속 와도 **상한에서** Connection Lost 로 끝난다.
- Connection Lost 는 **재시도하지 않는다**(이미 과금됐을 수 있다) - 서버가 받은 요청은 1건이어야 한다.

사용자 제보(2026-10-09): 그래도 Generate 가 299초 동안 안 풀렸다. 상한이 **시도마다** 새로 시작됐기 때문이다 -
Cloudflare 는 상한보다 먼저(실측 약 125초) HTTP 524 로 끊고, 그 실패는 3회까지 다시 보냈다.
- 524 는 Connection Lost 다 - 다시 보내지 않는다(서버가 받은 요청 1건).
- 다른 실패의 재시도는 **처음 시도부터 잰 상한 안에서만** 한다 - 생성 한 번이 상한을 넘겨 기다리지 않는다.

`python tools/test_nai_request_deadline.py`
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEADLINE_S = 2.0
HANG_S = 20          # 가짜 서버가 멎어 있는 시간 - 상한보다 충분히 길다
LATE_S = 1.5         # 상한 **직전에** 오류로 끝나는 응답(Cloudflare 524 가 이렇게 온다)


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _start_fake_nai(state: dict) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["hits"] += 1
            mode = state["mode"]
            if mode == "no_headers" or (mode == "500_then_hang" and state["hits"] > 1):
                time.sleep(HANG_S)
                return
            if mode in {"late_524", "late_500", "fast_500", "500_then_hang"}:
                if mode.startswith("late_"):
                    time.sleep(LATE_S)
                body = b"<html>origin timed out</html>"
                self.close_connection = True
                self.send_response(524 if mode == "late_524" else 500)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass
                return
            if self.path.endswith("-stream"):
                self._stream(mode)
            else:
                self._zip(mode)

        def _stream(self, mode: str) -> None:
            # 실제 NAI 스트림처럼 다 보내면 연결을 닫는다
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            image = base64.b64encode(_png_bytes()).decode()
            try:
                if mode == "trickle":     # 프레임이 조금씩 계속 온다 - 예전에는 끝없이 기다렸다
                    for step in range(int(HANG_S / 0.25)):
                        event = {"event_type": "intermediate", "step_ix": step, "image": image}
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(0.25)
                    return
                if mode == "stall":
                    time.sleep(HANG_S)
                    return
                event = {"event_type": "final", "image": image}
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
            except OSError:
                pass                      # 클라이언트가 상한에서 끊었다

        def _zip(self, mode: str) -> None:
            if mode == "stall":           # 머리는 왔는데 본문이 멎는다
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", "100000")
                self.end_headers()
                try:
                    self.wfile.write(b"PK")
                    self.wfile.flush()
                    time.sleep(HANG_S)
                except OSError:
                    pass
                return
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("image_0.png", _png_bytes())
            body = archive.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    evidence: dict = {}
    with tempfile.TemporaryDirectory(prefix="naia-nai-deadline-") as user_data:
        os.environ["NAIA_USER_DATA_DIR"] = user_data
        import core.api_service as api_service
        from core.runtime_paths import resolve_runtime_paths
        from core.secure_token_manager import SecureTokenManager
        from core.web_session_context import WebSessionContext

        api_service.NAI_REQUEST_DEADLINE_S = DEADLINE_S
        tokens = SecureTokenManager(resolve_runtime_paths().config_dir / "secure_tokens.json")
        tokens.save_token("nai_token", "pst-test-token")
        context = WebSessionContext(token_manager=tokens)

        state = {"mode": "ok", "hits": 0}
        server = _start_fake_nai(state)
        try:
            service = api_service.APIService(context)
            service.NAI_V3_API_URL = f"http://127.0.0.1:{server.server_port}/ai/generate-image"
            params = {
                "api_mode": "NAI", "input": "1girl", "negative_prompt": "", "model": "NAID4.5F",
                "width": 832, "height": 1216, "steps": 28, "cfg_scale": 5,
                "sampler": "k_euler_ancestral", "seed": 1, "action": "generate",
            }
            # (가짜 서버 모드, 스트리밍, 기대 상태, 걸린 시간 하한, 상한, 서버가 받을 요청 수 상한)
            at_deadline = (DEADLINE_S - 0.2, DEADLINE_S + 3.0, 1)
            cases = [
                ("ok", False, "success", None),
                ("ok", True, "success", None),
                ("no_headers", False, "error", at_deadline),
                ("stall", False, "error", at_deadline),
                ("stall", True, "error", at_deadline),
                ("trickle", True, "error", at_deadline),
                # 상한 직전의 524 - 다시 보내지 않고 거기서 끝난다(예전: 3회 x 1.5초)
                ("late_524", False, "error", (LATE_S - 0.2, DEADLINE_S, 1)),
                ("late_524", True, "error", (LATE_S - 0.2, DEADLINE_S, 1)),
                # 상한 직전의 500 - 쉬고 나면 남은 시간이 없다. 다시 보내지 않고 상한에서 끝난다
                ("late_500", False, "error", (DEADLINE_S - 0.2, DEADLINE_S + 0.7, 1)),
                # 금방 500, 다시 보낸 요청이 멎는다 - 재시도도 **첫 시도부터 잰** 상한에서 끊긴다
                # (시도마다 새로 재면 1.2초 + 2초 = 3.2초가 걸린다)
                ("500_then_hang", False, "error", (DEADLINE_S - 0.2, DEADLINE_S + 0.7, 2)),
            ]
            for mode, stream, expected, bounds in cases:
                state.update(mode=mode, hits=0)
                started = time.monotonic()
                result = service.call_generation_api(
                    dict(params), preview_callback=(lambda *args: None) if stream else None)
                elapsed = time.monotonic() - started
                label = f"{mode}{'_stream' if stream else ''}"
                assert result.get("status") == expected, (label, result)
                if bounds is not None:
                    low, high, max_hits = bounds
                    assert "Connection Lost" in str(result.get("message")), (label, result)
                    # 상한에서 끝난다 - 예전에는 읽기마다 · 시도마다 상한이 다시 시작되고 3회 재시도했다
                    assert low <= elapsed <= high, (label, elapsed)
                    assert 1 <= state["hits"] <= max_hits, (label, "retried", state["hits"])
                evidence[label] = f"{result.get('status')} in {elapsed:.1f}s, requests={state['hits']}"

            # 금방 끝나는 실패의 재시도는 그대로다 - 상한 안이면 3회까지 다시 보낸다
            # (재시도 사이 1초씩 쉬므로 2초 상한으로는 세 번이 안 들어간다 - 이 경우만 상한을 넉넉히)
            api_service.NAI_REQUEST_DEADLINE_S = 30.0
            state.update(mode="fast_500", hits=0)
            started = time.monotonic()
            result = service.call_generation_api(dict(params))
            elapsed = time.monotonic() - started
            assert result.get("status") == "error", result
            assert state["hits"] == 3, ("fast_500", state["hits"])
            assert "HTTP 500" in str(result.get("message")), result
            evidence["fast_500"] = f"error in {elapsed:.1f}s, requests={state['hits']}"
        finally:
            server.shutdown()

    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
