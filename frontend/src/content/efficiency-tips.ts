import { labels, locale, msg, t, tp } from "../lib/i18n";
import type { UsageReport } from "../types/usage";

/**
 * Efficiency tips from the vendors' own documentation, read on 2026-10-11:
 * Claude Code "Manage costs effectively" (code.claude.com/docs/en/costs),
 * Codex "Prompting" (learn.chatgpt.com/codex/prompting) and "Pricing" (learn.chatgpt.com/codex/pricing).
 * The app has no network access, so the tips are bundled. Check the pages again when a vendor changes its tools.
 */
export type TipSource = "claude" | "codex";

export const TIP_SOURCES: Record<TipSource, { label: string; url: string }> = {
  claude: labels({ label: msg("Claude Code docs"), url: "https://code.claude.com/docs/en/costs" }, ["label"]),
  codex: labels({ label: msg("Codex docs"), url: "https://learn.chatgpt.com/codex/pricing" }, ["label"]),
};

export interface EfficiencyTip {
  id: string;
  title: string;
  body: string;
  sources: TipSource[];
  /** Higher when the person's own numbers show the tip applies. 0 means it does not apply now. */
  relevance: (report: UsageReport) => number;
  /** The number from the person's own logs that the tip is based on, when there is one. */
  evidence?: (report: UsageReport) => string | null;
}

const HOUR = 3600;
const share = (part: number, whole: number) => (whole > 0 ? part / whole : 0);
const cacheReuse = (r: UsageReport) => share(r.totals.cached_tokens, r.totals.cached_tokens + r.totals.fresh_tokens);
const codexShort = (r: UsageReport) => {
  const w = r.codex_limits?.short;
  return w && !(w.resets_at && new Date(w.resets_at).getTime() < Date.now()) ? w.used_percent : 0;
};
const pct = (n: number) => `${Math.round(n * 100)}%`;
const mchars = (n: number) => (n >= 1e6 ? t("{n} million", { n: new Intl.NumberFormat(locale(), { maximumFractionDigits: 1 }).format(n / 1e6) }) : new Intl.NumberFormat(locale()).format(n));
const toolOut = (r: UsageReport, agent: "claude" | "codex", tool: string) => r.by_tool?.find((t) => t.agent === agent && t.tool === tool);
const hours = (s: number) => { const h = Math.round((s / 3600) * 10) / 10; return tp(h, "{count} hour", "{count} hours"); };

const EFFICIENCY_TIPS: EfficiencyTip[] = ([
  {
    id: "opus-share",
    title: msg("Use Sonnet for routine edits"),
    body: msg("Sonnet handles most coding tasks well and costs less. Switch with /model for simple edits, or lower the effort with /effort, and keep Opus for hard design work."),
    sources: ["claude"],
    relevance: (r) => ((r.signals?.opus_reply_share ?? 0) >= 0.7 && (r.by_agent.claude.fresh_tokens > 0) ? 5 : 0),
    evidence: (r) => t("{share} of Claude's replies in this range used Opus.", { share: pct(r.signals?.opus_reply_share ?? 0) }),
  },
  {
    id: "codex-compactions",
    title: msg("Codex sessions are running long"),
    body: msg("Each compaction rereads and summarizes the whole conversation. Start a new thread per task, and plan first with /plan."),
    sources: ["codex"],
    relevance: (r) => ((r.signals?.compactions.codex ?? 0) >= 5 ? 4 : 0),
    evidence: (r) => tp(r.signals?.compactions.codex ?? 0, "Codex compacted its conversations {count} time in this range.", "Codex compacted its conversations {count} times in this range."),
  },
  {
    id: "claude-compactions",
    title: msg("Claude sessions are running long"),
    body: msg("Compacting rereads the whole conversation. Use /clear between unrelated tasks; /rename first so you can /resume later."),
    sources: ["claude"],
    relevance: (r) => ((r.signals?.compactions.claude ?? 0) >= 5 ? 4 : 0),
    evidence: (r) => tp(r.signals?.compactions.claude ?? 0, "Claude compacted its conversations {count} time in this range.", "Claude compacted its conversations {count} times in this range."),
  },
  {
    id: "terminal-output",
    title: msg("Large command output fills context"),
    body: msg("Ask for filtered output, such as only failing tests, or send test runs and log reading to a subagent so only a summary comes back. A hook can filter test output automatically."),
    sources: ["claude"],
    relevance: (r) => {
      const bash = toolOut(r, "claude", "Bash")?.output_chars ?? 0;
      const all = r.signals?.tool_output_chars.claude ?? 0;
      return bash > 1_000_000 && share(bash, all) > 0.4 ? 4 : 0;
    },
    evidence: (r) => {
      const bash = toolOut(r, "claude", "Bash")?.output_chars ?? 0;
      return t("Claude's terminal commands returned {chars} characters, {share} of all its tool output.", { chars: mchars(bash), share: pct(share(bash, r.signals?.tool_output_chars.claude ?? 0)) });
    },
  },
  {
    id: "file-reads",
    title: msg("Reading whole files is costly"),
    body: msg("Point the agent at the function or lines you mean. For typed languages, a code intelligence plugin lets Claude jump to a definition instead of reading several files."),
    sources: ["claude"],
    relevance: (r) => ((toolOut(r, "claude", "Read")?.output_chars ?? 0) > 3_000_000 ? 3 : 0),
    evidence: (r) => {
      const read = toolOut(r, "claude", "Read");
      return read ? tp(read.calls, "Claude read files {count} time, {chars} characters in total.", "Claude read files {count} times, {chars} characters in total.", { chars: mchars(read.output_chars) }) : null;
    },
  },
  {
    id: "subagents",
    title: msg("Subagents use usage of their own"),
    body: msg("Each subagent runs its own conversation. Use them for noisy, self-contained jobs, give simple ones a smaller model, and keep the number small."),
    sources: ["claude", "codex"],
    relevance: (r) => (((r.signals?.subagents_started.claude ?? 0) + (r.signals?.subagents_started.codex ?? 0)) >= 15 ? 3 : 0),
    evidence: (r) => tp((r.signals?.subagents_started.claude ?? 0) + (r.signals?.subagents_started.codex ?? 0), "{count} subagent was started in this range (Claude {claude}, Codex {codex}).", "{count} subagents were started in this range (Claude {claude}, Codex {codex}).", { claude: r.signals?.subagents_started.claude ?? 0, codex: r.signals?.subagents_started.codex ?? 0 }),
  },
  {
    id: "clear",
    title: msg("Clear between unrelated tasks"),
    body: msg("Run /clear when you switch to different work. The whole conversation is sent again with every message, so old context costs tokens each turn. Use /rename first so you can /resume it later."),
    sources: ["claude"],
    relevance: (r) => (r.longest_session_seconds > 3 * HOUR ? 3 : 1),
  },
  {
    id: "long-session",
    title: msg("Long sessions cost more than they look"),
    body: msg("A one-line question in a session open all day still rereads the whole history. Start fresh, or use /compact with a note on what to keep, for example /compact Focus on test output."),
    sources: ["claude"],
    relevance: (r) => (r.longest_session_seconds > 5 * HOUR ? 4 : 0),
    evidence: (r) => t("The longest session in this range had {hours} of activity.", { hours: hours(r.longest_session_seconds) }),
  },
  {
    id: "cache",
    title: msg("Avoid long breaks in the middle of a task"),
    body: msg("After a break longer than the cache lifetime (an hour on a subscription), the first message reprocesses the full context. Finish or /clear before stepping away."),
    sources: ["claude"],
    relevance: (r) => (r.totals.fresh_tokens > 0 && cacheReuse(r) < 0.9 ? 4 : 0),
    evidence: (r) => t("Only {share} of input came from the cache in this range.", { share: pct(cacheReuse(r)) }),
  },
  {
    id: "plan",
    title: msg("Plan before big changes"),
    body: msg("Use plan mode (Shift+Tab) in Claude Code, or /plan in Codex, so a wrong direction is caught before any files change. Press Escape early if it heads the wrong way."),
    sources: ["claude", "codex"],
    relevance: () => 1,
  },
  {
    id: "specific",
    title: msg("Ask for something specific"),
    body: msg("\"Add input validation to the login function in auth.ts\" costs far less than \"improve this codebase\", which makes the agent scan broadly. Name the files, or attach them with @ in Codex."),
    sources: ["claude", "codex"],
    relevance: () => 1,
  },
  {
    id: "instructions-short",
    title: msg("Keep CLAUDE.md and AGENTS.md short"),
    body: msg("Both load into every session. Keep CLAUDE.md under about 200 lines and move rare workflows into skills, which load only when used. Nest AGENTS.md files to scope them."),
    sources: ["claude", "codex"],
    relevance: () => 1,
  },
  {
    id: "mcp",
    title: msg("Turn off MCP servers you are not using"),
    body: msg("Run /mcp in either tool and disable unused servers; each adds context. Command-line tools such as gh add none. In Claude Code, /context shows what takes space."),
    sources: ["claude", "codex"],
    relevance: () => 1,
  },
  {
    id: "model",
    title: msg("Match the model and effort to the job"),
    body: msg("Use a smaller model or lower effort (/effort in Claude Code) for simple edits, and keep the largest models for hard reasoning. Thinking tokens are billed as output."),
    sources: ["claude", "codex"],
    relevance: (r) => (share(r.totals.output_tokens, r.totals.fresh_tokens) > 0.25 ? 3 : 1),
  },
  {
    id: "codex-limit",
    title: msg("Codex is close to its limit"),
    body: msg("Smaller models have a much larger allowance, and Fast speed uses it up quicker. Keep tasks small and check /status in the Codex command line to see what is left."),
    sources: ["codex"],
    relevance: (r) => (codexShort(r) >= 75 ? 5 : 0),
    evidence: (r) => t("{share} of the current 5 hour window is used.", { share: `${Math.round(codexShort(r))}%` }),
  },
  {
    id: "verbose",
    title: msg("Send noisy work to a subagent"),
    body: msg("Running tests, reading logs or fetching docs fills context fast. A subagent keeps the noise in its own context and returns a summary. Give it a smaller model for simple jobs."),
    sources: ["claude"],
    relevance: () => 1,
  },
  {
    id: "verify",
    title: msg("Give a way to check the work"),
    body: msg("Include the test to run or the expected output. When the agent can verify its own work, it catches mistakes before you have to ask for another round."),
    sources: ["claude", "codex"],
    relevance: () => 1,
  },
  {
    id: "cloud",
    title: msg("Prefer local Codex tasks for small changes"),
    body: msg("Cloud tasks can use more of your allowance than local messages. Keep cloud runs for long, self-contained work."),
    sources: ["codex"],
    relevance: (r) => (r.by_agent.codex.fresh_tokens > r.by_agent.claude.fresh_tokens ? 2 : 0),
  },
] satisfies EfficiencyTip[]).map((tip) => labels(tip, ["title", "body"]));

/** The tips that fit the person's numbers first, then general advice in a stable order. */
export function pickTips(report: UsageReport, count: number, hidden: ReadonlySet<string> = new Set()): EfficiencyTip[] {
  return EFFICIENCY_TIPS.map((tip, index) => ({ tip, index, score: tip.relevance(report) }))
    .filter(({ score, tip }) => score > 0 && !hidden.has(tip.id))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, count)
    .map(({ tip }) => tip);
}
