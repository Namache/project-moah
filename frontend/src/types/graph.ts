export type NodeKind = "task" | "memory" | "file" | "checkpoint" | "milestone" | "shelf";
export type LinkStatus = "active" | "weak" | "candidate" | "disputed" | "superseded" | "archived" | "rejected";

/** One reason a link exists, oldest first. */
export interface Provenance {
  source: string;
  detail: string;
  at?: string;
}

export interface GraphNode {
  kind: NodeKind;
  id: string;
  label: string;
  title: string;
  subtype: string | null;
  status: string | null;
}

/** A link as seen from one record: `relationship` reads from that record to `node`. */
export interface TypedLink {
  id: string | null;
  relationship: string;
  stored_relationship: string;
  direction: "outgoing" | "incoming";
  group: string;
  node: GraphNode;
  strength: number;
  confidence: number;
  status: LinkStatus;
  origin: string;
  created_by: string;
  note: string | null;
  provenance: Provenance[];
  contextual_weights: Record<string, number>;
  success_count: number;
  failure_count: number;
}

export interface NodeLinks {
  node: GraphNode;
  links: TypedLink[];
}

export interface LinkInput {
  source: string;
  relationship: string;
  target: string;
  strength?: number;
  note?: string;
}

export interface RelationshipType {
  name: string;
  inverse: string;
  group: string;
}

export interface Shelf {
  id: string;
  name: string;
  description: string | null;
  parent_id: string | null;
  keywords: string[];
  member_count: number;
}

export interface ShelfDetail extends Shelf {
  members: GraphNode[];
}

export interface ShelfInput {
  name?: string;
  description?: string | null;
  parent?: string | null;
  keywords?: string[];
}

export interface ShelfActivation {
  id: string;
  name: string;
  activation: number;
  active: boolean;
  reason: string;
}

export interface CandidateLink {
  link_id: string;
  source: GraphNode;
  relationship: string;
  target: GraphNode;
  confidence: number;
  why: string;
}

export interface Orphan {
  id: string;
  type: string;
  title: string;
  node: string;
}

export interface DiscoverResult {
  mentions?: string[] | number;
  candidates?: string[] | number;
  records?: number;
}

export interface BrainNode {
  key: string;
  kind: NodeKind;
  id: string;
  label: string;
  title: string;
  subtype: string | null;
  status: string | null;
  shelves: string[];
  degree: number;
}

export interface BrainLink {
  source: string;
  target: string;
  relationship: string;
  group: string;
  strength: number;
  status: LinkStatus;
  /** A project's link into a Global record (Phase 4 cross-project route). */
  route?: boolean;
}

export interface BrainShelf {
  id: string;
  name: string;
  parent_id: string | null;
  /** The region in the middle of the brain (the global rules). */
  core?: boolean;
  /** On the shared tree every project files its records on. */
  shared?: boolean;
}

export interface BrainGraph {
  nodes: BrainNode[];
  links: BrainLink[];
  shelves: BrainShelf[];
}

export interface BrainProject {
  id: string;
  name: string;
  accent: string | null;
  global: boolean;
}

/** The whole workspace: every project that isn't archived, plus the global rules. */
export interface WorkspaceBrain {
  projects: BrainProject[];
  nodes: (BrainNode & { project_id: string })[];
  links: BrainLink[];
  shelves: (BrainShelf & { project_id: string })[];
}

/** What a context pack for some work lights up. Keys are "kind:id". */
export interface BrainActivation {
  operation: string;
  nodes: Record<string, number>;
  included: string[];
  paths: string[][];
  shelves: Record<string, number>;
}

/** Reads a relationship name as words: depends_on -> depends on. */
export const relationshipLabel = (name: string) => name.replace(/_/g, " ");

/** Link System Phase 3: graph health, clusters and shelf suggestions. */
export interface ShelfDensity {
  shelf_id: string;
  name: string;
  records: number;
  connected: number;
}

export interface RetrievalHealth {
  packs: number;
  /** Packs and packs with feedback in the last 30 days. */
  packs_recent: number;
  feedback_recent: number;
  /** Share of pack records that came in over links, not a word search, a shelf or the task. */
  through_links: number | null;
  average_depth: number | null;
  average_records: number | null;
  average_tokens: number | null;
  feedback_share: number | null;
  useful_share: number | null;
}

export interface ProjectHealth {
  id: string;
  name: string;
  nodes: number;
  links: number;
  strong_links: number;
  weak_links: number;
  guessed_links: number;
  /** Memory a link or shelf could lead an agent to (not in every pack, not manual only). */
  memory: number;
  /** Of that memory, how much nothing links to: only a word search finds it, and in the Global scope nothing does. */
  orphans: number;
  conflicts: number;
  superseded: number;
  shelves: number;
  /** trend: "new" or "growing" since the last daily snapshot (Phase 4). */
  clusters: { name: string; size: number; trend?: "new" | "growing" | null }[];
  density: ShelfDensity[];
  retrieval: RetrievalHealth;
  /** Checkpoints in the last 30 days: how often agents did real work here lately. */
  checkpoints_recent: number;
}

export interface ShelfSuggestion {
  key: string;
  /** Shelves are categories of knowledge, so a cluster is offered an existing shelf (place) or
   * flagged as needing a category a person names (needs_category, a notice only). Phase 4 adds
   * self-tuning shelves (add_member, add_keyword, remove_member), recurring failure areas
   * (pattern, a notice only) and sharing a lesson as one Global record (share). */
  kind: "place" | "needs_category" | "merge" | "add_member" | "add_keyword" | "remove_member" | "pattern" | "share";
  name: string;
  /** The suggestion in English, as agents read it. The app shows its own wording, built from kind, size and args. */
  message: string;
  args?: Record<string, string | number>;
  size: number;
  members: string[];
  parent: { id: string; name: string } | null;
  merge_from?: { id: string; name: string };
  /** The first few records the suggestion would touch. */
  records?: { label: string; title: string }[];
  project_id: string;
  project_name: string;
}

export interface WorkspaceHealth {
  projects: ProjectHealth[];
  suggestions: ShelfSuggestion[];
  last_decay: string | null;
  path_cache: { hits: number; misses: number };
}
