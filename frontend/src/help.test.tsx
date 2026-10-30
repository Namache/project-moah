import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { helpArticles, helpByLanguage, parseArticle, russianArticles, searchArticles } from "./lib/help";
import { setLanguage } from "./lib/i18n";
import { INSTALLS, type Install } from "./lib/install";
import { snippetsFor } from "./content/integrations";

const project = { id: "p1", name: "Trailhead", slug: "trailhead", description: null, icon: null, accent: null, root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };
const renderAt = (path: string) => { vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => Response.json(String(u).startsWith("/api/projects?") ? [project] : []))); return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>); };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLanguage("system"); delete (window as { projectBrainDesktop?: unknown }).projectBrainDesktop; });
const articles = helpArticles("flatpak");

describe("help content", () => {
  it("has every required guide and troubleshooting article with problem, causes and fixes", () => {
    const slugs = new Set(articles.map((a) => a.slug));
    for (const slug of ["getting-started", "projects", "tasks", "memory", "context-packs", "handoffs", "codex", "claude", "current-focus", "files-and-git", "search", "review"]) expect(slugs.has(slug), slug).toBe(true);
    const trouble = articles.filter((a) => a.category === "Troubleshooting");
    expect(trouble).toHaveLength(12);
    for (const article of trouble) for (const heading of ["## Problem", "## Likely causes", "## How to fix"]) expect(article.body, article.slug).toContain(heading);
    for (const article of articles) for (const slug of article.related) expect(slugs.has(slug), `${article.slug} -> ${slug}`).toBe(true);
  });

  it("parses metadata and searches by keyword, requiring every word", () => {
    expect(parseArticle("x", "---\ntitle: T\ncategory: C\nkeywords: a, b\nrelated: y\n---\nBody")).toMatchObject({ title: "T", keywords: ["a", "b"], related: ["y"], body: "Body" });
    for (const [word, slug] of [["locked", "memory"], ["codex", "codex"], ["supersede", "memory"], ["dependency", "tasks"], ["git", "files-and-git"], ["handoff", "handoffs"]] as const) expect(searchArticles(word, articles).map((a) => a.slug), word).toContain(slug);
    expect(searchArticles("codex zzzzqq", articles)).toEqual([]);
    expect(searchArticles("   ", articles)).toEqual([]);
  });

  it("has a Russian version of every article with the same links, snippets and sections", () => {
    const shape = (body: string) => ({ links: [...body.matchAll(/\[\[[a-z0-9-]+\]\]|\{\{snippet:\w+\}\}|\{\{only [a-z ]+\}\}|\{\{end\}\}|\]\(\/[^)]*\)/g)].map((m) => m[0]).sort(), sections: body.split("\n").filter((line) => line.startsWith("## ")).length, code: (body.match(/```/g) ?? []).length });
    expect(Object.keys(russianArticles).sort()).toEqual(Object.keys(helpByLanguage.en).sort());
    for (const [slug, english] of Object.entries(helpByLanguage.en)) {
      const russian = russianArticles[slug];
      expect({ category: russian.category, related: russian.related, only: russian.only, ...shape(russian.body) }, slug).toEqual({ category: english.category, related: english.related, only: english.only, ...shape(english.body) });
      expect(russian.title, slug).toMatch(/[а-яё]/i);
    }
    for (const article of Object.values(russianArticles).filter((a) => a.category === "Troubleshooting")) for (const heading of ["## Проблема", "## Вероятные причины", "## Как исправить"]) expect(article.body, article.slug).toContain(heading);
  });

  it("shows each system only its own instructions", () => {
    const foreign: Record<Install, RegExp> = {
      flatpak: /PowerShell|%LOCALAPPDATA%|Git for Windows|apt (install|remove)|project-moah-mcp` command was installed/,
      deb: /flatpak|distrobox|sandbox|PowerShell|%LOCALAPPDATA%|Git for Windows/i,
      linux: /flatpak|distrobox|sandbox|PowerShell|%LOCALAPPDATA%|Git for Windows/i,
      windows: /flatpak|distrobox|sandbox|apt (install|remove)|~\/\.local|~\/\.var/i,
      mac: /flatpak|distrobox|sandbox|PowerShell|%LOCALAPPDATA%|Git for Windows|apt (install|remove)/i,
    };
    for (const install of INSTALLS) {
      const shown = helpArticles(install);
      const slugs = new Set(shown.map((a) => a.slug));
      for (const article of shown) {
        expect(article.body, `${install}: ${article.slug}`).not.toMatch(foreign[install]);
        expect(article.body, `${install}: ${article.slug}`).not.toMatch(/\{\{(only|end)/);
        for (const [, slug] of article.body.matchAll(/\[\[([a-z0-9-]+)\]\]/g)) expect(slugs.has(slug), `${install}: ${article.slug} -> ${slug}`).toBe(true);
      }
    }
    expect(helpArticles("windows").some((a) => a.slug === "troubleshooting-container")).toBe(false);
    expect(helpArticles("flatpak").some((a) => a.slug === "troubleshooting-container")).toBe(true);
  });

  it("never states a token saving it cannot promise", () => {
    expect(articles.find((a) => a.slug === "context-packs")!.body).toMatch(/does not promise a fixed saving/);
  });
});

describe("help pages", () => {
  it("shows help in Russian and searches it in Russian", async () => {
    setLanguage("ru");
    const user = userEvent.setup();
    renderAt("/help");
    expect(screen.getByRole("heading", { name: "Чем помочь?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "С чего начать" })).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Искать в справке" }), "защищённую");
    await user.click(within(screen.getByRole("region", { name: "Результаты поиска" })).getByRole("link", { name: /Память/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Память" })).toBeInTheDocument();
  });

  it("searches from the help home and opens an article with related links", async () => {
    const user = userEvent.setup();
    renderAt("/help");
    await user.type(screen.getByRole("searchbox", { name: "Search help" }), "locked");
    await user.click(within(screen.getByRole("region", { name: "Search results" })).getByRole("link", { name: /Memory/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Memory" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Related articles" })).toBeInTheDocument();
  });

  it("explains an empty search, and sends unknown articles back to help", async () => {
    const user = userEvent.setup();
    renderAt("/help");
    await user.type(screen.getByRole("searchbox", { name: "Search help" }), "qqqqzzzz");
    expect(screen.getByText(/No help matches/)).toBeInTheDocument();
    cleanup();
    renderAt("/help/not-a-real-article");
    expect(await screen.findByRole("heading", { name: "How can we help?" })).toBeInTheDocument();
  });

  it("shows one global setup per agent, with no project to choose", async () => {
    renderAt("/help/codex");
    const section = await screen.findByRole("region", { name: "Setup commands for Codex" });
    const add = await within(section).findByText(/codex mcp add project-moah -- flatpak run --command=project-moah-mcp io.github.projectbrain.ProjectBrain --agent codex/);
    expect(add.textContent).not.toContain("--project");
    expect(within(section).getByText(/\[mcp_servers.project-moah\]/)).toBeInTheDocument();
    expect(within(section).getByText(/brain_brief/)).toBeInTheDocument();
    expect(within(section).queryByRole("combobox")).toBeNull();
  });

  it("does not render HTML from help text", () => {
    renderAt("/help/getting-started");
    expect(document.querySelector("script")).toBeNull();
    const { setup } = snippetsFor("claude");
    expect(setup[0].text).toContain("--scope user");
    expect(setup[1].text).toContain("--brief");
  });

  it("shows a Windows user the Windows setup, never the Flatpak one", async () => {
    (window as { projectBrainDesktop?: unknown }).projectBrainDesktop = { apiToken: "", install: "windows" };
    const exe = "C:\\Users\\me\\AppData\\Local\\Programs\\Project Moah\\resources\\bin\\project-brain-backend.exe";
    vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => Response.json(String(u).endsWith("/api/system/agent-command") ? { install: "windows", command: [exe, "--mcp"] } : String(u).startsWith("/api/projects?") ? [project] : [])));
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/help/claude"]}><App /></MemoryRouter></QueryClientProvider>);
    const section = await screen.findByRole("region", { name: "Setup commands for Claude Code" });
    expect(within(section).getByText(new RegExp(`claude mcp add .* -- "${exe.replace(/\\/g, "\\\\")}" --mcp --agent claude`))).toBeInTheDocument();
    expect(screen.getByText(/Run these commands in PowerShell/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/flatpak|distrobox/i);
  });

  it("gives commands that match how the app was installed", () => {
    const exe = "C:\\Users\\me\\AppData\\Local\\Programs\\Project Moah\\resources\\bin\\project-brain-backend.exe";
    const windows = snippetsFor("claude", { install: "windows", command: [exe, "--mcp"] });
    expect(windows.setup[0].text).toBe(`claude mcp add --transport stdio --scope user project-moah -- "${exe}" --mcp --agent claude`);
    expect(JSON.parse(windows.setup[1].text).hooks.SessionStart[0].hooks[0].command).toBe(`"${exe}" --mcp --brief --cwd "$CLAUDE_PROJECT_DIR"`);
    const toml = snippetsFor("codex", { install: "windows", command: [exe, "--mcp"] }).setup[1].text;
    expect(toml).toContain(`command = ${JSON.stringify(exe)}`);
    expect(toml).toContain('args = ["--mcp", "--agent", "codex"]');
    const deb = snippetsFor("codex", { install: "deb", command: ["project-moah-mcp"] });
    expect(deb.setup[0].text).toBe("codex mcp add project-moah -- project-moah-mcp --agent codex");
    expect(snippetsFor("claude", { install: "deb", command: ["project-moah-mcp"] }).setup[1].text).toContain('project-moah-mcp --brief --cwd \\"$CLAUDE_PROJECT_DIR\\"');
  });
});
