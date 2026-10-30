import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { proposalsApi } from "../api/proposals";
import { invalidateProject, queryKeys } from "../lib/queries";
import type { ProposalStatus } from "../types/proposal";

export function usePendingProposals() {
  return useQuery({ queryKey: queryKeys.proposalsPending, queryFn: ({ signal }) => proposalsApi.pending(signal), refetchInterval: 30_000, retry: false });
}
export function useProposals(projectId: string, statuses: ProposalStatus[]) {
  return useQuery({ queryKey: [...queryKeys.proposals(projectId), statuses], queryFn: ({ signal }) => proposalsApi.list(projectId, statuses, signal) });
}

export function useReviewActions(projectId: string) {
  const queryClient = useQueryClient();
  // Accepting can change tasks, memory, files, and what search and context show.
  const refresh = () => invalidateProject(queryClient, projectId);
  return {
    accept: useMutation({ mutationFn: ({ id, payload, note }: { id: string; payload?: Record<string, unknown>; note?: string }) => proposalsApi.accept(projectId, id, payload, note), onSettled: refresh }),
    reject: useMutation({ mutationFn: ({ id, note }: { id: string; note?: string }) => proposalsApi.reject(projectId, id, note), onSettled: refresh }),
    acceptAll: useMutation({ mutationFn: () => proposalsApi.acceptAll(projectId), onSettled: refresh }),
  };
}
