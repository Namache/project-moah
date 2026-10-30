import { labels, msg } from "../lib/i18n";
export type ProposalType = "create_memory" | "update_memory" | "supersede_memory" | "complete_task" | "update_task" | "add_acceptance_criterion" | "associate_file" | "create_bug";
export type ProposalStatus = "pending" | "accepted" | "rejected";

export const proposalLabels: Record<ProposalType, string> = labels({
  create_memory: msg("New memory"),
  update_memory: msg("Change memory"),
  supersede_memory: msg("Replace memory"),
  complete_task: msg("Complete task"),
  update_task: msg("Update task"),
  add_acceptance_criterion: msg("New requirement"),
  associate_file: msg("File notes"),
  create_bug: msg("New known issue"),
});

export interface Proposal {
  id: string;
  project_id: string;
  human_id: string;
  agent: string;
  proposal_type: ProposalType;
  target_entity_type: string | null;
  target_entity_id: string | null;
  target_label: string | null;
  target_locked: boolean;
  payload: Record<string, unknown>;
  snapshot: Record<string, unknown> | null;
  reason: string;
  status: ProposalStatus;
  review_note: string | null;
  applied_payload: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  reviewed_at: string | null;
  changes: string[];
}
export interface AcceptAllResult { accepted: Proposal[]; failed: Proposal[] }
export interface PendingCount { total: number; by_project: Record<string, number> }
