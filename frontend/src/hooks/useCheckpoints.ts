import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { checkpointsApi } from "../api/checkpoints";
import { invalidateProject, queryKeys } from "../lib/queries";
import type { CheckpointChanges, CheckpointInput } from "../types/checkpoint";

const rootKey = queryKeys.checkpoints;

export function useCheckpointsFeed(projectId: string, task?: string) {
  const pageSize = 20;
  return useInfiniteQuery({
    queryKey: [...rootKey(projectId), "feed", task ?? null],
    queryFn: ({ pageParam, signal }) => checkpointsApi.list(projectId, { task, limit: pageSize, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => lastPage.length === pageSize ? pages.length * pageSize : undefined,
    enabled: Boolean(projectId),
  });
}

export function useLatestCheckpoint(projectId: string, task?: string) {
  return useQuery({
    queryKey: [...rootKey(projectId), "latest", task ?? null],
    queryFn: ({ signal }) => checkpointsApi.latest(projectId, task, signal),
    enabled: Boolean(projectId),
  });
}

export function useCheckpoint(projectId: string, id: string | null) {
  return useQuery({
    queryKey: [...rootKey(projectId), "record", id],
    queryFn: ({ signal }) => checkpointsApi.get(projectId, id!, signal),
    enabled: Boolean(projectId && id),
  });
}

export function useCheckpointActions(projectId: string) {
  const client = useQueryClient();
  const refresh = async () => {
    await invalidateProject(client, projectId);
  };
  const create = useMutation({ mutationFn: (input: CheckpointInput) => checkpointsApi.create(projectId, input), onSuccess: refresh });
  const update = useMutation({ mutationFn: ({ id, changes }: { id: string; changes: CheckpointChanges }) => checkpointsApi.update(projectId, id, changes), onSuccess: refresh });
  return { create, update };
}
