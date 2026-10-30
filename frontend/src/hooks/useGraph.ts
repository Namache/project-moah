import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { graphApi } from "../api/graph";
import { invalidateKnowledge, invalidateProject } from "../lib/queries";
import type { LinkInput, ShelfInput } from "../types/graph";

// Project ID second, so invalidateProject refreshes these with every other view of the project.
export function useNodeLinks(projectId: string, node: string | null) {
  return useQuery({ queryKey: ["links", projectId, node], queryFn: ({ signal }) => graphApi.links(projectId, node!, signal), enabled: Boolean(projectId && node) });
}
export function useRelationshipTypes(projectId: string) {
  return useQuery({ queryKey: ["relationships", projectId], queryFn: ({ signal }) => graphApi.relationships(projectId, signal), enabled: Boolean(projectId), staleTime: Infinity });
}
export function useShelves(projectId: string) {
  return useQuery({ queryKey: ["shelves", projectId], queryFn: ({ signal }) => graphApi.shelves(projectId, signal), enabled: Boolean(projectId) });
}
export function useShelf(projectId: string, ref: string | null) {
  return useQuery({ queryKey: ["shelves", projectId, ref], queryFn: ({ signal }) => graphApi.shelf(projectId, ref!, signal), enabled: Boolean(projectId && ref) });
}
export function useShelfActivation(projectId: string, text: string) {
  return useQuery({ queryKey: ["shelves", projectId, "activation", text], queryFn: ({ signal }) => graphApi.activation(projectId, text, signal), enabled: Boolean(projectId && text.trim()) });
}
export function useLinkReview(projectId: string) {
  const candidates = useQuery({ queryKey: ["linkReview", projectId, "candidates"], queryFn: ({ signal }) => graphApi.candidates(projectId, signal), enabled: Boolean(projectId) });
  const orphans = useQuery({ queryKey: ["linkReview", projectId, "orphans"], queryFn: ({ signal }) => graphApi.orphans(projectId, signal), enabled: Boolean(projectId) });
  return { candidates, orphans };
}
export function useWorkspaceBrain() {
  return useQuery({ queryKey: ["brain-all"], queryFn: ({ signal }) => graphApi.brain(signal) });
}
/**
 * Agents write through their own MCP server, not through this window, so their records and links
 * would only show up after a click. The backend counts every change to knowledge, whoever made
 * it; when the count moves, the views built on it refresh, so a link an agent makes appears in
 * the Brain while you watch. Polling pauses while the window is hidden.
 */
export function useKnowledgeUpdates(intervalMs = 4000) {
  const client = useQueryClient();
  const version = useQuery({ queryKey: ["brain-version"], queryFn: ({ signal }) => graphApi.version(signal), refetchInterval: intervalMs, staleTime: 0, retry: false });
  const seen = useRef<number | null>(null);
  const current = typeof version.data?.version === "number" ? version.data.version : null;
  useEffect(() => {
    if (current === null) return;
    if (seen.current !== null && current !== seen.current) void invalidateKnowledge(client);
    seen.current = current;
  }, [current, client]);
}
export function useBrainHealth() {
  return useQuery({ queryKey: ["brain-health"], queryFn: ({ signal }) => graphApi.health(signal) });
}
/** Accept or dismiss a shelf the brain suggests; accepting changes shelves, so the project refreshes. */
export function useShelfSuggestions() {
  const client = useQueryClient();
  const accept = useMutation({
    mutationFn: ({ projectId, key }: { projectId: string; key: string }) => graphApi.acceptSuggestion(projectId, key),
    onSuccess: (_data, { projectId }) => invalidateProject(client, projectId),
  });
  const dismiss = useMutation({
    mutationFn: ({ projectId, key }: { projectId: string; key: string }) => graphApi.dismissSuggestion(projectId, key),
    onSuccess: () => client.invalidateQueries({ queryKey: ["brain-health"] }),
  });
  return { accept, dismiss };
}
export function useBrainActivation(projectId: string | null, task: string | null) {
  return useQuery({ queryKey: ["brain", projectId, "activation", task], queryFn: ({ signal }) => graphApi.graphActivation(projectId!, task!, signal), enabled: Boolean(projectId && task) });
}

export function useGraphActions(projectId: string) {
  const client = useQueryClient();
  const refresh = async () => { await invalidateProject(client, projectId); };
  const link = useMutation({ mutationFn: (input: LinkInput) => graphApi.link(projectId, input), onSuccess: refresh });
  const unlink = useMutation({ mutationFn: (linkId: string) => graphApi.unlink(projectId, linkId), onSuccess: refresh });
  const createShelf = useMutation({ mutationFn: (input: ShelfInput) => graphApi.createShelf(projectId, input), onSuccess: refresh });
  const updateShelf = useMutation({ mutationFn: ({ ref, input }: { ref: string; input: ShelfInput }) => graphApi.updateShelf(projectId, ref, input), onSuccess: refresh });
  const deleteShelf = useMutation({ mutationFn: (ref: string) => graphApi.deleteShelf(projectId, ref), onSuccess: refresh });
  const addMember = useMutation({ mutationFn: ({ ref, node }: { ref: string; node: string }) => graphApi.addMember(projectId, ref, node), onSuccess: refresh });
  const removeMember = useMutation({ mutationFn: ({ ref, node }: { ref: string; node: string }) => graphApi.removeMember(projectId, ref, node), onSuccess: refresh });
  const confirm = useMutation({ mutationFn: (linkId: string) => graphApi.confirm(projectId, linkId), onSuccess: refresh });
  const reject = useMutation({ mutationFn: (linkId: string) => graphApi.reject(projectId, linkId), onSuccess: refresh });
  const discover = useMutation({ mutationFn: (node?: string) => graphApi.discover(projectId, node), onSuccess: refresh });
  return { link, unlink, confirm, reject, discover, createShelf, updateShelf, deleteShelf, addMember, removeMember };
}
