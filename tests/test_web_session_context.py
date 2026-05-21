import json
import os
import subprocess
import sys

from core.web_session_context import (
    AutocompleteRuntimeState,
    InMemoryTokenManager,
    WebSessionContext,
)


def test_web_session_context_constructs_without_importing_pyqt_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
from core.web_session_context import InMemoryTokenManager, WebSessionContext

ctx = WebSessionContext(
    token_manager=InMemoryTokenManager({
        "nai_token": "pst-example-token",
        "webui_url": "http://127.0.0.1:7860",
    })
)
ctx.set_option("auto_generate", True)
print(json.dumps({
    "pyqt_imported": "PyQt6" in sys.modules,
    "main_window": ctx.main_window is None,
    "api_mode": ctx.get_api_mode(),
    "auto_generate": ctx.get_options()["auto_generate"],
    "status": ctx.http_status_payload(),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["pyqt_imported"] is False
    assert payload["main_window"] is True
    assert payload["api_mode"] == "NAI"
    assert payload["auto_generate"] is True
    assert payload["status"] == {
        "is_generating": False,
        "api_mode": "NAI",
        "autocomplete": {
            "kr_tags_loaded": False,
            "metadata_fallback": {
                "ready": False,
                "live_path_allows_build": False,
            },
            "translation_cache_size": 0,
            "result_cache_size": 0,
        },
    }


def test_default_cloudflared_binary_dir_uses_runtime_downloads(tmp_path):
    context = WebSessionContext(repo_root=tmp_path, token_manager=InMemoryTokenManager())

    assert context.runtime_paths is not None
    assert context.api_config_service.cloudflared.bin_dir == (
        context.runtime_paths.downloads_dir / "cloudflared"
    )
    assert context.api_config_service.timestamp_path == (
        context.runtime_paths.config_dir / "NAIA_api_timestamps.json"
    )


def test_api_status_payload_matches_remote_web_setup_contract():
    ctx = WebSessionContext(
        token_manager=InMemoryTokenManager({
            "nai_token": "pst-123456789",
            "webui_url": "http://127.0.0.1:7860",
            "comfyui_url": "http://127.0.0.1:8188",
            "nai_token_last_verified": "2026-05-19 12:00:00",
        }),
        autocomplete_state=AutocompleteRuntimeState(
            kr_tags_loaded=True,
            metadata_fallback_ready=True,
            translation_cache_size=2,
            result_cache_size=3,
        ),
    )

    local = ctx.api_status_payload("127.0.0.1")
    remote = ctx.api_status_payload("192.168.1.10")

    assert local["type"] == "api_status"
    assert local["nai_configured"] is True
    assert local["nai_token_preview"] == "pst-123"
    assert local["webui_url"] == "http://127.0.0.1:7860"
    assert local["comfyui_url"] == "http://127.0.0.1:8188"
    assert local["active_mode"] == "NAI"
    assert local["setup_allowed"] is True
    assert local["setup_required"] is False
    assert local["cloudflared_control_allowed"] is True
    assert local["autocomplete"]["kr_tags_loaded"] is True
    assert local["autocomplete"]["metadata_fallback"]["ready"] is True
    assert local["autocomplete"]["translation_cache_size"] == 2
    assert local["autocomplete"]["result_cache_size"] == 3

    assert remote["setup_allowed"] is False
    assert remote["setup_required"] is False
    assert remote["cloudflared_control_allowed"] is False


def test_initial_websocket_messages_cover_headless_startup_state():
    ctx = WebSessionContext(token_manager=InMemoryTokenManager())
    ctx.remote_params["model"] = "NAID4.5F"
    ctx.set_api_mode("WEBUI")
    ctx.set_option("prompt_fixed", True)

    messages = ctx.initial_websocket_messages(
        session_id="session-1",
        client_host="127.0.0.1",
    )

    assert [message["type"] for message in messages] == [
        "session",
        "desktop_window_state",
        "mode",
        "options",
        "params",
        "queue_state",
        "api_status",
        "init_complete",
    ]
    assert messages[1]["visible"] is False
    assert messages[1]["control_allowed"] is False
    assert messages[2]["mode"] == "WEBUI"
    assert messages[3]["prompt_fixed"] is True
    assert messages[4]["api_mode"] == "WEBUI"
    assert messages[4]["model"] == "NAID4.5F"
    assert messages[5]["is_generating"] is False
    assert messages[6]["setup_allowed"] is True
    assert messages[6]["setup_required"] is True


def test_event_bus_mode_changes_and_pipeline_hooks_are_appcontext_compatible():
    ctx = WebSessionContext(token_manager=InMemoryTokenManager())
    events = []
    ctx.subscribe("api_mode_changed", events.append)

    ctx.set_api_mode("COMFYUI")

    assert ctx.get_api_mode() == "COMFYUI"
    assert events == [{"old_mode": "NAI", "new_mode": "COMFYUI"}]

    module_low = object()
    module_high = object()
    ctx.register_pipeline_hook(
        {"target_pipeline": "PromptProcessor", "hook_point": "after_wildcard", "priority": 50},
        module_low,
    )
    ctx.register_pipeline_hook(
        {"target_pipeline": "PromptProcessor", "hook_point": "after_wildcard", "priority": 10},
        module_high,
    )

    assert ctx.get_pipeline_hooks("PromptProcessor", "after_wildcard") == [module_high, module_low]


def test_web_session_context_tracks_prompt_runs_and_generation_links():
    ctx = WebSessionContext(token_manager=InMemoryTokenManager())
    run = ctx.start_prompt_run(
        source="random",
        source_row={"general": "alpha, beta", "rating": "s"},
        settings={"api_mode": "NAI", "credential": "hidden-token"},
        external_request_id="random-1",
    )

    ctx.record_prompt_run_hook(
        run.prompt_run_id,
        hook_point="after_wildcard",
        module="ExampleHook",
        status="completed",
    )
    ctx.complete_prompt_run(run.prompt_run_id, final_prompt="alpha, beta")
    ctx.link_generation_to_prompt_run(run.prompt_run_id, "gen-1")

    payload = ctx.get_prompt_run_payload(run.prompt_run_id, include_source_row=True)

    assert payload["prompt_run_id"] == run.prompt_run_id
    assert payload["source"] == "random"
    assert payload["external_request_id"] == "random-1"
    assert payload["status"] == "completed"
    assert payload["final_prompt"] == "alpha, beta"
    assert payload["generation_request_ids"] == ["gen-1"]
    assert payload["hook_trace"][0]["hook_point"] == "after_wildcard"
    assert payload["hook_trace"][0]["module"] == "ExampleHook"
    assert payload["settings"]["api_mode"] == "NAI"
    assert "credential" not in payload["settings"]
    assert payload["source_row"]["general"] == "alpha, beta"


def test_web_session_context_uses_runtime_paths_for_default_writable_state(tmp_path):
    ctx = WebSessionContext(repo_root=tmp_path, token_manager=InMemoryTokenManager())

    assert ctx.runtime_paths.user_root == (tmp_path / "user-data").resolve()
    assert ctx._search_filter_state_path() == (
        tmp_path / "user-data" / "save" / "remote_web_filter_state.json"
    ).resolve()
    assert ctx._current_save_directory(use_timestamp_folder=False) == (
        tmp_path / "user-data" / "output"
    ).resolve()
    assert ctx.runner_parquet_path() == (
        tmp_path / "user-data" / "cache" / "naia_temp_rows.parquet"
    ).resolve()
    assert ctx.runner_parquet_sources()[0] == (
        (tmp_path / "user-data" / "cache" / "naia_temp_rows.parquet").resolve(),
        "runtime cache parquet",
    )
    assert (
        (tmp_path / "user-data" / "data" / "tags" / "tags_129.parquet").resolve(),
        "runtime tag archive parquet",
    ) in ctx.runner_parquet_sources()
    assert (tmp_path / "user-data" / "data").is_dir()
    assert (tmp_path / "user-data" / "downloads").is_dir()

    ctx.save_search_filter_state(query="runtime-query")

    runtime_state = tmp_path / "user-data" / "save" / "remote_web_filter_state.json"
    legacy_state = tmp_path / "save" / "remote_web_filter_state.json"
    assert runtime_state.exists()
    assert not legacy_state.exists()


def test_web_session_context_reads_legacy_save_state_before_rewriting_runtime_path(tmp_path):
    legacy_state = tmp_path / "save" / "remote_web_filter_state.json"
    legacy_state.parent.mkdir(parents=True)
    legacy_state.write_text('{"query": "legacy-query", "ratings": ["g"]}', encoding="utf-8")

    ctx = WebSessionContext(repo_root=tmp_path, token_manager=InMemoryTokenManager())

    assert ctx.search_filter_state["query"] == "legacy-query"
    ctx.save_search_filter_state(exclude="new-exclude")

    runtime_state = tmp_path / "user-data" / "save" / "remote_web_filter_state.json"
    assert runtime_state.exists()
    assert "new-exclude" in runtime_state.read_text(encoding="utf-8")
    assert "new-exclude" not in legacy_state.read_text(encoding="utf-8")


def test_web_session_context_disables_legacy_save_fallback_for_electron(tmp_path, monkeypatch):
    legacy_state = tmp_path / "save" / "remote_web_filter_state.json"
    legacy_vibe = tmp_path / "save" / "vibe_transfer" / "NAID4.5F"
    legacy_character = tmp_path / "save" / "character_reference" / "images"
    legacy_instant = tmp_path / "save" / "instant_wildcard"
    legacy_preset = tmp_path / "save" / "presets" / "NAI"
    legacy_state.parent.mkdir(parents=True)
    legacy_vibe.mkdir(parents=True)
    legacy_character.mkdir(parents=True)
    legacy_instant.mkdir(parents=True)
    legacy_preset.mkdir(parents=True)
    legacy_state.write_text('{"query": "legacy-query", "ratings": ["g"]}', encoding="utf-8")
    (legacy_vibe / "legacy.json").write_text('{"encodings": {"1.0": "legacy"}}', encoding="utf-8")
    (legacy_character / "legacy.png").write_bytes(b"not-a-real-png")
    (legacy_instant / "legacy.json").write_text('{"pose": "legacy"}', encoding="utf-8")
    (legacy_preset / "legacy.json").write_text('{"api_mode": "NAI"}', encoding="utf-8")
    monkeypatch.setenv("NAIA_ELECTRON", "1")

    ctx = WebSessionContext(repo_root=tmp_path, token_manager=InMemoryTokenManager())

    assert ctx.search_filter_state["query"] == ""
    assert ctx._existing_save_dirs("vibe_transfer") == []
    assert ctx._existing_save_dirs("character_reference", "images") == []
    assert ctx._existing_save_path("vibe_transfer", "NAID4.5F", "legacy.json") == (
        tmp_path / "user-data" / "save" / "vibe_transfer" / "NAID4.5F" / "legacy.json"
    ).resolve()
    assert ctx._existing_save_path("instant_wildcard", "legacy.json") == (
        tmp_path / "user-data" / "save" / "instant_wildcard" / "legacy.json"
    ).resolve()
    assert ctx._existing_save_path("presets", "NAI", "legacy.json") == (
        tmp_path / "user-data" / "save" / "presets" / "NAI" / "legacy.json"
    ).resolve()
