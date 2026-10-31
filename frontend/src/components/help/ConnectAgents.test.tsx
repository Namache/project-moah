import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { systemApi } from "../../api/system";
import { ConnectAgents, ConnectByCommand } from "./ConnectAgents";

describe("connect button", () => {
  afterEach(cleanup);

  it("says what happened to each agent", async () => {
    vi.spyOn(systemApi, "connectAgents").mockResolvedValue({ results: [
      { agent: "claude", status: "connected", detail: "" },
      { agent: "codex", status: "failed", detail: "Access is denied" },
    ] });
    render(<ConnectAgents />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Claude Code and Codex" }));
    expect(await screen.findByText(/Claude Code is connected. Restart it/)).toBeInTheDocument();
    expect(screen.getByText("Codex could not be connected: Access is denied")).toBeInTheDocument();
  });

  it("gives the Flatpak one command that opens the home folder for that run only", () => {
    render(<ConnectByCommand />);
    expect(screen.getByText("flatpak run --filesystem=home --command=project-moah-mcp io.github.projectbrain.ProjectBrain --connect")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect Claude Code and Codex" })).toBeNull();
  });

  it("offers another try when the app can't reach its service", async () => {
    vi.spyOn(systemApi, "connectAgents").mockRejectedValue(new Error("offline"));
    render(<ConnectAgents />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Claude Code and Codex" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please try again");
    expect(screen.getByRole("button", { name: "Connect Claude Code and Codex" })).toBeEnabled();
  });
});
