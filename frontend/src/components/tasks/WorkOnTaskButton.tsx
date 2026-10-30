import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { useState } from "react";
import { agentsApi, type AgentName, type WorkPrompt } from "../../api/agents";
import { queryKeys } from "../../lib/queries";
import { Button } from "../ui";

const NAME: Record<AgentName, string> = { claude: "Claude", codex: "Codex" };

/** Opens the default agent's desktop app with a prompt for this task typed in but not sent. */
export function WorkOnTaskButton({ projectId, task, compact = false, variant = "primary" }: { projectId: string; task: string; compact?: boolean; variant?: "primary" | "secondary" }) {
  const settings = useQuery({ queryKey: queryKeys.agentSettings, queryFn: ({ signal }) => agentsApi.settings(signal), retry: false });
  const preferred: AgentName = settings.data?.default_agent === "codex" ? "codex" : "claude";
  const other: AgentName = preferred === "claude" ? "codex" : "claude";
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ prompt: WorkPrompt; opened: boolean; copied: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);

  async function run(agent: AgentName) {
    setBusy(true); setError(null);
    try {
      const prompt = await agentsApi.workPrompt(projectId, task, agent);
      let copied = false;
      try { await navigator.clipboard.writeText(prompt.prompt); copied = true; } catch { /* shown below instead */ }
      const opener = window.projectBrainDesktop?.openAgent;
      const opened = opener ? await opener(prompt.url) : false;
      setResult({ prompt, opened, copied });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The prompt could not be prepared.");
    } finally { setBusy(false); }
  }

  const name = result ? NAME[result.prompt.agent] : NAME[preferred];
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant={variant} onClick={() => void run(preferred)} disabled={busy} title={`Opens ${NAME[preferred]} with a prompt for this task typed in, ready to send`}><Bot size={16} aria-hidden="true" />{busy ? "Preparing…" : `Work on task in ${NAME[preferred]}`}</Button>
        {!compact && <button type="button" onClick={() => void run(other)} disabled={busy} className="text-sm font-semibold text-forest hover:underline disabled:opacity-50">or in {NAME[other]}</button>}
      </div>
      {result && (
        <div role="status" className="mt-2 text-sm text-ink-muted">
          {result.opened ? `${name} opened with the prompt typed in. Read it, then press Enter to start.` : `${name} could not be opened from here.`}
          {result.copied ? " The prompt is also on your clipboard." : ""}
          {result.prompt.agent === "claude" && result.opened && result.prompt.folder ? ` Choose the folder ${result.prompt.folder} in Claude before sending.` : ""}
          {" "}<button type="button" className="font-semibold text-forest hover:underline" onClick={() => setShowPrompt((v) => !v)}>{showPrompt ? "Hide prompt" : "Show prompt"}</button>
          {showPrompt && <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl bg-neutral-soft p-3 text-xs text-ink">{result.prompt.prompt}</pre>}
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-danger-ink">{error}</p>}
    </div>
  );
}
