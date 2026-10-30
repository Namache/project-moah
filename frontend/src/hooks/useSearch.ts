import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { searchApi } from "../api/search";
import type { SearchFilters, SearchResult } from "../types/search";

const PAGE = 25;

/** Pages of results for one query. Pass projectId null for the explicit all-projects search. */
export function useSearch(projectId: string | null, filters: SearchFilters) {
  const q = filters.q.trim();
  return useInfiniteQuery({
    queryKey: ["search", projectId, { ...filters, q }],
    enabled: q.length > 0,
    initialPageParam: 0,
    placeholderData: keepPreviousData,
    queryFn: ({ pageParam, signal }) => {
      const page = { ...filters, q, limit: PAGE, offset: pageParam };
      return projectId === null ? searchApi.workspace(page, signal) : searchApi.project(projectId, page, signal);
    },
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.limit : undefined),
    select: (data) => ({ items: data.pages.flatMap((p) => p.items) as SearchResult[], total: data.pages[0]?.total ?? 0 }),
  });
}
