"use strict";

// The focus (Pomodoro) timer in the main process: its settings file, the timer, the small corner
// window that stays on the desktop while the timer is turned on, and the messages to Moah's window.
// The rules themselves are in pomodoro-core.cjs.

const { BrowserWindow, dialog, ipcMain, screen } = require("electron");
const { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } = require("node:fs");
const path = require("node:path");
const core = require("./pomodoro-core.cjs");

// The oval is about 96 x 36; the window leaves room around it for its shadow and the glowing Review count.
const MINI_MARGIN = { x: 0, y: 0 };
// How far that see-through edge may go past the monitor's edge when dragged (at the small size).
const MINI_OVERHANG = 8;
const X11_MARKER = "use-x11";

/**
 * On a Linux Wayland session the corner timer can't be placed or kept on top, so while the timer is
 * on, Moah starts through XWayland. The Flatpak's launcher reads the marker file itself; any other
 * Linux install starts again with the switch. Call it before anything else starts.
 */
function relaunchForX11(app) {
  if (process.platform !== "linux" || existsSync("/.flatpak-info")) return false;
  if (!process.env.WAYLAND_DISPLAY || !process.env.DISPLAY) return false;
  if (app.commandLine.getSwitchValue("ozone-platform") === "x11") return false;
  if (!existsSync(path.join(app.getPath("userData"), X11_MARKER))) return false;
  app.relaunch({ args: [...process.argv.slice(1), "--ozone-platform=x11"] });
  return true;
}

function createPomodoro({ app, getMainWindow, showMainWindow, say, writeLog = () => {} }) {
  const dir = app.getPath("userData");
  const settingsPath = path.join(dir, "pomodoro.json");
  const soundsDir = path.join(dir, "sounds");
  const display = core.linuxDisplay({ platform: process.platform, env: process.env, ozonePlatform: app.commandLine.getSwitchValue("ozone-platform") });
  // Placing a window and keeping it on top both work everywhere except a Linux Wayland session.
  const miniSupported = display !== "wayland";
  let settings = load();
  let mini = null;
  let miniReady = false;

  function load() {
    try {
      return core.cleanSettings(JSON.parse(readFileSync(settingsPath, "utf8")));
    } catch {
      return core.cleanSettings(null);
    }
  }

  function save() {
    try {
      mkdirSync(dir, { recursive: true });
      const temporary = `${settingsPath}.tmp`;
      writeFileSync(temporary, JSON.stringify(settings, null, 2));
      renameSync(temporary, settingsPath);
    } catch (error) {
      writeLog(`[timer] couldn't save settings: ${error.message}`);
    }
  }

  function syncX11Marker() {
    if (process.platform !== "linux") return;
    const marker = path.join(dir, X11_MARKER);
    try {
      if (settings.enabled) writeFileSync(marker, "The focus timer is on: start Project Moah through XWayland so its corner timer can stay on top.\n");
      else rmSync(marker, { force: true });
    } catch (error) {
      writeLog(`[timer] ${error.message}`);
    }
  }

  const timer = core.createTimer({
    plan: () => core.durations(settings),
    onChange: broadcast,
    onCue: cue,
  });
  const reviews = core.createReviewWatch({
    onChange: broadcast,
    onNew: () => cue("review"),
  });

  function labels() {
    return {
      focus: say("Focus"),
      break: say("Break"),
      paused: say("Paused"),
      ready: say("Ready"),
      open: say("Open Project Moah"),
      start: say("Start"),
      resume: say("Resume"),
      pause: say("Pause"),
      startFocus: say("Start focus"),
      startBreak: say("Start break"),
      breakReady: say("Break is ready"),
      focusReady: say("Time to focus"),
      review: say("{count} waiting for review"),
      left: say("{time} left"),
    };
  }

  function state() {
    return {
      settings,
      timer: timer.snapshot(),
      review: reviews.total,
      miniSupported,
      restartNeeded: settings.enabled && display === "wayland",
      now: Date.now(),
    };
  }

  function send(webContents, channel, payload) {
    if (webContents && !webContents.isDestroyed()) webContents.send(channel, payload);
  }

  function broadcast() {
    send(getMainWindow()?.webContents, "pomodoro:state", state());
    updateMini();
  }

  /** Sounds play in Moah's window, hidden or not, so they use the person's volume and own files. */
  function cue(kind) {
    if (!settings.enabled || !settings.soundsOn) return;
    send(getMainWindow()?.webContents, "pomodoro:cue", kind);
  }

  // The corner window.

  /** The desktop timer shows the whole time the focus timer is turned on: stopped or running, Moah open or not. */
  function wantMini() {
    return settings.enabled && miniSupported;
  }

  /** The size picked in Settings: the window grows and its page is zoomed to match. */
  const miniScale = () => core.MINI_SCALES[settings.miniSize] ?? 1;

  /** Where the person last dragged it, kept on a monitor that is still there; otherwise the bottom-left corner above the taskbar. */
  function miniBounds() {
    const size = core.miniSize(miniScale());
    const placed = core.placeOnScreen(settings.miniPosition, size, screen.getAllDisplays().map((one) => one.bounds), Math.round(MINI_OVERHANG * miniScale()));
    if (placed) return { ...placed, ...size };
    const main = getMainWindow();
    const where = main && !main.isDestroyed() ? screen.getDisplayMatching(main.getNormalBounds()) : screen.getPrimaryDisplay();
    return { ...core.cornerPosition(where.workArea, size, MINI_MARGIN), ...size };
  }

  // Dragging the corner timer with the left mouse button. The page says when a drag starts, moves and
  // ends; the main process reads the pointer itself, so the page's zoom can't skew the numbers. This
  // works on Windows and on X11 (where Moah runs while the timer is on, also under Wayland).
  let drag = null;

  function dragStart() {
    if (!mini || mini.isDestroyed()) return;
    const [x, y] = mini.getPosition();
    drag = { pointer: screen.getCursorScreenPoint(), x, y };
  }

  function dragMove() {
    if (!drag || !mini || mini.isDestroyed()) return;
    const pointer = screen.getCursorScreenPoint();
    mini.setPosition(Math.round(drag.x + pointer.x - drag.pointer.x), Math.round(drag.y + pointer.y - drag.pointer.y));
  }

  function dragEnd() {
    if (!drag || !mini || mini.isDestroyed()) return;
    dragMove();
    drag = null;
    const [x, y] = mini.getPosition();
    const size = core.miniSize(miniScale());
    // Dropped half off the monitor: pulled back in, and that place is the one remembered. The whole
    // monitor counts, taskbar included; only the first, default place keeps clear of the taskbar.
    const placed = core.placeOnScreen({ x, y }, size, screen.getAllDisplays().map((one) => one.bounds), Math.round(MINI_OVERHANG * miniScale())) ?? miniBounds();
    if (placed.x !== x || placed.y !== y) mini.setPosition(placed.x, placed.y);
    settings = core.cleanSettings({ miniPosition: { x: placed.x, y: placed.y } }, settings);
    save();
  }

  function sizeMini() {
    if (drag) return; // Don't pull it back while it is being dragged.
    const bounds = miniBounds();
    const now = mini.getBounds();
    if (now.width !== bounds.width || now.height !== bounds.height || now.x !== bounds.x || now.y !== bounds.y) mini.setBounds(bounds);
    // Chromium stores zoom as a level, so the factor read back can be off in the last digit.
    if (Math.abs(mini.webContents.getZoomFactor() - miniScale()) > 0.001) mini.webContents.setZoomFactor(miniScale());
  }

  function miniState() {
    return { ...state(), labels: labels() };
  }

  function createMini() {
    mini = new BrowserWindow({
      ...miniBounds(),
      show: false,
      frame: false,
      transparent: true,
      backgroundColor: "#00000000",
      hasShadow: false,
      resizable: false,
      movable: true,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      skipTaskbar: true,
      alwaysOnTop: true,
      focusable: false,
      title: "Project Moah",
      webPreferences: {
        preload: path.join(__dirname, "mini", "preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        spellcheck: false,
        backgroundThrottling: false,
      },
    });
    mini.setVisibleOnAllWorkspaces(true);
    mini.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    mini.webContents.on("will-navigate", (event) => event.preventDefault());
    mini.webContents.on("did-finish-load", () => {
      miniReady = true;
      send(mini?.webContents, "pomodoro:state", miniState());
      updateMini();
    });
    mini.on("closed", () => {
      mini = null;
      miniReady = false;
    });
    void mini.loadFile(path.join(__dirname, "mini", "mini.html")).catch((error) => writeLog(`[timer] ${error.message}`));
  }

  function updateMini() {
    if (!wantMini()) {
      if (mini && !mini.isDestroyed() && mini.isVisible()) mini.hide();
      return;
    }
    if (!mini) {
      createMini();
      return; // It shows once its page has loaded.
    }
    if (!miniReady) return;
    send(mini.webContents, "pomodoro:state", miniState());
    sizeMini();
    if (!mini.isVisible()) {
      mini.setAlwaysOnTop(true, "screen-saver"); // Above the taskbar too, wherever it is dragged.
      mini.showInactive();
    }
  }

  // Custom sounds: a copy goes into Moah's own folder, so moving or deleting the original breaks nothing.

  function removeCopies(kind) {
    try {
      for (const name of readdirSync(soundsDir)) if (name.startsWith(`${kind}.`)) rmSync(path.join(soundsDir, name), { force: true });
    } catch {
      // No sounds folder yet.
    }
  }

  async function chooseSound(kind, text) {
    const window = getMainWindow();
    const result = await dialog.showOpenDialog(window, {
      title: typeof text?.title === "string" && text.title.length <= 200 ? text.title : "Choose a sound",
      properties: ["openFile"],
      filters: [{ name: typeof text?.filter === "string" && text.filter.length <= 100 ? text.filter : "Sounds", extensions: [...core.SOUND_EXTENSIONS] }],
    });
    if (result.canceled || result.filePaths.length === 0) return { state: state() };
    const source = result.filePaths[0];
    const extension = path.extname(source).slice(1).toLowerCase();
    if (!core.SOUND_EXTENSIONS.includes(extension)) return { state: state(), error: "type" };
    let size;
    try {
      size = statSync(source).size;
    } catch {
      return { state: state(), error: "read" };
    }
    if (size === 0) return { state: state(), error: "read" };
    if (size > core.MAX_SOUND_BYTES) return { state: state(), error: "size" };
    try {
      mkdirSync(soundsDir, { recursive: true });
      removeCopies(kind);
      copyFileSync(source, path.join(soundsDir, `${kind}.${extension}`));
    } catch (error) {
      writeLog(`[timer] couldn't copy a sound: ${error.message}`);
      return { state: state(), error: "read" };
    }
    settings = core.cleanSettings({ sounds: { ...settings.sounds, [kind]: { file: `${kind}.${extension}`, name: path.basename(source) } } }, settings);
    save();
    broadcast();
    return { state: state() };
  }

  function resetSound(kind) {
    removeCopies(kind);
    settings = core.cleanSettings({ sounds: { ...settings.sounds, [kind]: null } }, settings);
    save();
    broadcast();
    return state();
  }

  function soundData(kind) {
    const chosen = settings.sounds[kind];
    if (!chosen) return null;
    try {
      return readFileSync(path.join(soundsDir, chosen.file));
    } catch {
      return null;
    }
  }

  function update(partial) {
    const before = core.durations(settings);
    const wasEnabled = settings.enabled;
    // Sounds change only through choose and reset, which copy and delete the files.
    // The corner timer's place changes only by dragging it.
    const { sounds, miniPosition, ...rest } = partial && typeof partial === "object" ? partial : {};
    settings = core.cleanSettings(rest, settings);
    save();
    if (settings.enabled !== wasEnabled) syncX11Marker();
    if (!settings.enabled) timer.stop();
    const after = core.durations(settings);
    if (before.workMs !== after.workMs || before.breakMs !== after.breakMs) timer.planChanged();
    broadcast();
    return state();
  }

  function command(name) {
    if (!settings.enabled) return state();
    if (name === "start") timer.start();
    else if (name === "pause") timer.pause();
    else if (name === "skip") timer.skip();
    else if (name === "stop") timer.stop();
    return state();
  }

  // Only Moah's own window may change the settings and sounds.
  const fromMain = (event) => event.sender === getMainWindow()?.webContents;
  const isKind = (kind) => core.SOUND_KINDS.includes(kind);
  ipcMain.handle("pomodoro:get", (event) => (fromMain(event) ? state() : null));
  ipcMain.handle("pomodoro:update", (event, partial) => (fromMain(event) ? update(partial) : null));
  ipcMain.handle("pomodoro:command", (event, name) => (fromMain(event) ? command(name) : null));
  ipcMain.handle("pomodoro:choose-sound", (event, kind, text) => (fromMain(event) && isKind(kind) ? chooseSound(kind, text) : null));
  ipcMain.handle("pomodoro:reset-sound", (event, kind) => (fromMain(event) && isKind(kind) ? resetSound(kind) : null));
  ipcMain.handle("pomodoro:sound", (event, kind) => (fromMain(event) && isKind(kind) ? soundData(kind) : null));
  ipcMain.handle("pomodoro:quit", (event) => {
    if (fromMain(event)) app.quit();
  });
  // The corner window may open Moah, start or pause the timer, and be dragged; nothing else.
  const fromMini = (event) => Boolean(mini && !mini.isDestroyed() && event.sender === mini.webContents);
  ipcMain.on("pomodoro:open", (event) => {
    if (fromMini(event)) showMainWindow();
  });
  ipcMain.on("pomodoro:toggle", (event) => {
    if (!fromMini(event) || !settings.enabled) return;
    if (timer.snapshot().running) timer.pause();
    else timer.start();
  });
  ipcMain.on("pomodoro:drag", (event, step) => {
    if (!fromMini(event)) return;
    if (step === "start") dragStart();
    else if (step === "move") dragMove();
    else if (step === "end") dragEnd();
    else if (step === "cancel") drag = null;
  });

  // A marker left from an older run (or removed by hand) follows the saved setting.
  syncX11Marker();

  // Turned on from an earlier run: the desktop timer shows from the start.
  updateMini();

  return {
    /** Items waiting in Review from the main process's regular check; `fresh` are the new ones. */
    setPending(total, fresh) {
      reviews.update(total, settings.enabled ? fresh : []);
    },
    /** The computer woke up: catch up with the clock straight away. */
    wake() {
      timer.check();
    },
    dispose() {
      timer.dispose();
      if (mini && !mini.isDestroyed()) mini.destroy();
    },
  };
}

module.exports = { createPomodoro, relaunchForX11 };
