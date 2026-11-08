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
const camp5 = { ...camp4, key: "task:t5", ref: "CAMP-005", title: "Camp sign", summary: "Sign mockup ready for review", done_at: "2026-01-03T11:35:00Z" };
function reviewOf(ref: string) {
  if (ref === "CAMP-005") {
    return { project_id: "p1", project_name: "Trailhead", project_slug: "trailhead", task_id: "t5", task_ref: "CAMP-005", task_title: "Camp sign", task_status: "blocked", task_description: null, criteria: [], earlier: [],
      current: { ...round, id: "w1", kind: "question", from_note: true, summary: "Sign mockup ready for review", options: [], done: [], not_done: [], how_to_check: null, details: "Two sign shapes.", screenshots: [] } };
  }
  if (ref === "CAMP-004") {
    return { project_id: "p1", project_name: "Trailhead", project_slug: "trailhead", task_id: "t4", task_ref: "CAMP-004", task_title: "Full camp label", task_status: "blocked", task_description: null, criteria: [], earlier: [],
      current: { ...round, id: "q1", kind: "question", summary: "Should a full camp show **0** or a red Full label?", options: ["Show 0", "Red Full label"], done: [], not_done: [], how_to_check: null, details: "DEC-001 sets capacity, not the look.", screenshots: [] } };
  }
  if (ref === "CAMP-003") {
    return { project_id: "p1", project_name: "Trailhead", project_slug: "trailhead", task_id: "t3", task_ref: "CAMP-003", task_title: "Ration balance", task_status: "review", task_description: "Rations drain too fast on long trips.\n\nHalve the drain.", criteria: [], earlier: [],
      current: { ...round, id: null, agent: "codex", generated: true, summary: "", done: ["Ration drain is 0.5 a day"], not_done: [], how_to_check: null, details: null, screenshots: [],
        next_steps: ["Watch one long trip in the log"], left_out: true,
        notes: [{ title: "Supply batch pushed", created_at: "2026-01-02T09:00:00Z", agent: "codex", summary: "Two supply fixes.", completed_work: "CAMP-003: ration drain is 0.5 a day.\nCAMP-009: water barrels stack.", remaining_work: "CAMP-009 icon is a placeholder.", problems: "", next_steps: "CAMP-003: watch one long trip in the log.", filed_here: false }] } };
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

const acceptedTents = { project_id: "p1", project_name: "Trailhead", project_slug: "trailhead", task_id: "t0", task_ref: "CAMP-000", task_title: "Tents", task_status: "completed", task_description: "Put up the tents", criteria: [], earlier: [],
  current: { ...round, id: "r0", agent: "codex", status: "accepted", reviewed_at: "2026-01-01T12:00:00Z", summary: "Tents are up.", done: ["Four tents"], not_done: [], how_to_check: null, details: null, screenshots: [] } };

function setup({ question = false, wait = false } = {}) {
  const state = { waiting: wait ? [camp5, upgrade] : question ? [camp4, upgrade, rations] : [upgrade, rations], reviewed: [tents] as object[] };
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
      const status = { accept: "accepted", reject: "rejected", answer: "answered", approve: "answered" }[verdict]!;
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
    if (url === "/api/projects/p2/tasks/BOOK-001/review") return Response.json({ ...reviewOf("CAMP-002"), project_id: "p2", project_name: "Bookshelf", task_ref: "BOOK-001", task_title: "Shelf labels" });
    if (url === "/api/projects/p1/tasks/CAMP-000/review/reopen" && method === "POST") {
      const comment = (JSON.parse(String(options?.body)) as { comment: string }).comment;
      state.reviewed = state.reviewed.map((i) => (i as { ref: string }).ref === "CAMP-000" ? { ...i, verdict: "rejected", task_status: "in_progress" } : i);
      return Response.json({ ...acceptedTents, task_status: "in_progress", current: { ...acceptedTents.current, status: "rejected", comment } });
    }
    if (url === "/api/projects/p1/tasks/CAMP-000/review") {
      const now = state.reviewed.find((i) => (i as { ref: string }).ref === "CAMP-000") as { verdict: string };
      return Response.json(now.verdict === "rejected" ? { ...acceptedTents, task_status: "in_progress", current: { ...acceptedTents.current, status: "rejected", comment: "Tents leak" } } : acceptedTents);
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
    const waiting = await within(timeline).findByRole("list", { name: "Finished work to check" });
    const rows = within(waiting).getAllByRole("button");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("aria-current", "true");
    expect(within(rows[0]).getByText("Claude Code")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/^Done /)).toBeInTheDocument();
    expect(within(rows[1]).getByText("Codex")).toBeInTheDocument();
    // Rows are tasks: nothing says "checkpoint" in the list.
    expect(within(timeline).queryByText(/checkpoint/i)).not.toBeInTheDocument();
  });

  it("folds each group away with its arrow and remembers it", async () => {
    setup();
    const user = userEvent.setup();
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    await within(timeline).findByRole("list", { name: "Finished work to check" });
    // Reviewed starts folded, with its count on the heading.
    const reviewedHead = within(timeline).getByRole("button", { name: /^Reviewed/ });
    expect(reviewedHead).toHaveAttribute("aria-expanded", "false");
    expect(reviewedHead).toHaveTextContent("1");
    expect(within(timeline).queryByRole("list", { name: "Reviewed" })).not.toBeInTheDocument();
    await user.click(reviewedHead);
    const reviewed = within(timeline).getByRole("list", { name: "Reviewed" });
    expect(within(reviewed).getByText("Accepted")).toBeInTheDocument();
    expect(within(reviewed).getByText(/^Reviewed /)).toBeInTheDocument();
    await user.click(within(timeline).getByRole("button", { name: /^Finished work to check/ }));
    expect(within(timeline).queryByRole("list", { name: "Finished work to check" })).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("moah.review.folded") ?? "{}")).toEqual({ questions: false, waiting: true, reviewed: false });
    localStorage.removeItem("moah.review.folded");
  });

  it("lets you drag the line between the list and the review", async () => {
    setup();
    const user = userEvent.setup();
    renderAt("/review");
    const line = await screen.findByRole("separator", { name: "Resize the task list" });
    const before = Number(line.getAttribute("aria-valuenow"));
    line.focus();
    await user.keyboard("{ArrowRight}");
    expect(Number(line.getAttribute("aria-valuenow"))).toBe(before + 24);
    expect(localStorage.getItem("moah.review.listWidth")).toBe(String(before + 24));
    await user.dblClick(line);
    expect(Number(line.getAttribute("aria-valuenow"))).toBe(380);
    localStorage.removeItem("moah.review.listWidth");
  });

  it("keeps its screen reader text inside the panes that scroll", async () => {
    setup();
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    await within(timeline).findByRole("list", { name: "Finished work to check" });
    await screen.findByText("Open the task");
    // Screen reader text is positioned absolutely. Unless something inside the scrolling pane is
    // positioned too, that text escapes the pane and the window scrolls on into empty space.
    const positioned = (el: Element) => /(^|\s|:)(relative|absolute|fixed|sticky)(\s|$)/.test(el.className);
    const hidden = Array.from(timeline.parentElement!.querySelectorAll(".sr-only"));
    expect(hidden.length).toBeGreaterThan(2);
    for (const text of hidden) {
      const pane = text.parentElement?.closest(".overflow-y-auto");
      if (!pane) continue;
      let holder = text.parentElement;
      while (holder && !positioned(holder)) holder = holder.parentElement;
      expect(holder !== null && pane.contains(holder), text.textContent ?? "").toBe(true);
    }
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

  it("accepts the work straight into Done, with your ticks, and moves on", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    renderAt("/review");
    await screen.findByText("Cost panel");
    await user.click(screen.getByRole("checkbox", { name: "Works with a gamepad" }));
    expect(screen.getByText("1 of 2 criteria ticked")).toBeInTheDocument();
    // No box that turns leftovers into To do tasks on the way.
    expect(screen.queryByRole("checkbox", { name: /When I accept/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Accept and move to Done" }));
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/decision"))?.body).toEqual({
      verdict: "accept", comment: null,
      criteria: [{ id: "c1", met: true }, { id: "c2", met: false }],
    });
    expect(calls.some((c) => c.url.endsWith("/follow-ups"))).toBe(false);
    // The next task came without a report: its lines are picked out of the agent's notes, in the same frames.
    expect(await screen.findByText("Codex wrote no report, so this is picked out of its notes on the task.")).toBeInTheDocument();
    expect(screen.getByText("Lines about other tasks are left out.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /^Done/ })).getByText("Ration drain is 0.5 a day")).toBeVisible();
    expect(within(screen.getByRole("region", { name: /^Not done/ })).getByText("Its notes list nothing left for this task.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /^What the agent plans next/ })).getByText("Watch one long trip in the log")).toBeInTheDocument();
    // The whole note, other tasks and all, is folded away underneath; so is what was asked.
    const notes = screen.getByText("The agent's full note").closest("details")!;
    expect(notes).not.toHaveAttribute("open");
    expect(within(notes).getByText("Filed under another task")).not.toBeVisible();
    expect(screen.getByText("What was asked").closest("details")).not.toHaveAttribute("open");
  });

  it("rejects only with a comment, quotes lines into it, and offers to open the agent", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    const openAgent = vi.fn(async () => true);
    vi.stubGlobal("projectBrainDesktop", { apiToken: "", install: "linux", openAgent });
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn(async () => undefined) }, configurable: true });
    renderAt("/review");
    await screen.findByText("Cost panel");
    const reject = screen.getByRole("button", { name: "Send back" });
    // Without a comment it says what is missing, where you type, instead of a grey button.
    await user.click(reject);
    expect(screen.getByRole("alert")).toHaveTextContent("Write what should change first, so the agent knows what to fix.");
    const box = screen.getByLabelText("Your comment for the agent");
    expect(box).toHaveFocus();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/decision"))).toBe(false);
    await user.click(screen.getByRole("button", { name: /Quote “Gamepad focus”/ }));
    expect(box).toHaveValue("> Gamepad focus\n");
    await user.type(box, "Still missing");
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
  });

  it("reopens accepted work from Reviewed with a comment", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    renderAt("/review?item=review:r0");
    expect(await screen.findByRole("heading", { level: 2, name: "Tents" })).toBeInTheDocument();
    expect(screen.getByText("You accepted this")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reopen with a comment" }));
    const box = screen.getByLabelText("What is wrong with CAMP-000?");
    await user.click(screen.getByRole("button", { name: "Reopen and send back" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Write what is wrong first");
    await user.type(box, "Tents leak");
    await user.click(screen.getByRole("button", { name: "Reopen and send back" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-000/review/reopen"))?.body).toEqual({ comment: "Tents leak" }));
    // Now it is sent back: the way to hand the comment to an agent shows.
    expect(await screen.findByText("Sent back.")).toBeInTheDocument();
    expect(screen.getByText("You sent this back")).toBeInTheDocument();
  });

  it("filters the list to one project", async () => {
    const { state } = setup();
    const user = userEvent.setup();
    const other = { ...upgrade, key: "task:t9", ref: "BOOK-001", title: "Shelf labels", project_id: "p2", project_name: "Bookshelf", project_accent: "#4A7" };
    state.waiting = [...state.waiting, other];
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    await within(timeline).findByText("Shelf labels");
    await user.selectOptions(within(timeline).getByRole("combobox"), "p2");
    const waiting = within(timeline).getByRole("list", { name: "Finished work to check" });
    expect(within(waiting).getAllByRole("button")).toHaveLength(1);
    expect(within(waiting).getByText("Shelf labels")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Shelf labels" })).toBeInTheDocument();
  });

  it("puts an agent's question on top and sends your answer back", async () => {
    const { calls } = setup({ question: true });
    const user = userEvent.setup();
    const openAgent = vi.fn(async () => true);
    vi.stubGlobal("projectBrainDesktop", { apiToken: "", install: "linux", openAgent });
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn(async () => undefined) }, configurable: true });
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    const asked = await within(timeline).findByRole("list", { name: "Questions from agents" });
    expect(within(asked).getByRole("button")).toHaveAttribute("aria-current", "true");
    expect(within(within(timeline).getByRole("list", { name: "Finished work to check" })).getAllByRole("button")).toHaveLength(2);
    expect(await screen.findByRole("heading", { name: "Claude Code needs your answer to go on" })).toBeInTheDocument();
    expect(screen.getByText("0").tagName).toBe("STRONG");
    expect(screen.queryByRole("button", { name: "Accept and move to Done" })).not.toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Send answer" });
    await user.click(send);
    expect(screen.getByRole("alert")).toHaveTextContent("Write your answer first.");
    await user.click(screen.getByRole("button", { name: "Red Full label" }));
    expect(screen.getByLabelText("Your answer for the agent")).toHaveValue("Red Full label");
    await user.click(send);
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-004/review/decision"))?.body).toEqual({ verdict: "answer", comment: "Red Full label" }));
    expect(await screen.findByText("Answered.")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Open in Claude Code with my answer" }));
    await waitFor(() => expect(openAgent).toHaveBeenCalled());
  });

  it("lets you approve a wait from an agent's note without words", async () => {
    const { calls } = setup({ wait: true });
    const user = userEvent.setup();
    renderAt("/review");
    expect(await screen.findByRole("heading", { name: "Claude Code is waiting for you" })).toBeInTheDocument();
    expect(screen.getByText("From the agent's note")).toBeInTheDocument();
    expect(screen.getByText(/Answering there is fine/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept and move to Done" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send answer" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve and continue" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-005/review/decision"))?.body).toEqual({ verdict: "approve", comment: null }));
  });

  it("shows a question you answered in the agent's own chat as answered there", async () => {
    const { state } = setup();
    state.reviewed = [{ ...camp4, key: "review:q9", task_status: "in_progress", reviewed_at: "2026-01-03T11:40:00Z", verdict: "answered", moved_to: "chat" }, ...state.reviewed];
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    await userEvent.setup().click(await within(timeline).findByRole("button", { name: /^Reviewed/ }));
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
    expect(await screen.findByRole("heading", { level: 2, name: "Ration balance" })).toBeInTheDocument();
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
