import json
import subprocess
import sys
from pathlib import Path

from tools.smoke_electron_cdp import (
    _collect_performance_metrics,
    _collect_runtime_checks,
    _measure_action_dispatch,
    _measure_random_prompt_roundtrip,
    _restart_backend_and_wait,
    _runtime_check_violations,
    _verify_install_manager_surface,
    _verify_clipboard_and_paste_surface,
    _verify_drag_drop_surface,
    _verify_feature_workflows_surface,
    _verify_file_picker_surface,
    _verify_websocket_reconnect,
    _wait_for_shell_state,
    build_launch_config,
    smoke_electron_cdp,
)


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_launch_config_accepts_source_electron_command(tmp_path):
    electron_root = tmp_path / "electron"
    electron_command = tmp_path / "electron.cmd"
    _write(electron_command, "")

    payload = build_launch_config(
        mode="source",
        electron_root=electron_root,
        electron_command=str(electron_command),
        debug_port=9337,
        backend_port=7423,
        user_data=tmp_path / "user-data",
    )

    assert payload["ok"] is True
    assert payload["command"] == str(electron_command)
    assert payload["args"] == [str(electron_root.resolve())]
    assert payload["env"]["NAIA_ELECTRON_REMOTE_DEBUGGING_PORT"] == "9337"
    assert payload["env"]["NAIA_BACKEND_PORT"] == "7423"
    assert payload["env"]["NAIA_USER_DATA_DIR"] == str((tmp_path / "user-data").resolve())
    assert payload["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert payload["env"]["PYTHONPYCACHEPREFIX"] == str((tmp_path / "user-data" / "cache" / "python-bytecode").resolve())


def test_build_launch_config_rejects_missing_packaged_exe(tmp_path):
    payload = build_launch_config(mode="packaged", package_root=tmp_path)

    assert payload["ok"] is False
    assert "Packaged Electron executable not found" in payload["reason"]


def test_smoke_electron_cdp_dry_run_for_packaged_app(tmp_path):
    _write(tmp_path / "NAIA.exe", "exe")

    payload = smoke_electron_cdp(
        mode="packaged",
        package_root=tmp_path,
        debug_port=9338,
        backend_port=7424,
        dry_run=True,
    )

    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["launch"]["command"] == str((tmp_path / "NAIA.exe").resolve())
    assert payload["violations"] == []


def test_smoke_electron_cdp_cli_dry_run(tmp_path):
    _write(tmp_path / "electron.cmd", "")

    result = subprocess.run(
        [
            sys.executable,
            "tools/smoke_electron_cdp.py",
            "--mode",
            "source",
            "--electron-root",
            str(tmp_path / "app"),
            "--electron-command",
            str(tmp_path / "electron.cmd"),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["dry_run"] is True


class FakeClient:
    def __init__(self, values=None):
        self.values = values or {}
        self.marker = "ok-1"
        self.reload_called = False
        self.reconnect_called = False

    def evaluate(self, expression: str):
        if "__naia_cdp_input_surface_probe" in expression:
            return self.values.get("resultImageInputSurface", {
                "fileInputPresent": True,
                "fileInputAccept": "image/*",
                "viewerPresent": True,
            })
        if "__naia_cdp_file_picker_probe" in expression:
            return self.values.get("filePicker", {
                "present": True,
                "count": 2,
                "accept": ["image/png,.png", "image/*"],
                "showPickerAvailable": True,
                "disabledCount": 0,
            })
        if "__naia_cdp_clipboard_probe" in expression:
            return self.values.get("clipboard", {
                "clipboardReadApi": True,
                "clipboardWriteApi": True,
                "dataTransferAvailable": True,
                "clipboardEventAvailable": True,
                "eventAvailable": True,
                "syntheticImagePastePrevented": True,
                "syntheticImagePasteDispatched": True,
                "reason": "",
            })
        if "__naia_cdp_drag_drop_probe" in expression:
            return self.values.get("dragDrop", {
                "targetPresent": True,
                "dataTransferAvailable": True,
                "dragEnterPrevented": True,
                "dragOverPrevented": True,
                "dropPrevented": True,
                "dropEffect": "copy",
                "activeClassObserved": True,
                "reason": "",
            })
        if "__naia_cdp_ws_reconnect_probe" in expression:
            return self.values.get("websocketReconnect", {
                "activeSocketFound": True,
                "closedOriginal": True,
                "reconnected": True,
                "originalReadyState": 1,
                "finalReadyState": 1,
                "elapsedMs": 3200,
                "reason": "",
            })
        if "__naia_cdp_action_dispatch_probe" in expression:
            return self.values.get("actionDispatch", {
                "available": True,
                "activeSocketOpen": True,
                "generate": {"dispatched": True, "latencyMs": 0.1},
                "random": {"dispatched": True, "latencyMs": 0.2},
                "payloadTypes": ["generate", "random"],
                "reason": "",
            })
        if "__naia_cdp_random_prompt_roundtrip_probe" in expression:
            return self.values.get("randomPromptRoundTrip", {
                "available": True,
                "activeSocketOpen": True,
                "promptUpdated": True,
                "latencyMs": 123.4,
                "promptLength": 240,
                "reason": "",
            })
        if "__naia_cdp_install_manager_probe" in expression:
            return self.values.get("installManager", {
                "available": True,
                "dataRootInitialized": True,
                "tagArchiveReady": True,
                "tagArchiveDownloadable": True,
                "tagArchiveFileCount": 150,
                "tagArchiveExpectedCount": 150,
                "reason": "",
            })
        if "__naia_cdp_performance_probe" in expression:
            return self.values.get("performance", {
                "domContentLoadedMs": 42.0,
                "loadEventEndMs": 84.0,
                "firstPaintMs": None,
                "firstContentfulPaintMs": None,
                "firstPaintProxyMs": 84.0,
                "firstPaintProxySource": "loadEventEnd",
                "firstPaintReady": True,
            })
        if "__naia_cdp_feature_workflows_probe" in expression:
            features = {
                feature_id: {"ok": True, "evidence": ["surface"], "missing": []}
                for feature_id in (
                    "random_prompt",
                    "generate",
                    "result_display",
                    "prompt_tools",
                    "params",
                    "presets",
                    "danbooru",
                    "artist_thumbnail",
                    "img2img",
                    "vibe_transfer_storage",
                    "character_reference",
                    "enhance",
                    "setup_api_settings",
                    "history",
                    "save_output",
                )
            }
            return self.values.get("featureWorkflows", {
                "requiredFeatureCount": 15,
                "observedFeatureCount": 15,
                "allRequiredFeaturesObserved": True,
                "features": features,
                "routeChecks": [],
                "domChecks": [],
                "nonDestructive": True,
            })
        if "window.naiaShell" in expression:
            return {
                "href": "http://127.0.0.1:7243/?desktop_shell=1&electron_shell=1",
                "title": "NAIA",
                "readyState": "complete",
                "innerWidth": 1280,
                "innerHeight": 860,
                "hasShell": True,
                "hasWebSocket": True,
                "hasClipboard": True,
                "hasFileInput": True,
                "localStorageWorks": True,
                "sessionStorageWorks": True,
                "backendState": "ready",
                "backendUrl": "http://127.0.0.1:7243",
                "runtimeDataRoot": "C:/tmp/naia-user-data",
            }
        if "localStorage.setItem" in expression:
            marker = expression.split('__naia_cdp_persist", ', 1)
            if len(marker) == 2:
                self.marker = json.loads(marker[1].split(")", 1)[0])
            return True
        if "localStorageValue" in expression:
            return {
                "readyState": "complete",
                "localStorageValue": self.values.get("storage", self.marker),
                "sessionStorageValue": self.values.get("storage", self.marker),
            }
        if "readyState === WebSocket.OPEN" in expression and "hasSocket" in expression:
            return {"hasSocket": True, "readyState": 1, "open": True}
        return {}

    def reload(self):
        self.reload_called = True

    def reconnect(self):
        self.reconnect_called = True
        return None


class RestartNavigatesClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.restart_attempted = False

    def evaluate(self, expression: str):
        if "window.naiaShell.restartBackend" in expression and not self.restart_attempted:
            self.restart_attempted = True
            raise RuntimeError("Cannot find context with specified id: target navigated or closed")
        return super().evaluate(expression)


class NavigationDuringShellStateClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.raised = False

    def evaluate(self, expression: str):
        if "window.naiaShell" in expression and not self.raised:
            self.raised = True
            raise RuntimeError("CDP Runtime.evaluate failed: {'code': -32000, 'message': 'Execution context was destroyed.'}")
        return super().evaluate(expression)


def test_wait_for_shell_state_retries_after_navigation_context_destroyed():
    client = NavigationDuringShellStateClient()

    state = _wait_for_shell_state(client, timeout=1.0)

    assert state["backendState"] == "ready"
    assert client.reconnect_called is True


def test_collect_runtime_checks_can_skip_download_and_restart():
    client = FakeClient()
    ready_state = {
        "innerWidth": 1280,
        "innerHeight": 860,
        "hasWebSocket": True,
        "hasClipboard": True,
        "hasFileInput": False,
        "runtimeDataRoot": "C:/tmp/naia-user-data",
    }

    checks = _collect_runtime_checks(
        client,
        ready_state,
        timeout=0.5,
        skip_download=True,
        skip_restart=True,
    )

    assert checks["window"]["meetsMinimum"] is True
    assert checks["browserApis"]["websocket"] is True
    assert checks["browserApis"]["clipboard"] is True
    assert checks["filePicker"]["present"] is True
    assert checks["clipboard"]["syntheticImagePastePrevented"] is True
    assert checks["dragDrop"]["dropPrevented"] is True
    assert checks["performance"]["firstPaintReady"] is True
    assert checks["storage"]["localStoragePersistsAfterReload"] is True
    assert checks["actionDispatch"]["generate"]["dispatched"] is True
    assert checks["actionDispatch"]["random"]["dispatched"] is True
    assert checks["installManager"]["available"] is True
    assert checks["installManager"]["dataRootInitialized"] is True
    assert checks["randomPromptRoundTrip"]["promptUpdated"] is True
    assert checks["websocketReconnect"]["reconnected"] is True
    assert checks["featureWorkflows"]["allRequiredFeaturesObserved"] is True
    assert checks["download"] is None
    assert checks["backendRestart"] is None
    assert client.reload_called is True


def test_runtime_probe_helpers_return_cdp_payloads():
    client = FakeClient()

    assert _verify_file_picker_surface(client)["showPickerAvailable"] is True
    assert _verify_clipboard_and_paste_surface(client)["syntheticImagePastePrevented"] is True
    assert _verify_drag_drop_surface(client)["activeClassObserved"] is True
    assert _verify_websocket_reconnect(client, timeout=0.5)["reconnected"] is True
    assert _measure_action_dispatch(client)["payloadTypes"] == ["generate", "random"]
    assert _measure_random_prompt_roundtrip(client, timeout=0.5)["latencyMs"] == 123.4
    assert _verify_install_manager_surface(client)["tagArchiveReady"] is True
    assert _collect_performance_metrics(client)["firstPaintReady"] is True
    assert _verify_feature_workflows_surface(client, timeout=0.5)["observedFeatureCount"] == 15


def test_backend_restart_check_reconnects_after_expected_navigation():
    client = RestartNavigatesClient()

    result = _restart_backend_and_wait(client, timeout=0.5)

    assert result["readyAfterRestart"] is True
    assert client.reconnect_called is True


def test_runtime_check_violations_require_strong_runtime_evidence():
    violations = _runtime_check_violations({
        "window": {"meetsMinimum": True},
        "browserApis": {"websocket": True, "clipboard": True, "fileInputPresent": True},
        "filePicker": {"present": True},
        "clipboard": {"clipboardReadApi": False, "syntheticImagePastePrevented": True},
        "dragDrop": {"targetPresent": True, "dropPrevented": True},
        "storage": {
            "localStoragePersistsAfterReload": True,
            "sessionStoragePersistsAfterReload": True,
        },
        "performance": {"firstPaintReady": True},
        "actionDispatch": {
            "generate": {"dispatched": True},
            "random": {"dispatched": True},
        },
        "installManager": {
            "available": True,
            "dataRootInitialized": True,
            "tagArchiveReady": True,
            "tagArchiveDownloadable": True,
        },
        "randomPromptRoundTrip": {"promptUpdated": True},
        "websocketReconnect": {"reconnected": True},
        "featureWorkflows": {"allRequiredFeaturesObserved": True},
    })

    assert violations == [{
        "path": "checks.clipboard.clipboardReadApi",
        "reason": "expected truthy Electron runtime smoke evidence",
    }]


def test_runtime_check_violations_require_feature_workflow_evidence():
    violations = _runtime_check_violations({
        "window": {"meetsMinimum": True},
        "browserApis": {"websocket": True, "clipboard": True, "fileInputPresent": True},
        "filePicker": {"present": True},
        "clipboard": {"clipboardReadApi": True, "syntheticImagePastePrevented": True},
        "dragDrop": {"targetPresent": True, "dropPrevented": True},
        "storage": {
            "localStoragePersistsAfterReload": True,
            "sessionStoragePersistsAfterReload": True,
        },
        "performance": {"firstPaintReady": True},
        "actionDispatch": {
            "generate": {"dispatched": True},
            "random": {"dispatched": True},
        },
        "installManager": {
            "available": True,
            "dataRootInitialized": True,
            "tagArchiveReady": True,
            "tagArchiveDownloadable": True,
        },
        "randomPromptRoundTrip": {"promptUpdated": True},
        "websocketReconnect": {"reconnected": True},
        "featureWorkflows": {"allRequiredFeaturesObserved": False},
    })

    assert violations == [{
        "path": "checks.featureWorkflows.allRequiredFeaturesObserved",
        "reason": "expected truthy Electron runtime smoke evidence",
    }]


def test_runtime_check_violations_allow_uninstalled_tag_archive_before_random_prompt():
    checks = {
        "window": {"meetsMinimum": True},
        "browserApis": {"websocket": True, "clipboard": True, "fileInputPresent": True},
        "filePicker": {"present": True},
        "clipboard": {"clipboardReadApi": True, "syntheticImagePastePrevented": True},
        "dragDrop": {"targetPresent": True, "dropPrevented": True},
        "storage": {
            "localStoragePersistsAfterReload": True,
            "sessionStoragePersistsAfterReload": True,
        },
        "performance": {"firstPaintReady": True},
        "actionDispatch": {
            "generate": {"dispatched": True},
            "random": {"dispatched": True},
        },
        "installManager": {
            "available": True,
            "dataRootInitialized": True,
            "tagArchiveReady": False,
            "tagArchiveDownloadable": True,
        },
        "randomPromptRoundTrip": {"promptUpdated": False},
        "websocketReconnect": {"reconnected": True},
        "featureWorkflows": {"allRequiredFeaturesObserved": True},
    }

    assert _runtime_check_violations(checks) == []
