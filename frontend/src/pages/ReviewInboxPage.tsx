import { ArrowRight, ClipboardCheck, Globe2 } from "lucide-react";
import { Link } from "react-router-dom";
import { AcceptAllButton } from "../components/proposals/AcceptAllButton";
import { ProposalCard } from "../components/proposals/ProposalCard";
import { EmptyState, ErrorState, PageHeading, ProjectAvatar } from "../components/ui";
import { useProjects } from "../hooks/useProjects";
import { usePendingProposals, useProposals } from "../hooks/useProposals";
import { GLOBAL_ID, projectPath } from "../lib/routes";
import type { Project } from "../types/project";

type Scope = Pick<Project, "id" | "name" | "icon" | "accent"> & { archived: boolean };

function ProjectGroup({ scope, count }: { scope: Scope; count: number }) {
  const query = useProposals(scope.id, ["pending"]);
  const items = query.data ?? [];
  const titleId = `review-${scope.id}`;
  return (
    <section aria-labelledby={titleId}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id={titleId} className="flex min-w-0 items-center gap-2.5 text-base font-semibold tracking-tight text-ink">
          {scope.id === GLOBAL_ID ? <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-sage-pale text-forest" aria-hidden="true"><Globe2 size={14} /></span> : <ProjectAvatar project={scope} size="small" />}
          <span className="truncate">{scope.name}</span>
          <span className="rounded-full bg-primary px-2 py-0.5 text-xs font-bold text-white" aria-label={`${count} waiting`}>{count}</span>
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          {!scope.archived && items.length > 1 && <AcceptAllButton projectId={scope.id} count={items.length} label={`Accept all ${items.length}`} />}
          <Link to={projectPath(scope.id, "review")} className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm font-semibold text-forest hover:bg-sage-pale focus-visible:outline-2 focus-visible:outline-forest">History<span className="sr-only"> for {scope.name}</span><ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </div>
      {query.isPending ? <div role="status" aria-label={`Loading suggestions for ${scope.name}`} className="h-32 animate-pulse rounded-xl bg-surface" />
        : query.isError ? <ErrorState title={`Suggestions for ${scope.name} could not be loaded`} message={query.error.message} onRetry={() => void query.refetch()} />
        : <ul className="space-y-4" aria-label={`Suggestions for ${scope.name}`}>{items.map((p) => <ProposalCard key={p.id} proposal={p} readonly={scope.archived} />)}</ul>}
    </section>
  );
}

/** Every suggestion waiting for review, across all projects and the Global rules, grouped by project. */
export function ReviewInboxPage() {
  const pending = usePendingProposals();
  const projects = useProjects();
  const byProject = pending.data?.by_project ?? {};
  const known = new Map<string, Scope>((projects.data ?? []).map((p) => [p.id, { ...p, archived: p.status === "archived" }]));
  known.set(GLOBAL_ID, { id: GLOBAL_ID, name: "Global rules", icon: null, accent: null, archived: false });
  const groups = Object.entries(byProject)
    .filter(([id, count]) => count > 0 && known.has(id))
    .map(([id, count]) => ({ scope: known.get(id)!, count }))
    .sort((a, b) => b.count - a.count || a.scope.name.localeCompare(b.scope.name));

  return (
    <div className="max-w-4xl">
      <PageHeading title="Inbox" description="Suggestions from your agents, from every project. Nothing changes until you accept one." />
      <div className="mt-8 space-y-10">
        {pending.isPending || projects.isPending ? <div role="status" aria-label="Loading suggestions" className="h-40 animate-pulse rounded-xl bg-surface" />
          : pending.isError ? <ErrorState title="Suggestions could not be loaded" message={pending.error.message} onRetry={() => void pending.refetch()} />
          : groups.length === 0 ? (
            <EmptyState icon={<ClipboardCheck size={26} />} title="You're all caught up">
              When Claude Code or Codex wants to change something you control, such as a locked decision or a task's status, the suggestion waits here for you.
            </EmptyState>
          ) : groups.map(({ scope, count }) => <ProjectGroup key={scope.id} scope={scope} count={count} />)}
      </div>
    </div>
  );
}
