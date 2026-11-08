import { t } from "../lib/i18n";
import type { WorkPrompt, AgentName } from "./agents";
import type { FollowUpColumn, PendingReviews, ReviewDecisionInput, ReviewDetail, ReviewFile, ReviewTimeline } from "../types/review";
import { ApiError, authHeaders, json, request } from "./client";

const task = (projectId: string, ref: string) => `/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(ref)}/review`;

export const reviewsApi = {
  timeline: (projectId?: string, signal?: AbortSignal) => request<ReviewTimeline>(`/reviews${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`, { signal }),
  pending: (signal?: AbortSignal) => request<PendingReviews>("/reviews/pending", { signal }),
  detail: (projectId: string, ref: string, signal?: AbortSignal) => request<ReviewDetail>(task(projectId, ref), { signal }),
  decide: (projectId: string, ref: string, { comment, ...rest }: ReviewDecisionInput) =>
    request<ReviewDetail>(`${task(projectId, ref)}/decision`, json("POST", { ...rest, comment: comment.trim() || null })),
  /** Takes back an acceptance: the task goes back to In progress, and the comment reaches the next agent. */
  reopen: (projectId: string, ref: string, comment: string) =>
    request<ReviewDetail>(`${task(projectId, ref)}/reopen`, json("POST", { comment: comment.trim() })),
  /** Takes back an Accept pressed a moment ago: the work waits in Review again. */
  undo: (projectId: string, ref: string) => request<ReviewDetail>(`${task(projectId, ref)}/undo`, json("POST", {})),
  /** Makes tasks from lines of the review: what was not done, or an unmet criterion. */
  followUps: (projectId: string, ref: string, items: string[], status: FollowUpColumn = "todo") =>
    request<ReviewDetail>(`${task(projectId, ref)}/follow-ups`, json("POST", { items, status })),
  /** Sends the file itself as the body; the backend checks its bytes, not its name. */
  attach: (projectId: string, ref: string, file: Blob, filename: string) =>
    request<ReviewFile>(`${task(projectId, ref)}/files?filename=${encodeURIComponent(filename)}`, {
      method: "POST",
      body: file,
      headers: { "Content-Type": file.type || "application/octet-stream" },
    }),
  remove: (projectId: string, fileId: string) => request<void>(`/projects/${encodeURIComponent(projectId)}/review-files/${encodeURIComponent(fileId)}`, json("DELETE")),
  fixPrompt: (projectId: string, ref: string, agent?: AgentName) => request<WorkPrompt>(`${task(projectId, ref)}/fix-prompt${agent ? `?agent=${agent}` : ""}`),
  /** A screenshot or attached file as a blob: an <img> cannot send the desktop token. */
  async blob(projectId: string, fileId: string, signal?: AbortSignal): Promise<Blob> {
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/review-files/${encodeURIComponent(fileId)}`, { headers: authHeaders(), signal });
    if (!response.ok) throw new ApiError(t("The file could not be loaded."), response.status);
    return response.blob();
  },
};
