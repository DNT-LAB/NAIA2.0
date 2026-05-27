"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("naiaShell", {
  getState: () => ipcRenderer.invoke("naia:shell-state"),
  restartBackend: () => ipcRenderer.invoke("naia:restart-backend"),
  openBrowser: () => ipcRenderer.invoke("naia:open-browser"),
  openDataFolder: () => ipcRenderer.invoke("naia:open-data-folder"),
  openLogs: () => ipcRenderer.invoke("naia:open-logs"),
  pickDirectory: () => ipcRenderer.invoke("naia:pick-directory"),
  onStateChanged: (callback) => {
    if (typeof callback !== "function") {
      return () => {};
    }
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("naia:shell-state-changed", listener);
    return () => ipcRenderer.removeListener("naia:shell-state-changed", listener);
  },
});
