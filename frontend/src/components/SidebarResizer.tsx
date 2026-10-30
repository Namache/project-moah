import { useCallback, useEffect, useState } from "react";
import { readPref, writePref } from "../lib/prefs";
import { t } from "../lib/i18n";

const KEY = "pb-sidebar-width";
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 440;
const DEFAULT = 256;

const clamp = (w: number) => Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(w)));

/** The wide sidebar's width, remembered per person. */
export function useSidebarWidth(): [number, (w: number) => void] {
  const [width, setWidth] = useState(() => { const saved = Number(readPref(KEY)); return saved ? clamp(saved) : DEFAULT; });
  const set = useCallback((w: number) => { const next = clamp(w); setWidth(next); writePref(KEY, String(next)); }, []);
  return [width, set];
}

/** A drag handle on the sidebar's edge. Arrow keys resize it too, Home and End jump to the limits, and double-click resets it. */
export function SidebarResizer({ width, onResize }: { width: number; onResize: (w: number) => void }) {
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => onResize(e.clientX);
    const stop = () => setDragging(false);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", stop); window.removeEventListener("pointercancel", stop); document.body.style.cursor = ""; document.body.style.userSelect = ""; };
  }, [dragging, onResize]);
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t("Resize sidebar")}
      aria-valuemin={SIDEBAR_MIN}
      aria-valuemax={SIDEBAR_MAX}
      aria-valuenow={width}
      tabIndex={0}
      title={t("Drag to resize. Double-click to reset.")}
      onPointerDown={(e) => { e.preventDefault(); setDragging(true); }}
      onDoubleClick={() => onResize(DEFAULT)}
      onKeyDown={(e) => {
        const keys: Record<string, number> = { ArrowLeft: width - 16, ArrowRight: width + 16, Home: SIDEBAR_MIN, End: SIDEBAR_MAX };
        const next = keys[e.key];
        if (next === undefined) return;
        e.preventDefault();
        onResize(next);
      }}
      className={`fixed inset-y-0 z-20 w-1.5 -translate-x-1/2 cursor-col-resize transition-colors hover:bg-primary/30 focus-visible:bg-primary/40 focus-visible:outline-none ${dragging ? "bg-primary/40" : ""}`}
      style={{ left: width }}
    />
  );
}
