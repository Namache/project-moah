import { afterEach, expect, it, vi } from "vitest";
import { projectsApi } from "./projects";

afterEach(() => {
  delete window.projectBrainDesktop;
  vi.unstubAllGlobals();
});

it("authenticates API requests from the desktop window", async () => {
  window.projectBrainDesktop = Object.freeze({ apiToken: "desktop-test-token" });
  const fetchMock = vi.fn(async () => Response.json([]));
  vi.stubGlobal("fetch", fetchMock);

  await projectsApi.list();

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects?include_archived=true",
    expect.objectContaining({
      headers: expect.objectContaining({ "X-Project-Brain-Token": "desktop-test-token" }),
    }),
  );
});
