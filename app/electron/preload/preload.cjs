"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("naiaShell", {
  getState: () => ipcRenderer.invoke("naia:shell-state"),
  restartBackend: () => ipcRenderer.invoke("naia:restart-backend"),
  openBrowser: () => ipcRenderer.invoke("naia:open-browser"),
  openDataFolder: () => ipcRenderer.invoke("naia:open-data-folder"),
  openLogs: () => ipcRenderer.invoke("naia:open-logs"),
  pickDirectory: () => ipcRenderer.invoke("naia:pick-directory"),
  checkUpdate: () => ipcRenderer.invoke("naia:check-update"),
  downloadUpdate: () => ipcRenderer.invoke("naia:download-update"),
  applyUpdate: () => ipcRenderer.invoke("naia:apply-update"),
  openReleasePage: () => ipcRenderer.invoke("naia:open-release-page"),
  onStateChanged: (callback) => {
    if (typeof callback !== "function") {
      return () => {};
    }
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("naia:shell-state-changed", listener);
    return () => ipcRenderer.removeListener("naia:shell-state-changed", listener);
  },
});
