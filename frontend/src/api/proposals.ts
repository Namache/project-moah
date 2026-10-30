import { json, request } from "./client";
import type { AcceptAllResult, PendingCount, Proposal, ProposalStatus } from "../types/proposal";

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/proposals`;

export const proposalsApi = {
  list: (projectId: string, statuses: ProposalStatus[], signal?: AbortSignal) => request<Proposal[]>(`${base(projectId)}?${statuses.map((s) => `status=${s}`).join("&")}`, { signal }),
  pending: (signal?: AbortSignal) => request<PendingCount>("/proposals/pending", { signal }),
  accept: (projectId: string, id: string, payload?: Record<string, unknown>, note?: string) => request<Proposal>(`${base(projectId)}/${encodeURIComponent(id)}/accept`, json("POST", payload || note ? { payload, note } : {})),
  reject: (projectId: string, id: string, note?: string) => request<Proposal>(`${base(projectId)}/${encodeURIComponent(id)}/reject`, json("POST", note ? { note } : {})),
  acceptAll: (projectId: string) => request<AcceptAllResult>(`${base(projectId)}/accept-all`, json("POST")),
};
