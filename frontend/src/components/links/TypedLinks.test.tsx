import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { TypedLinks } from "./TypedLinks";

const node = { kind: "task", id: "task-1", label: "INV-001", title: "Fix duplication", subtype: null, status: "todo" };
const links = {
  node,
  links: [
    { id: null, relationship: "governed_by", stored_relationship: "applies_to", direction: "incoming", group: "learning",
      node: { kind: "memory", id: "m-1", label: "RULE-001", title: "Clear before load", subtype: "rule", status: "active" },
      strength: 0.7, confidence: 1, status: "active", origin: "memory_task", created_by: "system", note: null },
    { id: "link-1", relationship: "affects", stored_relationship: "affects", direction: "outgoing", group: "structural",
      node: { kind: "memory", id: "m-2", label: "FACT-002", title: "InventoryManager owns state", subtype: "fact", status: "active" },
      strength: 0.9, confidence: 1, status: "active", origin: "link", created_by: "user", note: null },
  ],
};
const types = [{ name: "affects", inverse: "affected_by", group: "structural" }, { name: "relates_to", inverse: "relates_to", group: "knowledge" }];

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("lists links read from this record and adds a typed link", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/links/relationships")) return Response.json(types);
    if (init?.method === "POST") return Response.json(links.links[1], { status: 201 });
    return Response.json(links);
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TypedLinks projectId="project-1" node="task:task-1" readonly={false} /></QueryClientProvider>);

  expect(await screen.findByText("RULE-001")).toBeInTheDocument();
  expect(screen.getByText("governed by")).toBeInTheDocument();
  expect(screen.getByText("built in")).toBeInTheDocument();
  // Only stored links can be removed here; built-in ones are changed where they were made.
  expect(screen.getAllByRole("button", { name: /Remove link/ })).toHaveLength(1);

  await userEvent.selectOptions(await screen.findByLabelText("Relationship"), "affects");
  await userEvent.type(screen.getByLabelText("Linked record"), "FACT-002");
  await userEvent.selectOptions(screen.getByLabelText("Strength"), "0.9");
  await userEvent.click(screen.getByRole("button", { name: "Link" }));
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(post?.[0]).toBe("/api/projects/project-1/links");
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({ source: "task:task-1", relationship: "affects", target: "FACT-002", strength: 0.9 });
});
