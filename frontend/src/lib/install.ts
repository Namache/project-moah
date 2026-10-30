import { useQuery } from "@tanstack/react-query";
import { systemApi, type AgentLaunch } from "../api/system";

/** How this copy of Project Moah was installed. Help and setup commands show only what fits it. */
export type Install = "flatpak" | "deb" | "linux" | "windows" | "mac";
export const INSTALLS: Install[] = ["flatpak", "deb", "linux", "windows", "mac"];

const agentCommand = { queryKey: ["system", "agent-command"], queryFn: ({ signal }: { signal: AbortSignal }) => systemApi.agentCommand(signal), staleTime: Infinity } as const;

/** The backend's answer: the exact command agents run, for this installation. */
export function useAgentLaunch(): AgentLaunch | undefined {
  const query = useQuery(agentCommand);
  return query.data?.command?.length ? query.data : undefined;
}

/**
 * The desktop window knows at once; a browser (development) asks the backend. Until the backend
 * answers, and when it runs from source, the Flatpak is assumed.
 */
export function useInstall(): Install {
  const desktop = typeof window === "undefined" ? undefined : window.projectBrainDesktop?.install;
  const launch = useQuery({ ...agentCommand, enabled: !desktop });
  const reported = launch.data?.install;
  return desktop ?? (INSTALLS.includes(reported as Install) ? (reported as Install) : "flatpak");
}
