import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { usageReport } from "./test/usageFixture";

const project = { id: "p1", name: "Trailhead", slug: "trailhead", description: "A game", icon: "⛰️", accent: "#D99A53", root_path: "/repo", status: "active", current_focus_task_id: "t1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };
const task = { id: "t1", project_id: "p1", milestone_id: null, human_id: "CAMP-001", title: "Camp capacity", status: "in_progress", priority: "high", next_action: "Migrate", sort_order: 0, criteria_total: 2, criteria_completed: 1, tags: ["gameplay"], is_focus: true, is_blocked_by_open_dependency: false, created_at: "", updated_at: "" };
const memory = { id: "m1", project_id: "p1", human_id: "DEC-001", type: "decision", title: "Capacity is 6", content: "Six", status: "active", importance: "high", is_pinned: true, is_locked: true, ai_visibility: "always", source_type: null, source_reference: null, confidence: null, supersedes_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", invalidated_at: null, archived_at: null, tags: ["party"], tasks: [], superseded_by: null, supersedes: null };
const proposal = { id: "pr1", project_id: "p1", human_id: "PROP-001", agent: "codex", proposal_type: "update_memory", target_entity_type: "memory", target_entity_id: "m1", target_label: "DEC-001 Capacity", target_locked: true, payload: { content: "8" }, snapshot: null, reason: "Tests", status: "pending", review_note: null, applied_payload: null, error: null, created_at: "2026-01-02T00:00:00Z", reviewed_at: null, changes: ["Content: 6 → 8"] };
const pack = { project_id: "p1", project_name: "Trailhead", task: "CAMP-001", detail_level: "balanced", budget: 1500, estimated_tokens: 400, over_budget: false, text: "PROJECT", sections: [{ key: "task", title: "Current Task", tokens: 40, items: 1 }], items: [], omitted: { hidden: 1 }, warnings: [] };
const git = { state: "ok", message: "ok", root_path: "/repo", branch: "main", detached: false, head: "abcdef12", head_subject: "x", clean: true, changed: [], changed_total: 0, warnings: [] };

const row = { project_id: "p1", project_name: "Trailhead", project_icon: "⛰️", project_accent: "#D99A53", agent: "claude", reviewed_at: null, verdict: null, question: false, round: 1, generated: false };
const timeline = {
  waiting: [
    { ...row, kind: "task", key: "task:t4", ref: "CAMP-004", title: "Full camp label", summary: "Should a full camp show 0?", done_at: "2026-01-03T11:00:00Z", screenshots: 0, question: true, task_status: "blocked" },
    { ...row, kind: "task", key: "task:t2", ref: "CAMP-002", title: "Camp upgrade screen", summary: "Added the upgrade screen", done_at: "2026-01-03T10:00:00Z", screenshots: 1 },
    { ...row, kind: "suggestion", key: "proposal:pr1", ref: "PROP-001", title: "Change DEC-001", summary: "Tests", agent: "codex", done_at: "2026-01-02T00:00:00Z", screenshots: 0 },
  ],
  reviewed: [{ ...row, kind: "task", key: "review:r0", ref: "CAMP-000", title: "Tents", summary: "Tents", done_at: "2026-01-01T09:00:00Z", reviewed_at: "2026-01-01T12:00:00Z", verdict: "accepted", screenshots: 0 }],
};
const review = {
  project_id: "p1", project_name: "Trailhead", project_slug: "trailhead", task_id: "t2", task_ref: "CAMP-002", task_title: "Camp upgrade screen", task_status: "review", task_description: "Let players upgrade camps",
  criteria: [{ id: "c1", description: "Shows the cost", is_completed: true }, { id: "c2", description: "Works with a gamepad", is_completed: false }],
  current: { id: "r1", round: 1, agent: "claude", kind: "work", status: "pending", options: [], follow_ups: [], moved_to: null, summary: "Added the **upgrade screen**.", done: ["Cost panel", "Upgrade button"], not_done: ["Gamepad focus"], how_to_check: "Open a camp and press *Upgrade*.", details: "> [!WARNING]\n> Saves from 0.3 need a migration.\n\n| Tier | Cost |\n|---|---|\n| 2 | 40 |", generated: false, created_at: "2026-01-03T10:00:00Z", reviewed_at: null, comment: null,
    screenshots: [{ id: "f1", kind: "screenshot", filename: "upgrade.png", media_type: "image/png", size_bytes: 10, width: 800, height: 600, caption: "The upgrade screen", created_by: "claude", created_at: "2026-01-03T10:00:00Z" }], feedback: [] },
  earlier: [],
};

const detail = { ...task, description: "Prevent recruitment", acceptance_criteria: [{ id: "c1", description: "Track capacity", is_completed: true, sort_order: 0 }, { id: "c2", description: "Migrate", is_completed: false, sort_order: 1 }], relationships: [], milestone: null };

function route(url: string): unknown {
  if (url.startsWith("/api/usage")) return usageReport();
  if (url === "/api/agent-folders") return { created: [], suggested: [], folders: [{ folder: "/home/me/Desktop/Trailhead", status: "suggested", project_id: "p1", project_name: "Trailhead", claude_sessions: 3, codex_sessions: 1, last_seen: null }, { folder: "/home/me/Desktop/Proto", status: "created", project_id: "p2", project_name: "Proto", claude_sessions: 1, codex_sessions: 0, last_seen: null }] };
  if (url.startsWith("/api/projects/global/memory/counts")) return { by_type: { rule: 1 }, pinned: 0, locked: 0 };
  if (url.startsWith("/api/projects/global/memory")) return [{ ...memory, id: "g1", project_id: "global", human_id: "RULE-001", type: "rule", title: "Ask before building", related: [] }];
  if (url.endsWith("/history")) return { chain: [{ id: "m1", human_id: "DEC-001", type: "decision", title: "Capacity is 6", status: "active" }], current_id: "m1" };
  if (/^\/api\/projects\/p1\/memory\/(DEC-001|m1)$/.test(url)) return memory;
  if (/^\/api\/projects\/p1\/tasks\/(CAMP-001|t1)$/.test(url)) return detail;
  if (url.startsWith("/api/projects?")) return [project];
  if (url === "/api/projects/p1") return project;
  if (url.startsWith("/api/projects/p1/tasks?") || url === "/api/projects/p1/tasks") return [task];
  if (url.startsWith("/api/projects/p1/memory/counts")) return { by_type: { decision: 1 }, pinned: 1, locked: 1 };
  if (url.startsWith("/api/projects/p1/memory")) return [memory];
  if (url.startsWith("/api/projects/p1/proposals?")) return [proposal];
  if (url === "/api/proposals/pending") return { total: 1, by_project: { p1: 1 } };
  if (url === "/api/reviews/pending") return { total: 2, by_project: { p1: 2 }, newest: [] };
  if (url === "/api/reviews" || url === "/api/reviews?project_id=p1") return timeline;
  if (url === "/api/projects/p1/proposals/PROP-001") return proposal;
  if (url === "/api/projects/p1/tasks/CAMP-002/review") return review;
  if (url === "/api/projects/p1/tasks/CAMP-004/review") return { ...review, task_id: "t4", task_ref: "CAMP-004", task_title: "Full camp label", task_status: "blocked", criteria: [], current: { ...review.current, id: "q1", kind: "question", summary: "Should a full camp show 0?", options: ["Show 0", "Red Full label"], done: [], not_done: [], how_to_check: null, screenshots: [] } };
  if (url.startsWith("/api/agents/settings")) return { default_agent: "claude" };
  if (url.startsWith("/api/projects/p1/context")) return pack;
  if (url === "/api/projects/p1/files/tree") return { git, entries: [{ path: "a.gd", file_id: null, has_notes: false, stale: null, changed: null }], truncated: false, source: "git" };
  if (url === "/api/projects/p1/git/commits") return { git, commits: [] };
  if (url.includes("/search")) return { items: [{ entity_type: "task", entity_id: "t1", project_id: "p1", project_name: "Trailhead", human_id: "CAMP-001", title: "Camp capacity", snippet: "x", status: "todo", memory_type: null, score: 1, updated_at: null }], total: 1, limit: 25, offset: 0 };
  if (url === "/api/system/diagnostics") return { app_version: "0.1.0", python: "3", platform: "Linux", sqlite_version: "3", database: { path: "/x.db", size_bytes: 1000, migration: "0007_proposals", integrity: "ok", foreign_key_problems: 0, search_index_ready: true }, counts: { projects: 1 }, git: { available: true, version: "git 2" }, mcp: { command: "x", tools: 15 } };
  return [];
}
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);

beforeEach(() => { vi.stubGlobal("fetch", vi.fn(async (u: RequestInfo | URL) => Response.json(route(String(u))))); HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); }; HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); }; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// jsdom cannot measure colour or layout, so those rules are left to manual checks.
const rules = { "color-contrast": { enabled: false }, "scrollable-region-focusable": { enabled: false }, region: { enabled: false } };
async function violations(): Promise<string[]> {
  const result = await axe.run(document.body, { rules });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")})`);
}

const pages: [string, string, RegExp | string][] = [
  ["home", "/", "In focus"],
  ["projects", "/projects", "Current"],
  ["overview", "/projects/p1", "Current focus"],
  ["task board", "/projects/p1/tasks", "Camp capacity"],
  ["task panel", "/projects/p1/tasks?task=CAMP-001", /Acceptance criteria/],
  ["memory", "/projects/p1/memory", "Capacity is 6"],
  ["memory panel", "/projects/p1/memory?memory=DEC-001", /AI visibility/],
  ["files", "/projects/p1/files", "a.gd"],
  ["ai context", "/projects/p1/context", /about 400 tokens/],
  ["project review", "/projects/p1/review?item=task:t2", "Cost panel"],
  ["review", "/review?item=task:t2", "Cost panel"],
  ["review question", "/review", "Red Full label"],
  ["review suggestion", "/review?item=proposal:pr1", "Content: 6 → 8"],
  ["usage", "/usage", "Tips for you"],
  ["search", "/search?q=camp&project=p1", "Camp capacity"],
  ["help", "/help", "How can we help?"],
  ["help article", "/help/memory", "Replacing a decision"],
  ["settings", "/settings", "Healthy"],
  ["global rules", "/global", "Ask before building"],
];

describe("accessibility", () => {
  it.each(pages)("%s has no structural accessibility violations", async (_name, path, ready) => {
    renderAt(path);
    await screen.findAllByText(ready as string, { exact: typeof ready === "string" }).catch(async () => { await screen.findAllByText(ready as RegExp); });
    expect(await violations()).toEqual([]);
  });
});
