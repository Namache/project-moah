"use strict";

const { contextBridge, ipcRenderer } = require("electron");

// The corner timer only shows what the main process sends, and can ask for Moah's window.
contextBridge.exposeInMainWorld(
  "moahTimer",
  Object.freeze({
    onState: (listener) => {
      ipcRenderer.on("pomodoro:state", (_event, state) => listener(state));
    },
    open: () => ipcRenderer.send("pomodoro:open"),
  }),
);
