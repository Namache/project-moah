"use strict";

const assert = require("node:assert/strict");
const { mkdtempSync, readFileSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { readServicePort, saveServicePort } = require("./serviceport.cjs");

test("the service port is remembered for the next start", () => {
  const file = path.join(mkdtempSync(path.join(tmpdir(), "moah-port-")), "service-port.json");
  assert.equal(readServicePort(file), null); // first start: any free port
  assert.equal(saveServicePort(file, 51234), true);
  assert.equal(readServicePort(file), 51234);
  assert.deepEqual(JSON.parse(readFileSync(file, "utf8")), { port: 51234 });
  assert.equal(saveServicePort(file, 52000), true);
  assert.equal(readServicePort(file), 52000);
});

test("a damaged or odd file is ignored, and nothing odd is saved", () => {
  const file = path.join(mkdtempSync(path.join(tmpdir(), "moah-port-")), "service-port.json");
  for (const content of ["not json", "{}", '{"port": 80}', '{"port": 70000}', '{"port": "51234"}', "null"]) {
    writeFileSync(file, content);
    assert.equal(readServicePort(file), null, content);
  }
  assert.equal(saveServicePort(file, 0), false);
  assert.equal(saveServicePort(path.join(file, "missing-folder", "x.json"), 51234), false);
});
