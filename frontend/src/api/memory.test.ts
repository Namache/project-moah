import { afterEach, expect, it, vi } from "vitest";
import { memoryApi } from "./memory";

afterEach(() => vi.unstubAllGlobals());

it("scopes memory filters to the selected project and encodes search values", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) => Response.json([]));
  vi.stubGlobal("fetch", fetchMock);

  await memoryApi.list("project / one", {
    types: ["decision", "idea"], statuses: ["archived"], tag: "gameplay & saves", q: "party size",
  });

  const [url] = fetchMock.mock.calls[0];
  const parsed = new URL(String(url), "http://localhost");
  expect(parsed.pathname).toBe("/api/projects/project%20%2F%20one/memory");
  expect(parsed.searchParams.getAll("type")).toEqual(["decision", "idea"]);
  expect(parsed.searchParams.getAll("status")).toEqual(["archived"]);
  expect(parsed.searchParams.get("tag")).toBe("gameplay & saves");
  expect(parsed.searchParams.get("q")).toBe("party size");
});

it("accepts an empty successful response when deleting a memory", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
  await expect(memoryApi.remove("p1", "DEC-001")).resolves.toBeUndefined();
});
