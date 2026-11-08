import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { dismissNotice, useNotices } from "../lib/notify";
import { t } from "../lib/i18n";

const icons = { success: CheckCircle2, danger: CircleAlert, neutral: Info };
const iconTone = { success: "text-success", danger: "text-danger", neutral: "text-ink-subtle" };

/** Parts of a screen a notice must never cover, such as a bar of action buttons: mark them with data-keep-clear. */
export const KEEP_CLEAR = "[data-keep-clear]";
const EDGE = 16; // px from the window's edge, as bottom-4 right-4
const GAP = 12; // px between a notice and what it keeps clear of
const WIDTH = 320; // w-80
/** Above this much room taken from the bottom, the notices go to the top corner instead. */
const MAX_LIFT = 0.6;

/** Where the notices sit: bottom right, lifted above anything marked data-keep-clear in that corner. */
export function noticePlace(view: { width: number; height: number }, keepClear: Pick<DOMRect, "top" | "bottom" | "left" | "right">[]): { bottom: number } | { top: number } {
  const column = view.width - EDGE - Math.min(WIDTH, view.width - 2 * EDGE);
  let bottom = EDGE;
  for (const box of keepClear) {
    const shown = box.bottom > box.top && box.right > box.left && box.top < view.height && box.bottom > 0;
    if (shown && box.right > column && box.left < view.width - EDGE) bottom = Math.max(bottom, view.height - box.top + GAP);
  }
  return bottom > view.height * MAX_LIFT ? { top: EDGE } : { bottom };
}

function measure() {
  const boxes = [...document.querySelectorAll<HTMLElement>(KEEP_CLEAR)].map((element) => element.getBoundingClientRect());
  return noticePlace({ width: window.innerWidth, height: window.innerHeight }, boxes);
}

/** Follows the marked parts while notices show: they change size (a comment box grows) or appear (the next review opens). */
function usePlace(active: boolean) {
  const [place, setPlace] = useState<{ bottom: number } | { top: number }>({ bottom: EDGE });
  useEffect(() => {
    if (!active) return;
    const update = () => setPlace((current) => {
      const next = measure();
      return JSON.stringify(next) === JSON.stringify(current) ? current : next;
    });
    update();
    const timer = window.setInterval(update, 250);
    window.addEventListener("resize", update);
    return () => { window.clearInterval(timer); window.removeEventListener("resize", update); };
  }, [active]);
  return place;
}

/** Where notify() messages appear: bottom right, clear of action buttons, announced to screen readers. */
export function Notices() {
  const notices = useNotices();
  const place = usePlace(notices.length > 0);
  return (
    <div aria-live="polite" style={place} className="pointer-events-none fixed right-4 z-50 flex w-80 max-w-[calc(100%-2rem)] flex-col gap-2 transition-[bottom] duration-150">
      {notices.map(({ id, message, tone, action }) => {
        const Icon = icons[tone];
        return (
          <div key={id} role={tone === "danger" ? "alert" : "status"} className="pointer-events-auto flex items-start gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-3 text-sm text-ink shadow-card-hover">
            <Icon size={17} className={`mt-px flex-none ${iconTone[tone]}`} aria-hidden="true" />
            <p className="min-w-0 flex-1">{message}</p>
            {action && <button type="button" onClick={() => { dismissNotice(id); void action.run(); }} className="-my-0.5 rounded-md px-1.5 py-0.5 text-sm font-semibold text-forest hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">{action.label}</button>}
            <button type="button" onClick={() => dismissNotice(id)} aria-label={t("Close notice")} className="-m-1 rounded p-1 text-ink-subtle hover:text-ink focus-visible:outline-2 focus-visible:outline-forest"><X size={14} aria-hidden="true" /></button>
          </div>
        );
      })}
    </div>
  );
}
