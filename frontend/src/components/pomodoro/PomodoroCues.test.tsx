import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PomodoroSettings, PomodoroSoundKind, PomodoroState } from "../../api/pomodoro";
import { applyPomodoroState, resetPomodoroForTests } from "../../hooks/usePomodoro";
import { playTimerSound } from "../../lib/pomodoroSounds";
import { PomodoroCues } from "./PomodoroCues";

vi.mock("../../lib/pomodoroSounds", () => ({ playTimerSound: vi.fn(async () => true), canPlay: vi.fn(async () => true) }));

const settings: PomodoroSettings = { enabled: true, preset: "25-5", customWork: 30, customBreak: 6, soundsOn: true, volume: 70, miniSize: "small", sounds: { break: null, work: null, review: null } };
const state = (changes: Partial<PomodoroSettings> = {}): PomodoroState => ({ settings: { ...settings, ...changes }, timer: { phase: "focus", running: true, endsAt: Date.now() + 60_000, remainingMs: 60_000, totalMs: 60_000 }, review: 0, miniSupported: true, restartNeeded: false, now: Date.now() });

afterEach(() => {
  cleanup();
  resetPomodoroForTests();
  vi.mocked(playTimerSound).mockClear();
  delete (window as { projectBrainDesktop?: unknown }).projectBrainDesktop;
});

describe("timer sounds", () => {
  it("plays the cue the desktop app sends, and stays quiet once sounds are off", async () => {
    let cue: ((kind: PomodoroSoundKind) => void) | undefined;
    const bridge = { get: vi.fn(async () => state()), onState: vi.fn(() => () => {}), onCue: vi.fn((listener: (kind: PomodoroSoundKind) => void) => { cue = listener; return () => {}; }) };
    (window as { projectBrainDesktop?: unknown }).projectBrainDesktop = { apiToken: "t", pomodoro: bridge };
    render(<PomodoroCues />);
    await waitFor(() => expect(cue).toBeDefined());

    act(() => cue?.("break"));
    expect(playTimerSound).toHaveBeenCalledWith("break", expect.objectContaining({ volume: 70 }));

    act(() => applyPomodoroState(state({ soundsOn: false })));
    act(() => cue?.("review"));
    expect(playTimerSound).toHaveBeenCalledTimes(1);
  });

  it("plays the Review sound with the focus timer off", async () => {
    let cue: ((kind: PomodoroSoundKind) => void) | undefined;
    const bridge = { get: vi.fn(async () => state({ enabled: false })), onState: vi.fn(() => () => {}), onCue: vi.fn((listener: (kind: PomodoroSoundKind) => void) => { cue = listener; return () => {}; }) };
    (window as { projectBrainDesktop?: unknown }).projectBrainDesktop = { apiToken: "t", pomodoro: bridge };
    render(<PomodoroCues />);
    await waitFor(() => expect(cue).toBeDefined());
    act(() => cue?.("review"));
    expect(playTimerSound).toHaveBeenCalledWith("review", expect.objectContaining({ enabled: false }));
  });
});
