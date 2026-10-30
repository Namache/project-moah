import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { ActivityEvent } from "../../types/activity";
import { ProjectActivity } from "./ProjectActivity";
import { WorkspaceActivity } from "./WorkspaceActivity";
import { RecentActivity } from "./RecentActivity";

const event: ActivityEvent = {
  id: "event-1", project_id: "p1", project_name: "Trailhead", event_type: "TASK_CREATED",
  actor_type: "claude", actor_name: "Claude Code", entity_type: "task", entity_id: "task-1",
  task_id: "task-1", metadata: { title: "Build camp", human_id: "CAMP-001" },
  timestamp: "2026-10-10T12:00:00Z",
};

function renderFeed(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows project events with actor, timestamp, entity link, and applies actor filtering", async () => {
  const fetchMock = vi.fn(async () => Response.json([event]));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  renderFeed(<ProjectActivity projectId="p1" />);

  expect(await screen.findByText("Task created")).toBeInTheDocument();
  expect(screen.getByText("Claude Code · Claude")).toBeInTheDocument();
  expect(screen.getByText("CAMP-001")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open task" })).toHaveAttribute("href", "/projects/p1/tasks?task=task-1");
  expect(document.querySelector("time")).toHaveAttribute("datetime", event.timestamp);

  await user.click(screen.getByRole("button", { name: "Claude" }));
  expect(screen.getByRole("button", { name: "Claude" })).toHaveAttribute("aria-pressed", "true");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/projects/p1/activity?actor_type=claude&limit=50&offset=0", expect.any(Object)));
});

it("shows project identity and loads later workspace events", async () => {
  const firstPage = Array.from({ length: 50 }, (_, index) => ({ ...event, id: `event-${index}`, metadata: { title: `Task ${index}` } }));
  const later = { ...event, id: "later", project_id: "p2", project_name: "Starling", event_type: "CHECKPOINT_CREATED", entity_type: "checkpoint" as const, entity_id: "checkpoint-1", metadata: { title: "Phase 4 complete" } };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    return Response.json(url.searchParams.get("offset") === "50" ? [later] : firstPage);
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  renderFeed(<WorkspaceActivity />);

  expect(await screen.findByRole("button", { name: "Load more activity" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Load more activity" }));
  expect(await screen.findByRole("link", { name: "Starling" })).toHaveAttribute("href", "/projects/p2");
  expect(screen.getByRole("link", { name: "Open checkpoint" })).toHaveAttribute("href", "/projects/p2?checkpoint=checkpoint-1");
  expect(fetchMock).toHaveBeenCalledWith("/api/activity?limit=50&offset=50", expect.any(Object));
});

it("explains an empty activity timeline", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json([])));
  renderFeed(<ProjectActivity projectId="p1" />);

  expect(await screen.findByRole("heading", { name: "No activity yet" })).toBeInTheDocument();
});

it("shows a compact recent history with a link to the project timeline", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) => Response.json([event]));
  vi.stubGlobal("fetch", fetchMock);
  renderFeed(<RecentActivity projectId="p1" />);

  expect(await screen.findByText("Task created")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "CAMP-001 Build camp" })).toHaveAttribute("href", "/projects/p1/tasks?task=task-1");
  expect(screen.queryByRole("link", { name: "Open task" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "All activity" })).toHaveAttribute("href", "/projects/p1/activity");
  expect(fetchMock).toHaveBeenCalledWith("/api/projects/p1/activity?limit=5", expect.any(Object));
});

it("keeps deleted task history without linking to a missing record", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json([{ ...event, event_type: "TASK_DELETED" }])));
  renderFeed(<ProjectActivity projectId="p1" />);

  expect(await screen.findByText("Task deleted")).toBeInTheDocument();
  expect(screen.getByText("CAMP-001")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Open task" })).not.toBeInTheDocument();
});
