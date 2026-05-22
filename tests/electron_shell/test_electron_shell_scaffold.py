import json
from pathlib import Path


ELECTRON_ROOT = Path("app/electron")


def test_electron_shell_package_points_to_main_process():
    manifest = json.loads((ELECTRON_ROOT / "package.json").read_text(encoding="utf-8"))

    assert manifest["main"] == "main/main.cjs"
    assert "start" in manifest["scripts"]
    assert "test:main-contract" in manifest["scripts"]
    assert "goal:audit" in manifest["scripts"]
    assert "goal:audit:summary" in manifest["scripts"]
    assert "deps:plan:summary" in manifest["scripts"]
    assert "release:evidence" in manifest["scripts"]
    assert "release:evidence:summary" in manifest["scripts"]
    assert "release:evidence:fresh" in manifest["scripts"]
    assert "release:evidence:fresh:summary" in manifest["scripts"]
    assert "release:workspace" in manifest["scripts"]
    assert "release:workspace:summary" in manifest["scripts"]
    assert "release:workspace:evidence" in manifest["scripts"]
    assert "release:workspace:evidence:summary" in manifest["scripts"]
    assert "release:workspace:bundled-python" in manifest["scripts"]
    assert "release:workspace:bundled-python:evidence" in manifest["scripts"]
    assert "release:portable:workspace:plan" in manifest["scripts"]
    assert "release:portable:workspace:plan:summary" in manifest["scripts"]
    assert "release:portable:workspace" in manifest["scripts"]
    assert "release:portable:workspace:bundled-python" in manifest["scripts"]
    assert "release:final:plan:summary" in manifest["scripts"]
    assert "release:final" in manifest["scripts"]
    assert "release:final:install" in manifest["scripts"]
    assert "release:final:bundled-python" in manifest["scripts"]
    assert "preflight:electron-deps" in manifest["scripts"]
    assert "preflight:electron-deps:summary" in manifest["scripts"]
    assert (ELECTRON_ROOT / manifest["main"]).exists()


def test_electron_main_starts_headless_backend_and_waits_for_healthcheck():
    source = (ELECTRON_ROOT / "main/main.cjs").read_text(encoding="utf-8")

    assert "NAIA_web_headless.py" in source
    assert "NAIA_web_headless.exe" in source
    assert "process.resourcesPath" in source
    assert "naia-backend" in source
    assert "--no-browser" in source
    assert "/api/status" in source
    assert "NAIA_REMOTE_WEB_DIR" in source
    assert "NAIA_USER_DATA_DIR" in source
    assert "desktop_shell=1&electron_shell=1" in source
    assert "child_process" in source
    assert "NAIA_ELECTRON_REMOTE_DEBUGGING_PORT" in source
    assert "NAIA_ELECTRON_HIDE_MENU" in source
    assert "remote-debugging-port" in source
    assert "remote-allow-origins" in source
    assert "Menu.setApplicationMenu(null)" in source
    assert "setMenuBarVisibility(false)" in source
    assert "autoHideMenuBar: shouldHideApplicationMenu()" in source
    assert "STARTUP_WINDOW_BOUNDS" in source
    assert "expandMainWindowForApp" in source
    assert "PyQt6" not in source
    assert "legacy_desktop" not in source


def test_electron_main_detects_portable_user_data_folder():
    source = (ELECTRON_ROOT / "main/main.cjs").read_text(encoding="utf-8")

    assert "function portableUserDataRoot()" in source
    assert "path.dirname(app.getPath(\"exe\"))" in source
    assert "fs.existsSync(packagedUserData)" in source
    assert "return path.join(app.getPath(\"appData\"), \"NAIA\")" in source


def test_electron_main_keeps_popups_and_downloads_inside_shell_runtime():
    source = (ELECTRON_ROOT / "main/main.cjs").read_text(encoding="utf-8")

    assert "setWindowOpenHandler" in source
    assert "openInternalPopup" in source
    assert "openBrowserFallbackUrl" in source
    assert "naia-open-browser:" in source
    assert "will-navigate" in source
    assert "parent: mainWindow" in source
    assert "session.defaultSession.on(\"will-download\"" in source
    assert "ensureRuntimeSubfolder(\"downloads\")" in source
    assert "item.setSavePath" in source


def test_electron_package_declares_packaging_resource_contract():
    manifest = json.loads((ELECTRON_ROOT / "package.json").read_text(encoding="utf-8"))

    assert "stage:backend" in manifest["scripts"]
    assert "stage:python-runtime" in manifest["scripts"]
    assert "preflight:release" in manifest["scripts"]
    assert "preflight:release:bundled-python" in manifest["scripts"]
    assert "preflight:packaging-inputs" in manifest["scripts"]
    assert "preflight:packaging-inputs:bundled-python" in manifest["scripts"]
    assert "clean:staged" in manifest["scripts"]
    assert "clean:staged:bundled-python" in manifest["scripts"]
    assert "clean:packaged" in manifest["scripts"]
    assert "clean:packaged:bundled-python" in manifest["scripts"]
    assert "measure:release" in manifest["scripts"]
    assert "measure:release:defender" in manifest["scripts"]
    assert "smoke:backend" in manifest["scripts"]
    assert "smoke:web-contract" in manifest["scripts"]
    assert "smoke:packaged" in manifest["scripts"]
    assert "smoke:packaged:structure" in manifest["scripts"]
    assert "smoke:electron:source" in manifest["scripts"]
    assert "smoke:electron:packaged" in manifest["scripts"]
    assert "release:check" in manifest["scripts"]
    assert "release:stage" in manifest["scripts"]
    assert "release:portable" in manifest["scripts"]
    assert "release:portable:bundled-python" in manifest["scripts"]
    assert "release:portable:smoke" in manifest["scripts"]
    assert "release:portable:bundled-python:smoke" in manifest["scripts"]
    assert "release:workspace" in manifest["scripts"]
    assert "release:workspace:summary" in manifest["scripts"]
    assert "release:workspace:evidence" in manifest["scripts"]
    assert "release:workspace:evidence:summary" in manifest["scripts"]
    assert "release:workspace:bundled-python" in manifest["scripts"]
    assert "release:workspace:bundled-python:evidence" in manifest["scripts"]
    assert "release:portable:workspace:plan" in manifest["scripts"]
    assert "release:portable:workspace:plan:summary" in manifest["scripts"]
    assert "release:portable:workspace" in manifest["scripts"]
    assert "release:portable:workspace:bundled-python" in manifest["scripts"]
    assert "preflight:electron-deps" in manifest["scripts"]
    assert "preflight:electron-deps:summary" in manifest["scripts"]
    assert "goal:audit:summary" in manifest["scripts"]
    assert "release:final:plan:summary" in manifest["scripts"]
    assert "pack:dir" in manifest["scripts"]
    assert "dist:win-dir" in manifest["scripts"]
    assert "check:runtime" in manifest["scripts"]
    assert "check:source-payload" in manifest["scripts"]
    assert "check:shell-contract" in manifest["scripts"]
    assert "check:distribution" in manifest["scripts"]
    assert "check:approval-gate" in manifest["scripts"]
    assert "check:feature-contract" in manifest["scripts"]
    assert "check:packaged-feature-smoke" in manifest["scripts"]
    assert "check:runtime-writes" in manifest["scripts"]
    assert "check:asset-classification" in manifest["scripts"]
    assert "check:legacy-pyqt" in manifest["scripts"]
    assert "check:core-boundary" in manifest["scripts"]
    assert manifest["scripts"]["release:portable"] == "npm run release:portable:workspace:clean-python"
    assert manifest["scripts"]["release:portable:bundled-python"] == "npm run release:portable:workspace:bundled-python"
    assert manifest["scripts"]["release:portable:clean-python"] == "npm run release:portable:workspace:clean-python"
    assert "check:approval-gate" in manifest["scripts"]["release:check"]
    assert "check:source-payload" in manifest["scripts"]["release:check"]
    assert "check_release_source_payload.py" in manifest["scripts"]["check:source-payload"]
    assert "check_final_release_approval_gate.py" in manifest["scripts"]["check:approval-gate"]
    assert "--run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan" in manifest["scripts"]["release:final"]
    assert "--install-deps --yes --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan" in manifest["scripts"]["release:final:install"]
    assert "--require-bundled-python --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan" in manifest["scripts"]["release:final:bundled-python"]
    assert "--build-clean-python-runtime --python-runtime-version 3.12 --require-bundled-python --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan" in manifest["scripts"]["release:final:clean-python"]
    assert "--no-output --skip-electron-runtime --summary" in manifest["scripts"]["release:evidence:summary"]
    assert "--summary --output \"\" --portable-output \"\"" in manifest["scripts"]["release:final:plan:summary"]
    assert "run_electron_portable_workspace.py --run-electron-cdp --electron-timeout 180" in manifest["scripts"]["release:portable:smoke"]
    assert "--require-bundled-python --run-electron-cdp --electron-timeout 180" in manifest["scripts"]["release:portable:bundled-python:smoke"]
    assert "--build-clean-python-runtime --python-runtime-version 3.12 --require-bundled-python --run-electron-cdp --electron-timeout 180" in manifest["scripts"]["release:portable:clean-python:smoke"]
    assert manifest["build"]["extraResources"] == [
        {
            "from": "dist/NAIA-Web/resources/naia-backend",
            "to": "naia-backend",
        }
    ]
    assert manifest["build"]["extraFiles"] == [
        {
            "from": "dist/NAIA-Web/README_RELEASE.txt",
            "to": "README_RELEASE.txt",
        },
        {
            "from": "dist/NAIA-Web/RELEASE_MANIFEST.json",
            "to": "RELEASE_MANIFEST.json",
        },
        {
            "from": "dist/NAIA-Web/CHECKSUMS.sha256",
            "to": "CHECKSUMS.sha256",
        },
    ]
    assert manifest["build"]["afterPack"] == "packaging/afterPack.cjs"
    assert manifest["build"]["win"]["signAndEditExecutable"] is False
    assert manifest["build"]["win"]["forceCodeSigning"] is False
    assert manifest["devDependencies"]["electron"] == "42.1.0"
    assert manifest["devDependencies"]["electron-builder"] == "26.8.1"


def test_electron_after_pack_creates_portable_user_data_skeleton():
    source = (ELECTRON_ROOT / "packaging" / "afterPack.cjs").read_text(encoding="utf-8")

    assert "context.appOutDir" in source
    assert '"user-data"' in source
    assert "fs.mkdirSync" in source
    assert "recursive: true" in source


def test_maintenance_view_uses_non_scrolling_progress_layout():
    source = (ELECTRON_ROOT / "renderer" / "maintenance.html").read_text(encoding="utf-8")

    assert 'id="setup-progress"' in source
    assert "runtimeBootstrap" in source
    assert "processedCount" in source
    assert "currentPackage" in source
    assert "overflow: hidden;" in source
    assert "overflow-wrap: anywhere;" in source
    assert "LOG_VISIBLE_LINES" in source
    assert "overflow: auto" not in source


def test_electron_preload_exposes_shell_controls():
    source = (ELECTRON_ROOT / "preload/preload.cjs").read_text(encoding="utf-8")

    assert "naiaShell" in source
    assert "restartBackend" in source
    assert "openBrowser" in source
    assert "openDataFolder" in source
    assert "openLogs" in source


def test_electron_maintenance_view_has_backend_controls():
    source = (ELECTRON_ROOT / "renderer/maintenance.html").read_text(encoding="utf-8")

    assert "Restart backend" in source
    assert "Open in browser" in source
    assert "Open logs" in source
    assert "Open data folder" in source
