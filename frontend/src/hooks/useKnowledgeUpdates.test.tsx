import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useKnowledgeUpdates, useWorkspaceBrain } from "./useGraph";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function Watcher() {
  useKnowledgeUpdates(30);
  useWorkspaceBrain();
  return null;
}

it("reloads the brain when an agent changes knowledge, and only then", async () => {
  let version = 7;
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(String(url));
    if (String(url).endsWith("/brain/version")) return Response.json({ version });
    return Response.json({ projects: [], shelves: [], nodes: [], links: [] });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  render(<QueryClientProvider client={client}><Watcher /></QueryClientProvider>);
  const brainLoads = () => calls.filter((url) => url.endsWith("/api/brain")).length;

  await waitFor(() => expect(calls.filter((url) => url.endsWith("/brain/version")).length).toBeGreaterThan(3));
  expect(brainLoads()).toBe(1); // the version did not move, so nothing reloads

  version = 8; // an agent saved a link through its MCP server
  await waitFor(() => expect(brainLoads()).toBe(2));
  await waitFor(() => expect(calls.filter((url) => url.endsWith("/brain/version")).length).toBeGreaterThan(8));
  expect(brainLoads()).toBe(2);
});
