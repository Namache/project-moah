"use strict";

// The window's small choices (theme, language, folded sections, panel widths, the chosen
// microphone) are kept in the settings folder too, not only in the page's storage. The page's
// storage belongs to the window's address, port included, so it starts empty whenever the last
// run's port is taken; this file does not.

const { readFileSync, writeFileSync } = require("node:fs");

const MAX_KEY = 100;
const MAX_VALUE = 10_000;
const MAX_KEYS = 200;

const validKey = (key) => typeof key === "string" && key.length > 0 && key.length <= MAX_KEY;
const validValue = (value) => value === null || (typeof value === "string" && value.length <= MAX_VALUE);

/** The saved choices, or none when there is no file or it is damaged. Odd entries are dropped. */
function readChoices(file) {
  try {
    const saved = JSON.parse(readFileSync(file, "utf8"));
    if (typeof saved !== "object" || saved === null || Array.isArray(saved)) return {};
    const choices = {};
    for (const [key, value] of Object.entries(saved).slice(0, MAX_KEYS)) {
      if (validKey(key) && typeof value === "string" && value.length <= MAX_VALUE) choices[key] = value;
    }
    return choices;
  } catch {
    return {};
  }
}

/**
 * Keeps the choices in memory and writes them a moment after the last change, so dragging a
 * divider doesn't write the file on every step. flush() writes at once (before quitting).
 */
function createChoices(file, { delayMs = 300, onError = () => {} } = {}) {
  const choices = readChoices(file);
  let timer = null;
  const flush = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    try {
      writeFileSync(file, JSON.stringify(choices));
    } catch (error) {
      onError(error);
    }
  };
  return {
    all: () => ({ ...choices }),
    /** Saves one choice (null forgets it). Returns false for a key or value it won't keep. */
    set(key, value) {
      if (!validKey(key) || !validValue(value)) return false;
      if (value === null) {
        if (!(key in choices)) return true;
        delete choices[key];
      } else {
        if (choices[key] === value) return true;
        if (!(key in choices) && Object.keys(choices).length >= MAX_KEYS) return false;
        choices[key] = value;
      }
      if (timer) clearTimeout(timer);
      timer = setTimeout(flush, delayMs);
      timer.unref?.();
      return true;
    },
    flush: () => {
      if (timer) flush();
    },
  };
}

module.exports = { readChoices, createChoices };
