"use strict";

const { contextBridge, ipcRenderer } = require("electron");

const apiToken = ipcRenderer.sendSync("project-brain:get-token");
contextBridge.exposeInMainWorld(
  "projectBrainDesktop",
  Object.freeze({
    apiToken,
    // Opens the system folder chooser. In a Flatpak this goes through the file portal,
    // which grants the app access to just the folder the person picks. The title comes in the app's language.
    chooseFolder: (title) => ipcRenderer.invoke("project-brain:choose-folder", title),
    // Opens claude:// or codex:// links only; resolves to false when nothing could open it.
    openAgent: (url) => ipcRenderer.invoke("project-brain:open-agent", url),
  }),
);
