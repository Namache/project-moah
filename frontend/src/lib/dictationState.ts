import { useSyncExternalStore } from "react";

/**
 * What the app's one microphone is doing, for screens that show their own microphone button
 * (the Review comment box) instead of the floating one. The floating dock still does the work.
 */
export type DictationPhase = "idle" | "starting" | "recording" | "transcribing";
export interface DictationState { phase: DictationPhase; message: string }

const TOGGLE = "moah:toggle-dictation";
let state: DictationState = { phase: "idle", message: "" };
const listeners = new Set<() => void>();

export function publishDictationState(next: DictationState) {
  if (next.phase === state.phase && next.message === state.message) return;
  state = next;
  listeners.forEach((listener) => listener());
}

export function useDictationState(): DictationState {
  return useSyncExternalStore((onChange) => { listeners.add(onChange); return () => listeners.delete(onChange); }, () => state);
}

/** Starts or stops dictation into the focused text field, like the dictation shortcut. */
export function toggleDictation() {
  window.dispatchEvent(new Event(TOGGLE));
}

export function onDictationToggle(handler: () => void): () => void {
  window.addEventListener(TOGGLE, handler);
  return () => window.removeEventListener(TOGGLE, handler);
}
