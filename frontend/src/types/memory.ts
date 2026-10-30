import type { ImageInfo } from "./image";
import type { TaskRef } from "./task";
import { labels, msg } from "../lib/i18n";

export type MemoryType = "decision" | "rule" | "fact" | "idea" | "bug" | "note" | "warning";
export type MemoryStatus = "active" | "superseded" | "invalidated" | "archived";
export type MemoryImportance = "low" | "normal" | "high" | "critical";
export type AiVisibility = "always" | "relevant_only" | "manual_only" | "hidden";
export type MemorySort = "priority" | "updated_desc" | "updated_asc" | "title_asc";

export const memoryTypes: { value: MemoryType; label: string; plural: string }[] = [
  labels({ value: "decision", label: msg("Decision"), plural: msg("Decisions") }, ["label", "plural"]),
  labels({ value: "rule", label: msg("Rule"), plural: msg("Rules") }, ["label", "plural"]),
  labels({ value: "fact", label: msg("Fact"), plural: msg("Facts") }, ["label", "plural"]),
  labels({ value: "idea", label: msg("Idea"), plural: msg("Ideas") }, ["label", "plural"]),
  labels({ value: "bug", label: msg("Known issue"), plural: msg("Known issues") }, ["label", "plural"]),
  labels({ value: "note", label: msg("Note"), plural: msg("Notes") }, ["label", "plural"]),
  labels({ value: "warning", label: msg("Warning"), plural: msg("Warnings") }, ["label", "plural"]),
];

export const visibilityLabels: Record<AiVisibility, string> = labels({
  always: msg("Always"),
  relevant_only: msg("Relevant only"),
  manual_only: msg("Manual only"),
  hidden: msg("Hidden"),
});

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
