import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../types/task";
import { TaskBoard } from "./TaskBoard";

const task: TaskSummary = {
  id: "task-1", project_id: "project-1", milestone_id: null,
  human_id: "CAMP-001", title: "Camp Population Capacity", status: "in_progress",
  priority: "high", next_action: null, sort_order: 0, criteria_total: 0,
  criteria_completed: 0, tags: [], is_focus: false, is_blocked_by_open_dependency: false,
};

afterEach(cleanup);

describe("task board card actions", () => {
  it("moves a task directly to a chosen column without opening its detail", async () => {
    const user = userEvent.setup();
    const onMove = vi.fn();
    const onOpen = vi.fn();
    render(<TaskBoard tasks={[task]} selectedId={null} onOpen={onOpen} onMove={onMove} />);

    await user.click(screen.getByRole("button", { name: "Move CAMP-001 to another status" }));
    const choices = screen.getByRole("group", { name: "Move CAMP-001 to status" });
    expect(within(choices).queryByRole("button", { name: "In Progress" })).not.toBeInTheDocument();
    await user.click(within(choices).getByRole("button", { name: "To do" }));

    expect(onMove).toHaveBeenCalledExactlyOnceWith("task-1", "todo", Number.MAX_SAFE_INTEGER);
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.queryByRole("group", { name: "Move CAMP-001 to status" })).not.toBeInTheDocument();
  });

  it("lets a keyboard user dismiss the status choices with Escape", async () => {
    const user = userEvent.setup();
    render(<TaskBoard tasks={[task]} selectedId={null} onOpen={vi.fn()} onMove={vi.fn()} />);

    const moveButton = screen.getByRole("button", { name: "Move CAMP-001 to another status" });
    moveButton.focus();
    await user.keyboard("{Enter}");
    expect(moveButton).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Tab}{Escape}");

    expect(moveButton).toHaveAttribute("aria-expanded", "false");
    expect(moveButton).toHaveFocus();
  });

  it("explains keyboard dragging on each card", () => {
    render(<TaskBoard tasks={[task]} selectedId={null} onOpen={vi.fn()} onMove={vi.fn()} />);
    expect(screen.getByRole("button", { name: /CAMP-001 Camp Population Capacity/ })).toHaveAttribute("title", expect.stringContaining("press Space to pick up"));
    expect(screen.getByText(/focus a card and press Space/)).toBeInTheDocument();
  });

  it("opens tasks without offering move controls when the project is archived", async () => {
    const onOpen = vi.fn();
    const onMove = vi.fn();
    render(<TaskBoard tasks={[task]} selectedId={null} onOpen={onOpen} onMove={onMove} readOnly />);

    expect(screen.queryByRole("button", { name: "Move CAMP-001 to another status" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /CAMP-001 Camp Population Capacity/ }));
    expect(onOpen).toHaveBeenCalledWith(task);
    expect(onMove).not.toHaveBeenCalled();
  });
});
