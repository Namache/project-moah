import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DictationButton } from "./components/dictation/DictationButton";
import { downsample, insertDictation, wavBytes } from "./lib/recorder";

const recorder = vi.hoisted(() => ({ stop: vi.fn(), cancel: vi.fn(), fail: null as DOMException | null }));
vi.mock("./lib/recorder", async (original) => ({
  ...(await original<typeof import("./lib/recorder")>()),
  startRecording: vi.fn(async () => { if (recorder.fail) throw recorder.fail; return { stop: recorder.stop, cancel: recorder.cancel }; }),
}));

function Field({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <><textarea id="details" aria-label="Details" value={value} onChange={(event) => setValue(event.target.value)} /><DictationButton field="Details" target={() => document.getElementById("details") as HTMLTextAreaElement} value={value} onChange={setValue} /></>;
}

function setup({ available = true, text = "The save migration needs a test." } = {}) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input), method = options?.method ?? "GET";
    calls.push({ url, method, body: options?.body });
    if (url === "/api/dictation/status") return Response.json({ available, reason: available ? null : "The speech model is not part of this build." });
    if (url.startsWith("/api/dictation/transcribe")) return Response.json({ text });
    return Response.json([]);
  }));
  recorder.stop.mockResolvedValue(new Blob(["wav"], { type: "audio/wav" }));
  return calls;
}

const renderField = (initial?: string) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Field initial={initial} /></QueryClientProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); recorder.fail = null; vi.clearAllMocks(); });

describe("dictation", () => {
  it("records, sends the clip to the local service only, and puts the words where the cursor was", async () => {
    const calls = setup();
    renderField("Old saves load. Then ship.");
    const field = screen.getByRole("textbox", { name: "Details" }) as HTMLTextAreaElement;
    field.focus();
    field.setSelectionRange(16, 16);
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    expect(await screen.findByRole("button", { name: "Stop dictating into Details" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Stop dictating into Details" }));
    await waitFor(() => expect(field).toHaveValue("Old saves load. The save migration needs a test. Then ship."));
    expect(calls.every((call) => call.url.startsWith("/api/"))).toBe(true);
    expect(calls.find((call) => call.url.startsWith("/api/dictation/transcribe"))).toMatchObject({ url: "/api/dictation/transcribe?language=auto", method: "POST" });
  });

  it("listens for the language chosen in Settings", async () => {
    const calls = setup({ text: "Окно возвращения" });
    localStorage.setItem("moah.dictationLanguage", "ru");
    renderField();
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop dictating into Details" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Details" })).toHaveValue("Окно возвращения"));
    expect(calls.some((call) => call.url === "/api/dictation/transcribe?language=ru")).toBe(true);
    localStorage.removeItem("moah.dictationLanguage");
  });

  it("shows no microphone when the build has no speech model", async () => {
    const calls = setup({ available: false });
    renderField();
    await waitFor(() => expect(calls.some((call) => call.url === "/api/dictation/status")).toBe(true));
    expect(screen.queryByRole("button", { name: "Dictate into Details" })).not.toBeInTheDocument();
  });

  it("says when the microphone is refused or nothing was heard", async () => {
    setup({ text: "" });
    renderField();
    recorder.fail = new DOMException("denied", "NotAllowedError");
    await userEvent.click(await screen.findByRole("button", { name: "Dictate into Details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone access was refused.");
    recorder.fail = null;
    await userEvent.click(screen.getByRole("button", { name: "Dictate into Details" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop dictating into Details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No speech was heard.");
    expect(screen.getByRole("textbox", { name: "Details" })).toHaveValue("");
  });
});

describe("recording helpers", () => {
  it("adds spaces only where words would touch", () => {
    expect(insertDictation("", "Hello")).toEqual({ value: "Hello", cursor: 5 });
    expect(insertDictation("Ship it.", "Then test", 8)).toEqual({ value: "Ship it. Then test", cursor: 18 });
    expect(insertDictation("ab", "X", 1)).toEqual({ value: "a X b", cursor: 3 });
    expect(insertDictation("keep replace keep", "new", 5, 12)).toEqual({ value: "keep new keep", cursor: 8 });
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
