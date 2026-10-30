import { request } from "./client";
import type { Agent, UsageReport } from "../types/usage";

export interface UsageQuery { since: Date; until?: Date; agent?: Agent | null; bucket?: "hour" | "day" }

export const usageApi = {
  get: (q: UsageQuery, signal?: AbortSignal) => {
    const params = new URLSearchParams({ since: q.since.toISOString(), tz_offset: String(-q.since.getTimezoneOffset()), bucket: q.bucket ?? "day" });
    if (q.until) params.set("until", q.until.toISOString());
    if (q.agent) params.set("agent", q.agent);
    return request<UsageReport>(`/usage?${params}`, { signal });
  },
};
