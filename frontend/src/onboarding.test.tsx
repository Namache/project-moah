import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const project = { id: "p1", name: "Trailhead", slug: "trailhead", description: null, icon: null, accent: null, root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };

function setup(existing: unknown[] = []) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input), method = options?.method ?? "GET";
    calls.push({ url, method, body: options?.body ? JSON.parse(String(options.body)) : undefined });
    if (url === "/api/projects" && method === "POST") return Response.json(project, { status: 201 });
    if (url.startsWith("/api/projects?")) return Response.json(existing);
    if (url === "/api/projects/p1") return Response.json(project);
    if (url === "/api/projects/p1/tasks" && method === "POST") return Response.json({ id: "t1", human_id: "TRAI-001", title: "x", status: "todo" }, { status: 201 });
    return Response.json([]);
  }));
  return calls;
}
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("first-run onboarding", () => {
  it("walks through all five steps and ends at the AI setup guide", async () => {
    const calls = setup();
    const user = userEvent.setup();
    renderAt("/");
    expect(await screen.findByRole("heading", { name: /Welcome to Project Moah/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Get started" }));
    await user.type(screen.getByLabelText("Project name"), "Trailhead");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Connect a repository" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Skip for now" }));
    await user.type(await screen.findByLabelText("Task title"), "Implement save migration");
    await user.click(screen.getByRole("button", { name: "Create task" }));
    expect(await screen.findByRole("heading", { name: "Connect an AI" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Set up Claude" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Connect Claude Code" })).toBeInTheDocument();
    expect(calls.find((c) => c.url === "/api/projects" && c.method === "POST")?.body).toMatchObject({ name: "Trailhead" });
    expect(calls.find((c) => c.url === "/api/projects/p1/tasks" && c.method === "POST")?.body).toMatchObject({ title: "Implement save migration" });
    expect(localStorage.getItem("pb-onboarding-done")).toBe("1");
  });

  it("can be skipped at any step, and then stays out of the way", async () => {
    setup();
    const user = userEvent.setup();
    renderAt("/");
    await user.click(await screen.findByRole("button", { name: "Skip setup" }));
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();
    cleanup();
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "No active projects yet" })).toBeInTheDocument();
  });

  it("is not shown when projects already exist, but the tour can be reopened", async () => {
    setup([project]);
    renderAt("/");
    expect(await screen.findByRole("heading", { name: /^Good (morning|afternoon|evening|night)$/ })).toBeInTheDocument();
    cleanup();
    renderAt("/?tour=1");
    expect(await screen.findByRole("heading", { name: /Welcome to Project Moah/ })).toBeInTheDocument();
  });

  it("shows a getting-started checklist on a new project that can be dismissed for good", async () => {
    setup([project]);
    const user = userEvent.setup();
    renderAt("/projects/p1");
    expect(await screen.findByRole("heading", { name: "Getting started" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect repository" })).toBeInTheDocument();
    expect(screen.getByText("1 of 6 done")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("heading", { name: "Getting started" })).not.toBeInTheDocument();
    cleanup();
    renderAt("/projects/p1");
    await screen.findByRole("heading", { name: "Nothing in focus yet" });
    expect(screen.queryByRole("heading", { name: "Getting started" })).not.toBeInTheDocument();
  });
});
