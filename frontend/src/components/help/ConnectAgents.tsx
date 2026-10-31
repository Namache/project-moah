import { useState } from "react";
import { systemApi, type AgentConnection } from "../../api/system";
import { t } from "../../lib/i18n";
import { Button } from "../ui";

const NAMES = { claude: "Claude Code", codex: "Codex" };

function outcome({ agent, status, detail }: AgentConnection): string {
  const name = NAMES[agent];
  if (status === "connected") return t("{name} is connected. Restart it to start using Project Moah.", { name });
  if (status === "not_found") return t("{name} isn't installed on this computer, so it was skipped.", { name });
  return t("{name} could not be connected: {detail}", { name, detail });
}

/** One click instead of the commands: sets up every agent found on this computer. */
export function ConnectAgents() {
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<AgentConnection[] | null>(null);
  const [error, setError] = useState("");
  async function connect() {
    setBusy(true);
    setError("");
    try {
      setResults((await systemApi.connectAgents()).results);
    } catch {
      setResults(null);
      setError(t("Project Moah couldn't connect your agents. Please try again."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="my-4">
      <Button variant="primary" onClick={() => void connect()} disabled={busy}>{busy ? t("Connecting…") : t("Connect Claude Code and Codex")}</Button>
      <p className="mt-2 text-sm text-ink-muted">{t("Your other agent settings stay as they are, and a backup is saved next to each file that changes.")}</p>
      {results && <ul role="status" className="mt-2 text-sm">{results.map((result) => <li key={result.agent}>{outcome(result)}</li>)}</ul>}
      {error && <p role="alert" className="mt-2 text-sm text-danger-ink">{error}</p>}
    </div>
  );
}
