import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TasksPage } from "./pages/TasksPage";
import type { Milestone, MilestoneChanges } from "./types/task";

function milestone(id: string, name: string, sortOrder: number): Milestone {
  return { id, project_id: "p1", name, description: null, target_date: null, status: "planned", sort_order: sortOrder, task_count: 2, completed_task_count: 1 };
}

function mockMilestones() {
  let milestones = [milestone("m1", "Prototype", 0), milestone("m2", "Demo", 1), milestone("m3", "Release", 2)];
  const calls: { id: string; changes: MilestoneChanges }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input);
    const method = options?.method ?? "GET";
    if (url === "/api/projects/p1/tasks" && method === "GET") return Response.json([]);
    if (url === "/api/projects/p1/milestones?include_archived=true" && method === "GET") return Response.json(milestones);
    if (url === "/api/projects/p1/milestones" && method === "POST") {
      const body = JSON.parse(String(options?.body)) as { name: string };
      const created = milestone(`m${milestones.length + 1}`, body.name, milestones.length);
      milestones.push(created);
      return Response.json(created, { status: 201 });
    }
    const match = url.match(/^\/api\/projects\/p1\/milestones\/(m\d+)$/);
    if (match && method === "PATCH") {
      const changes = JSON.parse(String(options?.body)) as MilestoneChanges;
      const item = milestones.find((m) => m.id === match[1]);
      if (!item) return Response.json({ detail: "Not found" }, { status: 404 });
      calls.push({ id: item.id, changes });
      if (changes.sort_order !== undefined) {
        milestones = milestones.filter((m) => m.id !== item.id);
        milestones.splice(Math.min(changes.sort_order, milestones.length), 0, item);
        milestones.forEach((m, index) => { m.sort_order = index; });
      }
      Object.assign(item, changes);
      return Response.json(item);
    }
    return Response.json({ detail: `Unexpected request: ${method} ${url}` }, { status: 500 });
  }));
  return { calls };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/p1/tasks"]}><TasksPage projectId="p1" archived={false} /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("milestone management", () => {
  it("edits the name, description, date, and status", async () => {
    const { calls } = mockMilestones();
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Manage milestones" }));
    await user.click(await screen.findByRole("button", { name: "Edit Prototype" }));
    const form = screen.getByRole("form", { name: "Edit the Prototype milestone" });
    await user.clear(within(form).getByLabelText("Milestone name"));
    await user.type(within(form).getByLabelText("Milestone name"), "First playable");
    await user.type(within(form).getByLabelText("Description"), "A small playable build");
    fireEvent.change(within(form).getByLabelText("Target date"), { target: { value: "2026-12-01" } });
    await user.selectOptions(within(form).getByLabelText("Status"), "active");
    await user.click(within(form).getByRole("button", { name: "Save milestone" }));
    await waitFor(() => expect(calls).toContainEqual({ id: "m1", changes: { name: "First playable", description: "A small playable build", target_date: "2026-12-01", status: "active" } }));
    const manager = screen.getByRole("region", { name: "Manage milestones" });
    expect(await within(manager).findByText("First playable")).toBeInTheDocument();
    expect(within(manager).getByText("A small playable build")).toBeInTheDocument();
    expect(within(manager).getByText("Active")).toBeInTheDocument();
  });

  it("adds a milestone from the manager instead of the toolbar", async () => {
    mockMilestones();
    const user = userEvent.setup();
    renderPage();
    expect(screen.queryByRole("textbox", { name: "New milestone name" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manage milestones" }));
    const manager = await screen.findByRole("region", { name: "Manage milestones" });
    await user.type(within(manager).getByRole("textbox", { name: "New milestone name" }), "Launch");
    await user.click(within(manager).getByRole("button", { name: "Add milestone" }));
    expect(await within(manager).findByRole("heading", { name: "Launch" })).toBeInTheDocument();
    expect(within(manager).getByRole("textbox", { name: "New milestone name" })).toHaveValue("");
  });

  it("reorders milestones and keeps archived ones available to restore", async () => {
    const { calls } = mockMilestones();
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Manage milestones" }));
    const manager = await screen.findByRole("region", { name: "Manage milestones" });
    await user.click(within(manager).getByRole("button", { name: "Move Release up" }));
    await waitFor(() => expect(within(manager).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["Prototype", "Release", "Demo"]));
    expect(calls).toContainEqual({ id: "m3", changes: { sort_order: 1 } });

    await user.click(within(manager).getByRole("button", { name: "Archive Release" }));
    await waitFor(() => expect(within(manager).getByRole("button", { name: "Restore Release" })).toBeInTheDocument());
    expect(within(screen.getByLabelText("Milestone")).queryByRole("option", { name: /Release/ })).not.toBeInTheDocument();
    await user.click(within(manager).getByRole("button", { name: "Restore Release" }));
    await waitFor(() => expect(screen.getByLabelText("Milestone")).toHaveTextContent("Release"));
    expect(calls).toContainEqual({ id: "m3", changes: { status: "planned" } });
  });
});
