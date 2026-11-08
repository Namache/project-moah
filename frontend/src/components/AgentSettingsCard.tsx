import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi, type AgentSettings } from "../api/agents";
import { t } from "../lib/i18n";
import { queryKeys } from "../lib/queries";
import { Button, HelpTip } from "./ui";
import { ChevronRight } from "lucide-react";

/** A checkbox with its name, and the explanation under a "?" beside it (outside the label, so opening it never ticks the box). */
export function Switch({ checked, onChange, label, help }: { checked: boolean; onChange: (on: boolean) => void; label: string; help: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink">
      <label className="flex items-center gap-3"><input type="checkbox" className="h-4 w-4 accent-primary" checked={checked} onChange={(e) => onChange(e.target.checked)} /><strong>{label}</strong></label>
      <HelpTip label={label}>{help}</HelpTip>
    </div>
  );
}

type Commands = Pick<AgentSettings, "codex_command" | "claude_command">;

/** Default agent for "Work on task", the second-opinion switch (and, folded under it, how each agent is started), the daily update check, and whether packs explore. Explanations sit under "?". */
export function AgentSettingsCard() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.agentSettings, queryFn: ({ signal }) => agentsApi.settings(signal), retry: false });
  const save = useMutation({ mutationFn: (changes: Partial<AgentSettings>) => agentsApi.update(changes), onSuccess: (data) => client.setQueryData(queryKeys.agentSettings, data) });
  const s = query.data;
  // Unsaved command edits live apart from the saved settings, so saving another setting never discards them.
  const [edits, setEdits] = useState<Partial<Commands>>({});
  if (query.isError) return <p role="alert" className="text-sm text-danger-ink">{t("Agent settings are unavailable: {reason}", { reason: query.error.message })}</p>;
  if (!s) return <p role="status" className="text-sm text-ink-muted">{t("Loading agent settings…")}</p>;
  const saved: Commands = { codex_command: s.codex_command ?? "", claude_command: s.claude_command ?? "" };
  const commands: Commands = { ...saved, ...edits };
  const dirty = commands.codex_command !== saved.codex_command || commands.claude_command !== saved.claude_command;
  const edit = (key: keyof Commands, value: string) => setEdits((current) => ({ ...current, [key]: value }));

  return (
    <div className="space-y-6">
      <fieldset>
        <legend className="field-label flex items-center gap-2">{t("Default agent")} <HelpTip label={t("default agent")}>{t("\"Work on task\" opens this agent with a prompt for the task typed in, ready for you to send.")}</HelpTip></legend>
        <div role="group" aria-label={t("Default agent")} className="segmented mt-2">
          {(["claude", "codex"] as const).map((a) => <button key={a} type="button" aria-pressed={s.default_agent === a} onClick={() => save.mutate({ default_agent: a })} className={`filter-tab ${s.default_agent === a ? "filter-tab-active" : ""}`}>{a === "claude" ? "Claude" : "Codex"}</button>)}
        </div>
      </fieldset>

      <div className="space-y-4">
        <Switch checked={Boolean(s.second_opinion_enabled)} onChange={(on) => save.mutate({ second_opinion_enabled: on })} label={t("Allow second opinions")} help={t("Ask in a session (\"get a second opinion from Codex\") and the agent asks the other one, read-only, then shows you both views. It uses the other agent's usage too.")} />
        {s.second_opinion_enabled && (
          <details className="group pl-7" open={dirty || undefined}>
            <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded text-sm text-ink-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-forest">
              <ChevronRight size={14} className="transition-transform group-open:rotate-90" aria-hidden="true" />{t("Agent commands")}
            </summary>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(commands, { onSuccess: () => setEdits({}) }); }} className="mt-3 space-y-3">
              <p className="flex items-center gap-2 text-xs text-ink-subtle">{t("Only needed when an agent is installed under another name.")} <HelpTip label={t("agent commands")}>{t("The command each agent is started with. Change it only if yours is installed under another name.")}</HelpTip></p>
              <div><label htmlFor="codex-command" className="field-label">{t("Command for Codex")}</label><input id="codex-command" className="field-input font-mono" value={commands.codex_command} onChange={(e) => edit("codex_command", e.target.value)} maxLength={500} required /></div>
              <div><label htmlFor="claude-command" className="field-label">{t("Command for Claude Code")}</label><input id="claude-command" className="field-input font-mono" value={commands.claude_command} onChange={(e) => edit("claude_command", e.target.value)} maxLength={500} required /></div>
              <Button type="submit" disabled={!dirty || save.isPending}>{save.isPending ? t("Saving…") : t("Save commands")}</Button>
            </form>
          </details>
        )}
      </div>
      <Switch checked={s.update_check_enabled !== false} onChange={(on) => save.mutate({ update_check_enabled: on })} label={t("Automatically check for updates")} help={t("Once a day, at the start of a session, your agent looks up the newest Project Moah release on GitHub and asks you before updating. Project Moah itself never goes online.")} />
      <Switch checked={Boolean(s.explore_packs)} onChange={(on) => save.mutate({ explore_packs: on })} label={t("Let packs explore")} help={t("Context packs sometimes include a record reached over a link nobody has rated yet, so Project Moah learns whether it helps. Packs then differ a little from one request to the next. Off: the same request always gets the same pack.")} />
      {save.isError && <p role="alert" className="text-sm text-danger-ink">{save.error.message}</p>}
    </div>
  );
}
