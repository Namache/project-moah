import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronDown, Globe2 } from "lucide-react";
import { Button, HelpTip, ProjectAvatar, buttonClasses } from "../ui";
import { useBrainHealth, useShelfSuggestions } from "../../hooks/useGraph";
import { useProjects } from "../../hooks/useProjects";
import { GLOBAL_ID, projectPath } from "../../lib/routes";
import type { ProjectHealth, ShelfSuggestion } from "../../types/graph";
import type { Project } from "../../types/project";
import { labels, msg, t, tp } from "../../lib/i18n";

type Tone = "good" | "attention" | "quiet";
interface Signal { tone: Tone; text: string }
export interface Issue { id: string; project: string; text: string; help?: string; action?: { label: string; to: string } }
export interface Reading { findable: Signal; used: Signal; learning: Signal; issues: Issue[] }

const UNLINKED_LIMIT = 0.25; // more memory than this with no link is worth a look
const SMALL = 10; // fewer memories than this are too few to judge
const FEEDBACK_FROM = 0.5; // agents should say what helped after at least half of their packs
const DOT: Record<Tone, string> = { good: "bg-success", attention: "bg-warning", quiet: "bg-line-strong" };

const pct = (value: number) => `${Math.round(value * 100)}%`;
const projectName = (p: ProjectHealth) => (p.id === GLOBAL_ID ? t("Global rules") : p.name);

/** Three plain signals per project, and the problems worth a person's time, from the health numbers. */
export function readHealth(p: ProjectHealth): Reading {
  const r = p.retrieval;
  const name = projectName(p);
  const issues: Issue[] = [];
  const review = projectPath(p.id, "memory", { review: "links" });
  const issue = (key: string, text: string, extra: Partial<Issue> = {}) => issues.push({ id: `${p.id}:${key}`, project: name, text, ...extra });

  if (p.id === GLOBAL_ID) {
    // Every pack carries the Global rules; other Global records travel only over a project's link.
    const findable: Signal = p.orphans ? { tone: "attention", text: tp(p.orphans, "{count} reaches no agent", "{count} reach no agent") } : { tone: "good", text: t("All reach agents") };
    if (p.orphans) {
      issue("unreached", tp(p.orphans, "{count} memory never reaches an agent. Packs carry your Global rules, but other Global memory only when a project links to it.", "{count} memories never reach an agent. Packs carry your Global rules, but other Global memory only when a project links to it."), {
        help: t("Open the memory and make it a rule, or set it to Always, if every agent should know it."),
        action: { label: t("See them"), to: review },
      });
    }
    return { findable, used: { tone: "quiet", text: t("In every pack") }, learning: { tone: "quiet", text: t("Not tracked") }, issues };
  }

  let findable: Signal = { tone: "quiet", text: t("No memory yet") };
  if (p.memory && p.memory < SMALL) findable = { tone: "quiet", text: t("{linked} of {count} linked", { linked: p.memory - p.orphans, count: p.memory }) };
  else if (p.memory) {
    const unlinked = p.orphans / p.memory;
    const weak = unlinked > UNLINKED_LIMIT;
    findable = { tone: weak ? "attention" : "good", text: t("{share} linked", { share: pct(1 - unlinked) }) };
    if (weak) {
      issue("unlinked", tp(p.memory, "{unlinked} of {count} memory link to nothing, so agents only get them when their words happen to match.", "{unlinked} of {count} memories link to nothing, so agents only get them when their words happen to match.", { unlinked: p.orphans }), { action: { label: t("Check them"), to: review } });
    }
  }
  if (p.guessed_links) {
    issue("guesses", tp(p.guessed_links, "{count} guessed link waits for a yes or no. Guesses are never followed until someone confirms them.", "{count} guessed links wait for a yes or no. Guesses are never followed until someone confirms them."), { action: { label: t("Check them"), to: review } });
  }
  if (p.conflicts) issue("conflicts", tp(p.conflicts, "{count} pair of memories contradict each other.", "{count} pairs of memories contradict each other."), { action: { label: t("Open memory"), to: projectPath(p.id, "memory") } });

  const packs = r.packs_recent;
  const sessions = p.checkpoints_recent;
  let used: Signal = { tone: "good", text: tp(packs, "{count} pack", "{count} packs") };
  if (!packs && !sessions) used = { tone: "quiet", text: t("Quiet lately") };
  else if (sessions >= 3 && packs < sessions / 2) {
    used = { tone: "attention", text: tp(packs, "{count} pack", "{count} packs") };
    issue("unused", tp(packs, "Agents saved {checkpoints} in the last 30 days but asked for context {count} time. Without a context pack they work without your memory, and the brain has nothing to learn from.", "Agents saved {checkpoints} in the last 30 days but asked for context {count} times. Without a context pack they work without your memory, and the brain has nothing to learn from.", { checkpoints: tp(sessions, "{count} checkpoint", "{count} checkpoints") }), {
      help: t("The brief asks agents to call brain_context_pack before substantial work. If they skip it, add that line to the project's own agent instructions (CLAUDE.md or AGENTS.md)."),
    });
  }

  let learning: Signal = { tone: "quiet", text: packs ? t("No feedback yet") : t("No packs yet") };
  if (r.feedback_recent) learning = { tone: "good", text: t("Feedback on {share}", { share: pct(r.feedback_recent / packs) }) };
  if (packs >= 3 && r.feedback_recent / packs < FEEDBACK_FROM) {
    learning = { tone: "attention", text: r.feedback_recent ? t("Feedback on {share}", { share: pct(r.feedback_recent / packs) }) : t("No feedback") };
    issue("feedback", tp(packs, "Agents said what helped after {given} of {count} pack. That feedback is the only way the brain learns which links and memories are worth following.", "Agents said what helped after {given} of {count} packs. That feedback is the only way the brain learns which links and memories are worth following.", { given: r.feedback_recent }), {
      help: t("The brief asks agents to call brain_retrieval_feedback after working from a pack. Remind them in the project's agent instructions if they forget."),
    });
  }
  return { findable, used, learning, issues };
}

const KIND: Record<ShelfSuggestion["kind"], { label: string; accept?: string; done?: string }> = {
  place: labels({ label: msg("File on a shelf"), accept: msg("File them"), done: msg("Filed on {name}.") }),
  needs_category: labels({ label: msg("Needs a category") }),
  merge: labels({ label: msg("Merge shelves"), accept: msg("Merge"), done: msg("Merged into {name}.") }),
  add_member: labels({ label: msg("Add to a shelf"), accept: msg("Add"), done: msg("Added to {name}.") }),
  add_keyword: labels({ label: msg("Shelf keyword"), accept: msg("Add keyword"), done: msg("{name} now listens for that word.") }),
  remove_member: labels({ label: msg("Take off a shelf"), accept: msg("Take off"), done: msg("Taken off {name}.") }),
  pattern: labels({ label: msg("Recurring problem") }),
  share: labels({ label: msg("Same lesson twice"), accept: msg("Share"), done: msg("Shared as one Global memory, linked from both projects.") }),
};
const SUGGESTIONS_SHOWN = 5;

function recordsLabel(shown: number, total: number): string {
  if (total > shown) return tp(total, "Show the first {shown} of {count} item", "Show the first {shown} of {count} items", { shown });
  return tp(shown, "Show the item", "Show the {count} items");
}

/** The suggestion in the app's language; the backend's English message is the fallback for older data. */
function suggestionText(s: ShelfSuggestion): string {
  const a = s.args;
  if (!a) return s.message;
  const n = s.size;
  switch (s.kind) {
    case "place": return tp(n, "{count} linked item about {topic} sits on no shelf. File it on {shelf}?", "{count} linked items about {topic} sit on no shelf. File them on {shelf}?", a);
    case "needs_category": return a.where
      ? tp(n, "{count} item on {where} links mostly to others about {topic}. If they form a narrower category, add it under {parent} and file them there.", "{count} items on {where} link mostly to each other, about {topic}. If they form a narrower category, add it under {parent} and file them there.", a)
      : tp(n, "{count} linked item about {topic} fits no shelf yet. Add the category it belongs to in the knowledge tree and file it there.", "{count} linked items about {topic} fit no shelf yet. Add the category they belong to in the knowledge tree and file them there.", a);
    case "merge": return t("{from} and {into} hold mostly the same items ({share}%). Merge {from} into {into}?", a);
    case "add_member": return t("{label} ({title}) links mostly to items on {shelf} but is not on it. Add it?", { ...a, shelf: s.name });
    case "add_keyword": return t("{count} of the {total} items on {shelf} are about “{word}”. Let the shelf wake on that word?", { ...a, count: n, shelf: s.name });
    case "remove_member": return t("Agents called {label} noise {times} or more times and never useful. Take it off {shelf}?", { ...a, shelf: s.name });
    case "pattern": return tp(n, "{count} bug or warning clusters around {topic}, a recurring failure area. A rule could stop the next one.", "{count} bugs and warnings cluster around {topic}, a recurring failure area. A rule could stop the next one.", a);
    case "share": return t("{first} and {second} say the same thing (“{title}”). Make it one Global memory both projects link to?", a);
  }
}

/** Brain health: whether agents can find what was saved, whether they use it, and whether the
 * brain is learning from them; then the problems worth a look and the shelf suggestions. */
export function BrainHealth() {
  const health = useBrainHealth();
  const projects = useProjects();

  if (health.isError) return <p role="alert" className="mt-8 text-sm text-danger-ink">{t("Brain health could not be loaded: {reason}", { reason: health.error.message })}</p>;
  const data = health.data;
  const rows = (data?.projects ?? []).map((p) => ({ health: p, reading: readHealth(p) }));
  const issues = rows.flatMap((row) => row.reading.issues);
  const avatars = new Map((projects.data ?? []).map((p) => [p.id, p]));

  return (
    <section aria-labelledby="brain-health-title" className="mt-8">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="brain-health-title" className="flex items-center gap-1.5 text-lg font-semibold text-ink">
          {t("Brain health")}
          <HelpTip label={t("brain health")}>{t("Findable: memory a link or shelf leads to. Memory with no links only turns up when an agent's words match it. Used lately: context packs agents asked for in the last 30 days. Learning: how often agents said which memories helped; that feedback is how links grow stronger or fade.")} <Link to="/help/brain-health" className="underline">{t("More about brain health")}</Link></HelpTip>
        </h2>
        {data && <p className="text-sm text-ink-muted">{issues.length ? tp(issues.length, "{count} thing to look at", "{count} things to look at") : t("Nothing needs you right now")}</p>}
      </div>
      {!data ? <p role="status" className="mt-3 text-sm text-ink-subtle">{t("Checking…")}</p> : <>
        {issues.length > 0 && <Issues issues={issues} />}
        <h3 className="mt-6 text-sm font-semibold text-ink">{t("Projects")}</h3>
        <div className="mt-2 overflow-hidden rounded-xl border border-line bg-surface shadow-card">
          <div aria-hidden="true" className="hidden grid-cols-[minmax(0,1fr)_9rem_9rem_9rem_1rem] gap-4 border-b border-line px-4 py-2 text-xs font-medium text-ink-subtle md:grid">
            <span>{t("Project")}</span><span>{t("Findable")}</span><span>{t("Used lately")}</span><span>{t("Learning")}</span><span />
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
    <ul aria-label={t("Needs a look")} className="mt-3 divide-y divide-line rounded-xl border border-line bg-surface shadow-card">
      {issues.map((i) => (
        <li key={i.id} className="flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3 sm:flex-nowrap">
          <span aria-hidden="true" className={`mt-1.5 h-2 w-2 flex-none rounded-full ${DOT.attention}`} />
          <p className="min-w-0 flex-1 basis-56 text-sm leading-6 text-ink">
            <span className="font-medium">{i.project}:</span> {i.text}
            {i.help && <span className="ml-1 inline-flex align-middle"><HelpTip label={t("what to do about {name}", { name: i.project })}>{i.help}</HelpTip></span>}
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
      <span><span className="text-ink-subtle md:sr-only">{t("{label}:", { label })} </span>{signal.text}{signal.tone === "attention" && <span className="sr-only"> {t("(needs a look)")}</span>}</span>
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
        <SignalCell label={t("Findable")} signal={reading.findable} />
        <SignalCell label={t("Used lately")} signal={reading.used} />
        <SignalCell label={t("Learning")} signal={reading.learning} />
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
      ? tp(p.memory, "{count} memory besides your rules and always-visible memory: {linked} linked from a project, {orphans} reaching no agent. Rules go into every pack.", "{count} memories besides your rules and always-visible memory: {linked} linked from a project, {orphans} reaching no agent. Rules go into every pack.", { linked: p.memory - p.orphans, orphans: p.orphans })
      : tp(p.memory, "{count} memory an agent can be led to: {linked} linked or on a shelf, {orphans} found only by matching words.", "{count} memories an agent can be led to: {linked} linked or on a shelf, {orphans} found only by matching words.", { linked: p.memory - p.orphans, orphans: p.orphans }),
    [
      tp(p.links, "{count} link between {nodes} items (memory, tasks, files and milestones).", "{count} links between {nodes} items (memory, tasks, files and milestones).", { nodes: p.nodes }),
      p.guessed_links ? tp(p.guessed_links, "{count} guess is waiting.", "{count} guesses are waiting.") : "",
      p.weak_links ? tp(p.weak_links, "{count} link faded from disuse.", "{count} links faded from disuse.") : "",
      p.conflicts ? tp(p.conflicts, "{count} contradiction.", "{count} contradictions.") : "",
    ].filter(Boolean).join(" "),
  ];
  if (!global) {
    lines.push(r.packs
      ? [
        tp(r.packs_recent, "In the last 30 days agents asked for context {count} time, gave feedback on {feedback} and saved {checkpoints}.", "In the last 30 days agents asked for context {count} times, gave feedback on {feedback} and saved {checkpoints}.", { feedback: r.feedback_recent, checkpoints: tp(p.checkpoints_recent, "{count} checkpoint", "{count} checkpoints") }),
        tp(r.packs, "{count} pack in all.", "{count} packs in all."),
        r.useful_share === null ? "" : t("{share} of the memories agents rated helped.", { share: pct(r.useful_share) }),
      ].filter(Boolean).join(" ")
      : `${t("No agent has asked for a context pack here yet.")} ${tp(p.checkpoints_recent, "Agents saved {count} checkpoint in the last 30 days.", "Agents saved {count} checkpoints in the last 30 days.")}`);
    if (r.through_links !== null) lines.push(`${t("Links brought in {share} of the memories agents got. The rest came from your rules, matching words, shelves and the task itself.", { share: pct(r.through_links) })} ${tp(r.average_records ?? 0, "A pack averages {count} memory, about {tokens} tokens.", "A pack averages {count} memories, about {tokens} tokens.", { tokens: r.average_tokens ?? 0 })}`);
  }
  return (
    <div id={id} className="space-y-4 border-t border-line bg-canvas/60 px-4 py-4 text-sm">
      <ul className="space-y-1.5 leading-6 text-ink-muted">{lines.map((line) => <li key={line}>{line}</li>)}</ul>
      {p.clusters.length > 0 && <div>
        <h4 className="text-xs font-semibold text-ink-muted">{t("Topics the brain found")} <span className="font-normal text-ink-subtle">{t("(memories that link to each other more than to the rest)")}</span></h4>
        <ul aria-label={t("Topics in {name}", { name: projectName(p) })} className="mt-2 flex flex-wrap gap-1.5">
          {p.clusters.map((c) => <li key={c.name} className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-xs text-ink">{c.name} <span className="text-ink-subtle">{c.size}</span>{c.trend && <span className="ml-1 text-forest">{c.trend}</span>}</li>)}
        </ul>
      </div>}
      {p.density.length > 0 && <div>
        <h4 className="text-xs font-semibold text-ink-muted">{t("Shelves")} <span className="font-normal text-ink-subtle">{t("(share of each shelf's memories linked to another one on it)")}</span></h4>
        <ul aria-label={t("How connected the shelves of {name} are", { name: projectName(p) })} className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {p.density.map((d) => (
            <li key={d.shelf_id} className="flex items-center gap-2 text-xs">
              <span className="w-28 truncate text-ink-muted" title={d.name}>{d.name}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-soft"><span className="block h-full rounded-full bg-primary" style={{ width: pct(d.connected) }} /></span>
              <span className="w-24 text-right tabular-nums text-ink-subtle">{t("{share} of {count}", { share: pct(d.connected), count: d.records })}</span>
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
      setError(cause instanceof Error ? cause.message : t("That did not work."));
    }
  }

  if (!suggestions.length && !done) return null;
  const shown = all ? suggestions : suggestions.slice(0, SUGGESTIONS_SHOWN);
  return (
    <div className="mt-6">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
        {t("Suggestions")} <span className="font-normal tabular-nums text-ink-subtle">{suggestions.length}</span>
        <HelpTip label={t("suggestions")}>{t("The brain spots memories that link to each other and offers to group them on shelves. Shelves are views: accepting never changes a memory or a link. Dismissed suggestions are not offered again.")}</HelpTip>
      </h3>
      {error && <p role="alert" className="mt-2 text-sm text-danger-ink">{error}</p>}
      {done && !error && <p role="status" className="mt-2 flex items-center gap-1.5 text-sm text-forest"><Check size={15} aria-hidden="true" />{done}</p>}
      <ul className="mt-2 space-y-2">
        {shown.map((s) => {
          const kind = KIND[s.kind];
          const text = suggestionText(s);
          return (
            <li key={`${s.project_id}|${s.key}`} className="rounded-xl border border-line bg-surface px-4 py-3 shadow-card">
              <div className="flex flex-wrap items-start gap-x-4 gap-y-2 sm:flex-nowrap">
                <div className="min-w-0 flex-1 basis-64">
                  <p className="text-xs text-ink-subtle">{kind.label} · {s.project_name}</p>
                  <p className="mt-0.5 text-sm leading-6 text-ink">{text}</p>
                  {s.records && s.records.length > 0 && <details className="mt-1 text-xs">
                    <summary className="cursor-pointer text-forest">{recordsLabel(s.records.length, s.members.length)}</summary>
                    <ul className="mt-1.5 space-y-0.5 text-ink-muted">{s.records.map((r) => <li key={r.label} className="truncate"><span className="font-medium text-ink">{r.label}</span> {r.title}</li>)}</ul>
                  </details>}
                </div>
                <div className="flex flex-none items-center gap-1.5">
                  {kind.accept
                    ? <Button size="sm" variant="secondary" onClick={() => void act(() => accept.mutateAsync({ projectId: s.project_id, key: s.key }), t(kind.done!, { name: s.name }))}>{kind.accept}</Button>
                    : <Link to={projectPath(s.project_id, "memory", { new: "1", type: "rule" })} className={`inline-flex min-h-8 items-center rounded-lg px-2.5 text-sm font-medium ${buttonClasses.secondary}`}>{t("Write a rule")}</Link>}
                  <Button size="sm" variant="quiet" aria-label={t("Dismiss: {text}", { text })} onClick={() => void act(() => dismiss.mutateAsync({ projectId: s.project_id, key: s.key }), t("Dismissed. It won't be suggested again."))}>{t("Dismiss")}</Button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {suggestions.length > SUGGESTIONS_SHOWN && <Button size="sm" variant="quiet" className="mt-2" aria-expanded={all} onClick={() => setAll((value) => !value)}>{all ? t("Show fewer") : t("Show {count} more", { count: suggestions.length - SUGGESTIONS_SHOWN })}</Button>}
    </div>
  );
}
