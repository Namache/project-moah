import type { ImageInfo } from "./image";
import type { TaskRef } from "./task";

export type MemoryType = "decision" | "rule" | "fact" | "idea" | "bug" | "note" | "warning";
export type MemoryStatus = "active" | "superseded" | "invalidated" | "archived";
export type MemoryImportance = "low" | "normal" | "high" | "critical";
export type AiVisibility = "always" | "relevant_only" | "manual_only" | "hidden";
export type MemorySort = "priority" | "updated_desc" | "updated_asc" | "title_asc";

export const memoryTypes: { value: MemoryType; label: string; plural: string }[] = [
  { value: "decision", label: "Decision", plural: "Decisions" },
  { value: "rule", label: "Rule", plural: "Rules" },
  { value: "fact", label: "Fact", plural: "Facts" },
  { value: "idea", label: "Idea", plural: "Ideas" },
  { value: "bug", label: "Known issue", plural: "Known issues" },
  { value: "note", label: "Note", plural: "Notes" },
  { value: "warning", label: "Warning", plural: "Warnings" },
];

export const visibilityLabels: Record<AiVisibility, string> = {
  always: "Always",
  relevant_only: "Relevant only",
  manual_only: "Manual only",
  hidden: "Hidden",
};

export interface MemoryRef {
  id: string;
  human_id: string;
  type: MemoryType;
  title: string;
  status: MemoryStatus;
}

export interface MemoryRecord extends MemoryRef {
  project_id: string;
  content: string;
  importance: MemoryImportance;
  is_pinned: boolean;
  is_locked: boolean;
  /** Known issues only: false is pending, true is resolved. */
  is_resolved: boolean;
  /** Why a known issue is still pending, written during review. */
  pending_note: string | null;
  ai_visibility: AiVisibility;
  source_type: string | null;
  source_reference: string | null;
  confidence: number | null;
  supersedes_id: string | null;
  created_at: string;
  updated_at: string;
  invalidated_at: string | null;
  archived_at: string | null;
  tags: string[];
  tasks: TaskRef[];
  superseded_by: MemoryRef | null;
  supersedes: MemoryRef | null;
  /** Other memories of the same project this one is connected to. */
  related?: MemoryRef[];
  images?: ImageInfo[];
}

export interface MemoryHistory { chain: MemoryRef[]; current_id: string }
export interface MemoryCounts { by_type: Partial<Record<MemoryType, number>>; pinned: number; locked: number }

export interface MemoryInput {
  type: MemoryType;
  title: string;
  content?: string;
  importance?: MemoryImportance;
  ai_visibility?: AiVisibility;
  is_pinned?: boolean;
  is_locked?: boolean;
  is_resolved?: boolean;
  pending_note?: string | null;
  source_type?: string | null;
  source_reference?: string | null;
  confidence?: number | null;
  tags?: string[];
  task_ids?: string[];
}

export type MemoryChanges = Partial<Omit<MemoryInput, "type">>;
export type MemoryReplacement = Pick<MemoryInput, "title"> & Partial<Pick<MemoryInput, "content" | "importance" | "ai_visibility" | "is_locked">>;

export interface MemoryFilters {
  types?: MemoryType[];
  statuses?: MemoryStatus[];
  visibility?: AiVisibility[];
  pinned?: boolean;
  locked?: boolean;
  resolved?: boolean;
  tag?: string;
  task?: string;
  q?: string;
  sort?: MemorySort;
  limit?: number;
  offset?: number;
}
