import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { activityApi } from "../api/activity";
import type { ActivityFilters } from "../types/activity";

const pageSize = 50;

export function useProjectActivity(projectId: string, filters: ActivityFilters = {}) {
  return useInfiniteQuery({
    queryKey: ["activity", "project", projectId, filters],
    queryFn: ({ pageParam, signal }) => activityApi.project(projectId, { ...filters, limit: pageSize, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => lastPage.length === pageSize ? pages.length * pageSize : undefined,
    enabled: Boolean(projectId),
  });
}

export function useWorkspaceActivity(filters: ActivityFilters = {}) {
  return useInfiniteQuery({
    queryKey: ["activity", "workspace", filters],
    queryFn: ({ pageParam, signal }) => activityApi.workspace({ ...filters, limit: pageSize, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => lastPage.length === pageSize ? pages.length * pageSize : undefined,
  });
}

export function useRecentActivity(projectId: string) {
  return useQuery({
    queryKey: ["activity", "recent", projectId],
    queryFn: ({ signal }) => activityApi.project(projectId, { limit: 5 }, signal),
    enabled: Boolean(projectId),
  });
}

/** The latest few events across every project, for Home. */
export function useWorkspaceRecent(limit = 6) {
  return useQuery({
    queryKey: ["activity", "recent", "workspace", limit],
    queryFn: ({ signal }) => activityApi.workspace({ limit }, signal),
  });
}
