"""Real loopback HTTP/WS checks for command-scoped CLI sessions."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.agent_cli import CliError, parse_args
from core.agent_client import AgentCallError
from core.agent_local_session import local_agent_client

ROOT = Path(__file__).resolve().parents[1]


class LocalAgentSessionTests(unittest.TestCase):
    def test_standalone_and_explicit_remote_target_are_mutually_exclusive(self):
        with self.assertRaises(CliError):
            parse_args(['call', 'http:GET:/api/status', '--standalone', '--server', 'http://localhost:1'])

    def test_http_ws_state_isolation_cleanup_and_no_qt(self):
        with tempfile.TemporaryDirectory(prefix='naia-agent-local-test-') as temporary:
            user = Path(temporary)
            saved = user / 'save' / 'character_module.json'
            saved.parent.mkdir()
            saved.write_text('{"untouched":true}', encoding='utf-8')
            args = parse_args(['--user-data', str(user), 'batch', '--standalone'])
            import uvicorn
            real_config = uvicorn.Config
            def fast_heartbeat(*a, **kw):
                return real_config(*a, **kw, ws_ping_interval=.05, ws_ping_timeout=.1)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with patch('uvicorn.Config', side_effect=fast_heartbeat), local_agent_client(args, ROOT, []) as (client, info):
                    port = urlsplit(client.server).port
                    self.assertEqual(info['mode'], 'standalone_cli')
                    self.assertEqual(client.call('http:GET:/api/status')['http_status'], 200)
                    client.call('module:character:set', {'key': 'activated', 'value': True})
                    # A synchronous recv-only client misses server pings here.
                    time.sleep(.6)
                    response = client.call('module:character:get')
                    state = next(m for m in response['messages'] if m.get('type') == 'module_state')
                    self.assertTrue(state['activated'])
                    self.assertTrue(response['dispatch_complete'])
                    self.assertFalse(any(k.startswith(('PyQt', 'PySide')) for k in sys.modules))
                    self.assertEqual(saved.read_text(encoding='utf-8'), '{"untouched":true}')
                    self.assertEqual(list(saved.parent.rglob('*')), [saved])
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex(('127.0.0.1', port)), 0)
            self.assertEqual(saved.read_text(encoding='utf-8'), '{"untouched":true}')

    def test_invalid_timeout_is_rejected_before_runtime_start(self):
        args = parse_args(['call', 'http:GET:/api/status', '--standalone', '--timeout', '0'])
        with self.assertRaises(AgentCallError):
            with local_agent_client(args, ROOT, []):
                self.fail('Invalid timeout entered the runtime')

    def test_release_entrypoint_cannot_silently_drop_out(self):
        from tools.check_release_source_payload import REQUIRED_SELECTED_FILES, validate_selected_release_files
        selected = sorted(REQUIRED_SELECTED_FILES - {'NAIA_cli.py'}) + ['data/taglist/expression_tags.json']
        self.assertTrue(any(v['path'] == 'NAIA_cli.py' for v in validate_selected_release_files(selected)))


if __name__ == '__main__':
    unittest.main()
