import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DictationDock } from "./components/dictation/DictationDock";
import { DictationSettings } from "./components/dictation/DictationSettings";
import { dictationApi } from "./api/dictation";
import { downsample, insertDictation, isQuiet, level, SampleStore, startRecording, wavBytes } from "./lib/recorder";
import { LiveDictation } from "./lib/liveDictation";

const recorder = vi.hoisted(() => ({ stop: vi.fn(), cancel: vi.fn(), fail: null as DOMException | null, failWithDevice: null as DOMException | null, samples: 0 }));
vi.mock("./lib/recorder", async (original) => ({
  ...(await original<typeof import("./lib/recorder")>()),
  startRecording: vi.fn(async (_onLimit?: () => void, options?: { constraints?: MediaTrackConstraints }) => {
    if (recorder.fail) throw recorder.fail;
    if (recorder.failWithDevice && options?.constraints?.deviceId) throw recorder.failWithDevice;
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

const ENGINE = { loaded: true, load_seconds: 0.4, last_seconds: 1.2, last_audio_seconds: 3.4, last_finished: "2026-11-07T08:00:00+00:00", last_error: null as string | null, last_error_at: null as string | null, busy_since: null, threads: 7 };
const mic = (deviceId: string, label: string) => ({ kind: "audioinput", deviceId, label, groupId: "g" }) as MediaDeviceInfo;

function setup({ available = true, text = "The save migration needs a test.", live = [] as string[], devices = [] as MediaDeviceInfo[], engine = ENGINE } = {}) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn(), enumerateDevices: vi.fn(async () => devices), addEventListener: vi.fn(), removeEventListener: vi.fn() } });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input), method = options?.method ?? "GET";
    calls.push({ url, method });
    if (url === "/api/dictation/status") return Response.json({ available, reason: available ? null : "The speech model is not part of this build.", engine });
    if (url.startsWith("/api/dictation/transcribe")) return Response.json({ text: live.shift() ?? text, language: "en" });
    return Response.json([]);
  }));
  recorder.samples = 0;
  return calls;
}

const renderApp = (props?: { title?: string; details?: string }) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Form {...props} /><DictationDock /></QueryClientProvider>);
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); recorder.fail = null; recorder.failWithDevice = null; vi.clearAllMocks(); localStorage.clear(); });

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

describe("dictation input", () => {
  const constraintsOf = (call: number) => (vi.mocked(startRecording).mock.calls[call][1] as { constraints: MediaTrackConstraints }).constraints;

  it("records from the microphone and sound settings chosen in Settings, found again by name", async () => {
    setup({ devices: [mic("new-id", "USB headset"), mic("other", "Webcam")] });
    localStorage.setItem("moah.dictationInput", JSON.stringify({ deviceId: "old-id", label: "USB headset", noiseSuppression: false, echoCancellation: true, autoGainControl: false }));
    renderApp();
    await userEvent.click(screen.getByLabelText("Details"));
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    await screen.findByRole("button", { name: "Stop dictating into Details" });
    expect(constraintsOf(0)).toEqual({ channelCount: 1, noiseSuppression: false, echoCancellation: true, autoGainControl: false, deviceId: { exact: "new-id" } });
  });

  it("falls back to the default microphone when the chosen one will not open", async () => {
    setup({ devices: [mic("usb", "USB headset")] });
    localStorage.setItem("moah.dictationInput", JSON.stringify({ deviceId: "usb", label: "USB headset" }));
    recorder.failWithDevice = new DOMException("in use", "NotReadableError");
    renderApp();
    await userEvent.click(screen.getByLabelText("Details"));
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    await screen.findByRole("button", { name: "Stop dictating into Details" });
    expect(vi.mocked(startRecording)).toHaveBeenCalledTimes(2);
    expect(constraintsOf(1).deviceId).toBeUndefined();
  });

  it("says what to do when the microphone is busy", async () => {
    setup();
    recorder.fail = new DOMException("in use", "NotReadableError");
    renderApp();
    await userEvent.click(screen.getByLabelText("Details"));
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The microphone is in use by another app");
  });

  it("ends a reply that never comes with a clear message instead of waiting forever", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, options?: RequestInit) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    const live = dictationApi.transcribe(new Blob(["wav"]), "auto", true);
    const final = dictationApi.transcribe(new Blob([new Uint8Array(44 + 32_000 * 10)]), "auto", false);
    const outcomes = [live.catch((error: Error) => error.message), final.catch((error: Error) => error.message)];
    await vi.advanceTimersByTimeAsync(20_000);
    expect(await outcomes[0]).toContain("The speech engine took too long to answer.");
    // The final text gets longer: 45 seconds plus two per second of speech.
    let settled = false;
    void outcomes[1].then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(44_000);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(21_000);
    expect(await outcomes[1]).toContain("The speech engine took too long to answer.");
  });

  it("measures loudness on a scale where quiet speech still moves the bar", () => {
    expect(level(new Float32Array(100))).toBe(0);
    expect(level(new Float32Array(100).fill(1))).toBe(1);
    expect(level(new Float32Array(100).fill(0.03))).toBeGreaterThan(0.4);
  });
});

describe("dictation settings", () => {
  const renderSettings = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><DictationSettings /></QueryClientProvider>);

  it("picks a microphone and its sound clean-up, and remembers them", async () => {
    setup({ devices: [mic("usb", "USB headset"), mic("cam", "")] });
    renderSettings();
    const picker = await screen.findByLabelText("Microphone");
    expect(await screen.findByRole("option", { name: "USB headset" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Microphone 2" })).toBeInTheDocument();
    await userEvent.selectOptions(picker, "usb");
    await userEvent.click(screen.getByRole("checkbox", { name: /Reduce background noise/ }));
    expect(JSON.parse(localStorage.getItem("moah.dictationInput")!)).toEqual({ deviceId: "usb", label: "USB headset", noiseSuppression: false, echoCancellation: true, autoGainControl: true });
    // Back to the defaults: nothing is kept.
    await userEvent.selectOptions(picker, "");
    await userEvent.click(screen.getByRole("checkbox", { name: /Reduce background noise/ }));
    expect(localStorage.getItem("moah.dictationInput")).toBeNull();
  });

  it("says when the chosen microphone is not connected", async () => {
    setup({ devices: [mic("cam", "Webcam")] });
    localStorage.setItem("moah.dictationInput", JSON.stringify({ deviceId: "usb", label: "USB headset" }));
    renderSettings();
    expect(await screen.findByText("USB headset is not connected, so the default microphone is used.")).toBeInTheDocument();
    expect(screen.getByLabelText("Microphone")).toHaveValue("");
  });

  it("tests the microphone with a live level bar and says it works", async () => {
    const calls = setup();
    renderSettings();
    await userEvent.click(await screen.findByRole("button", { name: "Test the microphone" }));
    expect(await screen.findByText("Say something. The bar moves while sound comes in.")).toBeInTheDocument();
    const { onLevel } = vi.mocked(startRecording).mock.calls[0][1] as { onLevel: (value: number) => void };
    act(() => onLevel(0.6));
    expect(screen.getByRole("meter", { name: "Microphone level" })).toHaveAttribute("aria-valuenow", "60");
    act(() => onLevel(0.1));
    expect(screen.getByRole("meter", { name: "Microphone level" })).toHaveAttribute("aria-valuenow", "10");
    await userEvent.click(screen.getByRole("button", { name: "Stop the microphone test" }));
    expect(await screen.findByText("The microphone works.")).toBeInTheDocument();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(recorder.cancel).toHaveBeenCalled();
    // Nothing was sent to the speech engine: the test only listens.
    expect(calls.some((call) => call.url.startsWith("/api/dictation/transcribe"))).toBe(false);
  });

  it("says when almost no sound comes in, and when the microphone will not start", async () => {
    setup();
    renderSettings();
    await userEvent.click(await screen.findByRole("button", { name: "Test the microphone" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop the microphone test" }));
    expect(await screen.findByText(/Almost no sound came in/)).toBeInTheDocument();
    recorder.fail = new DOMException("denied", "NotAllowedError");
    await userEvent.click(screen.getByRole("button", { name: "Test the microphone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone access was refused.");
  });

  it("restarts a running test with a newly chosen microphone", async () => {
    setup({ devices: [mic("usb", "USB headset")] });
    renderSettings();
    await userEvent.click(await screen.findByRole("button", { name: "Test the microphone" }));
    await screen.findByRole("button", { name: "Stop the microphone test" });
    await userEvent.selectOptions(screen.getByLabelText("Microphone"), "usb");
    await waitFor(() => expect(vi.mocked(startRecording)).toHaveBeenCalledTimes(2));
    expect((vi.mocked(startRecording).mock.calls[1][1] as { constraints: MediaTrackConstraints }).constraints.deviceId).toEqual({ exact: "usb" });
  });

  it("says why dictation is off", async () => {
    setup({ available: false });
    renderSettings();
    expect(await screen.findByText("Dictation is off: The speech model is not part of this build.")).toBeInTheDocument();
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
