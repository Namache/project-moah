import { useQuery } from "@tanstack/react-query";
import { usageApi } from "../api/usage";
import type { Agent } from "../types/usage";

export type UsageRange = "today" | "7d" | "30d";
export type AgentFilter = Agent | "both";

/** Local midnight for "today", so days match the person's clock rather than UTC. */
export function rangeStart(range: UsageRange, now = new Date()): Date {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  if (range === "7d") start.setDate(start.getDate() - 6);
  if (range === "30d") start.setDate(start.getDate() - 29);
  return start;
}

/** Refreshes every 10 seconds while the window is visible; the service only reads newly written log lines. */
export function useUsage(range: UsageRange, agent: AgentFilter = "both") {
  return useQuery({
    queryKey: ["usage", range, agent],
    queryFn: ({ signal }) => usageApi.get({ since: rangeStart(range), agent: agent === "both" ? null : agent, bucket: range === "today" ? "hour" : "day" }, signal),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
    retry: false,
  });
}

/** One bucket (an hour or a day) the person clicked in the chart, for the breakdown below it. */
export function useUsageSlice(start: string | null, hourly: boolean, agent: AgentFilter) {
  return useQuery({
    queryKey: ["usage-slice", start, hourly, agent],
    enabled: Boolean(start),
    queryFn: ({ signal }) => {
      const since = new Date(start!);
      const until = new Date(since);
      if (hourly) until.setHours(until.getHours() + 1); else until.setDate(until.getDate() + 1);
      return usageApi.get({ since, until, agent: agent === "both" ? null : agent, bucket: "hour" }, signal);
    },
    refetchInterval: 30_000,
    retry: false,
  });
}
