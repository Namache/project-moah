"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const { DEFAULT_SETTINGS, cleanSettings, cornerPosition, createReviewWatch, createTimer, durations, linuxDisplay, miniSize, placeOnScreen, shouldCue } = require("./pomodoro-core.cjs");

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
  assert.deepEqual(h.timer.snapshot(), { phase: "idle", running: false, waiting: false, endsAt: null, remainingMs: 40 * MIN, totalMs: 40 * MIN });
  assert.equal(h.ticking, false);
});

test("goes round by itself: focus, break with the chime, focus with the back-to-work sound", () => {
  const h = harness();
  h.timer.start();
  assert.equal(h.timer.snapshot().phase, "focus");
  h.advance(25 * MIN - 1);
  assert.deepEqual(h.cues, []);
  h.advance(1);
  assert.deepEqual({ phase: h.timer.snapshot().phase, running: h.timer.snapshot().running, waiting: h.timer.snapshot().waiting, left: h.timer.snapshot().remainingMs }, { phase: "break", running: true, waiting: false, left: 5 * MIN });
  assert.deepEqual(h.cues, ["break"]);
  h.advance(5 * MIN);
  assert.deepEqual({ phase: h.timer.snapshot().phase, running: h.timer.snapshot().running }, { phase: "focus", running: true });
  assert.deepEqual(h.cues, ["break", "work"]);
});

test("pause works at any moment, in focus and in a break", () => {
  const h = harness();
  h.timer.start();
  h.advance(1_000);
  h.timer.pause();
  assert.equal(h.timer.snapshot().running, false);
  assert.equal(h.timer.snapshot().waiting, false);
  h.timer.start();
  h.advance(25 * MIN - 1_000);
  h.advance(2 * MIN);
  h.timer.pause();
  assert.deepEqual({ phase: h.timer.snapshot().phase, running: h.timer.snapshot().running, left: h.timer.snapshot().remainingMs }, { phase: "break", running: false, left: 3 * MIN });
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
  assert.deepEqual(h.timer.snapshot(), { phase: "idle", running: false, waiting: false, endsAt: null, remainingMs: 25 * MIN, totalMs: 25 * MIN });
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
    miniPosition: null,
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

test("a dragged corner timer keeps its place, pulled back inside the screen it is mostly on", () => {
  const size = { width: 136, height: 64 };
  const left = { x: 0, y: 0, width: 1920, height: 1040 };
  const right = { x: 1920, y: 0, width: 2560, height: 1400 };
  assert.equal(placeOnScreen(null, size, [left]), null);
  assert.deepEqual(placeOnScreen({ x: 800, y: 300 }, size, [left, right]), { x: 800, y: 300 });
  assert.deepEqual(placeOnScreen({ x: 3000, y: 1380 }, size, [left, right]), { x: 3000, y: 1336 });
  assert.deepEqual(placeOnScreen({ x: 1880, y: 500 }, size, [left, right]), { x: 1920, y: 500 });
  assert.deepEqual(placeOnScreen({ x: -50, y: -20 }, size, [left]), { x: 0, y: 0 });
  // The see-through edge may hang over the monitor's edge, the oval may not.
  assert.deepEqual(placeOnScreen({ x: 1900, y: 1000 }, size, [left], 8), { x: 1792, y: 984 });
  assert.deepEqual(placeOnScreen({ x: -50, y: -20 }, size, [left], 8), { x: -8, y: -8 });
  // Its monitor was unplugged: back to the corner.
  assert.equal(placeOnScreen({ x: 3000, y: 300 }, size, [left]), null);
});

test("a saved place is cleaned, and kept across other changes", () => {
  assert.deepEqual(cleanSettings({ miniPosition: { x: 12.4, y: 900.6 } }).miniPosition, { x: 12, y: 901 });
  assert.equal(cleanSettings({ miniPosition: { x: "1", y: 2 } }).miniPosition, null);
  assert.equal(cleanSettings({ miniPosition: { x: 1e9, y: 2 } }).miniPosition, null);
  const saved = cleanSettings({ miniPosition: { x: 40, y: 50 } });
  assert.deepEqual(cleanSettings({ volume: 10 }, saved).miniPosition, { x: 40, y: 50 });
});

test("sounds are on by default and separate from the timer: Review chimes with the timer off", () => {
  assert.equal(DEFAULT_SETTINGS.soundsOn, true);
  assert.equal(DEFAULT_SETTINGS.enabled, false);
  const timerOff = cleanSettings({});
  assert.equal(shouldCue("review", timerOff), true);
  assert.equal(shouldCue("break", timerOff), false);
  assert.equal(shouldCue("work", timerOff), false);
  const timerOn = cleanSettings({ enabled: true });
  assert.deepEqual(["review", "break", "work"].map((kind) => shouldCue(kind, timerOn)), [true, true, true]);
  const muted = cleanSettings({ enabled: true, soundsOn: false });
  assert.deepEqual(["review", "break", "work"].map((kind) => shouldCue(kind, muted)), [false, false, false]);
});
