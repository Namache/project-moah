import { INTEGRATIONS_CHECKED, snippetsFor, type Agent } from "../../content/integrations";
import { CodeBlock } from "./Markdown";

/** Setup commands for one agent. One connection covers every project. */
export function IntegrationSnippet({ agent }: { agent: Agent }) {
  const { setup, verify, sources } = snippetsFor(agent);
  const name = agent === "claude" ? "Claude Code" : "Codex";
  return (
    <section aria-label={`Setup commands for ${name}`} className="my-4">
      {setup.map((s) => <CodeBlock key={s.label} code={s.text} label={s.label} />)}
      {verify.map((s) => <CodeBlock key={s.label} code={s.text} label={s.label} />)}
      <p className="text-xs text-ink-subtle">Commands follow the official {name} documentation as checked on {INTEGRATIONS_CHECKED}: {sources.map((s) => `${s.label} (${s.url})`).join(", ")}. {agent === "claude" ? "The Claude Code connection has been confirmed by hand." : "This connection has not yet been confirmed by hand with the real Codex app."} Setup syntax can change; if a command is rejected, check that page.</p>
    </section>
  );
}
