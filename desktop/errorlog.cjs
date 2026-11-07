"use strict";

// The desktop app's part of the local error log (see backend/app/core/error_log.py): one JSON line
// per error in its settings folder, moved to "<file>.1" past MAX_BYTES so it stays small. The local
// service reads this file for Settings > Diagnostics. Nothing is sent anywhere.

const { appendFileSync, renameSync, statSync } = require("node:fs");
const { homedir } = require("node:os");

const MAX_BYTES = 256 * 1024;
const MAX_MESSAGE = 2_000;
const MAX_DETAIL = 12_000;

function clean(text, limit, home = homedir()) {
  let value = String(text ?? "").trim();
  if (home && home.length > 1) value = value.split(home).join("~");
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}

/** Returns record(message, detail?, level?), which never throws. */
function createErrorLog(file, { maxBytes = MAX_BYTES, home = homedir(), now = () => new Date() } = {}) {
  return function record(message, detail = "", level = "error") {
    try {
      const line = `${JSON.stringify({
        time: now().toISOString().replace(/\.\d{3}Z$/, "+00:00"),
        source: "desktop",
        level: level === "warning" ? "warning" : "error",
        message: clean(message, MAX_MESSAGE, home) || "Unknown error",
        detail: clean(detail, MAX_DETAIL, home),
      })}\n`;
      try {
        if (statSync(file).size + Buffer.byteLength(line) > maxBytes) renameSync(file, `${file}.1`);
      } catch {
        // No file yet.
      }
      appendFileSync(file, line, "utf8");
    } catch {
      // A broken log must never break the app.
    }
  };
}

module.exports = { createErrorLog, clean, MAX_BYTES };
