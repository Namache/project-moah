import { Activity, Brain, CircleHelp, FolderKanban, Gauge, Globe2, House, Inbox, ListTodo, Settings2, type LucideIcon } from "lucide-react";

export interface NavItem { label: string; to: string; icon: LucideIcon }

/** Pages used most days, at the top of the sidebar. */
export const primaryNav: NavItem[] = [
  { label: "Home", to: "/", icon: House },
  { label: "Inbox", to: "/review", icon: Inbox },
  { label: "All tasks", to: "/tasks", icon: ListTodo },
  { label: "Brain", to: "/brain", icon: Brain },
];

/** Workspace-wide pages visited less often, below the project list. */
export const secondaryNav: NavItem[] = [
  { label: "Activity", to: "/activity", icon: Activity },
  { label: "Global rules", to: "/global", icon: Globe2 },
  { label: "Usage", to: "/usage", icon: Gauge },
];

export const supportNav: NavItem[] = [
  { label: "Help", to: "/help", icon: CircleHelp },
  { label: "Settings", to: "/settings", icon: Settings2 },
];

export const projectsNavItem: NavItem = { label: "Projects", to: "/projects", icon: FolderKanban };
