import { useMutation, useQuery, useQueryClient, type Query } from "@tanstack/react-query";
import { tasksApi } from "../api/tasks";
import { invalidateProject, queryKeys } from "../lib/queries";
import type { MilestoneChanges, RelationshipType, TaskDetail, TaskInput, TaskStatus, TaskSummary, TaskUpdate } from "../types/task";


export function useTasks(projectId: string) {
  return useQuery({ queryKey: queryKeys.tasks(projectId), queryFn: ({ signal }) => tasksApi.list(projectId, signal), enabled: Boolean(projectId) });
}
export function useArchivedTasks(projectId: string, enabled: boolean) {
  return useQuery({ queryKey: queryKeys.archivedTasks(projectId), queryFn: ({ signal }) => tasksApi.listArchived(projectId, signal), enabled: Boolean(projectId && enabled) });
}
export function useTask(projectId: string, taskId: string | null, enabled = true) {
  return useQuery({ queryKey: queryKeys.task(projectId, taskId ?? ""), queryFn: ({ signal }) => tasksApi.get(projectId, taskId!, signal), enabled: Boolean(projectId && taskId && enabled) });
}
export function useMilestones(projectId: string, includeArchived = false) {
  return useQuery({ queryKey: [...queryKeys.milestones(projectId), includeArchived], queryFn: ({ signal }) => tasksApi.milestones(projectId, signal, includeArchived), enabled: Boolean(projectId) });
}
/** Overviews feed project cards; a failure just hides the extra summary. */
export function useOverviews() {
  return useQuery({ queryKey: queryKeys.overviews, queryFn: ({ signal }) => tasksApi.overviews(signal), retry: false });
}
export function useWorkspaceTasks() {
  return useQuery({ queryKey: queryKeys.workspaceTasks, queryFn: ({ signal }) => tasksApi.workspaceTasks(signal) });
}

/** Anything that changes tasks refreshes every view that shows them. */
function useRefresh(projectId: string) {
  const queryClient = useQueryClient();
  return async (task?: TaskDetail) => {
    if (task) queryClient.setQueryData(queryKeys.task(projectId, task.id), task);
    await invalidateProject(queryClient, projectId);
  };
}

export function useCreateTask(projectId: string) {
  const refresh = useRefresh(projectId);
  return useMutation({ mutationFn: (input: TaskInput) => tasksApi.create(projectId, input), onSuccess: refresh });
}
export function useUpdateTask(projectId: string) {
  const refresh = useRefresh(projectId);
  return useMutation({ mutationFn: ({ id, changes }: { id: string; changes: TaskUpdate }) => tasksApi.update(projectId, id, changes), onSuccess: refresh });
}
export function useStartTask(projectId: string) {
  const refresh = useRefresh(projectId);
  return useMutation({ mutationFn: (id: string) => tasksApi.start(projectId, id), onSuccess: refresh });
}
/** Drops the deleted task's cached record before refreshing, and its panel pauses that query, so the record is not asked for again. */
export function useDeleteTask(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => tasksApi.remove(projectId, id),
    onSuccess: async (_result, id) => {
      const deleted = (query: Query) => query.queryKey[0] === "task" && query.queryKey[1] === projectId && (query.state.data as TaskDetail | undefined)?.id === id;
      queryClient.removeQueries({ predicate: deleted });
      await invalidateProject(queryClient, projectId);
    },
  });
}
export function useFocus(projectId: string) {
  const refresh = useRefresh(projectId);
  return useMutation({ mutationFn: (task: string | null) => tasksApi.setFocus(projectId, task), onSuccess: () => refresh() });
}

/** Board moves update the cache first so a dropped card never snaps back. */
export function useMoveTask(projectId: string) {
  const queryClient = useQueryClient();
  const refresh = useRefresh(projectId);
  return useMutation({
    mutationFn: ({ id, status, index }: { id: string; status: TaskStatus; index: number }) => tasksApi.move(projectId, id, status, index),
    onMutate: async ({ id, status, index }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.tasks(projectId) });
      const previous = queryClient.getQueryData<TaskSummary[]>(queryKeys.tasks(projectId));
      if (previous) {
        const moving = previous.find((t) => t.id === id);
        if (moving) {
          const column = previous.filter((t) => t.status === status && t.id !== id).sort((a, b) => a.sort_order - b.sort_order);
          column.splice(Math.min(index, column.length), 0, { ...moving, status });
          const reordered = new Map(column.map((t, i) => [t.id, { ...t, sort_order: i }]));
          queryClient.setQueryData(queryKeys.tasks(projectId), previous.map((t) => reordered.get(t.id) ?? t).filter((t) => t.id !== id || reordered.has(id)));
        }
      }
      return { previous };
    },
    onError: (_error, _vars, context) => { if (context?.previous) queryClient.setQueryData(queryKeys.tasks(projectId), context.previous); },
    onSettled: () => refresh(),
  });
}

export function useCriterionActions(projectId: string, taskId: string) {
  const refresh = useRefresh(projectId);
  const add = useMutation({ mutationFn: (description: string) => tasksApi.addCriterion(projectId, taskId, description), onSuccess: refresh });
  const update = useMutation({ mutationFn: ({ id, changes }: { id: string; changes: { description?: string; is_completed?: boolean; sort_order?: number } }) => tasksApi.updateCriterion(projectId, taskId, id, changes), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: string) => tasksApi.deleteCriterion(projectId, taskId, id), onSuccess: refresh });
  return { add, update, remove };
}
export function useRelationshipActions(projectId: string, taskId: string) {
  const refresh = useRefresh(projectId);
  const add = useMutation({ mutationFn: ({ type, target }: { type: RelationshipType; target: string }) => tasksApi.addRelationship(projectId, taskId, type, target), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: string) => tasksApi.removeRelationship(projectId, taskId, id), onSuccess: refresh });
  return { add, remove };
}
export function useMilestoneActions(projectId: string) {
  const refresh = useRefresh(projectId);
  const create = useMutation({ mutationFn: (name: string) => tasksApi.createMilestone(projectId, { name }), onSuccess: () => refresh() });
  const update = useMutation({ mutationFn: ({ id, changes }: { id: string; changes: MilestoneChanges }) => tasksApi.updateMilestone(projectId, id, changes), onSuccess: () => refresh() });
  return { create, update };
}
