"use strict";

const assert = require("node:assert/strict");
const { mkdtempSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const test = require("node:test");
const display = require("./display.cjs");

const screenOf = (width, height) => ({ size: { width, height } });

test("Automatic leaves scaled and small screens at 100% and enlarges dense ones", () => {
  assert.equal(display.autoZoom(screenOf(1366, 768)), 1); // small laptop
  assert.equal(display.autoZoom(screenOf(1280, 720)), 1); // 1080p laptop at 150% system scaling
  assert.equal(display.autoZoom(screenOf(1920, 1080)), 1.1);
  assert.equal(display.autoZoom(screenOf(2560, 1440)), 1.25);
  assert.equal(display.autoZoom(screenOf(3440, 1440)), 1.25); // ultrawide: the height decides
  assert.equal(display.autoZoom(screenOf(3840, 2160)), 1.5); // 4K at 100% system scaling
  assert.equal(display.autoZoom(screenOf(1080, 1920)), 1.1); // portrait
  assert.equal(display.autoZoom(screenOf(5120, 2880)), 1.75);
  assert.equal(display.autoZoom(undefined), 1);
});

test("saved choices are checked, and anything unknown falls back to Automatic and standard text", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "moah-display-"));
  const file = path.join(dir, "display.json");
  assert.deepEqual(display.readPrefs(file), { zoom: "auto", text: 1 });
  display.writePrefs(file, { zoom: 1.5, text: 1.3 });
  assert.deepEqual(display.readPrefs(file), { zoom: 1.5, text: 1.3 });
  writeFileSync(file, JSON.stringify({ zoom: 9, text: "huge" }));
  assert.deepEqual(display.readPrefs(file), { zoom: "auto", text: 1 });
  writeFileSync(file, "not json");
  assert.deepEqual(display.readPrefs(file), { zoom: "auto", text: 1 });
});

test("Ctrl+Plus and Ctrl+Minus step from the size in use, and Ctrl+0 resets to Automatic", () => {
  const big = screenOf(2560, 1440);
  assert.deepEqual(display.stepZoom({ zoom: "auto", text: 1 }, big, 1), { zoom: 1.5, text: 1 });
  assert.deepEqual(display.stepZoom({ zoom: "auto", text: 1 }, big, -1), { zoom: 1.1, text: 1 });
  assert.deepEqual(display.stepZoom({ zoom: 2, text: 1.15 }, big, 1), { zoom: 2, text: 1.15 });
  assert.deepEqual(display.stepZoom({ zoom: 0.9, text: 1 }, big, -1), { zoom: 0.9, text: 1 });
  assert.deepEqual(display.stepZoom({ zoom: 1.75, text: 1 }, big, 0), { zoom: "auto", text: 1 });
});

test("only Ctrl or Cmd with plus, minus or zero counts as a zoom shortcut", () => {
  const key = (k, extra = {}) => ({ type: "keyDown", key: k, code: "", control: true, meta: false, alt: false, ...extra });
  assert.equal(display.zoomShortcut(key("=")), 1);
  assert.equal(display.zoomShortcut(key("+", { shift: true })), 1);
  assert.equal(display.zoomShortcut(key("-")), -1);
  assert.equal(display.zoomShortcut(key("0")), 0);
  assert.equal(display.zoomShortcut(key("", { code: "NumpadAdd" })), 1);
  assert.equal(display.zoomShortcut(key("0", { control: false, meta: true })), 0);
  assert.equal(display.zoomShortcut(key("=", { control: false })), null);
  assert.equal(display.zoomShortcut(key("=", { alt: true })), null);
  assert.equal(display.zoomShortcut(key("=", { type: "keyUp" })), null);
  assert.equal(display.zoomShortcut(key("k")), null);
});
