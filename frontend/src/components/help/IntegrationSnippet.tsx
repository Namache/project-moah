import { useAgentLaunch, useInstall } from "../../lib/install";
import { INTEGRATIONS_CHECKED, snippetsFor, type Agent } from "../../content/integrations";
import { t } from "../../lib/i18n";
import { ConnectAgents, ConnectByCommand } from "./ConnectAgents";
import { CodeBlock } from "./Markdown";

/** Setup commands for one agent, for the way this copy of the app was installed. One connection covers every project. */
export function IntegrationSnippet({ agent }: { agent: Agent }) {
  const launch = useAgentLaunch();
  const install = useInstall();
  const name = agent === "claude" ? "Claude Code" : "Codex";
  // The Flatpak commands are the fallback only on the Flatpak itself; elsewhere wait for the real ones.
  if (!launch && install !== "flatpak") return <p role="status" className="my-4 text-sm text-ink-muted">{t("Loading…")}</p>;
  const { setup, verify, sources } = snippetsFor(agent, launch);
  const commands = [...setup, ...verify].map((s) => <CodeBlock key={s.label} code={s.text} label={t(s.label)} />);
  const oneClick = launch && launch.install !== "flatpak" && launch.install !== "source";
  const oneCommand = !oneClick && install === "flatpak" && launch?.install !== "source";
  return (
    <section aria-label={t("Setup commands for {name}", { name })} className="my-4">
      {oneClick || oneCommand ? (
        <>
          {oneClick ? <ConnectAgents /> : <ConnectByCommand />}
          <details className="my-3">
            <summary className="cursor-pointer text-sm text-ink-muted">{t("Set it up by hand instead")}</summary>
            {commands}
          </details>
        </>
      ) : commands}
      <p className="text-xs text-ink-subtle">
        {t("Commands follow the official {name} documentation as checked on {date}: {sources}.", { name, date: INTEGRATIONS_CHECKED, sources: sources.map((s) => `${t(s.label)} (${s.url})`).join(", ") })}{" "}
        {agent === "claude" ? t("The Claude Code connection has been confirmed by hand.") : t("This connection has not yet been confirmed by hand with the real Codex app.")}{" "}
        {t("Setup syntax can change; if a command is rejected, check that page.")}
      </p>
    </section>
  );
}
