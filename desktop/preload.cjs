"use strict";

const { contextBridge, ipcRenderer } = require("electron");

const apiToken = ipcRenderer.sendSync("project-brain:get-token");
// "flatpak", "deb", "linux", "windows" or "mac": Help shows the instructions for this system only.
const install = ipcRenderer.sendSync("project-brain:get-install");
// Settings > Accessibility: the saved interface and text size, and what Automatic means on this screen.
const display = ipcRenderer.sendSync("project-brain:get-display");
contextBridge.exposeInMainWorld(
  "projectBrainDesktop",
  Object.freeze({
    apiToken,
    install,
    display,
    setDisplay: (prefs) => ipcRenderer.invoke("project-brain:set-display", prefs),
    // Ctrl+Plus/Minus/0 or a move to another screen changed the size; returns a function that stops listening.
    onDisplayChange: (listener) => {
      const handler = (_event, state) => listener(state);
      ipcRenderer.on("project-brain:display-changed", handler);
      return () => ipcRenderer.removeListener("project-brain:display-changed", handler);
    },
    // Opens the system folder chooser. In a Flatpak this goes through the file portal,
    // which grants the app access to just the folder the person picks. The title comes in the app's language.
    chooseFolder: (title) => ipcRenderer.invoke("project-brain:choose-folder", title),
    // Opens claude:// or codex:// links only; resolves to false when nothing could open it.
    openAgent: (url) => ipcRenderer.invoke("project-brain:open-agent", url),
  }),
);
