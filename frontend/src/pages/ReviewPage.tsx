import { ClipboardCheck } from "lucide-react";
import { useState } from "react";
import { ProposalCard } from "../components/proposals/ProposalCard";
import { AcceptAllButton } from "../components/proposals/AcceptAllButton";
import { EmptyState, ErrorState, HelpTip } from "../components/ui";
import { useProposals } from "../hooks/useProposals";
import { t } from "../lib/i18n";

export function ReviewPage({ projectId, archived }: { projectId: string; archived: boolean }) {
  const [history, setHistory] = useState(false);
  const query = useProposals(projectId, history ? ["accepted", "rejected"] : ["pending"]);
  const items = query.data ?? [];

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight">{t("Inbox")} <HelpTip label={t("About the Inbox")}>{t("Claude Code and Codex can suggest changes, such as editing a locked decision or completing a task. Nothing changes until you accept it. You can edit a suggestion first.")}</HelpTip></h2>
          <p className="mt-1 text-sm text-ink-muted">{t("Changes your agents suggested for this project. You can edit one before accepting it.")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label={t("Suggestion list")} className="segmented">
            <button type="button" aria-pressed={!history} onClick={() => setHistory(false)} className={`filter-tab ${!history ? "filter-tab-active" : ""}`}>{t("Waiting")}</button>
            <button type="button" aria-pressed={history} onClick={() => setHistory(true)} className={`filter-tab ${history ? "filter-tab-active" : ""}`}>{t("Decided")}</button>
          </div>
          {!history && !archived && items.length > 1 && <AcceptAllButton projectId={projectId} count={items.length} />}
        </div>
      </div>
      {query.isPending ? <div role="status" aria-label={t("Loading suggestions")} className="h-40 animate-pulse rounded-xl bg-surface" />
        : query.isError ? <ErrorState title={t("Suggestions could not be loaded")} message={query.error.message} onRetry={() => void query.refetch()} />
        : items.length === 0 ? <EmptyState icon={<ClipboardCheck size={26} />} title={history ? t("Nothing reviewed yet") : t("Nothing waiting for review")}>{history ? t("Suggestions you accept or reject will be listed here.") : t("When Claude Code or Codex suggests a change, it appears here and nothing changes until you accept it.")}</EmptyState>
        : <ul className="space-y-4" aria-label={history ? t("Reviewed suggestions") : t("Suggestions waiting for review")}>{items.map((p) => <ProposalCard key={p.id} proposal={p} readonly={archived} />)}</ul>}
    </div>
  );
}
