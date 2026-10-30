import { Activity, Brain, CircleHelp, FolderKanban, Gauge, Globe2, House, Inbox, ListTodo, Settings2, type LucideIcon } from "lucide-react";
import { labels, msg } from "../lib/i18n";

export interface NavItem { label: string; to: string; icon: LucideIcon }

/** Pages used most days, at the top of the sidebar. */
export const primaryNav: NavItem[] = [
  labels({ label: msg("Home"), to: "/", icon: House }, ["label"]),
  labels({ label: msg("Inbox"), to: "/review", icon: Inbox }, ["label"]),
  labels({ label: msg("All tasks"), to: "/tasks", icon: ListTodo }, ["label"]),
  labels({ label: msg("Brain"), to: "/brain", icon: Brain }, ["label"]),
];

/** Workspace-wide pages visited less often, below the project list. */
export const secondaryNav: NavItem[] = [
  labels({ label: msg("Activity"), to: "/activity", icon: Activity }, ["label"]),
  labels({ label: msg("Global rules"), to: "/global", icon: Globe2 }, ["label"]),
  labels({ label: msg("Usage"), to: "/usage", icon: Gauge }, ["label"]),
];

export const supportNav: NavItem[] = [
  labels({ label: msg("Help"), to: "/help", icon: CircleHelp }, ["label"]),
  labels({ label: msg("Settings"), to: "/settings", icon: Settings2 }, ["label"]),
];

export const projectsNavItem: NavItem = labels({ label: msg("Projects"), to: "/projects", icon: FolderKanban }, ["label"]);
