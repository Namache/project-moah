import { Activity } from "lucide-react";
import { useRecentActivity } from "../../hooks/useActivity";
import { CompactActivityItem } from "./ActivityFeed";
import { projectPath } from "../../lib/routes";
import { Widget } from "../ui";

export function RecentActivity({ projectId }: { projectId: string }) {
  const query = useRecentActivity(projectId);
  return <Widget title="Recent activity" icon={Activity} to={projectPath(projectId, "activity")} linkLabel="All activity">
    {query.isPending && <p role="status" className="text-sm text-ink-muted">Loading recent activity…</p>}
    {query.isError && <p role="alert" className="text-sm text-danger-ink">Recent activity could not be loaded. <button type="button" className="font-semibold underline" onClick={() => void query.refetch()}>Try again</button></p>}
    {query.isSuccess && (query.data.length > 0 ? <ol className="-mt-2">{query.data.map((event) => <CompactActivityItem key={event.id} event={event} />)}</ol> : <p className="text-sm text-ink-subtle">No recorded activity yet.</p>)}
  </Widget>;
}
