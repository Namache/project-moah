import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, X } from "lucide-react";
import { systemApi } from "../api/system";
import { Button } from "./ui";
import { t } from "../lib/i18n";

const CHECK_MS = 60_000;

/** After Project Moah is updated while it is open: one calm line with a Restart button, instead of the old version carrying on unnoticed. */
export function UpdateBanner() {
  const update = useQuery({ queryKey: ["app-update"], queryFn: ({ signal }) => systemApi.update(signal), refetchInterval: CHECK_MS, retry: false });
  const [hidden, setHidden] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  const status = update.data;
  if (!status?.newer) return null;
  const key = status.installed ?? "newer";
  if (hidden === key) return null;
  const restart = window.projectBrainDesktop?.restartForUpdate;
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5 text-sm text-ink sm:px-8 lg:px-10">
      <RefreshCw size={16} className="flex-none text-forest" aria-hidden="true" />
      <p className="min-w-0 flex-1">{restart ? t("Project Moah was updated. Restart it to use the new version.") : t("Project Moah was updated. Close it and open it again to use the new version.")}</p>
      {restart && (
        <Button variant="primary" size="sm" disabled={restarting} onClick={() => { setRestarting(true); void restart().then((ok) => { if (!ok) setRestarting(false); }).catch(() => setRestarting(false)); }}>
          {restarting ? t("Restarting…") : t("Restart now")}
        </Button>
      )}
      <button type="button" onClick={() => setHidden(key)} aria-label={t("Later")} title={t("Later")} className="-m-1 rounded p-1 text-ink-subtle hover:text-ink focus-visible:outline-2 focus-visible:outline-forest"><X size={14} aria-hidden="true" /></button>
    </div>
  );
}
