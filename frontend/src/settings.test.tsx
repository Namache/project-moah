import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { LanguageRoot, setLanguage } from "./lib/i18n";
import { diagnosticReport } from "./pages/SettingsPage";

const diag = { app_version: "0.1.0", python: "3.13.1", platform: "Linux", sqlite_version: "3.51.2", database: { path: "/home/u/.var/app/x/data/project-brain/project-brain.db", size_bytes: 204800, migration: "0007_proposals", integrity: "ok", foreign_key_problems: 0, search_index_ready: true }, counts: { projects: 2, tasks: 5, pending_proposals: 1 }, git: { available: false, version: null }, mcp: { command: "project-brain-mcp", tools: 15 } };
const agentSettings = { default_agent: "claude", second_opinion_enabled: false, codex_command: "codex", claude_command: "claude" };
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
