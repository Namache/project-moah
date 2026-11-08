import { useCallback, useEffect, useRef, useState } from "react";
import { readPref, writePref } from "../lib/prefs";
import { t } from "../lib/i18n";

/** A pane's width in pixels, remembered per person, kept between min and max. */
export function usePaneWidth(key: string, fallback: number, min: number, max: number): [number, (w: number) => void] {
  const clamp = useCallback((w: number) => Math.round(Math.min(Math.max(min, max), Math.max(min, w))), [min, max]);
  const [width, setWidth] = useState(() => { const saved = Number(readPref(key)); return clamp(saved > 0 ? saved : fallback); });
  // A smaller window lowers the limit: keep the pane inside it.
  useEffect(() => { setWidth((w) => clamp(w)); }, [clamp]);
  const set = useCallback((w: number) => { const next = clamp(w); setWidth(next); writePref(key, String(next)); }, [clamp, key]);
  return [width, set];
}

/**
 * The line between two side-by-side panes. Drag it to resize the pane on its left; the arrow keys
 * move it too, Home and End jump to the limits, and a double-click puts it back.
 */
export function PaneResizer({ width, min, max, fallback, onResize, label }: { width: number; min: number; max: number; fallback: number; onResize: (w: number) => void; label: string }) {
  const [dragging, setDragging] = useState(false);
  const start = useRef({ x: 0, width });
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => onResize(start.current.width + e.clientX - start.current.x);
    const stop = () => setDragging(false);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [dragging, onResize]);
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width}
      tabIndex={0}
      title={t("Drag to resize. Double-click to reset.")}
      onPointerDown={(e) => { e.preventDefault(); start.current = { x: e.clientX, width }; setDragging(true); }}
      onDoubleClick={() => onResize(fallback)}
      onKeyDown={(e) => {
        const keys: Record<string, number> = { ArrowLeft: width - 24, ArrowRight: width + 24, Home: min, End: max };
        const next = keys[e.key];
        if (next === undefined) return;
        e.preventDefault();
        onResize(next);
      }}
      className="group relative z-10 hidden w-0 shrink-0 cursor-col-resize lg:block focus-visible:outline-none"
    >
      {/* A wide, invisible grip around a thin line, so the line is easy to catch. */}
      <span className="absolute inset-y-0 -left-2 -right-2" aria-hidden="true" />
      <span className={`pointer-events-none absolute inset-y-0 -left-px w-[3px] transition-colors ${dragging ? "bg-primary/60" : "bg-line group-hover:bg-primary/40 group-focus-visible:bg-primary/60"}`} aria-hidden="true" />
      <span className={`pointer-events-none absolute left-1/2 top-1/2 flex h-10 w-2.5 -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center gap-1 rounded-full border bg-surface shadow-card transition-colors ${dragging ? "border-primary" : "border-line-strong group-hover:border-primary/60"}`} aria-hidden="true">
        <span className="h-0.5 w-0.5 rounded-full bg-ink-subtle" />
        <span className="h-0.5 w-0.5 rounded-full bg-ink-subtle" />
        <span className="h-0.5 w-0.5 rounded-full bg-ink-subtle" />
      </span>
    </div>
  );
}
