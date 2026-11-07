import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { LanguageRoot, setLanguage } from "./lib/i18n";
import { diagnosticReport } from "./pages/SettingsPage";
import { initDisplay, setDisplay } from "./lib/display";

const diag = { app_version: "0.1.0", python: "3.13.1", platform: "Linux", sqlite_version: "3.51.2", database: { path: "/home/u/.var/app/x/data/project-brain/project-brain.db", size_bytes: 204800, migration: "0007_proposals", integrity: "ok", foreign_key_problems: 0, search_index_ready: true }, counts: { projects: 2, tasks: 5, pending_proposals: 1 }, git: { available: false, version: null }, mcp: { command: "project-brain-mcp", tools: 15 } };
const agentSettings = { default_agent: "claude", second_opinion_enabled: false, codex_command: "codex", claude_command: "claude", update_check_enabled: true, explore_packs: false };
const taskSettings = { auto_delete_done: false, auto_delete_done_since: null };
const respond = (u: string) => Response.json(u === "/api/system/diagnostics" ? diag : u === "/api/settings/agents" ? agentSettings : u === "/api/settings/tasks" ? taskSettings : []);
const renderAt = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/settings"]}><LanguageRoot><App /></LanguageRoot></MemoryRouter></QueryClientProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setLanguage("system"); });

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
    const size = await screen.findByRole("group", { name: /Interface size/ });
    expect(within(size).getByRole("radio", { name: "Automatic" })).toBeChecked();
    await user.click(within(size).getByRole("radio", { name: "125%" }));
    expect(document.documentElement.style.zoom).toBe("1.25");
    expect(localStorage.getItem("pb-zoom")).toBe("1.25");
    const text = screen.getByRole("group", { name: /Text size/ });
    await user.click(within(text).getByRole("radio", { name: "130%" }));
    expect(document.documentElement.style.getPropertyValue("--text-scale")).toBe("1.3");
    expect(localStorage.getItem("pb-text-size")).toBe("1.3");
    await user.click(within(size).getByRole("radio", { name: "Automatic" }));
    await user.click(within(text).getByRole("radio", { name: "Standard" }));
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
    const size = await screen.findByRole("group", { name: /Interface size/ });
    expect(within(size).getByRole("radio", { name: "Automatic (125%)" })).toBeChecked();
    expect(screen.getByText(/Ctrl\+0 goes back to Automatic/)).toBeInTheDocument();
    await user.click(within(size).getByRole("radio", { name: "150%" }));
    expect(saveDisplay).toHaveBeenLastCalledWith({ zoom: 1.5, text: 1 });
    // The window is zoomed by the app, not by CSS.
    expect(document.documentElement.style.zoom).toBe("");
    // Ctrl+Minus in the app moves the setting too.
    await act(async () => listener?.({ zoom: 1.25, text: 1, auto: 1.25, zoomInUse: 1.25 }));
    expect(within(size).getByRole("radio", { name: "125%" })).toBeChecked();
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
    await user.click(within(await screen.findByRole("group", { name: "Language" })).getByRole("radio", { name: "Русский" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Настройки" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("ru");
    expect(localStorage.getItem("pb-language")).toBe("ru");
    expect(screen.getByRole("link", { name: /Справка/ })).toBeInTheDocument();
    await user.click(within(screen.getByRole("group", { name: "Язык" })).getByRole("radio", { name: "Система" }));
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
});
