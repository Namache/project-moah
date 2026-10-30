import { afterEach, expect, it, vi } from "vitest";
import { checkpointsApi } from "./checkpoints";

afterEach(() => vi.unstubAllGlobals());

it("scopes checkpoint lookup to the project and encodes task filters", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) => Response.json([]));
  vi.stubGlobal("fetch", fetchMock);

  await checkpointsApi.list("project / one", { task: "CAMP / 1", limit: 20, offset: 40 });

  const [url] = fetchMock.mock.calls[0];
  const parsed = new URL(String(url), "http://localhost");
  expect(parsed.pathname).toBe("/api/projects/project%20%2F%20one/checkpoints");
  expect(parsed.searchParams.get("task")).toBe("CAMP / 1");
  expect(parsed.searchParams.get("limit")).toBe("20");
  expect(parsed.searchParams.get("offset")).toBe("40");
});

it("treats a missing latest checkpoint as an empty state but preserves other errors", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "No checkpoint" }, { status: 404 })));
  await expect(checkpointsApi.latest("p1", "CAMP-001")).resolves.toBeNull();

  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "Database unavailable" }, { status: 503 })));
  await expect(checkpointsApi.latest("p1")).rejects.toThrow("Database unavailable");
});
