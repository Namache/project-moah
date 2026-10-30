import { Circle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { activityApi } from "../../api/activity";
import { useMemoryCounts } from "../../hooks/useMemory";
import { useTasks } from "../../hooks/useTasks";
import { readPref, writePref } from "../../lib/prefs";
import type { Project } from "../../types/project";
import { Button } from "../ui";
import { projectPath } from "../../lib/routes";
import { t } from "../../lib/i18n";

export const contextSeenKey = (projectId: string) => `pb-context-seen-${projectId}`;

/** A checklist that completes itself from real data, and can be dismissed for good. */
export function GettingStarted({ project }: { project: Project }) {
  const key = `pb-getting-started-${project.id}`;
  const [dismissed, setDismissed] = useState(() => readPref(key) === "1");
  const tasks = useTasks(project.id);
  const counts = useMemoryCounts(project.id);
  const agent = useQuery({ queryKey: ["agent-activity", project.id], queryFn: ({ signal }) => activityApi.project(project.id, { actorTypes: ["claude", "codex"], limit: 1 }, signal), retry: false });
  if (dismissed || project.status === "archived") return null;

  const items = [
    { label: t("Create project"), done: true, to: null },
    { label: t("Connect repository"), done: Boolean(project.root_path), to: projectPath(project.id, "files") },
    { label: t("Create first task"), done: (tasks.data?.length ?? 0) > 0, to: projectPath(project.id, "tasks") },
    { label: t("Add first decision"), done: (counts.data?.by_type?.decision ?? 0) > 0, to: projectPath(project.id, "memory", { new: "1" }) },
    { label: t("Connect Claude or Codex"), done: (agent.data?.length ?? 0) > 0, to: "/help/claude" },
    { label: t("Preview your first Context Pack"), done: readPref(contextSeenKey(project.id)) === "1", to: projectPath(project.id, "context") },
  ];
  const finished = items.filter((i) => i.done).length;
  if (finished === items.length) return null;

  const remaining = items.filter((i) => !i.done);
  return (
    <section aria-labelledby="getting-started-title" className="rounded-xl border border-line bg-surface px-5 py-4 shadow-card">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <h2 id="getting-started-title" className="text-sm font-semibold tracking-tight">{t("Getting started")}</h2>
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-line" role="progressbar" aria-label={t("Getting started progress")} aria-valuenow={finished} aria-valuemin={0} aria-valuemax={items.length}><div className="h-full rounded-full bg-primary" style={{ width: `${(finished / items.length) * 100}%` }} /></div>
          <p className="text-xs text-ink-muted">{t("{done} of {count} done", { done: finished, count: items.length })}</p>
        </div>
        <Button variant="quiet" size="sm" onClick={() => { writePref(key, "1"); setDismissed(true); }}>{t("Dismiss")}</Button>
      </div>
      {/* Finished steps drop out of the way; only what is left stays on screen. */}
      <ul className="mt-2.5 flex flex-wrap gap-2" aria-label={t("Steps left")}>
        {remaining.map((item) => (
          <li key={item.label}>
            {item.to
              ? <Link to={item.to} className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-sm text-ink hover:border-forest hover:text-forest focus-visible:outline-2 focus-visible:outline-forest"><Circle size={13} className="text-ink-subtle" aria-hidden="true" />{item.label}</Link>
              : <span className="inline-flex items-center gap-1.5 px-3 py-1 text-sm text-ink"><Circle size={13} aria-hidden="true" />{item.label}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
