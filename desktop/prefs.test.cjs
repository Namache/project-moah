"use strict";

const assert = require("node:assert/strict");
const { mkdtempSync, readFileSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { createChoices, readChoices } = require("./prefs.cjs");

const tempFile = () => path.join(mkdtempSync(path.join(tmpdir(), "moah-prefs-")), "window-prefs.json");

test("choices outlive the app: a new start reads what the last one saved", () => {
  const file = tempFile();
  const first = createChoices(file);
  assert.deepEqual(first.all(), {});
  assert.equal(first.set("pb-theme", "dark"), true);
  assert.equal(first.set("pb-language", "ru"), true);
  first.flush();
  assert.deepEqual(createChoices(file).all(), { "pb-theme": "dark", "pb-language": "ru" });
  const second = createChoices(file);
  assert.equal(second.set("pb-theme", null), true);
  second.flush();
  assert.deepEqual(readChoices(file), { "pb-language": "ru" });
});

test("a damaged file or odd entries are ignored, and odd choices are not kept", () => {
  const file = tempFile();
  for (const content of ["not json", "null", "[1,2]", '"text"']) {
    writeFileSync(file, content);
    assert.deepEqual(readChoices(file), {}, content);
  }
  writeFileSync(file, JSON.stringify({ good: "yes", number: 5, "": "empty key", long: "x".repeat(10_001) }));
  assert.deepEqual(readChoices(file), { good: "yes" });
  const choices = createChoices(file);
  assert.equal(choices.set("", "x"), false);
  assert.equal(choices.set("k", 5), false);
  assert.equal(choices.set("k", "x".repeat(10_001)), false);
});

test("a folder that can't be written reports the error instead of throwing", () => {
  const errors = [];
  const choices = createChoices(path.join(tempFile(), "missing", "x.json"), { onError: (error) => errors.push(error) });
  choices.set("pb-theme", "dark");
  choices.flush();
  assert.equal(errors.length, 1);
});

test("writes wait for the last change, so a drag writes once", async () => {
  const file = tempFile();
  const choices = createChoices(file, { delayMs: 20 });
  for (let width = 200; width < 260; width += 10) choices.set("pb-sidebar-width", String(width));
  assert.throws(() => readFileSync(file, "utf8")); // nothing written yet
  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.deepEqual(readChoices(file), { "pb-sidebar-width": "250" });
});
