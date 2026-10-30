import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EfficiencyDashboard } from "./components/usage/EfficiencyDashboard";
import { bucketize, formatDuration, formatTokens } from "./components/usage/UsageChart";
import { pickTips } from "./content/efficiency-tips";
import { rangeStart } from "./hooks/useUsage";
import { usageReport } from "./test/usageFixture";

function renderDashboard(report = usageReport()) {
  const urls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => { urls.push(String(input)); return Response.json(report); }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><EfficiencyDashboard /></MemoryRouter></QueryClientProvider>);
  return urls;
}

describe("efficiency dashboard", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("shows live totals, per-project rows, unlinked folders and Codex limits", async () => {
    renderDashboard();
    expect(await screen.findByText("7.9M")).toBeInTheDocument();
    expect(screen.getByText(/Live, updated/)).toBeInTheDocument();
    expect(screen.getAllByText("98%").length).toBeGreaterThan(0); // cache reuse 390M of 397.9M
    expect(screen.getByText("41 h")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "By project" }));
    expect(screen.getByRole("link", { name: "Trailhead" })).toHaveAttribute("href", "/projects/p1");
    expect(screen.getByText("~/Desktop/Scratch")).toBeInTheDocument();
    expect(screen.getByText("No project")).toBeInTheDocument();
    // The 5 hour window is current; the weekly one has already reset and is not shown as used.
    expect(screen.getByRole("meter", { name: "Codex limit: 5 hour window" })).toHaveAttribute("aria-valuenow", "82");
    expect(screen.getByRole("meter", { name: "Codex limit: Weekly" })).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByText("Reset")).toBeInTheDocument();
  });

  it("puts tips that match the numbers first and names their source", async () => {
    renderDashboard();
    const tips = within(await screen.findByRole("region", { name: "Tips for you" }));
    const titles = tips.getAllByText(/./, { selector: "p.font-semibold" }).map((el) => el.textContent);
    expect(titles.slice(0, 2)).toEqual(["Use Sonnet for routine edits", "Codex is close to its limit"]);
    expect(tips.getAllByText(/Claude Code docs|Codex docs/).length).toBeGreaterThan(0);
    await userEvent.click(tips.getByRole("button", { name: "Show all tips" }));
    expect(tips.getAllByText(/./, { selector: "p.font-semibold" }).length).toBeGreaterThan(titles.length);
  });

  it("asks for the chosen range from local midnight and remembers it", async () => {
    const urls = renderDashboard();
    await screen.findByText("7.9M");
    await userEvent.click(screen.getByRole("button", { name: "Today" }));
    const since = new URL(urls.at(-1)!, "http://x").searchParams.get("since")!;
    expect(new Date(since).getTime()).toBe(rangeStart("today").getTime());
    expect(localStorage.getItem("pb-usage-range")).toBe("today");
  });

  it("offers the chart's numbers as a table", async () => {
    renderDashboard();
    await userEvent.click(await screen.findByRole("button", { name: "Show table" }));
    const table = screen.getByRole("columnheader", { name: "Day" }).closest("table")!;
    expect(within(table).getAllByRole("row")).toHaveLength(8); // header and 7 days
  });

  it("says when an agent's logs are missing", async () => {
    renderDashboard(usageReport({ sources: { claude: { found: true }, codex: { found: false } } }));
    expect(await screen.findByText(/Codex logs were not found/)).toBeInTheDocument();
  });
});

describe("interactive dashboard", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("filters by agent and remembers it", async () => {
    const urls = renderDashboard();
    await screen.findByText("7.9M");
    await userEvent.click(screen.getByRole("button", { name: "Codex" }));
    expect(new URL(urls.at(-1)!, "http://x").searchParams.get("agent")).toBe("codex");
    expect(localStorage.getItem("pb-usage-agent")).toBe("codex");
  });

  it("loads one day's breakdown when its bar is clicked, and clears it again", async () => {
    const urls = renderDashboard();
    await screen.findByText("7.9M");
    const bars = within(screen.getByRole("group", { name: /Tokens per day/ })).getAllByRole("button");
    await userEvent.click(bars[6]);
    const params = new URL(urls.at(-1)!, "http://x").searchParams;
    expect(new Date(params.get("until")!).getTime() - new Date(params.get("since")!).getTime()).toBe(86_400_000);
    expect(bars[6]).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(await screen.findByRole("button", { name: "Show the whole range" }));
    expect(bars[6]).toHaveAttribute("aria-pressed", "false");
  });

  it("switches the chart between tokens, time and sessions", async () => {
    renderDashboard();
    await screen.findByText("7.9M");
    await userEvent.click(screen.getByRole("button", { name: "Active time" }));
    expect(screen.getByRole("group", { name: /Active time per day/ })).toBeInTheDocument();
  });

  it("shows models, tools and sessions in tabs", async () => {
    renderDashboard();
    expect(await screen.findByText("Claude Opus 5.5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "By tool" }));
    expect(screen.getAllByText("Terminal commands").length).toBe(2); // Claude Bash and Codex exec
    expect(screen.getByText("3.1M chars")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "By session" }));
    expect(screen.getByText(/compacted 3×/)).toBeInTheDocument();
    expect(screen.getByRole("tabpanel", { name: "By session" })).toBeInTheDocument();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "By model" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "By model" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "By tool" })).toHaveAttribute("tabindex", "-1");
  });

  it("gives tips with the number behind them, and hides one on request", async () => {
    renderDashboard();
    const tips = within(await screen.findByRole("region", { name: "Tips for you" }));
    expect(tips.getByText("96% of Claude's replies in this range used Opus.")).toBeInTheDocument();
    expect(tips.getByText("Codex compacted its conversations 24 times in this range.")).toBeInTheDocument();
    await userEvent.click(tips.getByRole("button", { name: "Hide the tip: Use Sonnet for routine edits" }));
    expect(tips.queryByText("Use Sonnet for routine edits")).toBeNull();
    expect(JSON.parse(localStorage.getItem("pb-hidden-tips")!)).toEqual(["opus-share"]);
    await userEvent.click(tips.getByRole("button", { name: "Show 1 hidden tip" }));
    expect(tips.getByText("Use Sonnet for routine edits")).toBeInTheDocument();
  });
});

describe("usage helpers", () => {
  it("formats tokens and durations for people", () => {
    expect([formatTokens(950), formatTokens(12_400), formatTokens(7_900_000), formatTokens(1_900_000_000)]).toEqual(["950", "12k", "7.9M", "1.9B"]);
    expect([formatDuration(0), formatDuration(30), formatDuration(1500), formatDuration(3600 * 41)]).toEqual(["0 min", "under 1 min", "25 min", "41 h"]);
  });

  it("groups hourly data into local days covering the whole range", () => {
    const report = usageReport();
    const days = bucketize(report, false);
    expect(days).toHaveLength(7);
    expect(days.reduce((sum, d) => sum + d.claude + d.codex, 0)).toBe(7_900_000);
  });

  it("only offers general tips when nothing stands out", () => {
    const quiet = usageReport({ longest_session_seconds: 600, codex_limits: null });
    expect(pickTips(quiet, 20).map((t) => t.id)).not.toContain("codex-limit");
  });
});
