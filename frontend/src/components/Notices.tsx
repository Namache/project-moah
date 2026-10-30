import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { dismissNotice, useNotices } from "../lib/notify";

const icons = { success: CheckCircle2, danger: CircleAlert, neutral: Info };
const iconTone = { success: "text-success", danger: "text-danger", neutral: "text-ink-subtle" };

/** Where notify() messages appear: bottom right, announced to screen readers. */
export function Notices() {
  const notices = useNotices();
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100%-2rem)] flex-col gap-2">
      {notices.map(({ id, message, tone }) => {
        const Icon = icons[tone];
        return (
          <div key={id} role={tone === "danger" ? "alert" : "status"} className="pointer-events-auto flex items-start gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-3 text-sm text-ink shadow-card-hover">
            <Icon size={17} className={`mt-px flex-none ${iconTone[tone]}`} aria-hidden="true" />
            <p className="min-w-0 flex-1">{message}</p>
            <button type="button" onClick={() => dismissNotice(id)} aria-label="Close notice" className="-m-1 rounded p-1 text-ink-subtle hover:text-ink focus-visible:outline-2 focus-visible:outline-forest"><X size={14} aria-hidden="true" /></button>
          </div>
        );
      })}
    </div>
  );
}
