import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useSyncExternalStore } from "react";
import { readPref, writePref } from "./prefs";

export type ThemeChoice = "system" | "light" | "dark";

export const themeChoices: { value: ThemeChoice; label: string; icon: LucideIcon }[] = [
  { value: "system", label: "System", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

const KEY = "pb-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
const listeners = new Set<() => void>();

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
}

export function readTheme(): ThemeChoice {
  const saved = readPref(KEY);
  return saved === "light" || saved === "dark" ? saved : "system";
}

/** Puts the resolved theme on <html>, where styles.css reads it. */
function apply(choice: ThemeChoice) {
  const dark = choice === "dark" || (choice === "system" && systemPrefersDark());
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function setTheme(choice: ThemeChoice) {
  writePref(KEY, choice === "system" ? null : choice);
  apply(choice);
  listeners.forEach((notify) => notify());
}

/** Call once before the first render, so the page never paints in the wrong theme; follows the system while the choice is System. */
export function initTheme() {
  apply(readTheme());
  if (typeof window.matchMedia !== "function") return;
  window.matchMedia(DARK_QUERY).addEventListener("change", () => { if (readTheme() === "system") apply("system"); });
}

export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const choice = useSyncExternalStore(
    (notify) => { listeners.add(notify); return () => { listeners.delete(notify); }; },
    readTheme,
  );
  return [choice, setTheme];
}
