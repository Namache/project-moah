import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { reviewsApi } from "../api/reviews";
import type { FollowUpColumn, ReviewDecisionInput } from "../types/review";
import { invalidateProject, queryKeys } from "../lib/queries";

/** Everything waiting for the person, for badges: finished tasks and agents' suggestions. */
export function usePendingReviews() {
  return useQuery({ queryKey: queryKeys.reviewsPending, queryFn: ({ signal }) => reviewsApi.pending(signal), refetchInterval: 30_000, retry: false });
}

export function useReviewTimeline(projectId?: string) {
  return useQuery({ queryKey: queryKeys.reviews(projectId), queryFn: ({ signal }) => reviewsApi.timeline(projectId, signal), refetchInterval: 30_000 });
}

export function useTaskReview(projectId: string | undefined, taskRef: string | undefined) {
  return useQuery({
    queryKey: queryKeys.review(projectId ?? "", taskRef ?? ""),
    queryFn: ({ signal }) => reviewsApi.detail(projectId!, taskRef!, signal),
    enabled: Boolean(projectId && taskRef),
  });
}

export function useReviewDecision(projectId: string, taskRef: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: ReviewDecisionInput) => reviewsApi.decide(projectId, taskRef, input),
    // Deciding changes the task's status, the board, the brief and every count. Not awaited, so
    // the screen can pick what to show next before the lists change under it.
    onSettled: () => { void invalidateProject(client, projectId); },
  });
}

/** Makes tasks from lines of a review; the board and the review show them at once. */
export function useFollowUps(projectId: string, taskRef: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ items, status }: { items: string[]; status?: FollowUpColumn }) => reviewsApi.followUps(projectId, taskRef, items, status),
    onSuccess: (detail) => { client.setQueryData(queryKeys.review(projectId, taskRef), detail); },
    onSettled: () => { void invalidateProject(client, projectId); },
  });
}
