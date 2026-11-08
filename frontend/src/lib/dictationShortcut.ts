import { useEffect, useState } from "react";
import { msg } from "./i18n";
import { readPref, writePref } from "./prefs";

/**
 * The keys that start and stop dictation, chosen in Settings > Dictation. Saved as the modifiers
 * and the key's code, such as "Ctrl+KeyT": the code names the key's place on the keyboard, so the
 * shortcut keeps working in another keyboard layout. Ctrl also means Cmd on a Mac.
 */
const KEY = "moah.dictationShortcut";
export const DEFAULT_SHORTCUT = "Ctrl+KeyT";
const CHANGED = "moah:dictation-shortcut";

export type Shortcut = { ctrl: boolean; alt: boolean; shift: boolean; code: string };

/** Keys that only modify another key, so they can't be the key itself. */
const MODIFIERS = new Set(["ControlLeft", "ControlRight", "ShiftLeft", "ShiftRight", "AltLeft", "AltRight", "MetaLeft", "MetaRight", "OSLeft", "OSRight", "CapsLock", "Fn"]);
/** Shortcuts a text field (editing) or the app (search, zoom) already uses. */
const TAKEN = new Set(["Ctrl+KeyK", "Ctrl+KeyA", "Ctrl+KeyC", "Ctrl+KeyV", "Ctrl+KeyX", "Ctrl+KeyZ", "Ctrl+KeyY", "Ctrl+Shift+KeyZ", "Ctrl+Shift+KeyV", "Ctrl+Digit0", "Ctrl+Numpad0", "Ctrl+Minus", "Ctrl+Equal", "Ctrl+Shift+Equal", "Ctrl+NumpadAdd", "Ctrl+NumpadSubtract"]);

export function parseShortcut(text: string): Shortcut | null {
  const parts = text.split("+");
  const code = parts.pop() ?? "";
  if (!code || parts.some((part) => !["Ctrl", "Alt", "Shift"].includes(part))) return null;
  return { ctrl: parts.includes("Ctrl"), alt: parts.includes("Alt"), shift: parts.includes("Shift"), code };
}

export function shortcutText(shortcut: Shortcut): string {
  return [shortcut.ctrl && "Ctrl", shortcut.alt && "Alt", shortcut.shift && "Shift", shortcut.code].filter(Boolean).join("+");
}

/** The shortcut a key press makes, or null for a lone modifier key. */
export function shortcutFromEvent(event: KeyboardEvent): Shortcut | null {
  if (!event.code || MODIFIERS.has(event.code)) return null;
  return { ctrl: event.ctrlKey || event.metaKey, alt: event.altKey, shift: event.shiftKey, code: event.code };
}

/**
 * Why these keys can't start dictation, or null when they can. Dictation writes into the field
 * being typed in, so a key without Ctrl or Alt would start it instead of typing that letter.
 */
export function shortcutProblem(shortcut: Shortcut): string | null {
  if (!shortcut.ctrl && !shortcut.alt && !/^F([1-9]|1[0-9]|2[0-4])$/.test(shortcut.code)) return msg("Hold Ctrl or Alt with the key, so typing still works.");
  if (TAKEN.has(shortcutText(shortcut))) return msg("These keys already do something else.");
  return null;
}

export function matchesShortcut(event: KeyboardEvent, shortcut: Shortcut): boolean {
  return event.code === shortcut.code && (event.ctrlKey || event.metaKey) === shortcut.ctrl && event.altKey === shortcut.alt && event.shiftKey === shortcut.shift;
}

/** The key's name as printed on it: KeyT is T, Digit1 is 1, ArrowUp is Up. */
function keyName(code: string): string {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit\d$/.test(code)) return code.slice(5);
  if (/^Numpad\d$/.test(code)) return `Num ${code.slice(6)}`;
  if (code.startsWith("Arrow")) return code.slice(5);
  const names: Record<string, string> = { Space: "Space", Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]", Backslash: "\\", Semicolon: ";", Quote: "'", Comma: ",", Period: ".", Slash: "/", Backquote: "`", Enter: "Enter", Escape: "Esc", Backspace: "Backspace", Tab: "Tab" };
  return names[code] ?? code;
}

/** How the shortcut is written for people, such as Ctrl+T. */
export function shortcutLabel(shortcut: Shortcut): string {
  return [shortcut.ctrl && "Ctrl", shortcut.alt && "Alt", shortcut.shift && "Shift", keyName(shortcut.code)].filter(Boolean).join("+");
}

/** The same keys for aria-keyshortcuts, such as Control+T. */
export function shortcutAria(shortcut: Shortcut): string {
  const key = keyName(shortcut.code);
  return [shortcut.ctrl && "Control", shortcut.alt && "Alt", shortcut.shift && "Shift", key === "Esc" ? "Escape" : key].filter(Boolean).join("+");
}

export function readDictationShortcut(): Shortcut {
  const saved = parseShortcut(readPref(KEY) ?? "");
  return saved && !shortcutProblem(saved) ? saved : parseShortcut(DEFAULT_SHORTCUT)!;
}

/** Saves the shortcut; the default is saved as nothing, so a later default reaches this person too. */
export function saveDictationShortcut(shortcut: Shortcut): void {
  const text = shortcutText(shortcut);
  writePref(KEY, text === DEFAULT_SHORTCUT ? null : text);
  window.dispatchEvent(new Event(CHANGED));
}

/** The current shortcut, kept up to date when Settings changes it. */
export function useDictationShortcut(): Shortcut {
  const [shortcut, setShortcut] = useState(readDictationShortcut);
  useEffect(() => {
    const refresh = () => setShortcut(readDictationShortcut());
    window.addEventListener(CHANGED, refresh);
    return () => window.removeEventListener(CHANGED, refresh);
  }, []);
  return shortcut;
}
