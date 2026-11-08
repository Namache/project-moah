import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { LanguageRoot, setLanguage } from "./lib/i18n";
import { diagnosticReport, errorLogText } from "./pages/SettingsPage";
import { DIAGNOSTICS_TIMEOUT_MS, systemApi } from "./api/system";
import { initDisplay, setDisplay } from "./lib/display";

const diag = { app_version: "0.1.0", python: "3.13.1", platform: "Linux", sqlite_version: "3.51.2", database: { path: "/home/u/.var/app/x/data/project-brain/project-brain.db", size_bytes: 204800, migration: "0007_proposals", integrity: "ok", foreign_key_problems: 0, search_index_ready: true }, counts: { projects: 2, tasks: 5, pending_proposals: 1 }, git: { available: false, version: null }, mcp: { command: "project-brain-mcp", tools: 15 } };
const agentSettings = { default_agent: "claude", second_opinion_enabled: false, codex_command: "codex", claude_command: "claude", update_check_enabled: true, explore_packs: false };
const taskSettings = { auto_delete_done: false, auto_delete_done_since: null };
const errorLog = { total: 2, entries: [
  { time: "2026-11-07T04:00:00+00:00", source: "mcp", level: "error", message: "brain_context_pack: KeyError: 'shelf'", detail: "Traceback (most recent call last):\n  File \"~/moah/app/mcp/server.py\", line 182" },
  { time: "2026-11-06T22:10:00+00:00", source: "desktop", level: "warning", message: "Could not open the agent's app: no handler for codex://", detail: "" },
] };
let errorsNow: typeof errorLog = { total: 0, entries: [] };
const respond = (u: string) => Response.json(u === "/api/system/diagnostics" ? diag : u === "/api/settings/agents" ? agentSettings : u === "/api/settings/tasks" ? taskSettings : u === "/api/system/errors" ? errorsNow : []);
const renderAt = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/settings"]}><LanguageRoot><App /></LanguageRoot></MemoryRouter></QueryClientProvider>);
afterEach(() => { errorsNow = { total: 0, entries: [] }; cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setLanguage("system"); });

describe("settings", () => {
  it("switches the theme, remembers it, and goes back to following the system", async () => {
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => respond(String(u))));
    const user = userEvent.setup();
    renderAt();
    const picker = await screen.findByRole("group", { name: /Theme/ });
    expect(within(picker).getByRole("radio", { name: "System" })).toBeChecked();
    await user.click(within(picker).getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("pb-theme")).toBe("dark");
    await user.click(within(picker).getByRole("radio", { name: "System" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("pb-theme")).toBeNull();
  });

  it("enlarges the interface and the text in a browser tab, and remembers both", async () => {
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => respond(String(u))));
    const user = userEvent.setup();
    renderAt();
    const size = await screen.findByRole("combobox", { name: "Interface size" });
    expect(size).toHaveDisplayValue("Automatic");
    await user.selectOptions(size, "125%");
    expect(document.documentElement.style.zoom).toBe("1.25");
    expect(localStorage.getItem("pb-zoom")).toBe("1.25");
    const text = screen.getByRole("combobox", { name: "Text size" });
    await user.selectOptions(text, "130%");
    expect(document.documentElement.style.getPropertyValue("--text-scale")).toBe("1.3");
    expect(localStorage.getItem("pb-text-size")).toBe("1.3");
    await user.selectOptions(size, "Automatic");
    await user.selectOptions(text, "Standard");
    expect(document.documentElement.style.zoom).toBe("");
    expect(localStorage.getItem("pb-zoom")).toBeNull();
    expect(localStorage.getItem("pb-text-size")).toBeNull();
  });

  it("in the desktop app, shows the size Automatic picked for the screen and lets the app save and zoom", async () => {
    let listener: ((state: DesktopDisplay) => void) | undefined;
    const saveDisplay = vi.fn(async (prefs: { zoom: number | "auto"; text: number }) => ({ ...prefs, auto: 1.25, zoomInUse: prefs.zoom === "auto" ? 1.25 : prefs.zoom }));
    vi.stubGlobal("projectBrainDesktop", { apiToken: "t", display: { zoom: "auto", text: 1, auto: 1.25, zoomInUse: 1.25 }, setDisplay: saveDisplay, onDisplayChange: (fn: (state: DesktopDisplay) => void) => { listener = fn; return () => {}; } });
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => respond(String(u))));
    initDisplay();
    const user = userEvent.setup();
    renderAt();
    const size = await screen.findByRole("combobox", { name: "Interface size" });
    expect(size).toHaveDisplayValue("Automatic (125%)");
    expect(screen.queryByText(/Ctrl\+0 goes back to Automatic/)).toBeNull(); // explained under "?"
    await user.click(screen.getByRole("button", { name: "Help: Interface size" }));
    expect(screen.getByText(/Ctrl\+0 goes back to Automatic/)).toBeInTheDocument();
    await user.selectOptions(size, "150%");
    expect(saveDisplay).toHaveBeenLastCalledWith({ zoom: 1.5, text: 1 });
    // The window is zoomed by the app, not by CSS.
    expect(document.documentElement.style.zoom).toBe("");
    // Ctrl+Minus in the app moves the setting too.
    await act(async () => listener?.({ zoom: 1.25, text: 1, auto: 1.25, zoomInUse: 1.25 }));
    expect(size).toHaveDisplayValue("125%");
    vi.unstubAllGlobals();
    await setDisplay({ zoom: "auto", text: 1 });
  });

  it("shows where data lives, health, Git availability, and a report without project content", async () => {
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => respond(String(u))));
    renderAt();
    expect((await screen.findAllByText("Healthy")).length).toBeGreaterThan(0);
    expect(screen.getByText(/project-brain\.db/)).toBeInTheDocument();
    expect(screen.getByText(/Not available to Project Moah/)).toBeInTheDocument();
    const report = diagnosticReport(diag);
    expect(report).toContain("Migration: 0007_proposals");
    expect(report).toContain("Records: projects 2, tasks 5, pending proposals 1");
    expect(report).not.toContain("Dictation");
  });

  it("puts how dictation did into the report and the card, with times and never words", async () => {
    const dictation = { available: true, reason: null, engine: { loaded: true, load_seconds: 0.4, last_seconds: 1.2, last_audio_seconds: 3.4, last_finished: "2026-11-07T08:00:00+00:00", last_error: "The speech engine is still busy with an earlier recording. Wait a moment, or restart Project Moah if this keeps happening.", last_error_at: "2026-11-07T08:10:00+00:00", busy_since: null, threads: 7 } };
    expect(diagnosticReport({ ...diag, dictation })).toContain("Dictation: ready, engine loaded in 0.4 s, 7 threads, last text 1.2 s for 3.4 s of audio at 2026-11-07T08:00:00+00:00, last error at 2026-11-07T08:10:00+00:00: The speech engine is still busy");
    expect(diagnosticReport({ ...diag, dictation: { available: false, reason: "The speech model is not part of this build." } })).toContain("Dictation: off (The speech model is not part of this build.)");
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => String(u) === "/api/system/diagnostics" ? Response.json({ ...diag, dictation }) : respond(String(u))));
    renderAt();
    expect(await screen.findByText(/^Works\. Last problem: The speech engine is still busy/)).toBeInTheDocument();
  });

  it("creates a backup with the app's credentials and says what it made", async () => {
    const fetchMock = vi.fn(async (u: RequestInfo | URL) => String(u) === "/api/system/export"
      ? new Response("DB", { headers: { "content-disposition": 'attachment; filename="project-moah-backup-20261010.db"' } })
      : respond(String(u)));
    vi.stubGlobal("fetch", fetchMock);
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    renderAt();
    await user.click(await screen.findByRole("button", { name: "Export Project Moah backup" }));
    expect(await screen.findByText(/Backup created: project-moah-backup-20261010\.db/)).toBeInTheDocument();
    expect(click).toHaveBeenCalledOnce();
  });

  it("points each agent to its setup guide", async () => {
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => respond(String(u))));
    renderAt();
    expect(await screen.findByRole("link", { name: /Claude Code.*Setup guide/ })).toHaveAttribute("href", "/help/claude");
    expect(screen.getByRole("link", { name: /Codex.*Setup guide/ })).toHaveAttribute("href", "/help/codex");
  });

  it("switches the whole app to Russian and back", async () => {
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => respond(String(u))));
    const user = userEvent.setup();
    renderAt();
    await user.selectOptions(await screen.findByRole("combobox", { name: "Language" }), "Русский");
    expect(await screen.findByRole("heading", { level: 1, name: "Настройки" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("ru");
    expect(localStorage.getItem("pb-language")).toBe("ru");
    expect(screen.getByRole("link", { name: /Справка/ })).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Язык" }), "Система");
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(localStorage.getItem("pb-language")).toBeNull();
  });

  it("turns on deleting completed tasks after two weeks and says when the first can go", async () => {
    const since = new Date().toISOString();
    const fetchMock = vi.fn(async (u: RequestInfo | URL, init?: RequestInit) => init?.method === "PATCH" ? Response.json({ auto_delete_done: true, auto_delete_done_since: since }) : respond(String(u)));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAt();
    const toggle = await screen.findByRole("checkbox", { name: /Delete completed tasks after two weeks/ });
    expect(toggle).not.toBeChecked();
    await user.click(toggle);
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/tasks", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ auto_delete_done: true }) }));
    expect(await screen.findByText(/nothing is deleted before/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Delete completed tasks after two weeks/ })).toBeChecked();
  });

  it("shows the error log beside the diagnostic report, copies it, and clears it", async () => {
    errorsNow = errorLog;
    const fetchMock = vi.fn(async (u: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE") { errorsNow = { total: 0, entries: [] }; return new Response(null, { status: 204 }); }
      return respond(String(u));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    renderAt();
    const list = await screen.findByRole("list", { name: "Error log" });
    expect(within(list).getByText(/KeyError: 'shelf'/)).toBeInTheDocument();
    expect(within(list).getByText("MCP server")).toBeInTheDocument();
    expect(within(list).getByText("Desktop app")).toBeInTheDocument();
    expect(screen.queryByText(/older build/)).toBeNull();
    expect(screen.queryByText(/The report lists counts/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Copy error log" }));
    const copied = writeText.mock.calls.at(-1)?.[0] as string;
    expect(copied).toContain("2026-11-07T04:00:00+00:00 [MCP server] error: brain_context_pack: KeyError: 'shelf'");
    expect(copied).toContain("    Traceback");
    await user.click(screen.getByRole("button", { name: "Copy diagnostic report" }));
    expect(writeText.mock.calls.at(-1)?.[0]).toContain("Migration: 0007_proposals");
    await user.click(screen.getByRole("button", { name: "Clear log" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Clear log" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/system/errors", expect.objectContaining({ method: "DELETE" }));
    expect(await screen.findByText("No errors so far.")).toBeInTheDocument();
  });

  it("gives up on a diagnostics check that never answers, with a clear message", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_u: RequestInfo | URL, options?: RequestInit) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    const outcome = systemApi.diagnostics().catch((error: Error) => error.message);
    await vi.advanceTimersByTimeAsync(DIAGNOSTICS_TIMEOUT_MS);
    expect(await outcome).toBe("The check took too long. Try again, or restart Project Moah if it keeps happening.");
    // Leaving the page cancels the check without that message.
    const page = new AbortController();
    const left = systemApi.diagnostics(page.signal).catch((error: Error) => error.name);
    page.abort();
    expect(await left).toBe("AbortError");
    vi.useRealTimers();
  });

  it("writes the copied error log in English, with a note when only the newest are shown", () => {
    setLanguage("ru");
    const text = errorLogText({ ...errorLog, total: 250 } as Parameters<typeof errorLogText>[0], "0.2.0");
    expect(text.split("\n")[0]).toBe("Project Moah 0.2.0 error log: 250 entries, newest first (showing 2)");
    expect(text).toContain("[desktop app] warning: Could not open the agent's app");
  });

  it("keeps explanations under ? buttons and the agent commands folded away", async () => {
    agentSettings.second_opinion_enabled = true;
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => respond(String(u))));
    const user = userEvent.setup();
    try {
      renderAt();
      expect(await screen.findByRole("heading", { name: "Connect agents" })).toBeInTheDocument();
      expect(screen.queryByText(/opens this agent with a prompt/)).toBeNull();
      await user.click(await screen.findByRole("button", { name: "Help: default agent" }));
      expect(screen.getByText(/opens this agent with a prompt/)).toBeInTheDocument();
      const commands = screen.getByText("Agent commands").closest("details")!;
      expect(commands).not.toHaveAttribute("open");
      expect(within(commands).getByLabelText("Command for Codex")).toHaveValue("codex");
    } finally {
      agentSettings.second_opinion_enabled = false;
    }
  });
});
