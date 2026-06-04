"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("naiaShell", {
  getState: () => ipcRenderer.invoke("naia:shell-state"),
  restartBackend: () => ipcRenderer.invoke("naia:restart-backend"),
  startTagDownload: () => ipcRenderer.invoke("naia:start-tag-download"),
  startBootstrapMigration: () => ipcRenderer.invoke("naia:start-bootstrap-migration"),
  openBrowser: () => ipcRenderer.invoke("naia:open-browser"),
  openDataFolder: () => ipcRenderer.invoke("naia:open-data-folder"),
  openLogs: () => ipcRenderer.invoke("naia:open-logs"),
  pickDirectory: () => ipcRenderer.invoke("naia:pick-directory"),
  checkUpdate: () => ipcRenderer.invoke("naia:check-update"),
  downloadUpdate: () => ipcRenderer.invoke("naia:download-update"),
  applyUpdate: () => ipcRenderer.invoke("naia:apply-update"),
  openReleasePage: () => ipcRenderer.invoke("naia:open-release-page"),
  // Embedded Danbooru browser (WebContentsView) bridge — Electron shell only.
  danbooruAttach: (rect) => ipcRenderer.invoke("naia:danbooru-attach", rect),
  danbooruDetach: () => ipcRenderer.invoke("naia:danbooru-detach"),
  danbooruSetBounds: (rect) => ipcRenderer.invoke("naia:danbooru-set-bounds", rect),
  danbooruNavigate: (text) => ipcRenderer.invoke("naia:danbooru-navigate", text),
  danbooruBack: () => ipcRenderer.invoke("naia:danbooru-back"),
  danbooruForward: () => ipcRenderer.invoke("naia:danbooru-forward"),
  danbooruReload: () => ipcRenderer.invoke("naia:danbooru-reload"),
  danbooruExtractPost: () => ipcRenderer.invoke("naia:danbooru-extract-post"),
  onDanbooruDidNavigate: (callback) => {
    if (typeof callback !== "function") {
      return () => {};
    }
    const listener = (_event, info) => callback(info);
    ipcRenderer.on("naia:danbooru-did-navigate", listener);
    return () => ipcRenderer.removeListener("naia:danbooru-did-navigate", listener);
  },
  onDanbooruInsertHistory: (callback) => {
    if (typeof callback !== "function") {
      return () => {};
    }
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("naia:danbooru-insert-history", listener);
    return () => ipcRenderer.removeListener("naia:danbooru-insert-history", listener);
  },
  onStateChanged: (callback) => {
    if (typeof callback !== "function") {
      return () => {};
    }
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("naia:shell-state-changed", listener);
    return () => ipcRenderer.removeListener("naia:shell-state-changed", listener);
  },
  // Grok(xAI) OAuth + 프록시 브리지 (제거 가능)
  grokState: () => ipcRenderer.invoke("naia:grok-state"),
  grokLogin: () => ipcRenderer.invoke("naia:grok-login"),
  grokRestartProxy: () => ipcRenderer.invoke("naia:grok-restart-proxy"),
  onGrokStateChanged: (callback) => {
    if (typeof callback !== "function") {
      return () => {};
    }
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("naia:grok-state-changed", listener);
    return () => ipcRenderer.removeListener("naia:grok-state-changed", listener);
  },
});

// Browser-style Ctrl + mouse-wheel zoom for the NAIA app (the Electron shell has no
// browser chrome to provide it). Captured before any grid wheel-paginators so a
// Ctrl+scroll only zooms — it never falls through to page navigation. The main process
// applies and persists the zoom factor (see naia:zoom-by).
window.addEventListener(
  "wheel",
  (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    event.stopPropagation();
    ipcRenderer.send("naia:zoom-by", event.deltaY < 0 ? 1 : -1);
  },
  { passive: false, capture: true }
);
