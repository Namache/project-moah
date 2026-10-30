import { WorkspaceActivity } from "../components/activity/WorkspaceActivity";
import { PageHeading } from "../components/ui";

export function ActivityPage() {
  return <div><PageHeading title="Activity" description="A timeline of recorded work across your projects." className="mb-8" /><WorkspaceActivity /></div>;
}
