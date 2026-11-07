"use strict";

// The local service's port is remembered between starts. The window's page storage (theme,
// language, folded sections, the chosen microphone and other small choices) belongs to its
// address, port included, so a new port on every start would forget all of them.

const { readFileSync, writeFileSync } = require("node:fs");

const valid = (port) => Number.isInteger(port) && port >= 1024 && port <= 65535;

/** The port the last run used, or null when there is none or the file is damaged. */
function readServicePort(file) {
  try {
    const port = JSON.parse(readFileSync(file, "utf8"))?.port;
    return valid(port) ? port : null;
  } catch {
    return null;
  }
}

/** Remembers the port for the next start. Returns false when it could not be saved. */
function saveServicePort(file, port) {
  if (!valid(port)) return false;
  if (readServicePort(file) === port) return true;
  try {
    writeFileSync(file, JSON.stringify({ port }));
    return true;
  } catch {
    return false;
  }
}

module.exports = { readServicePort, saveServicePort };
