import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { memoryApi } from "../api/memory";
import { invalidateProject, queryKeys } from "../lib/queries";
import type { MemoryChanges, MemoryFilters, MemoryInput, MemoryReplacement } from "../types/memory";

const rootKey = queryKeys.memory;

/** `fresh` always refetches when a view opens, for views that must not start from cached data. */
export function useMemoryList(projectId: string, filters: MemoryFilters = {}, enabled = true, fresh = false) {
  return useQuery({ queryKey: [...rootKey(projectId), "list", filters], queryFn: ({ signal }) => memoryApi.list(projectId, filters, signal), enabled: Boolean(projectId && enabled), refetchOnMount: fresh ? "always" : true });
}
export function useMemoryFeed(projectId: string, filters: MemoryFilters = {}) {
  const pageSize = 100;
  return useInfiniteQuery({
    queryKey: [...rootKey(projectId), "feed", filters],
    queryFn: ({ pageParam, signal }) => memoryApi.list(projectId, { ...filters, limit: pageSize, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => lastPage.length === pageSize ? allPages.length * pageSize : undefined,
    enabled: Boolean(projectId),
  });
}
export function useMemoryCounts(projectId: string) {
  return useQuery({ queryKey: [...rootKey(projectId), "counts"], queryFn: ({ signal }) => memoryApi.counts(projectId, signal), enabled: Boolean(projectId) });
}
export function useMemoryRecord(projectId: string, ref: string | null) {
  return useQuery({ queryKey: [...rootKey(projectId), "record", ref], queryFn: ({ signal }) => memoryApi.get(projectId, ref!, signal), enabled: Boolean(projectId && ref) });
}
export function useMemoryHistory(projectId: string, ref: string | null, enabled = true) {
  return useQuery({ queryKey: [...rootKey(projectId), "history", ref], queryFn: ({ signal }) => memoryApi.history(projectId, ref!, signal), enabled: Boolean(projectId && ref && enabled) });
}

export function useMemoryActions(projectId: string) {
  const client = useQueryClient();
  const refresh = async () => {
    await invalidateProject(client, projectId);
  };
  const create = useMutation({ mutationFn: (input: MemoryInput) => memoryApi.create(projectId, input), onSuccess: refresh });
  const update = useMutation({ mutationFn: ({ ref, changes }: { ref: string; changes: MemoryChanges }) => memoryApi.update(projectId, ref, changes), onSuccess: refresh });
  const link = useMutation({ mutationFn: ({ ref, related }: { ref: string; related: string }) => memoryApi.link(projectId, ref, related), onSuccess: refresh });
  const unlink = useMutation({ mutationFn: ({ ref, related }: { ref: string; related: string }) => memoryApi.unlink(projectId, ref, related), onSuccess: refresh });
  const supersede = useMutation({ mutationFn: ({ ref, input }: { ref: string; input: MemoryReplacement }) => memoryApi.supersede(projectId, ref, input), onSuccess: refresh });
  const archive = useMutation({ mutationFn: (ref: string) => memoryApi.archive(projectId, ref), onSuccess: refresh });
  const invalidate = useMutation({ mutationFn: (ref: string) => memoryApi.invalidate(projectId, ref), onSuccess: refresh });
  const restore = useMutation({ mutationFn: (ref: string) => memoryApi.restore(projectId, ref), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (ref: string) => memoryApi.remove(projectId, ref), onSuccess: refresh });
  return { create, update, supersede, archive, invalidate, restore, remove, link, unlink };
}
