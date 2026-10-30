import { Link, useParams } from "react-router-dom";
import { usePendingProposals } from "../hooks/useProposals";
import { PageHeading } from "../components/ui";
import { MemoryPage } from "./MemoryPage";
import { ReviewPage } from "./ReviewPage";
import { GLOBAL_ID } from "../lib/routes";
import { t } from "../lib/i18n";

/** Rules and memory that Claude Code and Codex follow in every project, from the reserved Global scope. */
export function GlobalPage() {
  const { section } = useParams();
  const pending = usePendingProposals().data?.by_project?.[GLOBAL_ID] ?? 0;
  const review = section === "review";
  const tab = (active: boolean) => `section-tab ${active ? "section-tab-active" : ""}`;
  return (
    <div className="space-y-5">
      <PageHeading title={t("Global rules")} description={t("Claude Code and Codex read these at the start of every session, in every project, before the project's own rules. Rules are always included; other global memory, such as your preferences, is included when its AI visibility is Always.")} />
      <nav aria-label={t("Global sections")} className="flex gap-1 border-b border-line">
        <Link to="/global" className={tab(!review)} aria-current={!review ? "page" : undefined}>{t("Rules and memory")}</Link>
        <Link to="/global/review" className={tab(review)} aria-current={review ? "page" : undefined}>{t("Inbox")}{pending ? <span className="ml-2 rounded-full bg-primary px-1.5 text-xs font-semibold leading-5 text-white">{pending}</span> : null}</Link>
      </nav>
      {review ? <ReviewPage projectId={GLOBAL_ID} archived={false} /> : <MemoryPage projectId={GLOBAL_ID} archived={false} />}
    </div>
  );
}
