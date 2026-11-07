"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const { DEFAULT_SETTINGS, cleanSettings, cornerPosition, createReviewWatch, createTimer, durations, linuxDisplay, miniSize } = require("./pomodoro-core.cjs");

const MIN = 60_000;

/** A timer on a fake clock: `advance(ms)` moves time on and runs the timer's checks. */
function harness(settings = { ...DEFAULT_SETTINGS }) {
  let clock = 1_000_000;
  let check = null;
  const cues = [];
  const changes = [];
  const state = { settings };
  const timer = createTimer({
    plan: () => durations(state.settings),
    now: () => clock,
    setInterval: (fn) => {
      check = fn;
      return { id: 1 };
    },
    clearInterval: () => {
      check = null;
    },
    onCue: (kind) => cues.push(kind),
    onChange: (snap) => changes.push(snap),
  });
  return {
    timer,
    cues,
    changes,
    state,
    get ticking() {
      return check !== null;
    },
    advance(ms) {
      clock += ms;
      check?.();
    },
  };
}

test("starts idle with the focus length of the chosen rhythm", () => {
  const h = harness({ ...DEFAULT_SETTINGS, preset: "40-10" });
  assert.deepEqual(h.timer.snapshot(), { phase: "idle", running: false, endsAt: null, remainingMs: 40 * MIN, totalMs: 40 * MIN });
  assert.equal(h.ticking, false);
});

test("goes round by itself: focus, break with the chime, focus with the back-to-work sound", () => {
  const h = harness();
  h.timer.start();
  assert.equal(h.timer.snapshot().phase, "focus");
  h.advance(25 * MIN - 1);
  assert.deepEqual(h.cues, []);
  h.advance(1);
  assert.equal(h.timer.snapshot().phase, "break");
  assert.equal(h.timer.snapshot().remainingMs, 5 * MIN);
  assert.deepEqual(h.cues, ["break"]);
  h.advance(5 * MIN);
  assert.equal(h.timer.snapshot().phase, "focus");
  assert.deepEqual(h.cues, ["break", "work"]);
});

test("pause keeps the time left, and resume carries on from it", () => {
  const h = harness();
  h.timer.start();
  h.advance(10 * MIN);
  h.timer.pause();
  assert.equal(h.ticking, false);
  assert.deepEqual({ ...h.timer.snapshot(), endsAt: null }, { phase: "focus", running: false, endsAt: null, remainingMs: 15 * MIN, totalMs: 25 * MIN });
  h.advance(60 * MIN);
  assert.equal(h.timer.snapshot().remainingMs, 15 * MIN);
  h.timer.start();
  h.advance(15 * MIN);
  assert.equal(h.timer.snapshot().phase, "break");
});

test("skip moves to the next phase without a sound and keeps a paused timer paused", () => {
  const h = harness();
  h.timer.start();
  h.timer.skip();
  assert.equal(h.timer.snapshot().phase, "break");
  assert.equal(h.timer.snapshot().running, true);
  h.timer.pause();
  h.timer.skip();
  assert.deepEqual({ phase: h.timer.snapshot().phase, running: h.timer.snapshot().running, left: h.timer.snapshot().remainingMs }, { phase: "focus", running: false, left: 25 * MIN });
  assert.deepEqual(h.cues, []);
});

test("skip and pause do nothing while stopped", () => {
  const h = harness();
  h.timer.skip();
  h.timer.pause();
  assert.equal(h.changes.length, 0);
});

test("stop goes back to the start", () => {
  const h = harness();
  h.timer.start();
  h.advance(30 * MIN);
  h.timer.stop();
  assert.deepEqual(h.timer.snapshot(), { phase: "idle", running: false, endsAt: null, remainingMs: 25 * MIN, totalMs: 25 * MIN });
  assert.equal(h.ticking, false);
});

test("a changed rhythm shows at once when stopped, and from the next phase when running", () => {
  const h = harness();
  h.state.settings = { ...DEFAULT_SETTINGS, preset: "50-10" };
  h.timer.planChanged();
  assert.equal(h.timer.snapshot().remainingMs, 50 * MIN);
  h.timer.start();
  h.state.settings = { ...DEFAULT_SETTINGS, preset: "custom", customWork: 20, customBreak: 3 };
  h.timer.planChanged();
  assert.equal(h.timer.snapshot().totalMs, 50 * MIN);
  h.advance(50 * MIN);
  assert.equal(h.timer.snapshot().totalMs, 3 * MIN);
});

test("after the computer sleeps past the end, the next phase starts from waking, once", () => {
  const h = harness();
  h.timer.start();
  h.advance(3 * 60 * MIN);
  assert.equal(h.timer.snapshot().phase, "break");
  assert.equal(h.timer.snapshot().remainingMs, 5 * MIN);
  assert.deepEqual(h.cues, ["break"]);
});

test("settings from disk are cleaned", () => {
  const cleaned = cleanSettings({ enabled: "yes", preset: "99-1", customWork: 999, customBreak: -4, volume: 140, soundsOn: false, miniSize: "huge", sounds: { break: { file: "../../etc/passwd", name: "x" }, work: { file: "work.ogg", name: "Bell.ogg" }, review: { file: "break.ogg", name: "y" } } });
  assert.deepEqual(cleaned, {
    enabled: false,
    preset: "25-5",
    customWork: 180,
    customBreak: 1,
    soundsOn: false,
    volume: 100,
    miniSize: "small",
    sounds: { break: null, work: { file: "work.ogg", name: "Bell.ogg" }, review: null },
  });
  assert.deepEqual(cleanSettings(null), { ...DEFAULT_SETTINGS, sounds: { break: null, work: null, review: null } });
});

test("a partial change keeps the rest of the saved settings", () => {
  const saved = cleanSettings({ enabled: true, preset: "custom", customWork: 45, sounds: { review: { file: "review.mp3", name: "ping.mp3" } } });
  const next = cleanSettings({ volume: 30 }, saved);
  assert.equal(next.enabled, true);
  assert.equal(next.customWork, 45);
  assert.equal(next.volume, 30);
  assert.deepEqual(next.sounds.review, { file: "review.mp3", name: "ping.mp3" });
});

test("the corner timer comes in three sizes, small by default", () => {
  assert.equal(cleanSettings(null).miniSize, "small");
  assert.equal(cleanSettings({ miniSize: "large" }).miniSize, "large");
  assert.equal(cleanSettings({ volume: 20 }, cleanSettings({ miniSize: "medium" })).miniSize, "medium");
  assert.deepEqual(miniSize(1), { width: 136, height: 64 });
  assert.deepEqual(miniSize(1.35), { width: 184, height: 86 });
  assert.deepEqual(miniSize(1.75), { width: 238, height: 112 });
});

test("custom durations are used for the custom rhythm only", () => {
  assert.deepEqual(durations({ ...DEFAULT_SETTINGS, preset: "custom", customWork: 33, customBreak: 7 }), { workMs: 33 * MIN, breakMs: 7 * MIN });
  assert.deepEqual(durations({ ...DEFAULT_SETTINGS, preset: "90-20", customWork: 33 }), { workMs: 90 * MIN, breakMs: 20 * MIN });
});

test("the review dot follows the total, and the sound plays only for new items", () => {
  const totals = [];
  let sounds = 0;
  const watch = createReviewWatch({ onChange: (t) => totals.push(t), onNew: () => (sounds += 1) });
  watch.update(2, []);
  watch.update(2, []);
  watch.update(3, [{ key: "task:a" }]);
  watch.update(0, []);
  assert.deepEqual(totals, [2, 3, 0]);
  assert.equal(sounds, 1);
});

test("the corner timer sits in the bottom-left corner of the work area, above the taskbar", () => {
  assert.deepEqual(cornerPosition({ x: 0, y: 0, width: 1920, height: 1040 }, { width: 112, height: 48 }), { x: 12, y: 982 });
  assert.deepEqual(cornerPosition({ x: 1920, y: 0, width: 2560, height: 1400 }, { width: 112, height: 48 }), { x: 1932, y: 1342 });
});

test("knows when Linux runs on Wayland, where the corner timer needs XWayland", () => {
  assert.equal(linuxDisplay({ platform: "win32", env: {}, ozonePlatform: "" }), "other");
  assert.equal(linuxDisplay({ platform: "linux", env: { WAYLAND_DISPLAY: "wayland-0" }, ozonePlatform: "" }), "wayland");
  assert.equal(linuxDisplay({ platform: "linux", env: { WAYLAND_DISPLAY: "wayland-0" }, ozonePlatform: "x11" }), "x11");
  assert.equal(linuxDisplay({ platform: "linux", env: { DISPLAY: ":0" }, ozonePlatform: "" }), "x11");
});
