"""Standalone stdlib-only checks for optional startup diagnostics (CI tools sweep)."""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import startup_phase_probe as probe


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "spans.jsonl"
        self.env = patch.dict(os.environ, NAIA_STARTUP_PROBE_LOG=str(self.path))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_result_exception_and_nested_parent(self):
        inner = probe.wrap(lambda value: value + 1, "inner")
        outer = probe.wrap(lambda value: inner(value), "outer")
        self.assertEqual(outer(4), 5)
        rows = self.rows()
        self.assertEqual(rows[1]["parent"], rows[0]["span"])
        failure = probe.wrap(lambda: 1 / 0, "failure")
        with self.assertRaises(ZeroDivisionError):
            failure()
        self.assertEqual(self.rows()[-1]["status"], "error")
        self.assertIsNone(probe._parent.get())

    def test_async_cancellation_preserved(self):
        async def wait():
            await asyncio.sleep(30)
        async def run():
            task = asyncio.create_task(probe.wrap(wait, "wait")())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(run())
        self.assertEqual(self.rows()[-1]["status"], "error")

    def test_class_and_static_descriptors(self):
        class Sample:
            @classmethod
            def method(cls):
                return cls
            @staticmethod
            def static():
                return 7
        module = types.ModuleType("test_probe_module")
        module.Sample = Sample
        with patch.dict(probe.TARGETS, {module.__name__: ["Sample.method", "Sample.static"]}):
            probe.instrument(module)
            probe.instrument(module)  # no duplicate wrapping
        self.assertIs(Sample.method(), Sample)
        self.assertEqual(Sample().static(), 7)
        self.assertEqual(len(self.rows()), 4)

    def test_progress_and_no_content_logging(self):
        seen = []
        def reader(path, *, progress):
            progress(0, 3)
            progress(3, 3)
            return path
        wrapped = probe.wrap(reader, "core.parquet_chunk_loader.read_parquet_chunked")
        self.assertEqual(wrapped("PRIVATE_PATH", progress=lambda a,b: seen.append((a,b))), "PRIVATE_PATH")
        self.assertEqual(seen, [(0,3),(3,3)])
        self.assertNotIn("PRIVATE_PATH", self.path.read_text())
        self.assertEqual([r["loaded"] for r in self.rows() if r["event"] == "parquet_batch"], [0,3])

    def test_unwritable_log_does_not_break_call(self):
        with patch.dict(os.environ, NAIA_STARTUP_PROBE_LOG=str(Path(self.temp.name) / "absent/x")):
            self.assertEqual(probe.wrap(lambda: 2, "ok")(), 2)

    def test_import_hook_wraps_before_from_import_alias(self):
        name = "startup_probe_test_fixture"
        (Path(self.temp.name) / (name + ".py")).write_text("def answer():\n    return 42\n")
        finder = probe._Finder()
        sys.meta_path.insert(0, finder)
        sys.path.insert(0, self.temp.name)
        try:
            with patch.dict(probe.TARGETS, {name: ["answer"]}):
                alias = importlib.import_module(name).answer
                self.assertEqual(alias(), 42)
            self.assertEqual([r["name"] for r in self.rows() if r["event"] == "end"],
                             ["import:" + name, name + ".answer"])
        finally:
            sys.meta_path.remove(finder)
            sys.path.remove(self.temp.name)
            sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()
