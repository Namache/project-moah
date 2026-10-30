import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { AlertCircle, ArrowRight, FolderKanban, MoreHorizontal, RefreshCw, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import type { Project, ProjectStatus } from "../types/project";
import { labels, locale, msg, t } from "../lib/i18n";

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

export const buttonClasses: Record<ButtonVariant, string> = {
  primary: "bg-primary text-white hover:bg-primary-hover shadow-card",
  secondary: "border border-line-strong bg-surface text-ink hover:bg-canvas shadow-card",
  quiet: "text-ink-muted hover:bg-hover hover:text-ink",
  danger: "bg-danger-solid text-white hover:bg-danger-solid-hover",
};

type ButtonSize = "md" | "sm" | "icon";

/** Every button and button-styled link shares one text size (text-sm); sizes only change the box. */
const buttonCore =
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-forest disabled:cursor-not-allowed disabled:opacity-60";

const buttonSizes: Record<ButtonSize, string> = {
  md: "min-h-9 px-3.5 py-1.5",
  sm: "min-h-8 px-2.5 py-1",
  icon: "h-8 w-8 shrink-0",
};

/** A panel that sits in a toolbar as a small pill while closed and opens into a full-width card below it. */
export const collapsiblePill = "inline-flex h-9 items-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-sm font-medium text-ink shadow-card hover:bg-canvas focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-forest";
export const collapsibleOpen = "order-last basis-full rounded-xl border border-line bg-surface p-4 shadow-card";
export const collapsibleHeader = "flex w-full items-center gap-2 text-left text-sm font-semibold text-ink focus-visible:outline-2 focus-visible:outline-forest";

/** The medium button look, for links styled as buttons. */
export const buttonBase = `${buttonCore} ${buttonSizes.md}`;

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({ variant = "secondary", size = "md", className = "", type = "button", ...props }: ButtonProps) {
  return <button type={type} className={`${buttonCore} ${buttonSizes[size]} ${buttonClasses[variant]} ${className}`} {...props} />;
}

const statusLabels: Record<ProjectStatus, string> = labels({
  active: msg("Active"),
  paused: msg("Paused"),
  completed: msg("Completed"),
  archived: msg("Archived"),
});

/** The status colours of docs/DESIGN.md. Colour is never the only signal: pair a tone with a word or an icon. */
export type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "special";

export const toneClasses: Record<Tone, { soft: string; dot: string; text: string }> = {
  neutral: { soft: "bg-neutral-soft text-neutral-ink", dot: "bg-neutral", text: "text-neutral-ink" },
  info: { soft: "bg-info-soft text-info-ink", dot: "bg-info", text: "text-info-ink" },
  success: { soft: "bg-success-soft text-success-ink", dot: "bg-success", text: "text-success-ink" },
  warning: { soft: "bg-warning-soft text-warning-ink", dot: "bg-warning", text: "text-warning-ink" },
  danger: { soft: "bg-danger-soft text-danger-ink", dot: "bg-danger", text: "text-danger-ink" },
  special: { soft: "bg-special-soft text-special-ink", dot: "bg-special", text: "text-special-ink" },
};

/** A small tinted label for a status or a type. */
export function Badge({ tone = "neutral", icon: Icon, children, className = "" }: { tone?: Tone; icon?: LucideIcon; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium ${toneClasses[tone].soft} ${className}`}>
      {Icon && <Icon size={12} strokeWidth={2.2} aria-hidden="true" />}{children}
    </span>
  );
}

const projectStatusTone: Record<ProjectStatus, Tone> = { active: "success", paused: "warning", completed: "info", archived: "neutral" };

export function StatusBadge({ status }: { status: ProjectStatus }) {
  return <Badge tone={projectStatusTone[status]}>{statusLabels[status]}</Badge>;
}

/** A square button that shows only an icon. The label is required: it names the button and becomes its tooltip. */
export function IconButton({ label, icon: Icon, size = 16, className = "", ...props }: Omit<ButtonProps, "children" | "size"> & { label: string; icon: LucideIcon; size?: number }) {
  return <Button variant="quiet" size="icon" aria-label={label} title={label} className={className} {...props}><Icon size={size} aria-hidden="true" /></Button>;
}

export interface SegmentOption<T extends string> { value: T; label: string; icon?: LucideIcon; count?: number }

/** One choice out of a few: views (Board / List) or filters (All / Decisions / Rules...). */
export function SegmentedControl<T extends string>({ label, options, value, onChange, className = "" }: { label: string; options: SegmentOption<T>[]; value: T; onChange: (value: T) => void; className?: string }) {
  return (
    <div role="group" aria-label={label} className={`segmented ${className}`}>
      {options.map(({ value: v, label: text, icon: Icon, count }) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)} className={`filter-tab inline-flex flex-none items-center gap-1.5 ${value === v ? "filter-tab-active" : ""}`}>
          {Icon && <Icon size={15} aria-hidden="true" />}{text}{count !== undefined && " "}
          {count !== undefined && <span className={`text-xs tabular-nums ${value === v ? "text-ink-muted" : "text-ink-subtle"}`}>{count}</span>}
        </button>
      ))}
    </div>
  );
}

export interface MenuItem { label: string; icon?: LucideIcon; onSelect: () => void; danger?: boolean; disabled?: boolean }

/** Rare actions on one item, behind a "⋯" button. Escape or a click outside closes it. */
export function Menu({ label, items, icon = MoreHorizontal, align = "right", trigger, triggerClassName = "", wide = false }: { label: string; items: MenuItem[]; icon?: LucideIcon; align?: "left" | "right"; trigger?: ReactNode; triggerClassName?: string; wide?: boolean }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    box.current?.querySelector<HTMLElement>("[role=menuitem]:not([disabled])")?.focus();
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key !== "Escape") return;
        box.current?.querySelector<HTMLElement>("button")?.focus();
      } else if (box.current?.contains(event.target as Node)) return;
      setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", close); };
  }, [open]);
  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const entries = [...(box.current?.querySelectorAll<HTMLElement>("[role=menuitem]:not([disabled])") ?? [])];
    const at = entries.indexOf(document.activeElement as HTMLElement);
    entries[(at + (event.key === "ArrowDown" ? 1 : entries.length - 1)) % entries.length]?.focus();
  }
  return (
    <div ref={box} className={`relative ${wide ? "flex" : "inline-flex"}`}>
      {trigger
        ? <button type="button" aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen((v) => !v)} className={triggerClassName}>{trigger}</button>
        : <IconButton label={label} icon={icon} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen((v) => !v)} />}
      {open && (
        <div id={id} role="menu" aria-label={label} onKeyDown={onKeyDown} className={`absolute top-full z-40 mt-1 min-w-48 rounded-xl border border-line bg-surface p-1 shadow-card-hover ${align === "right" ? "right-0" : "left-0"}`}>
          {items.map(({ label: text, icon: Icon, onSelect, danger, disabled }) => (
            <button key={text} type="button" role="menuitem" disabled={disabled} onClick={() => { setOpen(false); onSelect(); }}
              className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-hover focus-visible:bg-hover focus-visible:outline-none disabled:opacity-50 ${danger ? "text-danger-ink" : "text-ink"}`}>
              {Icon && <Icon size={15} aria-hidden="true" className={danger ? "" : "text-ink-subtle"} />}{text}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** "Are you sure?" for actions that can't be undone, in place of window.confirm. */
export function ConfirmDialog({ title, children, confirmLabel, onConfirm, onClose, busy = false, error, danger = true }: { title: string; children?: ReactNode; confirmLabel: string; onConfirm: () => void; onClose: () => void; busy?: boolean; error?: string | null; danger?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal?.();
    return () => { if (dialog?.open) dialog.close(); };
  }, []);
  return (
    <dialog ref={ref} onCancel={(event) => { event.preventDefault(); onClose(); }} aria-labelledby={titleId} className="dialog-panel m-auto w-[calc(100%-2rem)] max-w-sm rounded-xl border border-line bg-surface p-5 text-ink shadow-dialog backdrop:bg-black/40">
      <h2 id={titleId} className="text-base font-semibold tracking-tight">{title}</h2>
      {children && <div className="mt-2 text-sm leading-6 text-ink-muted">{children}</div>}
      {error && <p role="alert" className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger-ink">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose}>{t("Cancel")}</Button>
        <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy}>{confirmLabel}</Button>
      </div>
    </dialog>
  );
}

/** A section of a dashboard: small uppercase header with an icon, an optional link to the full page, then the content. */
export function Widget({ title, icon: Icon, to, linkLabel, action, children, className = "", bodyClassName = "" }: { title: string; icon?: LucideIcon; to?: string; linkLabel?: string; action?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={`flex min-w-0 flex-col rounded-xl border border-line bg-surface shadow-card ${className}`}>
      <header className="flex min-h-12 items-center gap-2 px-4 pt-3">
        <h2 id={headingId} className="flex min-w-0 items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
          {Icon && <Icon size={14} className="text-forest" aria-hidden="true" />}{title}
        </h2>
        {to && <Link to={to} aria-label={linkLabel ?? title} title={linkLabel ?? title} className="-ml-1 inline-flex h-6 w-6 items-center justify-center rounded text-ink-subtle hover:bg-hover hover:text-forest focus-visible:outline-2 focus-visible:outline-forest"><ArrowRight size={14} aria-hidden="true" /></Link>}
        {action && <div className="ml-auto flex items-center gap-1">{action}</div>}
      </header>
      <div className={`min-w-0 flex-1 px-4 pb-4 pt-2 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

/** A thin progress bar. Pair it with the number it shows. */
export function ProgressBar({ value, tone = "success", label }: { value: number; tone?: Tone; label: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <span role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(clamped)} className="block h-1.5 w-full overflow-hidden rounded-full bg-neutral-soft">
      <span className={`block h-full rounded-full ${toneClasses[tone].dot}`} style={{ width: `${clamped}%` }} />
    </span>
  );
}

/** A project's own colour; projects without a valid one use the app accent. */
export function projectAccent(project: Pick<Project, "accent">): string {
  return /^#[0-9a-fA-F]{6}$/.test(project.accent ?? "") ? project.accent! : "#35766d";
}

/** A big coloured square for a project: its colour as the fill and its icon in the middle. */
export function ProjectTile({ project, className = "" }: { project: Pick<Project, "name" | "icon" | "accent">; className?: string }) {
  const accent = projectAccent(project);
  return (
    <span className={`relative flex aspect-square items-center justify-center overflow-hidden rounded-xl text-4xl shadow-card ${className}`}
      style={{ background: `linear-gradient(145deg, ${accent} 0%, color-mix(in oklab, ${accent} 70%, black) 100%)` }} aria-hidden="true">
      <span className="relative drop-shadow-sm">{project.icon ? project.icon : <FolderKanban size={36} strokeWidth={1.7} className="text-white" />}</span>
    </span>
  );
}

export function ProjectAvatar({ project, size = "normal" }: { project: Pick<Project, "name" | "icon" | "accent">; size?: "small" | "normal" | "large" }) {
  const accent = projectAccent(project);
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-xl font-semibold ${size === "large" ? "h-16 w-16 text-3xl" : size === "small" ? "h-6 w-6 rounded-lg text-sm" : "h-12 w-12 text-2xl"}`}
      style={{ color: accent, backgroundColor: `${accent}1a` }}
      aria-hidden="true"
    >
      {project.icon ? project.icon : <FolderKanban size={size === "large" ? 28 : size === "small" ? 13 : 23} strokeWidth={1.8} />}
    </span>
  );
}

/** A page's title block: the heading and an optional one-line description. */
export function PageHeading({ title, description, className = "" }: { title: string; description?: string; className?: string }) {
  return (
    <div className={className}>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      {description && <p className="mt-1.5 max-w-2xl text-sm leading-6 text-ink-muted">{description}</p>}
    </div>
  );
}

export function ErrorState({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-xl bg-danger-soft p-5 text-danger-ink">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 shrink-0" size={21} aria-hidden="true" />
        <div>
          <h2 className="font-semibold">{title}</h2>
          <p className="mt-1 text-sm leading-6">{message}</p>
          {onRetry && <Button onClick={onRetry} className="mt-4"><RefreshCw size={16} />{t("Try again")}</Button>}
        </div>
      </div>
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon: ReactNode; title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong px-6 py-12 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-sage-pale text-forest">{icon}</div>
      <h2 className="mt-4 text-base font-semibold tracking-tight text-ink">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-ink-muted">{children}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function LoadingState({ label = t("Loading projects") }: { label?: string }) {
  return (
    <div role="status" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label={label}>
      {[0, 1, 2].map((item) => <div key={item} className="h-56 animate-pulse rounded-xl border border-line bg-surface p-6"><div className="h-12 w-12 rounded-xl bg-neutral-soft" /><div className="mt-5 h-5 w-1/2 rounded bg-neutral-soft" /><div className="mt-3 h-4 w-3/4 rounded bg-neutral-soft" /></div>)}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(locale(), { month: "short", day: "numeric", year: "numeric" }).format(date);
}

/** A small "?" that opens a short explanation. Keyboard and screen-reader friendly. */
export function HelpTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative inline-flex align-middle">
      <button type="button" aria-label={t("Help: {topic}", { topic: label })} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)} onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-line text-xs font-bold text-ink-muted hover:bg-sage-pale focus-visible:outline-2 focus-visible:outline-forest">?</button>
      {open && <span id={id} role="note" className="absolute left-0 top-7 z-20 w-72 rounded-xl border border-line bg-surface p-3 text-xs font-normal leading-5 text-ink shadow-dialog">{children}</span>}
    </span>
  );
}
