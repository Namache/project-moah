export type DetailLevel = "minimal" | "balanced" | "detailed";

export interface ContextItem { section: string; kind: string; ref: string | null; title: string; tokens: number; reason: string }
export interface ContextSection { key: string; title: string; tokens: number; items: number }

export interface ContextPack {
  project_id: string;
  project_name: string;
  task: string | null;
  detail_level: DetailLevel;
  budget: number;
  estimated_tokens: number;
  over_budget: boolean;
  text: string;
  sections: ContextSection[];
  items: ContextItem[];
  omitted: Record<string, number>;
  warnings: string[];
}

export interface ContextOptions {
  task?: string | null;
  query?: string;
  detail: DetailLevel;
  budget?: number | null;
  include?: string[];
  exclude?: string[];
}
