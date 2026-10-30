import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronDown, Globe2 } from "lucide-react";
import { Button, HelpTip, ProjectAvatar, buttonClasses } from "../ui";
import { useBrainHealth, useShelfSuggestions } from "../../hooks/useGraph";
import { useProjects } from "../../hooks/useProjects";
import { GLOBAL_ID, projectPath } from "../../lib/routes";
import type { ProjectHealth, ShelfSuggestion } from "../../types/graph";
import type { Project } from "../../types/project";

type Tone = "good" | "attention" | "quiet";
interface Signal { tone: Tone; text: string }
export interface Issue { id: string; project: string; text: string; help?: string; action?: { label: string; to: string } }
export interface Reading { findable: Signal; used: Signal; learning: Signal; issues: Issue[] }

const UNLINKED_LIMIT = 0.25; // more memory than this with no link is worth a look
const SMALL = 10; // fewer memories than this are too few to judge
const FEEDBACK_FROM = 0.5; // agents should say what helped after at least half of their packs
const DOT: Record<Tone, string> = { good: "bg-success", attention: "bg-warning", quiet: "bg-line-strong" };

const pct = (value: number) => `${Math.round(value * 100)}%`;
const count = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
const projectName = (p: ProjectHealth) => (p.id === GLOBAL_ID ? "Global rules" : p.name);

/** Three plain signals per project, and the problems worth a person's time, from the health numbers. */
export function readHealth(p: ProjectHealth): Reading {
  const r = p.retrieval;
  const name = projectName(p);
  const issues: Issue[] = [];
  const review = projectPath(p.id, "memory", { review: "links" });
  const issue = (key: string, text: string, extra: Partial<Issue> = {}) => issues.push({ id: `${p.id}:${key}`, project: name, text, ...extra });

  if (p.id === GLOBAL_ID) {
    // Every pack carries the Global rules; other Global records travel only over a project's link.
    const findable: Signal = p.orphans ? { tone: "attention", text: `${p.orphans} reach no agent` } : { tone: "good", text: "All reach agents" };
    if (p.orphans) {
      issue("unreached", `${count(p.orphans, "record")} never ${p.orphans === 1 ? "reaches" : "reach"} an agent. Packs carry your Global rules, but other Global records only when a project links to them.`, {
        help: "Open the record and make it a rule, or set it to Always, if every agent should know it.",
        action: { label: "See them", to: review },
      });
    }
    return { findable, used: { tone: "quiet", text: "In every pack" }, learning: { tone: "quiet", text: "Not tracked" }, issues };
  }

  let findable: Signal = { tone: "quiet", text: "No memory yet" };
  if (p.memory && p.memory < SMALL) findable = { tone: "quiet", text: `${p.memory - p.orphans} of ${p.memory} linked` };
  else if (p.memory) {
    const unlinked = p.orphans / p.memory;
    const weak = unlinked > UNLINKED_LIMIT;
    findable = { tone: weak ? "attention" : "good", text: `${pct(1 - unlinked)} linked` };
    if (weak) {
      issue("unlinked", `${p.orphans.toLocaleString()} of ${count(p.memory, "memory", "memories")} link to nothing, so agents only get them when their words happen to match.`, { action: { label: "Check them", to: review } });
    }
  }
  if (p.guessed_links) {
    issue("guesses", `${count(p.guessed_links, "guessed link")} ${p.guessed_links === 1 ? "waits" : "wait"} for a yes or no. Guesses are never followed until someone confirms them.`, { action: { label: "Check them", to: review } });
  }
  if (p.conflicts) issue("conflicts", `${count(p.conflicts, "pair")} of records contradict each other.`, { action: { label: "Open memory", to: projectPath(p.id, "memory") } });

  const packs = r.packs_recent;
  const sessions = p.checkpoints_recent;
  let used: Signal = { tone: "good", text: count(packs, "pack") };
  if (!packs && !sessions) used = { tone: "quiet", text: "Quiet lately" };
  else if (sessions >= 3 && packs < sessions / 2) {
    used = { tone: "attention", text: count(packs, "pack") };
    issue("unused", `Agents saved ${count(sessions, "checkpoint")} in the last 30 days but asked for context ${count(packs, "time")}. Without a context pack they work without your memory, and the brain has nothing to learn from.`, {
      help: "The brief asks agents to call brain_context_pack before substantial work. If they skip it, add that line to the project's own agent instructions (CLAUDE.md or AGENTS.md).",
    });
  }

  let learning: Signal = { tone: "quiet", text: packs ? "No feedback yet" : "No packs yet" };
  if (r.feedback_recent) learning = { tone: "good", text: `Feedback on ${pct(r.feedback_recent / packs)}` };
  if (packs >= 3 && r.feedback_recent / packs < FEEDBACK_FROM) {
    learning = { tone: "attention", text: r.feedback_recent ? `Feedback on ${pct(r.feedback_recent / packs)}` : "No feedback" };
    issue("feedback", `Agents said what helped after ${r.feedback_recent} of ${count(packs, "pack")}. That feedback is the only way the brain learns which links and records are worth following.`, {
      help: "The brief asks agents to call brain_retrieval_feedback after working from a pack. Remind them in the project's agent instructions if they forget.",
    });
  }
  return { findable, used, learning, issues };
}

const KIND: Record<ShelfSuggestion["kind"], { label: string; accept?: string; done?: (name: string) => string }> = {
  place: { label: "File on a shelf", accept: "File them", done: (name) => `Filed on ${name}.` },
  needs_category: { label: "Needs a category" },
  merge: { label: "Merge shelves", accept: "Merge", done: (name) => `Merged into ${name}.` },
  add_member: { label: "Add to a shelf", accept: "Add", done: (name) => `Added to ${name}.` },
  add_keyword: { label: "Shelf keyword", accept: "Add keyword", done: (name) => `${name} now listens for that word.` },
  remove_member: { label: "Take off a shelf", accept: "Take off", done: (name) => `Taken off ${name}.` },
  pattern: { label: "Recurring problem" },
  share: { label: "Same lesson twice", accept: "Share", done: () => "Shared as one Global record, linked from both projects." },
};
const SUGGESTIONS_SHOWN = 5;

function recordsLabel(shown: number, total: number): string {
  if (total > shown) return `Show the first ${shown} of ${total} records`;
  return shown === 1 ? "Show the record" : `Show the ${shown} records`;
}

/** Brain health: whether agents can find what was saved, whether they use it, and whether the
 * brain is learning from them; then the problems worth a look and the shelf suggestions. */
export function BrainHealth() {
  const health = useBrainHealth();
  const projects = useProjects();

  if (health.isError) return <p role="alert" className="mt-8 text-sm text-danger-ink">Brain health could not be loaded: {health.error.message}</p>;
  const data = health.data;
  const rows = (data?.projects ?? []).map((p) => ({ health: p, reading: readHealth(p) }));
  const issues = rows.flatMap((row) => row.reading.issues);
  const avatars = new Map((projects.data ?? []).map((p) => [p.id, p]));

  return (
    <section aria-labelledby="brain-health-title" className="mt-8">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="brain-health-title" className="flex items-center gap-1.5 text-lg font-semibold text-ink">
          Brain health
          <HelpTip label="brain health">Findable: memory a link or shelf leads to. Memory with no links only turns up when an agent's words match it. Used lately: context packs agents asked for in the last 30 days. Learning: how often agents said which records helped; that feedback is how links grow stronger or fade. <Link to="/help/brain-health" className="underline">More about brain health</Link></HelpTip>
        </h2>
        {data && <p className="text-sm text-ink-muted">{issues.length ? `${count(issues.length, "thing")} to look at` : "Nothing needs you right now"}</p>}
      </div>
      {!data ? <p role="status" className="mt-3 text-sm text-ink-subtle">Checking…</p> : <>
        {issues.length > 0 && <Issues issues={issues} />}
        <h3 className="mt-6 text-sm font-semibold text-ink">Projects</h3>
        <div className="mt-2 overflow-hidden rounded-xl border border-line bg-surface shadow-card">
          <div aria-hidden="true" className="hidden grid-cols-[minmax(0,1fr)_9rem_9rem_9rem_1rem] gap-4 border-b border-line px-4 py-2 text-xs font-medium text-ink-subtle md:grid">
            <span>Project</span><span>Findable</span><span>Used lately</span><span>Learning</span><span />
          </div>
          <ul className="divide-y divide-line">
            {rows.map(({ health: p, reading }) => <ProjectRow key={p.id} project={p} reading={reading} avatar={avatars.get(p.id)} />)}
          </ul>
        </div>
        <Suggestions suggestions={data.suggestions} />
      </>}
    </section>
  );
}

function Issues({ issues }: { issues: Issue[] }) {
  return (
    <ul aria-label="Needs a look" className="mt-3 divide-y divide-line rounded-xl border border-line bg-surface shadow-card">
      {issues.map((i) => (
        <li key={i.id} className="flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3 sm:flex-nowrap">
          <span aria-hidden="true" className={`mt-1.5 h-2 w-2 flex-none rounded-full ${DOT.attention}`} />
          <p className="min-w-0 flex-1 basis-56 text-sm leading-6 text-ink">
            <span className="font-medium">{i.project}:</span> {i.text}
            {i.help && <span className="ml-1 inline-flex align-middle"><HelpTip label={`what to do about ${i.project}`}>{i.help}</HelpTip></span>}
          </p>
          {i.action && <Link to={i.action.to} className={`inline-flex min-h-8 flex-none items-center rounded-lg px-2.5 text-sm font-medium ${buttonClasses.secondary}`}>{i.action.label}</Link>}
        </li>
      ))}
    </ul>
  );
}

function SignalCell({ label, signal }: { label: string; signal: Signal }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-ink-muted md:text-sm">
      <span aria-hidden="true" className={`h-2 w-2 flex-none rounded-full ${DOT[signal.tone]}`} />
      <span><span className="text-ink-subtle md:sr-only">{label}: </span>{signal.text}{signal.tone === "attention" && <span className="sr-only"> (needs a look)</span>}</span>
    </span>
  );
}

function ProjectRow({ project: p, reading, avatar }: { project: ProjectHealth; reading: Reading; avatar?: Pick<Project, "name" | "icon" | "accent"> }) {
  const [open, setOpen] = useState(false);
  const id = `health-${p.id}`;
  return (
    <li>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)} className="flex w-full flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-3 text-left hover:bg-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-forest md:grid md:grid-cols-[minmax(0,1fr)_9rem_9rem_9rem_1rem]">
        <span className="flex min-w-0 basis-full items-center gap-2.5 md:basis-auto">
          {p.id === GLOBAL_ID ? <span className="flex h-6 w-6 flex-none items-center justify-center rounded-md bg-sage-pale text-forest"><Globe2 size={14} aria-hidden="true" /></span> : avatar ? <ProjectAvatar project={avatar} size="small" /> : null}
          <span className="truncate text-sm font-medium text-ink">{projectName(p)}</span>
        </span>
        <SignalCell label="Findable" signal={reading.findable} />
        <SignalCell label="Used lately" signal={reading.used} />
        <SignalCell label="Learning" signal={reading.learning} />
        <ChevronDown size={16} className={`ml-auto flex-none text-ink-subtle transition-transform md:ml-0 ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && <Details id={id} project={p} />}
    </li>
  );
}

function Details({ id, project: p }: { id: string; project: ProjectHealth }) {
  const r = p.retrieval;
  const global = p.id === GLOBAL_ID;
  const lines = [
    global
      ? `${count(p.memory, "record")} besides your rules and always-visible records: ${p.memory - p.orphans} linked from a project, ${p.orphans} reaching no agent. Rules go into every pack.`
      : `${count(p.memory, "memory", "memories")} an agent can be led to: ${(p.memory - p.orphans).toLocaleString()} linked or on a shelf, ${p.orphans.toLocaleString()} found only by matching words.`,
    `${count(p.links, "link")} between ${count(p.nodes, "record")} (memory, tasks, files and milestones)${p.guessed_links ? `, plus ${count(p.guessed_links, "guess", "guesses")} waiting` : ""}${p.weak_links ? `; ${p.weak_links} faded from disuse` : ""}${p.conflicts ? `; ${count(p.conflicts, "contradiction")}` : ""}.`,
  ];
  if (!global) {
    lines.push(r.packs
      ? `In the last 30 days agents asked for context ${count(r.packs_recent, "time")}, gave feedback on ${r.feedback_recent} and saved ${count(p.checkpoints_recent, "checkpoint")}. ${count(r.packs, "pack")} in all${r.useful_share === null ? "" : `; ${pct(r.useful_share)} of the records agents rated helped`}.`
      : `No agent has asked for a context pack here yet. Agents saved ${count(p.checkpoints_recent, "checkpoint")} in the last 30 days.`);
    if (r.through_links !== null) lines.push(`Links brought in ${pct(r.through_links)} of the records agents got. The rest came from your rules, matching words, shelves and the task itself. A pack averages ${r.average_records ?? 0} records, about ${(r.average_tokens ?? 0).toLocaleString()} tokens.`);
  }
  return (
    <div id={id} className="space-y-4 border-t border-line bg-canvas/60 px-4 py-4 text-sm">
      <ul className="space-y-1.5 leading-6 text-ink-muted">{lines.map((line) => <li key={line}>{line}</li>)}</ul>
      {p.clusters.length > 0 && <div>
        <h4 className="text-xs font-semibold text-ink-muted">Topics the brain found <span className="font-normal text-ink-subtle">(records that link to each other more than to the rest)</span></h4>
        <ul aria-label={`Topics in ${projectName(p)}`} className="mt-2 flex flex-wrap gap-1.5">
          {p.clusters.map((c) => <li key={c.name} className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-xs text-ink">{c.name} <span className="text-ink-subtle">{c.size}</span>{c.trend && <span className="ml-1 text-forest">{c.trend}</span>}</li>)}
        </ul>
      </div>}
      {p.density.length > 0 && <div>
        <h4 className="text-xs font-semibold text-ink-muted">Shelves <span className="font-normal text-ink-subtle">(share of each shelf's records linked to another record on it)</span></h4>
        <ul aria-label={`How connected ${projectName(p)}'s shelves are`} className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {p.density.map((d) => (
            <li key={d.shelf_id} className="flex items-center gap-2 text-xs">
              <span className="w-28 truncate text-ink-muted" title={d.name}>{d.name}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-soft"><span className="block h-full rounded-full bg-primary" style={{ width: pct(d.connected) }} /></span>
              <span className="w-24 text-right tabular-nums text-ink-subtle">{pct(d.connected)} of {d.records}</span>
            </li>
          ))}
        </ul>
      </div>}
    </div>
  );
}

function Suggestions({ suggestions }: { suggestions: ShelfSuggestion[] }) {
  const { accept, dismiss } = useShelfSuggestions();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [all, setAll] = useState(false);

  async function act(action: () => Promise<unknown>, message: string) {
    setError(null);
    try {
      await action();
      setDone(message);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That did not work.");
    }
  }

  if (!suggestions.length && !done) return null;
  const shown = all ? suggestions : suggestions.slice(0, SUGGESTIONS_SHOWN);
  return (
    <div className="mt-6">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
        Suggestions <span className="font-normal tabular-nums text-ink-subtle">{suggestions.length}</span>
        <HelpTip label="suggestions">The brain spots records that link to each other and offers to group them on shelves. Shelves are views: accepting never changes a record or a link. Dismissed suggestions are not offered again.</HelpTip>
      </h3>
      {error && <p role="alert" className="mt-2 text-sm text-danger-ink">{error}</p>}
      {done && !error && <p role="status" className="mt-2 flex items-center gap-1.5 text-sm text-forest"><Check size={15} aria-hidden="true" />{done}</p>}
      <ul className="mt-2 space-y-2">
        {shown.map((s) => {
          const kind = KIND[s.kind];
          return (
            <li key={`${s.project_id}|${s.key}`} className="rounded-xl border border-line bg-surface px-4 py-3 shadow-card">
              <div className="flex flex-wrap items-start gap-x-4 gap-y-2 sm:flex-nowrap">
                <div className="min-w-0 flex-1 basis-64">
                  <p className="text-xs text-ink-subtle">{kind.label} · {s.project_name}</p>
                  <p className="mt-0.5 text-sm leading-6 text-ink">{s.message}</p>
                  {s.records && s.records.length > 0 && <details className="mt-1 text-xs">
                    <summary className="cursor-pointer text-forest">{recordsLabel(s.records.length, s.members.length)}</summary>
                    <ul className="mt-1.5 space-y-0.5 text-ink-muted">{s.records.map((r) => <li key={r.label} className="truncate"><span className="font-medium text-ink">{r.label}</span> {r.title}</li>)}</ul>
                  </details>}
                </div>
                <div className="flex flex-none items-center gap-1.5">
                  {kind.accept
                    ? <Button size="sm" variant="secondary" onClick={() => void act(() => accept.mutateAsync({ projectId: s.project_id, key: s.key }), kind.done!(s.name))}>{kind.accept}</Button>
                    : <Link to={projectPath(s.project_id, "memory", { new: "1", type: "rule" })} className={`inline-flex min-h-8 items-center rounded-lg px-2.5 text-sm font-medium ${buttonClasses.secondary}`}>Write a rule</Link>}
                  <Button size="sm" variant="quiet" aria-label={`Dismiss: ${s.message}`} onClick={() => void act(() => dismiss.mutateAsync({ projectId: s.project_id, key: s.key }), "Dismissed. It won't be suggested again.")}>Dismiss</Button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {suggestions.length > SUGGESTIONS_SHOWN && <Button size="sm" variant="quiet" className="mt-2" aria-expanded={all} onClick={() => setAll((value) => !value)}>{all ? "Show fewer" : `Show ${suggestions.length - SUGGESTIONS_SHOWN} more`}</Button>}
    </div>
  );
}
