"use strict";

// Interface and text size (Settings > Accessibility). The choice is saved in the settings folder,
// not in the page's storage: it must apply before the page loads, and the window's address can
// still change when the last run's port is taken.

const { readFileSync, writeFileSync } = require("node:fs");

// Interface size zooms the whole window, sidebar and panels included. Text size scales only the text.
const ZOOM_STEPS = [0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];
const TEXT_STEPS = [1, 1.15, 1.3, 1.5];
const DEFAULTS = Object.freeze({ zoom: "auto", text: 1 });

/**
 * A starting interface size for a display, from its usable height in logical pixels (the height
 * after the system's own scaling). Many logical pixels on one screen mean small text: a 1440p
 * or 4K screen at 100% system scaling packs the app into a small corner of the eye. Screens the
 * system already scales up (most laptops) come out at 100%.
 */
function autoZoom(display) {
  const height = Math.min(display?.size?.width ?? 0, display?.size?.height ?? 0);
  if (!Number.isFinite(height) || height < 1000) return 1;
  if (height < 1300) return 1.1;
  if (height < 1800) return 1.25;
  if (height < 2400) return 1.5;
  return 1.75;
}

function cleanPrefs(value) {
  const zoom = value?.zoom === "auto" || ZOOM_STEPS.includes(value?.zoom) ? value.zoom : DEFAULTS.zoom;
  const text = TEXT_STEPS.includes(value?.text) ? value.text : DEFAULTS.text;
  return { zoom, text };
}

function readPrefs(file) {
  try {
    return cleanPrefs(JSON.parse(readFileSync(file, "utf8")));
  } catch {
    return { ...DEFAULTS };
  }
}

function writePrefs(file, prefs) {
  writeFileSync(file, JSON.stringify(cleanPrefs(prefs)));
}

function zoomFor(prefs, display) {
  return prefs.zoom === "auto" ? autoZoom(display) : prefs.zoom;
}

/** Ctrl+Plus and Ctrl+Minus move one step from the size in use; Ctrl+0 goes back to Automatic. */
function stepZoom(prefs, display, direction) {
  if (direction === 0) return { ...prefs, zoom: "auto" };
  const current = zoomFor(prefs, display);
  const index = ZOOM_STEPS.findIndex((step) => step >= current - 0.001);
  const from = index === -1 ? ZOOM_STEPS.length - 1 : index;
  const next = ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, from + direction))];
  return { ...prefs, zoom: next };
}

/** Which zoom shortcut a key press is, if any: 1 bigger, -1 smaller, 0 reset. */
function zoomShortcut(input) {
  if (input.type !== "keyDown" || !(input.control || input.meta) || input.alt) return null;
  if (input.key === "+" || input.key === "=" || input.code === "NumpadAdd") return 1;
  if (input.key === "-" || input.key === "_" || input.code === "NumpadSubtract") return -1;
  if (input.key === "0" || input.code === "Numpad0") return 0;
  return null;
}

module.exports = { ZOOM_STEPS, TEXT_STEPS, DEFAULTS, autoZoom, cleanPrefs, readPrefs, writePrefs, zoomFor, stepZoom, zoomShortcut };
