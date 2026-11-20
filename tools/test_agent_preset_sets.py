"""Agent CLI preset-sets: read-only browsing of the bundled preset sets (the web mini preset popup's data).

Runs in the existing tools/test_*.py CI discovery on Windows and Linux. Seeds and set ids come from the
command's own output - the bundled packs change, so nothing here names a particular set.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import agent_cli as cli


class AgentPresetSetsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One user-data for the class: any session command seeds bundled dictionaries (tens of MB) into an
        # empty user-data once, exactly as the app's first start does. That is not this command's doing.
        cls.temp = tempfile.TemporaryDirectory(prefix="naia-cli-presets-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / "user-data"
        (cls.data / "save").mkdir(parents=True)
        (cls.data / "save" / "marker.json").write_text("{}", encoding="utf-8")
        env = patch.dict(os.environ, {
            "NAIA_USER_DATA_DIR": str(cls.data), "NAIA_DISABLE_LEGACY_SAVE_FALLBACK": "1", "NAIA_ELECTRON": "0",
        })
        env.start()
        cls.addClassCleanup(env.stop)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            cli.main(["auth"])

    def setUp(self):
        # The Korean dictionary takes seconds to read and may be absent in a fresh checkout.
        names = patch("app.backend.server.autocomplete_commands._ensure_kr_raw", return_value={})
        self.kr_raw, self.kr_patch = names.start(), names
        self.addCleanup(names.stop)

    def call(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = cli.main(["preset-sets", *args] if args[:1] != ("run",) else list(args))
        self.assertEqual(errors.getvalue(), "")
        return code, json.loads(output.getvalue())

    def ok(self, *args):
        code, body = self.call(*args)
        self.assertEqual(code, 0, body)
        return body["result"]

    def user_files(self):
        return {str(p.relative_to(self.data)): (p.stat().st_size, p.stat().st_mtime_ns)
                for p in self.data.rglob("*") if p.is_file()}

    def test_kinds_match_the_service_and_the_web_tabs(self):
        from core.preset_thumbs import KINDS
        self.assertEqual(set(cli.PRESET_SET_KINDS), set(KINDS))
        kinds = self.ok()["kinds"]                       # action defaults to kinds
        self.assertEqual([row["kind"] for row in kinds], ["outfit", "event", "link", "expression", "scene"])
        self.assertEqual([row["label"] for row in kinds], ["의상", "자세", "2인", "표정", "배경"])
        self.assertTrue(all(row["sets"] >= row["seeds"] > 0 for row in kinds))

    def test_drill_down_reaches_prompt_text_without_touching_user_data(self):
        before = self.user_files()
        with patch("core.headless_generation_service.HeadlessGenerationService.enqueue_remote_request",
                   side_effect=AssertionError("preset-sets must not dispatch")):
            for kind in cli.PRESET_SET_KINDS:
                with self.subTest(kind=kind):
                    categories = self.ok("categories", "--kind", kind)["categories"]
                    normal = next(row for row in categories if not row["separate"])
                    self.assertEqual(normal["sets"], sum(sub["sets"] for sub in normal["subcategories"]))
                    listing = self.ok("seeds", "--kind", kind, "--category", normal["category"], "--limit", "3")
                    self.assertEqual(listing["total"], normal["seeds"])
                    self.assertLessEqual(len(listing["seeds"]), 3)
                    seed = listing["seeds"][0]
                    self.assertEqual(seed["category"], normal["category"])
                    sets = self.ok("sets", "--kind", kind, "--seed", seed["seed"], "--pool", seed["pool"])["sets"]
                    self.assertEqual(len(sets), seed["sets"])
                    for row in sets:
                        self.assertEqual(row["seed"], seed["seed"])
                        self.assertTrue(row["text"])
                        self.assertNotIn("key", row)             # thumbnail fields stay out of the agent shape
                    self.assertEqual(self.ok("text", "--id", sets[0]["id"]), sets[0])
        self.assertEqual(before, self.user_files())

    def test_text_is_tags_then_add_without_repeats(self):
        self.assertEqual(cli.set_prompt_text({"tags": ["a", " b ", "a"], "add": ["b", "c", ""]}), "a, b, c")
        # A real set that carries add tags - otherwise dropping `add` would go unnoticed.
        from core.preset_bench_service import PresetBenchService
        service = PresetBenchService(None, thumbs_path=self.root / "absent.json")
        service._load()
        row = next(row for row in service._by_id.values() if set(row["add"]) - set(row["tags"]))
        result = self.ok("text", "--id", row["id"])
        self.assertEqual(result["add"], row["add"])
        self.assertEqual(result["text"].split(", ")[:len(row["tags"])], row["tags"])
        for tag in row["add"]:
            self.assertIn(tag, result["text"].split(", "))
        self.assertEqual(result["adult"], row["adult"])

    def test_search_by_tag_and_korean_name_groups_by_seed(self):
        seed = self.ok("seeds", "--kind", "outfit", "--limit", "1")["seeds"][0]["seed"]
        result = self.ok("search", seed, "--kind", "outfit")
        first = result["seeds"][0]
        self.assertEqual((first["kind"], first["seed"], first["pool"]), ("outfit", seed, ""))
        self.assertGreaterEqual(first["matched_sets"], len(first["set_ids"]))
        self.assertEqual(self.ok("text", "--id", first["set_ids"][0])["seed"], seed)
        # Korean name: the dictionary may be absent in a fresh checkout, so supply one record.
        with patch.object(self.kr_raw, "return_value", {seed.casefold(): {"keywords_kr": "<primary>:가짜이름표"}}):
            found = self.ok("search", "가짜이름표")
            self.assertEqual(found["seeds"][0]["seed"], seed)
            self.assertEqual(found["seeds"][0]["ko"], "가짜이름표")
            listed = self.ok("seeds", "--kind", "outfit", "--limit", "1")["seeds"][0]
            self.assertEqual((listed["seed"], listed["ko"]), (seed, "가짜이름표"))
        with patch.object(self.kr_raw, "side_effect", OSError("no dictionary")):
            self.assertEqual(self.ok("seeds", "--kind", "outfit", "--limit", "1")["seeds"][0]["ko"], "")
        self.kr_patch.stop()                             # the real loader, whatever this checkout has
        try:
            before = self.user_files()
            self.assertIsInstance(self.ok("seeds", "--kind", "outfit", "--limit", "1")["seeds"][0]["ko"], str)
            self.assertIsInstance(self.ok("search", seed, "--kind", "outfit")["truncated"], bool)
            self.assertEqual(before, self.user_files())
        finally:
            self.kr_patch.start()

    def test_separate_pools_are_skipped_unless_asked(self):
        from core.preset_bench_service import APART_GROUPS
        separate = {pool for pool, _ in APART_GROUPS}
        categories = self.ok("categories", "--kind", "link")["categories"]
        apart = [row for row in categories if row["separate"]]
        self.assertTrue(apart and all(row["pool"] in separate for row in apart))
        normal_total = sum(row["seeds"] for row in categories if not row["separate"])
        self.assertEqual(self.ok("seeds", "--kind", "link", "--limit", "1")["total"], normal_total)
        self.assertEqual(self.ok("seeds", "--kind", "link", "--limit", "1", "--include-separate")["total"],
                         normal_total + sum(row["seeds"] for row in apart))
        seed = self.ok("seeds", "--kind", "link", "--category", apart[0]["category"], "--limit", "1")["seeds"][0]
        self.assertEqual(seed["pool"], apart[0]["pool"])
        sets = self.ok("sets", "--kind", "link", "--seed", seed["seed"], "--pool", seed["pool"])["sets"]
        self.assertTrue(all(row["separate_pool"] == seed["pool"] for row in sets))
        tag = sets[0]["tags"][0]
        plain = self.ok("search", tag, "--kind", "link", "--limit", "500")
        self.assertTrue(all(row["pool"] == "" for row in plain["seeds"]))
        wide = self.ok("search", tag, "--kind", "link", "--limit", "500", "--include-separate")
        self.assertIn(seed["pool"], {row["pool"] for row in wide["seeds"]})
        for index in range(8):
            self.assertEqual(self.ok("random", "--kind", "link", "--random-seed", str(index))["separate_pool"], "")
        picked = self.ok("random", "--kind", "link", "--category", apart[0]["category"])
        self.assertEqual(picked["separate_pool"], apart[0]["pool"])

    def test_random_is_repeatable_and_stays_inside_its_scope(self):
        first = self.ok("random", "--kind", "expression", "--random-seed", "7")
        self.assertEqual(first, self.ok("random", "--kind", "expression", "--random-seed", "7"))
        self.assertEqual(first["candidates"], next(row for row in self.ok("kinds")["kinds"] if row["kind"] == "expression")["sets"])
        seed = self.ok("seeds", "--kind", "scene", "--limit", "1")["seeds"][0]
        picked = self.ok("random", "--kind", "scene", "--seed", seed["seed"])
        self.assertEqual((picked["seed"], picked["candidates"]), (seed["seed"], seed["sets"]))
        category = self.ok("categories", "--kind", "scene")["categories"][-1]
        ids = {self.ok("random", "--kind", "scene", "--category", category["category"], "--random-seed", str(i))["id"]
               for i in range(5)}
        inside = set()
        for row in self.ok("seeds", "--kind", "scene", "--category", category["category"], "--limit", "500")["seeds"]:
            inside.update(item["id"] for item in self.ok("sets", "--kind", "scene", "--seed", row["seed"])["sets"])
        self.assertLessEqual(ids, inside)

    def test_json_request_form_and_errors(self):
        request = self.root / "request.json"
        request.write_text(json.dumps({"command": "preset-sets", "action": "seeds", "kind": "event",
                                       "include_separate": True, "limit": 2}), encoding="utf-8")
        code, body = self.call("run", str(request))
        self.assertEqual(code, 0, body)
        self.assertEqual(len(body["result"]["seeds"]), 2)
        self.assertEqual(body["result"]["next_offset"], 2)
        for args, expected in (
                (("sets", "--kind", "outfit"), "invalid_arguments"),
                (("search",), "invalid_arguments"),
                (("text",), "invalid_arguments"),
                (("random",), "invalid_arguments"),
                (("seeds", "--kind", "nope"), "invalid_arguments"),
                (("seeds", "--kind", "outfit", "--limit", "0"), "invalid_arguments"),
                (("sets", "--kind", "outfit", "--seed", "x", "--pool", "no-such-pool"), "invalid_arguments"),
                (("sets", "--kind", "outfit", "--seed", "no such seed tag"), "preset_seed_not_found"),
                (("seeds", "--kind", "outfit", "--category", "no such category"), "preset_category_not_found"),
                (("text", "--id", "no-such-set-id"), "preset_set_not_found")):
            with self.subTest(args=args):
                code, body = self.call(*args)
                self.assertEqual(code, 2, body)
                self.assertEqual(body["error"]["code"], expected)

    def test_agent_facing_references_name_the_command(self):
        from core.agent_catalog import overview, source_catalog
        self.assertTrue(any("preset-sets" in line for line in overview(source_catalog(ROOT))["workflow"]))
        self.assertIn("preset-sets", cli.parser().format_help())
        self.assertIn("preset-sets", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main()
