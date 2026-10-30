import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Project } from "./types/project";
import type { TaskDetail, WorkspaceTask } from "./types/task";

const project: Project = { id: "p1", name: "Trailhead", slug: "trailhead", description: null, icon: "⛰️", accent: "#D99A53", root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };

function task(over: Partial<TaskDetail> = {}): TaskDetail {
  return { id: "t1", project_id: "p1", milestone_id: null, human_id: "CAMP-001", title: "Camp Population Capacity", status: "in_progress", priority: "high", next_action: "Add save migration", sort_order: 0, criteria_total: 2, criteria_completed: 1, tags: ["gameplay"], is_focus: false, is_blocked_by_open_dependency: false, description: null, acceptance_criteria: [{ id: "c1", description: "Track capacity", is_completed: true, sort_order: 0 }, { id: "c2", description: "Migrate old saves", is_completed: false, sort_order: 1 }], relationships: [], milestone: null, ...over };
}

function mockApi(currentProject: Project = project) {
  const tasks = [task()];
  const calls: { url: string; method: string; body?: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input);
    const method = options?.method ?? "GET";
    const body = options?.body ? JSON.parse(String(options.body)) : undefined;
    calls.push({ url, method, body });
    if (url === "/api/projects?include_archived=true") return Response.json([currentProject]);
    if (url === "/api/projects/p1") return Response.json(currentProject);
    if (url === "/api/projects/p1/tasks" && method === "GET") return Response.json(tasks.filter((t) => t.status !== "archived"));
    if (url === "/api/projects/p1/tasks?status=archived" && method === "GET") return Response.json(tasks.filter((t) => t.status === "archived"));
    if (url === "/api/projects/p1/tasks" && method === "POST") {
      const created = task({ id: "t2", human_id: "CAMP-002", title: body.title, status: "todo", priority: "normal", criteria_total: 0, criteria_completed: 0, tags: [], acceptance_criteria: [] });
      tasks.push(created);
      return Response.json(created, { status: 201 });
    }
    if (url === "/api/projects/p1/milestones" || url === "/api/projects/p1/milestones?include_archived=true") return Response.json([]);
    const one = url.match(/^\/api\/projects\/p1\/tasks\/([^/]+)$/);
    if (one && method === "GET") {
      const found = tasks.find((t) => t.id === one[1] || t.human_id === one[1]);
      return found ? Response.json(found) : Response.json({ detail: "Task not found" }, { status: 404 });
    }
    if (one && method === "PATCH") {
      const found = tasks.find((t) => t.id === one[1] || t.human_id === one[1]);
      if (!found) return Response.json({ detail: "Task not found" }, { status: 404 });
      Object.assign(found, body);
      return Response.json(found);
    }
    if (one && method === "DELETE") {
      tasks.splice(tasks.findIndex((t) => t.id === one[1]), 1);
      return new Response(null, { status: 204 });
    }
    if (url === "/api/projects/p1/tasks/t1/criteria/c2" && method === "PATCH") {
      if ("is_completed" in body) tasks[0].acceptance_criteria[1].is_completed = body.is_completed;
      if ("sort_order" in body) {
        tasks[0].acceptance_criteria.reverse();
        tasks[0].acceptance_criteria.forEach((criterion, index) => { criterion.sort_order = index; });
      }
      return Response.json(tasks[0]);
    }
    if (url === "/api/tasks?limit=500") {
      const rows: WorkspaceTask[] = [{ ...tasks[0], project_name: "Trailhead", project_icon: "⛰️", project_accent: "#D99A53" }, { ...task({ id: "s1", project_id: "p2", human_id: "CBT-001", title: "Turn Order System" }), project_name: "Starling", project_icon: null, project_accent: null }];
      return Response.json(rows);
    }
    if (url === "/api/workspace/overviews") return Response.json([]);
    return Response.json({ detail: "Unexpected test request" }, { status: 500 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls };
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.show = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("task journeys", () => {
  it("shows tasks in their board column with progress", async () => {
    mockApi();
    renderApp("/projects/p1/tasks");
    const column = await screen.findByRole("region", { name: /^In progress/ });
    expect(within(column).getByText("Camp Population Capacity")).toBeInTheDocument();
    expect(within(column).getByText("1 / 2")).toBeInTheDocument();
    expect(within(column).getByText("High")).toBeInTheDocument();
  });

  it("creates a task from the dialog and opens it", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/tasks");
    await user.click(await screen.findByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText(/^Title/), "Implement save migration");
    await user.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/p1/tasks" && (c.body as { title: string }).title === "Implement save migration")).toBe(true));
    expect(await screen.findByRole("dialog", { name: /CAMP-002/ })).toBeInTheDocument();
  });

  it("checks off an acceptance criterion inside the task panel", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/tasks?task=CAMP-001");
    await user.click(await screen.findByRole("checkbox", { name: "Done: Migrate old saves" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.url.endsWith("/criteria/c2") && (c.body as { is_completed: boolean }).is_completed)).toBe(true));
  });

  it("puts the title back when it is cleared instead of leaving it blank", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/tasks?task=CAMP-001");
    const title = await screen.findByRole("textbox", { name: "Title" });
    await user.clear(title);
    await user.tab();
    expect(title).toHaveValue("Camp Population Capacity");
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("says when an inline field has been saved", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/tasks?task=CAMP-001");
    const next = await screen.findByRole("textbox", { name: "Next action" });
    await user.clear(next);
    await user.type(next, "Write the migration test");
    await user.tab();
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PATCH" && (c.body as { next_action?: string }).next_action === "Write the migration test")).toBe(true);
  });

  it("deletes a task, closes its panel, and does not ask for the deleted task again", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/tasks?task=CAMP-001");
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /CAMP-001/ })).not.toBeInTheDocument());
    const deletedAt = calls.findIndex((c) => c.method === "DELETE");
    expect(deletedAt).toBeGreaterThan(-1);
    expect(calls.slice(deletedAt + 1).some((c) => c.method === "GET" && /\/tasks\/(t1|CAMP-001)$/.test(c.url))).toBe(false);
  });

  it("moves a requirement up and saves its order", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/tasks?task=CAMP-001");
    await user.click(await screen.findByRole("button", { name: "Move requirement up: Migrate old saves" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.url.endsWith("/criteria/c2") && (c.body as { sort_order?: number }).sort_order === 0)).toBe(true));
    await waitFor(() => expect((screen.getAllByLabelText("Requirement")[0] as HTMLInputElement).value).toBe("Migrate old saves"));
  });

  it("reopens and restores a task after archiving and closing its panel", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/tasks?task=CAMP-001");
    const panel = await screen.findByRole("dialog", { name: /CAMP-001/ });
    await user.click(within(panel).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.url.endsWith("/tasks/t1") && (c.body as { status?: string }).status === "archived")).toBe(true));
    await user.click(screen.getByRole("button", { name: "Close task" }));
    await user.click(screen.getByRole("button", { name: "Archived tasks" }));
    const archived = await screen.findByRole("region", { name: "Archived tasks" });
    await user.click(within(archived).getByRole("button", { name: /Camp Population Capacity/ }));
    await user.click(await screen.findByRole("button", { name: "Restore task" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.url.endsWith("/tasks/t1") && (c.body as { status?: string }).status === "todo")).toBe(true));
    await waitFor(() => expect(within(archived).queryByText("Camp Population Capacity")).not.toBeInTheDocument());
    expect(await screen.findByRole("region", { name: /^To do/ })).toHaveTextContent("Camp Population Capacity");
  });

  it("keeps each project's tasks under its own heading on All Tasks", async () => {
    mockApi();
    renderApp("/tasks");
    const climb = await screen.findByRole("region", { name: "Trailhead" });
    expect(within(climb).getByText("Camp Population Capacity")).toBeInTheDocument();
    expect(within(climb).queryByText("Turn Order System")).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Starling" })).getByText("Turn Order System")).toBeInTheDocument();
  });

  it("shows archived project tasks without task editing controls", async () => {
    mockApi({ ...project, status: "archived" });
    renderApp("/projects/p1/tasks?task=CAMP-001");

    const panel = await screen.findByRole("dialog", { name: /CAMP-001/ });
    expect(within(panel).getByText("Restore this project to edit its tasks.")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Title")).toHaveAttribute("readonly");
    expect(within(panel).getByLabelText("Status")).toBeDisabled();
    expect(within(panel).getByRole("checkbox", { name: "Done: Migrate old saves" })).toBeDisabled();
    expect(within(panel).queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move CAMP-001 to another status" })).not.toBeInTheDocument();
  });
});
