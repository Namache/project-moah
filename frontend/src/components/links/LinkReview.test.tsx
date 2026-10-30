import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { LinkReview } from "./LinkReview";

const candidate = {
  link_id: "link-9", relationship: "relates_to", confidence: 0.55, why: "titles of FACT-002 and DEC-001 overlap",
  source: { kind: "memory", id: "m-2", label: "FACT-002", title: "Ownership of InventoryManager", subtype: "fact", status: "active" },
  target: { kind: "memory", id: "m-1", label: "DEC-001", title: "Inventory ownership moved", subtype: "decision", status: "active" },
};
const orphan = { id: "NOTE-004", type: "note", title: "Zebra pattern", node: "memory:m-4" };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("confirms and rejects guessed links and lists orphan memory", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/links/candidates")) return Response.json([candidate]);
    if (url.endsWith("/links/orphans")) return Response.json([orphan]);
    if (url.endsWith("/links/discover")) return Response.json({ records: 3, mentions: 1, candidates: 2 });
    if (init?.method === "POST") return Response.json({});
    return Response.json([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><LinkReview projectId="project-1" readonly={false} /></QueryClientProvider>);

  await userEvent.click(screen.getByRole("button", { name: /Guessed links/ }));
  expect(await screen.findByText("55% sure")).toBeInTheDocument();
  expect(await screen.findByText("NOTE-004")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Confirm link FACT-002 to DEC-001" }));
  await userEvent.click(screen.getByRole("button", { name: "Reject link FACT-002 to DEC-001" }));
  const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST").map(([url]) => url);
  expect(posts).toEqual(["/api/projects/project-1/links/link-9/confirm", "/api/projects/project-1/links/link-9/reject"]);

  await userEvent.click(screen.getByRole("button", { name: "Look for links" }));
  expect(await screen.findByText(/Checked 3 tasks and memories: 1 links from names/)).toBeInTheDocument();
});

it("hides review actions in an archived project", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json(url.endsWith("/candidates") ? [candidate] : [])));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><LinkReview projectId="project-1" readonly /></QueryClientProvider>);
  await userEvent.click(screen.getByRole("button", { name: /Guessed links/ }));
  expect(await screen.findByText("55% sure")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Confirm link/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "Look for links" })).toBeNull();
});
