import { useState } from "react";
import { Plus, X } from "lucide-react";
import { Button, HelpTip } from "../ui";
import { useMemoryActions, useMemoryList } from "../../hooks/useMemory";
import type { MemoryRecord } from "../../types/memory";
import { t } from "../../lib/i18n";

/** The memory web: links between memories of one project. A context pack that includes one brings the others. */
export function ConnectedMemories({ projectId, memory, readonly, onOpen }: { projectId: string; memory: MemoryRecord; readonly: boolean; onOpen: (ref: string) => void }) {
  const actions = useMemoryActions(projectId);
  const candidates = useMemoryList(projectId, { statuses: ["active"], limit: 500 }, !readonly);
  const [choice, setChoice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const related = memory.related ?? [];
  const linked = new Set([memory.id, ...related.map((r) => r.id)]);
  const options = (candidates.data ?? []).filter((m) => !linked.has(m.id));

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : t("The link could not be changed.")); }
  }

  return (
    <section className="border-t border-line px-6 py-5" aria-labelledby="connected-title">
      <h3 id="connected-title" className="flex items-center gap-1.5 text-sm font-semibold text-ink">{t("Connected memories")} <HelpTip label={t("connected memories")}>{t("When an agent's context includes this memory, connected memories come with it. Agents also add connections as they record what they learn.")}</HelpTip></h3>
      {related.length ? (
        <ul className="mt-3 space-y-1.5">
          {related.map((ref) => (
            <li key={ref.id} className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
              <button type="button" onClick={() => onOpen(ref.human_id)} className="min-w-0 truncate text-left hover:text-forest focus-visible:outline-2 focus-visible:outline-forest"><strong className="text-forest">{ref.human_id}</strong> {ref.title}</button>
              {!readonly && <button type="button" aria-label={t("Disconnect {id}", { id: ref.human_id })} onClick={() => void run(() => actions.unlink.mutateAsync({ ref: memory.id, related: ref.id }))} className="rounded-md p-1 text-ink-muted hover:bg-neutral-soft"><X size={15} /></button>}
            </li>
          ))}
        </ul>
      ) : <p className="mt-1 text-xs text-ink-subtle">{t("Not connected to other memories yet.")}</p>}
      {!readonly && (
        <div className="mt-3 flex gap-2">
          <label htmlFor="connect-memory" className="sr-only">{t("Memory to connect")}</label>
          <select id="connect-memory" className="field-input" value={choice} onChange={(event) => setChoice(event.target.value)} disabled={!options.length}>
            <option value="">{candidates.isPending ? t("Loading memories…") : options.length ? t("Choose a memory to connect…") : t("No other active memories")}</option>
            {options.map((m) => <option key={m.id} value={m.id}>{m.human_id} {m.title}</option>)}
          </select>
          <Button onClick={() => { const related = choice; setChoice(""); void run(() => actions.link.mutateAsync({ ref: memory.id, related })); }} disabled={!choice || actions.link.isPending}><Plus size={16} />{t("Connect")}</Button>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-danger-ink">{error}</p>}
    </section>
  );
}
