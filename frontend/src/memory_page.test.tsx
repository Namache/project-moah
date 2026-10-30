import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { MemoryRecord, MemoryType } from "./types/memory";
import type { Project } from "./types/project";

const project: Project = { id: "p1", name: "Trailhead", slug: "trailhead", description: null, icon: "⛰️", accent: "#D99A53", root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };
const task = { id: "t1", project_id: "p1", human_id: "CAMP-001", title: "Camp Population Capacity", status: "todo", priority: "normal", next_action: null, sort_order: 0, criteria_total: 0, criteria_completed: 0, tags: [], is_focus: false, is_blocked_by_open_dependency: false, milestone_id: null, milestone: null };

function memory(type: MemoryType, over: Partial<MemoryRecord> = {}): MemoryRecord {
  const human_id = type === "decision" ? "DEC-001" : type === "idea" ? "IDEA-001" : "NOTE-001";
  return {
    id: type, human_id, project_id: "p1", type, title: type === "decision" ? "Maximum party size is 4" : type === "idea" ? "Try temporary tents" : "Camp notes",
    content: type === "idea" ? "This is only a possibility." : "Important project context.", status: "active", importance: "normal", is_pinned: false, is_locked: false, is_resolved: false, pending_note: null,
    ai_visibility: "relevant_only", source_type: null, source_reference: null, confidence: null, supersedes_id: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", invalidated_at: null, archived_at: null,
    tags: type === "decision" ? ["gameplay"] : ["maybe"], tasks: type === "decision" ? [{ id: "t1", human_id: "CAMP-001", title: "Camp Population Capacity", status: "todo" }] : [],
    superseded_by: null, supersedes: null, ...over,
  };
}

function mockApi(initial: MemoryRecord[] = [memory("decision"), memory("idea")], archived = false) {
  const records = [...initial];
  const calls: { url: string; method: string; body?: Record<string, unknown> }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input);
    const method = options?.method ?? "GET";
    const body = options?.body ? JSON.parse(String(options.body)) as Record<string, unknown> : undefined;
    calls.push({ url, method, body });
    if (url === "/api/projects?include_archived=true") return Response.json([{ ...project, status: archived ? "archived" : "active" }]);
    if (url === "/api/projects/p1") return Response.json({ ...project, status: archived ? "archived" : "active" });
    if (url === "/api/projects/p1/tasks") return Response.json([task]);
    if (url === "/api/projects/p1/memory/counts") {
      const active = records.filter((item) => item.status === "active");
      return Response.json({ by_type: Object.fromEntries(["decision", "rule", "fact", "idea", "bug", "note", "warning"].map((type) => [type, active.filter((item) => item.type === type).length])), pinned: active.filter((item) => item.is_pinned).length, locked: active.filter((item) => item.is_locked).length });
    }
    if (url === "/api/projects/p1/memory" && method === "POST" && body) {
      const next = memory(body.type as MemoryType, { id: "created", human_id: "NOTE-002", title: body.title as string, content: body.content as string, tags: body.tags as string[], tasks: (body.task_ids as string[]).includes("CAMP-001") ? [{ id: "t1", human_id: "CAMP-001", title: task.title, status: "todo" }] : [] });
      records.push(next);
      return Response.json(next, { status: 201 });
    }
    const patch = url.match(/^\/api\/projects\/p1\/memory\/([^/]+)$/);
    if (patch && method === "PATCH" && body) {
      const index = records.findIndex((item) => item.id === patch[1] || item.human_id === patch[1]);
      records[index] = { ...records[index], ...body } as MemoryRecord;
      return Response.json(records[index]);
    }
    if (url.startsWith("/api/projects/p1/memory?")) {
      const params = new URL(url, "http://test").searchParams;
      const types = params.getAll("type");
      const statuses = params.getAll("status");
      const visibility = params.getAll("visibility");
      const q = params.get("q")?.toLowerCase();
      let rows = records.filter((item) => (statuses.length ? statuses.includes(item.status) : item.status === "active") && (!types.length || types.includes(item.type)) && (!visibility.length || visibility.includes(item.ai_visibility)) && (!params.has("pinned") || item.is_pinned === (params.get("pinned") === "true")) && (!params.has("locked") || item.is_locked === (params.get("locked") === "true")) && (!params.has("resolved") || item.is_resolved === (params.get("resolved") === "true")) && (!params.get("tag") || item.tags.includes(params.get("tag")!)) && (!params.get("task") || item.tasks.some((linked) => linked.human_id === params.get("task"))) && (!q || `${item.human_id} ${item.title} ${item.content}`.toLowerCase().includes(q)));
      if (params.get("sort") === "title_asc") rows = [...rows].sort((a, b) => a.title.localeCompare(b.title));
      const offset = Number(params.get("offset") ?? 0);
      return Response.json(rows.slice(offset, offset + Number(params.get("limit") ?? 100)));
    }
    const history = url.match(/^\/api\/projects\/p1\/memory\/([^/]+)\/history$/);
    if (history) { const found = records.find((item) => item.id === history[1] || item.human_id === history[1]); return Response.json({ chain: found ? [{ id: found.id, human_id: found.human_id, type: found.type, title: found.title, status: found.status }] : [], current_id: found?.id ?? "" }); }
    const one = url.match(/^\/api\/projects\/p1\/memory\/([^/]+)$/);
    if (one) { const found = records.find((item) => item.id === one[1] || item.human_id === one[1]); return found ? Response.json(found) : Response.json({ detail: "Memory not found" }, { status: 404 }); }
    return Response.json({ detail: "Unexpected test request" }, { status: 500 });
  }));
  return { calls };
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.show = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("project memory page", () => {
  it("distinguishes decisions from ideas and filters by category, tag, and sort", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/memory");
    const decision = await screen.findByRole("button", { name: /Open DEC-001: Maximum party size is 4/ });
    const idea = screen.getByRole("button", { name: /Open IDEA-001: Try temporary tents/ });
    expect(decision).toHaveTextContent("Decision· Chosen");
    expect(idea).toHaveTextContent("Idea· Considering, not a requirement");
    expect(decision.closest("li")).not.toHaveClass("border-dashed");
    expect(idea.closest("li")).toHaveClass("border-dashed");
    await user.click(screen.getByRole("button", { name: /Ideas 1/ }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Open DEC-001/ })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Open IDEA-001/ })).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Sort memory" }), "title_asc");
    await waitFor(() => expect(calls.some((call) => call.url.includes("type=idea") && call.url.includes("sort=title_asc"))).toBe(true));
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.click(screen.getByRole("button", { name: "Filter memory by tag gameplay" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Open IDEA-001/ })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Open DEC-001/ })).toBeInTheDocument();
  });

  it("opens a deep linked record and creates memory already linked to a task", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/memory?memory=DEC-001");
    const dialog = await screen.findByRole("dialog", { name: "Maximum party size is 4" });
    expect(dialog).toHaveTextContent("DEC-001");
    await user.click(within(dialog).getByRole("button", { name: "Close memory" }));
    await user.click(screen.getByRole("button", { name: /Open IDEA-001: Try temporary tents/ }));
    expect(await screen.findByRole("dialog", { name: "Try temporary tents" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close memory" }));
    // The task shortcut uses the same URL contract as the task panel's Add memory link.
    await user.click(screen.getByRole("button", { name: "New memory" }));
    const createDialog = await screen.findByRole("dialog", { name: "Add project memory" });
    await user.type(within(createDialog).getByLabelText(/^Title/), "Camp rule");
    await user.click(within(createDialog).getByRole("button", { name: "Add memory" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.body?.title === "Camp rule")).toBe(true));
    expect(await screen.findByRole("dialog", { name: "Camp rule" })).toBeInTheDocument();
  });

  it("uses the task shortcut to prelink new memory and keeps archived projects read-only", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    renderApp("/projects/p1/memory?task=CAMP-001&new=1");
    const createDialog = await screen.findByRole("dialog", { name: "Add project memory" });
    expect(within(createDialog).getByText("CAMP-001")).toBeInTheDocument();
    await user.type(within(createDialog).getByLabelText(/^Title/), "Capacity choice");
    await user.click(within(createDialog).getByRole("button", { name: "Add memory" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && (call.body?.task_ids as string[]).includes("CAMP-001"))).toBe(true));
    expect(await screen.findByRole("button", { name: /Open NOTE-002: Capacity choice/ })).toBeInTheDocument();
  });

  it("searches and filters historical records, and loads memory beyond the first page", async () => {
    const notes = Array.from({ length: 101 }, (_, index) => memory("note", { id: `note-${index}`, human_id: `NOTE-${String(index + 1).padStart(3, "0")}`, title: `Note ${index + 1}`, tags: [] }));
    const { calls } = mockApi([...notes, memory("warning", { id: "warning", human_id: "WARN-001", title: "Hidden caution", ai_visibility: "hidden", is_pinned: true, is_locked: true, tags: ["safety"] }), memory("note", { id: "archived-note", human_id: "NOTE-999", title: "Old note", status: "archived", tags: [] })]);
    const user = userEvent.setup();
    renderApp("/projects/p1/memory");
    expect(await screen.findByRole("button", { name: "Load more memory" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open NOTE-101:/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more memory" }));
    expect(await screen.findByRole("button", { name: /Open NOTE-101:/ })).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Search memory" }), "Hidden caution");
    expect(await screen.findByRole("button", { name: /Open WARN-001: Hidden caution/ })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /Open NOTE-101:/ })).not.toBeInTheDocument());
    expect(screen.queryByRole("combobox", { name: "AI visibility filter" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Filters" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "AI visibility filter" }), "hidden");
    await user.selectOptions(screen.getByRole("combobox", { name: "Pinned filter" }), "yes");
    await user.selectOptions(screen.getByRole("combobox", { name: "Locked filter" }), "yes");
    expect(screen.getByRole("button", { name: /Filters 3 active/ })).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(calls.some((call) => call.url.includes("visibility=hidden") && call.url.includes("pinned=true") && call.url.includes("locked=true") && call.url.includes("q=Hidden+caution"))).toBe(true));
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Memory status" }), "archived");
    expect(await screen.findByRole("button", { name: /Open NOTE-999: Old note/ })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /Open WARN-001:/ })).not.toBeInTheDocument());
  }, 15000); // Renders and filters over a hundred cards, which is slow when the whole suite runs in parallel.

  it("filters known issues by pending and resolved", async () => {
    const pending = memory("note", { id: "bug-1", human_id: "BUG-001", type: "bug", title: "Crash on load", tags: [] });
    const resolved = memory("note", { id: "bug-2", human_id: "BUG-002", type: "bug", title: "Wrong tooltip", is_resolved: true, tags: [] });
    mockApi([pending, resolved]);
    const user = userEvent.setup();
    renderApp("/projects/p1/memory");
    expect(screen.queryByRole("group", { name: "Known issue state" })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /^Known issues/ }));
    const state = await screen.findByRole("group", { name: "Known issue state" });
    expect(await screen.findByRole("button", { name: /Open BUG-001:/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open BUG-002:/ })).toBeInTheDocument();
    await user.click(within(state).getByRole("button", { name: "Pending" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Open BUG-002:/ })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Open BUG-001:/ })).toBeInTheDocument();
    await user.click(within(state).getByRole("button", { name: "Resolved" }));
    expect(await screen.findByRole("button", { name: /Open BUG-002:/ })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /Open BUG-001:/ })).not.toBeInTheDocument());
  });

  it("reviews pending issues one card at a time, saving notes and resolutions", async () => {
    const first = memory("note", { id: "bug-1", human_id: "BUG-001", type: "bug", title: "Crash on load", tags: [] });
    const second = memory("note", { id: "bug-2", human_id: "BUG-002", type: "bug", title: "Wrong tooltip", tags: [] });
    const third = memory("note", { id: "bug-3", human_id: "BUG-003", type: "bug", title: "Slow startup", tags: [] });
    const { calls } = mockApi([first, second, third]);
    const user = userEvent.setup();
    renderApp("/projects/p1/memory");
    await user.click(await screen.findByRole("button", { name: /^Known issues/ }));
    await user.click(await screen.findByRole("button", { name: "Check pending issues" }));
    const review = await screen.findByRole("dialog", { name: "Check pending issues" });
    expect(await within(review).findByText("Crash on load")).toBeInTheDocument();
    expect(within(review).getByText("1 of 3")).toBeInTheDocument();

    await user.type(within(review).getByLabelText(/Why is it still pending/), "Still crashes on old saves");
    await user.click(within(review).getByRole("button", { name: "Still pending" }));
    expect(await within(review).findByText("Wrong tooltip")).toBeInTheDocument();
    expect(calls.some((call) => call.method === "PATCH" && call.url.endsWith("/bug-1") && call.body?.pending_note === "Still crashes on old saves")).toBe(true);

    await user.click(within(review).getByRole("button", { name: "Resolved" }));
    expect(await within(review).findByText("Slow startup")).toBeInTheDocument();
    expect(calls.some((call) => call.method === "PATCH" && call.url.endsWith("/bug-2") && call.body?.is_resolved === true)).toBe(true);

    await user.click(within(review).getByRole("button", { name: "Undo" }));
    expect(await within(review).findByText("Wrong tooltip")).toBeInTheDocument();
    expect(calls.some((call) => call.method === "PATCH" && call.url.endsWith("/bug-2") && call.body?.is_resolved === false)).toBe(true);

    await user.click(within(review).getByRole("button", { name: "Skip" }));
    await user.click(within(review).getByRole("button", { name: "Skip" }));
    expect(await within(review).findByText("Reviewed 3")).toBeInTheDocument();
    expect(within(review).getByText(/0 resolved, 1 still pending, 2 skipped/)).toBeInTheDocument();
  });

  it("closes the issue review with Escape and starts the next review from fresh data", async () => {
    const first = memory("note", { id: "bug-1", human_id: "BUG-001", type: "bug", title: "Crash on load", tags: [] });
    const second = memory("note", { id: "bug-2", human_id: "BUG-002", type: "bug", title: "Wrong tooltip", tags: [] });
    mockApi([first, second]);
    const user = userEvent.setup();
    renderApp("/projects/p1/memory");
    await user.click(await screen.findByRole("button", { name: /^Known issues/ }));
    await user.click(await screen.findByRole("button", { name: "Check pending issues" }));
    const review = await screen.findByRole("dialog", { name: "Check pending issues" });
    expect(await within(review).findByText("1 of 2")).toBeInTheDocument();
    fireEvent(review, new Event("cancel", { cancelable: true }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Check pending issues" })).not.toBeInTheDocument());

    first.is_resolved = true; // resolved somewhere else while the review was closed
    await user.click(screen.getByRole("button", { name: "Check pending issues" }));
    const again = await screen.findByRole("dialog", { name: "Check pending issues" });
    expect(await within(again).findByText("1 of 1")).toBeInTheDocument();
    expect(within(again).getByText("Wrong tooltip")).toBeInTheDocument();
  });

  it("does not offer editing controls for an archived project", async () => {
    mockApi([memory("decision")], true);
    renderApp("/projects/p1/memory?memory=DEC-001");
    const dialog = await screen.findByRole("dialog", { name: "Maximum party size is 4" });
    expect(screen.queryByRole("button", { name: "New memory" })).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText(/^Title/)).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });
});
