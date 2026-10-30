import { QueryClient } from "@tanstack/react-query";
import { expect, it } from "vitest";
import { invalidateProject } from "./queries";

it("refreshes every view of the project and the workspace-wide views, but not other projects", async () => {
  const client = new QueryClient();
  const keys = [["memory-links", "p1"], ["context", "p1", "", "balanced"], ["task", "p1", "CAMP-1"], ["search", null, { q: "x" }], ["projects"], ["memory", "p2"], ["usage", "7d", "both"]];
  keys.forEach((key) => client.setQueryData(key, 1));
  await invalidateProject(client, "p1");
  const stale = keys.filter((key) => client.getQueryState(key)?.isInvalidated).map((key) => key.join("/"));
  expect(stale).toEqual(["memory-links/p1", "context/p1//balanced", "task/p1/CAMP-1", "search//[object Object]", "projects"]);
});
