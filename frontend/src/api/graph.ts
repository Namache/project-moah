import { json, request } from "./client";
import type { BrainActivation, WorkspaceBrain, CandidateLink, DiscoverResult, LinkInput, Orphan, NodeLinks, RelationshipType, Shelf, ShelfActivation, ShelfDetail, ShelfInput, TypedLink, WorkspaceHealth } from "../types/graph";

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;
const shelf = (projectId: string, ref: string) => `${base(projectId)}/shelves/${encodeURIComponent(ref)}`;

export const graphApi = {
  relationships: (projectId: string, signal?: AbortSignal) => request<RelationshipType[]>(`${base(projectId)}/links/relationships`, { signal }),
  links: (projectId: string, node: string, signal?: AbortSignal) => request<NodeLinks>(`${base(projectId)}/links?node=${encodeURIComponent(node)}`, { signal }),
  link: (projectId: string, input: LinkInput) => request<TypedLink>(`${base(projectId)}/links`, json("POST", input)),
  unlink: (projectId: string, linkId: string) => request<void>(`${base(projectId)}/links/${encodeURIComponent(linkId)}`, json("DELETE")),
  confirm: (projectId: string, linkId: string) => request<TypedLink>(`${base(projectId)}/links/${encodeURIComponent(linkId)}/confirm`, json("POST")),
  reject: (projectId: string, linkId: string) => request<TypedLink>(`${base(projectId)}/links/${encodeURIComponent(linkId)}/reject`, json("POST")),
  candidates: (projectId: string, signal?: AbortSignal) => request<CandidateLink[]>(`${base(projectId)}/links/candidates`, { signal }),
  orphans: (projectId: string, signal?: AbortSignal) => request<Orphan[]>(`${base(projectId)}/links/orphans`, { signal }),
  discover: (projectId: string, node?: string) => request<DiscoverResult>(`${base(projectId)}/links/discover`, json("POST", node ? { node } : {})),
  brain: (signal?: AbortSignal) => request<WorkspaceBrain>("/brain", { signal }),
  health: (signal?: AbortSignal) => request<WorkspaceHealth>("/brain/health", { signal }),
  version: (signal?: AbortSignal) => request<{ version: number }>("/brain/version", { signal }),
  acceptSuggestion: (projectId: string, key: string) => request<{ shelf_id: string; name: string }>(`${base(projectId)}/shelf-suggestions/accept`, json("POST", { key })),
  dismissSuggestion: (projectId: string, key: string) => request<void>(`${base(projectId)}/shelf-suggestions/dismiss`, json("POST", { key })),
  graphActivation: (projectId: string, task: string, signal?: AbortSignal) => request<BrainActivation>(`${base(projectId)}/graph/activation?task=${encodeURIComponent(task)}`, { signal }),
  shelves: (projectId: string, signal?: AbortSignal) => request<Shelf[]>(`${base(projectId)}/shelves`, { signal }),
  shelf: (projectId: string, ref: string, signal?: AbortSignal) => request<ShelfDetail>(shelf(projectId, ref), { signal }),
  activation: (projectId: string, text: string, signal?: AbortSignal) => request<ShelfActivation[]>(`${base(projectId)}/shelves/activation?text=${encodeURIComponent(text)}`, { signal }),
  createShelf: (projectId: string, input: ShelfInput) => request<Shelf>(`${base(projectId)}/shelves`, json("POST", input)),
  updateShelf: (projectId: string, ref: string, input: ShelfInput) => request<Shelf>(shelf(projectId, ref), json("PATCH", input)),
  deleteShelf: (projectId: string, ref: string) => request<void>(shelf(projectId, ref), json("DELETE")),
  addMember: (projectId: string, ref: string, node: string) => request<ShelfDetail>(`${shelf(projectId, ref)}/members`, json("POST", { node })),
  removeMember: (projectId: string, ref: string, node: string) => request<ShelfDetail>(`${shelf(projectId, ref)}/members?node=${encodeURIComponent(node)}`, json("DELETE")),
};
