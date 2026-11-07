"use strict";

// The focus (Pomodoro) timer's rules, with no Electron in them so they can be tested on plain Node.
// The timer lives in the main process: it keeps exact time while Moah's window is hidden, and the
// windows only draw what it reports.

/** Focus and break minutes for each rhythm offered in Settings. "custom" uses the person's own numbers. */
const PRESETS = Object.freeze({
  "25-5": [25, 5],
  "40-10": [40, 10],
  "50-10": [50, 10],
  "52-17": [52, 17],
  "90-20": [90, 20],
});
const SOUND_KINDS = Object.freeze(["break", "work", "review"]);
// The formats Settings names when a file is turned down: "MP3, OGG, WAV or FLAC, up to 5 MB".
const SOUND_EXTENSIONS = Object.freeze(["mp3", "ogg", "wav", "flac"]);
const MAX_SOUND_BYTES = 5 * 1024 * 1024;
// How much bigger the corner timer is drawn for each size picked in Settings. Small is the oval as designed.
const MINI_SCALES = Object.freeze({ small: 1, medium: 1.35, large: 1.75 });
const MINUTE = 60_000;

const DEFAULT_SETTINGS = Object.freeze({
  enabled: false,
  preset: "25-5",
  customWork: 30,
  customBreak: 6,
  soundsOn: true,
  volume: 70,
  miniSize: "small",
  sounds: Object.freeze({ break: null, work: null, review: null }),
});

function wholeNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, Math.round(number)));
}

/** A custom sound as saved: the copy's file name in Moah's sounds folder and the original name to show. */
function cleanSound(kind, value) {
  if (!value || typeof value !== "object") return null;
  const { file, name } = value;
  if (typeof file !== "string" || typeof name !== "string") return null;
  const match = /^([a-z]+)\.([a-z0-9]+)$/.exec(file);
  if (!match || match[1] !== kind || !SOUND_EXTENSIONS.includes(match[2])) return null;
  return { file, name: name.slice(0, 200) };
}

/** Settings from disk or from the window, with anything unknown or out of range replaced by a safe value. */
function cleanSettings(raw, base = DEFAULT_SETTINGS) {
  const input = raw && typeof raw === "object" ? raw : {};
  const sounds = {};
  for (const kind of SOUND_KINDS) {
    const given = input.sounds && typeof input.sounds === "object" && kind in input.sounds ? input.sounds[kind] : base.sounds[kind];
    sounds[kind] = cleanSound(kind, given);
  }
  return {
    enabled: typeof input.enabled === "boolean" ? input.enabled : base.enabled,
    preset: typeof input.preset === "string" && (input.preset in PRESETS || input.preset === "custom") ? input.preset : base.preset,
    customWork: wholeNumber(input.customWork ?? base.customWork, 1, 180, base.customWork),
    customBreak: wholeNumber(input.customBreak ?? base.customBreak, 1, 60, base.customBreak),
    soundsOn: typeof input.soundsOn === "boolean" ? input.soundsOn : base.soundsOn,
    volume: wholeNumber(input.volume ?? base.volume, 0, 100, base.volume),
    miniSize: typeof input.miniSize === "string" && input.miniSize in MINI_SCALES ? input.miniSize : base.miniSize,
    sounds,
  };
}

/** How long focus and break last, in milliseconds. */
function durations(settings) {
  const [work, rest] = settings.preset === "custom" ? [settings.customWork, settings.customBreak] : PRESETS[settings.preset] ?? PRESETS["25-5"];
  return { workMs: work * MINUTE, breakMs: rest * MINUTE };
}

/**
 * The timer itself. It goes round by itself: focus, break, focus... until stopped.
 * `plan()` gives the current durations, so a changed rhythm applies from the next phase on.
 * `onChange(snapshot)` runs after every change; `onCue("break" | "work")` when a phase ends by itself.
 */
function createTimer({ plan, onChange = () => {}, onCue = () => {}, now = Date.now, setInterval: every = setInterval, clearInterval: stopEvery = clearInterval, tickMs = 500 }) {
  let phase = "idle";
  let running = false;
  let endsAt = null;
  let remainingMs = plan().workMs;
  let totalMs = remainingMs;
  let ticker = null;

  const snapshot = () => ({ phase, running, endsAt, remainingMs: running ? Math.max(0, endsAt - now()) : remainingMs, totalMs });
  const changed = () => onChange(snapshot());

  // A steady check of the wall clock, instead of one long timeout: it stays right after the computer
  // sleeps, and when the clock is changed.
  function watch(on) {
    if (on && !ticker) {
      ticker = every(check, tickMs);
      ticker?.unref?.();
    } else if (!on && ticker) {
      stopEvery(ticker);
      ticker = null;
    }
  }

  function enter(next, keepRunning) {
    const { workMs, breakMs } = plan();
    phase = next;
    totalMs = next === "break" ? breakMs : workMs;
    remainingMs = totalMs;
    running = keepRunning;
    endsAt = running ? now() + totalMs : null;
    watch(running);
  }

  function check() {
    if (!running || now() < endsAt) return;
    const next = phase === "break" ? "focus" : "break";
    enter(next, true);
    onCue(next === "break" ? "break" : "work");
    changed();
  }

  return {
    snapshot,
    check,
    start() {
      if (running) return;
      if (phase === "idle") enter("focus", true);
      else {
        running = true;
        endsAt = now() + remainingMs;
        watch(true);
      }
      changed();
    },
    pause() {
      if (!running) return;
      remainingMs = Math.max(0, endsAt - now());
      running = false;
      endsAt = null;
      watch(false);
      changed();
    },
    /** Straight to the next phase, without its sound. A paused timer stays paused. */
    skip() {
      if (phase === "idle") return;
      enter(phase === "break" ? "focus" : "break", running);
      changed();
    },
    stop() {
      phase = "idle";
      running = false;
      endsAt = null;
      remainingMs = totalMs = plan().workMs;
      watch(false);
      changed();
    },
    /** The rhythm changed in Settings. A stopped timer shows the new focus length; a running one keeps its phase. */
    planChanged() {
      if (phase !== "idle") return;
      remainingMs = totalMs = plan().workMs;
      changed();
    },
    dispose() {
      watch(false);
    },
  };
}

/**
 * Items waiting in Review, as the main process sees them every few seconds. The dot shows while
 * anything waits; the sound plays only for items that are new since the last check.
 */
function createReviewWatch({ onChange = () => {}, onNew = () => {} } = {}) {
  let total = 0;
  return {
    get total() {
      return total;
    },
    update(nextTotal, fresh = []) {
      const count = Number.isFinite(nextTotal) && nextTotal > 0 ? Math.floor(nextTotal) : 0;
      const changed = count !== total;
      total = count;
      if (changed) onChange(total);
      if (Array.isArray(fresh) && fresh.length > 0) onNew(fresh.length);
    },
  };
}

/** The corner window's size for a scale: the designed 136 x 64 (room for the oval, its shadow and the count). */
function miniSize(scale = 1, base = { width: 136, height: 64 }) {
  return { width: Math.round(base.width * scale), height: Math.round(base.height * scale) };
}

/** Where the corner timer goes: the bottom-left corner of the work area, so it sits just above the taskbar. */
function cornerPosition(workArea, size, margin = { x: 12, y: 10 }) {
  return {
    x: Math.round(workArea.x + margin.x),
    y: Math.round(workArea.y + workArea.height - size.height - margin.y),
  };
}

/**
 * Whether the corner timer can be placed and kept on top. On a Linux Wayland session Electron can
 * do neither, and it can't tell when the window is minimized; Moah then runs through XWayland
 * while the timer is on, which needs one restart.
 */
function linuxDisplay({ platform, env, ozonePlatform }) {
  if (platform !== "linux") return "other";
  if (ozonePlatform === "x11") return "x11";
  if (ozonePlatform === "wayland") return "wayland";
  return env.WAYLAND_DISPLAY ? "wayland" : "x11";
}

module.exports = {
  DEFAULT_SETTINGS,
  MAX_SOUND_BYTES,
  MINI_SCALES,
  PRESETS,
  SOUND_EXTENSIONS,
  SOUND_KINDS,
  cleanSettings,
  cornerPosition,
  createReviewWatch,
  createTimer,
  durations,
  linuxDisplay,
  miniSize,
};
