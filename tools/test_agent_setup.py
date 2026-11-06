"""Cold-machine catalogs, item-specific consent and real local download lifecycle."""
from contextlib import redirect_stdout, redirect_stderr
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import agent_setup as setup
from core.agent_client import AgentClient, AgentCallError, _run_connected_command
from core.agent_cli import parse_args, main
from core.runtime_paths import RuntimePaths


class AgentSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="naia-agent-setup-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = RuntimePaths(self.root, self.root, self.root / "user", False)

    def test_catalogs_in_empty_environment_are_offline_and_do_not_create_user_data(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network")):
            models = setup.model_catalog(self.paths)
            assets = setup.asset_catalog(self.paths)
        self.assertFalse(self.paths.user_root.exists())
        rows = {r["key"]: r for r in models["items"]}
        self.assertEqual(rows["NAID5FM"]["variant"], "medium")
        self.assertFalse(rows["NAID5FM"]["capabilities"]["negative_prompt"])
        self.assertTrue(rows["NAID4.5F"]["capabilities"]["character_reference"])
        self.assertTrue(rows["NAID5C"]["inpainting_is_substitute"])
        self.assertFalse(models["account_access_verified"])
        by_id = {r["id"]: r for r in assets["items"]}
        for key in ("character_pack", "event_map", "tag_archive", "tag_combo", "event_preset", "sequence"):
            self.assertFalse(by_id[key]["ready"], key)
        self.assertTrue(any(r["id"].startswith("artist_thumbnail:") and r["downloadable"] for r in assets["items"]))

    def test_approval_is_item_specific_and_no_download_occurs_before_it(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network")):
            for approval in (None, "tag_archive", "yes", "*"):
                with self.subTest(approval=approval), self.assertRaises(setup.SetupRequired) as caught:
                    setup.install_asset(self.paths, "event_map", approval)
                self.assertEqual(caught.exception.code, "asset_setup_required")
                self.assertTrue(caught.exception.details["requires_user_input"])
                self.assertEqual(caught.exception.details["install_requests"][0]["approve_download"], "event_map")
        self.assertFalse(self.paths.user_root.exists())

    def test_generic_call_stops_before_missing_feature_or_download_is_submitted(self):
        catalog = setup.asset_catalog(self.paths)
        client = AgentClient(ROOT)
        self.addCleanup(client.close)
        with patch.object(client, "_discovery", return_value=catalog), patch.object(client, "_call_http") as submit:
            for identifier in ("http:GET:/api/event-map/explore", "http:POST:/api/install-manager/event-map/download"):
                entry = {"id": identifier, "callable": True, "transport": {"type": "http"}}
                with patch.object(client, "describe", return_value=entry), self.assertRaises(AgentCallError) as caught:
                    client.call(identifier)
                self.assertEqual(caught.exception.code, "asset_setup_required")
                self.assertFalse(caught.exception.details["submitted"])
            submit.assert_not_called()

    def test_virtual_artist_collection_keeps_partial_installed_pack_usable(self):
        from core.artist_thumbnail_service import ArtistThumbnailService
        key = "NAID5-6333-165"
        with patch.dict(ArtistThumbnailService.ARTIST_THUMB_MODES, {key: {
                "path": Path("data/example.json"), "url": "https://example.invalid/asset", "expected_size": 2}}):
            target = self.paths.ui_assets_dir / "artist_thumb" / "example.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"{}")
            catalog = setup.asset_catalog(self.paths)
        collection = next(r for r in catalog["items"] if r["id"] == "artist_thumbnail:NAID5-CURATED")
        self.assertTrue(collection["ready"])
        self.assertTrue(collection["install_candidates"])

    def test_installer_waits_verifies_and_leaves_data_available_to_next_invocation(self):
        import pandas as pd
        from core.runtime_install_manager import RuntimeInstallManager
        served = self.root / "served"
        served.mkdir()
        parquet = served / "tags_000.parquet"
        pd.DataFrame([{"id": 1, "general": "tree", "rating": "g"}]).to_parquet(parquet)
        with zipfile.ZipFile(served / "tags.zip", "w") as zf:
            zf.write(parquet, parquet.name)
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(served)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/tags.zip"
        def manager(paths):
            return RuntimeInstallManager(paths, tag_archive_url=url, expected_tag_files=1)
        with patch("core.runtime_install_manager.RuntimeInstallManager", side_effect=manager):
            result = setup.install_asset(self.paths, "tag_archive", "tag_archive")
            setup.require_assets(self.paths, ["tag_archive"])
            second = setup.install_asset(self.paths, "tag_archive", "tag_archive")
        self.assertTrue(result["installed"])
        self.assertTrue(second["already_ready"])
        installed = self.paths.data_dir / "tags" / parquet.name
        self.assertEqual(pd.read_parquet(installed).iloc[0]["general"], "tree")

    def test_failed_download_is_not_reported_as_installed(self):
        with patch("urllib.request.urlopen", side_effect=OSError("fixture offline")):
            with self.assertRaises(setup.SetupRequired) as caught:
                setup.install_asset(self.paths, "event_map", "event_map")
        self.assertEqual(caught.exception.code, "asset_install_failed")

    def test_json_install_request_preserves_explicit_approval_and_batch_pause(self):
        args = parse_args(["assets", "install", "event_map", "--approve-download", "event_map"])
        self.assertEqual(args.approve_download, "event_map")
        request = {"command": "assets", "action": "install", "item": "event_map", "approve_download": "event_map"}
        with patch("sys.stdin", io.StringIO(json.dumps(request))):
            self.assertEqual(parse_args(["run", "-"]).approve_download, "event_map")
        client = AgentClient(ROOT)
        self.addCleanup(client.close)
        calls = [{"id": "first"}, {"id": "second"}, {"id": "third"}]
        args = parse_args(["batch", "--input", json.dumps(calls)])
        with patch.object(client, "call", side_effect=[{"done": "first"}, AgentCallError("pause", code="asset_setup_required", details={"submitted": False})]) as invoke:
            with self.assertRaises(AgentCallError) as caught:
                _run_connected_command(args, client)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(caught.exception.details["completed"], [{"done": "first"}])

    def test_non_nai_models_do_not_claim_nai_choices(self):
        self.assertEqual(setup.model_catalog(self.paths, "COMFYUI")["items"], [])

    def test_asset_routes_report_actual_target_without_leaking_remote_host_paths(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from types import SimpleNamespace
        from app.backend.server.agent_discovery_routes import register_agent_discovery_routes
        async def run(fn, *args):
            return fn(*args)
        context = SimpleNamespace(runtime_paths=self.paths, repo_root=self.root, get_api_mode=lambda: "NAI")
        app = FastAPI()
        register_agent_discovery_routes(app, context, run_in_thread=run)
        with TestClient(app) as client:
            body = client.get("/api/agent/assets").json()
            self.assertEqual(body["user_data"], str(self.paths.user_root))
            models = client.get("/api/agent/models").json()
            self.assertIn("NAID5FM", [r["key"] for r in models["items"]])
            remote = client.get("/api/agent/assets", headers={"host": "remote.example"}).json()
            self.assertNotIn(str(self.paths.user_root), json.dumps(remote))
            self.assertNotIn(str(self.paths.project_root), json.dumps(remote))
        self.assertFalse(self.paths.user_root.exists())

    def test_artist_installer_uses_persistent_previews_without_writing_user_preferences(self):
        from core.artist_thumbnail_service import ArtistThumbnailService
        pack = "NAID5-6333-165"
        info = {"path": Path("data/mini.json"), "url": "https://example.invalid/mini", "expected_size": 2}
        target = self.paths.ui_assets_dir / "artist_thumb" / "mini.json"
        preferences = self.paths.ui_assets_dir / "artist_thumb" / "state.json"
        preferences.parent.mkdir(parents=True)
        preferences.write_text('{"untouched": true}', encoding="utf-8")
        favorite = self.paths.wildcards_dir / "favorite_artist.txt"
        favorite.parent.mkdir()
        favorite.write_text("keep-me", encoding="utf-8")
        before = {p: p.read_bytes() for p in (preferences, favorite)}
        def start(svc, key):
            self.assertEqual(key, pack)
            target.write_bytes(b"{}")
            svc._set_download_state(active=False, done=True, error="")
        with patch.dict(ArtistThumbnailService.ARTIST_THUMB_MODES, {pack: info}), patch.object(ArtistThumbnailService, "start_download", start):
            result = setup.install_asset(self.paths, "artist_thumbnail:" + pack, "artist_thumbnail:" + pack)
        self.assertTrue(result["installed"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_missing_increment_dependency_does_not_download_unapproved_base(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unapproved base download")):
            with self.assertRaises(setup.SetupRequired) as caught:
                setup.install_asset(self.paths, "tag_archive_increment", "tag_archive_increment")
        self.assertEqual(caught.exception.code, "asset_setup_required")
        self.assertEqual(caught.exception.details["items"][0]["id"], "tag_archive")
        self.assertFalse(self.paths.user_root.exists())

    def test_character_thumbnail_only_offers_pack_after_local_lookup_is_missing(self):
        from types import SimpleNamespace
        catalog = setup.asset_catalog(self.paths)
        client = AgentClient(ROOT)
        self.addCleanup(client.close)
        identifier = "http:GET:/api/character-viewer/thumbnail"
        entry = {"id": identifier, "callable": True, "transport": {
            "type": "http", "method": "GET", "path": "/api/character-viewer/thumbnail"}}
        good = SimpleNamespace(status_code=200, ok=True, headers={"Content-Type": "image/png"}, content=b"image")
        def non_json():
            raise ValueError()
        good.json = non_json
        missing = SimpleNamespace(status_code=404, ok=False, headers={"Content-Type": "application/json"},
                                  json=lambda: {"error": "missing"})
        with patch.object(client, "describe", return_value=entry), patch.object(client, "_discovery", return_value=catalog) as discover:
            with patch.object(client, "_request", return_value=good):
                self.assertEqual(client.call(identifier)["http_status"], 200)
                discover.assert_not_called()
            with patch.object(client, "_request", return_value=missing), self.assertRaises(AgentCallError) as caught:
                client.call(identifier, {"query": {"character": "example"}})
        self.assertEqual(caught.exception.code, "asset_setup_required")
        self.assertEqual(caught.exception.details["reason"], "optional_thumbnail_pack_missing")

    def test_models_preserve_aliases_without_duplicate_choices(self):
        rows = setup.model_catalog(self.paths)["items"]
        v45 = next(row for row in rows if row["key"] == "NAID4.5F")
        self.assertIn("NAID4.5", v45["aliases"])
        self.assertEqual(setup.resolve_model(self.paths, "NAID5.0F"), "NAID5F")
        with self.assertRaises(setup.SetupRequired):
            setup.resolve_model(self.paths, "   ")

    def test_model_namespace_enum_and_wire_aliases_round_trip(self):
        catalog = setup.model_catalog(self.paths)
        self.assertEqual(catalog["model_schema"]["enum"], [r["id"] for r in catalog["items"]])
        for row in catalog["items"]:
            for value in (row["id"], row["key"], row["api_model"]):
                with self.subTest(value=value):
                    self.assertEqual(setup.resolve_model(self.paths, value), row["key"])
        for bad in ("nai:", "webui:NAID5F", "nai:nai-diffusion-5-full", "v5"):
            with self.subTest(bad=bad), self.assertRaises(setup.SetupRequired) as caught:
                setup.resolve_model(self.paths, bad)
            self.assertIn("NAID5F", str(caught.exception))
            self.assertIn("nai:NAID5F", caught.exception.details["valid_model_ids"])

    def test_model_enum_keeps_custom_registry_choices(self):
        from types import SimpleNamespace
        from core.nai_model_registry import NaiModelRegistry
        registry = NaiModelRegistry(SimpleNamespace(runtime_paths=self.paths))
        registry.upsert({"key": "CUSTOM_TEST", "api_model": "custom-provider-model"})
        catalog = setup.model_catalog(self.paths)
        self.assertIn("nai:CUSTOM_TEST", catalog["model_schema"]["enum"])
        self.assertEqual(setup.resolve_model(self.paths, "nai:CUSTOM_TEST"), "CUSTOM_TEST")
        self.assertEqual(setup.resolve_model(self.paths, "custom-provider-model"), "CUSTOM_TEST")

    def test_download_gate_does_not_block_local_initialize_or_image_export(self):
        self.assertEqual(setup.download_asset_id("http:POST:/api/install-manager/initialize", {}), "")
        self.assertEqual(setup.download_asset_id("http:GET:/api/artist-thumb/download", {}), "")
        self.assertEqual(setup.download_asset_id("http:POST:/api/event-preset/download/cancel", {}), "")
        self.assertEqual(setup.download_asset_id("http:POST:/api/install-manager/event-map/download", {}), "event_map")


if __name__ == "__main__":
    unittest.main()
