import { expect, it } from "vitest";
import { checkpointPath, memoryPath, projectPath, taskPath } from "./routes";

it("links project records to project pages and Global records to the Global pages", () => {
  expect(taskPath("p1", "CAMP 1")).toBe("/projects/p1/tasks?task=CAMP%201");
  expect(memoryPath("p1", "DEC-001")).toBe("/projects/p1/memory?memory=DEC-001");
  expect(checkpointPath("p1", "c1")).toBe("/projects/p1?checkpoint=c1");
  expect(projectPath("p1", "memory", { task: "CAMP-1", new: "1", memory: null })).toBe("/projects/p1/memory?task=CAMP-1&new=1");
  expect(memoryPath("global", "RULE-001")).toBe("/global?memory=RULE-001");
  expect(projectPath("global", "review")).toBe("/global/review");
  expect(projectPath("global", "tasks")).toBe("/global");
});
