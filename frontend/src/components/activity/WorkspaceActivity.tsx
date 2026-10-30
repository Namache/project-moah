import { useState } from "react";
import { useWorkspaceActivity } from "../../hooks/useActivity";
import type { ActivityFilter } from "../../types/activity";
import { ActivityFilterBar, ActivityResults, filtersForActivity } from "./ActivityFeed";

export function WorkspaceActivity() {
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const query = useWorkspaceActivity(filtersForActivity(filter));
  return <section aria-label="Workspace activity feed">
    <ActivityFilterBar value={filter} onChange={setFilter} />
    <ActivityResults events={query.data?.pages.flat() ?? []} filter={filter} workspace isPending={query.isPending} error={query.isError ? query.error.message : null} hasNextPage={Boolean(query.hasNextPage)} isFetchingNextPage={query.isFetchingNextPage} onRetry={() => void query.refetch()} onLoadMore={() => void query.fetchNextPage()} />
  </section>;
}
