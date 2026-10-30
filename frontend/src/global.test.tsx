import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ConnectedMemories } from "./components/memory/ConnectedMemories";
import type { MemoryRecord } from "./types/memory";

const base = { project_id: "p1", content: "", status: "active", importance: "normal", is_pinned: false, is_locked: false, is_resolved: false, pending_note: null, ai_visibility: "relevant_only", source_type: null, source_reference: null, confidence: null, supersedes_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", invalidated_at: null, archived_at: null, tags: [], tasks: [], superseded_by: null, supersedes: null } as const;
const decision = { ...base, id: "m1", human_id: "DEC-001", type: "decision", title: "Capacity is 6", related: [{ id: "m2", human_id: "FACT-001", type: "fact", title: "Camps hold six", status: "active" }] } as unknown as MemoryRecord;
const fact = { ...base, id: "m2", human_id: "FACT-001", type: "fact", title: "Camps hold six", related: [] };
const warning = { ...base, id: "m3", human_id: "WARN-001", type: "warning", title: "Saves break above 9", related: [] };

function wrap(ui: React.ReactNode, path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("connected memories", () => {
  it("lists connections, connects another memory and disconnects one", async () => {
    const calls: { url: string; method: string; body?: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      calls.push({ url: String(input), method: options?.method ?? "GET", body: options?.body ? String(options.body) : undefined });
      if (String(input).includes("/links")) return Response.json(decision);
      return Response.json([decision, fact, warning]);
    }));
    const onOpen = vi.fn();
    wrap(<ConnectedMemories projectId="p1" memory={decision} readonly={false} onOpen={onOpen} />);
    const section = within(screen.getByRole("region", { name: /Connected memories/ }));
    await userEvent.click(section.getByRole("button", { name: "FACT-001 Camps hold six" }));
    expect(onOpen).toHaveBeenCalledWith("FACT-001");

    // Itself and already connected memories are not offered.
    const picker = await section.findByRole("combobox", { name: "Memory to connect" });
    await screen.findByRole("option", { name: "WARN-001 Saves break above 9" });
    expect(within(picker).queryByRole("option", { name: /DEC-001|FACT-001/ })).toBeNull();
    await userEvent.selectOptions(picker, "m3");
    await userEvent.click(section.getByRole("button", { name: "Connect" }));
    expect(calls.find((c) => c.method === "POST")).toMatchObject({ url: "/api/projects/p1/memory/m1/links", body: JSON.stringify({ related: "m3" }) });

    await userEvent.click(section.getByRole("button", { name: "Disconnect FACT-001" }));
    expect(calls.find((c) => c.method === "DELETE")?.url).toBe("/api/projects/p1/memory/m1/links/m2");
  });

  it("is read-only for records that are not active", () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json([])));
    wrap(<ConnectedMemories projectId="p1" memory={decision} readonly onOpen={() => {}} />);
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Disconnect/ })).toBeNull();
  });
});

describe("global rules page", () => {
  it("shows the Global scope's memory and is reachable from the sidebar", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input); urls.push(url);
      if (url.startsWith("/api/projects/global/memory/counts")) return Response.json({ by_type: { rule: 1 }, pinned: 0, locked: 0 });
      if (url.startsWith("/api/projects/global/memory")) return Response.json([{ ...base, id: "g1", project_id: "global", human_id: "RULE-001", type: "rule", title: "Ask before building", related: [] }]);
      if (url === "/api/proposals/pending") return Response.json({ total: 1, by_project: { global: 1 } });
      return Response.json([]);
    }));
    wrap(<App />, "/global");
    expect(await screen.findByRole("heading", { level: 1, name: "Global rules" })).toBeInTheDocument();
    expect(await screen.findByText("Ask before building")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Global rules" })).toHaveAttribute("href", "/global");
    // Waiting suggestions for the Global scope lead to its own Review tab.
    expect(screen.getAllByRole("link").some((l) => l.getAttribute("href") === "/global/review")).toBe(true);
  });
});
