import { useEffect, useState, useSyncExternalStore } from "react";
import { pomodoroBridge, remainingMs, type PomodoroState, type PomodoroTimer } from "../api/pomodoro";

// One copy of the timer's state for the whole page, kept current by the main process.
let current: PomodoroState | null = null;
let started = false;
const listeners = new Set<() => void>();

function set(state: PomodoroState) {
  current = state;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const bridge = pomodoroBridge();
  if (bridge && !started) {
    started = true;
    bridge.onState(set);
    void bridge.get().then(set).catch(() => { started = false; });
  }
  return () => listeners.delete(listener);
}

/** For tests: forget what the last test's desktop bridge said. */
export function resetPomodoroForTests() {
  current = null;
  started = false;
}

/** The timer's state, or null in a browser or until the desktop app answers. */
export function usePomodoro(): PomodoroState | null {
  return useSyncExternalStore(subscribe, () => current);
}

/** The page's own copy, updated after a change the page made, so the screen doesn't wait for the next message. */
export function applyPomodoroState(state: PomodoroState | null | undefined) {
  if (state) set(state);
}

/** Time left, redrawn several times a second while the timer runs. */
export function useRemaining(timer: PomodoroTimer | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  const running = Boolean(timer?.running);
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [running]);
  return timer ? remainingMs(timer, running ? now : undefined) : 0;
}
