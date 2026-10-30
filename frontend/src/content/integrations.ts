/**
 * Everything vendor-specific about connecting an agent lives in this one file.
 * If Codex or Claude Code change how MCP servers or hooks are configured, update only this.
 *
 * Each agent connects once, for every project: the project is found from the folder the agent
 * works in, and the Global rules apply everywhere.
 *
 * Checked against the official documentation on 2026-10-11:
 *   Claude Code: https://code.claude.com/docs/en/mcp  (`claude mcp add --scope user ... -- command args`)
 *                https://code.claude.com/docs/en/hooks (SessionStart hook output is added as context)
 *   Codex:       https://developers.openai.com/codex/mcp  (`codex mcp add ... -- command args`, `~/.codex/config.toml`)
 * Claude Code's connection was confirmed by hand on 2026-10-11; Codex's has not been yet.
 */
import { msg } from "../lib/i18n";

const APP_ID = "io.github.projectbrain.ProjectBrain";
export const INTEGRATIONS_CHECKED = "2026-10-11";
export type Agent = "claude" | "codex";

/** The command an agent runs to start Project Moah's local MCP server. */
function serverCommand(agent: Agent): string[] {
  return ["flatpak", "run", "--command=project-moah-mcp", APP_ID, "--agent", agent];
}

/** Prints the session brief (global rules, project rules, focus) for the folder Claude Code opened. */
const BRIEF_COMMAND = `flatpak run --command=project-moah-mcp ${APP_ID} --brief --cwd "$CLAUDE_PROJECT_DIR"`;

const shell = (parts: string[]) => parts.map((p) => (/^[\w./:=@%+-]+$/.test(p) ? p : `'${p.replace(/'/g, "'\\''")}'`)).join(" ");

export interface Snippet { label: string; language: string; text: string }

export function snippetsFor(agent: Agent): { setup: Snippet[]; verify: Snippet[]; sources: { label: string; url: string }[] } {
  const command = serverCommand(agent);
  if (agent === "claude") {
    return {
      setup: [
        { label: msg("1. Connect Claude Code once, for every project"), language: "bash", text: `claude mcp add --transport stdio --scope user project-moah -- ${shell(command)}` },
        { label: msg("2. Load your rules at the start of every session: add this to ~/.claude/settings.json"), language: "json", text: JSON.stringify({ hooks: { SessionStart: [{ matcher: "startup|clear|compact", hooks: [{ type: "command", command: BRIEF_COMMAND, timeout: 20 }] }] } }, null, 2) },
      ],
      verify: [{ label: msg("Check the connection"), language: "bash", text: "claude mcp list" }],
      sources: [{ label: msg("Claude Code MCP documentation"), url: "https://code.claude.com/docs/en/mcp" }, { label: msg("Claude Code hooks"), url: "https://code.claude.com/docs/en/hooks" }],
    };
  }
  const args = command.slice(1).map((a) => JSON.stringify(a)).join(", ");
  return {
    setup: [
      { label: msg("1. Connect Codex once, for every project"), language: "bash", text: `codex mcp add project-moah -- ${shell(command)}` },
      { label: msg("Or add this to ~/.codex/config.toml"), language: "toml", text: `[mcp_servers.project-moah]\ncommand = ${JSON.stringify(command[0])}\nargs = [${args}]\nstartup_timeout_sec = 20` },
      { label: msg("2. Tell Codex to start every session from Project Moah: add this to ~/.codex/AGENTS.md"), language: "markdown", text: "Project Moah is the source of truth for my rules and memory. At the start of every session, call\nthe project-moah tool brain_brief with your working folder as cwd and follow what it returns." },
    ],
    verify: [{ label: msg("Check the connection"), language: "bash", text: "codex mcp list" }],
    sources: [{ label: msg("Codex MCP documentation"), url: "https://developers.openai.com/codex/mcp" }],
  };
}

const quote = (value: string) => (/^[\w./:=@%+~-]+$/.test(value) ? value : `'${value.replace(/'/g, "'\\''")}'`);

/** Commands to share one repository folder with the sandboxed app, read-only, and to undo it. */
export function shareFolderCommands(folder: string): { grant: string; undo: string } {
  return {
    grant: `flatpak override --user --filesystem=${quote(`${folder}:ro`)} ${APP_ID}`,
    undo: `flatpak override --user --nofilesystem=${quote(folder)} ${APP_ID}`,
  };
}
