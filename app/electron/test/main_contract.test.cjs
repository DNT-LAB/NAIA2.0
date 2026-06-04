"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");

const ELECTRON_ROOT = path.resolve(__dirname, "..");
const MAIN_PATH = path.join(ELECTRON_ROOT, "main", "main.cjs");

function mkdirp(target) {
  fs.mkdirSync(target, { recursive: true });
}

function writeFile(target, content = "") {
  mkdirp(path.dirname(target));
  fs.writeFileSync(target, content, "utf8");
}

function loadMain({
  env = {},
  appData,
  exePath,
  isPackaged = false,
  resourcesPath,
  spawnImpl,
  cliSwitches = [],
  argv = [],
} = {}) {
  const source = fs.readFileSync(MAIN_PATH, "utf8");
  const opened = [];
  const menuCalls = [];
  const app = {
    isPackaged,
    paths: {},
    commandLine: {
      switches: [],
      appendSwitch(name, value) {
        this.switches.push([name, value]);
      },
      hasSwitch(name) {
        return cliSwitches.includes(name);
      },
    },
    setPath(name, value) {
      this.paths[name] = value;
    },
    getPath(name) {
      if (this.paths[name]) {
        return this.paths[name];
      }
      if (name === "appData") {
        return appData || path.join(os.tmpdir(), "naia-appdata");
      }
      if (name === "exe") {
        return exePath || path.join(os.tmpdir(), "NAIA.exe");
      }
      return os.tmpdir();
    },
    on() {},
    quit() {},
    requestSingleInstanceLock() {
      return true;
    },
    whenReady() {
      return {
        then() {
          return { catch() {} };
        },
      };
    },
  };
  function BrowserWindow() {}
  BrowserWindow.getAllWindows = () => [];

  const electron = {
    app,
    BrowserWindow,
    ipcMain: { handle() {} },
    Menu: {
      setApplicationMenu(menu) {
        menuCalls.push(menu);
      },
    },
    session: { defaultSession: { on() {} } },
    shell: {
      openExternal(url) {
        opened.push(url);
        return Promise.resolve("");
      },
      openPath(target) {
        opened.push(target);
        return Promise.resolve("");
      },
    },
  };
  const processStub = {
    env: { ...process.env, ...env },
    platform: process.platform,
    resourcesPath: resourcesPath || process.resourcesPath,
    argv: ["node", MAIN_PATH, ...argv],
  };

  const sandbox = {
    URL,
    Buffer,
    clearTimeout,
    console,
    module: { exports: {} },
    exports: {},
    process: processStub,
    require(specifier) {
      if (specifier === "electron") {
        return electron;
      }
      if (specifier === "node:child_process" && spawnImpl) {
        const childProcess = require(specifier);
        return {
          ...childProcess,
          spawn: spawnImpl,
        };
      }
      return require(specifier);
    },
    setTimeout,
    __dirname: path.join(ELECTRON_ROOT, "main"),
    __filename: MAIN_PATH,
  };
  vm.runInNewContext(source, sandbox, { filename: MAIN_PATH });
  return { api: sandbox.module.exports.__test, app, menuCalls, opened };
}

test("source backend launch config uses repo venv, no-browser, and app data user root", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "naia-electron-source-"));
  try {
    const appData = path.join(root, "AppData");
    const venvPython = path.join(root, "venv", "Scripts", "python.exe");
    const entry = path.join(root, "NAIA_web_headless.py");
    writeFile(venvPython, "python");
    writeFile(entry, "print('ok')\n");

    const { api } = loadMain({
      appData,
      env: {
        NAIA_REPO_ROOT: root,
        NAIA_BACKEND_PORT: "7421",
      },
    });
    const launch = await api.backendLaunchConfig();

    assert.equal(launch.root, root);
    assert.equal(launch.command, venvPython);
    assert.equal(launch.entry, entry);
    assert.deepEqual(Array.from(launch.args), [
      "-B",
      entry,
      "--host",
      "0.0.0.0",
      "--port",
      "7421",
      "--auto-port",
      "--no-browser",
    ]);
    assert.equal(launch.env.NAIA_ELECTRON, "1");
    assert.equal(launch.env.NAIA_HEADLESS_OPEN_BROWSER, "0");
    assert.equal(launch.env.PYTHONDONTWRITEBYTECODE, "1");
    assert.equal(launch.env.PYTHONPYCACHEPREFIX, path.join(appData, "NAIA", "cache", "python-bytecode"));
    assert.equal(launch.env.NAIA_USER_DATA_DIR, path.join(appData, "NAIA"));
    assert.equal(launch.env.NAIA_REMOTE_WEB_DIR, path.join(root, "app", "web", "remote"));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("grok proxy port is dynamic: explicit env wins and reaches the Python backend", async () => {
  // Multi-instance contract: an explicit NAIA_GROK_PROXY_PORT is honored and is
  // forwarded into the backend environment so the Python proxy resolver targets
  // the same progrok instance the shell spawned (each NAIA instance = own port).
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "naia-electron-grok-"));
  try {
    const venvPython = path.join(root, "venv", "Scripts", "python.exe");
    const entry = path.join(root, "NAIA_web_headless.py");
    writeFile(venvPython, "python");
    writeFile(entry, "print('ok')\n");

    const { api } = loadMain({
      env: { NAIA_REPO_ROOT: root, NAIA_GROK_PROXY_PORT: "18650" },
    });
    const resolved = await api.resolveGrokProxyPort();
    assert.equal(resolved, 18650);

    const launch = await api.backendLaunchConfig();
    assert.equal(launch.env.NAIA_GROK_PROXY_PORT, "18650");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("findFreePort returns the first port that is not in use", async () => {
  const { api } = loadMain();
  const blocker = net.createServer();
  await new Promise((resolve) => blocker.listen(0, "127.0.0.1", resolve));
  const taken = blocker.address().port;
  try {
    const free = await api.findFreePort("127.0.0.1", taken, 8);
    assert.notEqual(free, taken);
    assert.equal(free > taken && free <= taken + 8, true);
  } finally {
    await new Promise((resolve) => blocker.close(resolve));
  }
});

test("electron userData is install-local so separate install dirs get independent locks", () => {
  // Multi-instance contract: the single-instance lock + persist:danbooru session live under
  // Electron's userData. Pointing it at <runtimeDataRoot>/electron makes each install directory
  // its own lock, so separate-directory portable copies run simultaneously (no launcher needed).
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "naia-electron-userdata-"));
  try {
    const { api, app } = loadMain({ env: { NAIA_USER_DATA_DIR: root } });
    const expected = path.join(root, "electron");
    assert.equal(api.electronUserDataDir(), expected);
    assert.equal(app.paths.userData, expected); // setPath ran at module load, before the lock
    assert.equal(fs.existsSync(expected), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("packaged portable isolates per install dir: danbooru/lock under electron, NAI token under user-data", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "naia-electron-portable-userdata-"));
  try {
    const exePath = path.join(root, "NAIA.exe");
    mkdirp(path.join(root, "user-data")); // portableUserDataRoot() requires it to exist
    const { app, api } = loadMain({ isPackaged: true, exePath, env: { NAIA_USER_DATA_DIR: "" } });
    // danbooru session (persist:danbooru/Partitions) + the single-instance lock live under
    // Electron's userData — the `electron` subfolder, so separate install dirs do NOT share login.
    assert.equal(app.paths.userData, path.join(root, "user-data", "electron"));
    // The backend (NAI token at config/secure_tokens.json) stays at the PARENT user-data, NOT the
    // electron subfolder: the Electron-userData move must never redirect the backend token store.
    // Net: a different install directory isolates BOTH danbooru and the NAI token.
    assert.equal(api.backendEnvironment(root).NAIA_USER_DATA_DIR, path.join(root, "user-data"));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("explicit --user-data-dir (launcher / manual override) is honored over the install-local default", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "naia-electron-udd-"));
  try {
    // argv form: manual `NAIA.exe --user-data-dir=...` or the clone test.
    const viaArgv = loadMain({
      env: { NAIA_USER_DATA_DIR: root },
      argv: ["--user-data-dir=" + path.join(root, "explicit")],
    });
    assert.equal(viaArgv.api.userDataDirSwitchPresent(), true);
    assert.equal(viaArgv.app.paths.userData, undefined); // setPath NOT called — the switch wins
    // commandLine.hasSwitch form: the same-folder launcher tools/launch_naia_instance.ps1.
    const viaSwitch = loadMain({ env: { NAIA_USER_DATA_DIR: root }, cliSwitches: ["user-data-dir"] });
    assert.equal(viaSwitch.api.userDataDirSwitchPresent(), true);
    assert.equal(viaSwitch.app.paths.userData, undefined);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("packaged backend launch config uses resources backend, managed runtime env, and portable user-data", async () => {
  const packageRoot = fs.mkdtempSync(path.join(os.tmpdir(), "naia-electron-packaged-"));
  try {
    const resources = path.join(packageRoot, "resources");
    const backendRoot = path.join(resources, "naia-backend");
    const entry = path.join(backendRoot, "NAIA_web_headless.py");
    const basePython = path.join(resources, "python", "python.exe");
    const envPython = path.join(packageRoot, "user-data", "runtime-env", "Scripts", "python.exe");
    writeFile(entry, "print('ok')\n");
    writeFile(basePython, "python");
    writeFile(envPython, "python");
    mkdirp(path.join(packageRoot, "user-data"));

    const { api } = loadMain({
      isPackaged: true,
      resourcesPath: resources,
      exePath: path.join(packageRoot, "NAIA.exe"),
      env: {
        NAIA_BACKEND_PORT: "7243",
        NAIA_RUNTIME_ENV_SKIP_BOOTSTRAP: "1",
      },
    });
    const launch = await api.backendLaunchConfig();

    assert.equal(launch.root, backendRoot);
    assert.equal(launch.command, envPython);
    assert.equal(launch.entry, entry);
    assert.equal(launch.env.NAIA_USER_DATA_DIR, path.join(packageRoot, "user-data"));
    assert.equal(launch.env.NAIA_RESOURCE_ROOT, backendRoot);
    assert.equal(launch.env.NAIA_REMOTE_WEB_DIR, path.join(backendRoot, "app", "web", "remote"));
    assert.equal(launch.env.PYTHONPYCACHEPREFIX, path.join(packageRoot, "user-data", "cache", "python-bytecode"));
    assert.equal(api.packagedPythonExecutable(), basePython);
    assert.equal(api.runtimeEnvRoot(), path.join(packageRoot, "user-data", "runtime-env"));
    assert.equal(api.pythonBytecodeCacheRoot(), path.join(packageRoot, "user-data", "cache", "python-bytecode"));
  } finally {
    fs.rmSync(packageRoot, { recursive: true, force: true });
  }
});

test("packaged runtime env bootstrap creates env and installs requirements before backend launch", async () => {
  const packageRoot = fs.mkdtempSync(path.join(os.tmpdir(), "naia-electron-bootstrap-"));
  const calls = [];
  try {
    const resources = path.join(packageRoot, "resources");
    const backendRoot = path.join(resources, "naia-backend");
    const entry = path.join(backendRoot, "NAIA_web_headless.py");
    const basePython = path.join(resources, "python", "python.exe");
    const userDataRoot = path.join(packageRoot, "user-data");
    const envPython = path.join(userDataRoot, "runtime-env", "Scripts", "python.exe");
    const generatedBytecode = path.join(resources, "python", "Lib", "__pycache__", "venv.cpython-310.pyc");
    writeFile(entry, "print('ok')\n");
    writeFile(path.join(backendRoot, "requirements-headless.txt"), "fastapi\n");
    writeFile(basePython, "python");
    mkdirp(userDataRoot);

    const spawnImpl = (command, args) => {
      calls.push({ command, args: Array.from(args) });
      if (args.includes("venv")) {
        writeFile(envPython, "python");
        writeFile(generatedBytecode, "bytecode");
      }
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      setImmediate(() => {
        if (args.includes("install")) {
          child.stdout.emit("data", "Collecting fastapi\n");
          child.stdout.emit("data", "Downloading starlette-0.50.0-py3-none-any.whl (74 kB)\n");
          child.stdout.emit("data", "Installing collected packages: starlette, fastapi\n");
          child.stdout.emit("data", "Successfully installed fastapi starlette\n");
        }
        child.emit("exit", 0, null);
      });
      return child;
    };

    const { api } = loadMain({
      isPackaged: true,
      resourcesPath: resources,
      exePath: path.join(packageRoot, "NAIA.exe"),
      spawnImpl,
    });
    const launch = await api.backendLaunchConfig();

    assert.equal(launch.command, envPython);
    assert.equal(calls.length, 2);
    assert.deepEqual(calls[0], {
      command: basePython,
      args: ["-B", "-m", "venv", path.join(userDataRoot, "runtime-env")],
    });
    assert.equal(calls[1].command, envPython);
    assert.deepEqual(calls[1].args.slice(0, 5), [
      "-B",
      "-m",
      "pip",
      "install",
      "--disable-pip-version-check",
    ]);
    assert.equal(calls[1].args.at(-2), "-r");
    assert.equal(calls[1].args.at(-1), path.join(backendRoot, "requirements-headless.txt"));
    assert.equal(api.runtimeEnvReady(backendRoot), true);
    assert.ok(fs.existsSync(api.runtimeEnvMarker()));
    assert.equal(fs.existsSync(generatedBytecode), false);
    const state = api.shellState().runtimeBootstrap;
    assert.equal(state.ready, true);
    assert.equal(state.percent, 100);
    assert.equal(state.phase, "ready");
    assert.equal(state.processedCount >= 2, true);
  } finally {
    fs.rmSync(packageRoot, { recursive: true, force: true });
  }
});

test("runtime bootstrap parser exposes package install progress", () => {
  const { api } = loadMain();
  const collecting = api.runtimeBootstrapProgressFromLine("Collecting fastapi", {
    phase: "installing-requirements",
    percent: 35,
    processedCount: 0,
    expectedCount: 3,
  });
  assert.equal(collecting.currentPackage, "fastapi");
  assert.equal(collecting.processedCount, 1);
  assert.equal(collecting.percent, 37);

  const installing = api.runtimeBootstrapProgressFromLine(
    "Installing collected packages: starlette, fastapi",
    collecting,
  );
  assert.equal(installing.phase, "installing-packages");
  assert.equal(installing.expectedCount, 3);
  assert.equal(installing.percent >= 90, true);

  const done = api.runtimeBootstrapProgressFromLine("Successfully installed fastapi starlette", installing);
  assert.equal(done.phase, "requirements-ready");
  assert.equal(done.percent, 96);
  assert.equal(done.processedCount, 2);
});

test("bundled Python bytecode cleanup is scoped to the packaged runtime", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "naia-electron-bytecode-"));
  try {
    const runtimeRoot = path.join(root, "resources", "python");
    const pycacheFile = path.join(runtimeRoot, "Lib", "__pycache__", "module.cpython-310.pyc");
    const nestedBytecode = path.join(runtimeRoot, "Lib", "pkg", "cached.pyo");
    const normalFile = path.join(runtimeRoot, "Lib", "module.py");
    writeFile(pycacheFile, "bytecode");
    writeFile(nestedBytecode, "bytecode");
    writeFile(normalFile, "print('keep')\n");

    const { api } = loadMain({
      isPackaged: true,
      resourcesPath: path.join(root, "resources"),
      exePath: path.join(root, "NAIA.exe"),
    });
    const removed = api.removePythonRuntimeBytecode(runtimeRoot);

    assert.equal(removed.pycacheDirs, 1);
    assert.equal(removed.bytecodeFiles, 1);
    assert.equal(fs.existsSync(pycacheFile), false);
    assert.equal(fs.existsSync(nestedBytecode), false);
    assert.equal(fs.existsSync(normalFile), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("browser fallback opens only http and https URLs", () => {
  const { api, opened } = loadMain();

  assert.equal(api.openBrowserFallbackUrl("naia-open-browser://open?url=https%3A%2F%2Fexample.com%2Fdocs"), true);
  assert.deepEqual(opened, ["https://example.com/docs"]);
  assert.equal(api.openBrowserFallbackUrl("naia-open-browser://open?url=file%3A%2F%2FC%3A%2Fsecret.txt"), false);
  assert.equal(api.openBrowserFallbackUrl("https://example.com/direct"), false);
});

test("remote entry URL carries the Electron shell query contract", () => {
  const { api } = loadMain();

  assert.equal(api.ENTRY_QUERY, "desktop_shell=1&electron_shell=1");
  assert.equal(api.remoteEntryUrl("http://127.0.0.1:7243"), "http://127.0.0.1:7243/?desktop_shell=1&electron_shell=1");
});

test("app icon path points at packaged Electron icon asset", () => {
  const { api } = loadMain();

  assert.equal(api.appIconPath(), path.join(ELECTRON_ROOT, "assets", "naia.ico"));
  assert.equal(fs.existsSync(api.appIconPath()), true);
});

test("afterPack reapplies the NAIA icon resource for unsigned Windows dir builds", () => {
  const source = fs.readFileSync(path.join(ELECTRON_ROOT, "packaging", "afterPack.cjs"), "utf8");
  const helper = fs.readFileSync(path.resolve(ELECTRON_ROOT, "..", "..", "tools", "apply_windows_exe_icon.py"), "utf8");

  assert.match(source, /apply_windows_exe_icon\.py/);
  assert.match(source, /NAIA\.exe/);
  assert.match(source, /naia\.ico/);
  assert.match(source, /spawnSync/);
  assert.match(source, /process\.platform !== "win32"/);
  assert.match(helper, /LANG_EN_US = 1033/);
  assert.match(helper, /language_ids: tuple\[int, \.\.\.\] = \(LANG_NEUTRAL, LANG_EN_US\)/);
});

test("packaged CDP smoke allows first-run runtime bootstrap time", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(ELECTRON_ROOT, "package.json"), "utf8"));

  assert.match(manifest.scripts["smoke:electron:packaged"], /--package-root app\/electron\/dist\/win-unpacked/);
  assert.match(manifest.scripts["smoke:electron:packaged"], /--timeout 240/);
});

test("startup window uses compact bounds before expanding to the app shell", () => {
  const { api } = loadMain();

  assert.equal(api.STARTUP_WINDOW_BOUNDS.width, 900);
  assert.equal(api.STARTUP_WINDOW_BOUNDS.height, 600);
  assert.equal(api.STARTUP_WINDOW_BOUNDS.minWidth, 760);
  assert.equal(api.STARTUP_WINDOW_BOUNDS.minHeight, 480);
  assert.equal(api.APP_WINDOW_BOUNDS.width, 1280);
  assert.equal(api.APP_WINDOW_BOUNDS.height, 860);
  assert.equal(api.APP_WINDOW_BOUNDS.minWidth, 960);
  assert.equal(api.APP_WINDOW_BOUNDS.minHeight, 640);
});

test("application menu is hidden for packaged builds and opt-in for source runs", () => {
  const packaged = loadMain({ isPackaged: true });
  assert.equal(packaged.api.HIDE_MENU_ENV, "NAIA_ELECTRON_HIDE_MENU");
  assert.equal(packaged.api.shouldHideApplicationMenu(), true);
  assert.equal(packaged.api.configureApplicationMenu(), true);
  assert.deepEqual(packaged.menuCalls, [null]);

  const sourceDefault = loadMain();
  assert.equal(sourceDefault.api.shouldHideApplicationMenu(), false);
  assert.equal(sourceDefault.api.configureApplicationMenu(), false);
  assert.deepEqual(sourceDefault.menuCalls, []);

  const sourceOptIn = loadMain({ env: { NAIA_ELECTRON_HIDE_MENU: "1" } });
  assert.equal(sourceOptIn.api.shouldHideApplicationMenu(), true);
  assert.equal(sourceOptIn.api.configureApplicationMenu(), true);
  assert.deepEqual(sourceOptIn.menuCalls, [null]);
});

test("remote debugging switch is opt-in for CDP smoke automation", () => {
  const { api, app } = loadMain({
    env: {
      NAIA_ELECTRON_REMOTE_DEBUGGING_PORT: "9335",
    },
  });

  assert.equal(api.REMOTE_DEBUGGING_ENV, "NAIA_ELECTRON_REMOTE_DEBUGGING_PORT");
  assert.equal(api.remoteDebuggingPort(), 9335);
  assert.deepEqual(app.commandLine.switches, [
    ["remote-debugging-port", "9335"],
    ["remote-allow-origins", "*"],
  ]);
});

test("runtime install gate is packaged-only by default with explicit source override", () => {
  const sourceDefault = loadMain();
  assert.equal(sourceDefault.api.RUNTIME_INSTALL_FORCE_ENV, "NAIA_ELECTRON_RUNTIME_INSTALL");
  assert.equal(sourceDefault.api.RUNTIME_INSTALL_SKIP_ENV, "NAIA_ELECTRON_SKIP_RUNTIME_INSTALL");
  assert.equal(sourceDefault.api.shouldRunRuntimeInstallGate(), false);

  const sourceForced = loadMain({ env: { NAIA_ELECTRON_RUNTIME_INSTALL: "1" } });
  assert.equal(sourceForced.api.shouldRunRuntimeInstallGate(), true);

  const packaged = loadMain({ isPackaged: true });
  assert.equal(packaged.api.shouldRunRuntimeInstallGate(), true);

  const packagedSkipped = loadMain({
    isPackaged: true,
    env: { NAIA_ELECTRON_SKIP_RUNTIME_INSTALL: "1" },
  });
  assert.equal(packagedSkipped.api.shouldRunRuntimeInstallGate(), false);
});

test("runtime install gate waits for a user choice and never auto-downloads", async () => {
  // Contract: the gate initializes, then parks until the install-manager
  // reports ready. It must NOT POST /tag-archive/download itself — starting the
  // Hugging Face download (or importing from a previous install) is now an
  // explicit user choice in the maintenance window. The poll here simulates the
  // user having started a download externally (download.active on the first
  // poll) which then completes (ready on the second poll).
  const calls = [];
  let polls = 0;
  const server = http.createServer((req, res) => {
    calls.push(`${req.method} ${req.url}`);
    res.setHeader("content-type", "application/json");
    if (req.method === "POST" && req.url === "/api/install-manager/initialize") {
      res.end(JSON.stringify({
        ok: true,
        tag_archive: {
          ready: false,
          file_count: 0,
          expected_count: 2,
          download: { active: false, phase: "idle", percent: 0, message: "" },
        },
      }));
      return;
    }
    if (req.method === "GET" && req.url === "/api/install-manager") {
      polls += 1;
      res.end(JSON.stringify({
        ok: true,
        tag_archive: {
          ready: polls >= 2,
          file_count: polls >= 2 ? 2 : 1,
          expected_count: 2,
          download: {
            active: polls < 2,
            phase: polls >= 2 ? "complete" : "tag_archive",
            percent: polls >= 2 ? 100 : 55,
            message: polls >= 2 ? "complete" : "downloading",
            done: polls >= 2,
          },
        },
      }));
      return;
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ ok: false, error: "not found" }));
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const { api } = loadMain({ isPackaged: true });
    const address = server.address();
    const ready = await api.ensureRuntimeInstallReady(`http://127.0.0.1:${address.port}`, {
      pollIntervalMs: 5,
      timeoutMs: 1000,
    });

    assert.equal(ready, true);
    assert.ok(
      !calls.includes("POST /api/install-manager/tag-archive/download"),
      "gate must not auto-trigger the tag-archive download",
    );
    assert.equal(calls[0], "POST /api/install-manager/initialize");
    assert.deepEqual(calls.slice(1), [
      "GET /api/install-manager",
      "GET /api/install-manager",
    ]);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("runtime install gate auto-downloads when NAIA_ELECTRON_AUTO_TAG_DOWNLOAD=1", async () => {
  // Automated/CI path (the CDP release smoke): no human picks a choice and the
  // random-prompt round-trip needs tag data, so the gate auto-starts the
  // download exactly as it did before the interactive choice was introduced.
  const calls = [];
  let polls = 0;
  const server = http.createServer((req, res) => {
    calls.push(`${req.method} ${req.url}`);
    res.setHeader("content-type", "application/json");
    if (req.method === "POST" && req.url === "/api/install-manager/initialize") {
      res.end(JSON.stringify({
        ok: true,
        tag_archive: {
          ready: false, file_count: 0, expected_count: 2,
          download: { active: false, phase: "idle", percent: 0, message: "" },
        },
      }));
      return;
    }
    if (req.method === "POST" && req.url === "/api/install-manager/tag-archive/download") {
      res.end(JSON.stringify({
        ok: true,
        tag_archive: {
          ready: false, file_count: 0, expected_count: 2,
          download: { active: true, phase: "tag_archive", percent: 10, message: "downloading" },
        },
      }));
      return;
    }
    if (req.method === "GET" && req.url === "/api/install-manager") {
      polls += 1;
      res.end(JSON.stringify({
        ok: true,
        tag_archive: {
          ready: polls >= 2, file_count: polls >= 2 ? 2 : 1, expected_count: 2,
          download: {
            active: polls < 2,
            phase: polls >= 2 ? "complete" : "tag_archive",
            percent: polls >= 2 ? 100 : 55,
            message: polls >= 2 ? "complete" : "downloading",
            done: polls >= 2,
          },
        },
      }));
      return;
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ ok: false, error: "not found" }));
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const { api } = loadMain({ isPackaged: true, env: { NAIA_ELECTRON_AUTO_TAG_DOWNLOAD: "1" } });
    const address = server.address();
    const ready = await api.ensureRuntimeInstallReady(`http://127.0.0.1:${address.port}`, {
      pollIntervalMs: 5,
      timeoutMs: 1000,
    });

    assert.equal(ready, true);
    assert.equal(calls[0], "POST /api/install-manager/initialize");
    assert.equal(calls[1], "POST /api/install-manager/tag-archive/download");
    assert.ok(
      calls.slice(2).every((c) => c === "GET /api/install-manager"),
      "after auto-download the gate only polls",
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
