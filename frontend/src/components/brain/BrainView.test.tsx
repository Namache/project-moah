import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { BrainView, workspaceGraph } from "./BrainView";
import { useBrainStore } from "./store";

vi.mock("./BrainScene", () => ({ BrainScene: () => <div data-testid="scene" /> }));

const brain = {
  projects: [
    { id: "global", name: "Global rules", accent: null, global: true },
    { id: "p1", name: "Trailhead", accent: null, global: false },
    { id: "p2", name: "Starcount", accent: null, global: false },
  ],
  shelves: [{ id: "s-1", name: "Inventory", parent_id: null, project_id: "p1" }],
  nodes: [
    { key: "memory:g1", kind: "memory", id: "g1", label: "RULE-001", title: "Small commits", subtype: "rule", status: "active", shelves: [], degree: 0, project_id: "global" },
    { key: "task:t1", kind: "task", id: "t1", label: "INV-001", title: "Fix duplication", subtype: null, status: "todo", shelves: [], degree: 1, project_id: "p1" },
    { key: "memory:m1", kind: "memory", id: "m1", label: "RULE-002", title: "Clear before load", subtype: "rule", status: "active", shelves: ["s-1"], degree: 1, project_id: "p1" },
    { key: "memory:m2", kind: "memory", id: "m2", label: "FACT-001", title: "Star map", subtype: "fact", status: "active", shelves: [], degree: 0, project_id: "p2" },
  ],
  links: [{ source: "task:t1", target: "memory:m1", relationship: "governed_by", group: "learning", strength: 0.7, status: "active" }],
};
const activation = { operation: "debugging", nodes: { "memory:m1": 0.6 }, included: ["memory:m1"], paths: [["task:t1", "memory:m1"]], shelves: { "s-1": 0.8 } };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); useBrainStore.setState({ selected: null, focusShelf: null }); });

it("makes each project a region, with its shelves inside and global rules in the core", () => {
  const graph = workspaceGraph(brain as never);
  expect(graph.shelves.find((s) => s.id === "project:global")?.core).toBe(true);
  expect(graph.shelves.find((s) => s.id === "s-1")?.parent_id).toBe("project:p1");
  expect(graph.nodes.find((n) => n.key === "memory:m2")?.shelves).toEqual(["project:p2"]);
  expect(graph.nodes.find((n) => n.key === "memory:m1")?.shelves).toEqual(["s-1"]);
});

it("lights up a task from any project and explains why a record was reached", async () => {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.includes("/graph/activation")) return Response.json(activation);
    if (url.endsWith("/brain")) return Response.json(brain);
    if (url.includes("/tasks")) return Response.json([{ id: "t1", human_id: "INV-001", title: "Fix duplication", status: "todo", project_id: "p1" }]);
    if (url.includes("/links?node=")) return Response.json({ node: brain.nodes[2], links: [] });
    return Response.json([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><BrainView webgl /></QueryClientProvider>);

  expect(await screen.findByTestId("scene")).toBeInTheDocument();
  expect(screen.getByText(/Items: 4, links: 1, projects: 3, shelves: 1/)).toBeInTheDocument();
  await userEvent.selectOptions(await screen.findByLabelText("Light up a task"), "p1|INV-001");
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/projects/p1/graph/activation?task=INV-001"))).toBe(true);
  expect(await screen.findByRole("button", { name: "Inventory 80%" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Trailhead 60%" })).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("Find a record"), "RULE-002");
  expect(await screen.findByText(/In the context pack \(score 0.60\)/)).toBeInTheDocument();
  expect(screen.getByText("Came by: INV-001 → RULE-002")).toBeInTheDocument();
  expect(screen.getByText(/Trailhead · rule/)).toBeInTheDocument();
});

it("explains when 3D graphics are unavailable", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json(url.endsWith("/brain") ? brain : [])));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><BrainView webgl={false} /></QueryClientProvider>);
  expect(await screen.findByText(/could not start 3D graphics/)).toBeInTheDocument();
  expect(screen.queryByTestId("scene")).toBeNull();
});
