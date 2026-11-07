import { useSyncExternalStore } from "react";
import { readPref, writePref } from "./prefs";

/**
 * Settings > Accessibility. Interface size zooms the whole window (sidebar, panels and text);
 * text size scales only the text, on top of it. The desktop app keeps both in its settings folder
 * and zooms the window itself; in a plain browser tab they live in the tab's storage and the zoom
 * is CSS, next to the browser's own zoom.
 */
export const zoomSteps = [0.9, 1, 1.1, 1.25, 1.5, 1.75, 2] as const;
export const textSteps = [1, 1.15, 1.3, 1.5] as const;

export type ZoomChoice = number | "auto";
export type DisplayState = DesktopDisplay;

const ZOOM_KEY = "pb-zoom";
const TEXT_KEY = "pb-text-size";
const listeners = new Set<() => void>();

const desktop = () => (typeof window === "undefined" ? undefined : window.projectBrainDesktop);

function cleanZoom(value: unknown): ZoomChoice {
  return typeof value === "number" && (zoomSteps as readonly number[]).includes(value) ? value : "auto";
}
function cleanText(value: unknown): number {
  return typeof value === "number" && (textSteps as readonly number[]).includes(value) ? value : 1;
}

function fromBrowser(): DisplayState {
  const zoom = cleanZoom(Number(readPref(ZOOM_KEY)));
  const text = cleanText(Number(readPref(TEXT_KEY)));
  // The browser has its own zoom and knows the screen better, so Automatic leaves the size alone here.
  return { zoom, text, auto: 1, zoomInUse: zoom === "auto" ? 1 : zoom };
}

let state: DisplayState = fromBrowser();

/** Puts the sizes on <html>: --text-scale feeds every text size in styles.css. */
function apply(next: DisplayState) {
  state = next;
  const root = document.documentElement;
  root.style.setProperty("--text-scale", String(next.text));
  // The desktop app zooms the window natively; a browser tab gets CSS zoom instead.
  if (!desktop()?.setDisplay) root.style.zoom = next.zoomInUse === 1 ? "" : String(next.zoomInUse);
  listeners.forEach((notify) => notify());
}

export function readDisplay(): DisplayState {
  return state;
}

export async function setDisplay(prefs: { zoom: ZoomChoice; text: number }) {
  const clean = { zoom: cleanZoom(prefs.zoom), text: cleanText(prefs.text) };
  const app = desktop();
  if (app?.setDisplay) {
    // Show the change at once; the app answers with what it saved and zoomed to.
    apply({ ...state, ...clean, zoomInUse: clean.zoom === "auto" ? state.auto : clean.zoom });
    const saved = await app.setDisplay(clean);
    if (saved) apply(saved);
    return;
  }
  writePref(ZOOM_KEY, clean.zoom === "auto" ? null : String(clean.zoom));
  writePref(TEXT_KEY, clean.text === 1 ? null : String(clean.text));
  apply(fromBrowser());
}

/** Call once before the first render, so the first paint already has the right sizes. */
export function initDisplay() {
  const app = desktop();
  apply(app?.display ?? fromBrowser());
  app?.onDisplayChange?.((next) => apply(next));
}

export function useDisplay(): DisplayState {
  return useSyncExternalStore((notify) => { listeners.add(notify); return () => { listeners.delete(notify); }; }, readDisplay);
}

/** 1.25 → "125%" in the person's language. */
export function percent(value: number, language?: string): string {
  return new Intl.NumberFormat(language, { style: "percent", maximumFractionDigits: 0 }).format(value);
}
