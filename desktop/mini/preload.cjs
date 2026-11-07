"use strict";

const { contextBridge, ipcRenderer } = require("electron");

// The corner timer only shows what the main process sends, and can ask for Moah's window, start or
// pause the timer, and be dragged somewhere else on the screen.
contextBridge.exposeInMainWorld(
  "moahTimer",
  Object.freeze({
    onState: (listener) => {
      ipcRenderer.on("pomodoro:state", (_event, state) => listener(state));
    },
    open: () => ipcRenderer.send("pomodoro:open"),
    toggle: () => ipcRenderer.send("pomodoro:toggle"),
    drag: (step) => ipcRenderer.send("pomodoro:drag", step),
  }),
);
