import { afterEach, expect, it, vi } from "vitest";
import { activityApi } from "./activity";

afterEach(() => vi.unstubAllGlobals());

it("scopes a project timeline and encodes its actor, entity, and task filters", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) => Response.json([]));
  vi.stubGlobal("fetch", fetchMock);

  await activityApi.project("project / one", { actorTypes: ["claude", "codex"], entityTypes: ["task"], task: "CAMP-001", limit: 50, offset: 50 });

  const [url] = fetchMock.mock.calls[0];
  const parsed = new URL(String(url), "http://localhost");
  expect(parsed.pathname).toBe("/api/projects/project%20%2F%20one/activity");
  expect(parsed.searchParams.getAll("actor_type")).toEqual(["claude", "codex"]);
  expect(parsed.searchParams.getAll("entity_type")).toEqual(["task"]);
  expect(parsed.searchParams.get("task")).toBe("CAMP-001");
  expect(parsed.searchParams.get("limit")).toBe("50");
  expect(parsed.searchParams.get("offset")).toBe("50");
});
