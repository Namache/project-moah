import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { projectsApi } from "../api/projects";
import { invalidateProject, queryKeys } from "../lib/queries";
import type { ProjectInput, ProjectUpdate } from "../types/project";

export function useProjects() {
  return useQuery({ queryKey: queryKeys.projects, queryFn: ({ signal }) => projectsApi.list(signal) });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: queryKeys.project(id),
    queryFn: ({ signal }) => projectsApi.get(id, signal),
    enabled: Boolean(id),
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (project: ProjectInput) => projectsApi.create(project),
    onSuccess: (project) => invalidateProject(queryClient, project.id),
  });
}

export function useUpdateProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: ProjectUpdate) => projectsApi.update(id, changes),
    onSuccess: (project) => invalidateProject(queryClient, project.id),
  });
}

export function useArchiveProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => projectsApi.archive(id),
    onSuccess: (project) => invalidateProject(queryClient, project.id),
  });
}

export function useRestoreProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => projectsApi.update(id, { status: "active" }),
    onSuccess: (project) => invalidateProject(queryClient, project.id),
  });
}
