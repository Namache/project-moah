// Opens an installed Project Moah, checks its window, that its Help shows this system's setup
// commands, and that it never reaches past this computer, and saves screenshots. Uses a
// throwaway home folder, never real data.
//
// Usage: node scripts/check-desktop-window.cjs APP_EXECUTABLE EXPECTED_INSTALL SCREENSHOT_DIR
// Needs the playwright package (only its Electron driver; no browsers are downloaded).
const { _electron } = require("playwright");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

async function main([executable, expected, out]) {
  if (!executable || !expected || !out) throw new Error("Usage: check-desktop-window.cjs APP_EXECUTABLE EXPECTED_INSTALL SCREENSHOT_DIR");
  fs.mkdirSync(out, { recursive: true });
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "moah-check-"));
  const env = { ...process.env, HOME: home, USERPROFILE: home, LOCALAPPDATA: path.join(home, "AppData", "Local"), APPDATA: path.join(home, "AppData", "Roaming"), XDG_DATA_HOME: path.join(home, ".local", "share"), XDG_CONFIG_HOME: path.join(home, ".config") };
  const netLog = path.join(out, "net-log.json");
  // Chromium refuses to run as root with its sandbox on; CI runners and containers sometimes are root.
  const args = [`--log-net-log=${netLog}`, ...(process.getuid?.() === 0 ? ["--no-sandbox"] : [])];
  const app = await _electron.launch({ executablePath: executable, args, env, timeout: 90_000 });
  try {
    const win = await app.firstWindow({ timeout: 90_000 });
    await win.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 60_000 });
    const title = await win.title();
    const install = await win.evaluate(() => window.projectBrainDesktop?.install);
    console.log(`Window: "${title}", install: ${install}`);
    if (title !== "Project Moah") throw new Error(`Unexpected window title: ${title}`);
    if (install !== expected) throw new Error(`The app thinks it is a ${install} install, expected ${expected}`);
    await win.screenshot({ path: path.join(out, "home.png") });
    // Typing is what wakes a spell checker, the usual culprit for a surprise download.
    await win.getByRole("button", { name: "Search or jump to…" }).click();
    await win.keyboard.type("helo wrold speling", { delay: 20 });
    await win.keyboard.press("Escape");

    await win.evaluate(() => { history.pushState({}, "", "/help/claude"); dispatchEvent(new PopStateEvent("popstate")); });
    const first = win.locator("pre").first();
    await first.waitFor({ timeout: 30_000 });
    const command = (await first.innerText()).trim();
    console.log(`Connect command: ${command}`);
    if (expected !== "flatpak" && /flatpak/i.test(command)) throw new Error("A non-Flatpak install shows a Flatpak command");
    const page = await win.locator("main").innerText();
    if (expected !== "flatpak" && /flatpak|bazzite|distrobox/i.test(page)) throw new Error("Help mentions Flatpak on a non-Flatpak install");
    await win.screenshot({ path: path.join(out, "help-claude.png"), fullPage: true });
  } finally {
    await app.close();
    fs.rmSync(home, { recursive: true, force: true, maxRetries: 5 });
  }
  checkStaysLocal(netLog);
}

/** Every address in Chromium's network log must be this computer. */
function checkStaysLocal(netLog) {
  const seen = new Set();
  for (const event of JSON.parse(fs.readFileSync(netLog, "utf8")).events ?? []) {
    for (const key of ["url", "host", "hostname", "origin"]) {
      const value = event.params?.[key];
      if (typeof value === "string" && !/^(data|blob|file|devtools|chrome|about):/.test(value)) seen.add(value);
    }
  }
  const local = /(^|\/\/|\[)(127\.0\.0\.1|localhost|::1)([:\]/]|$)/;
  const outside = [...seen].filter((value) => !local.test(value));
  console.log(`Network: ${seen.size - outside.length} local addresses, ${outside.length} outside`);
  if (seen.size === outside.length) throw new Error("The network log saw no local traffic, so it cannot be trusted");
  if (outside.length) throw new Error(`The app reached outside this computer: ${outside.join(", ")}`);
}

main(process.argv.slice(2)).catch((error) => {
  console.error(error);
  process.exit(1);
});
