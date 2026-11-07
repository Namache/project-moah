"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { mkdtempSync, readFileSync, existsSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { createErrorLog } = require("./errorlog.cjs");

const folder = () => mkdtempSync(path.join(tmpdir(), "moah-errors-"));

test("writes one JSON line per error, with the home folder shortened", () => {
  const file = path.join(folder(), "errors-desktop.log");
  const record = createErrorLog(file, { home: "/home/someone", now: () => new Date("2026-11-07T04:00:00.123Z") });
  record("Could not read /home/someone/notes.txt", "Error: at /home/someone/app.js:1");
  record("Agent app missing", "", "warning");
  const lines = readFileSync(file, "utf8").trim().split("\n").map((line) => JSON.parse(line));
  assert.equal(lines.length, 2);
  assert.deepEqual(lines[0], { time: "2026-11-07T04:00:00+00:00", source: "desktop", level: "error", message: "Could not read ~/notes.txt", detail: "Error: at ~/app.js:1" });
  assert.equal(lines[1].level, "warning");
});

test("moves a full file aside instead of growing without end", () => {
  const file = path.join(folder(), "errors-desktop.log");
  const record = createErrorLog(file, { maxBytes: 400 });
  for (let i = 0; i < 10; i += 1) record(`error number ${i}`, "x".repeat(50));
  assert.ok(existsSync(`${file}.1`));
  assert.ok(readFileSync(file, "utf8").length <= 400);
  assert.match(readFileSync(file, "utf8"), /error number 9/);
});

test("never throws, even when the folder is gone", () => {
  const record = createErrorLog(path.join(folder(), "missing", "deeper", "errors.log"));
  assert.doesNotThrow(() => record("still fine"));
});
