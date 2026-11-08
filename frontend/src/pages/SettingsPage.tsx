import { AgentSettingsCard, Switch } from "../components/AgentSettingsCard";
import { agentsApi } from "../api/agents";
import { TaskSettingsCard } from "../components/TaskSettingsCard";
import { FocusTimerSettings, SoundSettings } from "../components/pomodoro/FocusTimerSettings";
import { DictationSettings } from "../components/dictation/DictationSettings";
import { serverText } from "../api/dictation";
import { Choice } from "../components/Choice";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSingleKeys } from "../lib/reviewKeys";
import { queryKeys } from "../lib/queries";
import { ArrowRight, Check, ChevronRight, Copy, Download, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, ConfirmDialog, ErrorState, HelpTip, PageHeading } from "../components/ui";
import { systemApi, type Diagnostics, type ErrorEntry, type ErrorLog, type ErrorSource } from "../api/system";
import { useTimeout } from "../hooks/useTimeout";
import { languageChoices, locale, t, tp, tx, useLanguageChoice } from "../lib/i18n";
import { themeChoices, useTheme } from "../lib/theme";
import { percent, setDisplay, textSteps, useDisplay, zoomSteps } from "../lib/display";

const megabytes = (bytes: number | null) => (bytes === null ? t("unknown") : `${new Intl.NumberFormat(locale(), { maximumFractionDigits: bytes < 10_485_760 ? 2 : 1 }).format(bytes / 1_048_576)} ${t("MB")}`);

/** The copied report stays in English with the raw names, so it reads the same in any bug report. */
export function diagnosticReport(d: Diagnostics): string {
  const size = d.database.size_bytes === null ? "unknown" : `${(d.database.size_bytes / 1_048_576).toFixed(d.database.size_bytes < 10_485_760 ? 2 : 1)} MB`;
  return [
    `Project Moah ${d.app_version}`, `Platform: ${d.platform}`, `Python ${d.python}, SQLite ${d.sqlite_version}`,
    `Database: ${d.database.path ?? "unknown"} (${size})`,
    `Migration: ${d.database.migration}`, `Integrity: ${d.database.integrity}, foreign key problems: ${d.database.foreign_key_problems}`,
    `Search index: ${d.database.search_index_ready ? "ready" : "unavailable"}`, `Git: ${d.git.available ? d.git.version ?? "available" : "not available"}`,
    `Records: ${Object.entries(d.counts).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(", ")}`,
    ...(d.builds ? [`Build: ${d.builds.installed}, packs from older builds in the last day: ${d.builds.old_build_last_day}`] : []),
    ...(d.errors ? [`Errors logged: ${d.errors.total}, in the last day: ${d.errors.last_day}${d.errors.last ? `, last at ${d.errors.last}` : ""}`] : []),
    ...(d.dictation ? [dictationLine(d.dictation)] : []),
  ].join("\n");
}

function dictationLine({ available, reason, engine }: NonNullable<Diagnostics["dictation"]>): string {
  if (!available) return `Dictation: off (${reason ?? "unknown reason"})`;
  if (!engine) return "Dictation: ready";
  const parts = [engine.loaded ? `engine loaded in ${engine.load_seconds ?? "?"} s` : "engine not loaded", `${engine.threads} threads`];
  if (engine.last_seconds !== null && engine.last_audio_seconds !== null) parts.push(`last text ${engine.last_seconds} s for ${engine.last_audio_seconds} s of audio at ${engine.last_finished ?? "?"}`);
  if (engine.busy_since) parts.push(`busy since ${engine.busy_since}`);
  if (engine.last_error) parts.push(`last error at ${engine.last_error_at ?? "?"}: ${engine.last_error}`);
  return `Dictation: ready, ${parts.join(", ")}`;
}

const SOURCE_NAMES: Record<ErrorSource, string> = { service: "local service", mcp: "MCP server", desktop: "desktop app", window: "app window" };

/** The copied log is in English too. Messages come from the code, and the home folder is already shortened to ~. */
export function errorLogText(log: ErrorLog, version?: string): string {
  const head = `Project Moah ${version ?? ""} error log: ${log.total} ${log.total === 1 ? "entry" : "entries"}, newest first${log.total > log.entries.length ? ` (showing ${log.entries.length})` : ""}`.replace("  ", " ");
  return [head, ...log.entries.map((e) => [`${e.time} [${SOURCE_NAMES[e.source]}] ${e.level}: ${e.message}`, ...(e.detail ? [e.detail.replace(/^/gm, "    ")] : [])].join("\n"))].join("\n\n");
}

/** On screen, counts use the app's own words. */
function countLabel(key: string, n: number): string {
  switch (key) {
    case "projects": return tp(n, "{count} project", "{count} projects");
    case "tasks": return tp(n, "{count} task", "{count} tasks");
    case "memories": return tp(n, "{count} memory", "{count} memories");
    case "checkpoints": return tp(n, "{count} checkpoint", "{count} checkpoints");
    case "files": return tp(n, "{count} file", "{count} files");
    case "pending_proposals": return tp(n, "{count} suggestion waiting", "{count} suggestions waiting");
    default: return `${key.replace(/_/g, " ")} ${n}`;
  }
}

function Card({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return <section aria-labelledby={id} className="rounded-xl border border-line bg-surface p-5 shadow-card sm:p-6"><h2 id={id} className="text-base font-semibold tracking-tight">{title}</h2><div className="mt-3">{children}</div></section>;
}

/** A card that opens on click, for what is needed now and then: data and diagnostics. */
function FoldingCard({ title, extra, badges, onOpen, children }: { title: string; extra?: ReactNode; badges?: ReactNode; onOpen?: () => void; children: ReactNode }) {
  return (
    <details className="group rounded-xl border border-line bg-surface shadow-card" onToggle={(e) => { if ((e.currentTarget as HTMLDetailsElement).open) onOpen?.(); }}>
      <summary className="flex cursor-pointer list-none items-center gap-3 rounded-xl p-5 focus-visible:outline-2 focus-visible:outline-forest sm:px-6">
        <ChevronRight size={16} className="text-ink-subtle transition-transform group-open:rotate-90" aria-hidden="true" />
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {extra && <span className="text-sm text-ink-muted">{extra}</span>}
        {badges && <span className="ml-auto flex items-center gap-2">{badges}</span>}
      </summary>
      <div className="border-t border-line p-5 sm:p-6">{children}</div>
    </details>
  );
}

const sourceLabel = (source: ErrorSource) => source === "service" ? t("Local service") : source === "mcp" ? t("MCP server") : source === "desktop" ? t("Desktop app") : t("App window");

function ErrorRow({ entry }: { entry: ErrorEntry }) {
  const when = new Date(entry.time);
  const time = Number.isNaN(when.getTime()) ? entry.time : new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" }).format(when);
  const head = <><span className="shrink-0 text-ink-subtle">{time}</span><span className="shrink-0 font-medium text-ink">{sourceLabel(entry.source)}</span>{entry.level === "warning" && <Badge tone="warning">{t("Warning")}</Badge>}<span className="min-w-0 break-words text-ink-muted">{entry.message}</span></>;
  if (!entry.detail) return <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2 text-sm">{head}</li>;
  return (
    <li>
      <details className="group/row">
        <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2 text-sm hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">
          <ChevronRight size={14} className="shrink-0 self-center text-ink-subtle transition-transform group-open/row:rotate-90" aria-hidden="true" />{head}
        </summary>
        <pre className="mx-3 mb-3 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-neutral-soft p-3 font-mono text-xs leading-5 text-ink">{entry.detail}</pre>
      </details>
    </li>
  );
}

function GuideLink({ to, name }: { to: string; name: string }) {
  return (
    <Link to={to} className="group flex items-center justify-between gap-3 rounded-lg border border-line px-4 py-3 hover:border-forest/40 hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">
      <span><span className="block text-sm font-semibold text-ink">{name}</span><span className="block text-xs text-ink-muted">{t("Setup guide")}</span></span>
      <ArrowRight size={16} className="text-ink-subtle group-hover:text-forest" aria-hidden="true" />
    </Link>
  );
}

/** A labelled dropdown, with its explanation under a "?" when there is one. */
function SelectField({ id, label, help, value, choices, onChange }: { id: string; label: string; help?: string; value: string; choices: { value: string; label: string }[]; onChange: (value: string) => void }) {
  return (
    <div>
      <span className="flex items-center gap-2"><label htmlFor={id} className="field-label" style={{ marginBottom: 0 }}>{label}</label>{help && <HelpTip label={label}>{help}</HelpTip>}</span>
      <select id={id} className="field-input mt-2 max-w-xs" value={value} onChange={(event) => onChange(event.target.value)}>{choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select>
    </div>
  );
}

/** Interface size zooms the whole window; text size scales only the text on top of it. */
function AccessibilityCard() {
  const display = useDisplay();
  const desktop = Boolean(window.projectBrainDesktop?.setDisplay);
  const zoomChoices = [
    { value: "auto", label: desktop ? t("Automatic ({size})", { size: percent(display.auto, locale()) }) : t("Automatic") },
    ...zoomSteps.map((step) => ({ value: String(step), label: percent(step, locale()) })),
  ];
  const textChoices = textSteps.map((step) => ({ value: String(step), label: step === 1 ? t("Standard") : percent(step, locale()) }));
  return (
    <Card id="settings-accessibility" title={t("Accessibility")}>
      <div className="space-y-5">
        <SelectField id="interface-size" label={t("Interface size")}
          help={desktop ? t("Makes everything bigger: the sidebar, panels, buttons and text. Automatic picks a size from your screen's resolution. Ctrl+Plus and Ctrl+Minus change it anywhere in the app, and Ctrl+0 goes back to Automatic.") : t("Makes everything bigger: the sidebar, panels, buttons and text.")}
          value={String(display.zoom)} choices={zoomChoices}
          onChange={(value) => void setDisplay({ zoom: value === "auto" ? "auto" : Number(value), text: display.text })} />
        <SelectField id="text-size" label={t("Text size")} help={t("Makes only the text bigger, on top of the interface size, and leaves the layout as it is.")}
          value={String(display.text)} choices={textChoices}
          onChange={(value) => void setDisplay({ zoom: display.zoom, text: Number(value) })} />
        <ReviewKeysSwitch />
      </div>
    </Card>
  );
}

/** Single-letter keys in Review (A, S, J, K) can be turned off (WCAG 2.1.4): speech input
 * "types" letters, and an A heard in passing would accept work. */
function ReviewKeysSwitch() {
  const client = useQueryClient();
  const singleKeys = useSingleKeys();
  const save = useMutation({ mutationFn: (on: boolean) => agentsApi.update({ review_single_keys: on }), onSuccess: (data) => client.setQueryData(queryKeys.agentSettings, data) });
  return (
    <Switch checked={singleKeys} onChange={(on) => save.mutate(on)} label={t("Single-letter keys in Review")}
      help={t("A accepts and opens the next task, S starts a comment, J and K move through the list. Turn them off if you use speech input or they get in your way; the buttons and arrow keys keep working.")} />
  );
}

function Diagnostics() {
  const diagnostics = useQuery({ queryKey: ["diagnostics"], queryFn: ({ signal }) => systemApi.diagnostics(signal), retry: false });
  const errors = useQuery({ queryKey: ["error-log"], queryFn: ({ signal }) => systemApi.errors(signal), retry: false });
  const clear = useMutation({ mutationFn: () => systemApi.clearErrors(), onSuccess: () => { setConfirming(false); void errors.refetch(); void diagnostics.refetch(); } });
  const [copied, setCopied] = useState<"report" | "log" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const later = useTimeout();
  const d = diagnostics.data;
  const log = errors.data;
  const healthy = d ? d.database.integrity === "ok" && d.database.foreign_key_problems === 0 : null;
  const recent = d?.errors?.last_day ?? 0;

  async function copy(kind: "report" | "log", text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(kind); later(() => setCopied(null), 2000); } catch { /* the text is shown on screen */ }
  }

  return (
    <FoldingCard title={t("Diagnostics")} extra={d && t("Version {version}", { version: d.app_version })} onOpen={() => { void errors.refetch(); void diagnostics.refetch(); }}
      badges={<>{recent > 0 && <Badge tone="warning">{tp(recent, "{count} error today", "{count} errors today")}</Badge>}{healthy !== null && <Badge tone={healthy ? "success" : "warning"}>{healthy ? t("Healthy") : t("Needs attention")}</Badge>}</>}>
      {diagnostics.isPending ? <p role="status" className="text-sm text-ink-muted">{t("Checking…")}</p>
        : diagnostics.isError ? <ErrorState title={t("Diagnostics are unavailable")} message={diagnostics.error.message} onRetry={() => void diagnostics.refetch()} />
        : d && <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-ink-muted">{t("Database")}</dt><dd>{healthy ? t("Healthy") : t("Needs attention: {integrity}, {count} link problems", { integrity: d.database.integrity, count: d.database.foreign_key_problems })} <span className="text-ink-subtle">({t("schema {name}", { name: d.database.migration ?? "?" })})</span></dd>
            <dt className="text-ink-muted">{t("Search")}</dt><dd>{d.database.search_index_ready ? t("Ready") : t("Unavailable")}</dd>
            <dt className="text-ink-muted">Git</dt><dd>{d.git.available ? d.git.version : t("Not available to Project Moah, so repository details are hidden")}</dd>
            {d.dictation && <><dt className="text-ink-muted">{t("Dictation")}</dt><dd>{d.dictation.available ? (d.dictation.engine?.last_error ? t("Works. Last problem: {problem}", { problem: serverText(d.dictation.engine.last_error) }) : t("Works")) : t("Dictation is off: {reason}", { reason: serverText(d.dictation.reason ?? "") })}</dd></>}
            <dt className="text-ink-muted">{t("MCP server")}</dt><dd>{tp(d.mcp.tools, "{count} tool, started by your agent when needed", "{count} tools, started by your agent when needed")}</dd>
            {d.builds && <><dt className="text-ink-muted">{t("Build")}</dt><dd>{d.builds.installed}</dd></>}
            <dt className="text-ink-muted">{t("Contents")}</dt><dd>{Object.entries(d.counts).map(([k, v]) => countLabel(k, v)).join(", ")}</dd>
          </dl>}

      <section aria-labelledby="error-log-title" className="mt-6 border-t border-line pt-5">
        <h3 id="error-log-title" className="flex items-center gap-2 text-sm font-semibold">{t("Error log")} <HelpTip label={t("error log")}>{t("When something goes wrong in Project Moah's local service, its MCP server, the desktop app or the window, it is written here. The log stays on this computer, keeps only the newest errors, and shows your home folder as ~. Errors can still name a file or a record, so read the log before you share it.")}</HelpTip>
          {log && log.total > 0 && <span className="text-sm font-normal text-ink-muted">{tp(log.total, "{count} entry", "{count} entries")}</span>}
        </h3>
        {errors.isPending ? <p role="status" className="mt-2 text-sm text-ink-muted">{t("Checking…")}</p>
          : errors.isError ? <p role="alert" className="mt-2 text-sm text-danger-ink">{t("The error log could not be read: {reason}", { reason: errors.error.message })}</p>
          : log && log.entries.length === 0 ? <p className="mt-2 text-sm text-ink-muted">{t("No errors so far.")}</p>
          : log && <ul aria-label={t("Error log")} className="mt-3 max-h-96 divide-y divide-line overflow-auto rounded-lg border border-line">{log.entries.map((entry, i) => <ErrorRow key={`${entry.time}-${i}`} entry={entry} />)}</ul>}
      </section>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button onClick={() => d && void copy("report", diagnosticReport(d))} disabled={!d}>{copied === "report" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied === "report" ? t("Copied") : t("Copy diagnostic report")}</Button>
        {log && log.total > 0 && <>
          <Button onClick={() => void copy("log", errorLogText(log, d?.app_version))}>{copied === "log" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied === "log" ? t("Copied") : t("Copy error log")}</Button>
          <Button variant="quiet" onClick={() => setConfirming(true)}><Trash2 size={16} aria-hidden="true" />{t("Clear log")}</Button>
        </>}
      </div>
      {confirming && <ConfirmDialog title={t("Clear the error log?")} confirmLabel={t("Clear log")} busy={clear.isPending} error={clear.isError ? clear.error.message : null} onConfirm={() => clear.mutate()} onClose={() => setConfirming(false)}>{t("Every entry is deleted from this computer. New errors are logged again as they happen.")}</ConfirmDialog>}
    </FoldingCard>
  );
}

export function SettingsPage() {
  const diagnostics = useQuery({ queryKey: ["diagnostics"], queryFn: ({ signal }) => systemApi.diagnostics(signal), retry: false });
  const backup = useMutation({ mutationFn: () => systemApi.downloadBackup() });
  const [theme, setTheme] = useTheme();
  const [language, setLanguage] = useLanguageChoice();
  const d = diagnostics.data;

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeading title={t("Settings")} description={t("Project Moah runs on this computer, needs no account, and sends no usage data anywhere.")} />

      <Card id="settings-general" title={t("General")}>
        <div className="space-y-5">
          <Choice name="theme" legend={t("Theme")} value={theme} onChange={setTheme} choices={themeChoices.map((c) => ({ ...c, label: t(c.label) }))} />
          <SelectField id="app-language" label={t("Language")} value={language} onChange={(value) => setLanguage(value as typeof language)} choices={languageChoices.map((c) => ({ value: c.value, label: c.value === "system" ? t(c.label) : c.label }))} />
        </div>
      </Card>

      <Card id="settings-dictation" title={t("Dictation")}>
        <DictationSettings />
      </Card>

      <AccessibilityCard />

      <FocusTimerSettings />

      <SoundSettings />

      <Card id="settings-agents" title={t("Connect agents")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <GuideLink to="/help/claude" name="Claude Code" />
          <GuideLink to="/help/codex" name="Codex" />
        </div>
        <div className="mt-6 border-t border-line pt-6"><AgentSettingsCard /></div>
      </Card>

      <Card id="settings-tasks" title={t("Tasks")}>
        <TaskSettingsCard />
      </Card>

      <FoldingCard title={t("Data")} extra={d?.database.size_bytes != null ? megabytes(d.database.size_bytes) : undefined}>
        {d?.database.path && <p className="text-sm">{tx("Location: {path} ({size})", { path: <code className="break-all rounded bg-neutral-soft px-1.5 py-0.5 text-xs">{d.database.path}</code>, size: megabytes(d.database.size_bytes) })}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={() => backup.mutate()} disabled={backup.isPending}><Download size={16} aria-hidden="true" />{backup.isPending ? t("Preparing…") : t("Export Project Moah backup")}</Button>
          {backup.isSuccess && <span role="status" className="text-sm text-forest">{t("Backup created: {file}. Find it in your downloads, or where you chose to save it.", { file: backup.data })}</span>}
        </div>
        {backup.isError && <p role="alert" className="mt-2 text-sm text-danger-ink">{backup.error.message}</p>}
        <p className="mt-3 text-xs leading-6 text-ink-subtle">{tx("To restore, close Project Moah and replace the database file with your backup. <help>More about your data</help>.", { help: (text) => <Link to="/help/data-and-backup" className="underline">{text}</Link> })}</p>
      </FoldingCard>

      <Diagnostics />
    </div>
  );
}
