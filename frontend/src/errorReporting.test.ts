import { describe, expect, it, vi } from "vitest";
import { initErrorReporting } from "./lib/errorReporting";

describe("error reporting", () => {
  it("sends each uncaught window error once, and skips failed requests", async () => {
    const target = new EventTarget() as unknown as Window;
    const report = vi.fn(async (_message: string, _detail: string) => {});
    initErrorReporting(target, report);
    const boom = new TypeError("x is undefined");
    for (let i = 0; i < 3; i += 1) target.dispatchEvent(Object.assign(new Event("error"), { error: boom, message: boom.message }));
    const api = Object.assign(new Error("Task not found"), { name: "ApiError" });
    target.dispatchEvent(Object.assign(new Event("unhandledrejection"), { reason: api }));
    target.dispatchEvent(Object.assign(new Event("unhandledrejection"), { reason: new RangeError("bad index") }));
    expect(report).toHaveBeenCalledTimes(2);
    expect(report.mock.calls[0][0]).toBe("TypeError: x is undefined");
    expect(report.mock.calls[1][0]).toBe("RangeError: bad index");
  });
});
