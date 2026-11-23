import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { SendBackToAgent } from "./components/review/ReviewComposer";
import { setLanguage } from "./lib/i18n";
import type { ReviewChat } from "./api/agents";

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

const UNKNOWN: ReviewChat = { kind: "unknown", agent: "claude", url: null, delivered: false, resume: null };
function setup({ question = false, wait = false, singleKeys = true, chat = UNKNOWN, chatKnown = true }: { question?: boolean; wait?: boolean; singleKeys?: boolean; chat?: ReviewChat; chatKnown?: boolean } = {}) {
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
    if (url === "/api/settings/agents") return Response.json({ default_agent: "claude", review_single_keys: singleKeys });
    const decision = url.match(/^\/api\/projects\/p1\/tasks\/(CAMP-\d+)\/review\/decision$/);
    if (decision && method === "POST") {
      const verdict = (JSON.parse(String(options?.body)) as { verdict: string }).verdict;
      const status = { accept: "accepted", reject: "rejected", answer: "answered", approve: "answered" }[verdict]!;
      const done = state.waiting.find((i) => i.ref === decision[1])!;
      state.waiting = state.waiting.filter((i) => i !== done);
      const key = verdict === "accept" ? `review:a-${done.ref}` : verdict === "answer" ? "review:q1" : "review:r1";
      state.reviewed = [{ ...done, key, reviewed_at: "2026-01-03T11:00:00Z", verdict: status }, ...state.reviewed];
      const detail = reviewOf(decision[1]);
      return Response.json({ ...detail, task_status: verdict === "accept" ? "completed" : "in_progress", current: { ...detail.current, id: verdict === "answer" ? "q1" : "r1", status, reviewed_at: "2026-01-03T11:00:00Z", chat_known: chatKnown } });
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
    if (/\/review\/fix-prompt(\?agent=claude)?$/.test(url)) return Response.json({ agent: "claude", task: "CAMP-002", prompt: "Fix CAMP-002", url: "claude://code/new?q=Fix", folder: null, chat });
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
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); setLanguage("system"); });

describe("Review screen", () => {
  it("lists finished work on the left with who did it, and opens the newest", async () => {
    setup();
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    const waiting = await within(timeline).findByRole("list", { name: "Finished work to check" });
    const rows = within(waiting).getAllByRole("button");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("aria-current", "true");
    expect(within(rows[0]).getByText(/^Claude Code · Done /)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/^Codex · /)).toBeInTheDocument();
    // A waiting task in Review needs no "Review" badge; one without the agent's report says so.
    expect(within(rows[0]).queryByText("Review")).not.toBeInTheDocument();
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

  it("keeps a group folded or shown until you press its arrow, also after accepting and a restart", async () => {
    const { state } = setup();
    state.waiting = [upgrade];
    const user = userEvent.setup();
    const { unmount } = renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    await within(timeline).findByRole("list", { name: "Finished work to check" });
    // Accepting the last waiting task opens a reviewed one, but Reviewed stays folded.
    await user.click(await screen.findByRole("button", { name: "Accept and move to Done" }));
    await waitFor(() => expect(within(timeline).getByRole("button", { name: /^Reviewed/ })).toHaveTextContent("2"));
    expect(within(timeline).getByRole("button", { name: /^Reviewed/ })).toHaveAttribute("aria-expanded", "false");
    // Fold "Finished work to check" and show Reviewed, then start again with new work waiting.
    await user.click(within(timeline).getByRole("button", { name: /^Finished work to check/ }));
    await user.click(within(timeline).getByRole("button", { name: /^Reviewed/ }));
    unmount();
    state.waiting = [upgrade, rations];
    renderAt("/review");
    const again = await screen.findByRole("complementary", { name: "Review timeline" });
    await within(again).findByRole("list", { name: "Reviewed" });
    const work = within(again).getByRole("button", { name: /^Finished work to check/ });
    expect(work).toHaveAttribute("aria-expanded", "false");
    expect(work).toHaveTextContent("2");
    // With nothing chosen, the first task you can see opens, not one hidden in a folded group.
    expect(within(within(again).getByRole("list", { name: "Reviewed" })).getAllByRole("button")[0]).toHaveAttribute("aria-current", "true");
    cleanup();
    // A link straight to a task in a folded group opens it on the right; the group stays folded.
    renderAt("/review?item=task:t3");
    const third = await screen.findByRole("complementary", { name: "Review timeline" });
    expect(await screen.findByText("Ration drain is 0.5 a day")).toBeInTheDocument();
    expect(within(third).getByRole("button", { name: /^Finished work to check/ })).toHaveAttribute("aria-expanded", "false");
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

  it("says an acceptance with a comment goes to the chat that did the work", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    renderAt("/review");
    await screen.findByText("Cost panel");
    await user.type(screen.getByRole("textbox", { name: "Your comment for the agent" }), "Good. Add it to the changelog too.");
    await user.click(screen.getByRole("button", { name: "Accept and move to Done" }));
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/decision"))?.body).toMatchObject({
      verdict: "accept", comment: "Good. Add it to the changelog too.",
    });
    expect(await screen.findByText("Accepted. CAMP-002 is in Done. Your comment goes to the chat that did the work.")).toBeInTheDocument();
  });

  it("does not say the comment goes to a chat when Moah does not know the chat", async () => {
    const { calls } = setup({ chatKnown: false });
    const user = userEvent.setup();
    renderAt("/review");
    await screen.findByText("Cost panel");
    await user.type(screen.getByRole("textbox", { name: "Your comment for the agent" }), "Good. Add it to the changelog too.");
    await user.click(screen.getByRole("button", { name: "Accept and move to Done" }));
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/decision"))?.body).toMatchObject({ verdict: "accept" });
    expect(await screen.findByText("Accepted. CAMP-002 is in Done. Moah doesn't know which chat did the work, so your comment is only saved under Reviewed.")).toBeInTheDocument();
    expect(screen.queryByText(/goes to the chat/)).not.toBeInTheDocument();
  });

  it("says it in Russian too, with the chat known and not", async () => {
    setLanguage("ru");
    setup();
    const user = userEvent.setup();
    renderAt("/review");
    await screen.findByText("Cost panel");
    await user.type(screen.getByRole("textbox", { name: "Ваш комментарий для агента" }), "Хорошо.");
    await user.click(screen.getByRole("button", { name: "Принять и перенести в «Готово»" }));
    expect(await screen.findByText("Принято. CAMP-002 в «Готово». Ваш комментарий уйдёт в чат, который делал работу.")).toBeInTheDocument();
    cleanup(); vi.unstubAllGlobals();
    setup({ chatKnown: false });
    renderAt("/review");
    await screen.findByText("Cost panel");
    await user.type(screen.getByRole("textbox", { name: "Ваш комментарий для агента" }), "Хорошо.");
    await user.click(screen.getByRole("button", { name: "Принять и перенести в «Готово»" }));
    expect(await screen.findByText("Принято. CAMP-002 в «Готово». Moah не знает, какой чат делал работу, поэтому комментарий только сохранён в «Проверено».")).toBeInTheDocument();
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
    // Nothing was written, so nothing is said about a chat.
    expect(await screen.findByText("Accepted. CAMP-002 is in Done.")).toBeInTheDocument();
    expect(screen.queryByText(/goes to the chat/)).not.toBeInTheDocument();
    // The next task came without a report: its lines are picked out of the agent's notes, in the same frames.
    expect(await screen.findByText("Codex wrote no report, so this is picked out of its notes on the task.")).toBeInTheDocument();
    expect(screen.getByText("Lines about other tasks are left out.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /^Done/ })).getByText("Ration drain is 0.5 a day")).toBeVisible();
    expect(within(screen.getByRole("region", { name: /^Not done/ })).getByText("Its notes don't say what is left. Check the task before you accept.")).toBeInTheDocument();
    // Silence in the notes is not "0 not done".
    expect(screen.queryByText("0 not done")).not.toBeInTheDocument();
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
    // Moah does not know which chat asked, so a new chat is offered, and says so.
    expect(await screen.findByText(/The next agent that opens this project sees your comments first/)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Start a new chat in Claude Code with my comments" }));
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
    await user.click(await screen.findByRole("button", { name: "Start a new chat in Claude Code with my answer" }));
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
    // Also when focus is not in the list, e.g. after clicking in the review.
    first.blur();
    await user.keyboard("j");
    expect(await screen.findByRole("heading", { level: 2, name: "Ration balance" })).toBeInTheDocument();
  });

  it("goes through a pile from the keyboard: A accepts and opens the next, S starts a comment", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    await screen.findByText("Cost panel");
    // Work that came without the agent's own report says so on its line.
    expect(within(within(timeline).getByRole("button", { name: /CAMP-003/ })).getByText("No report")).toBeInTheDocument();
    expect(within(within(timeline).getByRole("button", { name: /CAMP-002/ })).queryByText("No report")).not.toBeInTheDocument();
    // Typing an "a" in the comment box is just a letter.
    await user.keyboard("s");
    const box = screen.getByRole("textbox", { name: "Your comment for the agent" });
    expect(box).toHaveFocus();
    await user.keyboard("a");
    expect(box).toHaveValue("a");
    expect(calls.some((c) => c.url.endsWith("/review/decision"))).toBe(false);
    await user.clear(box);
    box.blur();
    // Ticking a criterion doesn't swallow the key: A still accepts.
    await user.click(screen.getByRole("checkbox", { name: /Works with a gamepad/ }));
    await user.keyboard("a");
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/decision"))?.body).toMatchObject({ verdict: "accept" });
    expect(await screen.findByText("Codex wrote no report, so this is picked out of its notes on the task.")).toBeInTheDocument();
    // A quick Accept can be taken back from its notice.
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/undo"))).toBe(true));
  });

  it("opens the work one agent note covered as one batch and accepts it in one go", async () => {
    const { calls, state } = setup();
    for (const item of state.waiting as { ref: string; batch?: string; batch_title?: string }[]) {
      if (item.ref === "CAMP-002" || item.ref === "CAMP-003") Object.assign(item, { batch: "batch:n1", batch_title: "Supply batch" });
    }
    const user = userEvent.setup();
    renderAt("/review");
    const timeline = await screen.findByRole("complementary", { name: "Review timeline" });
    const group = await within(timeline).findByRole("list", { name: "Batch: Supply batch" });
    expect(within(group).getAllByRole("button")).toHaveLength(2);
    await user.click(within(timeline).getByRole("button", { name: /Supply batch/ }));
    const tasks = await screen.findByRole("list", { name: "Tasks in this batch" });
    // Each task with its own lines, picked out of the notes for one without a report.
    expect(await within(tasks).findByText("Cost panel")).toBeInTheDocument();
    expect(await within(tasks).findByText("Ration drain is 0.5 a day")).toBeInTheDocument();
    // Unfinished work (CAMP-002 has "Gamepad focus" not done) starts unticked, with the reason.
    const unfinished = await screen.findByRole("checkbox", { name: "Accept CAMP-002 with the batch" });
    expect(unfinished).not.toBeChecked();
    expect(within(tasks).getByText("Left unticked: 1 not done")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Accept CAMP-003 with the batch" })).toBeChecked();
    // Ticking it shows it would go too; unticking leaves it for later again.
    await user.click(unfinished);
    expect(await screen.findByRole("button", { name: "Accept 2 and move to Done" })).toBeInTheDocument();
    await user.click(unfinished);
    await user.click(screen.getByRole("button", { name: "Accept 1 and move to Done" }));
    const decided = calls.filter((c) => c.method === "POST" && c.url.endsWith("/review/decision"));
    expect(decided.map((c) => c.url)).toEqual(["/api/projects/p1/tasks/CAMP-003/review/decision"]);
    expect(decided[0].body).toMatchObject({ verdict: "accept" });
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/CAMP-003/review/undo"))).toBe(true));
  });

  it("leaves single-letter keys alone when Settings turned them off", async () => {
    const { calls } = setup({ singleKeys: false });
    const user = userEvent.setup();
    renderAt("/review");
    await screen.findByText("Cost panel");
    await waitFor(() => expect(calls.some((c) => c.url === "/api/settings/agents")).toBe(true));
    await user.keyboard("ajks");
    expect(calls.some((c) => c.url.endsWith("/review/decision"))).toBe(false);
    expect(screen.getByRole("textbox", { name: "Your comment for the agent" })).not.toHaveFocus();
    expect(screen.queryByText(/Keys: A accepts/)).not.toBeInTheDocument();
    // The button still works.
    await user.click(screen.getByRole("button", { name: /Accept and move to Done/ }));
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/CAMP-002/review/decision"))?.body).toMatchObject({ verdict: "accept" });
  });

  it("shows one project's work in its Review tab", async () => {
    const { calls } = setup();
    renderAt("/projects/p1/review");
    expect(await screen.findByText("Cost panel")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/reviews?project_id=p1")).toBe(true);
  });
});

// ---- Review's button goes to the chat that asked ----------------------------------------------

const THREAD = "019a7c2e-5b1f-7c3a-8e4d-2f6b9a1c0d37"; // a Codex thread id, made up
const CHATS = {
  desktop: { kind: "desktop", agent: "claude", url: "claude://code/continue?session=local_5d3b8f72-0c1a-4e96-b7d4-9a2e6c18f035", delivered: false, resume: null },
  terminal: { kind: "terminal", agent: "claude", url: null, delivered: false, resume: null },
  elsewhere: { kind: "elsewhere", agent: "claude", url: null, delivered: false, resume: null },
  codex: { kind: "codex", agent: "codex", url: `codex://threads/${THREAD}`, delivered: false, resume: `codex resume ${THREAD}` },
  unknown: UNKNOWN,
} satisfies Record<string, ReviewChat>;

/** Only the box under a decision, with the backend's answer about the chat: `state.chat` can change between looks. */
function chatBox(chat: ReviewChat, { opened = true, preferred = "claude" }: { opened?: boolean; preferred?: "claude" | "codex" } = {}) {
  const state = { chat, fail: false };
  const looks: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (!url.includes("/review/fix-prompt")) return Response.json({});
    looks.push(url);
    if (state.fail) return Response.json({ detail: "CAMP-002 was not sent back." }, { status: 409 });
    const agent = url.includes("agent=codex") ? "codex" : url.includes("agent=claude") ? "claude" : preferred;
    return Response.json({ agent, task: "CAMP-002", prompt: `Fix CAMP-002 in ${agent}`, url: agent === "codex" ? "codex://new?prompt=Fix" : "claude://code/new?q=Fix", folder: null, chat: state.chat });
  }));
  const openAgent = vi.fn(async () => opened);
  vi.stubGlobal("projectBrainDesktop", { apiToken: "", install: "linux", openAgent });
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return { state, looks, openAgent, writeText };
}
const renderBox = (answered = false) => render(<SendBackToAgent projectId="p1" taskRef="CAMP-002" answered={answered} />);
const noNewChatButton = () => {
  expect(screen.queryByRole("button", { name: /^Start a new chat in / })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^or in / })).not.toBeInTheDocument();
};

describe("Sending a decision back to the chat that asked", () => {
  it("fetches the chat as the box shows and goes to it, never to a new chat", async () => {
    const user = userEvent.setup();
    const { openAgent, looks } = chatBox(CHATS.desktop);
    renderBox();
    const go = await screen.findByRole("button", { name: "Go to the chat" });
    expect(looks).toHaveLength(1); // before any press
    expect(screen.getByText("Sent back.")).toBeInTheDocument();
    // One sentence says where it goes and whether it arrived: no second status line under the buttons.
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("Sent back. Your comments go to the chat that did the work as soon as it can take them.");
    expect(screen.queryByText(/Moah can't open that chat/)).not.toBeInTheDocument();
    expect(screen.queryByText(/The next agent that opens this project/)).not.toBeInTheDocument();
    noNewChatButton();
    await user.click(go);
    expect(openAgent).toHaveBeenCalledExactlyOnceWith(CHATS.desktop.url);
    expect(screen.queryByText(/could not be opened/)).not.toBeInTheDocument();
  });

  it("says an answer is already in the chat once it is delivered", async () => {
    chatBox({ ...CHATS.desktop, delivered: true });
    renderBox(true);
    expect(await screen.findByText("Answered.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Answered. Your answer is already in the chat that asked.");
    expect(screen.getByRole("button", { name: "Go to the chat" })).toBeInTheDocument();
    noNewChatButton();
  });

  it("looks once more after about four seconds when the chat has not taken it yet, and only once", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true }); // the testing library waits on timers too
    const { state, looks } = chatBox(CHATS.desktop);
    renderBox(true);
    expect(await screen.findByText(/Your answer goes to the chat that asked as soon as it can take it\./)).toBeInTheDocument();
    expect(looks).toHaveLength(1);
    state.chat = { ...state.chat, delivered: true };
    await act(async () => { vi.advanceTimersByTime(3500); });
    expect(looks).toHaveLength(1);
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(looks).toHaveLength(2);
    expect(await screen.findByText(/Your answer is already in the chat that asked\./)).toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(looks).toHaveLength(2);
  });

  it("does not look again when the chat already has it, or when no chat is known", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true }); // the testing library waits on timers too
    const delivered = chatBox({ ...CHATS.terminal, delivered: true });
    renderBox();
    await screen.findByText(/Your comments are already in the chat that did the work\./);
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(delivered.looks).toHaveLength(1);
    cleanup();
    const unknown = chatBox(CHATS.unknown);
    renderBox();
    await screen.findByRole("button", { name: "Start a new chat in Claude Code with my comments" });
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(unknown.looks).toHaveLength(1);
  });

  it("stops looking when the box goes away", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true }); // the testing library waits on timers too
    const { looks } = chatBox(CHATS.desktop);
    renderBox();
    await screen.findByRole("button", { name: "Go to the chat" });
    cleanup();
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(looks).toHaveLength(1);
  });

  it("goes to a Codex chat, and offers the command for a terminal with a Copy button", async () => {
    const user = userEvent.setup();
    const { openAgent, writeText } = chatBox(CHATS.codex, { preferred: "codex" });
    renderBox(true);
    await user.click(await screen.findByRole("button", { name: "Go to the chat" }));
    expect(openAgent).toHaveBeenCalledExactlyOnceWith(`codex://threads/${THREAD}`);
    expect(screen.getByRole("status")).toHaveTextContent("Answered. Your answer goes to the chat that asked as soon as it can take it.");
    expect(screen.getByText("Or in a terminal:")).toBeInTheDocument();
    expect(screen.getByText(`codex resume ${THREAD}`)).toBeInTheDocument();
    noNewChatButton();
    await user.click(screen.getByRole("button", { name: "Copy command" }));
    expect(writeText).toHaveBeenCalledExactlyOnceWith(`codex resume ${THREAD}`);
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it.each(["terminal", "elsewhere"] as const)("cannot open a %s chat, says so, and still only offers a new chat as a small extra", async (kind) => {
    const { openAgent } = chatBox(CHATS[kind]);
    renderBox();
    expect(await screen.findByRole("button", { name: "Start a new chat instead" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Go to the chat" })).not.toBeInTheDocument();
    noNewChatButton();
    const said = screen.getByRole("status");
    expect(said).toHaveTextContent("Sent back. Your comments go to the chat that did the work as soon as it can take them.");
    expect(said).not.toHaveTextContent("Moah can't");
    // The reason it cannot open the chat is one muted line, below the buttons.
    const why = screen.getByText("Moah can't open that chat from here: it runs in a terminal or outside the Claude app.");
    expect(screen.getByRole("button", { name: "Start a new chat instead" }).compareDocumentPosition(why) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText(/Or in a terminal/)).not.toBeInTheDocument();
    expect(openAgent).not.toHaveBeenCalled();
  });

  it("says a terminal chat already took the answer", async () => {
    chatBox({ ...CHATS.terminal, delivered: true });
    renderBox(true);
    expect(await screen.findByText(/Your answer is already in the chat that asked\./)).toBeInTheDocument();
  });

  it("offers a new chat only when it does not know the chat, labelled as one, in either agent", async () => {
    const user = userEvent.setup();
    const { openAgent, writeText } = chatBox(CHATS.unknown);
    renderBox(true);
    expect(await screen.findByText(/The next agent that opens this project sees your answer first\. Or hand it over now:/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Go to the chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start a new chat instead" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start a new chat in Claude Code with my answer" }));
    await waitFor(() => expect(openAgent).toHaveBeenLastCalledWith("claude://code/new?q=Fix"));
    expect(writeText).toHaveBeenCalledWith("Fix CAMP-002 in claude");
    expect(await screen.findByText(/Claude Code opened with the prompt typed in/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "or in Codex" }));
    await waitFor(() => expect(openAgent).toHaveBeenLastCalledWith("codex://new?prompt=Fix"));
    expect(await screen.findByText(/Codex opened with the prompt typed in/)).toBeInTheDocument();
  });

  it("starts a new chat from the small link in the chat's own agent, with the prompt typed in", async () => {
    const user = userEvent.setup();
    const { openAgent, writeText } = chatBox(CHATS.codex, { preferred: "claude" });
    renderBox();
    await user.click(await screen.findByRole("button", { name: "Start a new chat instead" }));
    await waitFor(() => expect(openAgent).toHaveBeenCalledExactlyOnceWith("codex://new?prompt=Fix"));
    expect(writeText).toHaveBeenCalledWith("Fix CAMP-002 in codex");
    expect(await screen.findByText(/Codex opened with the prompt typed in/)).toBeInTheDocument();
  });

  it("says when the app could not be opened from here, and a Codex chat still has its command", async () => {
    const user = userEvent.setup();
    const claude = chatBox(CHATS.desktop, { opened: false });
    renderBox();
    await user.click(await screen.findByRole("button", { name: "Go to the chat" }));
    expect(await screen.findByText("Claude Code could not be opened from here.")).toBeInTheDocument();
    expect(claude.openAgent).toHaveBeenCalledOnce();
    cleanup();
    chatBox(CHATS.codex, { opened: false });
    renderBox();
    await user.click(await screen.findByRole("button", { name: "Go to the chat" }));
    expect(await screen.findByText("Codex could not be opened from here.")).toBeInTheDocument();
    expect(screen.getByText(`codex resume ${THREAD}`)).toBeInTheDocument();
  });

  it("says so in a browser, where the desktop app's bridge does not exist", async () => {
    chatBox(CHATS.desktop);
    vi.stubGlobal("projectBrainDesktop", undefined);
    const user = userEvent.setup();
    renderBox();
    await user.click(await screen.findByRole("button", { name: "Go to the chat" }));
    expect(await screen.findByText("Claude Code could not be opened from here.")).toBeInTheDocument();
  });

  it("falls back to the new chat button when the chat could not be looked up", async () => {
    const box = chatBox(CHATS.desktop);
    box.state.fail = true;
    renderBox();
    expect(await screen.findByRole("button", { name: "Start a new chat in Claude Code with my comments" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Go to the chat" })).not.toBeInTheDocument();
  });

  it("shows no buttons while it does not know the chat yet", async () => {
    chatBox(CHATS.desktop);
    renderBox();
    expect(screen.getByText("Sent back.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    await screen.findByRole("button", { name: "Go to the chat" });
  });

  it("works through the Review screen: a rejected task goes to its desktop chat", async () => {
    const { calls } = setup({ chat: CHATS.desktop });
    const user = userEvent.setup();
    const openAgent = vi.fn(async () => true);
    vi.stubGlobal("projectBrainDesktop", { apiToken: "", install: "linux", openAgent });
    renderAt("/review");
    await screen.findByText("Cost panel");
    await user.type(screen.getByLabelText("Your comment for the agent"), "Still missing");
    await user.click(screen.getByRole("button", { name: "Send back" }));
    await user.click(await screen.findByRole("button", { name: "Go to the chat" }));
    expect(openAgent).toHaveBeenCalledExactlyOnceWith(CHATS.desktop.url);
    noNewChatButton();
    expect(calls.filter((c) => c.url.includes("/fix-prompt"))).toHaveLength(1);
  });
});

describe("Sending a decision back, in Russian", () => {
  const texts = {
    desktop: ["Перейти в чат", "Ваши комментарии уйдут в чат, который делал работу, как только он сможет их принять.", "Вместо этого начать новый чат"],
    codex: ["Перейти в чат", "Ваши комментарии уйдут в чат, который делал работу, как только он сможет их принять.", "Или в терминале:"],
    terminal: ["Ваши комментарии уйдут в чат, который делал работу, как только он сможет их принять.", "Moah не может открыть этот чат отсюда: он идёт в терминале или вне приложения Claude.", "Вместо этого начать новый чат"],
    elsewhere: ["Ваши комментарии уйдут в чат, который делал работу, как только он сможет их принять.", "Moah не может открыть этот чат отсюда: он идёт в терминале или вне приложения Claude.", "Вместо этого начать новый чат"],
    unknown: ["Начать новый чат в Claude Code с моими комментариями", "Следующий агент, открывший этот проект, первым делом увидит ваши комментарии. Или передайте их сейчас:"],
  } as const;
  it.each(Object.keys(texts) as (keyof typeof texts)[])("shows a %s chat in Russian", async (kind) => {
    setLanguage("ru");
    chatBox(CHATS[kind]);
    renderBox();
    for (const text of texts[kind]) expect(await screen.findByText(new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
  });

  it("says an answer is already in the chat, and that a new chat is meant, in Russian", async () => {
    setLanguage("ru");
    chatBox({ ...CHATS.desktop, delivered: true });
    renderBox(true);
    expect(await screen.findByRole("status")).toHaveTextContent("Ответ дан. Ваш ответ уже в чате, который спрашивал.");
    cleanup();
    chatBox(CHATS.unknown);
    renderBox(true);
    expect(await screen.findByRole("button", { name: "Начать новый чат в Claude Code с моим ответом" })).toBeInTheDocument();
  });
});
