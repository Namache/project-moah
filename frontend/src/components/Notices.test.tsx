import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Notices, noticePlace } from "./Notices";
import { dismissNotice, notify } from "../lib/notify";

const view = { width: 1280, height: 800 };
const box = (top: number, bottom: number, left = 0, right = 1280) => ({ top, bottom, left, right });

describe("where notices sit", () => {
  it("stays in the bottom corner when nothing there needs to stay clear", () => {
    expect(noticePlace(view, [])).toEqual({ bottom: 16 });
    // A bar on the left half only, away from the notices' column.
    expect(noticePlace(view, [box(700, 800, 0, 600)])).toEqual({ bottom: 16 });
    // Hidden or scrolled away.
    expect(noticePlace(view, [box(0, 0, 0, 0), box(900, 980)])).toEqual({ bottom: 16 });
  });

  it("goes above the Review screen's action buttons", () => {
    // The comment box and its buttons fill the bottom 140 px across the panel.
    expect(noticePlace(view, [box(660, 800, 380, 1280)])).toEqual({ bottom: 152 });
    // The dictation dock and the bar: above the higher one.
    expect(noticePlace(view, [box(660, 800, 380, 1280), box(730, 780, 1100, 1260)])).toEqual({ bottom: 152 });
  });

  it("moves to the top corner when the bottom is mostly taken", () => {
    expect(noticePlace(view, [box(200, 800)])).toEqual({ top: 16 });
  });
});

describe("Notices", () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ""; });

  it("lifts a notice above a bar marked data-keep-clear", async () => {
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(800);
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1280);
    const { container } = render(<><div data-keep-clear="" data-testid="bar">Send back · Accept</div><Notices /></>);
    vi.spyOn(screen.getByTestId("bar"), "getBoundingClientRect").mockReturnValue({ top: 680, bottom: 800, left: 300, right: 1280, width: 980, height: 120, x: 300, y: 680, toJSON: () => ({}) });
    act(() => notify("Accepted. CAMP-001 is in Done."));
    expect(await screen.findByText("Accepted. CAMP-001 is in Done.")).toBeInTheDocument();
    const region = container.querySelector("[aria-live]") as HTMLElement;
    expect(region.style.bottom).toBe("132px");
    act(() => { for (let id = 0; id < 10; id += 1) dismissNotice(id); });
  });
});
