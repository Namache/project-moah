import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { filesApi } from "../api/files";
import { invalidateProject } from "../lib/queries";
import type { FileChanges } from "../types/files";

export function useFileTree(projectId: string) {
  return useQuery({ queryKey: ["file-tree", projectId], queryFn: ({ signal }) => filesApi.tree(projectId, signal) });
}
export function useFileNotes(projectId: string, id: string | null) {
  return useQuery({ queryKey: ["file", projectId, id], queryFn: ({ signal }) => filesApi.get(projectId, id!, signal), enabled: Boolean(id) });
}
export function useFileHistory(projectId: string, id: string | null) {
  return useQuery({ queryKey: ["file-history", projectId, id], queryFn: ({ signal }) => filesApi.history(projectId, id!, signal), enabled: Boolean(id) });
}
export function useCommits(projectId: string) {
  return useQuery({ queryKey: ["commits", projectId], queryFn: ({ signal }) => filesApi.commits(projectId, signal) });
}

function useRefresh(projectId: string) {
  const queryClient = useQueryClient();
  return () => invalidateProject(queryClient, projectId);
}

export function useFileActions(projectId: string) {
  const refresh = useRefresh(projectId);
  return {
    create: useMutation({ mutationFn: ({ path, changes }: { path: string; changes?: FileChanges }) => filesApi.create(projectId, path, changes), onSuccess: refresh }),
    update: useMutation({ mutationFn: ({ id, changes }: { id: string; changes: FileChanges }) => filesApi.update(projectId, id, changes), onSuccess: refresh }),
    reviewed: useMutation({ mutationFn: (id: string) => filesApi.reviewed(projectId, id), onSuccess: refresh }),
    remove: useMutation({ mutationFn: (id: string) => filesApi.remove(projectId, id), onSuccess: refresh }),
    link: useMutation({ mutationFn: ({ sha, task }: { sha: string; task: string }) => filesApi.linkCommit(projectId, sha, task), onSuccess: refresh }),
    unlink: useMutation({ mutationFn: ({ sha, task }: { sha: string; task: string }) => filesApi.unlinkCommit(projectId, sha, task), onSuccess: refresh }),
  };
}
