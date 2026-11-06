"""Codex release review 2026-11-06 fixes: H1 URL credentials masked, M3 access broadcast sent once.

M1 (empty preset negative) lives in tests/test_inpaint_prompt_swap.py with the swap fixtures.
Run: python tools/test_release_review_fixes.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backend.server.api_control_commands import _broadcast_access  # noqa: E402
from core.agent_cli import redact  # noqa: E402
from core.agent_protocol import AgentReplySocket, mask_url_credentials, sanitize, secret_values  # noqa: E402


class FakeSocket:
    def __init__(self, host="127.0.0.1"):
        self.sent = []
        self.client = SimpleNamespace(host=host)

    async def send_text(self, text):
        self.sent.append(json.loads(text))


class FakeContext:
    prompt_text = "p"
    negative_prompt_text = "n"

    def api_status_payload(self, host):
        return {"type": "api_status", "host": host}

    def get_api_mode(self):
        return "WEBUI"

    def generation_param_schema_payload(self):
        return {"type": "schema"}


class UrlCredentialTests(unittest.TestCase):
    def test_userinfo_and_token_query_masked(self):
        text = "connect failed: https://alice:pw123@host.example:7860/sdapi?token=FAKE999&mode=x"
        masked = mask_url_credentials(text)
        self.assertNotIn("pw123", masked)
        self.assertNotIn("FAKE999", masked)
        self.assertIn("host.example:7860", masked)
        self.assertIn("mode=x", masked)

    def test_plain_local_address_untouched(self):
        text = "WebUI at http://127.0.0.1:7860/?page=2 is down"
        self.assertEqual(mask_url_credentials(text), text)

    def test_sanitize_and_cli_redact_mask_nested_strings(self):
        payload = {"error": ["bad http://u:sekret@h:1/?api_key=K1"]}
        for out in (sanitize(payload), redact(payload, [])):
            dumped = json.dumps(out)
            self.assertNotIn("sekret", dumped)
            self.assertNotIn("K1", dumped)

    def test_command_url_parts_become_secrets(self):
        # 서버가 주소를 다른 모양으로 되돌려 줘도(조각만) 가린다.
        secrets = secret_values({"type": "set_webui_url", "url": "http://bob:hunter2@h:7860/?auth=Z9"})
        self.assertIn("bob:hunter2", secrets)
        self.assertIn("Z9", secrets)
        self.assertEqual(sanitize("user was bob:hunter2", secrets), "user was [REDACTED]")


class AccessBroadcastTests(unittest.TestCase):
    def test_agent_requester_gets_one_wrapped_copy_and_others_still_receive(self):
        raw, other = FakeSocket(), FakeSocket("10.0.0.2")
        wrapped = AgentReplySocket(raw, "call1", SimpleNamespace(), {"type": "set_no_api"})
        asyncio.run(_broadcast_access(FakeContext(), wrapped, {raw, other}, "127.0.0.1"))
        self.assertEqual(len(raw.sent), 4)
        self.assertTrue(all(msg.get("_agent_call_id") == "call1" for msg in raw.sent))
        self.assertEqual(len(other.sent), 4)
        self.assertTrue(all("_agent_call_id" not in msg for msg in other.sent))
        self.assertEqual(other.sent[0]["host"], "10.0.0.2")

    def test_browser_requester_unchanged(self):
        raw, other = FakeSocket(), FakeSocket()
        asyncio.run(_broadcast_access(FakeContext(), raw, {raw, other}, "127.0.0.1"))
        self.assertEqual((len(raw.sent), len(other.sent)), (4, 4))


if __name__ == "__main__":
    unittest.main(verbosity=2)
