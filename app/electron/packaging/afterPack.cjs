"use strict";

const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");

function applyWindowsExeIcon(appOutDir) {
  if (process.platform !== "win32") {
    return;
  }
  const exePath = path.join(appOutDir, "NAIA.exe");
  const iconPath = path.join(__dirname, "..", "assets", "naia.ico");
  const helperPath = path.join(__dirname, "..", "..", "..", "tools", "apply_windows_exe_icon.py");
  for (const target of [exePath, iconPath, helperPath]) {
    if (!fs.existsSync(target)) {
      throw new Error(`Electron icon post-step missing required file: ${target}`);
    }
  }

  const python = process.env.PYTHON || process.env.PYTHON_EXE || "python";
  const completed = childProcess.spawnSync(python, [helperPath, exePath, iconPath], {
    encoding: "utf8",
    windowsHide: true,
  });
  if (completed.error) {
    throw completed.error;
  }
  if (completed.status !== 0) {
    const stdout = String(completed.stdout || "").trim();
    const stderr = String(completed.stderr || "").trim();
    throw new Error([
      `NAIA.exe icon resource update failed with exit code ${completed.status}.`,
      stdout,
      stderr,
    ].filter(Boolean).join("\n"));
  }
}

// Copy the bundled Grok (progrok) runtime into the packaged resources. electron-builder
// strips node_modules from extraResources directory copies, so the staged runtime
// (resources/progrok-runtime, ~700 files incl. node_modules) is copied here instead, raw.
// The source path is handed in via NAIA_PROGROK_RUNTIME_SRC by the release orchestrator;
// when it is absent (e.g. a manual build without Grok) this is a no-op.
function bundleGrokRuntime(appOutDir) {
  const source = process.env.NAIA_PROGROK_RUNTIME_SRC;
  if (!source || !fs.existsSync(source)) {
    return;
  }
  const dest = path.join(appOutDir, "resources", "progrok-runtime");
  fs.rmSync(dest, { recursive: true, force: true });
  fs.cpSync(source, dest, { recursive: true });
  const entry = path.join(dest, "node_modules", "progrok", "dist", "index.js");
  if (!fs.existsSync(entry)) {
    throw new Error(`Grok runtime bundle is incomplete; missing entry: ${entry}`);
  }
}

exports.default = async function afterPack(context) {
  const userDataDir = path.join(context.appOutDir, "user-data");
  fs.mkdirSync(userDataDir, { recursive: true });
  applyWindowsExeIcon(context.appOutDir);
  bundleGrokRuntime(context.appOutDir);
};

exports.__test = {
  applyWindowsExeIcon,
  bundleGrokRuntime,
};
