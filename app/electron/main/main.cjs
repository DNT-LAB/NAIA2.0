"use strict";

const { app, BrowserWindow, dialog, ipcMain, Menu, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_BIND_HOST = "0.0.0.0";
const DEFAULT_PORT = 7243;
const HEALTH_PATH = "/api/status";
const LOG_LIMIT = 1000;
const PACKAGED_BACKEND_DIR = "naia-backend";
const ENTRY_QUERY = "desktop_shell=1&electron_shell=1";
const REMOTE_DEBUGGING_ENV = "NAIA_ELECTRON_REMOTE_DEBUGGING_PORT";
const HIDE_MENU_ENV = "NAIA_ELECTRON_HIDE_MENU";
const RUNTIME_INSTALL_FORCE_ENV = "NAIA_ELECTRON_RUNTIME_INSTALL";
const RUNTIME_INSTALL_SKIP_ENV = "NAIA_ELECTRON_SKIP_RUNTIME_INSTALL";
const RUNTIME_INSTALL_TIMEOUT_MS = 60 * 60 * 1000;
const RUNTIME_ENV_DIR = "runtime-env";
const RUNTIME_ENV_MARKER = "naia-runtime-env.json";
const RUNTIME_ENV_MARKER_SCHEMA = 1;
const PYTHON_BYTECODE_CACHE_DIR = path.join("cache", "python-bytecode");
const APP_ICON = path.join(__dirname, "..", "assets", "naia.ico");
// Auto-update: poll the GitHub releases API for the portable build and surface
// it to the Remote Web shell UI. Releases are tagged vX.Y.Z and carry the
// portable zip + a SHA256SUMS.txt that the apply step verifies against.
const UPDATE_REPO = "DNT-LAB/NAIA2.0";
const UPDATE_LATEST_RELEASE_URL = `https://api.github.com/repos/${UPDATE_REPO}/releases/latest`;
const UPDATE_RELEASES_PAGE_URL = `https://github.com/${UPDATE_REPO}/releases/latest`;
const UPDATE_PORTABLE_ASSET = "NAIA-Portable.zip";
const UPDATE_CHECKSUMS_ASSET = "SHA256SUMS.txt";
const UPDATE_USER_AGENT = "NAIA-Updater";
const UPDATE_DIR_NAME = ".updates";
// Windows in-place swap helper. The app's exe/resources can't be overwritten
// while running, so this PowerShell script is written to user-data/.updates at
// apply time, spawned detached, waits for the app to exit, then moves the live
// install (everything except the preserved user-data folder) into backup/ and
// the staged build into place, rolling back on failure, and relaunches.
// NOTE: kept free of ${...} and backticks so it survives the JS template literal.
const APPLY_SCRIPT_PS1 = `param([string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
function Write-ApplyLog($m) {
  try { "$([DateTime]::Now.ToString('s')) $m" | Out-File -LiteralPath $cfg.logPath -Append -Encoding utf8 } catch {}
}
function Move-WithRetry($src, $dest) {
  for ($r = 0; $r -lt 6; $r++) {
    try { Move-Item -LiteralPath $src -Destination $dest -Force; return } catch { Start-Sleep -Milliseconds 400 }
  }
  Move-Item -LiteralPath $src -Destination $dest -Force
}
function Remove-WithRetry($target) {
  if (-not (Test-Path -LiteralPath $target)) { return }
  for ($r = 0; $r -lt 6; $r++) {
    try { Remove-Item -LiteralPath $target -Recurse -Force } catch { Start-Sleep -Milliseconds 400 }
    if (-not (Test-Path -LiteralPath $target)) { return }
  }
}
Write-ApplyLog "apply start pid=$($cfg.pid) install=$($cfg.installRoot)"
for ($i = 0; $i -lt 240; $i++) {
  $proc = Get-Process -Id $cfg.pid -ErrorAction SilentlyContinue
  if (-not $proc) { break }
  Start-Sleep -Milliseconds 500
}
Start-Sleep -Milliseconds 1000
$preserve = @($cfg.preserve)
if (Test-Path -LiteralPath $cfg.backupRoot) { Remove-Item -LiteralPath $cfg.backupRoot -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $cfg.backupRoot -Force | Out-Null
$moved = New-Object System.Collections.ArrayList
try {
  Get-ChildItem -LiteralPath $cfg.installRoot -Force | ForEach-Object {
    if ($preserve -contains $_.Name) { return }
    Move-WithRetry $_.FullName (Join-Path $cfg.backupRoot $_.Name)
    [void]$moved.Add($_.Name)
  }
  Get-ChildItem -LiteralPath $cfg.stagedRoot -Force | ForEach-Object {
    if ($preserve -contains $_.Name) { return }
    Move-WithRetry $_.FullName (Join-Path $cfg.installRoot $_.Name)
  }
  Write-ApplyLog "swap ok"
} catch {
  Write-ApplyLog "swap FAILED: $_ rolling back"
  foreach ($name in $moved) {
    $cur = Join-Path $cfg.installRoot $name
    if (Test-Path -LiteralPath $cur) { Remove-Item -LiteralPath $cur -Recurse -Force -ErrorAction SilentlyContinue }
    $bak = Join-Path $cfg.backupRoot $name
    if (Test-Path -LiteralPath $bak) { Move-Item -LiteralPath $bak -Destination $cur -Force -ErrorAction SilentlyContinue }
  }
  Write-ApplyLog "rollback done"
}
foreach ($d in @($cfg.cleanupDirs)) {
  try { Remove-WithRetry $d; Write-ApplyLog "cleaned $d" } catch { Write-ApplyLog "cleanup FAILED $d : $_" }
}
Write-ApplyLog "relaunch $($cfg.exePath)"
try { Start-Process -FilePath $cfg.exePath } catch { Write-ApplyLog "relaunch FAILED: $_" }
Write-ApplyLog "apply end"
`;
const STARTUP_WINDOW_BOUNDS = Object.freeze({
  width: 680,
  height: 420,
  minWidth: 560,
  minHeight: 360,
});
const APP_WINDOW_BOUNDS = Object.freeze({
  width: 1280,
  height: 860,
  minWidth: 960,
  minHeight: 640,
});

let mainWindow = null;
let backendProcess = null;
let backendState = "stopped";
let backendPort = readPort(process.env.NAIA_BACKEND_PORT, DEFAULT_PORT);
let backendUrl = buildRemoteUrl(backendPort);
let backendLogs = [];
let startingBackend = null;
let runtimeInstallGate = null;
let runtimeInstallState = null;
let runtimeBootstrapState = null;
let quitting = false;
let backendPortConfirmed = false;
let cachedAppVersion = null;
let updateCheckPromise = null;
let updateDownloadPromise = null;
let updateState = {
  phase: "idle", // idle | checking | available | up-to-date | error | downloading | downloaded | applying
  currentVersion: null,
  latestVersion: null,
  releaseTag: "",
  releaseUrl: "",
  releaseNotes: "",
  publishedAt: "",
  assetUrl: "",
  assetSize: 0,
  checksumsUrl: "",
  downloadPercent: 0,
  downloadedBytes: 0,
  verified: false,
  error: "",
  checkedAt: null,
  updatedAt: null,
};

function readPort(value, fallback) {
  const parsed = Number.parseInt(value || "", 10);
  if (Number.isInteger(parsed) && parsed >= 1024 && parsed <= 65535) {
    return parsed;
  }
  return fallback;
}

function remoteDebuggingPort() {
  return readPort(process.env[REMOTE_DEBUGGING_ENV], 0);
}

function configureRemoteDebugging() {
  const port = remoteDebuggingPort();
  if (!port || !app.commandLine) {
    return false;
  }
  app.commandLine.appendSwitch("remote-debugging-port", String(port));
  app.commandLine.appendSwitch("remote-allow-origins", "*");
  return true;
}

function shouldHideApplicationMenu() {
  return app.isPackaged || process.env[HIDE_MENU_ENV] === "1";
}

function configureApplicationMenu() {
  if (!shouldHideApplicationMenu()) {
    return false;
  }
  Menu.setApplicationMenu(null);
  return true;
}

function repoRoot() {
  if (process.env.NAIA_REPO_ROOT) {
    return path.resolve(process.env.NAIA_REPO_ROOT);
  }
  return path.resolve(__dirname, "..", "..", "..");
}

function resourcesRoot() {
  if (process.env.NAIA_RESOURCE_ROOT) {
    return path.resolve(process.env.NAIA_RESOURCE_ROOT);
  }
  if (app.isPackaged) {
    return process.resourcesPath;
  }
  return repoRoot();
}

function packagedBackendRoot() {
  return path.join(resourcesRoot(), PACKAGED_BACKEND_DIR);
}

function backendRoot() {
  if (process.env.NAIA_BACKEND_ROOT) {
    return path.resolve(process.env.NAIA_BACKEND_ROOT);
  }
  const packagedRoot = packagedBackendRoot();
  if (fs.existsSync(path.join(packagedRoot, "NAIA_web_headless.py"))
    || fs.existsSync(path.join(packagedRoot, "NAIA_web_headless.exe"))) {
    return packagedRoot;
  }
  return repoRoot();
}

function backendEntry(root) {
  if (process.env.NAIA_BACKEND_ENTRY) {
    return path.resolve(process.env.NAIA_BACKEND_ENTRY);
  }
  const executable = process.platform === "win32"
    ? path.join(root, "NAIA_web_headless.exe")
    : path.join(root, "NAIA_web_headless");
  if (fs.existsSync(executable)) {
    return executable;
  }
  return path.join(root, "NAIA_web_headless.py");
}

function packagedPythonExecutable() {
  const candidate = process.platform === "win32"
    ? path.join(resourcesRoot(), "python", "python.exe")
    : path.join(resourcesRoot(), "python", "bin", "python");
  return fs.existsSync(candidate) ? candidate : null;
}

function sourceVenvPython(root) {
  const candidate = process.platform === "win32"
    ? path.join(root, "venv", "Scripts", "python.exe")
    : path.join(root, "venv", "bin", "python");
  return fs.existsSync(candidate) ? candidate : null;
}

function runtimeEnvRoot() {
  if (process.env.NAIA_RUNTIME_ENV_DIR) {
    return path.resolve(process.env.NAIA_RUNTIME_ENV_DIR);
  }
  return path.join(runtimeDataRoot(), RUNTIME_ENV_DIR);
}

function pythonBytecodeCacheRoot() {
  if (process.env.PYTHONPYCACHEPREFIX) {
    return path.resolve(process.env.PYTHONPYCACHEPREFIX);
  }
  return path.join(runtimeDataRoot(), PYTHON_BYTECODE_CACHE_DIR);
}

function removePythonRuntimeBytecode(root = path.join(resourcesRoot(), "python")) {
  const runtimeRoot = path.resolve(root);
  const removed = { pycacheDirs: 0, bytecodeFiles: 0 };
  if (!fs.existsSync(runtimeRoot)) {
    return removed;
  }

  function visit(directory) {
    let entries;
    try {
      entries = fs.readdirSync(directory, { withFileTypes: true });
    } catch (_error) {
      return;
    }

    for (const entry of entries) {
      const fullPath = path.join(directory, entry.name);
      const relative = path.relative(runtimeRoot, fullPath);
      if (relative.startsWith("..") || path.isAbsolute(relative)) {
        continue;
      }
      if (entry.isDirectory()) {
        if (entry.name === "__pycache__") {
          fs.rmSync(fullPath, { recursive: true, force: true });
          removed.pycacheDirs += 1;
        } else {
          visit(fullPath);
        }
      } else if (entry.isFile() && /\.(pyc|pyo)$/i.test(entry.name)) {
        fs.rmSync(fullPath, { force: true });
        removed.bytecodeFiles += 1;
      }
    }
  }

  visit(runtimeRoot);
  return removed;
}

function runtimeEnvPython() {
  return process.platform === "win32"
    ? path.join(runtimeEnvRoot(), "Scripts", "python.exe")
    : path.join(runtimeEnvRoot(), "bin", "python");
}

function runtimeEnvMarker() {
  return path.join(runtimeEnvRoot(), RUNTIME_ENV_MARKER);
}

function requirementsPath(root) {
  return path.join(root, "requirements-headless.txt");
}

function wheelhousePath() {
  return path.join(resourcesRoot(), "wheelhouse");
}

function hashFile(filePath) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  return hash.digest("hex");
}

function requirementsFingerprint(root) {
  const requirements = requirementsPath(root);
  if (!fs.existsSync(requirements)) {
    return "missing";
  }
  return hashFile(requirements);
}

function countRuntimeRequirements(root) {
  const requirements = requirementsPath(root);
  if (!fs.existsSync(requirements)) {
    return 0;
  }
  return fs.readFileSync(requirements, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#") && !line.startsWith("-"))
    .length;
}

function runtimeEnvReady(root) {
  const python = runtimeEnvPython();
  if (!fs.existsSync(python)) {
    return false;
  }
  if (process.env.NAIA_RUNTIME_ENV_SKIP_BOOTSTRAP === "1") {
    return true;
  }
  const marker = runtimeEnvMarker();
  if (!fs.existsSync(marker)) {
    return false;
  }
  try {
    const payload = JSON.parse(fs.readFileSync(marker, "utf8"));
    return payload.schema_version === RUNTIME_ENV_MARKER_SCHEMA
      && payload.requirements_sha256 === requirementsFingerprint(root);
  } catch (_error) {
    return false;
  }
}

function setRuntimeBootstrapState(state) {
  runtimeBootstrapState = {
    ...(runtimeBootstrapState || {}),
    ...state,
    updatedAt: new Date().toISOString(),
  };
  broadcastShellState();
}

function runtimeBootstrapProgressFromLine(line, currentState = runtimeBootstrapState || {}) {
  const text = String(line || "").trim();
  if (!text) {
    return null;
  }
  const state = currentState || {};
  let processedCount = Number(state.processedCount || 0);
  let expectedCount = Number(state.expectedCount || 0);
  let currentPackage = String(state.currentPackage || "");
  let message = text;
  let phase = String(state.phase || "installing-requirements");
  let percent = Number(state.percent || 35);

  const packageMatch = text.match(/^(?:Collecting|Downloading|Using cached)\s+([^\s(]+)/i);
  if (packageMatch) {
    processedCount += 1;
    currentPackage = packageMatch[1];
    message = `Python package: ${currentPackage}`;
    percent = Math.min(88, 35 + processedCount * 2);
  }

  const installingMatch = text.match(/^Installing collected packages:\s*(.+)$/i);
  if (installingMatch) {
    const packages = installingMatch[1].split(",").map((item) => item.trim()).filter(Boolean);
    expectedCount = Math.max(expectedCount, packages.length);
    currentPackage = packages[0] || currentPackage;
    message = `Installing ${packages.length || expectedCount || ""} Python packages`.trim();
    phase = "installing-packages";
    percent = Math.max(percent, 90);
  }

  const successMatch = text.match(/^Successfully installed\s+(.+)$/i);
  if (successMatch) {
    const packages = successMatch[1].split(/\s+/).filter(Boolean);
    expectedCount = Math.max(expectedCount, packages.length);
    processedCount = Math.max(processedCount, packages.length);
    currentPackage = "";
    message = "Python packages installed.";
    phase = "requirements-ready";
    percent = 96;
  }

  return {
    active: true,
    ready: false,
    phase,
    percent,
    message,
    processedCount,
    expectedCount,
    currentPackage,
  };
}

function updateRuntimeBootstrapFromOutput(chunk) {
  for (const line of String(chunk || "").split(/\r?\n/)) {
    const update = runtimeBootstrapProgressFromLine(line);
    if (update) {
      setRuntimeBootstrapState(update);
    }
  }
}

function runBootstrapCommand(label, command, args, options = {}) {
  appendBackendLog("shell", `${label}: ${command} ${args.join(" ")}`);
  fs.mkdirSync(pythonBytecodeCacheRoot(), { recursive: true });
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd || backendRoot(),
      env: {
        ...process.env,
        ...(options.env || {}),
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONPYCACHEPREFIX: pythonBytecodeCacheRoot(),
        PYTHONUTF8: "1",
        PYTHONIOENCODING: "utf-8",
      },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => {
      appendBackendLog("stdout", chunk);
      if (typeof options.onOutput === "function") {
        options.onOutput(chunk, "stdout");
      }
    });
    child.stderr.on("data", (chunk) => {
      appendBackendLog("stderr", chunk);
      if (typeof options.onOutput === "function") {
        options.onOutput(chunk, "stderr");
      }
    });
    child.on("error", (error) => reject(new Error(`${label} failed: ${error.message}`)));
    child.on("exit", (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${label} failed: exit=${code} signal=${signal}`));
    });
  });
}

function writeRuntimeEnvMarker(root, basePython) {
  const marker = {
    schema_version: RUNTIME_ENV_MARKER_SCHEMA,
    requirements_sha256: requirementsFingerprint(root),
    requirements_path: requirementsPath(root),
    base_python: basePython,
    env_python: runtimeEnvPython(),
    created_at: new Date().toISOString(),
  };
  fs.writeFileSync(runtimeEnvMarker(), JSON.stringify(marker, null, 2) + "\n", "utf8");
}

async function ensureManagedRuntimeEnv(root) {
  if (!app.isPackaged) {
    return null;
  }
  const basePython = packagedPythonExecutable();
  if (!basePython) {
    return null;
  }
  if (runtimeEnvReady(root)) {
    setRuntimeBootstrapState({
      active: false,
      ready: true,
      phase: "ready",
      percent: 100,
      message: "Python runtime is ready.",
      error: "",
    });
    return runtimeEnvPython();
  }

  const requirements = requirementsPath(root);
  if (!fs.existsSync(requirements)) {
    throw new Error(`Headless requirements file not found: ${requirements}`);
  }

  fs.mkdirSync(runtimeDataRoot(), { recursive: true });
  fs.mkdirSync(runtimeEnvRoot(), { recursive: true });

  try {
    if (!fs.existsSync(runtimeEnvPython())) {
      setRuntimeBootstrapState({
        active: true,
        ready: false,
        phase: "creating-env",
        percent: 8,
        message: "Creating isolated Python runtime environment.",
        stepCurrent: 1,
        stepTotal: 2,
        processedCount: 0,
        expectedCount: 0,
        currentPackage: "",
        error: "",
      });
      await runBootstrapCommand("Creating NAIA runtime env", basePython, ["-B", "-m", "venv", runtimeEnvRoot()], {
        cwd: root,
      });
      setRuntimeBootstrapState({
        active: true,
        ready: false,
        phase: "env-ready",
        percent: 28,
        message: "Python runtime environment created.",
        stepCurrent: 1,
        stepTotal: 2,
      });
      const removed = removePythonRuntimeBytecode();
      if (removed.pycacheDirs || removed.bytecodeFiles) {
        appendBackendLog("shell", `Cleaned bundled Python bytecode after venv bootstrap: ${JSON.stringify(removed)}`);
      }
    } else {
      setRuntimeBootstrapState({
        active: true,
        ready: false,
        phase: "env-ready",
        percent: 28,
        message: "Python runtime environment exists.",
        stepCurrent: 1,
        stepTotal: 2,
        processedCount: 0,
        expectedCount: 0,
        currentPackage: "",
        error: "",
      });
    }

    const pipArgs = [
      "-B",
      "-m",
      "pip",
      "install",
      "--disable-pip-version-check",
    ];
    const wheelhouse = wheelhousePath();
    if (fs.existsSync(wheelhouse)) {
      if (process.env.NAIA_PIP_NO_INDEX === "1") {
        pipArgs.push("--no-index");
      }
      pipArgs.push("--find-links", wheelhouse);
    }
    pipArgs.push("-r", requirements);
    setRuntimeBootstrapState({
      active: true,
      ready: false,
      phase: "installing-requirements",
      percent: 35,
      message: "Installing Python packages.",
      stepCurrent: 2,
      stepTotal: 2,
      processedCount: 0,
      expectedCount: countRuntimeRequirements(root),
      currentPackage: "",
      error: "",
    });
    await runBootstrapCommand("Installing NAIA runtime requirements", runtimeEnvPython(), pipArgs, {
      cwd: root,
      onOutput: updateRuntimeBootstrapFromOutput,
    });
    const removed = removePythonRuntimeBytecode();
    if (removed.pycacheDirs || removed.bytecodeFiles) {
      appendBackendLog("shell", `Cleaned bundled Python bytecode after requirements bootstrap: ${JSON.stringify(removed)}`);
    }
    writeRuntimeEnvMarker(root, basePython);
    setRuntimeBootstrapState({
      active: false,
      ready: true,
      phase: "ready",
      percent: 100,
      message: "Python runtime is ready.",
      currentPackage: "",
      error: "",
    });
    return runtimeEnvPython();
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    setRuntimeBootstrapState({
      active: false,
      ready: false,
      phase: "error",
      percent: Number(runtimeBootstrapState && runtimeBootstrapState.percent || 0),
      message,
      error: message,
    });
    throw error;
  }
}

async function pythonExecutable(root) {
  if (process.env.NAIA_PYTHON) {
    return process.env.NAIA_PYTHON;
  }

  const managedPython = await ensureManagedRuntimeEnv(root);
  if (managedPython) {
    return managedPython;
  }

  const venvPython = sourceVenvPython(root);
  if (venvPython) {
    return venvPython;
  }
  return "python";
}

async function backendCommand(root) {
  const entry = backendEntry(root);
  if (!fs.existsSync(entry)) {
    throw new Error(`Backend entrypoint not found: ${entry}`);
  }
  if (entry.endsWith(".py")) {
    return {
      command: await pythonExecutable(root),
      args: ["-B", entry],
      entry,
    };
  }
  return {
    command: entry,
    args: [],
    entry,
  };
}

function backendArgs() {
  return [
    "--host",
    process.env.NAIA_BACKEND_BIND_HOST || DEFAULT_BIND_HOST,
    "--port",
    String(backendPort),
    "--auto-port",
    "--no-browser",
  ];
}

function backendEnvironment(root) {
  return {
    ...process.env,
    NAIA_ELECTRON: "1",
    NAIA_HEADLESS_OPEN_BROWSER: "0",
    NAIA_RESOURCE_ROOT: process.env.NAIA_RESOURCE_ROOT || root,
    NAIA_REMOTE_WEB_DIR: process.env.NAIA_REMOTE_WEB_DIR || path.join(root, "app", "web", "remote"),
    NAIA_USER_DATA_DIR: runtimeDataRoot(),
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONPYCACHEPREFIX: pythonBytecodeCacheRoot(),
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  };
}

async function backendLaunchConfig() {
  const root = backendRoot();
  const backend = await backendCommand(root);
  return {
    root,
    command: backend.command,
    args: [...backend.args, ...backendArgs()],
    entry: backend.entry,
    env: backendEnvironment(root),
  };
}

function buildRemoteUrl(port) {
  return `http://${DEFAULT_HOST}:${port}`;
}

function appendBackendLog(source, chunk) {
  const text = String(chunk || "");
  for (const line of text.split(/\r?\n/)) {
    if (!line) {
      continue;
    }
    backendLogs.push({ source, line, time: new Date().toISOString() });
    parseBackendPort(line);
  }
  if (backendLogs.length > LOG_LIMIT) {
    backendLogs = backendLogs.slice(-LOG_LIMIT);
  }
  broadcastShellState();
}

function parseBackendPort(line) {
  const match = line.match(/backend:\s+http:\/\/127\.0\.0\.1:(\d+)/i)
    || line.match(/using\s+(\d+)\./i);
  if (!match) {
    return;
  }

  const parsed = readPort(match[1], backendPort);
  backendPortConfirmed = true;
  if (parsed !== backendPort) {
    backendPort = parsed;
    backendUrl = buildRemoteUrl(backendPort);
  }
}

function shellState() {
  return {
    backendState,
    backendPort,
    backendUrl,
    backendRoot: backendRoot(),
    resourcesRoot: resourcesRoot(),
    runtimeDataRoot: runtimeDataRoot(),
    runtimeEnvRoot: runtimeEnvRoot(),
    runtimeBootstrap: runtimeBootstrapState,
    runtimeInstall: runtimeInstallState,
    healthUrl: `${backendUrl}${HEALTH_PATH}`,
    logs: backendLogs.slice(-200),
    appVersion: currentAppVersion(),
    update: updateState,
  };
}

function broadcastShellState() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("naia:shell-state-changed", shellState());
  }
}

async function startBackendProcess() {
  const launch = await backendLaunchConfig();
  backendPortConfirmed = false;
  const child = spawn(launch.command, launch.args, {
    cwd: launch.root,
    env: launch.env,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess = child;
  backendState = "starting";
  appendBackendLog("shell", `Starting backend: ${launch.command} ${launch.args.join(" ")}`);

  child.stdout.on("data", (chunk) => appendBackendLog("stdout", chunk));
  child.stderr.on("data", (chunk) => appendBackendLog("stderr", chunk));
  child.on("error", (error) => {
    backendState = "error";
    appendBackendLog("shell", `Backend failed to start: ${error.message}`);
  });
  child.on("exit", (code, signal) => {
    backendProcess = null;
    backendState = quitting ? "stopped" : "exited";
    appendBackendLog("shell", `Backend exited with code=${code} signal=${signal}`);
  });
}

function requestHealth(port, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const req = http.get(`${buildRemoteUrl(port)}${HEALTH_PATH}`, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 500);
    });
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.on("error", () => resolve(false));
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function shouldRunRuntimeInstallGate() {
  if (process.env[RUNTIME_INSTALL_SKIP_ENV] === "1") {
    return false;
  }
  return app.isPackaged || process.env[RUNTIME_INSTALL_FORCE_ENV] === "1";
}

function runtimeInstallReadyFromPayload(payload) {
  return !!(payload && payload.tag_archive && payload.tag_archive.ready);
}

function runtimeInstallErrorFromPayload(payload) {
  if (!payload || payload.ok === false) {
    return payload && payload.error ? String(payload.error) : "Runtime install manager returned an invalid response.";
  }
  const download = payload.tag_archive && payload.tag_archive.download ? payload.tag_archive.download : {};
  if (download.error && !download.active) {
    return String(download.error);
  }
  return "";
}

function normalizeRuntimeInstallState(payload, fallback = {}) {
  const archive = payload && payload.tag_archive ? payload.tag_archive : {};
  const download = archive.download || {};
  const ready = !!archive.ready;
  const error = runtimeInstallErrorFromPayload(payload);
  const active = !!download.active || !!fallback.active;
  let phase = String(fallback.phase || download.phase || "checking");
  if (ready) {
    phase = "ready";
  } else if (error) {
    phase = "error";
  } else if (download.phase && download.phase !== "idle") {
    phase = String(download.phase);
  }
  return {
    active,
    ready,
    phase,
    percent: Number(download.percent || (ready ? 100 : fallback.percent || 0)),
    message: String(
      fallback.message
      || download.message
      || (ready ? "태그 데이터 준비 완료" : "태그 데이터 설치 상태 확인 중...")
    ),
    error,
    fileCount: Number(archive.file_count || 0),
    expectedCount: Number(archive.expected_count || 0),
    updatedAt: new Date().toISOString(),
  };
}

function setRuntimeInstallState(state) {
  runtimeInstallState = {
    ...(runtimeInstallState || {}),
    ...state,
    updatedAt: new Date().toISOString(),
  };
  broadcastShellState();
}

function httpJsonRequest(targetUrl, options = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(targetUrl);
    const req = http.request(parsed, {
      method: options.method || "GET",
      timeout: options.timeoutMs || 10000,
      headers: {
        Accept: "application/json",
      },
    }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        let payload = {};
        if (body) {
          try {
            payload = JSON.parse(body);
          } catch (error) {
            reject(new Error(`Invalid JSON from ${targetUrl}: ${error.message}`));
            return;
          }
        }
        if (res.statusCode < 200 || res.statusCode >= 500) {
          reject(new Error(`HTTP ${res.statusCode} from ${targetUrl}: ${body.slice(0, 240)}`));
          return;
        }
        resolve(payload);
      });
    });
    req.on("timeout", () => {
      req.destroy(new Error(`Request timed out: ${targetUrl}`));
    });
    req.on("error", reject);
    req.end();
  });
}

// --- Auto-update -----------------------------------------------------------

function currentAppVersion() {
  if (cachedAppVersion) {
    return cachedAppVersion;
  }
  let version = "";
  try {
    if (typeof app.getVersion === "function") {
      version = String(app.getVersion() || "");
    }
  } catch (_error) {
    version = "";
  }
  if (!version) {
    try {
      const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
      version = String(pkg.version || "");
    } catch (_error) {
      version = "";
    }
  }
  cachedAppVersion = version || "0.0.0";
  return cachedAppVersion;
}

function parseVersionParts(value) {
  const core = String(value || "").trim().replace(/^v/i, "").split(/[-+]/)[0];
  return core.split(".").map((part) => Number.parseInt(part, 10) || 0);
}

function compareVersions(a, b) {
  const pa = parseVersionParts(a);
  const pb = parseVersionParts(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i += 1) {
    const da = pa[i] || 0;
    const db = pb[i] || 0;
    if (da > db) {
      return 1;
    }
    if (da < db) {
      return -1;
    }
  }
  return 0;
}

function httpsJsonRequest(targetUrl, options = {}) {
  return new Promise((resolve, reject) => {
    const req = https.request(targetUrl, {
      method: options.method || "GET",
      timeout: options.timeoutMs || 15000,
      headers: {
        "User-Agent": UPDATE_USER_AGENT,
        Accept: "application/vnd.github+json",
        ...(options.headers || {}),
      },
    }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode} from ${targetUrl}: ${body.slice(0, 200)}`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(new Error(`Invalid JSON from ${targetUrl}: ${error.message}`));
        }
      });
    });
    req.on("timeout", () => {
      req.destroy(new Error(`Request timed out: ${targetUrl}`));
    });
    req.on("error", reject);
    req.end();
  });
}

function parseLatestRelease(payload) {
  const tag = String((payload && payload.tag_name) || "");
  const assets = Array.isArray(payload && payload.assets) ? payload.assets : [];
  const findAsset = (name) => assets.find((asset) => asset && asset.name === name) || null;
  const portable = findAsset(UPDATE_PORTABLE_ASSET);
  const checksums = findAsset(UPDATE_CHECKSUMS_ASSET);
  return {
    version: tag.replace(/^v/i, ""),
    tag,
    releaseUrl: String((payload && payload.html_url) || UPDATE_RELEASES_PAGE_URL),
    releaseNotes: String((payload && payload.body) || ""),
    publishedAt: String((payload && payload.published_at) || ""),
    assetUrl: portable ? String(portable.browser_download_url || "") : "",
    assetSize: portable ? Number(portable.size || 0) : 0,
    checksumsUrl: checksums ? String(checksums.browser_download_url || "") : "",
  };
}

async function fetchLatestRelease() {
  const payload = await httpsJsonRequest(UPDATE_LATEST_RELEASE_URL);
  return parseLatestRelease(payload);
}

function setUpdateState(patch) {
  updateState = { ...updateState, ...patch, updatedAt: new Date().toISOString() };
  broadcastShellState();
}

async function checkForUpdate() {
  if (updateCheckPromise) {
    return updateCheckPromise;
  }
  const current = currentAppVersion();
  setUpdateState({ phase: "checking", currentVersion: current, error: "" });
  updateCheckPromise = (async () => {
    try {
      const release = await fetchLatestRelease();
      const newer = !!release.version && compareVersions(release.version, current) > 0;
      setUpdateState({
        phase: newer ? "available" : "up-to-date",
        currentVersion: current,
        latestVersion: release.version,
        releaseTag: release.tag,
        releaseUrl: release.releaseUrl,
        releaseNotes: release.releaseNotes,
        publishedAt: release.publishedAt,
        assetUrl: release.assetUrl,
        assetSize: release.assetSize,
        checksumsUrl: release.checksumsUrl,
        downloadPercent: 0,
        downloadedBytes: 0,
        verified: false,
        error: "",
        checkedAt: new Date().toISOString(),
      });
      return updateState;
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      setUpdateState({ phase: "error", error: message, checkedAt: new Date().toISOString() });
      return updateState;
    } finally {
      updateCheckPromise = null;
    }
  })();
  return updateCheckPromise;
}

function updatesRoot() {
  return path.join(runtimeDataRoot(), UPDATE_DIR_NAME);
}

function httpsText(targetUrl, redirectsLeft = 5) {
  return new Promise((resolve, reject) => {
    const req = https.request(targetUrl, {
      method: "GET",
      timeout: 15000,
      headers: { "User-Agent": UPDATE_USER_AGENT, Accept: "text/plain" },
    }, (res) => {
      const status = res.statusCode || 0;
      if (status >= 300 && status < 400 && res.headers.location) {
        res.resume();
        if (redirectsLeft <= 0) {
          reject(new Error("Too many redirects"));
          return;
        }
        resolve(httpsText(new URL(res.headers.location, targetUrl).toString(), redirectsLeft - 1));
        return;
      }
      if (status < 200 || status >= 300) {
        res.resume();
        reject(new Error(`HTTP ${status} from ${targetUrl}`));
        return;
      }
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => resolve(body));
    });
    req.on("timeout", () => req.destroy(new Error(`Request timed out: ${targetUrl}`)));
    req.on("error", reject);
    req.end();
  });
}

function httpsDownloadToFile(targetUrl, destPath, onProgress, redirectsLeft = 5) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    const req = https.request(targetUrl, {
      method: "GET",
      timeout: 60000,
      headers: { "User-Agent": UPDATE_USER_AGENT, Accept: "application/octet-stream" },
    }, (res) => {
      const status = res.statusCode || 0;
      if (status >= 300 && status < 400 && res.headers.location) {
        res.resume();
        if (redirectsLeft <= 0) {
          reject(new Error("Too many redirects"));
          return;
        }
        const next = new URL(res.headers.location, targetUrl).toString();
        resolve(httpsDownloadToFile(next, destPath, onProgress, redirectsLeft - 1));
        return;
      }
      if (status < 200 || status >= 300) {
        res.resume();
        reject(new Error(`HTTP ${status} downloading ${targetUrl}`));
        return;
      }
      const total = Number(res.headers["content-length"] || 0);
      let received = 0;
      const hash = crypto.createHash("sha256");
      const out = fs.createWriteStream(destPath);
      res.on("data", (chunk) => {
        received += chunk.length;
        hash.update(chunk);
        if (typeof onProgress === "function") {
          onProgress(received, total);
        }
      });
      res.on("error", (error) => {
        out.destroy();
        reject(error);
      });
      out.on("error", reject);
      res.pipe(out);
      out.on("finish", () => {
        out.close(() => resolve({ bytes: received, total, sha256: hash.digest("hex") }));
      });
    });
    req.on("timeout", () => req.destroy(new Error(`Download stalled: ${targetUrl}`)));
    req.on("error", reject);
    req.end();
  });
}

function parseChecksums(text, filename) {
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    const match = line.match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (match && path.basename(match[2].trim()) === filename) {
      return match[1].toLowerCase();
    }
  }
  return "";
}

function extractZip(zipPath, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  return new Promise((resolve, reject) => {
    let command;
    let args;
    if (process.platform === "win32") {
      const escapedZip = zipPath.replace(/'/g, "''");
      const escapedDest = destDir.replace(/'/g, "''");
      command = "powershell";
      args = [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `Expand-Archive -LiteralPath '${escapedZip}' -DestinationPath '${escapedDest}' -Force`,
      ];
    } else {
      command = "ditto";
      args = ["-x", "-k", zipPath, destDir];
    }
    const child = spawn(command, args, { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Extraction failed (exit ${code}): ${stderr.slice(0, 300)}`));
      }
    });
  });
}

async function downloadUpdate() {
  if (updateDownloadPromise) {
    return updateDownloadPromise;
  }
  const assetUrl = updateState.assetUrl;
  const checksumsUrl = updateState.checksumsUrl;
  if (!assetUrl || !checksumsUrl) {
    setUpdateState({ phase: "error", error: "릴리스 자산 URL을 찾을 수 없습니다." });
    return updateState;
  }
  updateDownloadPromise = (async () => {
    const root = updatesRoot();
    const downloadDir = path.join(root, "download");
    const stagingDir = path.join(root, "staging");
    const zipPath = path.join(downloadDir, UPDATE_PORTABLE_ASSET);
    try {
      fs.rmSync(downloadDir, { recursive: true, force: true });
      fs.rmSync(stagingDir, { recursive: true, force: true });
      fs.mkdirSync(downloadDir, { recursive: true });
      setUpdateState({ phase: "downloading", downloadPercent: 0, downloadedBytes: 0, verified: false, error: "" });

      const checksumsText = await httpsText(checksumsUrl);
      const expected = parseChecksums(checksumsText, UPDATE_PORTABLE_ASSET);
      if (!expected) {
        throw new Error("SHA256SUMS.txt에서 NAIA-Portable.zip 체크섬을 찾지 못했습니다.");
      }

      const result = await httpsDownloadToFile(assetUrl, zipPath, (received, total) => {
        const percent = total > 0 ? Math.min(99, Math.round((received / total) * 100)) : 0;
        if (percent !== updateState.downloadPercent) {
          setUpdateState({ downloadPercent: percent, downloadedBytes: received });
        }
      });
      if (result.sha256.toLowerCase() !== expected) {
        fs.rmSync(zipPath, { force: true });
        throw new Error(
          `체크섬 불일치 — 다운로드가 손상되었습니다 (expected ${expected.slice(0, 12)}…, got ${result.sha256.slice(0, 12)}…).`,
        );
      }
      setUpdateState({ downloadPercent: 100, downloadedBytes: result.bytes, verified: true });

      await extractZip(zipPath, stagingDir);
      const stagedRoot = path.join(stagingDir, "NAIA-Portable");
      if (!fs.existsSync(stagedRoot)) {
        throw new Error("압축 해제 결과에서 NAIA-Portable 폴더를 찾지 못했습니다.");
      }
      if (process.platform === "win32" && !fs.existsSync(path.join(stagedRoot, "NAIA.exe"))) {
        throw new Error("스테이징된 빌드에 NAIA.exe가 없습니다.");
      }
      setUpdateState({ phase: "downloaded", verified: true, downloadPercent: 100, error: "" });
      return updateState;
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      setUpdateState({ phase: "error", error: message, verified: false });
      return updateState;
    } finally {
      updateDownloadPromise = null;
    }
  })();
  return updateDownloadPromise;
}

function buildApplyConfig() {
  const root = updatesRoot();
  const installRoot = path.dirname(app.getPath("exe"));
  const userRoot = runtimeDataRoot();
  const preserve = [];
  const rel = path.relative(installRoot, userRoot);
  if (rel && !rel.startsWith("..") && !path.isAbsolute(rel)) {
    // User data lives under the install root (portable layout) — never swap it.
    preserve.push(rel.split(path.sep)[0]);
  }
  return {
    pid: process.pid,
    installRoot,
    stagedRoot: path.join(root, "staging", "NAIA-Portable"),
    backupRoot: path.join(root, "backup"),
    exePath: app.getPath("exe"),
    preserve,
    cleanupDirs: [path.join(root, "staging"), path.join(root, "download")],
    logPath: path.join(root, "apply.log"),
  };
}

async function applyUpdate() {
  if (process.platform !== "win32") {
    setUpdateState({ phase: "error", error: "자동 적용은 현재 Windows에서만 지원됩니다. 릴리스 페이지에서 수동으로 업데이트하세요." });
    return updateState;
  }
  if (!app.isPackaged) {
    setUpdateState({ phase: "error", error: "개발 모드에서는 업데이트를 적용할 수 없습니다." });
    return updateState;
  }
  const config = buildApplyConfig();
  if (updateState.phase !== "downloaded" || !updateState.verified || !fs.existsSync(config.stagedRoot)) {
    setUpdateState({ phase: "error", error: "적용할 검증된 업데이트가 없습니다. 먼저 다운로드하세요." });
    return updateState;
  }
  const root = updatesRoot();
  const scriptPath = path.join(root, "apply_update.ps1");
  const configPath = path.join(root, "apply.json");
  try {
    fs.mkdirSync(root, { recursive: true });
    fs.writeFileSync(scriptPath, APPLY_SCRIPT_PS1, "utf8");
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), "utf8");
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    setUpdateState({ phase: "error", error: `업데이트 적용 준비 실패: ${message}` });
    return updateState;
  }
  setUpdateState({ phase: "applying", error: "" });
  appendBackendLog("shell", `Applying update: detached swap helper for ${config.installRoot}`);
  const child = spawn("powershell", [
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    scriptPath,
    "-ConfigPath",
    configPath,
  ], { detached: true, stdio: "ignore", windowsHide: true });
  child.unref();
  quitting = true;
  stopBackend();
  setTimeout(() => app.quit(), 400);
  return { ok: true, applying: true };
}

async function runRuntimeInstallGate(baseUrl, options = {}) {
  if (!shouldRunRuntimeInstallGate()) {
    setRuntimeInstallState({
      active: false,
      ready: true,
      phase: "skipped",
      percent: 100,
      message: "Runtime data gate skipped.",
      error: "",
    });
    return true;
  }

  const pollIntervalMs = options.pollIntervalMs || 1000;
  const timeoutMs = options.timeoutMs || RUNTIME_INSTALL_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;
  const apiBase = String(baseUrl || "").replace(/\/+$/, "");

  setRuntimeInstallState({
    active: true,
    ready: false,
    phase: "checking",
    percent: 0,
    message: "태그 데이터 설치 상태 확인 중...",
    error: "",
  });

  const initialized = await httpJsonRequest(`${apiBase}/api/install-manager/initialize`, { method: "POST" });
  setRuntimeInstallState(normalizeRuntimeInstallState(initialized, { active: true }));
  const initializeError = runtimeInstallErrorFromPayload(initialized);
  if (initializeError) {
    throw new Error(initializeError);
  }
  if (runtimeInstallReadyFromPayload(initialized)) {
    setRuntimeInstallState(normalizeRuntimeInstallState(initialized, {
      active: false,
      message: "태그 데이터 준비 완료",
    }));
    return true;
  }

  setRuntimeInstallState({
    active: true,
    ready: false,
    phase: "download",
    percent: 0,
    message: "처음 실행에 필요한 태그 데이터를 다운로드합니다.",
    error: "",
  });
  const started = await httpJsonRequest(`${apiBase}/api/install-manager/tag-archive/download`, { method: "POST" });
  setRuntimeInstallState(normalizeRuntimeInstallState(started, { active: true }));
  const startError = runtimeInstallErrorFromPayload(started);
  if (startError) {
    throw new Error(startError);
  }

  while (Date.now() < deadline) {
    await delay(pollIntervalMs);
    const current = await httpJsonRequest(`${apiBase}/api/install-manager`);
    setRuntimeInstallState(normalizeRuntimeInstallState(current, { active: true }));
    if (runtimeInstallReadyFromPayload(current)) {
      setRuntimeInstallState(normalizeRuntimeInstallState(current, {
        active: false,
        message: "태그 데이터 준비 완료",
      }));
      return true;
    }
    const error = runtimeInstallErrorFromPayload(current);
    if (error) {
      throw new Error(error);
    }
  }

  throw new Error("Runtime data installation timed out.");
}

async function ensureRuntimeInstallReady(baseUrl, options = {}) {
  if (runtimeInstallGate) {
    return runtimeInstallGate;
  }
  runtimeInstallGate = runRuntimeInstallGate(baseUrl, options);
  try {
    return await runtimeInstallGate;
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    setRuntimeInstallState({
      active: false,
      ready: false,
      phase: "error",
      message,
      error: message,
    });
    throw error;
  } finally {
    runtimeInstallGate = null;
  }
}

async function waitForBackend(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (backendPortConfirmed && await requestHealth(backendPort)) {
      backendState = "ready";
      backendUrl = buildRemoteUrl(backendPort);
      broadcastShellState();
      return backendUrl;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Backend did not become ready at ${backendUrl}${HEALTH_PATH}`);
}

async function ensureBackendReady() {
  if (backendState === "ready" && await requestHealth(backendPort)) {
    return backendUrl;
  }
  if (startingBackend) {
    return startingBackend;
  }

  startingBackend = (async () => {
    if (!backendProcess) {
      await startBackendProcess();
    }
    return waitForBackend();
  })();

  try {
    return await startingBackend;
  } finally {
    startingBackend = null;
  }
}

function stopBackend() {
  if (!backendProcess) {
    return;
  }
  backendState = "stopping";
  broadcastShellState();
  backendProcess.kill();
}

function maintenanceFile() {
  return path.join(__dirname, "..", "renderer", "maintenance.html");
}

function loadMaintenance(reason, message) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.loadFile(maintenanceFile(), {
    query: {
      reason: reason || "loading",
      message: message || "",
    },
  });
}

function isHttpLikeUrl(url) {
  return /^https?:\/\//i.test(String(url || ""));
}

function openBrowserFallbackUrl(url) {
  try {
    const parsed = new URL(String(url || ""));
    if (parsed.protocol !== "naia-open-browser:") {
      return false;
    }
    const target = parsed.searchParams.get("url");
    if (target && isHttpLikeUrl(target)) {
      shell.openExternal(target);
      return true;
    }
  } catch (_error) {
    return false;
  }
  return false;
}

function configurePopupHandling(browserWindow) {
  hideWindowMenu(browserWindow);
  browserWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (openBrowserFallbackUrl(url)) {
      return { action: "deny" };
    }
    if (isHttpLikeUrl(url)) {
      openInternalPopup(url);
    }
    return { action: "deny" };
  });
  browserWindow.webContents.on("will-navigate", (event, url) => {
    if (openBrowserFallbackUrl(url)) {
      event.preventDefault();
    }
  });
}

function hideWindowMenu(browserWindow) {
  if (!shouldHideApplicationMenu() || !browserWindow) {
    return;
  }
  if (typeof browserWindow.setMenu === "function") {
    browserWindow.setMenu(null);
  }
  if (typeof browserWindow.setAutoHideMenuBar === "function") {
    browserWindow.setAutoHideMenuBar(true);
  }
  if (typeof browserWindow.setMenuBarVisibility === "function") {
    browserWindow.setMenuBarVisibility(false);
  }
}

function openInternalPopup(url) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    shell.openExternal(url);
    return;
  }
  const popup = new BrowserWindow({
    parent: mainWindow,
    modal: false,
    width: 1160,
    height: 820,
    minWidth: 860,
    minHeight: 560,
    title: "NAIA",
    icon: appIconPath(),
    autoHideMenuBar: shouldHideApplicationMenu(),
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  configurePopupHandling(popup);
  popup.loadURL(url);
}

function expandMainWindowForApp() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.setMinimumSize(APP_WINDOW_BOUNDS.minWidth, APP_WINDOW_BOUNDS.minHeight);
  mainWindow.setSize(APP_WINDOW_BOUNDS.width, APP_WINDOW_BOUNDS.height, true);
  mainWindow.center();
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: STARTUP_WINDOW_BOUNDS.width,
    height: STARTUP_WINDOW_BOUNDS.height,
    minWidth: STARTUP_WINDOW_BOUNDS.minWidth,
    minHeight: STARTUP_WINDOW_BOUNDS.minHeight,
    title: "NAIA",
    icon: appIconPath(),
    autoHideMenuBar: shouldHideApplicationMenu(),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  configurePopupHandling(mainWindow);

  loadMaintenance("loading", "Starting NAIA backend...");

  ensureBackendReady()
    .then(async (url) => {
      if (!mainWindow || mainWindow.isDestroyed()) {
        return;
      }
      await ensureRuntimeInstallReady(url);
      expandMainWindowForApp();
      mainWindow.loadURL(remoteEntryUrl(url));
    })
    .catch((error) => {
      backendState = "error";
      appendBackendLog("shell", error.message);
      loadMaintenance("error", error.message);
    });
}

function portableUserDataRoot() {
  if (app.isPackaged) {
    const packagedUserData = path.join(path.dirname(app.getPath("exe")), "user-data");
    if (fs.existsSync(packagedUserData)) {
      return packagedUserData;
    }
  }
  if (process.env.NAIA_PORTABLE) {
    if (app.isPackaged) {
      return path.join(path.dirname(app.getPath("exe")), "user-data");
    }
    return path.join(repoRoot(), "user-data");
  }
  return null;
}

function runtimeDataRoot() {
  if (process.env.NAIA_USER_DATA_DIR) {
    return path.resolve(process.env.NAIA_USER_DATA_DIR);
  }
  const portableRoot = portableUserDataRoot();
  if (portableRoot) {
    return portableRoot;
  }
  return path.join(app.getPath("appData"), "NAIA");
}

function ensureRuntimeSubfolder(name) {
  const target = path.join(runtimeDataRoot(), name);
  fs.mkdirSync(target, { recursive: true });
  return target;
}

function openRuntimeSubfolder(name) {
  const target = ensureRuntimeSubfolder(name);
  return shell.openPath(target);
}

function configureDownloads() {
  session.defaultSession.on("will-download", (_event, item) => {
    const downloadsDir = ensureRuntimeSubfolder("downloads");
    const filename = path.basename(item.getFilename() || "download");
    const savePath = path.join(downloadsDir, filename);
    item.setSavePath(savePath);
    appendBackendLog("shell", `Download target: ${savePath}`);
  });
}

function appIconPath() {
  return APP_ICON;
}

ipcMain.handle("naia:shell-state", () => shellState());
ipcMain.handle("naia:restart-backend", async () => {
  stopBackend();
  await new Promise((resolve) => setTimeout(resolve, 750));
  backendState = "starting";
  const url = await ensureBackendReady();
  await ensureRuntimeInstallReady(url);
  if (mainWindow && !mainWindow.isDestroyed()) {
    await mainWindow.loadURL(remoteEntryUrl(url));
  }
  return shellState();
});
ipcMain.handle("naia:open-browser", () => shell.openExternal(`${backendUrl}/?desktop_shell=1`));
ipcMain.handle("naia:open-data-folder", () => shell.openPath(runtimeDataRoot()));
ipcMain.handle("naia:open-logs", () => openRuntimeSubfolder("logs"));
ipcMain.handle("naia:pick-directory", async () => {
  const win = BrowserWindow.getFocusedWindow() || BrowserWindow.getAllWindows()[0] || null;
  const options = { properties: ["openDirectory"], title: "이전 NAIA2.0 데이터 폴더 선택" };
  const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  if (result.canceled || !Array.isArray(result.filePaths) || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});
ipcMain.handle("naia:check-update", () => checkForUpdate());
ipcMain.handle("naia:download-update", () => downloadUpdate());
ipcMain.handle("naia:apply-update", () => applyUpdate());
ipcMain.handle("naia:open-release-page", () => {
  const url = updateState.releaseUrl || UPDATE_RELEASES_PAGE_URL;
  return shell.openExternal(url);
});

configureRemoteDebugging();

const lock = app.requestSingleInstanceLock();
if (!lock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    configureApplicationMenu();
    configureDownloads();
    createMainWindow();
  });
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
  app.on("before-quit", () => {
    quitting = true;
    stopBackend();
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit();
    }
  });
}

function remoteEntryUrl(url) {
  return `${url}/?${ENTRY_QUERY}`;
}

module.exports.__test = {
  APP_WINDOW_BOUNDS,
  ENTRY_QUERY,
  HIDE_MENU_ENV,
  REMOTE_DEBUGGING_ENV,
  RUNTIME_INSTALL_FORCE_ENV,
  RUNTIME_INSTALL_SKIP_ENV,
  STARTUP_WINDOW_BOUNDS,
  backendArgs,
  backendCommand,
  backendEnvironment,
  backendLaunchConfig,
  backendRoot,
  buildRemoteUrl,
  appIconPath,
  compareVersions,
  currentAppVersion,
  parseLatestRelease,
  parseChecksums,
  updatesRoot,
  httpsText,
  httpsDownloadToFile,
  extractZip,
  buildApplyConfig,
  applyScriptPs1: APPLY_SCRIPT_PS1,
  configureRemoteDebugging,
  configureApplicationMenu,
  isHttpLikeUrl,
  ensureRuntimeInstallReady,
  httpJsonRequest,
  countRuntimeRequirements,
  openBrowserFallbackUrl,
  packagedPythonExecutable,
  portableUserDataRoot,
  remoteDebuggingPort,
  remoteEntryUrl,
  runtimeInstallErrorFromPayload,
  runtimeInstallReadyFromPayload,
  shouldRunRuntimeInstallGate,
  requirementsFingerprint,
  requirementsPath,
  removePythonRuntimeBytecode,
  resourcesRoot,
  runtimeDataRoot,
  runtimeEnvMarker,
  runtimeEnvPython,
  runtimeEnvReady,
  runtimeEnvRoot,
  runtimeBootstrapProgressFromLine,
  pythonBytecodeCacheRoot,
  shellState,
  shouldHideApplicationMenu,
  sourceVenvPython,
  wheelhousePath,
};
