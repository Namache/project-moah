import type { MemoryStatus, MemoryType } from "./memory";

export type SearchEntityType = "project" | "task" | "memory" | "checkpoint" | "file";

export interface SearchResult {
  entity_type: SearchEntityType;
  entity_id: string;
  project_id: string;
  project_name: string;
  human_id: string | null;
  title: string;
  snippet: string;
  status: string;
  memory_type: MemoryType | null;
  score: number;
  updated_at: string | null;
}

export interface SearchResponse {
  items: SearchResult[];
  total: number;
  limit: number;
  offset: number;
}

export interface SearchFilters {
  q: string;
  entityTypes?: SearchEntityType[];
  memoryTypes?: MemoryType[];
  memoryStatuses?: MemoryStatus[];
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}
