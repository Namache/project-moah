import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const project = { id: "p1", name: "Trailhead", slug: "c", description: null, icon: null, accent: null, root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };
const base = { project_id: "p1", agent: "codex", target_entity_type: "memory", target_entity_id: "m1", snapshot: null, review_note: null, applied_payload: null, error: null, created_at: "2026-01-02T00:00:00Z", reviewed_at: null, status: "pending" };
const locked = { ...base, id: "a", human_id: "PROP-001", proposal_type: "update_memory", target_label: "DEC-001 Base camp capacity", target_locked: true, payload: { content: "8" }, reason: "Playtests need 8", changes: ["Content: 6 → 8"] };
const other = { ...base, id: "b", human_id: "PROP-002", proposal_type: "complete_task", target_label: null, target_locked: false, payload: { complete_all_criteria: false }, reason: "", changes: ["Status: in progress → completed"] };

function setup(list: object[] = [locked, other]) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input), method = options?.method ?? "GET";
    calls.push({ url, method, body: options?.body ? JSON.parse(String(options.body)) : undefined });
    if (url.startsWith("/api/projects?")) return Response.json([project]);
    if (url === "/api/projects/p1") return Response.json(project);
    if (url.startsWith("/api/projects/p1/proposals?")) return Response.json(url.includes("status=pending") ? list : []);
    if (url === "/api/proposals/pending") return Response.json({ total: list.length, by_project: { p1: list.length } });
    if (url.endsWith("/accept") || url.endsWith("/reject")) return Response.json({ ...locked, status: url.endsWith("/accept") ? "accepted" : "rejected" });
    if (url.endsWith("/accept-all")) return Response.json({ accepted: list, failed: [] });
    return Response.json([]);
  }));
  return calls;
}
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Review", () => {
  it("shows what will change, warns about locked memory, and accepts as is", async () => {
    const calls = setup();
    const user = userEvent.setup();
    renderAt("/projects/p1/review");
    const card = await screen.findByRole("article", { name: /PROP-001/ });
    expect(within(card).getByText("Content: 6 → 8")).toBeInTheDocument();
    expect(within(card).getByText("Locked")).toBeInTheDocument();
    expect(within(card).getByText(/stays locked/)).toBeInTheDocument();
    expect(within(card).getByText(/Playtests need 8/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Accept" }));
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/projects/p1/proposals/a/accept")).toBe(true);
  });

  it("edits lists, numbers and text without losing typed commas or structured values", async () => {
    const file = { ...base, id: "c", human_id: "PROP-003", proposal_type: "create_memory", target_label: null, target_locked: false, reason: "", changes: ["New decision"],
      payload: { title: "Camp size", tags: ["camp"], confidence: 0.5, importance_score: 2, symbols: [{ name: "Camp", kind: "class" }] } };
    const calls = setup([file]);
    const user = userEvent.setup();
    renderAt("/projects/p1/review");
    const card = await screen.findByRole("article", { name: /PROP-003/ });
    await user.click(within(card).getByRole("button", { name: "Edit and accept" }));
    const tags = within(card).getByLabelText(/Tags/);
    await user.type(tags, ", balance");
    expect(tags).toHaveValue("camp, balance");
    const score = within(card).getByLabelText("Importance score");
    await user.clear(score);
    await user.type(score, "3");
    expect(within(card).getByText(/"name": "Camp"/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Accept with my edits" }));
    expect(calls.find((c) => c.url.endsWith("/c/accept"))?.body).toEqual({ payload: { title: "Camp size", tags: ["camp", "balance"], confidence: 0.5, importance_score: 3, symbols: [{ name: "Camp", kind: "class" }] } });
  });

  it("lets a person edit before accepting and reject with a note", async () => {
    const calls = setup();
    const user = userEvent.setup();
    renderAt("/projects/p1/review");
    const card = await screen.findByRole("article", { name: /PROP-001/ });
    await user.click(within(card).getByRole("button", { name: "Edit and accept" }));
    const field = within(card).getByLabelText("Content");
    await user.clear(field);
    await user.type(field, "7");
    await user.click(within(card).getByRole("button", { name: "Accept with my edits" }));
    expect(calls.find((c) => c.url.endsWith("/a/accept"))?.body).toEqual({ payload: { content: "7" } });

    const second = screen.getByRole("article", { name: /PROP-002/ });
    await user.click(within(second).getByRole("button", { name: "Dismiss" }));
    await user.type(within(second).getByLabelText(/Note for the record/), "Not yet");
    await user.click(within(second).getByRole("button", { name: "Dismiss suggestion" }));
    expect(calls.find((c) => c.url.endsWith("/b/reject"))?.body).toEqual({ note: "Not yet" });
  });

  it("asks before accepting everything, and explains an empty queue", async () => {
    const calls = setup();
    const user = userEvent.setup();
    renderAt("/projects/p1/review");
    await user.click(await screen.findByRole("button", { name: "Accept all" }));
    expect(calls.some((c) => c.url.endsWith("/accept-all"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Yes, accept all" }));
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/accept-all"))).toBe(true);
    cleanup();
    setup([]);
    renderAt("/projects/p1/review");
    expect(await screen.findByText("Nothing waiting for review")).toBeInTheDocument();
  });

  it("shows pending suggestions on Home and in the project tabs", async () => {
    setup();
    renderAt("/");
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(await within(inbox).findByText(/suggestions wait/)).toBeInTheDocument();
    expect(within(inbox).getByRole("link", { name: "Open Inbox" })).toHaveAttribute("href", "/review");
    const tiles = screen.getByRole("list", { name: "Active projects" });
    expect(within(tiles).getByLabelText("2 in Inbox")).toBeInTheDocument();
  });

  it("lists every waiting suggestion on the workspace Review page, grouped by project", async () => {
    setup();
    renderAt("/review");
    const group = await screen.findByRole("region", { name: /Trailhead/ });
    expect(await within(group).findByRole("article", { name: /PROP-001/ })).toBeInTheDocument();
    expect(within(group).getByRole("article", { name: /PROP-002/ })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Accept all 2" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Workspace" });
    expect(within(nav).getByRole("link", { name: /Inbox/ })).toHaveAttribute("href", "/review");
  });

  it("says when nothing is waiting", async () => {
    setup([]);
    renderAt("/review");
    expect(await screen.findByRole("heading", { name: "You're all caught up" })).toBeInTheDocument();
  });
});
