import { Bot, Lock } from "lucide-react";
import { useId, useState } from "react";
import { useReviewActions } from "../../hooks/useProposals";
import { proposalLabels, type Proposal } from "../../types/proposal";
import { Badge, Button, formatDate } from "../ui";
import { t } from "../../lib/i18n";

type Draft = Record<string, unknown>;
type FieldKind = "boolean" | "list" | "number" | "text" | "fixed";

function kindOf(value: unknown): FieldKind {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "number";
  if (Array.isArray(value)) return value.every((item) => typeof item === "string" || typeof item === "number") ? "list" : "fixed";
  if (value !== null && typeof value === "object") return "fixed";
  return "text";
}

function asText(value: unknown, kind: FieldKind): string {
  if (kind === "list") return (value as unknown[]).join(", ");
  return value == null ? "" : String(value);
}

/** Text fields are edited as typed text, so commas and partial numbers survive until the person accepts. */
function draftFrom(payload: Draft): Draft {
  return Object.fromEntries(Object.entries(payload).map(([key, value]) => {
    const kind = kindOf(value);
    return [key, kind === "boolean" || kind === "fixed" ? value : asText(value, kind)];
  }));
}

/** Turns the edited text back into the payload's own types; untouched fields keep their original value. */
function payloadFrom(original: Draft, draft: Draft): Draft {
  return Object.fromEntries(Object.entries(original).map(([key, value]) => {
    const kind = kindOf(value);
    const edited = draft[key];
    if (kind === "boolean" || kind === "fixed" || edited === asText(value, kind)) return [key, kind === "boolean" ? edited : value];
    const text = String(edited ?? "");
    if (kind === "list") return [key, text.split(",").map((item) => item.trim()).filter(Boolean)];
    if (kind === "number") return [key, text.trim() === "" ? null : Number.isFinite(Number(text)) ? Number(text) : text];
    return [key, text];
  }));
}

/** Edits a proposal's payload with plain fields: text, numbers, yes/no, or comma-separated lists. Structured values are shown, not edited. */
function PayloadEditor({ original, draft, onChange }: { original: Draft; draft: Draft; onChange: (next: Draft) => void }) {
  const idBase = useId();
  return (
    <div className="mt-3 space-y-3 rounded-xl bg-neutral-soft p-3">
      {Object.entries(original).map(([key, value]) => {
        const label = key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
        const id = `${idBase}-${key}`;
        const kind = kindOf(value);
        const text = String(draft[key] ?? "");
        if (kind === "boolean") return <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(draft[key])} onChange={(e) => onChange({ ...draft, [key]: e.target.checked })} className="h-4 w-4 accent-primary" />{label}</label>;
        if (kind === "fixed") return <div key={key}><p className="field-label">{label} <span className="font-normal text-ink-subtle">{t("not editable here")}</span></p><pre className="overflow-x-auto rounded-lg bg-surface p-2 text-xs">{JSON.stringify(value, null, 2)}</pre></div>;
        if (kind === "list") return <div key={key}><label htmlFor={id} className="field-label">{label} <span className="font-normal text-ink-subtle">{t("comma separated")}</span></label><input id={id} className="field-input" value={text} onChange={(e) => onChange({ ...draft, [key]: e.target.value })} /></div>;
        if (kind === "number") return <div key={key}><label htmlFor={id} className="field-label">{label}</label><input id={id} inputMode="decimal" className="field-input" value={text} onChange={(e) => onChange({ ...draft, [key]: e.target.value })} /></div>;
        return <div key={key}><label htmlFor={id} className="field-label">{label}</label><textarea id={id} rows={text.length > 80 ? 4 : 2} className="field-input" value={text} onChange={(e) => onChange({ ...draft, [key]: e.target.value })} /></div>;
      })}
    </div>
  );
}

export function ProposalCard({ proposal, readonly }: { proposal: Proposal; readonly: boolean }) {
  const { accept, reject } = useReviewActions(proposal.project_id);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => draftFrom(proposal.payload));
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const pending = proposal.status === "pending";
  const busy = accept.isPending || reject.isPending;
  const error = (accept.error ?? reject.error) as Error | null;
  const shownError = error?.message ?? proposal.error;

  return (
    <li className="rounded-xl border border-line bg-surface p-5 shadow-card">
      <article aria-label={`${proposal.human_id} ${proposalLabels[proposal.proposal_type]}`}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="font-bold tracking-wide text-forest">{proposal.human_id}</span>
          <span className="rounded-full bg-sage-pale px-2.5 py-0.5 font-semibold text-forest">{proposalLabels[proposal.proposal_type]}</span>
          <span className="inline-flex items-center gap-1 text-ink-muted"><Bot size={13} aria-hidden="true" />{proposal.agent}</span>
          <span className="text-ink-subtle">{formatDate(proposal.created_at)}</span>
          {!pending && <Badge tone={proposal.status === "accepted" ? "success" : "neutral"}>{proposal.status === "accepted" ? t("Accepted") : t("Dismissed")}</Badge>}
        </div>
        {proposal.target_label && <h3 className="mt-2 flex items-center gap-2 text-sm font-semibold text-ink">{proposal.target_label}{proposal.target_locked && <span className="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2 py-0.5 text-xs font-semibold text-warning-ink"><Lock size={11} aria-hidden="true" />{t("Locked")}</span>}</h3>}
        {proposal.reason && <p className="mt-2 text-sm leading-6 text-ink-muted"><strong className="text-ink">{t("Why:")}</strong> {proposal.reason}</p>}
        <ul className="mt-3 space-y-1 rounded-xl bg-neutral-soft px-4 py-3 text-sm text-ink" aria-label={t("What will change")}>{proposal.changes.map((line) => <li key={line}>{line}</li>)}</ul>
        {pending && proposal.target_locked && <p className="mt-2 text-xs text-warning-ink">{t("This memory is locked, so an agent could not change it. Accepting applies the change because you reviewed it. The memory stays locked.")}</p>}
        {proposal.applied_payload && <p className="mt-2 text-xs text-ink-subtle">{t("You edited this before accepting it.")}</p>}
        {proposal.review_note && <p className="mt-2 text-xs text-ink-subtle">{t("Your note:")} {proposal.review_note}</p>}
        {shownError && pending && <p role="alert" className="mt-3 rounded-xl bg-danger-soft px-3 py-2 text-sm text-danger-ink">{shownError}</p>}

        {pending && !readonly && (
          <>
            {editing && <PayloadEditor original={proposal.payload} draft={draft} onChange={setDraft} />}
            {rejecting && <div className="mt-3"><label htmlFor={`note-${proposal.id}`} className="field-label">{t("Note for the record")} <span className="font-normal text-ink-subtle">{t("Optional")}</span></label><input id={`note-${proposal.id}`} className="field-input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></div>}
            <div className="mt-4 flex flex-wrap gap-2">
              {!rejecting && (editing
                ? <><Button variant="primary" disabled={busy} onClick={() => accept.mutate({ id: proposal.id, payload: payloadFrom(proposal.payload, draft) })}>{t("Accept with my edits")}</Button><Button variant="quiet" onClick={() => { setEditing(false); setDraft(draftFrom(proposal.payload)); }}>{t("Cancel edit")}</Button></>
                : <><Button variant="primary" disabled={busy} onClick={() => accept.mutate({ id: proposal.id })}>{t("Accept")}</Button><Button disabled={busy} onClick={() => setEditing(true)}>{t("Edit and accept")}</Button></>)}
              {!editing && (rejecting
                ? <><Button variant="danger" disabled={busy} onClick={() => reject.mutate({ id: proposal.id, note: note.trim() || undefined })}>{t("Dismiss suggestion")}</Button><Button variant="quiet" onClick={() => setRejecting(false)}>{t("Cancel")}</Button></>
                : <Button variant="quiet" disabled={busy} onClick={() => setRejecting(true)}>{t("Dismiss")}</Button>)}
            </div>
          </>
        )}
      </article>
    </li>
  );
}
