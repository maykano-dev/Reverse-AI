// Minimal, secure bridge. The UI is the existing web app and talks to the
// local backend over HTTP; the only thing worth exposing is a little metadata.
"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("reverseaiDesktop", {
  isDesktop: true,
  info: () => ipcRenderer.invoke("reverseai:info"),
  pickFolder: () => ipcRenderer.invoke("reverseai:pick-folder"),
  onOpenFolder: (cb) => ipcRenderer.on("reverseai:open-folder", (_e, path) => cb(path)),
});
