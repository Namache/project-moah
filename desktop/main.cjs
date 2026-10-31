"use strict";

const { app, BrowserWindow, Menu, Notification, Tray, dialog, ipcMain, nativeImage, screen, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const { createWriteStream, existsSync, mkdirSync, readFileSync, writeFileSync } = require("node:fs");
const { randomBytes } = require("node:crypto");
const { homedir } = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

// The app was renamed to Project Moah; keep its settings folder (window state, logs, saved
// layout) where Project Brain put it, so the rename doesn't reset anything.
// A missing AppData folder makes getPath throw, which would stop the app before it can say why.
function settingsParent() {
  try {
    return app.getPath("appData");
  } catch {
    return homedir();
  }
}
app.setPath("userData", path.join(settingsParent(), "Project Brain"));

// The window only ever talks to the local service. Without this, Chromium on Windows looks for
// a "wpad" proxy on the network as soon as it loads a page.
app.commandLine.appendSwitch("no-proxy-server");

const READY_PREFIX = "PROJECT_BRAIN_READY ";
const STARTUP_TIMEOUT_MS = 45_000;
let backend = null;
let window = null;
let tray = null;
let stopping = false;
let stopPromise = null;
let backendStoppedForQuit = false;
let quitting = false;
// An agent starting on Windows opens the app with --tray: running, with no window in the way.
const startInTray = process.argv.includes("--tray");
let maximizeOnShow = false;
let apiToken = "";
let logStream = null;
let logPath = "";
let fatalShown = false;

// The page is served by the local service and loads nothing from elsewhere: scripts, styles, icons and
// API calls all come from its own origin. React sets inline style properties, so inline styles stay allowed.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");
// Copy buttons use the clipboard; nothing else (camera, notifications, location and so on) is ever needed.
const ALLOWED_PERMISSIONS = new Set(["clipboard-sanitized-write"]);

/** How this copy was installed, so Help and setup commands match the person's system. */
function installKind() {
  if (process.platform === "win32") return "windows";
  if (process.platform === "darwin") return "mac";
  if (existsSync("/.flatpak-info")) return "flatpak";
  // The .deb installs under /opt and adds the agent launcher next to the app's own command.
  if (app.getAppPath().startsWith("/opt/") || existsSync("/usr/bin/project-moah-mcp")) return "deb";
  return "linux";
}

function backendExecutable() {
  const filename = process.platform === "win32" ? "project-brain-backend.exe" : "project-brain-backend";
  const base = app.isPackaged ? process.resourcesPath : __dirname;
  return path.join(base, "bin", filename);
}

function writeLog(line) {
  logStream?.write(`${new Date().toISOString()} ${line}\n`);
}

function originOf(url) {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

/** Error texts in the computer's language. The app's own language choice lives in the window, which may not exist yet. */
const RUSSIAN = {
  "Project Moah stopped": "Project Moah остановился",
  "Project Moah could not open": "Не удалось открыть Project Moah",
  "Its local service stopped unexpectedly. Restart Project Moah to continue.": "Его локальная служба неожиданно остановилась. Перезапустите Project Moah, чтобы продолжить.",
  "The local service stopped during startup ({reason}).": "Локальная служба остановилась при запуске ({reason}).",
  "Details were saved to {path}": "Подробности сохранены в {path}",
  "Open Project Moah": "Открыть Project Moah",
  "Quit": "Выйти",
  "A proposal needs your decision": "Предложение ждёт вашего решения",
  "{count} proposals need your decision": "Предложений, ждущих вашего решения: {count}",
  "{agent} in {project}: {summary}": "{agent} в «{project}»: {summary}",
  "Open the Inbox to accept or reject them.": "Откройте «Входящие», чтобы принять или отклонить их.",
};
function say(text, vars = {}) {
  const chosen = app.getLocale().toLowerCase().startsWith("ru") ? RUSSIAN[text] ?? text : text;
  return chosen.replace(/\{(\w+)\}/g, (whole, name) => (name in vars ? String(vars[name]) : whole));
}

/** Shows one error and quits. Later failures caused by the same problem are only logged. */
function fatal(title, message) {
  writeLog(`[fatal] ${title}: ${message}`);
  if (fatalShown) return;
  fatalShown = true;
  dialog.showErrorBox(title, message);
  app.quit();
}

function waitForExit(child, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      child.off("exit", onExit);
      resolve(false);
    }, timeoutMs);
    function onExit() {
      clearTimeout(timeout);
      resolve(true);
    }
    child.once("exit", onExit);
  });
}

function stopBackend() {
  stopping = true;
  if (stopPromise) return stopPromise;
  const child = backend;
  if (!child || child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  stopPromise = (async () => {
    // The sidecar watches stdin for EOF and shuts down its server gracefully.
    if (!child.stdin.destroyed) child.stdin.end();
    if (await waitForExit(child, 5_000)) return;
    writeLog("[service] graceful shutdown timed out; terminating process tree");
    if (process.platform === "win32") {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
      killer.on("error", (error) => writeLog(`[service] taskkill failed: ${error.message}`));
      await waitForExit(killer, 3_000);
    } else {
      child.kill("SIGTERM");
    }
    await waitForExit(child, 3_000);
  })();
  return stopPromise;
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const executable = backendExecutable();
    const child = spawn(executable, [], {
      cwd: path.dirname(executable),
      env: { ...process.env, PROJECT_BRAIN_DESKTOP_TOKEN: apiToken, PYTHONUNBUFFERED: "1" },
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    backend = child;
    child.stdin.on("error", (error) => writeLog(`[service stdin] ${error.message}`));
    let settled = false;
    let ready = false;
    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error("The local service did not start within 45 seconds."));
        void stopBackend();
      }
    }, STARTUP_TIMEOUT_MS);

    const lines = readline.createInterface({ input: child.stdout });
    lines.on("line", (line) => {
      if (line.startsWith(READY_PREFIX)) {
        const port = Number(line.slice(READY_PREFIX.length));
        if (!Number.isInteger(port) || port < 1 || port > 65535) {
          if (!settled) {
            settled = true;
            clearTimeout(timeout);
            reject(new Error("The local service reported an invalid port."));
            void stopBackend();
          }
          return;
        }
        ready = true;
        if (!settled) {
          settled = true;
          clearTimeout(timeout);
          resolve(port);
        }
      } else {
        writeLog(`[service] ${line}`);
      }
    });
    child.stderr.on("data", (chunk) => writeLog(`[service] ${String(chunk).trimEnd()}`));
    child.on("error", (error) => {
      writeLog(`[service error] ${error.message}`);
      if (!settled) {
        settled = true;
        clearTimeout(timeout);
        reject(error);
      }
    });
    child.on("exit", (code, signal) => {
      writeLog(`[service exit] code=${code} signal=${signal}`);
      if (!settled) {
        settled = true;
        clearTimeout(timeout);
        reject(new Error(`The local service exited before startup (${code ?? signal}).`));
      } else if (ready && !stopping) {
        if (window) fatal(say("Project Moah stopped"), say("Its local service stopped unexpectedly. Restart Project Moah to continue."));
        else fatal(say("Project Moah could not open"), `${say("The local service stopped during startup ({reason}).", { reason: code ?? signal })}\n\n${say("Details were saved to {path}", { path: logPath })}`);
      }
    });
  });
}

async function waitForHealth(port) {
  const url = `http://127.0.0.1:${port}/api/health`;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { "X-Project-Brain-Token": apiToken },
        signal: AbortSignal.timeout(1_000),
      });
      if (response.ok) return;
    } catch {
      // The service may still be finishing startup.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("The local service did not become ready.");
}

function windowStatePath() {
  return path.join(app.getPath("userData"), "window-state.json");
}

// The first launch opens maximised. Later launches restore the size, position and maximised state the person left,
// as long as the saved bounds still overlap a connected display. Wayland ignores the position; the size still applies.
function loadWindowState() {
  const work = screen.getPrimaryDisplay().workArea;
  const fallback = { width: Math.min(1440, work.width), height: Math.min(900, work.height), maximized: true };
  try {
    const saved = JSON.parse(readFileSync(windowStatePath(), "utf8"));
    const { x, y, width, height } = saved;
    if (![width, height].every(Number.isFinite)) return fallback;
    const state = { width: Math.max(800, width), height: Math.max(600, height), maximized: saved.maximized === true };
    if (Number.isFinite(x) && Number.isFinite(y)) {
      const visible = screen.getAllDisplays().some(({ workArea: a }) => x < a.x + a.width && x + state.width > a.x && y < a.y + a.height && y + state.height > a.y);
      if (visible) Object.assign(state, { x, y });
    }
    return state;
  } catch {
    return fallback;
  }
}

function saveWindowState() {
  if (!window || window.isDestroyed()) return;
  const bounds = window.getNormalBounds();
  try {
    writeFileSync(windowStatePath(), JSON.stringify({ ...bounds, maximized: maximizeOnShow || window.isMaximized() }));
  } catch (error) {
    writeLog(`[window state] ${error.message}`);
  }
}

function secureSession(origin) {
  const ses = session.defaultSession;
  const trusted = (webContents, requestingOrigin) => webContents === window?.webContents && requestingOrigin === origin;
  ses.setPermissionRequestHandler((webContents, permission, callback, details) => {
    callback(ALLOWED_PERMISSIONS.has(permission) && trusted(webContents, originOf(details.requestingUrl)));
  });
  ses.setPermissionCheckHandler((webContents, permission, requestingOrigin) => ALLOWED_PERMISSIONS.has(permission) && trusted(webContents, requestingOrigin));
  ses.webRequest.onHeadersReceived({ urls: [`${origin}/*`] }, (details, callback) => {
    const headers = { ...details.responseHeaders };
    for (const name of Object.keys(headers)) if (name.toLowerCase() === "content-security-policy") delete headers[name];
    callback({ responseHeaders: { ...headers, "Content-Security-Policy": [CONTENT_SECURITY_POLICY] } });
  });
}

async function openWindow(port) {
  const origin = `http://127.0.0.1:${port}`;
  secureSession(origin);
  const state = loadWindowState();
  window = new BrowserWindow({
    width: state.width,
    height: state.height,
    ...(state.x === undefined ? {} : { x: state.x, y: state.y }),
    minWidth: 800,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    title: "Project Moah",
    icon: path.join(__dirname, "assets", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: process.platform !== "linux",
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  const stayInApp = (event, url) => {
    if (originOf(url) !== origin) event.preventDefault();
  };
  window.webContents.on("will-navigate", stayInApp);
  window.webContents.on("will-redirect", stayInApp);
  window.once("ready-to-show", () => {
    if (startInTray) {
      maximizeOnShow = state.maximized;
      return;
    }
    if (state.maximized) window?.maximize();
    window?.show();
  });
  // On Windows the X button hides the window to the tray and the app keeps running; Quit in the
  // tray menu ends it. Without a tray icon there would be no way back, so it closes as usual.
  window.on("close", (event) => {
    saveWindowState();
    if (process.platform !== "win32" || quitting || !tray) return;
    event.preventDefault();
    window.hide();
  });
  // Windows is shutting down or signing out: a hidden window must not hold that up.
  window.on("session-end", () => {
    quitting = true;
  });
  await window.loadURL(origin);
}

function showWindow() {
  if (!window) return;
  if (window.isMinimized()) window.restore();
  if (maximizeOnShow) window.maximize();
  maximizeOnShow = false;
  window.show();
  window.focus();
}

/** An icon in the system tray (notification area) for every build, so a minimised window is easy to find. */
function createTray() {
  if (tray) return;
  // Windows draws its tray from a multi-size .ico; Linux trays want a small picture.
  const image = process.platform === "win32"
    ? nativeImage.createFromPath(path.join(__dirname, "assets", "icon.ico"))
    : nativeImage.createFromPath(path.join(__dirname, "assets", "icon.png")).resize({ width: 22, height: 22 });
  try {
    tray = new Tray(image);
  } catch (error) {
    // A Linux desktop without a tray (plain GNOME) still has the taskbar; never fail to start over it.
    writeLog(`[tray] ${error.message}`);
    showWindow();
    return;
  }
  tray.setToolTip("Project Moah");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: say("Open Project Moah"), click: showWindow },
    { type: "separator" },
    { label: say("Quit"), click: () => app.quit() },
  ]));
  tray.on("click", showWindow);
  // For scripts/check-desktop-window.cjs, which checks every build has its tray icon.
  global.projectMoahTray = !image.isEmpty();
}

const PROPOSAL_CHECK_MS = 15_000;
// Pending proposals already notified about (or waiting when the app opened and summed up once).
let notifiedProposals = null;

function openReview() {
  showWindow();
  // The page is a single-page app: change its route without reloading what the person had open.
  void window?.webContents.executeJavaScript(
    'history.pushState({}, "", "/review"); dispatchEvent(new PopStateEvent("popstate"));',
  ).catch((error) => writeLog(`[review] ${error.message}`));
}

function notify(title, body) {
  const note = new Notification({ title, body, icon: path.join(__dirname, "assets", "icon.png") });
  note.on("click", openReview);
  note.show();
}

/** OS notifications (like an agent asking for permission) when proposals wait for a person's decision. */
async function checkProposals(port) {
  let pending;
  try {
    const response = await fetch(`http://127.0.0.1:${port}/api/proposals/pending`, {
      headers: { "X-Project-Brain-Token": apiToken },
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) return;
    pending = await response.json();
  } catch {
    return; // The service is busy or stopping; the next check tries again.
  }
  const newest = pending.newest ?? [];
  const first = notifiedProposals === null;
  const fresh = first ? [] : newest.filter((proposal) => !notifiedProposals.has(proposal.id));
  notifiedProposals = new Set(newest.map((proposal) => proposal.id));
  if (!Notification.isSupported()) return;
  if (first && pending.total > 0) {
    notify(
      pending.total === 1 ? say("A proposal needs your decision") : say("{count} proposals need your decision", { count: pending.total }),
      say("Open the Inbox to accept or reject them."),
    );
  } else if (fresh.length === 1) {
    const [proposal] = fresh;
    notify(say("A proposal needs your decision"), say("{agent} in {project}: {summary}", { agent: proposal.agent, project: proposal.project_name, summary: proposal.summary }));
  } else if (fresh.length > 1) {
    notify(say("{count} proposals need your decision", { count: fresh.length }), say("Open the Inbox to accept or reject them."));
  }
}

function watchProposals(port) {
  void checkProposals(port);
  setInterval(() => void checkProposals(port), PROPOSAL_CHECK_MS).unref();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", (event, argv) => {
    // Another agent starting must not pull the window up; the person opening the app must.
    if (!argv.includes("--tray")) showWindow();
  });
  app.on("before-quit", (event) => {
    quitting = true;
    if (backendStoppedForQuit) return;
    event.preventDefault();
    void stopBackend().finally(() => {
      backendStoppedForQuit = true;
      app.quit();
    });
  });
  app.on("window-all-closed", () => app.quit());
  // Windows shows notifications only for the app ID its Start menu shortcut carries.
  if (process.platform === "win32") app.setAppUserModelId("io.github.projectbrain.ProjectBrain");
  app.whenReady().then(async () => {
    // On Linux, Chromium downloads spelling dictionaries from Google as soon as it starts. The app
    // never goes online, so spell checking is off there; Windows and macOS use the system's checker.
    if (process.platform === "linux") {
      session.defaultSession.setSpellCheckerEnabled(false);
      session.defaultSession.setSpellCheckerLanguages([]);
    }
    const logDir = app.getPath("userData");
    mkdirSync(logDir, { recursive: true });
    logPath = path.join(logDir, "desktop.log");
    logStream = createWriteStream(logPath, { flags: "a" });
    apiToken = randomBytes(32).toString("hex");
    ipcMain.on("project-brain:get-token", (event) => {
      event.returnValue = event.sender === window?.webContents ? apiToken : "";
    });
    const install = installKind();
    ipcMain.on("project-brain:get-install", (event) => {
      event.returnValue = install;
    });
    // "Work on task": open an agent's desktop app with a prompt typed in. Only the two agents'
    // own link schemes are allowed, so the page cannot use this to open anything else.
    ipcMain.handle("project-brain:open-agent", async (event, url) => {
      if (event.sender !== window?.webContents || typeof url !== "string" || url.length > 20_000) return false;
      let scheme;
      try { scheme = new URL(url).protocol; } catch { return false; }
      if (scheme !== "claude:" && scheme !== "codex:") return false;
      try {
        await shell.openExternal(url);
        return true;
      } catch (error) {
        writeLog(`[open agent] ${error.message}`);
        return false;
      }
    });
    ipcMain.handle("project-brain:choose-folder", async (event, title) => {
      // Only the app's own window may open the chooser.
      if (event.sender !== window?.webContents) return null;
      const heading = typeof title === "string" && title.length > 0 && title.length <= 200 ? title : "Choose the project's repository folder";
      const result = await dialog.showOpenDialog(window, { title: heading, properties: ["openDirectory"] });
      return result.canceled || result.filePaths.length === 0 ? null : result.filePaths[0];
    });
    try {
      const port = await startBackend();
      await waitForHealth(port);
      await openWindow(port);
      createTray();
      watchProposals(port);
    } catch (error) {
      writeLog(`[startup error] ${error.stack ?? error.message}`);
      fatal(say("Project Moah could not open"), `${error.message}\n\n${say("Details were saved to {path}", { path: logPath })}`);
    }
  });
}
