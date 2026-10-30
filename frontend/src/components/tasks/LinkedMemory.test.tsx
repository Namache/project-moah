import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { MemoryRecord } from "../../types/memory";
import { LinkedMemory } from "./LinkedMemory";

const decision: MemoryRecord = {
  id: "memory-1", human_id: "DEC-001", project_id: "project-1", type: "decision",
  title: "Keep saves compatible", content: "Use schema migrations.", status: "active",
  importance: "high", is_pinned: false, is_locked: false, is_resolved: false, pending_note: null, ai_visibility: "always",
  source_type: null, source_reference: null, confidence: null, supersedes_id: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  invalidated_at: null, archived_at: null, tags: [], tasks: [],
  superseded_by: null, supersedes: null,
};

function renderLinkedMemory() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><LinkedMemory projectId="project-1" task={{ id: "task-1", human_id: "CAMP-001" }} /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows active memory linked to this task and opens it in the same project", async () => {
  const fetchMock = vi.fn(async () => Response.json([decision]));
  vi.stubGlobal("fetch", fetchMock);
  renderLinkedMemory();

  expect(await screen.findByRole("link", { name: "Open Decision memory DEC-001: Keep saves compatible" })).toHaveAttribute("href", "/projects/project-1/memory?memory=DEC-001");
  expect(screen.getByText("Decision")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/projects/project-1/memory?status=active&task=task-1", expect.any(Object));
  expect(screen.getByRole("link", { name: "View task memory" })).toHaveAttribute("href", "/projects/project-1/memory?task=CAMP-001");
});

it("explains an empty task and offers to create linked memory", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json([])));
  renderLinkedMemory();

  expect(await screen.findByText("No active memory is linked to this task yet.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Add memory" })).toHaveAttribute("href", "/projects/project-1/memory?task=CAMP-001&new=1");
});
