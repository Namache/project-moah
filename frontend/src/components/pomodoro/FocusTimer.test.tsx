import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PomodoroBridge, PomodoroSettings, PomodoroState, PomodoroTimer } from "../../api/pomodoro";
import { applyPomodoroState, resetPomodoroForTests } from "../../hooks/usePomodoro";
import { LanguageRoot, setLanguage } from "../../lib/i18n";
import { FocusTimerSettings, SoundSettings } from "./FocusTimerSettings";
import { FocusTimerWidget } from "./FocusTimerWidget";

const settings: PomodoroSettings = { enabled: true, preset: "25-5", customWork: 30, customBreak: 6, soundsOn: true, volume: 70, miniSize: "small", sounds: { break: null, work: null, review: null } };
const idle: PomodoroTimer = { phase: "idle", running: false, endsAt: null, remainingMs: 25 * 60_000, totalMs: 25 * 60_000 };

function stateWith(changes: { settings?: Partial<PomodoroSettings>; timer?: Partial<PomodoroTimer>; restartNeeded?: boolean } = {}): PomodoroState {
  return { settings: { ...settings, ...changes.settings }, timer: { ...idle, ...changes.timer }, review: 0, miniSupported: true, restartNeeded: changes.restartNeeded ?? false, now: Date.now() };
}

/** A stand-in for the desktop app: it remembers the settings and answers like the main process. */
function fakeDesktop(start: PomodoroState) {
  let state = start;
  const answer = () => Promise.resolve(state);
  const bridge = {
    get: vi.fn(answer),
    update: vi.fn(async (partial: Partial<PomodoroSettings>) => { state = { ...state, settings: { ...state.settings, ...partial } }; return state; }),
    command: vi.fn(async (name: string) => {
      if (name === "start") state = { ...state, timer: { ...state.timer, phase: "focus", running: true, endsAt: Date.now() + state.timer.remainingMs } };
      return state;
    }),
    chooseSound: vi.fn(async () => ({ state })),
    resetSound: vi.fn(answer),
    sound: vi.fn(async () => null),
    quit: vi.fn(async () => {}),
    onState: vi.fn(() => () => {}),
    onCue: vi.fn(() => () => {}),
  } satisfies PomodoroBridge;
  (window as { projectBrainDesktop?: unknown }).projectBrainDesktop = { apiToken: "t", pomodoro: bridge };
  return bridge;
}

const show = (ui: React.ReactNode) => render(<MemoryRouter><LanguageRoot>{ui}</LanguageRoot></MemoryRouter>);

afterEach(() => {
  cleanup();
  resetPomodoroForTests();
  setLanguage("system");
  delete (window as { projectBrainDesktop?: unknown }).projectBrainDesktop;
});

describe("focus timer on Home", () => {
  it("stays out of the way in a browser and while the timer is turned off", async () => {
    const { container, unmount } = show(<FocusTimerWidget />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    const bridge = fakeDesktop(stateWith({ settings: { enabled: false } }));
    show(<FocusTimerWidget />);
    await waitFor(() => expect(bridge.get).toHaveBeenCalled());
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
  });

  it("starts a focus round and counts real minutes down", async () => {
    const bridge = fakeDesktop(stateWith());
    const user = userEvent.setup();
    show(<FocusTimerWidget />);
    expect(await screen.findByRole("timer")).toHaveTextContent("25:00");
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip to break" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Stop the timer" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Start" }));
    expect(bridge.command).toHaveBeenCalledWith("start");
    expect(await screen.findByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByText("Focus")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop the timer" })).toBeEnabled();

    act(() => applyPomodoroState(stateWith({ timer: { phase: "break", running: true, endsAt: Date.now() + 4 * 60_000 + 12_500, totalMs: 5 * 60_000 } })));
    expect(screen.getByRole("timer")).toHaveTextContent("04:13");
    expect(screen.getByRole("button", { name: "Skip to focus" })).toBeEnabled();

    act(() => applyPomodoroState(stateWith({ timer: { phase: "break", running: false, remainingMs: 61_000, totalMs: 5 * 60_000 } })));
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("waits for Start when a part ends, naming what comes next", async () => {
    const bridge = fakeDesktop(stateWith({ timer: { phase: "break", running: false, waiting: true, remainingMs: 5 * 60_000, totalMs: 5 * 60_000 } }));
    const user = userEvent.setup();
    show(<FocusTimerWidget />);
    expect(await screen.findByText("Break is ready")).toBeInTheDocument();
    expect(screen.getByRole("timer")).toHaveTextContent("05:00");
    await user.click(screen.getByRole("button", { name: "Start break" }));
    expect(bridge.command).toHaveBeenCalledWith("start");

    act(() => applyPomodoroState(stateWith({ timer: { phase: "focus", running: false, waiting: true, remainingMs: 25 * 60_000, totalMs: 25 * 60_000 } })));
    expect(screen.getByText("Time to focus")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start focus" })).toBeInTheDocument();
  });
});

describe("focus timer settings", () => {
  it("only shows in the desktop app, and greys out everything while the timer is off", async () => {
    const { container, unmount } = show(<FocusTimerSettings />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    const bridge = fakeDesktop(stateWith({ settings: { enabled: false } }));
    const user = userEvent.setup();
    show(<FocusTimerSettings />);
    const toggle = await screen.findByRole("checkbox", { name: "Show the focus timer" });
    expect(toggle).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /25 \/ 5/ })).toBeDisabled();
    expect(screen.queryByRole("checkbox", { name: "Play sounds" })).not.toBeInTheDocument();
    await user.click(toggle);
    expect(bridge.update).toHaveBeenCalledWith({ enabled: true });
  });

  it("saves the Pomodoro type and keeps custom minutes in range", async () => {
    const bridge = fakeDesktop(stateWith());
    const user = userEvent.setup();
    show(<FocusTimerSettings />);
    const types = await screen.findByRole("radiogroup", { name: "Pomodoro type" });
    expect(within(types).getAllByRole("radio")).toHaveLength(6);
    expect(within(types).getByRole("radio", { name: /25 \/ 5/ })).toBeChecked();
    await user.click(within(types).getByRole("radio", { name: /40 \/ 10/ }));
    expect(bridge.update).toHaveBeenLastCalledWith({ preset: "40-10" });

    await user.click(within(types).getByRole("radio", { name: /Custom/ }));
    const focus = await screen.findByRole("spinbutton", { name: "Focus, minutes" });
    expect(focus).toHaveValue(30);
    await user.clear(focus);
    await user.type(focus, "300");
    await user.tab();
    expect(bridge.update).toHaveBeenLastCalledWith({ customWork: 180, customBreak: 6 });
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: "Focus, minutes" })).toHaveValue(180));

    const calls = bridge.update.mock.calls.length;
    await user.clear(screen.getByRole("spinbutton", { name: "Break, minutes" }));
    await user.tab();
    expect(bridge.update).toHaveBeenCalledTimes(calls);
  });

  it("sets how big the corner timer is", async () => {
    const bridge = fakeDesktop(stateWith());
    const user = userEvent.setup();
    show(<FocusTimerSettings />);
    const sizes = await screen.findByRole("group", { name: "Desktop timer size" });
    expect(within(sizes).getByRole("radio", { name: "Small" })).toBeChecked();
    await user.click(within(sizes).getByText("Large"));
    expect(bridge.update).toHaveBeenLastCalledWith({ miniSize: "large" });
    await waitFor(() => expect(within(sizes).getByRole("radio", { name: "Large" })).toBeChecked());
  });

  it("keeps sounds on their own, so they work while the timer is off", async () => {
    const { container, unmount } = show(<SoundSettings />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    fakeDesktop(stateWith({ settings: { enabled: false } }));
    show(<SoundSettings />);
    const toggle = await screen.findByRole("checkbox", { name: "Play sounds" });
    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
    expect(toggle).toHaveAccessibleDescription("Works whether the focus timer is on or off.");
    expect(screen.getByRole("slider", { name: "Volume" })).toBeEnabled();
    expect(screen.getAllByRole("button", { name: "Play" })[2]).toBeEnabled();
    expect(screen.getAllByText("Plays while the focus timer is on")).toHaveLength(2);
  });

  it("saves the volume once the slider rests, and turns sounds off", async () => {
    const bridge = fakeDesktop(stateWith());
    const user = userEvent.setup();
    show(<SoundSettings />);
    const slider = await screen.findByRole("slider", { name: "Volume" });
    fireEvent.change(slider, { target: { value: "40" } });
    fireEvent.change(slider, { target: { value: "35" } });
    expect(screen.getByText("35%")).toBeInTheDocument();
    expect(bridge.update).not.toHaveBeenCalled();
    await waitFor(() => expect(bridge.update).toHaveBeenCalledWith({ volume: 35 }));
    expect(bridge.update).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("checkbox", { name: "Play sounds" }));
    expect(bridge.update).toHaveBeenLastCalledWith({ soundsOn: false });
    await waitFor(() => expect(screen.getByRole("slider", { name: "Volume" })).toBeDisabled());
  });

  it("names each sound, and offers the default back only for a sound you chose", async () => {
    fakeDesktop(stateWith({ settings: { sounds: { break: { file: "break.mp3", name: "Temple bell.mp3" }, work: null, review: null } } }));
    show(<SoundSettings />);
    expect(await screen.findByText("Temple bell.mp3")).toBeInTheDocument();
    expect(screen.getByText("Default: wooden knock")).toBeInTheDocument();
    expect(screen.getByText("Default: calm drop")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Play" })).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Choose your own sound for Break starts" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use the default sound for Break starts" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use the default sound for Back to work" })).not.toBeInTheDocument();
  });

  it("says plainly when a chosen file can't be used", async () => {
    const bridge = fakeDesktop(stateWith());
    bridge.chooseSound.mockResolvedValueOnce({ state: stateWith(), error: "size" } as never);
    const user = userEvent.setup();
    show(<SoundSettings />);
    await user.click(await screen.findByRole("button", { name: "Choose your own sound for New in Review" }));
    expect(bridge.chooseSound).toHaveBeenCalledWith("review", { title: "Choose a sound", filter: "Sounds" });
    const dialog = await screen.findByRole("alertdialog", { name: "This file isn't supported" });
    expect(dialog).toHaveAccessibleDescription("You can upload an MP3, OGG, WAV or FLAC file up to 5 MB.");
    expect(await violations()).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "OK" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("asks for one restart on a Wayland desktop, with a way to quit", async () => {
    const bridge = fakeDesktop(stateWith({ restartNeeded: true }));
    const user = userEvent.setup();
    show(<FocusTimerSettings />);
    expect(await screen.findByText("Restart Project Moah to show the small timer in the corner of the screen.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Quit Project Moah" }));
    expect(bridge.quit).toHaveBeenCalled();
  });

  it("speaks Russian, and has no structural accessibility problems", async () => {
    fakeDesktop(stateWith({ settings: { preset: "custom" } }));
    const home = show(<FocusTimerWidget />);
    await screen.findByRole("timer");
    expect(await violations()).toEqual([]);
    act(() => setLanguage("ru"));
    expect(await screen.findByRole("button", { name: "Начать" })).toBeInTheDocument();
    expect(screen.getByText("Таймер фокуса")).toBeInTheDocument();
    home.unmount();

    act(() => setLanguage("system"));
    show(<><FocusTimerSettings /><SoundSettings /></>);
    await screen.findByRole("radiogroup", { name: "Pomodoro type" });
    expect(await violations()).toEqual([]);
    act(() => setLanguage("ru"));
    expect(await screen.findByRole("radiogroup", { name: "Тип помодоро" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Фокус, минут" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выбрать свой звук: «Начало перерыва»" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Звуки" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Проигрывать звуки" })).toHaveAccessibleDescription("Работает и с включённым, и с выключенным таймером фокуса.");
  });
});

const rules = { "color-contrast": { enabled: false }, region: { enabled: false } };
async function violations(): Promise<string[]> {
  const result = await axe.run(document.body, { rules });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")})`);
}
