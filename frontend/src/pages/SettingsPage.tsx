import { AgentSettingsCard } from "../components/AgentSettingsCard";
import { TaskSettingsCard } from "../components/TaskSettingsCard";
import { Choice } from "../components/Choice";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, ChevronRight, Copy, Download } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, ErrorState, PageHeading } from "../components/ui";
import { systemApi, type Diagnostics } from "../api/system";
import { useTimeout } from "../hooks/useTimeout";
import { languageChoices, locale, t, tp, tx, useLanguageChoice } from "../lib/i18n";
import { themeChoices, useTheme } from "../lib/theme";

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
  ].join("\n");
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

function GuideLink({ to, name }: { to: string; name: string }) {
  return (
    <Link to={to} className="group flex items-center justify-between gap-3 rounded-lg border border-line px-4 py-3 hover:border-forest/40 hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">
      <span><span className="block text-sm font-semibold text-ink">{name}</span><span className="block text-xs text-ink-muted">{t("Setup guide")}</span></span>
      <ArrowRight size={16} className="text-ink-subtle group-hover:text-forest" aria-hidden="true" />
    </Link>
  );
}

function Diagnostics() {
  const diagnostics = useQuery({ queryKey: ["diagnostics"], queryFn: ({ signal }) => systemApi.diagnostics(signal), retry: false });
  const [copied, setCopied] = useState(false);
  const later = useTimeout();
  const d = diagnostics.data;
  const healthy = d ? d.database.integrity === "ok" && d.database.foreign_key_problems === 0 : null;

  async function copyReport() {
    if (!d) return;
    try { await navigator.clipboard.writeText(diagnosticReport(d)); setCopied(true); later(() => setCopied(false), 2000); } catch { /* the report is shown on screen */ }
  }

  return (
    <details className="group rounded-xl border border-line bg-surface shadow-card">
      <summary className="flex cursor-pointer list-none items-center gap-3 rounded-xl p-5 focus-visible:outline-2 focus-visible:outline-forest sm:px-6">
        <ChevronRight size={16} className="text-ink-subtle transition-transform group-open:rotate-90" aria-hidden="true" />
        <h2 className="text-base font-semibold tracking-tight">{t("Diagnostics")}</h2>
        {d && <span className="text-sm text-ink-muted">{t("Version {version}", { version: d.app_version })}</span>}
        {healthy !== null && <Badge tone={healthy ? "success" : "warning"} className="ml-auto">{healthy ? t("Healthy") : t("Needs attention")}</Badge>}
      </summary>
      <div className="border-t border-line p-5 sm:p-6">
        {diagnostics.isPending ? <p role="status" className="text-sm text-ink-muted">{t("Checking…")}</p>
          : diagnostics.isError ? <ErrorState title={t("Diagnostics are unavailable")} message={diagnostics.error.message} onRetry={() => void diagnostics.refetch()} />
          : d && <>
            <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-ink-muted">{t("Database")}</dt><dd>{healthy ? t("Healthy") : t("Needs attention: {integrity}, {count} link problems", { integrity: d.database.integrity, count: d.database.foreign_key_problems })} <span className="text-ink-subtle">({t("schema {name}", { name: d.database.migration ?? "?" })})</span></dd>
              <dt className="text-ink-muted">{t("Search")}</dt><dd>{d.database.search_index_ready ? t("Ready") : t("Unavailable")}</dd>
              <dt className="text-ink-muted">Git</dt><dd>{d.git.available ? d.git.version : t("Not available to Project Moah, so repository details are hidden")}</dd>
              <dt className="text-ink-muted">{t("MCP server")}</dt><dd>{tp(d.mcp.tools, "{count} tool, started by your agent when needed", "{count} tools, started by your agent when needed")}</dd>
              <dt className="text-ink-muted">{t("Contents")}</dt><dd>{Object.entries(d.counts).map(([k, v]) => countLabel(k, v)).join(", ")}</dd>
            </dl>
            <Button className="mt-4" onClick={() => void copyReport()}>{copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied ? t("Copied") : t("Copy diagnostic report")}</Button>
            <p className="mt-2 text-xs text-ink-subtle">{t("The report lists counts and versions only, never your project content. It stays in English, so anyone can read it.")}</p>
          </>}
      </div>
    </details>
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
          <Choice name="theme" legend={t("Theme")} hint={t("System follows your computer's light or dark setting.")} value={theme} onChange={setTheme} choices={themeChoices.map((c) => ({ ...c, label: t(c.label) }))} />
          <Choice name="language" legend={t("Language")} hint={t("System follows your computer's language.")} value={language} onChange={setLanguage} choices={languageChoices.map((c) => ({ ...c, label: c.value === "system" ? t(c.label) : c.label }))} />
        </div>
      </Card>

      <Card id="settings-agents" title={t("Agents")}>
        <p className="text-sm text-ink-muted">{t("Connect each agent once, and it works in every project. The connection stays on this computer.")}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <GuideLink to="/help/claude" name="Claude Code" />
          <GuideLink to="/help/codex" name="Codex" />
        </div>
        <div className="mt-6 border-t border-line pt-6"><AgentSettingsCard /></div>
      </Card>

      <Card id="settings-tasks" title={t("Tasks")}>
        <TaskSettingsCard />
      </Card>

      <Card id="settings-data" title={t("Data")}>
        <p className="text-sm leading-7 text-ink-muted">{t("Everything is stored in one file on this computer. Your source code is never copied into it, and deleting a project here never deletes a repository.")}</p>
        {d?.database.path && <p className="mt-3 text-sm">{tx("Location: {path} ({size})", { path: <code className="break-all rounded bg-neutral-soft px-1.5 py-0.5 text-xs">{d.database.path}</code>, size: megabytes(d.database.size_bytes) })}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={() => backup.mutate()} disabled={backup.isPending}><Download size={16} aria-hidden="true" />{backup.isPending ? t("Preparing…") : t("Export Project Moah backup")}</Button>
          {backup.isSuccess && <span role="status" className="text-sm text-forest">{t("Backup created: {file}. Find it in your downloads, or where you chose to save it.", { file: backup.data })}</span>}
        </div>
        {backup.isError && <p role="alert" className="mt-2 text-sm text-danger-ink">{backup.error.message}</p>}
        <p className="mt-3 text-xs leading-6 text-ink-subtle">{tx("To restore, close Project Moah and replace the database file with your backup. <help>More about your data</help>.", { help: (text) => <Link to="/help/data-and-backup" className="underline">{text}</Link> })}</p>
      </Card>

      <Diagnostics />
    </div>
  );
}
