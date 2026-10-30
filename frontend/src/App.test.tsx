import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Project } from "./types/project";
import { StrictMode } from "react";

function makeProject(id: string, name: string): Project {
  return {
    id,
    name,
    slug: name.toLowerCase(),
    description: null,
    icon: "📁",
    accent: "#35766d",
    root_path: null,
    status: "active",
    current_focus_task_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_opened_at: null,
    archived_at: null,
  };
}

function mockProjectApi(initial: Project[]) {
  const records = [...initial];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input);
    const method = options?.method ?? "GET";
    if (url === "/api/projects?include_archived=true" && method === "GET") return Response.json(records);
    if (url === "/api/projects" && method === "POST") {
      const inputProject = JSON.parse(String(options?.body)) as { name: string; description: string | null; icon: string; accent: string; root_path: string | null };
      const project = { ...makeProject("new-project", inputProject.name), ...inputProject };
      records.push(project);
      return Response.json(project, { status: 201 });
    }
    const archiveMatch = url.match(/^\/api\/projects\/([^/]+)\/archive$/);
    if (archiveMatch && method === "POST") {
      const project = records.find((item) => item.id === archiveMatch[1]);
      if (!project) return Response.json({ detail: "Project not found" }, { status: 404 });
      project.status = "archived";
      return Response.json(project);
    }
    const projectMatch = url.match(/^\/api\/projects\/([^/]+)$/);
    if (projectMatch) {
      const project = records.find((item) => item.id === projectMatch[1]);
      if (!project) return Response.json({ detail: "Project not found" }, { status: 404 });
      if (method === "PATCH") {
        Object.assign(project, JSON.parse(String(options?.body)));
      }
      return Response.json(project);
    }
    return Response.json({ detail: "Unexpected test request" }, { status: 500 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } });
  return render(<StrictMode><QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider></StrictMode>);
}

beforeEach(() => {
  vi.unstubAllGlobals();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.show = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("project journeys", () => {
  it("creates a project and opens its own overview", async () => {
    const fetchMock = mockProjectApi([]);
    const user = userEvent.setup();
    renderApp("/projects");

    await user.click(screen.getByRole("button", { name: "New project" }));
    expect(screen.getByRole("dialog", { name: "New project" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: /Project name/ }), "Trailhead");
    await user.type(screen.getByRole("textbox", { name: /Description/ }), "A cooperative adventure");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Trailhead" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Nothing in focus yet" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/projects", expect.objectContaining({ method: "POST", body: expect.stringContaining('"name":"Trailhead"') }));
  });

  it("switches between separate project URLs", async () => {
    const fetchMock = mockProjectApi([makeProject("one", "Trailhead"), makeProject("two", "Starling")]);
    const user = userEvent.setup();
    renderApp("/projects/one");

    expect(await screen.findByRole("heading", { level: 1, name: "Trailhead" })).toBeInTheDocument();
    await user.click(within(screen.getByRole("navigation", { name: "Your projects" })).getByRole("link", { name: "Starling" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Starling" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/projects/two", expect.anything());
  });

  it("archives with confirmation and restores from Archived projects", async () => {
    mockProjectApi([makeProject("one", "Trailhead")]);
    const user = userEvent.setup();
    renderApp("/projects");

    await user.click(await screen.findByRole("button", { name: "Actions for Trailhead" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(screen.getByRole("heading", { name: "Archive Trailhead?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Archive project" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Actions for Trailhead" })).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /Archived 1/ }));
    await user.click(await screen.findByRole("button", { name: "Actions for Trailhead" }));
    await user.click(screen.getByRole("menuitem", { name: "Restore" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Actions for Trailhead" })).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Current 1/ }));
    await user.click(await screen.findByRole("button", { name: "Actions for Trailhead" }));
    expect(screen.getByRole("menuitem", { name: "Archive" })).toBeInTheDocument();
  });
});
