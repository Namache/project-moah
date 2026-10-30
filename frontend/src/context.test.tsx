import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const project = { id: "p1", name: "Trailhead", slug: "c", description: null, icon: null, accent: null, root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };
const pack = (detail: string, over = {}) => ({ project_id: "p1", project_name: "Trailhead", task: "CAMP-001", detail_level: detail, budget: 1500, estimated_tokens: detail === "minimal" ? 300 : 900, over_budget: false, text: `PACK ${detail}`, sections: [{ key: "task", title: "Current Task", tokens: 100, items: 1 }, { key: "decisions", title: "Important Decisions", tokens: 200, items: 2 }], items: [], omitted: { hidden: 2, "manual only": 1 }, warnings: [], ...over });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("AI context inspector", () => {
  it("previews each detail level, shows what was left out, and includes manual-only memory on request", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/projects?")) return Response.json([project]);
      if (url === "/api/projects/p1") return Response.json(project);
      if (url.startsWith("/api/projects/p1/context")) return Response.json(pack(new URL(url, "http://x").searchParams.get("detail") ?? "balanced"));
      if (url.startsWith("/api/projects/p1/memory")) return Response.json([{ id: "m1", human_id: "NOTE-001", title: "Manual party note", type: "note" }]);
      return Response.json([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/projects/p1/context"]}><App /></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText(/about 900 tokens/)).toBeInTheDocument();
    expect(screen.getByText("2 hidden from AI")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Minimal/ }));
    expect(await screen.findByText(/about 300 tokens/)).toBeInTheDocument();
    await user.click(await screen.findByRole("checkbox", { name: /NOTE-001/ }));
    await screen.findByText(/about 300 tokens/);
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("include=NOTE-001") && String(u).includes("detail=minimal"))).toBe(true);
    await user.click(screen.getByRole("button", { name: "Preview context" }));
    expect(screen.getByLabelText("Context preview")).toHaveTextContent("PACK minimal");
  });
});
