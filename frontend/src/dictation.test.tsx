import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DictationDock } from "./components/dictation/DictationDock";
import { downsample, insertDictation, isQuiet, SampleStore, wavBytes } from "./lib/recorder";
import { LiveDictation } from "./lib/liveDictation";

const recorder = vi.hoisted(() => ({ stop: vi.fn(), cancel: vi.fn(), fail: null as DOMException | null, samples: 0 }));
vi.mock("./lib/recorder", async (original) => ({
  ...(await original<typeof import("./lib/recorder")>()),
  startRecording: vi.fn(async () => {
    if (recorder.fail) throw recorder.fail;
    return { rate: 16_000, length: () => recorder.samples, clip: () => new Blob(["wav"], { type: "audio/wav" }), quietBefore: () => false, stop: recorder.stop, cancel: recorder.cancel };
  }),
}));

/** A form like the app's: a title input and a details text area, both React-controlled. */
function Form({ title = "", details = "" }: { title?: string; details?: string }) {
  const [titleValue, setTitle] = useState(title);
  const [detailsValue, setDetails] = useState(details);
  return (
    <form>
      <label htmlFor="title">Title *</label><input id="title" value={titleValue} onChange={(event) => setTitle(event.target.value)} />
      <label htmlFor="details">Details</label><textarea id="details" value={detailsValue} onChange={(event) => setDetails(event.target.value)} />
      <p data-testid="saved">{titleValue}|{detailsValue}</p>
    </form>
  );
}

function setup({ available = true, text = "The save migration needs a test.", live = [] as string[] } = {}) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input), method = options?.method ?? "GET";
    calls.push({ url, method });
    if (url === "/api/dictation/status") return Response.json({ available, reason: available ? null : "The speech model is not part of this build." });
    if (url.startsWith("/api/dictation/transcribe")) return Response.json({ text: live.shift() ?? text, language: "en" });
    return Response.json([]);
  }));
  recorder.samples = 0;
  return calls;
}

const renderApp = (props?: { title?: string; details?: string }) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Form {...props} /><DictationDock /></QueryClientProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); recorder.fail = null; vi.clearAllMocks(); localStorage.clear(); });

describe("dictation", () => {
  it("writes into the field that was clicked, live while speaking, then puts in the final text at the cursor", async () => {
    const calls = setup({ live: ["The save"] });
    renderApp({ details: "Old saves load. Then ship." });
    const details = screen.getByLabelText("Details") as HTMLTextAreaElement;
    await userEvent.click(details);
    details.setSelectionRange(16, 16);
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    expect(await screen.findByRole("button", { name: "Stop dictating into Details" })).toHaveAttribute("aria-pressed", "true");
    expect(details).toHaveAttribute("readonly");
    recorder.samples = 16_000 * 2;
    await waitFor(() => expect(details).toHaveValue("Old saves load. The save Then ship."));
    await userEvent.click(screen.getByRole("button", { name: "Stop dictating into Details" }));
    await waitFor(() => expect(details).toHaveValue("Old saves load. The save migration needs a test. Then ship."));
    // The form's own state followed, as if the words had been typed.
    expect(screen.getByTestId("saved")).toHaveTextContent("|Old saves load. The save migration needs a test. Then ship.");
    expect(details).not.toHaveAttribute("readonly");
    expect(document.activeElement).toBe(details);
    expect(calls.filter((call) => call.url.startsWith("/api/dictation/transcribe")).every((call) => call.method === "POST")).toBe(true);
    expect(calls.every((call) => call.url.startsWith("/api/"))).toBe(true);
  });

  it("works in a title field and starts and stops with Ctrl+Shift+Space", async () => {
    setup({ text: "Welcome back popup" });
    renderApp();
    const title = screen.getByLabelText("Title *");
    await userEvent.click(title);
    expect(await screen.findByRole("button", { name: "Dictate into Title" })).toBeInTheDocument();
    fireEvent.keyDown(window, { code: "Space", key: " ", ctrlKey: true, shiftKey: true });
    expect(await screen.findByRole("button", { name: "Stop dictating into Title" })).toBeInTheDocument();
    recorder.samples = 16_000;
    fireEvent.keyDown(window, { code: "Space", key: " ", ctrlKey: true, shiftKey: true });
    await waitFor(() => expect(title).toHaveValue("Welcome back popup"));
  });

  it("asks for a field first when none is selected", async () => {
    setup();
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Dictate" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Click the field you want to write in");
  });

  it("listens for the language chosen in Settings", async () => {
    const calls = setup({ text: "Окно возвращения" });
    localStorage.setItem("moah.dictationLanguage", "ru");
    renderApp();
    await userEvent.click(screen.getByLabelText("Details"));
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    recorder.samples = 16_000;
    await userEvent.click(await screen.findByRole("button", { name: "Stop dictating into Details" }));
    await waitFor(() => expect(screen.getByLabelText("Details")).toHaveValue("Окно возвращения"));
    expect(calls.some((call) => call.url === "/api/dictation/transcribe?language=ru")).toBe(true);
  });

  it("shows no microphone when the build has no speech model", async () => {
    const calls = setup({ available: false });
    renderApp();
    await waitFor(() => expect(calls.some((call) => call.url === "/api/dictation/status")).toBe(true));
    expect(screen.queryByRole("button", { name: /Dictate/ })).not.toBeInTheDocument();
  });

  it("says when the microphone is refused or nothing was heard, and leaves the text as it was", async () => {
    setup({ text: "" });
    renderApp({ details: "Keep me" });
    await userEvent.click(screen.getByLabelText("Details"));
    recorder.fail = new DOMException("denied", "NotAllowedError");
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone access was refused.");
    recorder.fail = null;
    await userEvent.click(screen.getByRole("button", { name: "Dictate into Details" }));
    recorder.samples = 16_000;
    await userEvent.click(await screen.findByRole("button", { name: "Stop dictating into Details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No speech was heard.");
    expect(screen.getByLabelText("Details")).toHaveValue("Keep me");
  });
});

describe("live dictation", () => {
  function fakeRecording(rate = 1000) {
    const state = { length: 0, quiet: false, clips: [] as [number, number][] };
    const recording = { rate, length: () => state.length, clip: (from: number, to: number) => { state.clips.push([from, to]); return new Blob(); }, quietBefore: () => state.quiet, stop: vi.fn(), cancel: vi.fn() };
    return { state, recording };
  }

  it("sends only the newest part quickly, and settles a long part at a pause with an exact pass", async () => {
    const { state, recording } = fakeRecording();
    const replies = ["one", "one two", "three", "three four"];
    const passes: boolean[] = [];
    const shown: string[] = [];
    const live = new LiveDictation(recording, async (_wav, quick) => { passes.push(quick); return replies.shift() ?? ""; }, (words) => shown.push(words), 60_000);
    state.length = 5_000; await live.tick();
    state.length = 7_000; state.quiet = true; await live.tick(); // 7 s at a pause: settled
    state.quiet = false; state.length = 9_000; await live.tick();
    state.length = 9_500; await live.tick(); // less than a step of new sound: nothing sent
    state.length = 11_000; await live.tick();
    expect(state.clips).toEqual([[0, 5_000], [0, 7_000], [7_000, 9_000], [7_000, 11_000]]);
    expect(passes).toEqual([true, false, true, true]);
    expect(shown).toEqual(["one", "one two", "one two three", "one two three four"]);
    replies.push("three four five");
    state.length = 12_000;
    expect(await live.finish()).toBe("one two three four five");
    expect(state.clips.at(-1)).toEqual([7_000, 12_000]);
    expect(passes.at(-1)).toBe(false);
    expect(recording.stop).toHaveBeenCalled();
  });

  it("settles a part that runs past the quick window even without a pause", async () => {
    const { state, recording } = fakeRecording();
    const passes: boolean[] = [];
    const live = new LiveDictation(recording, async (_wav, quick) => { passes.push(quick); return "words"; }, () => {}, 60_000);
    state.length = 9_600; await live.tick();
    state.length = 11_000; await live.tick();
    expect(passes).toEqual([false, true]);
    expect(state.clips).toEqual([[0, 9_600], [9_600, 11_000]]);
    live.cancel();
  });

  it("keeps going when one live update fails", async () => {
    const { state, recording } = fakeRecording();
    let calls = 0;
    const shown: string[] = [];
    const live = new LiveDictation(recording, async () => { calls += 1; if (calls === 1) throw new Error("busy"); return "hello"; }, (words) => shown.push(words), 60_000);
    state.length = 2_000; await live.tick();
    state.length = 4_000; await live.tick();
    expect(shown).toEqual(["hello"]);
    live.cancel();
  });
});

describe("recording helpers", () => {
  it("adds spaces only where words would touch", () => {
    expect(insertDictation("", "Hello")).toEqual({ value: "Hello", cursor: 5 });
    expect(insertDictation("Ship it.", "Then test", 8)).toEqual({ value: "Ship it. Then test", cursor: 18 });
    expect(insertDictation("ab", "X", 1)).toEqual({ value: "a X b", cursor: 3 });
    expect(insertDictation("keep replace keep", "new", 5, 12)).toEqual({ value: "keep new keep", cursor: 8 });
  });

  it("keeps recorded sound in one growing buffer and spots pauses", () => {
    const store = new SampleStore();
    for (let i = 0; i < 200; i++) store.push(new Float32Array(4096).fill(i % 2 ? 0.5 : 0));
    expect(store.length).toBe(200 * 4096);
    expect(store.slice(4096, 4098)).toEqual(new Float32Array([0.5, 0.5]));
    expect(isQuiet(new Float32Array(100))).toBe(true);
    expect(isQuiet(new Float32Array(100).fill(0.2))).toBe(false);
  });

  it("writes 16 kHz mono 16-bit WAV", () => {
    const samples = downsample(new Float32Array(48_000).fill(0.5), 48_000, 16_000);
    expect(samples.length).toBe(16_000);
    const bytes = wavBytes(samples, 16_000);
    const view = new DataView(bytes);
    expect(bytes.byteLength).toBe(44 + 32_000);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getInt16(44, true)).toBe(16383);
  });
});
