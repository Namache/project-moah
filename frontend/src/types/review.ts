import type { TaskStatus } from "./task";

export type ReviewStatus = "pending" | "accepted" | "rejected" | "answered" | "replaced";
export type ReviewVerdict = "accepted" | "rejected" | "answered";
/** work: an account of finished work. question: an agent stopped to ask you something. */
export type ReviewKind = "work" | "question";
export type FollowUpColumn = "todo" | "backlog";

/** A task you made from a line of the review. */
export interface FollowUp { text: string; task_id: string; task_ref: string; task_status: TaskStatus }

export interface ReviewFile {
  id: string;
  kind: "screenshot" | "feedback";
  filename: string;
  media_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  caption: string | null;
  created_by: string | null;
  created_at: string;
}

/** One round of a task's review: the agent's account of the work and the person's answer. */
export interface ReviewRound {
  id: string | null;
  round: number;
  agent: string;
  kind: ReviewKind;
  status: ReviewStatus;
  /** For a question, the question. */
  summary: string;
  done: string[];
  not_done: string[];
  how_to_check: string | null;
  details: string | null;
  /** A question's answers to pick from. */
  options: string[];
  generated: boolean;
  created_at: string;
  reviewed_at: string | null;
  comment: string | null;
  /** Set when the person decided by moving the task on the board: the column it went to. */
  moved_to: TaskStatus | "chat" | null;
  follow_ups: FollowUp[];
  screenshots: ReviewFile[];
  feedback: ReviewFile[];
}

export interface ReviewDetail {
  project_id: string;
  project_name: string;
  project_slug: string;
  task_id: string;
  task_ref: string;
  task_title: string;
  task_status: TaskStatus;
  task_description: string | null;
  criteria: { id: string; description: string; is_completed: boolean }[];
  current: ReviewRound;
  earlier: ReviewRound[];
}

/** One line of the Review timeline: a finished task or an agent's suggestion. */
export interface ReviewItem {
  kind: "task" | "suggestion";
  key: string;
  project_id: string;
  project_name: string;
  project_icon: string | null;
  project_accent: string | null;
  ref: string;
  title: string;
  summary: string;
  agent: string;
  done_at: string;
  reviewed_at: string | null;
  verdict: ReviewVerdict | null;
  /** An agent's question, waiting for your answer (or answered). */
  question: boolean;
  /** The task's board column now; null for a suggestion. */
  task_status: TaskStatus | null;
  moved_to: TaskStatus | "chat" | null;
  round: number;
  screenshots: number;
  generated: boolean;
}

export interface ReviewTimeline { waiting: ReviewItem[]; reviewed: ReviewItem[] }

export interface PendingReviews {
  total: number;
  by_project: Record<string, number>;
  newest: { key: string; kind: "task" | "suggestion"; project_name: string; agent: string; title: string; question: boolean }[];
}

/** What you decide on a review: accept or reject finished work, or answer an agent's question. */
export interface ReviewDecisionInput {
  verdict: "accept" | "reject" | "answer";
  comment: string;
  /** Which acceptance criteria are met, as you ticked them. */
  criteria?: { id: string; met: boolean }[];
  /** With accept: lines to make into new tasks, and the column they go to. */
  follow_ups?: string[];
  follow_up_status?: FollowUpColumn;
}

export const MAX_FEEDBACK_FILES = 10;
export const MAX_FEEDBACK_BYTES = 5 * 1024 * 1024;
export const MAX_TEXT_BYTES = 1024 * 1024;
