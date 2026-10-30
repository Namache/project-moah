import { Activity } from "lucide-react";
import { useRecentActivity } from "../../hooks/useActivity";
import { CompactActivityItem } from "./ActivityFeed";
import { projectPath } from "../../lib/routes";
import { Widget } from "../ui";
import { t } from "../../lib/i18n";

export function RecentActivity({ projectId }: { projectId: string }) {
  const query = useRecentActivity(projectId);
  return <Widget title={t("Recent activity")} icon={Activity} to={projectPath(projectId, "activity")} linkLabel={t("All activity")}>
    {query.isPending && <p role="status" className="text-sm text-ink-muted">{t("Loading recent activity…")}</p>}
    {query.isError && <p role="alert" className="text-sm text-danger-ink">{t("Recent activity could not be loaded.")} <button type="button" className="font-semibold underline" onClick={() => void query.refetch()}>{t("Try again")}</button></p>}
    {query.isSuccess && (query.data.length > 0 ? <ol className="-mt-2">{query.data.map((event) => <CompactActivityItem key={event.id} event={event} />)}</ol> : <p className="text-sm text-ink-subtle">{t("No recorded activity yet.")}</p>)}
  </Widget>;
}
