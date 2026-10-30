import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryPanel } from "./MemoryPanel";
import type { MemoryRecord } from "../../types/memory";
import type { TaskSummary } from "../../types/task";

const task: TaskSummary = { id: "t1", project_id: "p1", milestone_id: null, human_id: "CAMP-001", title: "Camp capacity", status: "todo", priority: "normal", next_action: null, sort_order: 0, criteria_total: 0, criteria_completed: 0, tags: [], is_focus: false, is_blocked_by_open_dependency: false };

function memory(overrides: Partial<MemoryRecord> = {}): MemoryRecord {
  return {
    id: "m1", project_id: "p1", human_id: "DEC-001", type: "decision", title: "Maximum party size is 4", content: "Four members fit the camp.", status: "active", importance: "high", is_pinned: false, is_locked: false, is_resolved: false, pending_note: null, ai_visibility: "relevant_only", source_type: "agent", source_reference: "Earlier session", confidence: 0.8, supersedes_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", invalidated_at: null, archived_at: null, tags: ["gameplay"], tasks: [], superseded_by: null, supersedes: null,
    ...overrides,
  };
}

interface Call { url: string; method: string; body?: Record<string, unknown> }

function mockApi(initial: MemoryRecord = memory(), linkedTask: TaskSummary = task) {
  let current = initial;
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input);
    const method = options?.method ?? "GET";
    const body = options?.body ? JSON.parse(String(options.body)) as Record<string, unknown> : undefined;
    calls.push({ url, method, body });
    if (url === "/api/projects/p1/tasks") return Response.json(linkedTask.status === "archived" ? [] : [linkedTask]);
    if (url === `/api/projects/p1/tasks/${linkedTask.human_id}` || url === `/api/projects/p1/tasks/${linkedTask.id}`) return Response.json(linkedTask);
    if (url === "/api/projects/p1/memory" && method === "POST") {
      current = memory({ id: "m2", human_id: "DEC-002", ...body });
      return Response.json(current, { status: 201 });
    }
    if (url === "/api/projects/p1/memory/m1" && method === "DELETE") return new Response(null, { status: 204 });
    if (url === "/api/projects/p1/memory/DEC-001" || url === "/api/projects/p1/memory/m1") {
      if (method === "PATCH") { current = { ...current, ...body }; return Response.json(current); }
      return Response.json(current);
    }
    if (url === "/api/projects/p1/memory/DEC-001/history") {
      const chain = [current.supersedes, { id: current.id, human_id: current.human_id, title: current.title, type: current.type, status: current.status }, current.superseded_by].filter(Boolean);
      return Response.json({ chain, current_id: chain.at(-1)?.id ?? current.id });
    }
    if (url === "/api/projects/p1/memory/m1/supersede" && method === "POST") {
      current = memory({ id: "m2", human_id: "DEC-002", title: String(body?.title), content: String(body?.content), supersedes_id: "m1" });
      return Response.json(current, { status: 201 });
    }
    if (url === "/api/projects/p1/memory/m1/restore" && method === "POST") { current = { ...current, status: "active" }; return Response.json(current); }
    if (url === "/api/projects/p1/memory/m1/archive" && method === "POST") { current = { ...current, status: "archived" }; return Response.json(current); }
    if (url === "/api/projects/p1/memory/m1/invalidate" && method === "POST") { current = { ...current, status: "invalidated" }; return Response.json(current); }
    return Response.json({ detail: `Unexpected ${method} ${url}` }, { status: 500 });
  }));
  return calls;
}

function renderPanel(memoryRef: string | null, options: { readonly?: boolean; defaultTaskRef?: string | null } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onChanged = vi.fn();
  const onClose = vi.fn();
  render(<QueryClientProvider client={client}><MemoryPanel projectId="p1" memoryRef={memoryRef} onChanged={onChanged} onClose={onClose} readonly={options.readonly ?? false} defaultTaskRef={options.defaultTaskRef} /></QueryClientProvider>);
  return { onChanged, onClose };
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.show = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("memory panel", () => {
  it("creates a typed memory with visibility, tags, lock, pin, and a linked project task", async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    const { onChanged } = renderPanel(null, { defaultTaskRef: "CAMP-001" });
    await screen.findByText("Camp capacity");
    await user.selectOptions(screen.getByLabelText("Type"), "decision");
    await user.type(screen.getByLabelText(/Title/), "The camp holds four people");
    await user.type(screen.getByLabelText("Details"), "This is the current design choice.");
    await user.selectOptions(screen.getByLabelText("Importance"), "critical");
    await user.selectOptions(screen.getByLabelText("AI visibility"), "hidden");
    expect(screen.getByText(/Keep out of AI context/)).toBeInTheDocument();
    await user.click(screen.getByLabelText("Pin to the top"));
    await user.click(screen.getByLabelText("Lock memory"));
    await user.type(screen.getByLabelText("Tags"), "gameplay, design");
    await user.click(screen.getByRole("button", { name: "Add memory" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith("DEC-002"));
    const post = calls.find((call) => call.method === "POST" && call.url === "/api/projects/p1/memory");
    expect(post?.body).toMatchObject({ type: "decision", title: "The camp holds four people", content: "This is the current design choice.", importance: "critical", ai_visibility: "hidden", is_pinned: true, is_locked: true, tags: ["gameplay", "design"], task_ids: ["CAMP-001"] });
  });

  it("keeps a new memory open and unchanged until Cancel or Add memory is chosen", async () => {
    mockApi();
    const user = userEvent.setup();
    const { onClose } = renderPanel(null);
    await user.type(screen.getByLabelText(/Title/), "Half written");
    const dialog = screen.getByRole("dialog");
    await user.click(dialog.parentElement ?? document.body);
    fireEvent.click(dialog);
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/Title/)).toHaveValue("Half written");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("resolves an archived task preselected from its task panel", async () => {
    mockApi(memory(), { ...task, status: "archived" });
    renderPanel(null, { defaultTaskRef: "CAMP-001" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Unlink task CAMP-001" }).closest("li")).toHaveTextContent("Camp capacity"));
    expect(screen.queryByText("Task not loaded")).not.toBeInTheDocument();
  });

  it("explains a lock, displays provenance, and lets a person edit while keeping type fixed", async () => {
    const calls = mockApi(memory({ is_locked: true }));
    const user = userEvent.setup();
    const { onChanged } = renderPanel("DEC-001");
    const panel = await screen.findByRole("dialog", { name: /Maximum party size is 4/ });
    expect(within(panel).getByText(/AI agents cannot change it without your review/)).toBeInTheDocument();
    expect(within(panel).getByText(/Earlier session/)).toBeInTheDocument();
    expect(within(panel).getByText("Confidence: 80%")).toBeInTheDocument();
    expect(within(panel).getByText(/The type cannot change after creation/)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Delete" })).toBeDisabled();
    await user.clear(within(panel).getByLabelText(/Title/));
    await user.type(within(panel).getByLabelText(/Title/), "Maximum party size is 6");
    await user.selectOptions(within(panel).getByLabelText("AI visibility"), "always");
    await user.click(within(panel).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith("DEC-001"));
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ title: "Maximum party size is 6", ai_visibility: "always" });
  });

  it("supersedes an active record and keeps the prior record available in history", async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    const { onChanged } = renderPanel("DEC-001");
    const panel = await screen.findByRole("dialog", { name: /Maximum party size is 4/ });
    const history = within(panel).getByRole("region", { name: "Memory history" });
    expect(within(history).getByRole("button", { name: /DEC-001/ })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Supersede" }));
    await user.clear(within(panel).getByLabelText("New title"));
    await user.type(within(panel).getByLabelText("New title"), "Maximum party size is 6");
    await user.click(within(panel).getByRole("button", { name: "Create replacement" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith("DEC-002"));
    expect(calls.find((call) => call.url.endsWith("/supersede") && call.method === "POST")?.body).toMatchObject({ title: "Maximum party size is 6", content: "Four members fit the camp." });
  });

  it("restores an archived record and prevents editing historical text", async () => {
    const calls = mockApi(memory({ status: "archived" }));
    const user = userEvent.setup();
    renderPanel("DEC-001");
    const panel = await screen.findByRole("dialog", { name: /Maximum party size is 4/ });
    await user.click(within(panel).getByRole("button", { name: "Restore memory" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/restore"))).toBe(true));
  });

  it("leaves superseded text read only but still permits human pin changes", async () => {
    const calls = mockApi(memory({ status: "superseded", superseded_by: { id: "m2", human_id: "DEC-002", title: "New choice", type: "decision", status: "active" } }));
    const user = userEvent.setup();
    renderPanel("DEC-001");
    const panel = await screen.findByRole("dialog", { name: /Maximum party size is 4/ });
    expect(within(panel).getByLabelText(/Title/)).toBeDisabled();
    expect(within(panel).getByLabelText("Details")).toBeDisabled();
    await user.click(within(panel).getByLabelText("Pin to the top"));
    await user.click(within(panel).getByRole("button", { name: /Save pin, lock, or task links/ }));
    await waitFor(() => expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ is_pinned: true }));
  });

  it("shows the whole replacement chain and opens another version", async () => {
    mockApi(memory({ status: "superseded", supersedes_id: "m0", supersedes: { id: "m0", human_id: "DEC-000", title: "Original choice", type: "decision", status: "superseded" }, superseded_by: { id: "m2", human_id: "DEC-002", title: "Latest choice", type: "decision", status: "active" } }));
    const user = userEvent.setup();
    const { onChanged } = renderPanel("DEC-001");
    const history = await screen.findByRole("region", { name: "Memory history" });
    expect(await within(history).findByRole("button", { name: /DEC-002.*Latest/ })).toBeInTheDocument();
    expect(within(history).getByRole("button", { name: /DEC-000/ })).toBeInTheDocument();
    await user.click(within(history).getByRole("button", { name: /DEC-000/ }));
    expect(onChanged).toHaveBeenCalledWith("DEC-000");
  });

  it("requires explicit confirmation before permanent deletion", async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    const { onChanged, onClose } = renderPanel("DEC-001");
    const panel = await screen.findByRole("dialog", { name: /Maximum party size is 4/ });
    await user.click(within(panel).getByRole("button", { name: "Delete" }));
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    await user.click(within(panel).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(null));
    expect(onClose).toHaveBeenCalled();
  });

  it("confirms invalidation before removing a memory from active use", async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    renderPanel("DEC-001");
    const panel = await screen.findByRole("dialog", { name: /Maximum party size is 4/ });
    await user.click(within(panel).getByRole("button", { name: "Mark incorrect" }));
    expect(calls.some((call) => call.url.endsWith("/invalidate") && call.method === "POST")).toBe(false);
    const confirmation = within(panel).getByText("Mark this memory incorrect?").parentElement!;
    await user.click(within(confirmation).getByRole("button", { name: "Mark incorrect" }));
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/invalidate") && call.method === "POST")).toBe(true));
  });
});
