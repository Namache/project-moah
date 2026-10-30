import { useState } from "react";
import { ChevronDown, Library, Plus, Trash2, X } from "lucide-react";
import { Button, ConfirmDialog, HelpTip, collapsibleHeader, collapsibleOpen, collapsiblePill } from "../ui";
import { notify } from "../../lib/notify";
import { useGraphActions, useShelf, useShelfActivation, useShelves } from "../../hooks/useGraph";
import type { Shelf } from "../../types/graph";

const splitWords = (value: string) => value.split(",").map((word) => word.trim()).filter(Boolean);

/** Specialty Shelves: knowledge domains that stay dormant until a task wakes them. */
export function ShelvesPanel({ projectId, readonly }: { projectId: string; readonly: boolean }) {
  const shelves = useShelves(projectId);
  const actions = useGraphActions(projectId);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [keywords, setKeywords] = useState("");
  const [trial, setTrial] = useState("");
  const [error, setError] = useState<string | null>(null);
  const list = shelves.data ?? [];

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : "The shelf could not be changed."); }
  }

  return (
    <section aria-label="Shelves" className={open ? collapsibleOpen : undefined}>
      <button type="button" aria-expanded={open} aria-controls="shelves-body" onClick={() => setOpen((value) => !value)} className={open ? collapsibleHeader : collapsiblePill}>
        <Library size={15} className="text-forest" aria-hidden="true" />Shelves
        <span className="text-xs font-normal tabular-nums text-ink-subtle">{shelves.isPending ? "" : `${list.length}`}</span>
        <ChevronDown size={14} className={`ml-auto transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && <div id="shelves-body" className="mt-3">
        <p className="flex items-center gap-1.5 text-xs leading-5 text-ink-muted">A shelf is a knowledge area such as Inventory or Save System. When a task mentions its name or keywords, or works on records on it, the shelf wakes and its rules and memory join the agent's context; the rest stay out. <HelpTip label="shelves">Tagging a memory or task with a shelf's name also puts it on that shelf. A record can sit on many shelves and still exists once.</HelpTip></p>
        {list.length > 0 && <ul className="mt-3 space-y-1.5">
          {list.map((shelf) => <ShelfRow key={shelf.id} projectId={projectId} shelf={shelf} parent={list.find((s) => s.id === shelf.parent_id)?.name} open={selected === shelf.id} onToggle={() => setSelected(selected === shelf.id ? null : shelf.id)} readonly={readonly} />)}
        </ul>}
        {!readonly && <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto]">
          <label className="sr-only" htmlFor="shelf-name">Shelf name</label>
          <input id="shelf-name" className="field-input" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder="New shelf, e.g. Inventory" />
          <label className="sr-only" htmlFor="shelf-keywords">Keywords</label>
          <input id="shelf-keywords" className="field-input" value={keywords} onChange={(event) => setKeywords(event.target.value)} placeholder="Keywords that wake it: items, loot, stack" />
          <Button disabled={!name.trim() || actions.createShelf.isPending} onClick={() => { const input = { name: name.trim(), keywords: splitWords(keywords) }; setName(""); setKeywords(""); void run(() => actions.createShelf.mutateAsync(input)); }}><Plus size={16} />Add shelf</Button>
        </div>}
        {list.length > 0 && <div className="mt-4">
          <label htmlFor="shelf-trial" className="text-xs font-semibold text-ink-muted">Try a task</label>
          <input id="shelf-trial" className="field-input mt-1" value={trial} maxLength={2000} onChange={(event) => setTrial(event.target.value)} placeholder="Fix duplicated items after loading a save" />
          {trial.trim() && <Activation projectId={projectId} text={trial} />}
        </div>}
        {error && <p role="alert" className="mt-2 text-xs text-danger-ink">{error}</p>}
      </div>}
    </section>
  );
}

function Activation({ projectId, text }: { projectId: string; text: string }) {
  const activation = useShelfActivation(projectId, text);
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Shelves this task wakes">
      {(activation.data ?? []).map((item) => (
        <li key={item.id} title={item.reason} className={`rounded-full border px-2.5 py-0.5 text-xs ${item.active ? "border-forest bg-sage-pale font-semibold text-forest" : "border-line text-ink-subtle"}`}>{item.name} {Math.round(item.activation * 100)}%</li>
      ))}
    </ul>
  );
}

function ShelfRow({ projectId, shelf, parent, open, onToggle, readonly }: { projectId: string; shelf: Shelf; parent?: string; open: boolean; onToggle: () => void; readonly: boolean }) {
  const detail = useShelf(projectId, open ? shelf.id : null);
  const actions = useGraphActions(projectId);
  const [member, setMember] = useState("");
  const [keywords, setKeywords] = useState(shelf.keywords.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : "The shelf could not be changed."); }
  }

  return (
    <li className="rounded-lg border border-line text-sm">
      <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-center gap-2 px-3 py-2 text-left focus-visible:outline-2 focus-visible:outline-forest">
        <strong className="text-ink">{shelf.name}</strong>
        {parent && <span className="text-xs text-ink-subtle">in {parent}</span>}
        <span className="min-w-0 truncate text-xs text-ink-muted">{shelf.keywords.join(", ")}</span>
        <span className="ml-auto shrink-0 text-xs text-ink-subtle">{shelf.member_count} records</span>
      </button>
      {open && <div className="border-t border-line px-3 py-2">
        {detail.data?.members.length ? <ul className="space-y-1">
          {detail.data.members.map((node) => (
            <li key={`${node.kind}-${node.id}`} className="flex items-center justify-between gap-2 text-xs">
              <span className="min-w-0 truncate"><strong className="text-forest">{node.label}</strong> {node.title !== node.label && node.title}</span>
              {!readonly && <button type="button" aria-label={`Take ${node.label} off ${shelf.name}`} onClick={() => void run(() => actions.removeMember.mutateAsync({ ref: shelf.id, node: `${node.kind}:${node.id}` }))} className="rounded-md p-1 text-ink-muted hover:bg-neutral-soft"><X size={14} /></button>}
            </li>
          ))}
        </ul> : <p className="text-xs text-ink-subtle">{detail.isPending ? "Loading…" : "Nothing on this shelf yet."}</p>}
        {!readonly && <div className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
          <input aria-label={`Record to put on ${shelf.name}`} className="field-input" value={member} maxLength={1100} onChange={(event) => setMember(event.target.value)} placeholder="RULE-004, PB-12, file:src/inventory.gd" />
          <Button disabled={!member.trim()} onClick={() => { const node = member.trim(); setMember(""); void run(() => actions.addMember.mutateAsync({ ref: shelf.id, node })); }}><Plus size={16} />Add</Button>
          <input aria-label={`Keywords for ${shelf.name}`} className="field-input" value={keywords} onChange={(event) => setKeywords(event.target.value)} placeholder="Keywords, comma separated" />
          <Button disabled={keywords === shelf.keywords.join(", ")} onClick={() => void run(async () => { const saved = await actions.updateShelf.mutateAsync({ ref: shelf.id, input: { keywords: splitWords(keywords) } }); setKeywords(saved.keywords.join(", ")); })}>Save keywords</Button>
        </div>}
        {!readonly && <button type="button" onClick={() => setDeleting(true)} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-danger-ink hover:underline"><Trash2 size={13} />Delete shelf</button>}
        {error && <p role="alert" className="mt-2 text-xs text-danger-ink">{error}</p>}
      </div>}
      {deleting && <ConfirmDialog title={`Delete the ${shelf.name} shelf?`} confirmLabel="Delete shelf" onClose={() => setDeleting(false)}
        onConfirm={() => { setDeleting(false); void run(async () => { await actions.deleteShelf.mutateAsync(shelf.id); notify(`${shelf.name} shelf deleted`); }); }}>Its memories stay where they are.</ConfirmDialog>}
      {deleting && <ConfirmDialog title={`Delete the ${shelf.name} shelf?`} confirmLabel="Delete shelf" onClose={() => setDeleting(false)}
        onConfirm={() => { setDeleting(false); void run(async () => { await actions.deleteShelf.mutateAsync(shelf.id); notify(`${shelf.name} shelf deleted`); }); }}>Its memories stay where they are.</ConfirmDialog>}
    </li>
  );
}
