import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { agentsApi, type AgentSettings } from "../api/agents";
import { t } from "../lib/i18n";
import { queryKeys } from "../lib/queries";
import { Button } from "./ui";

type Commands = Pick<AgentSettings, "codex_command" | "claude_command">;

/** Default agent for "Work on task", the second-opinion switch, and, while it is on, how each agent is started. */
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
        <legend className="field-label">{t("Default agent")}</legend>
        <p className="text-xs text-ink-subtle">{t("\"Work on task\" opens this agent with a prompt for the task typed in, ready for you to send.")}</p>
        <div role="group" aria-label={t("Default agent")} className="segmented mt-2">
          {(["claude", "codex"] as const).map((a) => <button key={a} type="button" aria-pressed={s.default_agent === a} onClick={() => save.mutate({ default_agent: a })} className={`filter-tab ${s.default_agent === a ? "filter-tab-active" : ""}`}>{a === "claude" ? "Claude" : "Codex"}</button>)}
        </div>
      </fieldset>

      <div className="space-y-4">
        <label className="flex items-start gap-3 text-sm text-ink">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-primary" checked={Boolean(s.second_opinion_enabled)} onChange={(e) => save.mutate({ second_opinion_enabled: e.target.checked })} />
          <span><strong>{t("Allow second opinions")}</strong><br /><span className="text-ink-muted">{t("Ask in a session (\"get a second opinion from Codex\") and the agent asks the other one, read-only, then shows you both views. It uses the other agent's usage too.")}</span></span>
        </label>
        {s.second_opinion_enabled && (
          <form onSubmit={(e) => { e.preventDefault(); save.mutate(commands, { onSuccess: () => setEdits({}) }); }} className="space-y-3 pl-7">
            <p className="text-xs text-ink-subtle">{t("The command each agent is started with. Change it only if yours is installed under another name.")}</p>
            <div><label htmlFor="codex-command" className="field-label">{t("Command for Codex")}</label><input id="codex-command" className="field-input font-mono" value={commands.codex_command} onChange={(e) => edit("codex_command", e.target.value)} maxLength={500} required /></div>
            <div><label htmlFor="claude-command" className="field-label">{t("Command for Claude Code")}</label><input id="claude-command" className="field-input font-mono" value={commands.claude_command} onChange={(e) => edit("claude_command", e.target.value)} maxLength={500} required /></div>
            <Button type="submit" disabled={!dirty || save.isPending}>{save.isPending ? t("Saving…") : t("Save commands")}</Button>
          </form>
        )}
      </div>
      {save.isError && <p role="alert" className="text-sm text-danger-ink">{save.error.message}</p>}
    </div>
  );
}
