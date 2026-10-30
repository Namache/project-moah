import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const project = { id: "p1", name: "Trailhead", slug: "c", description: null, icon: null, accent: null, root_path: "/repo", status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };
const okGit = { state: "ok", message: "ok", root_path: "/repo", branch: "main", detached: false, head: "abcdef123456", head_subject: "Initial", clean: false, changed: [{ path: "src/new.gd", status: "untracked" }], changed_total: 1, warnings: [] };
const notes = { id: "f1", project_id: "p1", path: "src/camp.gd", language: "gdscript", purpose: "Owns capacity", summary: null, last_seen_hash: "x", stale: true, symbols: [{ id: "s1", name: "CampManager", kind: "class", summary: null }], tasks: [], memories: [], checkpoints: [] };
const entries = [{ path: "src/camp.gd", file_id: "f1", has_notes: true, stale: true, changed: null }, { path: "src/new.gd", file_id: null, has_notes: false, stale: null, changed: "untracked" }, { path: "README.md", file_id: null, has_notes: false, stale: null, changed: null }];
const commit = { sha: "a".repeat(40), short_sha: "aaaaaaaa", subject: "CAMP-001 add capacity", author: "Ada", committed_at: "2026-01-02T00:00:00Z", files: [], tasks: [{ task: { id: "t1", human_id: "CAMP-001", title: "Camp", status: "todo" }, status: "suggested", origin: "commit message" }], in_repository: true };

function setup(git = okGit, treeEntries = entries, current = project) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input), method = options?.method ?? "GET";
    calls.push({ url, method, body: options?.body ? JSON.parse(String(options.body)) : undefined });
    if (url.startsWith("/api/projects?")) return Response.json([current]);
    if (url === "/api/projects/p1") return Response.json(current);
    if (url === "/api/projects/p1/files/tree") return Response.json({ git, entries: treeEntries, truncated: false, source: "git" });
    if (url === "/api/projects/p1/files/f1") return Response.json(notes);
    if (url === "/api/projects/p1/files/f1/git") return Response.json({ git, commits: [commit] });
    if (url === "/api/projects/p1/files" && method === "POST") return Response.json({ ...notes, id: "f2", path: "README.md", stale: null }, { status: 201 });
    if (url === "/api/projects/p1/git/commits") return Response.json({ git, commits: [commit] });
    if (url.includes("/git/commits/") && method === "POST") return Response.json(commit, { status: 201 });
    return Response.json([]);
  }));
  return calls;
}
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("files and git", () => {
  it("shows Git status, flags files with notes, changes and stale notes, and opens details", async () => {
    setup();
    renderAt("/projects/p1/files");
    expect(await screen.findByText("main")).toBeInTheDocument();
    expect(screen.getByText("1 changed file")).toBeInTheDocument();
    const tree = screen.getByRole("list", { name: "Repository files" });
    expect(within(tree).getByRole("button", { name: /camp\.gd/ })).toHaveTextContent("Changed since review");
    expect(within(tree).getByRole("button", { name: /new\.gd/ })).toHaveTextContent("untracked");
  });

  it("opens a file from the link, shows its notes and warns when it changed", async () => {
    setup();
    renderAt("/projects/p1/files?file=src/camp.gd");
    expect(await screen.findByRole("heading", { name: "src/camp.gd" })).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Owns capacity")).toBeInTheDocument();
    expect(screen.getByText("CampManager")).toBeInTheDocument();
    expect(screen.getByText(/changed since these notes were last reviewed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Notes are still correct/ })).toBeInTheDocument();
  });

  it("adds notes for a file that has none", async () => {
    const calls = setup();
    const user = userEvent.setup();
    renderAt("/projects/p1/files?file=README.md");
    await user.click(await screen.findByRole("button", { name: /Add notes/ }));
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/p1/files" && (c.body as { path: string }).path === "README.md")).toBe(true);
  });

  it("explains an unavailable repository without breaking the page", async () => {
    setup({ ...okGit, state: "git_missing", message: "Git is not available to Project Moah, so repository details can't be shown.", changed: [] } as typeof okGit, entries.slice(0, 1));
    renderAt("/projects/p1/files");
    expect(await screen.findByText("Repository details are not available.")).toBeInTheDocument();
    expect(screen.getByText(/Tasks, memory, and your file notes keep working normally/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Repository files" })).toBeInTheDocument();
  });

  it("explains a folder the sandbox cannot see and shows the read-only share command", async () => {
    setup({ ...okGit, state: "not_shared", message: "Project Moah runs in a sandbox and can only see folders you share with it.", root_path: "/home/you/Desktop/my project", changed: [] } as typeof okGit, entries.slice(0, 1));
    renderAt("/projects/p1/files");
    expect(await screen.findByText("Repository details are not available.")).toBeInTheDocument();
    expect(screen.getByText("flatpak override --user --filesystem='/home/you/Desktop/my project:ro' io.github.projectbrain.ProjectBrain")).toBeInTheDocument();
    expect(screen.getByText(/can never be changed|cannot change it/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "More about containers" })).toHaveAttribute("href", "/help/troubleshooting-container");
  });

  it("confirms a suggested task link for a commit", async () => {
    const calls = setup();
    const user = userEvent.setup();
    renderAt("/projects/p1/files");
    await user.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith(`/git/commits/${"a".repeat(40)}/tasks`) && (c.body as { task: string }).task === "CAMP-001")).toBe(true);
  });

  it("keeps an archived project's file notes read-only, including from the keyboard", async () => {
    const user = userEvent.setup();
    const calls = setup(okGit, entries, { ...project, status: "archived" });
    renderAt("/projects/p1/files?file=src/camp.gd");
    const purpose = await screen.findByRole("textbox", { name: "Purpose" });
    expect(purpose).toHaveAttribute("readonly");
    await user.click(purpose);
    await user.type(purpose, " more");
    await user.tab();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });
});
