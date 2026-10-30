import { INTEGRATIONS_CHECKED, snippetsFor, type Agent } from "../../content/integrations";
import { t } from "../../lib/i18n";
import { CodeBlock } from "./Markdown";

/** Setup commands for one agent. One connection covers every project. */
export function IntegrationSnippet({ agent }: { agent: Agent }) {
  const { setup, verify, sources } = snippetsFor(agent);
  const name = agent === "claude" ? "Claude Code" : "Codex";
  return (
    <section aria-label={t("Setup commands for {name}", { name })} className="my-4">
      {[...setup, ...verify].map((s) => <CodeBlock key={s.label} code={s.text} label={t(s.label)} />)}
      <p className="text-xs text-ink-subtle">
        {t("Commands follow the official {name} documentation as checked on {date}: {sources}.", { name, date: INTEGRATIONS_CHECKED, sources: sources.map((s) => `${t(s.label)} (${s.url})`).join(", ") })}{" "}
        {agent === "claude" ? t("The Claude Code connection has been confirmed by hand.") : t("This connection has not yet been confirmed by hand with the real Codex app.")}{" "}
        {t("Setup syntax can change; if a command is rejected, check that page.")}
      </p>
    </section>
  );
}
