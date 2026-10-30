import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../types/task";
import { ArchivedTasks } from "./ArchivedTasks";

const archivedTask: TaskSummary = {
  id: "t1", project_id: "p1", milestone_id: null, human_id: "CAMP-001", title: "Old migration",
  status: "archived", priority: "normal", next_action: null, sort_order: 0,
  criteria_total: 0, criteria_completed: 0, tags: [], is_focus: false, is_blocked_by_open_dependency: false,
};

function renderArchived(onOpen = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ArchivedTasks projectId="p1" onOpen={onOpen} /></QueryClientProvider>);
  return onOpen;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("loads archived tasks on demand and opens one for restoration", async () => {
  const fetchMock = vi.fn(async () => Response.json([archivedTask]));
  vi.stubGlobal("fetch", fetchMock);
  const onOpen = renderArchived();
  const user = userEvent.setup();

  expect(fetchMock).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Archived tasks" }));
  expect(await screen.findByText("Old migration")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/projects/p1/tasks?status=archived", expect.any(Object));
  await user.click(within(screen.getByRole("region", { name: "Archived tasks" })).getByRole("button", { name: /Old migration/ }));
  expect(onOpen).toHaveBeenCalledWith(archivedTask);
});

it("shows a retry action when the archived list fails to load", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(Response.json({ detail: "Unavailable" }, { status: 503 }))
    .mockResolvedValueOnce(Response.json([]));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  renderArchived();

  await user.click(screen.getByRole("button", { name: "Archived tasks" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Unavailable");
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("No archived tasks.")).toBeInTheDocument();
});
