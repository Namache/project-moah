import { useState } from "react";
import { Check, ChevronDown, Search, Sparkles, X } from "lucide-react";
import { Button, HelpTip, collapsibleHeader, collapsibleOpen, collapsiblePill } from "../ui";
import { useGraphActions, useLinkReview } from "../../hooks/useGraph";
import { relationshipLabel } from "../../types/graph";
import { t } from "../../lib/i18n";

/** What the Link System is unsure about: links it guessed, and memory nothing links to. */
const howMany = (value: string[] | number | undefined) => (Array.isArray(value) ? value.length : value ?? 0);

export function LinkReview({ projectId, readonly, defaultOpen = false }: { projectId: string; readonly: boolean; defaultOpen?: boolean }) {
  const { candidates, orphans } = useLinkReview(projectId);
  const actions = useGraphActions(projectId);
  const [open, setOpen] = useState(defaultOpen);
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<string | null>(null);
  const guesses = candidates.data ?? [];
  const lonely = orphans.data ?? [];
  const count = guesses.length + lonely.length;

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : t("The link could not be changed.")); }
  }
  async function discoverAll() {
    await run(async () => {
      const result = await actions.discover.mutateAsync(undefined);
      setFound(t("Checked {checked} tasks and memories: {mentions} links from names in the text, {guesses} new guesses.", { checked: result.records ?? 0, mentions: howMany(result.mentions), guesses: howMany(result.candidates) }));
    });
  }

  return (
    <section aria-label={t("Guessed links")} className={open ? collapsibleOpen : undefined}>
      <button type="button" aria-expanded={open} aria-controls="link-review-body" onClick={() => setOpen((value) => !value)} className={open ? collapsibleHeader : collapsiblePill}>
        <Sparkles size={15} className="text-forest" aria-hidden="true" />{t("Guessed links")}
        <span className="text-xs font-normal tabular-nums text-ink-subtle">{candidates.isPending || orphans.isPending ? "" : `${count}`}</span>
        <ChevronDown size={14} className={`ml-auto transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && <div id="link-review-body" className="mt-3">
        <p className="flex items-center gap-1.5 text-xs leading-5 text-ink-muted">{t("Guessed links are never followed until someone confirms them. Rejected guesses are remembered and not suggested again.")} <HelpTip label={t("link review")}>{t("Guesses come from records whose titles share their important words. Records named in the text (DEC-004, a file path) are linked straight away. A guess that helps an agent's work is confirmed automatically.")}</HelpTip></p>

        <h3 className="mt-4 text-xs font-semibold text-ink-muted">{t("Guessed links")}</h3>
        {guesses.length ? <ul className="mt-1.5 space-y-1.5">
          {guesses.map((c) => (
            <li key={c.link_id} className="flex items-center justify-between gap-2 rounded-lg border border-dashed border-line px-3 py-2 text-sm">
              <span className="min-w-0" title={c.why}>
                <strong className="text-forest">{c.source.label}</strong> <span className="text-ink-muted">{relationshipLabel(c.relationship)}</span> <strong className="text-forest">{c.target.label}</strong>
                <span className="block truncate text-xs text-ink-subtle">{c.source.title} / {c.target.title}</span>
              </span>
              <span className="flex shrink-0 items-center gap-1 text-xs text-ink-subtle">
                <span title={c.why}>{t("{share} sure", { share: `${Math.round(c.confidence * 100)}%` })}</span>
                {!readonly && <>
                  <button type="button" aria-label={t("Confirm link {from} to {to}", { from: c.source.label, to: c.target.label })} onClick={() => void run(() => actions.confirm.mutateAsync(c.link_id))} className="rounded-md p-1 text-forest hover:bg-sage-pale"><Check size={15} /></button>
                  <button type="button" aria-label={t("Reject link {from} to {to}", { from: c.source.label, to: c.target.label })} onClick={() => void run(() => actions.reject.mutateAsync(c.link_id))} className="rounded-md p-1 text-ink-muted hover:bg-neutral-soft"><X size={15} /></button>
                </>}
              </span>
            </li>
          ))}
        </ul> : <p className="mt-1 text-xs text-ink-subtle">{candidates.isPending ? t("Loading…") : t("No guesses waiting.")}</p>}

        <h3 className="mt-4 text-xs font-semibold text-ink-muted">{t("Memory nothing links to")}</h3>
        {lonely.length ? <ul className="mt-1.5 flex flex-wrap gap-1.5">
          {lonely.map((o) => <li key={o.node} title={o.title} className="max-w-full truncate rounded-full border border-line px-2.5 py-0.5 text-xs"><strong className="text-forest">{o.id}</strong> {o.title}</li>)}
        </ul> : <p className="mt-1 text-xs text-ink-subtle">{orphans.isPending ? t("Loading…") : t("Every memory is linked or on a shelf.")}</p>}
        {lonely.length > 0 && <p className="mt-1.5 text-xs text-ink-subtle">{t("Only a word search finds these. Link them, put them on a shelf, or archive them if they no longer matter.")}</p>}

        {!readonly && <div className="mt-4"><Button onClick={() => void discoverAll()} disabled={actions.discover.isPending}><Search size={16} />{actions.discover.isPending ? t("Looking…") : t("Look for links")}</Button></div>}
        {found && <p role="status" className="mt-2 text-xs text-ink-muted">{found}</p>}
        {error && <p role="alert" className="mt-2 text-xs text-danger-ink">{error}</p>}
      </div>}
    </section>
  );
}
