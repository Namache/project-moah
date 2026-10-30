import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectCheckpoints, TaskCheckpoints } from "./CheckpointsSection";
import type { Checkpoint } from "../../types/checkpoint";

const checkpoint: Checkpoint = {
  id: "c1", project_id: "p1", task_id: "t1", task: { id: "t1", human_id: "CAMP-001", title: "Camp capacity", status: "todo" },
  title: "Capacity rules drafted", summary: "Validation works.", completed_work: "Capacity calculation", remaining_work: "Migration",
  problems: "Old saves lack capacity", next_steps: "Add migration fallback", agent: "Claude", git_commit: "abc123",
  created_at: "2026-01-02T12:00:00Z", updated_at: "2026-01-02T12:00:00Z",
};
const older: Checkpoint = { ...checkpoint, id: "c0", title: "Started capacity work", created_at: "2026-01-01T12:00:00Z" };
interface Call { url: string; method: string; body?: Record<string, unknown> }

function mockApi(options: { empty?: boolean } = {}) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
    calls.push({ url, method, body });
    if (url === "/api/projects/p1/tasks") return Response.json([{ id: "t1", project_id: "p1", human_id: "CAMP-001", title: "Camp capacity", status: "todo" }]);
    if (url.endsWith("/checkpoints/latest") || url.includes("/checkpoints/latest?")) return options.empty ? Response.json({ detail: "No checkpoint" }, { status: 404 }) : Response.json(checkpoint);
    if (url.includes("/checkpoints?") && method === "GET") return Response.json(options.empty ? [] : [checkpoint, older]);
    if (url === "/api/projects/p1/checkpoints" && method === "POST") return Response.json({ ...checkpoint, id: "c2", title: body?.title, ...body }, { status: 201 });
    if (url === "/api/projects/p1/checkpoints/c1" && method === "PATCH") return Response.json({ ...checkpoint, ...body });
    if (url === "/api/projects/p1/checkpoints/c1" && method === "GET") return Response.json(checkpoint);
    if (url === "/api/projects/p1/checkpoints/c0" && method === "GET") return Response.json(older);
    return Response.json({ detail: `Unexpected ${method} ${url}` }, { status: 500 });
  }));
  return calls;
}

function renderProject(path = "/projects/p1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/projects/:projectId" element={<ProjectCheckpoints projectId="p1" archived={false} />} /></Routes></MemoryRouter></QueryClientProvider>);
}

function LocationEcho() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("checkpoint UI", () => {
  it("shows the resolved latest checkpoint, history, and opens a deep linked checkpoint", async () => {
    mockApi();
    renderProject("/projects/p1?checkpoint=c1");
    expect(await screen.findByRole("dialog", { name: "Capacity rules drafted" })).toBeInTheDocument();
    expect(screen.getByText("Latest checkpoint")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open checkpoint Started capacity work" })).toBeInTheDocument();
    const panel = screen.getByRole("dialog", { name: "Capacity rules drafted" });
    expect(within(panel).getByLabelText("Next steps")).toHaveValue("Add migration fallback");
    expect(within(panel).getByRole("link", { name: /CAMP-001/ })).toHaveAttribute("href", "/projects/p1/tasks?task=CAMP-001");
  });

  it("creates a task checkpoint with resume fields and a fixed task link", async () => {
    const calls = mockApi({ empty: true });
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/p1/tasks?task=CAMP-001"]}><LocationEcho /><TaskCheckpoints projectId="p1" taskId="t1" /></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText(/No checkpoint yet/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create checkpoint" }));
    const panel = screen.getByRole("dialog", { name: "Record progress" });
    await user.type(within(panel).getByLabelText(/Title/), "Capacity migration queued");
    await user.type(within(panel).getByLabelText("Completed work"), "Validation tests pass");
    await user.type(within(panel).getByLabelText("Remaining work"), "Migrate old saves");
    await user.type(within(panel).getByLabelText("Problems"), "Legacy data has no capacity");
    await user.type(within(panel).getByLabelText("Next steps"), "Add a fallback value");
    await user.click(within(panel).getByRole("button", { name: "Create checkpoint" }));
    await waitFor(() => expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({
      task_id: "t1", title: "Capacity migration queued", completed_work: "Validation tests pass",
      remaining_work: "Migrate old saves", problems: "Legacy data has no capacity", next_steps: "Add a fallback value",
    }));
    expect(calls.some((call) => call.url.includes("/checkpoints/latest?task=t1"))).toBe(true);
    expect(screen.getByTestId("location")).toHaveTextContent("task=CAMP-001");
    expect(screen.getByTestId("location")).toHaveTextContent("checkpoint=c2");
  });

  it("rejects a checkpoint linked to another task and preserves the open task on close", async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/p1/tasks?task=CAMP-002&checkpoint=c1"]}><LocationEcho /><TaskCheckpoints projectId="p1" taskId="t2" /></MemoryRouter></QueryClientProvider>);

    const panel = await screen.findByRole("dialog", { name: "Capacity rules drafted" });
    expect(within(panel).getByRole("alert")).toHaveTextContent("does not belong to the open task");
    expect(within(panel).queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText(/Title/)).not.toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Close checkpoint" }));
    expect(screen.getByTestId("location")).toHaveTextContent("task=CAMP-002");
    expect(screen.getByTestId("location")).not.toHaveTextContent("checkpoint=");
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
  });

  it("explains why an archived task's checkpoints are read-only", async () => {
    mockApi();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/p1/tasks?task=CAMP-001&checkpoint=c1"]}><TaskCheckpoints projectId="p1" taskId="t1" archived /></MemoryRouter></QueryClientProvider>);

    const panel = await screen.findByRole("dialog", { name: "Capacity rules drafted" });
    expect(within(panel).getByText("Checkpoints are read-only while their project or task is archived.")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });

  it("edits only changed fields on an existing checkpoint", async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    renderProject();
    await user.click(await screen.findByRole("button", { name: "Open checkpoint Capacity rules drafted" }));
    const panel = await screen.findByRole("dialog", { name: "Capacity rules drafted" });
    await user.clear(within(panel).getByLabelText("Next steps"));
    await user.type(within(panel).getByLabelText("Next steps"), "Run migration test");
    await user.click(within(panel).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ next_steps: "Run migration test" }));
  });
});
