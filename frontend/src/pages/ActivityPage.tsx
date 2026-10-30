import { WorkspaceActivity } from "../components/activity/WorkspaceActivity";
import { PageHeading } from "../components/ui";
import { t } from "../lib/i18n";

export function ActivityPage() {
  return <div><PageHeading title={t("Activity")} description={t("A timeline of recorded work across your projects.")} className="mb-8" /><WorkspaceActivity /></div>;
}
