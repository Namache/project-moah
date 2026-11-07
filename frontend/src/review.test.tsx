import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const project = { id: "p1", name: "Trailhead", slug: "trailhead", description: null, icon: "⛰️", accent: "#D99A53", root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };
const row = { project_id: "p1", project_name: "Trailhead", project_icon: "⛰️", project_accent: "#D99A53", kind: "task", reviewed_at: null, verdict: null, question: false, task_status: "review", moved_to: null, round: 1, generated: false };
const upgrade = { ...row, key: "task:t2", ref: "CAMP-002", title: "Camp upgrade screen", summary: "Added the upgrade screen", agent: "claude", done_at: "2026-01-03T10:00:00Z", screenshots: 1 };
const rations = { ...row, key: "task:t3", ref: "CAMP-003", title: "Ration balance", summary: "Halved the ration drain", agent: "codex", done_at: "2026-01-03T09:00:00Z", screenshots: 0, generated: true };
const camp4 = { ...row, key: "task:t4", ref: "CAMP-004", title: "Full camp label", summary: "Should a full camp show 0?", agent: "claude", done_at: "2026-01-03T11:30:00Z", screenshots: 0, question: true, task_status: "blocked" };
const tents = { ...row, key: "review:r0", ref: "CAMP-000", title: "Tents", summary: "Tents", agent: "codex", done_at: "2026-01-01T09:00:00Z", reviewed_at: "2026-01-01T12:00:00Z", verdict: "accepted", screenshots: 0 };

const round = { id: "r1", round: 1, agent: "claude", kind: "work", status: "pending", options: [], follow_ups: [] as object[], moved_to: null, generated: false, created_at: "2026-01-03T10:00:00Z", reviewed_at: null, comment: null, feedback: [], earlier: [] };
function reviewOf(ref: string) {
  if (ref === "CAMP-004") {
    return { project_id: "p1", project_name: "Trailhead", project_slug: "trailhead", task_id: "t4", task_ref: "CAMP-004", task_title: "Full camp label", task_status: "blocked", task_description: null, criteria: [], earlier: [],
      current: { ...round, id: "q1", kind: "question", summary: "Should a full camp show **0** or a red Full label?", options: ["Show 0", "Red Full label"], done: [], not_done: [], how_to_check: null, details: "DEC-001 sets capacity, not the look.", screenshots: [] } };
  }
  if (ref === "CAMP-003") {
    return { project_id: "p1", project_name: "Trailhead", project_slug: "trailhead", task_id: "t3", task_ref: "CAMP-003", task_title: "Ration balance", task_status: "review", task_description: null, criteria: [], earlier: [],
      current: { ...round, id: null, agent: "codex", generated: true, summary: "Halved the ration drain.", done: ["Ration drain is 0.5 a day"], not_done: [], how_to_check: null, details: null, screenshots: [] } };
  }
  return {
    project_id: "p1", project_name: "Trailhead", project_slug: "trailhead", task_id: "t2", task_ref: "CAMP-002", task_title: "Camp upgrade screen", task_status: "review", task_description: "Let players upgrade camps",
    criteria: [{ id: "c1", description: "Shows the cost", is_completed: true }, { id: "c2", description: "Works with a gamepad", is_completed: false }],
    current: { ...round, summary: "Added the **upgrade screen**.", done: ["Cost panel", "Upgrade button"], not_done: ["Gamepad focus"], how_to_check: "Open a camp and press *Upgrade*.",
      details: "> [!WARNING]\n> Saves from 0.3 need a migration.\n\n| Tier | Cost |\n|---|---|\n| 2 | 40 |\n\n<script>alert(1)</script>\n\n[Design notes](https://example.com/notes)",
      screenshots: [{ id: "f1", kind: "screenshot", filename: "upgrade.png", media_type: "image/png", size_bytes: 10, width: 800, height: 600, caption: "The upgrade screen", created_by: "claude", created_at: "2026-01-03T10:00:00Z" }] },
    earlier: [],
  };
}

function setup({ question = false } = {}) {
  const state = { waiting: question ? [camp4, upgrade, rations] : [upgrade, rations], reviewed: [tents] as object[] };
  const made: object[] = [];
  const calls: { url: string; method: string; body?: unknown }[] = [];
  URL.createObjectURL = vi.fn(() => "blob:shot");
  URL.revokeObjectURL = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input), method = options?.method ?? "GET";
    calls.push({ url, method, body: typeof options?.body === "string" ? JSON.parse(options.body) : undefined });
    if (url.startsWith("/api/projects?")) return Response.json([project]);
    if (url === "/api/projects/p1") return Response.json(project);
    if (url === "/api/reviews/pending") return Response.json({ total: state.waiting.length, by_project: { p1: state.waiting.length }, newest: [] });
    if (url === "/api/reviews" || url === "/api/reviews?project_id=p1") return Response.json(state);
    if (url.startsWith("/api/agents/settings")) return Response.json({ default_agent: "claude" });
    const decision = url.match(/^\/api\/projects\/p1\/tasks\/(CAMP-\d+)\/review\/decision$/);
    if (decision && method === "POST") {
      const verdict = (JSON.parse(String(options?.body)) as { verdict: string }).verdict;
      const status = { accept: "accepted", reject: "rejected", answer: "answered" }[verdict]!;
      const done = state.waiting.find((i) => i.ref === decision[1])!;
      state.waiting = state.waiting.filter((i) => i !== done);
      const key = verdict === "accept" ? `review:a-${done.ref}` : verdict === "answer" ? "review:q1" : "review:r1";
      state.reviewed = [{ ...done, key, reviewed_at: "2026-01-03T11:00:00Z", verdict: status }, ...state.reviewed];
      const detail = reviewOf(decision[1]);
      return Response.json({ ...detail, task_status: verdict === "accept" ? "completed" : "in_progress", current: { ...detail.current, id: verdict === "answer" ? "q1" : "r1", status, reviewed_at: "2026-01-03T11:00:00Z" } });
    }
    const followUps = url.match(/^\/api\/projects\/p1\/tasks\/(CAMP-\d+)\/review\/follow-ups$/);
    if (followUps && method === "POST") {
      const items = (JSON.parse(String(options?.body)) as { items: string[] }).items;
      made.push(...items.map((text, i) => ({ text, task_id: `n${made.length + i}`, task_ref: `CAMP-0${10 + made.length + i}`, task_status: "todo" })));
      const detail = reviewOf(followUps[1]);
      return Response.json({ ...detail, current: { ...detail.current, follow_ups: made } });
    }
    if (url.endsWith("/review/fix-prompt?agent=claude")) return Response.json({ agent: "claude", prompt: "Fix CAMP-002", url: "claude://code/new?q=Fix", folder: null });
    const review = url.match(/^\/api\/projects\/p1\/tasks\/(CAMP-\d+)\/review$/);
    if (review) {
      const decided = state.reviewed.find((i) => (i as { ref: string }).ref === review[1] && ["rejected", "answered"].includes((i as { verdict: string }).verdict)) as { verdict: string } | undefined;
      const detail = reviewOf(review[1]);
      if (decided) return Response.json({ ...detail, task_status: "in_progress", current: { ...detail.current, status: decided.verdict, reviewed_at: "2026-01-03T11:00:00Z", comment: "Gamepad focus is missing" } });
      return Response.json({ ...detail, current: { ...detail.current, follow_ups: made } });
    }
    if (url.includes("/review-files/")) return new Response(new Blob(["png"], { type: "image/png" }));
    return Response.json([]);
  }));
  return { calls, state };
}
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Review screen", () => {
  it("lists finished work on the left with who did it, and opens the newest", async () => {
    setup();
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    const waiting = await within(timeline).findByRole("list", { name: "Needs review" });
    const rows = within(waiting).getAllByRole("button");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("aria-current", "true");
    expect(within(rows[0]).getByText("Claude Code")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/^Done /)).toBeInTheDocument();
    expect(within(rows[1]).getByText("Codex")).toBeInTheDocument();
    expect(within(rows[1]).getByText("From checkpoint")).toBeInTheDocument();
    const reviewed = within(timeline).getByRole("list", { name: "Reviewed" });
    expect(within(reviewed).getByText("Accepted")).toBeInTheDocument();
    expect(within(reviewed).getByText(/^Reviewed /)).toBeInTheDocument();
  });

  it("draws the review as colourful Markdown, never as raw HTML", async () => {
    setup();
    renderAt("/review");
    const panel = await screen.findByRole("region", { name: "Selected review" });
    expect(await within(panel).findByText("Cost panel")).toBeInTheDocument();
    expect(within(panel).getByText("upgrade screen").tagName).toBe("STRONG");
    expect(within(panel).getByRole("region", { name: /^Done/ })).toBeInTheDocument();
    expect(within(within(panel).getByRole("region", { name: /^Not done/ })).getByText("Gamepad focus")).toBeInTheDocument();
    expect(within(panel).getByRole("note")).toHaveTextContent("Saves from 0.3 need a migration.");
    expect(within(panel).getByRole("table")).toBeInTheDocument();
    expect(panel.querySelector("script")).toBeNull();
    // Links never navigate away from the app.
    const link = within(panel).getByRole("link", { name: "Design notes" });
    expect(link).not.toHaveAttribute("target");
    const shot = within(panel).getByRole("button", { name: "View The upgrade screen" });
    await waitFor(() => expect(shot.querySelector("img")).toHaveAttribute("src", "blob:shot"));
    // Criteria start ticked while the work waits: you untick what isn't met.
    expect(within(panel).getByText("2 of 2 criteria ticked")).toBeInTheDocument();
    expect(within(panel).getByRole("checkbox", { name: "Works with a gamepad" })).toBeChecked();
  });

  it("accepts the work with your ticks, makes tasks from what was left, and moves on", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    renderAt("/review");
    await screen.findByText("Cost panel");
    await user.click(screen.getByRole("checkbox", { name: "Works with a gamepad" }));
    expect(screen.getByText("1 of 2 criteria ticked")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "When I accept, make tasks from the 2 lines left" })).toBeChecked();
    await user.selectOptions(screen.getByRole("combobox", { name: "Column for the new tasks" }), "backlog");
    await user.click(screen.getByRole("button", { name: "Accept" }));
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/decision"))?.body).toEqual({
      verdict: "accept", comment: null,
      criteria: [{ id: "c1", met: true }, { id: "c2", met: false }],
      follow_ups: ["Gamepad focus", "Works with a gamepad"], follow_up_status: "backlog",
    });
    expect(await screen.findByText("Ration drain is 0.5 a day")).toBeInTheDocument();
    expect(screen.getByText("The agent didn't write a review, so this is its last checkpoint.")).toBeInTheDocument();
  });

  it("rejects only with a comment, quotes lines into it, and offers to open the agent", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    const openAgent = vi.fn(async () => true);
    vi.stubGlobal("projectBrainDesktop", { apiToken: "", install: "linux", openAgent });
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn(async () => undefined) }, configurable: true });
    renderAt("/review");
    await screen.findByText("Cost panel");
    const reject = screen.getByRole("button", { name: "Reject" });
    expect(reject).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Quote “Gamepad focus”/ }));
    const box = screen.getByLabelText("Your comment for the agent");
    expect(box).toHaveValue("> Gamepad focus\n");
    await user.type(box, "Still missing");
    expect(reject).toBeEnabled();
    await user.click(reject);
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/decision"))?.body).toEqual({ verdict: "reject", comment: "> Gamepad focus\nStill missing", criteria: [{ id: "c1", met: true }, { id: "c2", met: true }] }));
    // The rejected task stays on screen, with the way to hand the comments over now.
    expect(await screen.findByText("Sent back.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Camp upgrade screen" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Open in Claude Code with my comments" }));
    await waitFor(() => expect(openAgent).toHaveBeenCalledWith("claude://code/new?q=Fix"));
    expect(await screen.findByText(/Claude Code opened with the prompt typed in/)).toBeInTheDocument();
  });

  it("makes a task from one Not done line and shows it there", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    renderAt("/review");
    await screen.findByText("Cost panel");
    await user.click(screen.getByRole("button", { name: "Make a task from “Gamepad focus”" }));
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/follow-ups"))?.body).toEqual({ items: ["Gamepad focus"], status: "todo" });
    const chip = await screen.findByRole("link", { name: /CAMP-010/ });
    expect(chip).toHaveTextContent("To do");
    expect(screen.queryByRole("button", { name: "Make a task from “Gamepad focus”" })).not.toBeInTheDocument();
    // Accept then offers only what is still left.
    await user.click(screen.getByRole("checkbox", { name: "Works with a gamepad" }));
    expect(screen.getByRole("checkbox", { name: "When I accept, make a task from the 1 line left" })).toBeInTheDocument();
  });

  it("puts an agent's question on top and sends your answer back", async () => {
    const { calls } = setup({ question: true });
    const user = userEvent.setup();
    const openAgent = vi.fn(async () => true);
    vi.stubGlobal("projectBrainDesktop", { apiToken: "", install: "linux", openAgent });
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn(async () => undefined) }, configurable: true });
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    const asked = await within(timeline).findByRole("list", { name: "Needs your answer" });
    expect(within(asked).getByRole("button")).toHaveAttribute("aria-current", "true");
    expect(within(within(timeline).getByRole("list", { name: "Needs review" })).getAllByRole("button")).toHaveLength(2);
    expect(await screen.findByRole("heading", { name: "Claude Code needs your answer to go on" })).toBeInTheDocument();
    expect(screen.getByText("0").tagName).toBe("STRONG");
    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Send answer" });
    expect(send).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Red Full label" }));
    expect(screen.getByLabelText("Your answer for the agent")).toHaveValue("Red Full label");
    await user.click(send);
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-004/review/decision"))?.body).toEqual({ verdict: "answer", comment: "Red Full label" }));
    expect(await screen.findByText("Answered.")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Open in Claude Code with my answer" }));
    await waitFor(() => expect(openAgent).toHaveBeenCalled());
  });

  it("shows a question you answered in the agent's own chat as answered there", async () => {
    const { state } = setup();
    state.reviewed = [{ ...camp4, key: "review:q9", task_status: "in_progress", reviewed_at: "2026-01-03T11:40:00Z", verdict: "answered", moved_to: "chat" }, ...state.reviewed];
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    const reviewed = await within(timeline).findByRole("list", { name: "Reviewed" });
    expect(within(reviewed).getByText("Answered in the chat")).toBeInTheDocument();
    expect(within(reviewed).queryByText(/on the board/)).not.toBeInTheDocument();
  });

  it("moves through the timeline with J and K", async () => {
    setup();
    const user = userEvent.setup();
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    const first = (await within(timeline).findAllByRole("button"))[0];
    first.focus();
    await user.keyboard("j");
    expect(await screen.findByText("Ration drain is 0.5 a day")).toBeInTheDocument();
    expect(within(timeline).getByRole("button", { name: /CAMP-003/ })).toHaveFocus();
    await user.keyboard("k");
    expect(await screen.findByText("Cost panel")).toBeInTheDocument();
  });

  it("shows one project's work in its Review tab", async () => {
    const { calls } = setup();
    renderAt("/projects/p1/review");
    expect(await screen.findByText("Cost panel")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/reviews?project_id=p1")).toBe(true);
  });
});
