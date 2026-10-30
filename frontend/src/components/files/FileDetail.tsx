import { useQuery } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { memoryApi } from "../../api/memory";
import { useFileActions, useFileHistory, useFileNotes } from "../../hooks/useFiles";
import { useTasks } from "../../hooks/useTasks";
import type { FileTreeEntry } from "../../types/files";
import { InlineText } from "../tasks/TaskBits";
import { Button, ErrorState, formatDate } from "../ui";
import { t } from "../../lib/i18n";

function LinkPicker({ label, options, selectedIds, onAdd, onRemove, chips, readonly }: { label: string; options: { id: string; label: string }[]; selectedIds: Set<string>; onAdd: (id: string) => void; onRemove: (id: string) => void; chips: { id: string; label: string }[]; readonly: boolean }) {
  const free = options.filter((o) => !selectedIds.has(o.id));
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{label}</h4>
      {chips.length === 0 && <p className="mt-1 text-sm text-ink-subtle">{t("None linked.")}</p>}
      <ul className="mt-1.5 flex flex-wrap gap-1.5">{chips.map((c) => <li key={c.id} className="inline-flex items-center gap-1 rounded-lg bg-sage-pale px-2 py-1 text-xs font-medium text-forest">{c.label}{!readonly && <button type="button" aria-label={t("Unlink {name}", { name: c.label })} onClick={() => onRemove(c.id)} className="rounded p-0.5 hover:bg-surface"><X size={12} /></button>}</li>)}</ul>
      {!readonly && free.length > 0 && <select aria-label={t("Link: {kind}", { kind: label })} value="" onChange={(e) => e.target.value && onAdd(e.target.value)} className="field-input mt-2 !min-h-9 !w-auto max-w-full"><option value="">{t("Link…")}</option>{free.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</select>}
    </div>
  );
}

export function FileDetail({ projectId, entry, readonly, onGone }: { projectId: string; entry: FileTreeEntry; readonly: boolean; onGone: () => void }) {
  const notes = useFileNotes(projectId, entry.file_id);
  const history = useFileHistory(projectId, entry.file_id);
  const actions = useFileActions(projectId);
  const tasks = useTasks(projectId);
  const memories = useQuery({ queryKey: ["memory-links", projectId], queryFn: ({ signal }) => memoryApi.list(projectId, { statuses: ["active"] }, signal) });
  const [symbol, setSymbol] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const error = (actions.create.error ?? actions.update.error ?? actions.remove.error ?? actions.reviewed.error) as Error | null;

  if (!entry.file_id) {
    return (
      <div className="rounded-xl border border-line bg-surface p-6 shadow-card">
        <h3 className="break-all text-lg font-semibold">{entry.path}</h3>
        <p className="mt-2 text-sm text-ink-muted">{t("Project Moah has no notes about this file yet. Notes tell agents what a file is for, so they can open the right one first.")}</p>
        {entry.changed && <p className="mt-2 text-sm text-info-ink">{t("It is {state} in the working tree.", { state: entry.changed })}</p>}
        {!readonly && <Button variant="primary" className="mt-4" onClick={() => actions.create.mutate({ path: entry.path })} disabled={actions.create.isPending}><Plus size={16} />{t("Add notes")}</Button>}
        {error && <p role="alert" className="mt-3 text-sm text-danger-ink">{error.message}</p>}
      </div>
    );
  }
  if (notes.isPending) return <div role="status" aria-label={t("Loading file")} className="h-64 animate-pulse rounded-xl bg-surface" />;
  if (notes.isError) return <ErrorState title={t("File notes could not be loaded")} message={notes.error.message} onRetry={() => void notes.refetch()} />;
  const f = notes.data;
  const save = (changes: Parameters<typeof actions.update.mutate>[0]["changes"], onSuccess?: () => void) => actions.update.mutate({ id: f.id, changes }, { onSuccess });
  const symbolInputs = f.symbols.map((s) => ({ name: s.name, kind: s.kind, summary: s.summary }));
  const addSymbol = (event: FormEvent) => { event.preventDefault(); if (symbol.trim()) { save({ symbols: [...symbolInputs, { name: symbol.trim(), kind: "symbol" }] }, () => setSymbol("")); } };
  const taskOptions = (tasks.data ?? []).map((t) => ({ id: t.id, label: `${t.human_id} ${t.title}` }));
  const memoryOptions = (memories.data ?? []).map((m) => ({ id: m.id, label: `${m.human_id} ${m.title}` }));

  return (
    <div className="space-y-5 rounded-xl border border-line bg-surface p-6 shadow-card">
      <div>
        <h3 className="break-all text-lg font-semibold">{f.path}</h3>
        <p className="mt-1 text-xs text-ink-subtle">{f.language ?? t("Unknown language")}</p>
        {f.stale && <div role="status" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-warning-soft px-3 py-2 text-sm text-warning-ink">{t("This file changed since these notes were last reviewed.")}{!readonly && <Button onClick={() => actions.reviewed.mutate(f.id)}><RefreshCw size={14} />{t("Notes are still correct")}</Button>}</div>}
      </div>
      <div><h4 className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{t("Purpose")}</h4><InlineText value={f.purpose ?? ""} label={t("Purpose")} placeholder={t("What is this file for?")} onSave={(v) => actions.update.mutateAsync({ id: f.id, changes: { purpose: v || null } })} readOnly={readonly} /></div>
      <div><h4 className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{t("Summary")}</h4><InlineText multiline value={f.summary ?? ""} label={t("Summary")} placeholder={t("What should someone know before opening it?")} onSave={(v) => actions.update.mutateAsync({ id: f.id, changes: { summary: v || null } })} readOnly={readonly} /></div>
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{t("Important symbols")}</h4>
        {f.symbols.length === 0 && <p className="mt-1 text-sm text-ink-subtle">{t("None listed.")}</p>}
        <ul className="mt-1.5 flex flex-wrap gap-1.5">{f.symbols.map((s) => <li key={s.id} className="inline-flex items-center gap-1 rounded-lg bg-neutral-soft px-2 py-1 font-mono text-xs"><span title={s.kind}>{s.name}</span>{!readonly && <button type="button" aria-label={t("Remove symbol {name}", { name: s.name })} onClick={() => save({ symbols: symbolInputs.filter((x) => x.name !== s.name || x.kind !== s.kind) })} className="rounded p-0.5 hover:bg-surface"><X size={12} /></button>}</li>)}</ul>
        {!readonly && <form onSubmit={addSymbol} className="mt-2 flex gap-2"><input aria-label={t("Add a symbol")} value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder={t("Class or function name")} className="field-input !min-h-9" maxLength={200} /><Button type="submit" disabled={!symbol.trim()}>{t("Add")}</Button></form>}
      </div>
      <LinkPicker label={t("Related tasks")} options={taskOptions} selectedIds={new Set(f.tasks.map((t) => t.id))} chips={f.tasks.map((t) => ({ id: t.id, label: t.human_id }))} readonly={readonly} onAdd={(id) => save({ task_ids: [...f.tasks.map((t) => t.id), id] })} onRemove={(id) => save({ task_ids: f.tasks.filter((t) => t.id !== id).map((t) => t.id) })} />
      <LinkPicker label={t("Related decisions, rules, and bugs")} options={memoryOptions} selectedIds={new Set(f.memories.map((m) => m.id))} chips={f.memories.map((m) => ({ id: m.id, label: m.human_id }))} readonly={readonly} onAdd={(id) => save({ memory_ids: [...f.memories.map((m) => m.id), id] })} onRemove={(id) => save({ memory_ids: f.memories.filter((m) => m.id !== id).map((m) => m.id) })} />
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{t("Recent Git activity")}</h4>
        {history.isPending ? <p className="mt-1 text-sm text-ink-subtle">{t("Loading…")}</p> : history.isError ? <p role="alert" className="mt-1 text-sm text-danger-ink">{t("History could not be loaded.")} {history.error.message}</p> : history.data.git.state !== "ok" ? <p className="mt-1 text-sm text-ink-subtle">{history.data?.git.message}</p> : history.data.commits.length === 0 ? <p className="mt-1 text-sm text-ink-subtle">{t("No commits touch this file yet.")}</p>
          : <ul className="mt-1.5 space-y-1 text-sm">{history.data.commits.map((c) => <li key={c.sha}><span className="font-mono text-xs text-forest">{c.short_sha}</span> {c.subject} <span className="text-xs text-ink-subtle">{formatDate(c.committed_at)}</span></li>)}</ul>}
      </div>
      {error && <p role="alert" className="text-sm text-danger-ink">{error.message}</p>}
      {!readonly && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4">
          <p className="text-xs text-ink-subtle">{t("Removing notes never changes the file itself.")}</p>
          {confirmRemove ? <span className="flex items-center gap-2 text-sm">{t("Remove notes?")} <Button variant="danger" onClick={() => actions.remove.mutate(f.id, { onSuccess: onGone })}>{t("Remove")}</Button><Button variant="quiet" onClick={() => setConfirmRemove(false)}>{t("Cancel")}</Button></span>
            : <Button variant="quiet" className="text-danger-ink" onClick={() => setConfirmRemove(true)}><Trash2 size={16} />{t("Remove notes")}</Button>}
        </div>
      )}
    </div>
  );
}
