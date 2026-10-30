import { useState } from "react";
import { useProjectActivity } from "../../hooks/useActivity";
import type { ActivityFilter } from "../../types/activity";
import { ActivityFilterBar, ActivityResults, filtersForActivity } from "./ActivityFeed";
import { t } from "../../lib/i18n";

export function ProjectActivity({ projectId }: { projectId: string }) {
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const query = useProjectActivity(projectId, filtersForActivity(filter));
  return <section aria-label={t("Project activity")}>
    <div className="mb-5"><h2 className="text-xl font-semibold tracking-tight text-ink">{t("Project activity")}</h2><p className="mt-1 text-sm text-ink-muted">{t("A timeline of recorded work and decisions in this project.")}</p></div>
    <ActivityFilterBar value={filter} onChange={setFilter} />
    <ActivityResults events={query.data?.pages.flat() ?? []} filter={filter} workspace={false} isPending={query.isPending} error={query.isError ? query.error.message : null} hasNextPage={Boolean(query.hasNextPage)} isFetchingNextPage={query.isFetchingNextPage} onRetry={() => void query.refetch()} onLoadMore={() => void query.fetchNextPage()} />
  </section>;
}
