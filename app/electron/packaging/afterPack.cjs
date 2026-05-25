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

exports.default = async function afterPack(context) {
  const userDataDir = path.join(context.appOutDir, "user-data");
  fs.mkdirSync(userDataDir, { recursive: true });
  applyWindowsExeIcon(context.appOutDir);
};

exports.__test = {
  applyWindowsExeIcon,
};
