"use strict";

const { app, BrowserWindow, WebContentsView, dialog, ipcMain, Menu, screen, session, shell } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const net = require("node:net");
const os = require("node:os");
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
// Automated/CI flag: skip the interactive tag-data choice and auto-download the
// corpus (original behavior). Used by the CDP release smoke, which needs tag
// data present and has no human to pick a path.
const RUNTIME_INSTALL_AUTO_DOWNLOAD_ENV = "NAIA_ELECTRON_AUTO_TAG_DOWNLOAD";
const RUNTIME_INSTALL_TIMEOUT_MS = 60 * 60 * 1000;
const RUNTIME_ENV_DIR = "runtime-env";
const RUNTIME_ENV_MARKER = "naia-runtime-env.json";
const RUNTIME_ENV_MARKER_SCHEMA = 1;
const PYTHON_BYTECODE_CACHE_DIR = path.join("cache", "python-bytecode");
const APP_ICON = path.join(__dirname, "..", "assets", "naia.ico");
// Auto-update: poll the GitHub releases API for the portable build and surface
// it to the Remote Web shell UI. Releases are tagged vX.Y.Z and carry the
// portable zip + a SHA256SUMS.txt that the apply step verifies against.
//
// WARNING(update channel): there are TWO update paths that must stay in sync.
// Packaged/portable installs use this release feed (download + swap). Source
// clones follow their git upstream branch (origin/future02 today) via the
// run_NAIA_* launchers' fetch/pull check on every start. This shell check
// stays release-feed driven even in source mode — it does NOT see commit-level
// drift; updateState.sourceMode only switches the banner to git-pull guidance
// for release-tag notifications. If future02 is ever force-merged into/renamed
// to main, revise every update touchpoint together: all four run_NAIA_*
// launchers, the source-mode banner guidance (updateBannerControls.mjs), and
// existing clones' upstream branches.
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
// 업데이트 스왑 헬퍼. 2.0.29 업데이트 사고(여러 PC에서 설치 파손) 이후 하드닝:
//  1) swap 전 잠금 선검사(Find-LockedItem, rename 왕복 = 비파괴 원자 연산) — ollama serve /
//     cloudflared 처럼 naia-backend 를 CWD 로 상속한 상주 자식이 폴더를 잠근 채 남아 있으면
//     설치를 건드리지 않고 중단(marker 기록) 후 기존 버전을 재실행한다.
//  2) 실패 복원을 Copy 기반 전체 복원(Restore-FromBackup)으로 교체 — 기존 롤백은 실패한
//     항목이 moved 목록에 등록되기 전이라 복원 대상에서 빠졌고, Move-Item 의 재귀 이동이
//     resources 알맹이를 backup 으로 옮긴 뒤라 설치가 반파된 채 남았다(재현 실증).
//     Copy 는 잠긴 디렉터리 안으로도 파일을 되돌릴 수 있고 backup 은 수동 복구용으로 남긴다.
//  3) 실패 사유를 markerPath 에 기록 — 재실행된 앱이 시작 시 읽어 사용자에게 표면화한다.
// (PS1 내부 주석은 인코딩 안전을 위해 ASCII/영문만 사용 — powershell 5.1 이 BOM 없는
//  UTF-8 스크립트를 ANSI 로 읽는 환경이 있다.)
const APPLY_SCRIPT_PS1 = `param([string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
function Write-ApplyLog($m) {
  try { "$([DateTime]::Now.ToString('s')) $m" | Out-File -LiteralPath $cfg.logPath -Append -Encoding utf8 } catch {}
}
function Write-ApplyMarker($m) {
  try { if ($cfg.markerPath) { $m | Out-File -LiteralPath $cfg.markerPath -Encoding utf8 } } catch {}
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
function Repair-ProbeResidue($root) {
  # A previous run may have renamed an item to the probe name and then failed to
  # rename it back (narrow race: something grabs it between the two renames).
  # Put it back before doing anything else -- otherwise the install stays broken
  # and the next probe would nest the suffix.
  $fixed = @()
  foreach ($item in Get-ChildItem -LiteralPath $root -Force) {
    if ($item.Name -notlike '*.__swap_probe__') { continue }
    $original = $item.Name.Substring(0, $item.Name.Length - '.__swap_probe__'.Length)
    if (Test-Path -LiteralPath (Join-Path $root $original)) { continue }
    for ($r = 0; $r -lt 20; $r++) {
      Rename-Item -LiteralPath $item.FullName -NewName $original -Force -ErrorAction SilentlyContinue
      if (Test-Path -LiteralPath (Join-Path $root $original)) { $fixed += $original; break }
      Start-Sleep -Milliseconds 300
    }
  }
  return $fixed
}
function Find-LockedItem($root, $preserve) {
  # Pre-swap lock probe: rename each top-level item back and forth. Rename is an
  # atomic non-destructive operation; a resident child process that inherited its
  # CWD from the backend (ollama serve / cloudflared) makes it fail cleanly here
  # instead of half-destroying the install mid-swap.
  #
  # The result is checked by EXISTENCE, not by catching. Rename-Item failures are
  # non-terminating, so this gate used to depend entirely on the script-level
  # 'Stop' preference: with it absent the rename fails, nothing throws, and the
  # probe reports 'not locked' -- letting the destructive swap start on a locked
  # install. Measured 2026-08-31.
  foreach ($item in Get-ChildItem -LiteralPath $root -Force) {
    if ($preserve -contains $item.Name) { continue }
    if ($item.Name -like '*.__swap_probe__') { return 'RESIDUE:' + $item.Name }
    $probeName = $item.Name + '.__swap_probe__'
    $probePath = Join-Path $root $probeName
    $originalPath = $item.FullName
    Rename-Item -LiteralPath $originalPath -NewName $probeName -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $probePath)) { return 'LOCKED:' + $item.Name }
    # Restore. Try hard: leaving the item under the probe name is exactly the
    # damage this function exists to prevent.
    for ($r = 0; $r -lt 100; $r++) {
      Rename-Item -LiteralPath $probePath -NewName $item.Name -Force -ErrorAction SilentlyContinue
      if (Test-Path -LiteralPath $originalPath) { $probePath = ''; break }
      Start-Sleep -Milliseconds 300
    }
    if ($probePath) { return 'RESIDUE:' + $item.Name }
  }
  return $null
}
function Restore-FromBackup($backupRoot, $installRoot) {
  # Copy (not move) everything back so files can be restored even into a locked
  # directory, and the backup stays behind for manual recovery.
  $failed = 0
  foreach ($item in Get-ChildItem -LiteralPath $backupRoot -Force) {
    $dest = Join-Path $installRoot $item.Name
    try {
      if ($item.PSIsContainer) {
        if (-not (Test-Path -LiteralPath $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }
        Copy-Item -Path (Join-Path $item.FullName '*') -Destination $dest -Recurse -Force
      } else {
        Copy-Item -LiteralPath $item.FullName -Destination $dest -Force
      }
    } catch { $failed = $failed + 1; Write-ApplyLog "restore FAILED for $($item.Name): $_" }
  }
  return $failed
}
Write-ApplyLog "apply start pid=$($cfg.pid) install=$($cfg.installRoot)"
$repaired = Repair-ProbeResidue $cfg.installRoot
if ($repaired.Count -gt 0) { Write-ApplyLog "repaired probe residue: $($repaired -join ', ')" }
for ($i = 0; $i -lt 240; $i++) {
  $proc = Get-Process -Id $cfg.pid -ErrorAction SilentlyContinue
  if (-not $proc) { break }
  Start-Sleep -Milliseconds 500
}
Start-Sleep -Milliseconds 1000
$preserve = @($cfg.preserve)
$locked = $null
for ($i = 0; $i -lt 20; $i++) {
  $locked = Find-LockedItem $cfg.installRoot $preserve
  if (-not $locked) { break }
  Start-Sleep -Milliseconds 1000
}
if ($locked) {
  # RESIDUE means the probe could not put an item back -- the install is NOT
  # untouched and saying so would send the user to a silently broken app.
  if ($locked -like 'RESIDUE:*') {
    Write-ApplyLog "swap ABORTED (probe residue, install DAMAGED): $locked"
    Write-ApplyMarker "PROBE_RESIDUE: $locked"
  } else {
    Write-ApplyLog "swap ABORTED (locked): $locked"
    Write-ApplyMarker "LOCKED: $locked"
    Write-ApplyLog "install untouched"
  }
  try { Start-Process -FilePath $cfg.exePath } catch { Write-ApplyLog "relaunch FAILED: $_" }
  Write-ApplyLog "apply end (aborted)"
  exit 0
}
if (Test-Path -LiteralPath $cfg.backupRoot) { Remove-Item -LiteralPath $cfg.backupRoot -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $cfg.backupRoot -Force | Out-Null
try {
  Get-ChildItem -LiteralPath $cfg.installRoot -Force | ForEach-Object {
    if ($preserve -contains $_.Name) { return }
    Move-WithRetry $_.FullName (Join-Path $cfg.backupRoot $_.Name)
  }
  Get-ChildItem -LiteralPath $cfg.stagedRoot -Force | ForEach-Object {
    if ($preserve -contains $_.Name) { return }
    Move-WithRetry $_.FullName (Join-Path $cfg.installRoot $_.Name)
  }
  Write-ApplyLog "swap ok"
} catch {
  $reason = "$_"
  Write-ApplyLog "swap FAILED: $reason restoring from backup"
  $restoreFailed = Restore-FromBackup $cfg.backupRoot $cfg.installRoot
  if ($restoreFailed -gt 0) {
    # Do not claim a clean rollback we did not achieve. The user needs to know the
    # install may be mixed so they reinstall instead of trusting a broken app.
    Write-ApplyMarker "RESTORE_INCOMPLETE: $restoreFailed item(s) failed after: $reason"
    Write-ApplyLog "restore INCOMPLETE ($restoreFailed failed, backup kept at $($cfg.backupRoot))"
  } else {
    Write-ApplyMarker "SWAP_FAILED: $reason"
    Write-ApplyLog "restore done (backup kept at $($cfg.backupRoot))"
  }
}
foreach ($d in @($cfg.cleanupDirs)) {
  try { Remove-WithRetry $d; Write-ApplyLog "cleaned $d" } catch { Write-ApplyLog "cleanup FAILED $d : $_" }
}
Write-ApplyLog "relaunch $($cfg.exePath)"
try { Start-Process -FilePath $cfg.exePath } catch { Write-ApplyLog "relaunch FAILED: $_" }
Write-ApplyLog "apply end"
`;
const STARTUP_WINDOW_BOUNDS = Object.freeze({
  width: 900,
  height: 600,
  minWidth: 760,
  minHeight: 480,
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
// Whether the user picked the *download* path in the maintenance window. Set by
// ``naia:start-tag-download`` and read in ``runRuntimeInstallGate`` to arm the
// completion deadline (the download is bounded; no deadline while still waiting
// on the user's choice).
let runtimeInstallChoiceMade = false;
// Whether the user picked "import from previous NAIA2.0". While true, the gate
// must NOT auto-complete on tag readiness — it waits for the explicit
// ``naia:restart-backend`` so the freshly-imported data is loaded by a clean
// backend restart instead of against the stale startup cache. Cleared by the
// restart handler.
let bootstrapMigrationActive = false;
let runtimeBootstrapState = null;
let quitting = false;
let backendPortConfirmed = false;
let cachedAppVersion = null;
let updateCheckPromise = null;
let updateDownloadPromise = null;
let updateState = {
  phase: "idle", // idle | checking | available | up-to-date | error | downloading | downloaded | applying
  // Source checkouts cannot take the zip download/swap path; the banner shows
  // git-pull guidance instead (see WARNING(update channel) above).
  sourceMode: !app.isPackaged,
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
    NAIA_GROK_PROXY_PORT: String(grokProxyPort),
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
    const req = requestModuleFor(targetUrl).request(targetUrl, {
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
  // NAIA_UPDATE_FEED_URL lets a mirror/enterprise feed (or a local e2e harness)
  // stand in for the GitHub releases API; it must return the same JSON shape.
  const feedUrl = process.env.NAIA_UPDATE_FEED_URL || UPDATE_LATEST_RELEASE_URL;
  const payload = await httpsJsonRequest(feedUrl);
  return parseLatestRelease(payload);
}

function requestModuleFor(targetUrl) {
  return new URL(targetUrl).protocol === "http:" ? http : https;
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
    const req = requestModuleFor(targetUrl).request(targetUrl, {
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
    const req = requestModuleFor(targetUrl).request(targetUrl, {
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

// 직전 자동 업데이트 스왑이 중단/실패했으면(marker 존재) 사용자에게 표면화한다.
// 스왑 헬퍼는 별도 프로세스라 앱이 죽은 뒤 실패하고, 재실행된 앱만 이를 알릴 수 있다.
function surfaceLastApplyError() {
  try {
    const marker = path.join(updatesRoot(), "last_apply_error.txt");
    if (!fs.existsSync(marker)) {
      return;
    }
    const raw = fs.readFileSync(marker, "utf8").trim();
    fs.rmSync(marker, { force: true });
    if (!raw) {
      return;
    }
    appendBackendLog("shell", `Previous update apply did not complete: ${raw}`);
    // ⚠️ 문구가 실제 상태보다 낙관적이면 안 된다. 예전에는 어떤 실패든 "이전 버전으로
    //    복원했습니다" 라고 단정해, 반쪽만 복원된 설치를 사용자가 멀쩡한 줄 알고 썼다.
    let friendly;
    if (raw.startsWith("LOCKED:")) {
      friendly = `업데이트를 적용하지 못했습니다 — 설치 폴더를 다른 프로세스가 사용 중이었습니다 (${raw.slice(7).trim()}). 설치는 그대로입니다. Ollama/Cloudflared 등을 종료한 뒤 다시 시도하세요.`;
    } else if (raw.startsWith("PROBE_RESIDUE:")) {
      friendly = `업데이트를 중단했지만 설치 폴더가 손상되었을 수 있습니다 (${raw.slice(14).trim()}). 앱을 완전히 종료한 뒤 다시 실행하면 자동 복구를 시도합니다. 실행되지 않으면 릴리스 페이지에서 새로 받아 설치하세요.`;
    } else if (raw.startsWith("RESTORE_INCOMPLETE:")) {
      friendly = `업데이트에 실패했고 이전 버전 복원도 일부 실패했습니다 (${raw.slice(19).trim()}). 설치가 섞인 상태일 수 있으니 릴리스 페이지에서 새로 받아 설치하세요. 백업은 user-data\.updates\backup 에 있습니다.`;
    } else {
      friendly = `업데이트 적용 중 오류가 발생해 이전 버전으로 복원했습니다 (${raw}). 다시 시도하거나 릴리스 페이지에서 새로 받아 설치하세요.`;
    }
    setUpdateState({ phase: "error", error: friendly });
  } catch (_e) {
    // 표면화 실패는 앱 기동을 막지 않는다
  }
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
    // 스왑 헬퍼가 중단/실패 사유를 남기는 파일 — 재실행된 앱이 시작 시 읽어 표면화.
    markerPath: path.join(root, "last_apply_error.txt"),
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
  const launchCmdPath = path.join(root, "apply_launch.cmd");
  try {
    fs.mkdirSync(root, { recursive: true });
    fs.writeFileSync(scriptPath, APPLY_SCRIPT_PS1, "utf8");
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), "utf8");
    // Launch the helper via `start` from a .cmd: that gives it its own console
    // so it survives this process exiting. A plain detached child is otherwise
    // killed by Electron's Windows job object when the app quits.
    fs.writeFileSync(
      launchCmdPath,
      `@echo off\r\nstart "NAIA Update" /min powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "${scriptPath}" -ConfigPath "${configPath}"\r\n`,
      "utf8",
    );
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    setUpdateState({ phase: "error", error: `업데이트 적용 준비 실패: ${message}` });
    return updateState;
  }
  setUpdateState({ phase: "applying", error: "" });
  appendBackendLog("shell", `Applying update: swap helper for ${config.installRoot}`);
  const child = spawn(process.env.COMSPEC || "cmd.exe", ["/c", launchCmdPath], {
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  child.unref();
  quitting = true;
  stopBackend();
  setTimeout(() => app.quit(), 800);
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
  // The completion deadline only starts once the user has chosen a path; it is
  // computed lazily the first time a choice is detected so a user who leaves
  // the maintenance window open for a while before picking does not time out
  // immediately.
  let choiceDeadline = 0;
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

  // Automated contexts (the CDP release smoke) have no human to pick a path and
  // need tag data present for the random-prompt round-trip checks, so they set
  // NAIA_ELECTRON_AUTO_TAG_DOWNLOAD=1 to restore the original auto-download.
  // Interactive launches fall through to the awaiting_choice flow below.
  if (process.env[RUNTIME_INSTALL_AUTO_DOWNLOAD_ENV] === "1") {
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
    // Arm the deadline and skip the awaiting_choice state; the unified poll
    // loop below treats this exactly like a user-initiated download.
    runtimeInstallChoiceMade = true;
  } else if (initialized && initialized.tag_archive && initialized.tag_archive.download
      && initialized.tag_archive.download.active) {
    // A tag-archive download is already running — e.g. ``naia:restart-backend``
    // auto-armed it because a migration finished without tag data. Treat it as
    // the download choice immediately instead of flashing ``awaiting_choice``
    // for one poll interval (the loop below would recover via download.active,
    // but the maintenance view would briefly show the two-choice CTA).
    runtimeInstallChoiceMade = true;
    bootstrapMigrationActive = false;
    setRuntimeInstallState(normalizeRuntimeInstallState(initialized, { active: true }));
  } else {
    // Do NOT auto-trigger the Hugging Face download. A returning user with a
    // previous NAIA2.0 install can carry the ~1.4 GB tag corpus over via the
    // migration flow, and silently spending bandwidth+time on a download they
    // would have skipped is the bug the user reported. Surface a choice in the
    // maintenance window: "허깅페이스에서 다운로드" starts the download via the
    // ``naia:start-tag-download`` IPC, "NAIA2.0에서 가져오기" hands off to the
    // migration UI. Either path eventually makes ``install-manager`` report
    // ready, which the poll loop picks up.
    runtimeInstallChoiceMade = false;
    bootstrapMigrationActive = false;
    setRuntimeInstallState(normalizeRuntimeInstallState(initialized, {
      active: false,
      phase: "awaiting_choice",
      message: "태그 데이터를 어떻게 준비할지 선택하세요.",
      error: "",
    }));
  }

  // No timeout while the user is deciding. The completion deadline applies only
  // to the bounded download path; the migration path is user-interactive and
  // completes via the explicit "NAIA 재시작" (restartBackend), never a timer.
  while (true) {
    await delay(pollIntervalMs);
    let current;
    try {
      // Re-resolve the backend URL every iteration: a user-initiated restart
      // (``naia:restart-backend`` during bootstrap migration) respawns the
      // backend with --auto-port, so the port can change while this gate is
      // still in flight. Polling the captured launch-time ``apiBase`` would
      // then hit a dead port forever. Only trust the global ``backendUrl``
      // once a spawned backend confirmed its port — explicit-base callers
      // (the contract tests pass a mock server URL without spawning) must
      // keep polling the ``baseUrl`` they were given.
      const pollBase = String(backendPortConfirmed && backendUrl ? backendUrl : apiBase)
        .replace(/\/+$/, "");
      current = await httpJsonRequest(`${pollBase}/api/install-manager`);
    } catch (pollError) {
      // The backend can be momentarily unreachable during a user-initiated
      // restart (the "NAIA 재시작" button in the migration popup). Treat the
      // transient error as "keep polling" rather than failing the gate. If the
      // user picked the download path, make sure the deadline is armed even
      // before the first successful GET so a dead backend cannot hang forever.
      if (runtimeInstallChoiceMade && !choiceDeadline) {
        choiceDeadline = Date.now() + timeoutMs;
      }
      if (choiceDeadline && Date.now() >= choiceDeadline) {
        throw new Error("Runtime data installation timed out.");
      }
      continue;
    }
    const downloadActive = runtimeInstallChoiceMade
      || !!(current && current.tag_archive && current.tag_archive.download && current.tag_archive.download.active);
    // Deadline only for the download path. Migration is interactive (no timer).
    if (downloadActive && !choiceDeadline) {
      choiceDeadline = Date.now() + timeoutMs;
    }
    const showActive = downloadActive || bootstrapMigrationActive;
    setRuntimeInstallState(normalizeRuntimeInstallState(current, {
      active: showActive,
      phase: showActive ? undefined : "awaiting_choice",
      message: showActive ? undefined : "태그 데이터를 어떻게 준비할지 선택하세요.",
    }));
    if (runtimeInstallReadyFromPayload(current)) {
      // During bootstrap migration, tag files can appear (import copied
      // data/tags) before the user clicks "NAIA 재시작". Do NOT auto-complete
      // and navigate away from the migration UI: wait for restartBackend, which
      // clears bootstrapMigrationActive and re-warms the backend so ALL imported
      // data (tags, presets, wildcards, settings) is picked up cleanly rather
      // than against a stale in-memory cache.
      if (bootstrapMigrationActive) {
        continue;
      }
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
    if (choiceDeadline && Date.now() >= choiceDeadline) {
      throw new Error("Runtime data installation timed out.");
    }
  }
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
  // Windows: 백엔드 python 이 낳은 상주 자식(ollama serve / cloudflared)까지 트리째 종료.
  // kill() 은 본체만 죽여서, cwd 를 상속한 자식이 resources/naia-backend 를 계속 잠근 채
  // 남아 자동 업데이트 스왑을 실패시키고 설치를 파손시켰다(2.0.29 업데이트 사고 —
  // apply.log 'being used by another process'). 외부에서 사용자가 직접 켠 프로세스는
  // 이 트리에 속하지 않으므로 건드리지 않는다.
  if (process.platform === "win32" && backendProcess.pid) {
    let killed = false;
    try {
      const result = spawnSync("taskkill", ["/PID", String(backendProcess.pid), "/T", "/F"], {
        windowsHide: true,
        timeout: 10000,
      });
      // ⚠️ `spawnSync` 는 실패해도 **던지지 않는다.** 접근 거부·timeout·ENOENT 는
      //    예외가 아니라 결과 객체(`error`/`status`)로 돌아온다. 예전에는 곧장
      //    `return` 해서 폴백 `kill()` 이 영영 안 돌았고, 그러면 백엔드 트리가
      //    살아남아 `resources/naia-backend` 를 잠근 채 남는다 - 이 함수가 막으려던
      //    바로 그 상황이다(2.0.29 업데이트 사고). 결과를 보고 갈린다.
      killed = !result.error && result.status === 0;
      if (!killed) {
        const why = result.error ? result.error.message : `exit ${result.status}`;
        appendBackendLog("shell", `taskkill failed (${why}); falling back to kill()`);
      }
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      appendBackendLog("shell", `taskkill threw (${message}); falling back to kill()`);
    }
    if (killed) return;
  }
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

/**
 * 뒤로 갈 수 있는 가장 먼 곳은 **메인 생성 화면**이다.
 *
 * 창은 `maintenance.html`(준비 화면)을 먼저 띄우고 백엔드가 뜨면 앱 주소로
 * 넘어간다. 그래서 그 준비 화면이 히스토리에 남고, 마우스 뒤로가기 버튼을 누르면
 * 멀쩡히 쓰던 앱이 "NAIA data ready" 화면으로 되돌아간다(사용자 지적).
 *
 * 입력을 가로채는 대신 **갈 곳 자체를 없앤다.** 앱 주소로 넘어온 뒤 히스토리를
 * 비우면 뒤로가기는 아무 일도 하지 않는다. 이 방식이 좋은 이유가 하나 더 있다 —
 * 창 단위로 입력을 막으면 안에 붙는 Danbooru 뷰의 자기 뒤로가기까지 죽는다.
 * 그쪽은 자기 히스토리를 그대로 갖는다.
 *
 * 앱은 `pushState` 를 쓰지 않으므로(확인함) 지울 것은 준비 화면 항목뿐이다.
 * 재시작하면 준비 화면 -> 앱 순서가 다시 생기는데, 그때도 여기서 다시 비운다.
 */
function preventBackNavigation(browserWindow) {
  if (!browserWindow) return;
  const wc = browserWindow.webContents;
  wc.on("did-finish-load", () => {
    // 준비 화면(file://) 에서는 비우지 않는다 — 거기서는 아직 갈 곳이 없고,
    // 비워 봐야 뒤이어 앱으로 넘어가며 다시 쌓인다.
    if (!/^https?:/i.test(wc.getURL() || "")) return;
    try {
      if (typeof wc.clearHistory === "function") wc.clearHistory();
    } catch (_error) {
      /* 히스토리를 못 비워도 앱은 떠야 한다 */
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

// --- Renderer zoom (browser-style Ctrl+wheel / Ctrl+± / Ctrl+0) -------------
// Electron has no browser chrome, so Ctrl+wheel zoom must be wired up by hand. The
// main window's factor is persisted (per-instance, under userData) and re-applied on
// every load since zoom resets on navigation. Other webContents (popup) zoom transiently.
// Limited to 5 discrete levels — the default (1.0) ±2 steps. Zooming in any further
// shrinks the CSS viewport past the responsive breakpoint and flips the app into its
// mobile layout, so the range is intentionally narrow.
const ZOOM_DEFAULT = 1.0;
const ZOOM_STEP = 0.1;
const ZOOM_MIN = ZOOM_DEFAULT - 2 * ZOOM_STEP; // 0.8
const ZOOM_MAX = ZOOM_DEFAULT + 2 * ZOOM_STEP; // 1.2
let zoomFactorCache = null;

function zoomConfigPath() {
  try {
    return path.join(app.getPath("userData"), "naia-zoom.json");
  } catch (_error) {
    return null;
  }
}

function clampZoom(factor) {
  if (!Number.isFinite(factor)) return 1.0;
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(factor * 100) / 100));
}

function loadZoomFactor() {
  if (zoomFactorCache !== null) return zoomFactorCache;
  let factor = 1.0;
  try {
    const configPath = zoomConfigPath();
    if (configPath && fs.existsSync(configPath)) {
      const raw = JSON.parse(fs.readFileSync(configPath, "utf8"));
      const parsed = Number(raw && raw.zoomFactor);
      if (Number.isFinite(parsed)) factor = clampZoom(parsed);
    }
  } catch (_error) {}
  zoomFactorCache = factor;
  return factor;
}

function saveZoomFactor(factor) {
  zoomFactorCache = factor;
  try {
    const configPath = zoomConfigPath();
    if (configPath) fs.writeFileSync(configPath, JSON.stringify({ zoomFactor: factor }), "utf8");
  } catch (_error) {}
}

function isMainWebContents(webContents) {
  return Boolean(
    mainWindow && !mainWindow.isDestroyed() && webContents === mainWindow.webContents
  );
}

function applyMainWindowZoom() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    mainWindow.webContents.setZoomFactor(loadZoomFactor());
  } catch (_error) {}
}

function adjustZoom(webContents, direction) {
  if (!webContents || webContents.isDestroyed() || !direction) return;
  const main = isMainWebContents(webContents);
  let current;
  try {
    current = webContents.getZoomFactor();
  } catch (_error) {
    current = main ? loadZoomFactor() : 1.0;
  }
  const next = clampZoom(current + (direction > 0 ? ZOOM_STEP : -ZOOM_STEP));
  try {
    webContents.setZoomFactor(next);
  } catch (_error) {}
  if (main) saveZoomFactor(next);
}

function resetZoom(webContents) {
  if (!webContents || webContents.isDestroyed()) return;
  try {
    webContents.setZoomFactor(1.0);
  } catch (_error) {}
  if (isMainWebContents(webContents)) saveZoomFactor(1.0);
}

ipcMain.on("naia:zoom-by", (event, direction) => {
  const dir = Number(direction);
  if (!Number.isFinite(dir) || dir === 0) return;
  adjustZoom(event.sender, dir > 0 ? 1 : -1);
});

ipcMain.on("naia:zoom-reset", (event) => resetZoom(event.sender));

// Automation 완료 등 백그라운드 작업이 끝나면 작업표시줄 버튼을 깜빡여(Windows 노란불)
// 사용자 주의를 끈다. 창이 이미 포커스면 불필요하므로 비활성(다른 창/최소화)일 때만 깜빡인다.
ipcMain.on("naia:flash-taskbar", () => {
  if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isFocused()) return;
  try { mainWindow.flashFrame(true); } catch (e) {}
});

// Browser-style Ctrl+± / Ctrl+0 keyboard zoom for the main app window.
function attachZoomKeyboard(targetWindow) {
  targetWindow.webContents.on("before-input-event", (event, input) => {
    if (input.type !== "keyDown" || !(input.control || input.meta)) return;
    const key = String(input.key || "");
    if (key === "+" || key === "=" || key === "Add") {
      adjustZoom(targetWindow.webContents, 1);
      event.preventDefault();
    } else if (key === "-" || key === "Subtract") {
      adjustZoom(targetWindow.webContents, -1);
      event.preventDefault();
    } else if (key === "0") {
      resetZoom(targetWindow.webContents);
      event.preventDefault();
    }
  });
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

  // Show on first paint, but ALSO show on the first did-finish-load as a fallback:
  // applying the persisted zoom factor (below) can suppress the `ready-to-show` signal
  // on some GPU/compositor states, which would otherwise leave the window invisible
  // forever (the v2.0.18 "window never shows" regression). Never rely on ready-to-show
  // alone to make the window visible.
  const showMainWindowOnce = () => {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      mainWindow.show();
    }
  };
  mainWindow.once("ready-to-show", showMainWindowOnce);
  mainWindow.webContents.once("did-finish-load", showMainWindowOnce);
  mainWindow.webContents.once("dom-ready", showMainWindowOnce);
  // Ultimate guard: if neither paint nor load event reveals the window, force it.
  setTimeout(showMainWindowOnce, 2000);
  mainWindow.on("closed", () => {
    danbooruView = null;
    danbooruViewAttached = false;
    danbooruWarmupState = "idle";
    mainWindow = null;
  });
  // 창을 다시 보면(포커스) 작업표시줄 깜빡임을 멈춘다 — Windows는 포커스 시 자동
  // 정지하지만 방어적으로 명시한다(Automation 완료 시 깜빡인 노란불 해제).
  mainWindow.on("focus", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      try { mainWindow.flashFrame(false); } catch (e) {}
    }
  });
  // If the shell renderer reloads or navigates (maintenance/bootstrap/F5) while the
  // Danbooru panel is open, the renderer loses its embedActive state and cannot detach
  // the native child view — so detach it here too (no-op when unattached).
  mainWindow.webContents.on("did-start-loading", () => detachDanbooruView());
  configurePopupHandling(mainWindow);

  // Browser-style zoom: re-apply the saved factor on every load (zoom resets on
  // navigation) and wire Ctrl+= / Ctrl+- / Ctrl+0. Pinch/visual zoom is intentionally
  // left disabled so zoom stays within the 5 discrete levels and never reaches the
  // mobile-layout breakpoint.
  // The setZoomFactor call is DEFERRED to a later tick: running it inside the
  // did-finish-load paint path suppressed `ready-to-show` and left the window invisible
  // (v2.0.18 regression). Deferring lets the first frame paint + show before we zoom.
  mainWindow.webContents.on("did-finish-load", () => setTimeout(() => applyMainWindowZoom(), 0));
  attachZoomKeyboard(mainWindow);
  preventBackNavigation(mainWindow);

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

// --- Embedded Danbooru browser (WebContentsView) ---------------------------
// Serves danbooru.donmai.us inside the app as a native child view (the desktop
// QWebEngineView analog). It runs in its OWN WebContents on a persistent partition,
// so it is unaffected by donmai's CSP/X-Frame-Options and keeps login across restarts
// (persist:danbooru lives under userData — the same %APPDATA%-class location the
// desktop browser_profile used). Browser (non-Electron) clients never reach this;
// they fall back to the JSON query/Load path in danbooruTab.mjs.
let danbooruView = null;
let danbooruViewAttached = false;
const DANBOORU_HOSTS = new Set(["danbooru.donmai.us", "www.danbooru.donmai.us"]);
const DANBOORU_POST_RE = /danbooru\.donmai\.us\/posts\/(\d+)/;
const DANBOORU_HOME_URL = "https://danbooru.donmai.us/";
// 한국에서 danbooru.donmai.us 직접 연결이 막혀, 같은 Cloudflare(donmai.us) 형제
// 프로퍼티인 safebooru 로 먼저 접속해 챌린지를 통과시킨 뒤 조용히 danbooru 로
// 천이한다. safebooru 는 워밍업 홉일 뿐이라 임베드 뷰가 두 호스트를 모두 허용해야
// (CF 챌린지 리다이렉트는 same-host) 하지만 태그 추출/포스트 인식은 danbooru 전용.
const SAFEBOORU_HOME_URL = "https://safebooru.donmai.us/";
const DANBOORU_VIEW_HOSTS = new Set([
  "danbooru.donmai.us",
  "www.danbooru.donmai.us",
  "safebooru.donmai.us",
]);
// idle=미시작 / safebooru=워밍업 로드중 / transitioned=danbooru 로 천이함 / done=완료.
let danbooruWarmupState = "idle";
// 워밍업 중 로드 실패(네트워크/차단) 재시도 상한 — 무한 재시도 방지(cold 로드마다 리셋).
let danbooruWarmupRetries = 0;
const DANBOORU_WARMUP_MAX_RETRIES = 3;
// Tag extraction = crawl the page the view ALREADY loaded (Dev0714 tabs/web_view.py:307-334),
// reading data-tag-name from each <ul class="{category}-tag-list">. No server-side donmai
// request, so Cloudflare (which resets the backend's plain client) is bypassed entirely.
const DANBOORU_EXTRACT_JS = `(() => {
  const cats = ['artist','copyright','character','general','meta'];
  const out = {};
  let total = 0;
  for (const c of cats) {
    const ul = document.querySelector('ul.' + c + '-tag-list');
    const names = [];
    if (ul) {
      const seen = new Set();
      ul.querySelectorAll('[data-tag-name]').forEach((el) => {
        const n = el.getAttribute('data-tag-name');
        if (n && !seen.has(n)) { seen.add(n); names.push(n); }
      });
    }
    out[c] = names; total += names.length;
  }
  const m = location.pathname.match(/\\/posts\\/(\\d+)/);
  out.post_id = m ? m[1] : null;
  out.__total = total;
  return out;
})()`;

// Mirror of danbooru_routes.normalize_danbooru_browser_url (host-locked).
function resolveDanbooruUrl(text) {
  const value = String(text || "").trim();
  const base = "https://danbooru.donmai.us";
  let url;
  if (!value) {
    url = `${base}/posts?tags=rating%3Ageneral&z=5`;
  } else if (/^\d+$/.test(value)) {
    url = `${base}/posts/${value}`;
  } else if (value.startsWith("//")) {
    url = "https:" + value;
  } else if (value.startsWith("/")) {
    url = base + value;
  } else if (/^(?:www\.)?danbooru\.donmai\.us(?:\/|$)/i.test(value)) {
    url = "https://" + value;
  } else if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(value)) {
    url = `${base}/posts?tags=${encodeURIComponent(value)}`;
  } else {
    url = value;
  }
  try {
    const parsed = new URL(url);
    const host = (parsed.hostname || "").toLowerCase();
    if (!["http:", "https:"].includes(parsed.protocol) || !DANBOORU_HOSTS.has(host)) {
      return null;
    }
    return parsed.toString();
  } catch (_error) {
    return null;
  }
}

function roundRect(rect) {
  return {
    x: Math.round(Number(rect && rect.x) || 0),
    y: Math.round(Number(rect && rect.y) || 0),
    width: Math.max(0, Math.round(Number(rect && rect.width) || 0)),
    height: Math.max(0, Math.round(Number(rect && rect.height) || 0)),
  };
}

function sendDanbooruNav() {
  if (!mainWindow || mainWindow.isDestroyed() || !danbooruView) {
    return;
  }
  const wc = danbooruView.webContents;
  const url = wc.getURL();
  const match = DANBOORU_POST_RE.exec(url || "");
  mainWindow.webContents.send("naia:danbooru-did-navigate", {
    url,
    postId: match ? match[1] : null,
    canGoBack: wc.canGoBack(),
    canGoForward: wc.canGoForward(),
  });
}

function danbooruImageLabel(srcURL) {
  try {
    const parsed = new URL(srcURL);
    const base = decodeURIComponent((parsed.pathname.split("/").pop() || "").split("?")[0]) || "";
    return (base || "Danbooru Image").slice(0, 120);
  } catch (_error) {
    return "Danbooru Image";
  }
}

// 우클릭 "히스토리에 추가": 임베드 뷰의 세션(쿠키 + Chromium 네트워크 스택)으로 이미지를
// 받아(서버사이드 requests 와 달리 Cloudflare JA3 차단 우회) data URL 로 렌더러에 전달한다.
// 렌더러(danbooruTab)가 /api/image/insert-history 로 넣고 성공 시 단부루 패널을 최소화한다.
async function sendDanbooruImageToHistory(srcURL) {
  if (!mainWindow || mainWindow.isDestroyed() || !danbooruView || danbooruView.webContents.isDestroyed()) {
    return;
  }
  const target = mainWindow.webContents;
  try {
    const ses = danbooruView.webContents.session;
    if (!ses || typeof ses.fetch !== "function") {
      throw new Error("세션 fetch 를 사용할 수 없습니다.");
    }
    const resp = await ses.fetch(srcURL);
    if (!resp.ok) {
      throw new Error("HTTP " + resp.status);
    }
    const buf = Buffer.from(await resp.arrayBuffer());
    if (!buf.length) {
      throw new Error("빈 이미지");
    }
    const contentType = String(resp.headers.get("content-type") || "image/jpeg").split(";")[0].trim() || "image/jpeg";
    const dataUrl = "data:" + contentType + ";base64," + buf.toString("base64");
    target.send("naia:danbooru-insert-history", { dataUrl, label: danbooruImageLabel(srcURL) });
  } catch (error) {
    target.send("naia:danbooru-insert-history", {
      error: "이미지를 가져오지 못했습니다: " + String((error && error.message) || error),
    });
  }
}

// Cloudflare 워밍업 상태 머신. did-finish-load 마다 호출되어, 현재 페이지가 CF
// 챌린지("Just a moment…" / window._cf_chl_opt)면 그대로 대기하고(챌린지가 스스로
// 다시 로드하며 이 훅을 재발화), safebooru 에서 정상 페이지가 확인되면 danbooru 로
// 조용히 천이한다. danbooru 정상 페이지가 뜨면 done 으로 잠가 재천이를 막는다.
async function maybeAdvanceDanbooruWarmup() {
  if (danbooruWarmupState === "idle" || danbooruWarmupState === "done") {
    return;
  }
  if (!danbooruView || danbooruView.webContents.isDestroyed()) {
    return;
  }
  const wc = danbooruView.webContents;
  let info;
  try {
    info = await wc.executeJavaScript(
      "({cf: !!window._cf_chl_opt, title: String(document.title || ''), host: String(location.hostname || '')})",
      true,
    );
  } catch (_error) {
    return;
  }
  if (!info || typeof info !== "object") {
    return;
  }
  const isChallenge = !!info.cf
    || /just a moment|attention required|잠시\s*만|사람인지 확인/i.test(String(info.title || ""));
  if (isChallenge) {
    return; // CF 진행 중 — 챌린지가 다음 로드를 다시 발화한다.
  }
  const host = String(info.host || "").toLowerCase();
  if (danbooruWarmupState === "safebooru" && host === "safebooru.donmai.us") {
    danbooruWarmupState = "transitioned";
    try { wc.loadURL(DANBOORU_HOME_URL); } catch (_error) {}
    return;
  }
  if (danbooruWarmupState === "transitioned" && DANBOORU_HOSTS.has(host)) {
    danbooruWarmupState = "done";
  }
}

function ensureDanbooruView() {
  if (danbooruView) {
    return danbooruView;
  }
  const view = new WebContentsView({
    webPreferences: {
      session: session.fromPartition("persist:danbooru"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  const wc = view.webContents;
  // donmai target=_blank (source links, full image) must not spawn raw windows.
  wc.setWindowOpenHandler(({ url }) => {
    try {
      const host = new URL(url).hostname.toLowerCase();
      if (DANBOORU_VIEW_HOSTS.has(host)) {
        wc.loadURL(url);
      } else if (isHttpLikeUrl(url)) {
        shell.openExternal(url);
      }
    } catch (_error) {}
    return { action: "deny" };
  });
  // Keep the embedded view strictly on http(s) danbooru/safebooru.donmai.us — reject
  // other schemes (javascript:/file:/…) and off-allowlist server redirects. safebooru
  // is allowed because the Cloudflare warm-up hop redirects within its own host.
  const guardNavigation = (event, url) => {
    let allowed = false;
    try {
      const parsed = new URL(url);
      allowed = ["http:", "https:"].includes(parsed.protocol)
        && DANBOORU_VIEW_HOSTS.has((parsed.hostname || "").toLowerCase());
    } catch (_error) {
      allowed = false;
    }
    if (!allowed) {
      event.preventDefault();
      if (isHttpLikeUrl(url)) {
        shell.openExternal(url);
      }
    }
  };
  wc.on("will-navigate", guardNavigation);
  wc.on("will-redirect", guardNavigation);
  wc.on("did-navigate", () => sendDanbooruNav());
  wc.on("did-navigate-in-page", () => sendDanbooruNav());
  // Cloudflare 워밍업 진행: 각 로드 완료마다 챌린지 통과 여부를 확인하고, safebooru
  // 에서 정상 페이지가 확인되면 조용히 danbooru 로 천이한다.
  wc.on("did-finish-load", () => { void maybeAdvanceDanbooruWarmup(); });
  // 워밍업 실패 복구: safebooru 로드나 danbooru 천이가 네트워크 오류/차단으로 실패하면
  // did-finish-load 가 안 와 뷰가 멈춘다. safebooru 로 되돌려 재워밍업(상한까지). ERR_ABORTED
  // (-3, CF 리다이렉트로 앞선 로드가 대체된 경우)는 정상이라 무시한다.
  wc.on("did-fail-load", (_event, errorCode, _errorDesc, _validatedURL, isMainFrame) => {
    if (!isMainFrame || errorCode === -3) return;
    if (danbooruWarmupState !== "safebooru" && danbooruWarmupState !== "transitioned") return;
    if (danbooruWarmupRetries >= DANBOORU_WARMUP_MAX_RETRIES) return;
    danbooruWarmupRetries += 1;
    danbooruWarmupState = "safebooru";
    setTimeout(() => {
      try {
        if (danbooruView && !danbooruView.webContents.isDestroyed()) {
          danbooruView.webContents.loadURL(SAFEBOORU_HOME_URL);
        }
      } catch (_error) {}
    }, 1500);
  });
  // 우클릭 컨텍스트 메뉴: 이미지에 한해 복사 / 저장 (donmai 임베드 뷰).
  wc.on("context-menu", (_event, params) => {
    if (params.mediaType !== "image" || !params.srcURL) {
      return;
    }
    const menu = Menu.buildFromTemplate([
      { label: "이미지 복사", click: () => { try { wc.copyImageAt(params.x, params.y); } catch (_error) {} } },
      { label: "이미지 저장", click: () => { try { wc.downloadURL(params.srcURL); } catch (_error) {} } },
      { type: "separator" },
      { label: "히스토리에 추가", click: () => { void sendDanbooruImageToHistory(params.srcURL); } },
    ]);
    try { menu.popup({ window: mainWindow }); } catch (_error) {}
  });
  danbooruView = view;
  return view;
}

function attachDanbooruView(rect) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return false;
  }
  const view = ensureDanbooruView();
  if (!danbooruViewAttached) {
    mainWindow.contentView.addChildView(view);
    danbooruViewAttached = true;
  }
  view.setBounds(roundRect(rect));
  if (!view.webContents.getURL()) {
    // Cold 로드: danbooru 직접 접속이 (한국에서) 막히므로 safebooru 로 먼저 붙어
    // Cloudflare 를 통과시키고, 정상 페이지 확인 후 maybeAdvanceDanbooruWarmup 이
    // danbooru 로 천이한다.
    danbooruWarmupRetries = 0;
    danbooruWarmupState = "safebooru";
    view.webContents.loadURL(SAFEBOORU_HOME_URL);
  }
  sendDanbooruNav();
  return true;
}

function detachDanbooruView() {
  if (danbooruView && danbooruViewAttached && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.contentView.removeChildView(danbooruView);
  }
  danbooruViewAttached = false;
}

// The danbooru view drives the MAIN window overlay; only the trusted main-window
// renderer may control it. The same preload is shared with external http popups, so
// every handler rejects calls from any other WebContents (incl. the danbooru view).
function isDanbooruSender(event) {
  return !!(
    mainWindow
    && !mainWindow.isDestroyed()
    && event
    && event.sender === mainWindow.webContents
  );
}

ipcMain.handle("naia:danbooru-attach", (event, rect) =>
  isDanbooruSender(event) ? attachDanbooruView(rect) : false);
ipcMain.handle("naia:danbooru-detach", (event) => {
  if (isDanbooruSender(event)) {
    detachDanbooruView();
  }
  return true;
});
ipcMain.handle("naia:danbooru-set-bounds", (event, rect) => {
  if (isDanbooruSender(event) && danbooruView && danbooruViewAttached) {
    danbooruView.setBounds(roundRect(rect));
  }
  return true;
});
ipcMain.handle("naia:danbooru-navigate", (event, text) => {
  if (!isDanbooruSender(event)) {
    return { ok: false, error: "forbidden" };
  }
  const url = resolveDanbooruUrl(text);
  if (!url) {
    return { ok: false, error: "Danbooru URL, post ID, or tag query is required" };
  }
  ensureDanbooruView().webContents.loadURL(url);
  return { ok: true, url };
});
ipcMain.handle("naia:danbooru-back", (event) => {
  if (isDanbooruSender(event) && danbooruView && danbooruView.webContents.canGoBack()) {
    danbooruView.webContents.goBack();
  }
  return true;
});
ipcMain.handle("naia:danbooru-forward", (event) => {
  if (isDanbooruSender(event) && danbooruView && danbooruView.webContents.canGoForward()) {
    danbooruView.webContents.goForward();
  }
  return true;
});
ipcMain.handle("naia:danbooru-reload", (event) => {
  if (isDanbooruSender(event) && danbooruView) {
    danbooruView.webContents.reload();
  }
  return true;
});
// Crawl tags from the live view DOM (the page is already rendered with the user's
// session). Polls briefly because did-navigate can fire before the tag list paints.
ipcMain.handle("naia:danbooru-extract-post", async (event) => {
  if (!isDanbooruSender(event) || !danbooruView || danbooruView.webContents.isDestroyed()) {
    return { ok: false, error: "no view" };
  }
  const wc = danbooruView.webContents;
  for (let attempt = 0; attempt < 8; attempt++) {
    try {
      const data = await wc.executeJavaScript(DANBOORU_EXTRACT_JS);
      if (data && data.__total > 0 && data.post_id) {
        return { ok: true, extracted: data, post_id: data.post_id };
      }
    } catch (_error) {
      // page mid-load / navigated away — retry
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return { ok: false, error: "no tags on page" };
});

ipcMain.handle("naia:shell-state", () => shellState());
ipcMain.handle("naia:restart-backend", async () => {
  // The "NAIA 재시작" button is the explicit completion of a bootstrap
  // migration: clearing this lets the still-pending install gate finish once
  // the freshly-restarted backend reports tag data ready.
  bootstrapMigrationActive = false;
  // Show the maintenance view FIRST: the install gate's progress/choice UI only
  // renders there, so a restart that has to wait on the gate (e.g. tag data
  // still missing after a migration) would otherwise look like a hang on
  // whatever page issued the restart (bootstrap.html just shows "재시작 중…").
  // Contract note: navigating here destroys the renderer context that issued
  // this invoke, so the returned promise may never settle for that caller —
  // this was already the case via the final loadURL below, and every caller
  // (maintenance.html, dataMigrationPanel, smoke_electron_cdp's
  // "navigated or closed" handler) tolerates it.
  loadMaintenance("loading", "NAIA 재시작 중...");
  stopBackend();
  // Wait for the old process to actually exit (its 'exit' handler clears
  // ``backendProcess``) before spawning the replacement. The previous fixed
  // 750ms was racy under load: when the kill took longer, ``ensureBackendReady``
  // saw a still-set ``backendProcess``, skipped the spawn entirely, and then
  // polled a dead port for 30s.
  const exitDeadline = Date.now() + 15000;
  while (backendProcess && Date.now() < exitDeadline) {
    await delay(100);
  }
  if (backendProcess) {
    appendBackendLog("shell", "restart: old backend still alive after 15s; proceeding anyway");
  }
  await delay(750); // let the OS release the port before the same-port respawn
  backendState = "starting";
  const url = await ensureBackendReady();
  // Tag data is mandatory runtime data. If the restart finds it missing (a
  // migration whose source had no data/tags, or a partial copy), start the
  // Hugging Face download now so the gate shows download progress instead of
  // parking on the two-choice screen again. Skipped when the gate itself is
  // disabled (dev runs) so a source checkout never auto-downloads ~1.4 GB.
  if (shouldRunRuntimeInstallGate()) {
    try {
      const status = await httpJsonRequest(`${url}/api/install-manager`);
      if (!runtimeInstallReadyFromPayload(status)) {
        const started = await httpJsonRequest(
          `${url}/api/install-manager/tag-archive/download`,
          { method: "POST" },
        );
        runtimeInstallChoiceMade = true;
        setRuntimeInstallState(normalizeRuntimeInstallState(started, { active: true }));
      }
    } catch (error) {
      // Non-fatal: the gate below still runs and surfaces its own state.
      appendBackendLog("shell", `restart tag-data check failed: ${error && error.message}`);
    }
  }
  // The gate must not strand the shell on the maintenance view. Before the
  // restart flow navigated here first, the window stayed on the app page, so a
  // transient gate failure (stale keep-alive socket to the reused port, a slow
  // first response from the just-booted backend) was invisible and the page
  // self-healed over its WebSocket. Now the window is parked on
  // maintenance.html, so a single throw would leave it there forever. Retry
  // once, then fall back to navigating anyway when the backend itself reports
  // tag data ready.
  let gateError = null;
  try {
    await ensureRuntimeInstallReady(url);
  } catch (error) {
    gateError = error;
    appendBackendLog("shell", `restart install gate failed: ${error && error.message}; retrying once`);
    await delay(1500);
    try {
      await ensureRuntimeInstallReady(url);
      gateError = null;
    } catch (retryError) {
      gateError = retryError;
      appendBackendLog("shell", `restart install gate retry failed: ${retryError && retryError.message}`);
    }
  }
  if (gateError) {
    let readyAnyway = false;
    try {
      const status = await httpJsonRequest(`${url}/api/install-manager`);
      readyAnyway = runtimeInstallReadyFromPayload(status);
    } catch (_error) {
      readyAnyway = false;
    }
    if (!readyAnyway) {
      // Surface the failure in the maintenance UI (its 재시작 button stays
      // usable) instead of a silent, permanent "NAIA 재시작 중...".
      loadMaintenance("error", `재시작 후 데이터 게이트 실패: ${gateError && gateError.message}`);
      return shellState();
    }
    appendBackendLog("shell", "restart: install gate errored but tag data is ready; continuing to app");
  }
  if (mainWindow && !mainWindow.isDestroyed()) {
    try {
      await mainWindow.loadURL(remoteEntryUrl(url));
    } catch (error) {
      // ERR_ABORTED from a competing navigation is not fatal — whatever
      // superseded this navigation is what the user sees.
      appendBackendLog("shell", `restart loadURL failed: ${error && error.message}`);
    }
  }
  return shellState();
});
ipcMain.handle("naia:start-tag-download", async () => {
  // Maintenance window asks us to fetch the tag corpus from Hugging Face.
  // Marks the gate's choice as made so the deadline kicks in and the polling
  // loop transitions from "awaiting_choice" to active download progress.
  if (!backendUrl) return { ok: false, error: "Backend not ready." };
  try {
    const payload = await httpJsonRequest(`${backendUrl}/api/install-manager/tag-archive/download`, { method: "POST" });
    // Choosing the download abandons any in-progress migration handshake so the
    // gate completes on download readiness.
    bootstrapMigrationActive = false;
    runtimeInstallChoiceMade = true;
    setRuntimeInstallState(normalizeRuntimeInstallState(payload, { active: true }));
    // If we were on the standalone migration page, return to the maintenance
    // view so the user sees download progress (it renders the progress bar).
    loadMaintenance("loading", "태그 데이터 다운로드 중...");
    return { ok: true };
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    return { ok: false, error: message };
  }
});
ipcMain.handle("naia:start-bootstrap-migration", async () => {
  // User wants to bring tag data over from a previous NAIA2.0 install. We hand
  // off to the main app's data migration UI by loading it with a bootstrap
  // hint, then mark the choice as made so the install gate polls under the
  // normal deadline. Once migration writes tag files to disk the install
  // manager will report ready and the gate completes — at that point the
  // user will use the existing "NAIA 재시작" button which re-loads main app
  // without the bootstrap hint.
  if (!backendUrl) return { ok: false, error: "Backend not ready." };
  if (mainWindow && !mainWindow.isDestroyed()) {
    // Load the standalone migration page (NOT the full app). This keeps the
    // migration a focused, pre-launch step instead of opening the real app
    // (which would show API/random-prompt errors and need a large window).
    expandMainWindowForApp();
    try {
      await mainWindow.loadURL(`${backendUrl.replace(/\/+$/, "")}/bootstrap.html`);
    } catch (error) {
      // Navigation failed — do NOT mark the choice as made, otherwise the
      // install gate would start a deadline against a UI that never loaded.
      const message = error && error.message ? error.message : String(error);
      return { ok: false, error: message };
    }
  }
  // Only now that the migration UI is actually showing do we mark the migration
  // path active. The gate keeps waiting (no deadline) until the user clicks
  // "NAIA 재시작", which clears this flag and completes via a clean restart.
  bootstrapMigrationActive = true;
  return { ok: true };
});
ipcMain.handle("naia:open-browser", () => shell.openExternal(`${backendUrl}/?desktop_shell=1`));
ipcMain.handle("naia:open-data-folder", () => shell.openPath(runtimeDataRoot()));
ipcMain.handle("naia:open-logs", () => openRuntimeSubfolder("logs"));

// Interactive 의 태그 사전 플로트는 팝업 오른쪽에 258px 가 남아야 뜬다. Electron 창이
// 그보다 좁으면 아무 표시 없이 사라져 기능이 고장난 것처럼 보였다(2026-07-30).
// 렌더러가 필요한 CSS 폭을 알려주면 여기서 두 단계로 맞춘다.
//   1) 창을 넓힌다 — 작업 영역을 넘지 않는 선에서. 대개 여기서 해결된다.
//   2) 그래도 모자라면 줌을 한 단계씩 낮춘다(ZOOM_MIN 0.8 까지).
// 줌을 먼저 낮추지 않는 이유: 창을 넓히는 편이 글자 크기를 지켜 준다.
ipcMain.handle("naia:fit-width", (_event, cssWidth) => {
  const need = Math.max(320, Math.round(Number(cssWidth) || 0));
  const win = mainWindow;
  if (!win || win.isDestroyed()) return { ok: false, reason: "no-window" };
  const cssNow = () => {
    let zoom = 1.0;
    try { zoom = win.webContents.getZoomFactor() || 1.0; } catch (_e) { zoom = loadZoomFactor(); }
    const [w] = win.getContentSize();
    return { zoom, css: Math.floor(w / zoom) };
  };
  const before = cssNow();
  let resized = false;
  // 1단계 — 창 넓히기. 최대화 상태에서는 늘릴 수 없으니 건너뛴다.
  if (before.css < need && !win.isMaximized() && !win.isFullScreen()) {
    try {
      const area = screen.getDisplayMatching(win.getBounds()).workArea;
      const b = win.getBounds();
      const [cw] = win.getContentSize();
      const chrome = b.width - cw;                       // 테두리 폭
      const wantContent = Math.ceil(need * before.zoom);
      const wantWidth = Math.min(area.width, wantContent + chrome);
      if (wantWidth > b.width) {
        let x = b.x;
        if (x + wantWidth > area.x + area.width) x = Math.max(area.x, area.x + area.width - wantWidth);
        win.setBounds({ x, y: b.y, width: wantWidth, height: b.height });
        resized = true;
      }
    } catch (_error) {}
  }
  // 2단계 — 그래도 모자라면 줌을 단계별로 낮춘다.
  let zoomed = false;
  let cur = cssNow();
  let guard = 0;
  while (cur.css < need && cur.zoom > ZOOM_MIN + 1e-9 && guard++ < 8) {
    const next = clampZoom(cur.zoom - ZOOM_STEP);
    if (next >= cur.zoom) break;
    try { win.webContents.setZoomFactor(next); } catch (_error) { break; }
    saveZoomFactor(next);
    zoomed = true;
    cur = cssNow();
  }
  return { ok: cur.css >= need, need, cssWidth: cur.css, zoom: cur.zoom, resized, zoomed,
           before: before.css };
});
ipcMain.handle("naia:pick-directory", async () => {
  const win = BrowserWindow.getFocusedWindow() || BrowserWindow.getAllWindows()[0] || null;
  const options = { properties: ["openDirectory"], title: "이전 NAIA2.0 데이터 폴더 선택" };
  const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  if (result.canceled || !Array.isArray(result.filePaths) || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});
// 이미지 저장 폴더 선택 전용 — 데이터-마이그레이션 핸들러와 분리(제목/생성옵션 다름). createDirectory 로
// 새 폴더 생성 허용(macOS 전용 플래그지만 Windows 네이티브 다이얼로그는 이미 "새 폴더" 지원, 무해).
ipcMain.handle("naia:pick-save-directory", async () => {
  const win = BrowserWindow.getFocusedWindow() || BrowserWindow.getAllWindows()[0] || null;
  const options = { properties: ["openDirectory", "createDirectory"], title: "이미지 저장 폴더 선택" };
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

// ===== Grok(xAI) OAuth + 프록시 (ima2 패턴, 제거 가능 블록) ===========================
// 번들된 progrok 를 NAIA.exe(=Electron) 를 Node 로 써서(ELECTRON_RUN_AS_NODE) 구동한다.
//   - app ready 시 `progrok proxy` 를 관리 자식으로 자동 기동(미로그인 시 auth_required 로 종료)
//   - naia:grok-login 이 `progrok login --browser`(로컬백 자동 캡처) 실행 → 성공 시 프록시 재기동
//   - 토큰/프록시 모두 progrok 가 관리, NAIA 는 토큰을 보관하지 않는다.
// 제거: 이 블록 + preload 의 grok* + resources/progrok-runtime + 프론트 패널만 지우면 됨.
const GROK_PROXY_HOST = "127.0.0.1";
const GROK_PROXY_PORT = 18645; // default base port; resolved dynamically below
const GROK_PROXY_PORT_ENV = "NAIA_GROK_PROXY_PORT";
let grokProxyProcess = null;
let grokProxyState = "stopped"; // stopped|starting|ready|auth_required|offline|unavailable
let grokProxyPort = readPort(process.env[GROK_PROXY_PORT_ENV], GROK_PROXY_PORT);
let grokLoginProcess = null;

function grokRuntimeRoot() {
  return path.join(resourcesRoot(), "progrok-runtime");
}

function grokProgrokEntry() {
  const entry = path.join(grokRuntimeRoot(), "node_modules", "progrok", "dist", "index.js");
  return fs.existsSync(entry) ? entry : null;
}

// progrok stores its OAuth tokens at ~/.progrok/auth.json (CONFIG_DIR/AUTH_FILE
// in progrok's token store; we spawn it without overriding HOME). Used to skip
// the startup proxy spawn for users who never logged in — for them the proxy
// is started lazily by ``naia:grok-login`` (which always restarts the proxy
// when the login process exits) or the manual ``naia:grok-restart-proxy``.
function grokAuthFilePresent() {
  try {
    return fs.existsSync(path.join(os.homedir(), ".progrok", "auth.json"));
  } catch (_e) {
    return false;
  }
}

function spawnGrok(args, opts = {}) {
  if (!grokProgrokEntry()) return null;
  // NAIA.exe 를 Node 로 실행(ELECTRON_RUN_AS_NODE). grok-launch.cjs 가 commander 의
  // electron argv 오슬라이스(process.defaultApp 보정) + ESM 동적 import 를 처리한다.
  const launcher = path.join(grokRuntimeRoot(), "grok-launch.cjs");
  return spawn(process.execPath, [launcher, ...args], {
    windowsHide: true,
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
    ...opts,
  });
}

function grokState() {
  return { available: !!grokProgrokEntry(), proxyState: grokProxyState, host: GROK_PROXY_HOST, port: grokProxyPort };
}

function broadcastGrokState() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("naia:grok-state-changed", grokState());
  }
}

function setGrokProxyState(state) {
  grokProxyState = state;
  broadcastGrokState();
}

function probePort(host, port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", () => {
      try { srv.close(); } catch (_e) {}
      resolve(false);
    });
    srv.once("listening", () => {
      srv.close(() => resolve(true));
    });
    srv.listen(port, host);
  });
}

async function findFreePort(host, startPort, maxTries = 64) {
  for (let i = 0; i < maxTries; i += 1) {
    const candidate = startPort + i;
    if (candidate > 65535) break;
    // eslint-disable-next-line no-await-in-loop
    if (await probePort(host, candidate)) {
      return candidate;
    }
  }
  // Nothing free in range: fall back to the base port. We deliberately do NOT
  // throw — Grok is optional and this runs during startup; throwing would block
  // the main window. progrok then just reports "unavailable" if it cannot bind,
  // exactly like the pre-dynamic-port behavior.
  return startPort;
}

// Resolve the progrok proxy port BEFORE the backend spawns so the Electron shell
// and the Python backend (NAIA_GROK_PROXY_PORT) agree on it. An explicit
// NAIA_GROK_PROXY_PORT wins (deterministic, race-free — the launcher uses this for
// guaranteed isolation); otherwise probe upward from the default so multiple
// concurrent instances each get their own proxy instead of colliding on 18645.
// The probe is best-effort: there is a small check-then-bind window, so on the
// rare simultaneous start it degrades to the old single-proxy behavior (one
// instance's progrok reports unavailable) rather than corrupting anything.
async function resolveGrokProxyPort() {
  const explicit = readPort(process.env[GROK_PROXY_PORT_ENV], 0);
  if (explicit) {
    grokProxyPort = explicit;
    return grokProxyPort;
  }
  try {
    grokProxyPort = await findFreePort(GROK_PROXY_HOST, GROK_PROXY_PORT);
  } catch (_error) {
    grokProxyPort = GROK_PROXY_PORT;
  }
  return grokProxyPort;
}

function startGrokProxy() {
  if (!grokProgrokEntry()) { setGrokProxyState("unavailable"); return; }
  if (grokProxyProcess) return;
  let authRequired = false;
  const child = spawnGrok(["proxy", "--host", GROK_PROXY_HOST, "--port", String(grokProxyPort)], {
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (!child) { setGrokProxyState("unavailable"); return; }
  grokProxyProcess = child;
  setGrokProxyState("starting");
  const scan = (buf) => {
    const text = String(buf || "");
    appendBackendLog("grok", text.trim());
    const m = text.match(/https?:\/\/(?:127\.0\.0\.1|localhost):(\d+)\/v1/i);
    if (m) { grokProxyPort = Number(m[1]) || GROK_PROXY_PORT; setGrokProxyState("ready"); }
    if (/not logged in|progrok login|grok login/i.test(text)) authRequired = true;
  };
  child.stdout.on("data", scan);
  child.stderr.on("data", scan);
  child.on("error", (error) => appendBackendLog("grok", `proxy error: ${error.message}`));
  child.on("exit", (code) => {
    grokProxyProcess = null;
    if (quitting) return;
    setGrokProxyState(authRequired ? "auth_required" : "offline");
  });
}

function stopGrokProxy() {
  if (grokLoginProcess) { try { grokLoginProcess.kill(); } catch (_e) {} grokLoginProcess = null; }
  if (!grokProxyProcess) return;
  try { grokProxyProcess.kill(); } catch (_e) {}
  grokProxyProcess = null;
}

ipcMain.handle("naia:grok-state", () => grokState());

ipcMain.handle("naia:grok-restart-proxy", () => {
  stopGrokProxy();
  startGrokProxy();
  return grokState();
});

ipcMain.handle("naia:grok-login", async () => {
  if (!grokProgrokEntry()) return { ok: false, message: "progrok 런타임이 번들되지 않았습니다." };
  if (grokLoginProcess) return { ok: false, message: "이미 로그인 진행 중입니다. 열린 브라우저에서 완료하세요." };
  stopGrokProxy(); // 로그인 중에는 프록시를 내려 56121 콜백/토큰 파일 경합을 피한다.
  return await new Promise((resolve) => {
    const child = spawnGrok(["login", "--browser"], { stdio: ["ignore", "pipe", "pipe"] });
    if (!child) { startGrokProxy(); resolve({ ok: false, message: "progrok 실행 실패." }); return; }
    grokLoginProcess = child;
    let tail = "";
    const onData = (buf) => { const t = String(buf || ""); tail = (tail + t).slice(-2000); appendBackendLog("grok-login", t.trim()); };
    child.stdout.on("data", onData);
    child.stderr.on("data", onData);
    child.on("error", (error) => { grokLoginProcess = null; startGrokProxy(); resolve({ ok: false, message: `로그인 실행 오류: ${error.message}` }); });
    child.on("exit", (code) => {
      grokLoginProcess = null;
      startGrokProxy(); // 로그인 결과와 무관하게 프록시 재기동(성공 시 ready, 실패 시 auth_required)
      if (code === 0) { resolve({ ok: true, message: "로그인 완료." }); return; }
      const lastLines = tail.split(/\r?\n/).filter(Boolean).slice(-2).join(" ");
      resolve({ ok: false, message: `로그인 실패 (code ${code}). ${lastLines}`.trim() });
    });
  });
});
// ===== /Grok 블록 ===================================================================

configureRemoteDebugging();

// Make Electron's own userData install-local so SEPARATE-DIRECTORY portable copies run as
// independent instances. The single-instance lock (below) and the persist:danbooru session
// both live under userData; by default that is the global %APPDATA%/<productName>, so every
// copy shares one lock and the 2nd launch just focuses the 1st window and quits. Pointing
// userData at <install>/user-data/electron (the same install-local root the backend already
// uses via runtimeDataRoot()) gives each install its own lock — no launcher needed.
function userDataDirSwitchPresent() {
  // An explicit --user-data-dir (the same-folder launcher tools/launch_naia_instance.ps1, or a
  // manual override) wins — setPath would otherwise clobber that switch. Detect it both via the
  // Electron commandLine API and raw argv so it is robust regardless of how it was passed.
  if (app.commandLine && typeof app.commandLine.hasSwitch === "function" && app.commandLine.hasSwitch("user-data-dir")) {
    return true;
  }
  const argv = Array.isArray(process.argv) ? process.argv : [];
  return argv.some((arg) => arg === "--user-data-dir" || arg.startsWith("--user-data-dir="));
}

function electronUserDataDir() {
  return path.join(runtimeDataRoot(), "electron");
}

// Must run BEFORE requestSingleInstanceLock() so the lock is keyed on the final userData path.
function applyInstallLocalUserData() {
  try {
    if (userDataDirSwitchPresent() || typeof app.setPath !== "function") {
      return null;
    }
    const target = electronUserDataDir();
    fs.mkdirSync(target, { recursive: true });
    app.setPath("userData", target);
    return target;
  } catch (error) {
    // Install dir not writable (e.g. Program Files) — fall back to the default userData.
    appendBackendLog("shell", `userData override skipped: ${error && error.message}`);
    return null;
  }
}

applyInstallLocalUserData();

const lock = app.requestSingleInstanceLock();
if (!lock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (!mainWindow.isVisible()) {
        mainWindow.show();
      }
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    configureApplicationMenu();
    configureDownloads();
    surfaceLastApplyError();
    // Resolve the Grok proxy port first so the backend env carries it (multi-instance).
    await resolveGrokProxyPort();
    createMainWindow();
    // Grok(제거 가능): 로그인 흔적(~/.progrok/auth.json)이 있는 사용자만 번들
    // progrok 프록시를 자동 기동. 미로그인 유저에게는 프로세스를 띄우지 않고
    // auth_required 상태만 노출 — 로그인(naia:grok-login) 종료 시 기존 로직이
    // 프록시를 기동한다.
    if (grokAuthFilePresent()) {
      startGrokProxy();
    } else {
      setGrokProxyState(grokProgrokEntry() ? "auth_required" : "unavailable");
    }
  });
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
  app.on("before-quit", () => {
    quitting = true;
    stopBackend();
    stopGrokProxy(); // Grok(제거 가능)
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
  preventBackNavigation,
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
  resolveGrokProxyPort,
  findFreePort,
  runtimeInstallErrorFromPayload,
  runtimeInstallReadyFromPayload,
  shouldRunRuntimeInstallGate,
  requirementsFingerprint,
  requirementsPath,
  removePythonRuntimeBytecode,
  resourcesRoot,
  runtimeDataRoot,
  electronUserDataDir,
  userDataDirSwitchPresent,
  applyInstallLocalUserData,
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
