import { useMemo, useState } from "react";
import { Check, Plus, X } from "lucide-react";
import { Button } from "../ui";
import { useGraphActions, useNodeLinks, useRelationshipTypes } from "../../hooks/useGraph";
import { relationshipLabel, type GraphNode, type TypedLink } from "../../types/graph";
import { labels, msg, t } from "../../lib/i18n";

const strengths = [
  labels({ value: 0.3, label: msg("Useful") }, ["label"]),
  labels({ value: 0.5, label: msg("Relevant") }, ["label"]),
  labels({ value: 0.7, label: msg("Strong") }, ["label"]),
  labels({ value: 0.9, label: msg("Critical") }, ["label"]),
];

/** Hover text: strength, what it learned per kind of work, and why the link exists. */
function linkDetail(link: TypedLink) {
  const lines = [t("Strength {strength}, confidence {confidence}", { strength: link.strength.toFixed(2), confidence: link.confidence.toFixed(2) })];
  const learned = Object.entries(link.contextual_weights ?? {}).map(([work, weight]) => `${work} ${Math.round(weight * 100)}%`);
  if (learned.length) lines.push(t("Learned: {weights}", { weights: learned.join(", ") }));
  if (link.success_count || link.failure_count) lines.push(t("Helped {helped}, missed {missed}", { helped: link.success_count, missed: link.failure_count }));
  for (const reason of (link.provenance ?? []).slice(-4)) lines.push(`${reason.source}: ${reason.detail}`);
  return lines.join("\n");
}

/**
 * Typed links of one record (the Link System): how it relates to other records, read from this record.
 * Built-in links come from task relationships, memory links and file links; they are changed where they were made.
 */
export function TypedLinks({ projectId, node, readonly, onOpen }: { projectId: string; node: string; readonly: boolean; onOpen?: (node: GraphNode) => void }) {
  const links = useNodeLinks(projectId, node);
  const types = useRelationshipTypes(projectId);
  const actions = useGraphActions(projectId);
  const [relationship, setRelationship] = useState("relates_to");
  const [target, setTarget] = useState("");
  const [strength, setStrength] = useState(0.5);
  const [error, setError] = useState<string | null>(null);
  const groups = useMemo(() => {
    const out = new Map<string, string[]>();
    for (const type of types.data ?? []) out.set(type.group, [...(out.get(type.group) ?? []), type.name]);
    return [...out.entries()];
  }, [types.data]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : t("The link could not be changed.")); }
  }
  function add() {
    const input = { source: node, relationship, target: target.trim(), strength };
    setTarget("");
    void run(() => actions.link.mutateAsync(input));
  }

  const items = (links.data?.links ?? []).filter((link) => link.status !== "rejected");
  return (
    <div>
      {links.isError && <p role="alert" className="text-xs text-danger-ink">{t("Links could not be loaded.")}</p>}
      {items.length ? (
        <ul className="space-y-1.5">
          {items.map((link) => (
            <li key={`${link.stored_relationship}-${link.direction}-${link.node.kind}-${link.node.id}`} className={`flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${link.status === "candidate" ? "border-dashed border-line text-ink-muted" : "border-line"}`}>
              <button type="button" disabled={!onOpen} onClick={() => onOpen?.(link.node)} className="min-w-0 truncate text-left enabled:hover:text-forest focus-visible:outline-2 focus-visible:outline-forest">
                <span className="text-ink-muted">{relationshipLabel(link.relationship)}</span>{" "}
                <strong className="text-forest">{link.node.label}</strong>{link.node.title !== link.node.label && <> {link.node.title}</>}
              </button>
              <span className="flex shrink-0 items-center gap-2 text-xs text-ink-subtle">
                {link.status === "candidate" ? <span title={linkDetail(link)}>{t("guess")}</span>
                  : <span title={linkDetail(link)}>{link.status === "weak" ? t("weak {share}", { share: `${Math.round(link.strength * 100)}%` }) : `${Math.round(link.strength * 100)}%`}</span>}
                {link.status === "candidate" && link.id && !readonly && <button type="button" aria-label={t("Confirm link to {name}", { name: link.node.label })} onClick={() => void run(() => actions.confirm.mutateAsync(link.id!))} className="rounded-md p-1 text-forest hover:bg-sage-pale"><Check size={15} /></button>}
                {link.id === null ? <span title={t("Made in its own place: task relationships, connected memories, or file links")}>{t("built in")}</span>
                  : !readonly && <button type="button" aria-label={link.status === "candidate" ? t("Reject link to {name}", { name: link.node.label }) : t("Remove link to {name}", { name: link.node.label })} onClick={() => void run(() => (link.status === "candidate" ? actions.reject : actions.unlink).mutateAsync(link.id!))} className="rounded-md p-1 text-ink-muted hover:bg-neutral-soft"><X size={15} /></button>}
              </span>
            </li>
          ))}
        </ul>
      ) : !links.isPending && <p className="text-xs text-ink-subtle">{t("No links yet.")}</p>}
      {!readonly && (
        <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_minmax(0,7rem)_auto]">
          <label className="sr-only" htmlFor={`rel-${node}`}>{t("Relationship")}</label>
          <select id={`rel-${node}`} className="field-input" value={relationship} onChange={(event) => setRelationship(event.target.value)}>
            {groups.map(([group, names]) => <optgroup key={group} label={group}>{names.map((name) => <option key={name} value={name}>{relationshipLabel(name)}</option>)}</optgroup>)}
          </select>
          <label className="sr-only" htmlFor={`target-${node}`}>{t("Linked record")}</label>
          <input id={`target-${node}`} className="field-input" value={target} maxLength={1100} onChange={(event) => setTarget(event.target.value)} placeholder={t("DEC-003, PB-12, file:src/save.gd, shelf:Inventory")} />
          <label className="sr-only" htmlFor={`strength-${node}`}>{t("Strength")}</label>
          <select id={`strength-${node}`} className="field-input" value={strength} onChange={(event) => setStrength(Number(event.target.value))}>
            {strengths.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <Button onClick={add} disabled={!target.trim() || actions.link.isPending}><Plus size={16} />{t("Link")}</Button>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-danger-ink">{error}</p>}
    </div>
  );
}
