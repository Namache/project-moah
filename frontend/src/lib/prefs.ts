/**
 * Per-person conveniences (theme, language, folded sections, panel widths). Always safe to lose;
 * never required to work.
 *
 * The page's own storage belongs to the window's address, port included, so it starts empty when
 * the desktop app has to use a new port. The desktop app therefore also keeps each choice in its
 * settings folder; a choice found only in the page's storage (from before) is copied over.
 */
type Saved = Record<string, string>;
let saved: Saved | null | undefined;

const desktop = () => (typeof window === "undefined" ? undefined : window.projectBrainDesktop);

function desktopChoices(): Saved | null {
  if (saved === undefined) {
    const prefs = desktop()?.prefs;
    saved = prefs && desktop()?.setPref ? { ...prefs } : null;
  }
  return saved;
}

function local(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function readPref(key: string): string | null {
  const choices = desktopChoices();
  if (choices && key in choices) return choices[key];
  const value = local(key);
  if (choices && value !== null) {
    choices[key] = value;
    desktop()?.setPref?.(key, value);
  }
  return value;
}

export function writePref(key: string, value: string | null): void {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* storage may be blocked */ }
  const choices = desktopChoices();
  if (!choices) return;
  if (value === null) delete choices[key];
  else choices[key] = value;
  try { desktop()?.setPref?.(key, value); } catch { /* the desktop app may be closing */ }
}

/** Tests only: forget what was read from the desktop app. */
export function resetPrefsForTests(): void {
  saved = undefined;
}
