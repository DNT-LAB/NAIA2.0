"""Agent CLI set_prompt: a field the agent did not send is preserved, and open tabs receive the change.

Browser set_prompt (always both fields) keeps its old meaning: a missing field is stored as "".
Run: python tools/test_agent_set_prompt.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backend.server.session_commands import handle_session_command  # noqa: E402
from core.agent_protocol import AgentReplySocket  # noqa: E402


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


class FakeContext:
    def __init__(self):
        self.prompt_text = "1girl, solo"
        self.negative_prompt_text = "lowres, bad hands"
        self.preset_syncs = []

    def stale_prompt_edit(self, origin, preset):
        return False

    def save_remote_ui_state(self):
        return {}

    def sync_negative_into_current_preset(self):
        self.preset_syncs.append("negative")

    def sync_prompt_into_current_preset(self, preset):
        self.preset_syncs.append("prompt")


def run(ws, context, command, broadcasts):
    async def broadcast_json(clients, payload):
        broadcasts.append(dict(payload))

    async def run_in_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    return asyncio.run(handle_session_command(ws, context, set(), "127.0.0.1", command,
                                              broadcast_json=broadcast_json, run_in_thread=run_in_thread))


class AgentSetPromptTest(unittest.TestCase):
    def test_agent_prompt_only_keeps_negative_and_reaches_tabs(self):
        context, raw, broadcasts = FakeContext(), FakeSocket(), []
        ws = AgentReplySocket(raw, "c-test1", context, {})
        run(ws, context, {"type": "set_prompt", "prompt": "1girl, agent"}, broadcasts)
        self.assertEqual(context.prompt_text, "1girl, agent")
        self.assertEqual(context.negative_prompt_text, "lowres, bad hands")
        self.assertEqual(broadcasts, [{"type": "prompt_sync", "prompt": "1girl, agent"}])
        self.assertEqual(raw.sent[-1]["negative_prompt"], "lowres, bad hands")
        self.assertEqual(context.preset_syncs, [])  # 에이전트 편집은 프리셋 파일에 쓰지 않는다

    def test_agent_negative_only_keeps_prompt(self):
        context, raw, broadcasts = FakeContext(), FakeSocket(), []
        ws = AgentReplySocket(raw, "c-test2", context, {})
        run(ws, context, {"type": "set_prompt", "negative_prompt": "worst quality"}, broadcasts)
        self.assertEqual(context.prompt_text, "1girl, solo")
        self.assertEqual(context.negative_prompt_text, "worst quality")
        self.assertNotIn("prompt", broadcasts[0])
        self.assertEqual(broadcasts[0]["negative_prompt"], "worst quality")

    def test_browser_set_prompt_unchanged(self):
        context, raw, broadcasts = FakeContext(), FakeSocket(), []
        run(raw, context, {"type": "set_prompt", "prompt": "typed"}, broadcasts)
        self.assertEqual(context.prompt_text, "typed")
        self.assertEqual(context.negative_prompt_text, "")  # 화면은 늘 두 칸을 보낸다 - 옛 의미 그대로
        self.assertEqual(broadcasts, [])
        self.assertEqual(raw.sent[-1]["type"], "prompt_sync")


if __name__ == "__main__":
    unittest.main()
