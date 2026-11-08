import { afterEach, describe, expect, it, vi } from "vitest";
import { readPref, resetPrefsForTests, writePref } from "./prefs";

function desktopWith(prefs: Record<string, string>) {
  const setPref = vi.fn();
  Object.defineProperty(window, "projectBrainDesktop", { value: { apiToken: "t", prefs, setPref }, configurable: true });
  resetPrefsForTests();
  return setPref;
}

afterEach(() => {
  localStorage.clear();
  Reflect.deleteProperty(window, "projectBrainDesktop");
  resetPrefsForTests();
});

describe("choices survive the desktop app starting on a new port", () => {
  it("reads the desktop app's saved choice when the page's storage is empty", () => {
    desktopWith({ "pb-theme": "dark", "pb-language": "ru" });
    expect(readPref("pb-theme")).toBe("dark");
    expect(readPref("pb-language")).toBe("ru");
    expect(readPref("pb-missing")).toBeNull();
  });

  it("saves every change in the desktop app too, and forgets removed ones", () => {
    const setPref = desktopWith({});
    writePref("pb-theme", "light");
    expect(setPref).toHaveBeenLastCalledWith("pb-theme", "light");
    expect(readPref("pb-theme")).toBe("light");
    writePref("pb-theme", null);
    expect(setPref).toHaveBeenLastCalledWith("pb-theme", null);
    expect(readPref("pb-theme")).toBeNull();
  });

  it("copies a choice made before this version over to the desktop app once", () => {
    localStorage.setItem("pb-theme", "dark");
    const setPref = desktopWith({});
    expect(readPref("pb-theme")).toBe("dark");
    expect(readPref("pb-theme")).toBe("dark");
    expect(setPref).toHaveBeenCalledTimes(1);
    expect(setPref).toHaveBeenCalledWith("pb-theme", "dark");
  });

  it("works from the page's storage alone in a browser", () => {
    writePref("pb-theme", "dark");
    expect(readPref("pb-theme")).toBe("dark");
    expect(localStorage.getItem("pb-theme")).toBe("dark");
  });
});
