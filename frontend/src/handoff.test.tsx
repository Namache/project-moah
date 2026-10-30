import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HandoffButton } from "./components/handoff/HandoffButton";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const renderButton = () => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><HandoffButton projectId="p1" task="CAMP-001" /></MemoryRouter></QueryClientProvider>);

describe("handoff button", () => {
  it("builds the handoff for the task, copies it, and offers a preview", async () => {
    const fetchMock = vi.fn(async () => Response.json({ project_id: "p1", task: "CAMP-001", text: "Handoff from Project Moah.\n\nTASK\nCAMP-001", estimated_tokens: 12, warnings: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const write = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
    renderButton();
    await user.click(screen.getByRole("button", { name: "Copy handoff" }));
    expect(await screen.findByRole("button", { name: "Handoff copied" })).toBeInTheDocument();
    expect((fetchMock.mock.calls as unknown[][])[0][0]).toBe("/api/projects/p1/handoff?task=CAMP-001");
    expect(write).toHaveBeenCalledWith("Handoff from Project Moah.\n\nTASK\nCAMP-001");
    expect(screen.getByLabelText("Handoff preview", { selector: "pre" })).toHaveTextContent("CAMP-001");
  });

  it("shows the text when the clipboard is blocked, and reports build failures", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ project_id: "p1", task: null, text: "NOTE", estimated_tokens: 1, warnings: [] })));
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => { throw new Error("blocked"); } }, configurable: true });
    renderButton();
    await user.click(screen.getByRole("button", { name: "Copy handoff" }));
    expect(await screen.findByText(/Copying was blocked/)).toBeInTheDocument();
    cleanup();
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "Task CAMP-001 was not found in this project" }, { status: 404 })));
    renderButton();
    await user.click(screen.getByRole("button", { name: "Copy handoff" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("was not found");
  });
});
