"""Agent CLI contract: real preset/pipeline/dispatch, fake provider transport only.

Runs in the existing tools/test_*.py CI discovery on Windows and Linux.
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


class AgentCliContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="naia-cli-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "user-data"
        self.data.mkdir()
        self.env = patch.dict(os.environ, {
            "NAIA_USER_DATA_DIR": str(self.data), "NAIA_DISABLE_LEGACY_SAVE_FALLBACK": "1",
            "NAIA_CLI_TEST_TOKEN": "cli-secret-never-output-123456", "NAIA_ELECTRON": "0",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        for mode in ("NAI", "WEBUI", "COMFYUI"):
            directory = self.data / "save" / "presets" / mode
            directory.mkdir(parents=True)
            (directory / "fixture.json").write_text(json.dumps({
                "module_settings": {"pre_prompt": "prefixmarker", "post_prompt": "postfixmarker"},
                "main_settings": {"model": "NAID4.5F" if mode == "NAI" else "provider-model",
                                  "negative": mode + " negative", "steps": 9, "cfg_scale": 4.5},
            }), encoding="utf-8")
        import pandas as pd
        self.parquet = self.root / "fixture.parquet"
        pd.DataFrame([
            {"id": 11, "general": "scenery, tree, blue sky", "rating": "g"},
            {"id": 12, "general": "scenery, mountain, cloud", "rating": "g"},
            {"id": 13, "general": "scenery, excludedmarker", "rating": "e"},
        ]).to_parquet(self.parquet)

    def call(self, *args, credential=True):
        output, errors = io.StringIO(), io.StringIO()
        prefix = ["--credential-env", "NAIA_CLI_TEST_TOKEN"] if credential else []
        with redirect_stdout(output), redirect_stderr(errors):
            code = cli.main([*prefix, *args])
        self.assertEqual(errors.getvalue(), "")
        self.assertNotIn(os.environ["NAIA_CLI_TEST_TOKEN"], output.getvalue())
        return code, json.loads(output.getvalue())

    def test_auth_does_not_create_credentials(self):
        code, body = self.call("auth", credential=False)
        self.assertEqual(code, 0)
        self.assertFalse(body["result"]["providers"]["NAI"]["configured"])
        self.assertFalse((self.data / "config" / "secure_tokens.json").exists())

    def test_current_preset_listing_and_implicit_generation_preserve_user_choice(self):
        (self.data / "save/presets/last_used_preset.json").write_text(
            json.dumps({"NAI": "fixture"}), encoding="utf-8")
        preset = self.data / "save/presets/NAI/fixture.json"
        data = json.loads(preset.read_text(encoding="utf-8"))
        data["main_settings"].update(width=832, height=1216)
        preset.write_text(json.dumps(data), encoding="utf-8")
        before = {p: p.read_bytes() for p in (self.data / "save").rglob("*.json")}
        code, body = self.call("presets")
        self.assertEqual(code, 0, body)
        listing = body["result"]
        self.assertEqual(listing["current_preset"], "fixture")
        current = [r for r in listing["items"] if r["is_current"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["model"], "NAID4.5F")
        self.assertEqual(current[0]["size"], "832 x 1216")
        self.assertTrue(current[0]["has_prefix"])
        self.assertTrue(current[0]["has_postfix"])
        self.assertTrue(current[0]["summary"].startswith("* fixture:"))
        code, inspected = self.call("presets", "--name", "default")
        self.assertEqual(code, 0, inspected)
        self.assertFalse(inspected["result"]["is_current"])
        code, body = self.call("generate", "--prompt", "robot", "--output", str(self.root / "dry.png"), "--dry-run")
        self.assertEqual(code, 0, body)
        self.assertEqual(body["result"]["preset"], "fixture")
        self.assertEqual(body["result"]["parameters"]["model"], "NAID4.5F")
        self.assertEqual(body["result"]["parameters"]["steps"], 9)
        self.assertEqual(body["result"]["parameters"]["width"], 832)
        self.assertEqual(before, {p: p.read_bytes() for p in (self.data / "save").rglob("*.json")})

    def test_dry_run_cost_uses_final_model_size_and_fixed_steps_without_provider(self):
        cases = [("nai:NAID4.5F", 1024, 28, 0, True),
                 ("nai:NAID4.5F", 1024, 29, 21, False),
                 ("nai:NAID5F", 1472, 28, 63, False),
                 ("nai:NAID5FM", 1024, 40, 0, True)]
        with patch("core.headless_generation_service.HeadlessGenerationService.execute_request",
                   side_effect=AssertionError("Dry-run must not submit")):
            for model, size, steps, price, free in cases:
                with self.subTest(model=model, steps=steps):
                    code, body = self.call("generate", "--prompt", "robot", "--model", model,
                        "--width", str(size), "--height", str(size), "--steps", str(steps),
                        "--output", str(self.root / "cost.png"), "--dry-run")
                    self.assertEqual(code, 0, body)
                    cost = body["result"]["cost"]
                    self.assertEqual(cost["anlas"], price)
                    self.assertEqual(cost["meets_free_conditions"], free)
                    self.assertGreater(cost["anlas_if_paid"], 0)
                    self.assertFalse(cost["quota_verified"])
                    self.assertFalse(cost["account_access_verified"])
                    if model.endswith("FM"):
                        self.assertEqual(body["result"]["parameters"]["steps"], 14)
        self.assertFalse((self.root / "cost.png").exists())

    def test_wrong_model_error_lists_valid_choices(self):
        code, body = self.call("generate", "--prompt", "robot", "--model", "v5",
                              "--output", str(self.root / "dry.png"), "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("NAID5F", body["error"]["message"])
        self.assertIn("nai:NAID5FM", body["error"]["details"]["valid_model_ids"])

    def test_saved_encrypted_token_is_used_without_output(self):
        from core.secure_token_manager import SecureTokenManager
        token_file = self.data / "config" / "secure_tokens.json"
        manager = SecureTokenManager(token_file)
        with redirect_stdout(io.StringIO()):
            manager.save_token("nai_token", os.environ["NAIA_CLI_TEST_TOKEN"])
        before = token_file.read_bytes()
        code, body = self.call("generate", "--prompt", "robot", "--preset", "fixture",
                              "--output", str(self.root / "dry.png"), "--dry-run", credential=False)
        self.assertEqual(code, 0, body)
        self.assertTrue(body["result"]["parameters"]["credential_configured"])
        self.assertEqual(before, token_file.read_bytes())

    def test_mode_preset_and_explicit_overrides(self):
        for mode in ("NAI", "WEBUI", "COMFYUI"):
            with self.subTest(mode=mode):
                code, body = self.call("--mode", mode, "generate", "--preset", "fixture", "--prompt", "robot",
                                      "--negative", "", "--steps", "3", "--seed", "123",
                                      "--output", str(self.root / "dry.png"), "--dry-run")
                self.assertEqual(code, 0, body)
                result = body["result"]
                self.assertEqual(result["negative_prompt"], "")
                self.assertEqual(result["parameters"]["steps"], 3)
                self.assertEqual(result["parameters"]["seed"], 123)
                self.assertFalse(result["executed"])
                if mode != "NAI":
                    self.assertFalse(result["cost"]["applicable"])
                    self.assertNotIn("anlas", result["cost"])
                self.assertFalse((self.root / "dry.png").exists())

    def test_random_pipeline_and_unchanged_source_settings(self):
        originals = {p: p.read_bytes() for p in (self.data / "save").rglob("*.json")}
        args = ("random", "--preset", "fixture", "--parquet", str(self.parquet), "--ratings", "g", "--random-seed", "7")
        code, first = self.call(*args)
        self.assertEqual(code, 0, first)
        _, second = self.call(*args)
        for body in (first, second):
            result = body["result"]
            self.assertEqual(result["matched_rows"], 2)
            self.assertIn("prefixmarker", result["prompt"])
            self.assertIn("postfixmarker", result["prompt"])
            self.assertNotIn("excludedmarker", result["prompt"])
        self.assertEqual(first["result"]["prompt"], second["result"]["prompt"])
        self.assertEqual(originals, {p: p.read_bytes() for p in (self.data / "save").rglob("*.json")})

    def test_empty_filter_fails_without_fallback(self):
        code, body = self.call("random", "--parquet", str(self.parquet), "--query", "nevermatches123")
        self.assertEqual(code, 2)
        self.assertEqual(body["error"]["code"], "no_matches")

    def test_combined_parquet_deduplicates_matching_ids(self):
        code, body = self.call("random", "--preset", "fixture", "--parquet", str(self.parquet),
                              "--parquet", str(self.parquet), "--exclude", "mountain")
        self.assertEqual(code, 0, body)
        self.assertEqual(body["result"]["matched_rows"], 1)
        self.assertEqual(body["result"]["source_id"], "11")

    def test_missing_credentials_block_provider(self):
        with patch("core.api_service.APIService.call_generation_api") as provider:
            code, body = self.call("generate", "--model", "NAID4.5F", "--prompt", "robot", "--output", str(self.root / "missing.png"), credential=False)
        self.assertEqual(code, 2)
        self.assertEqual(body["error"]["code"], "generation_blocked")
        provider.assert_not_called()

    def test_json_stdin_preserves_option_like_prompt(self):
        request = {"command": "generate", "model": "NAID4.5F", "prompt": "-bad hands, robot", "dry_run": True,
                   "output": str(self.root / "dry.png")}
        with patch("sys.stdin", io.StringIO(json.dumps(request))):
            code, body = self.call("run", "-")
        self.assertEqual(code, 0, body)
        self.assertFalse(body["result"]["executed"])

    def test_json_request_and_validation(self):
        request = self.root / "request.json"
        request.write_text(json.dumps({"command": "random", "preset": "fixture", "parquet": [str(self.parquet)],
                                       "random_seed": 8, "ratings": "g"}), encoding="utf-8")
        code, body = self.call("run", str(request))
        self.assertEqual(code, 0, body)
        for args in (("tags", "tree", "--limit", "0"), ("random", "--cfg", "nan"), ("generate", "--prompt", "")):
            code, body = self.call(*args)
            self.assertEqual(code, 2)
            self.assertEqual(body["error"]["code"], "invalid_arguments")

    def test_generation_uses_service_and_saves_png_without_secret(self):
        from PIL import Image
        target = self.root / "generated.png"
        sent = []
        def provider(_service, params, **kwargs):
            sent.append(params)
            return {"status": "success", "image": Image.new("RGB", (64, 64), "blue")}
        with patch("core.api_service.APIService.call_generation_api", provider):
            code, body = self.call("generate", "--random", "--parquet", str(self.parquet), "--preset", "fixture",
                                  "--output", str(target), "--seed", "42")
        self.assertEqual(code, 0, body)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["credential"], os.environ["NAIA_CLI_TEST_TOKEN"])
        self.assertIn("prefixmarker", sent[0]["input"])
        self.assertTrue(body["result"]["executed"])
        with Image.open(target) as image:
            self.assertEqual(image.size, (64, 64))
            self.assertNotIn(os.environ["NAIA_CLI_TEST_TOKEN"], str(image.info))

    def test_provider_error_redacted_and_reservation_removed(self):
        target = self.root / "failure.png"
        with patch("core.api_service.APIService.call_generation_api", side_effect=RuntimeError(os.environ["NAIA_CLI_TEST_TOKEN"])):
            code, body = self.call("generate", "--model", "NAID4.5F", "--prompt", "robot", "--output", str(target))
        self.assertEqual(code, 1)
        self.assertEqual(body["error"]["message"], "[REDACTED]")
        self.assertFalse(target.exists())

    def test_existing_output_is_preserved_before_provider_call(self):
        target = self.root / "existing.png"
        target.write_bytes(b"existing")
        with patch("core.api_service.APIService.call_generation_api") as provider:
            code, body = self.call("generate", "--prompt", "robot", "--output", str(target))
        self.assertEqual(code, 2)
        self.assertEqual(body["error"]["code"], "output_exists")
        self.assertEqual(target.read_bytes(), b"existing")
        provider.assert_not_called()

    def test_fresh_generation_requires_model_before_provider_and_output(self):
        target = self.root / "unselected.png"
        with patch("core.api_service.APIService.call_generation_api") as provider:
            code, body = self.call("generate", "--prompt", "robot", "--output", str(target))
        self.assertEqual(code, 2, body)
        self.assertEqual(body["error"]["code"], "model_selection_required")
        self.assertTrue(body["error"]["details"]["catalog"]["items"])
        provider.assert_not_called()
        self.assertFalse(target.exists())

    def test_ambiguous_model_returns_choices_instead_of_falling_back(self):
        code, body = self.call("generate", "--model", "v5", "--prompt", "robot",
                              "--output", str(self.root / "dry.png"), "--dry-run")
        self.assertEqual(code, 2, body)
        self.assertEqual(body["error"]["code"], "model_selection_required")

    def test_medium_explicit_choice_preserves_fixed_parameters(self):
        code, body = self.call("generate", "--model", "nai-diffusion-5-full-medium", "--steps", "28",
                              "--prompt", "robot", "--output", str(self.root / "dry.png"), "--dry-run")
        self.assertEqual(code, 0, body)
        self.assertEqual(body["result"]["parameters"]["model"], "NAID5FM")
        self.assertEqual(body["result"]["parameters"]["steps"], 14)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main()
