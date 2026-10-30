import { BrainHealth } from "../components/brain/BrainHealth";
import { BrainView } from "../components/brain/BrainView";
import { PageHeading } from "../components/ui";
import { t } from "../lib/i18n";

export function BrainPage() {
  return (
    <div>
      <PageHeading title={t("Brain")} description={t("Everything your agents know, across every project, drawn as one brain. Each project is a region, global rules sit in the middle.")} />
      <div className="mt-7"><BrainView /></div>
      <BrainHealth />
    </div>
  );
}
