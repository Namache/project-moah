import { AgentSettingsCard } from "../components/AgentSettingsCard";
import { TaskSettingsCard } from "../components/TaskSettingsCard";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Copy, Download } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { IntegrationSnippet } from "../components/help/IntegrationSnippet";
import { Button, ErrorState, PageHeading } from "../components/ui";
import { systemApi, type Diagnostics } from "../api/system";
import { useTimeout } from "../hooks/useTimeout";
import { themeChoices, useTheme } from "../lib/theme";

const megabytes = (bytes: number | null) => (bytes === null ? "unknown" : `${(bytes / 1_048_576).toFixed(bytes < 10_485_760 ? 2 : 1)} MB`);

export function diagnosticReport(d: Diagnostics): string {
  return [
    `Project Moah ${d.app_version}`, `Platform: ${d.platform}`, `Python ${d.python}, SQLite ${d.sqlite_version}`,
    `Database: ${d.database.path ?? "unknown"} (${megabytes(d.database.size_bytes)})`,
    `Migration: ${d.database.migration}`, `Integrity: ${d.database.integrity}, foreign key problems: ${d.database.foreign_key_problems}`,
    `Search index: ${d.database.search_index_ready ? "ready" : "unavailable"}`, `Git: ${d.git.available ? d.git.version ?? "available" : "not available"}`,
    `Records: ${Object.entries(d.counts).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(", ")}`,
  ].join("\n");
}

// On screen, records use the app's own words; the copied report keeps the raw names for bug reports.
const RECORD_LABELS: Record<string, string> = { pending_proposals: "suggestions waiting for review" };
const recordLabel = (key: string) => RECORD_LABELS[key] ?? key.replace(/_/g, " ");

/** System, Light or Dark, as a segmented control built from real radio buttons. */
function ThemePicker() {
  const [theme, setTheme] = useTheme();
  return (
    <fieldset>
      <legend className="text-sm text-ink-muted">Theme. System follows your computer's light or dark setting.</legend>
      <div className="segmented mt-3">
        {themeChoices.map(({ value, label, icon: Icon }) => (
          <label key={value} className={`filter-tab inline-flex cursor-pointer items-center gap-2 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-forest ${theme === value ? "filter-tab-active" : ""}`}>
            <input type="radio" name="theme" value={value} checked={theme === value} onChange={() => setTheme(value)} className="sr-only" />
            <Icon size={15} aria-hidden="true" />{label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Card({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return <section aria-labelledby={id} className="rounded-xl border border-line bg-surface p-5 shadow-card sm:p-6"><h2 id={id} className="text-base font-semibold tracking-tight">{title}</h2><div className="mt-3">{children}</div></section>;
}

export function SettingsPage() {
  const diagnostics = useQuery({ queryKey: ["diagnostics"], queryFn: ({ signal }) => systemApi.diagnostics(signal), retry: false });
  const backup = useMutation({ mutationFn: () => systemApi.downloadBackup() });
  const [copied, setCopied] = useState(false);
  const later = useTimeout();
  const [agent, setAgent] = useState<"claude" | "codex">("claude");
  const d = diagnostics.data;

  async function copyReport() {
    if (!d) return;
    try { await navigator.clipboard.writeText(diagnosticReport(d)); setCopied(true); later(() => setCopied(false), 2000); } catch { /* the report is shown on screen */ }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeading title="Settings" description="Project Moah runs on this computer, needs no account, and sends no usage data anywhere." />

      <Card id="settings-appearance" title="Appearance">
        <ThemePicker />
      </Card>

      <Card id="settings-agents" title="Agents">
        <p className="text-sm text-ink-muted">Claude Code and Codex connect to Project Moah on this computer, so they can read your project's context and record their work. The connection is local and needs no network.</p>
        <section aria-labelledby="settings-connect" className="mt-6">
          <h3 id="settings-connect" className="text-sm font-semibold text-ink">Connect an agent</h3>
          <p className="mt-1 text-xs text-ink-subtle">Run these once per agent. Step-by-step guides: <Link to="/help/claude" className="font-medium text-forest underline">Claude Code</Link>, <Link to="/help/codex" className="font-medium text-forest underline">Codex</Link>.</p>
          <div role="group" aria-label="Agent to connect" className="segmented mt-3">
            {(["claude", "codex"] as const).map((a) => <button key={a} type="button" aria-pressed={agent === a} onClick={() => setAgent(a)} className={`filter-tab ${agent === a ? "filter-tab-active" : ""}`}>{a === "claude" ? "Claude Code" : "Codex"}</button>)}
          </div>
          <IntegrationSnippet key={agent} agent={agent} />
        </section>
        <section aria-labelledby="settings-agent-defaults" className="mt-8 border-t border-line pt-6">
          <h3 id="settings-agent-defaults" className="mb-4 text-sm font-semibold text-ink">How agents work together</h3>
          <AgentSettingsCard />
        </section>
      </Card>

      <Card id="settings-tasks" title="Tasks">
        <TaskSettingsCard />
      </Card>

      <Card id="settings-data" title="Data">
        <p className="text-sm leading-7 text-ink-muted">Everything is stored in one file on this computer. Your source code is never copied into it, and deleting a project here never deletes a repository.</p>
        {d?.database.path && <p className="mt-3 text-sm"><span className="text-ink-muted">Location:</span> <code className="break-all rounded bg-neutral-soft px-1.5 py-0.5 text-xs">{d.database.path}</code> <span className="text-ink-subtle">({megabytes(d.database.size_bytes)})</span></p>}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={() => backup.mutate()} disabled={backup.isPending}><Download size={16} aria-hidden="true" />{backup.isPending ? "Preparing…" : "Export Project Moah backup"}</Button>
          {backup.isSuccess && <span role="status" className="text-sm text-forest">Backup created: {backup.data}. Find it in your downloads, or where you chose to save it.</span>}
        </div>
        {backup.isError && <p role="alert" className="mt-2 text-sm text-danger-ink">{backup.error.message}</p>}
        <p className="mt-3 text-xs leading-6 text-ink-subtle">To restore, close Project Moah and replace the database file with your backup. <Link to="/help/data-and-backup" className="underline">More about your data</Link>.</p>
      </Card>

      <Card id="settings-advanced" title="Advanced diagnostics">
        {diagnostics.isPending ? <p role="status" className="text-sm text-ink-muted">Checking…</p>
          : diagnostics.isError ? <ErrorState title="Diagnostics are unavailable" message={diagnostics.error.message} onRetry={() => void diagnostics.refetch()} />
          : d && <>
            <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-ink-muted">Version</dt><dd>{d.app_version}</dd>
              <dt className="text-ink-muted">Database</dt><dd>{d.database.integrity === "ok" && d.database.foreign_key_problems === 0 ? "Healthy" : `Needs attention: ${d.database.integrity}, ${d.database.foreign_key_problems} link problems`} <span className="text-ink-subtle">(schema {d.database.migration})</span></dd>
              <dt className="text-ink-muted">Search</dt><dd>{d.database.search_index_ready ? "Ready" : "Unavailable"}</dd>
              <dt className="text-ink-muted">Git</dt><dd>{d.git.available ? d.git.version : "Not available to Project Moah, so repository details are hidden"}</dd>
              <dt className="text-ink-muted">MCP server</dt><dd>{d.mcp.tools} tools, started by your agent when needed</dd>
              <dt className="text-ink-muted">Records</dt><dd>{Object.entries(d.counts).map(([k, v]) => `${v} ${recordLabel(k)}`).join(", ")}</dd>
            </dl>
            <Button className="mt-4" onClick={() => void copyReport()}>{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? "Copied" : "Copy diagnostic report"}</Button>
            <p className="mt-2 text-xs text-ink-subtle">The report lists counts and versions only, never your project content.</p>
          </>}
      </Card>
    </div>
  );
}
