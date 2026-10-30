import { Check, ClipboardCopy } from "lucide-react";
import { useState } from "react";
import { handoffApi, type Handoff } from "../../api/handoff";
import { Button } from "../ui";
import { useTimeout } from "../../hooks/useTimeout";

/** Builds the handoff on click, copies it, and shows it so a person can read or select it. */
export function HandoffButton({ projectId, task, variant = "secondary" }: { projectId: string; task?: string | null; variant?: "secondary" | "primary" | "quiet" }) {
  const [state, setState] = useState<"idle" | "loading" | "copied" | "error">("idle");
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const [message, setMessage] = useState("");
  const later = useTimeout();

  async function copy() {
    setState("loading");
    setMessage("");
    try {
      const built = await handoffApi.get(projectId, task);
      setHandoff(built);
      try {
        await navigator.clipboard.writeText(built.text);
        setState("copied");
        later(() => setState((s) => (s === "copied" ? "idle" : s)), 2500);
      } catch {
        setState("idle");
        setMessage("Copying was blocked, so the handoff is shown below. Select it and copy.");
      }
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "The handoff could not be built.");
    }
  }

  return (
    <div>
      <Button variant={variant} onClick={() => void copy()} disabled={state === "loading"}>
        {state === "copied" ? <Check size={16} aria-hidden="true" /> : <ClipboardCopy size={16} aria-hidden="true" />}
        {state === "loading" ? "Building…" : state === "copied" ? "Handoff copied" : "Copy handoff"}
      </Button>
      <span role="status" className="sr-only">{state === "copied" ? "Handoff copied to the clipboard" : ""}</span>
      {message && <p role="alert" className="mt-2 text-sm text-warning-ink">{message}</p>}
      {handoff && (
        <details className="mt-3" open={Boolean(message)}>
          <summary className="cursor-pointer text-sm font-medium text-forest">Preview handoff, about {handoff.estimated_tokens.toLocaleString()} tokens</summary>
          <pre aria-label="Handoff preview" className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-neutral-soft p-4 text-xs leading-6 text-ink">{handoff.text}</pre>
        </details>
      )}
    </div>
  );
}
