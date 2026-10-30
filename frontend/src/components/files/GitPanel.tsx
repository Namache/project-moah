import { AlertTriangle, GitBranch } from "lucide-react";
import { Link } from "react-router-dom";
import { useFileActions, useCommits } from "../../hooks/useFiles";
import { useTasks } from "../../hooks/useTasks";
import type { GitStatus } from "../../types/files";
import { shareFolderCommands } from "../../content/integrations";
import { CodeBlock } from "../help/Markdown";
import { formatDate } from "../ui";
import { labels, msg, t, tp, tx } from "../../lib/i18n";

/** Why repository details are missing, by the backend's state; Git's own error text stays as Git wrote it. */
const gitProblems: Record<string, string> = labels({
  not_shared: msg("Project Moah runs in a sandbox and can only see folders you share with it, so it cannot see this one. Choose the folder again with Choose folder in the project settings, or share it read-only (see Help)."),
  no_path: msg("This project has no repository folder yet. Add one in the project settings."),
  path_missing: msg("The repository folder could not be found. It may have moved."),
  git_missing: msg("Git is not available to Project Moah, so repository details can't be shown."),
  not_repo: msg("This folder is not a Git repository."),
  unsafe_repo: msg("Git refused to open this repository because of its folder ownership."),
  timeout: msg("Git took too long to answer."),
});

function sharedFolder(warning: string): string {
  const others = /^The same repository folder is also used by: (.+)\.$/.exec(warning);
  return others ? t("The same repository folder is also used by: {names}.", { names: others[1] }) : warning;
}

export function GitBanner({ git }: { git: GitStatus }) {
  if (git.state !== "ok") {
    return (
      <div role="status" className="flex items-start gap-3 rounded-xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm text-warning-ink">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
        <div><p className="font-semibold">{t("Repository details are not available.")}</p><p className="mt-0.5">{gitProblems[git.state] ?? git.message}</p>{git.root_path && <p className="mt-0.5 break-all text-xs">{t("Expected:")} {git.root_path}</p>}<p className="mt-1 text-xs">{t("Tasks, memory, and your file notes keep working normally.")}</p>
          {git.state === "not_shared" && git.root_path && (() => { const cmd = shareFolderCommands(git.root_path); return (
            <div className="mt-3 text-sm">
              <p>{tx("The easiest fix is to open the project settings and use <b>Choose folder</b>. If you run your agent inside a container such as distrobox, you can instead share just this folder, read-only, with one command. It works from inside the container too.", { b: (text) => <strong>{text}</strong> })}</p>
              <CodeBlock code={cmd.grant} label={t("Share this folder, read-only")} />
              <p className="text-xs">{t("Project Moah can then read this one folder and nothing else, and cannot change it. To undo:")} <code className="rounded bg-surface/60 px-1">{cmd.undo}</code>. <Link to="/help/troubleshooting-container" className="font-medium underline">{t("More about containers")}</Link>.</p>
            </div>); })()}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-xl border border-line bg-surface px-4 py-3 text-sm">
      <span className="inline-flex items-center gap-1.5 font-semibold text-ink"><GitBranch size={15} aria-hidden="true" />{git.detached ? t("Detached HEAD") : git.branch ?? t("No commits yet")}</span>
      <span className="text-ink-muted">{git.clean ? t("Working tree is clean") : tp(git.changed_total, "{count} changed file", "{count} changed files")}</span>
      {git.head && <span className="min-w-0 truncate text-ink-muted"><span className="font-mono text-xs text-forest">{git.head.slice(0, 8)}</span> {git.head_subject}</span>}
      {git.warnings.map((w) => <span key={w} className="text-xs text-warning-ink">{sharedFolder(w)}</span>)}
    </div>
  );
}

export function Commits({ projectId, readonly }: { projectId: string; readonly: boolean }) {
  const commits = useCommits(projectId);
  const tasks = useTasks(projectId);
  const { link, unlink } = useFileActions(projectId);
  if (commits.isPending) return <div role="status" aria-label={t("Loading commits")} className="h-24 animate-pulse rounded-xl bg-surface" />;
  if (commits.isError) return <p role="alert" className="text-sm text-danger-ink">{commits.error.message}</p>;
  const { git, commits: list } = commits.data;
  return (
    <section aria-labelledby="commits-title">
      <h3 id="commits-title" className="text-base font-semibold tracking-tight">{t("Commits and tasks")}</h3>
      <p className="mt-1 text-sm text-ink-muted">{t("A task ID in a commit message is only a suggestion until you confirm it.")}</p>
      {list.length === 0 ? <p className="mt-3 text-sm text-ink-subtle">{git.state === "ok" ? t("No commits yet.") : t("Commits appear here once the repository is available. Confirmed links are kept.")}</p>
        : <ul className="mt-3 divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
          {list.map((c) => (
            <li key={c.sha} className="flex flex-wrap items-start gap-3 px-4 py-3 text-sm">
              <span className="w-20 shrink-0 font-mono text-xs text-forest">{c.short_sha}</span>
              <span className="min-w-0 flex-1"><span className="block font-medium text-ink">{c.subject}</span><span className="text-xs text-ink-subtle">{c.author} {formatDate(c.committed_at)}{!c.in_repository && ` ${t("(no longer in the repository)")}`}</span></span>
              <span className="flex flex-wrap items-center gap-1.5">
                {c.tasks.map((ct) => ct.status === "suggested"
                  ? <span key={ct.task.id} className="inline-flex items-center gap-1 rounded-lg border border-dashed border-forest/50 px-2 py-0.5 text-xs text-forest">{t("Suggested {id}", { id: ct.task.human_id })}{!readonly && <button type="button" onClick={() => link.mutate({ sha: c.sha, task: ct.task.human_id })} className="font-semibold underline">{t("Confirm")}</button>}</span>
                  : <span key={ct.task.id} className="inline-flex items-center gap-1 rounded-lg bg-sage-pale px-2 py-0.5 text-xs font-medium text-forest">{ct.task.human_id}{!readonly && <button type="button" aria-label={t("Unlink {task} from {commit}", { task: ct.task.human_id, commit: c.short_sha })} onClick={() => unlink.mutate({ sha: c.sha, task: ct.task.human_id })}>×</button>}</span>)}
                {!readonly && c.in_repository && <select aria-label={t("Link {commit} to a task", { commit: c.short_sha })} value="" onChange={(e) => e.target.value && link.mutate({ sha: c.sha, task: e.target.value })} className="field-input !min-h-8 !w-auto !py-1 text-xs"><option value="">{t("Link to task…")}</option>{(tasks.data ?? []).filter((t) => !c.tasks.some((x) => x.task.id === t.id && x.status === "confirmed")).map((t) => <option key={t.id} value={t.human_id}>{t.human_id} {t.title}</option>)}</select>}
              </span>
            </li>
          ))}
        </ul>}
      {(link.isError || unlink.isError) && <p role="alert" className="mt-2 text-sm text-danger-ink">{(link.error ?? unlink.error)?.message}</p>}
    </section>
  );
}
