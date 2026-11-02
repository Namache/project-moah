import { Suspense, lazy } from "react";
import { BrainHealth } from "../components/brain/BrainHealth";
import { PageHeading } from "../components/ui";
import { t } from "../lib/i18n";

// Loaded when the Brain page opens: its graph layout library is a large part of the app's code
// and no other page needs it.
const BrainView = lazy(() => import("../components/brain/BrainView").then((m) => ({ default: m.BrainView })));

export function BrainPage() {
  return (
    <div>
      <PageHeading title={t("Brain")} description={t("Everything your agents know, across every project, drawn as one brain. Each topic is a region, global rules sit in the middle.")} />
      <div className="mt-7">
        <Suspense fallback={<p role="status" className="py-24 text-center text-sm text-slate-400">{t("Growing the brain…")}</p>}>
          <BrainView />
        </Suspense>
      </div>
      <BrainHealth />
    </div>
  );
}
