from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.graph import ShelfActivation

DetailLevel = Literal["minimal", "balanced", "detailed"]


class ContextItem(BaseModel):
    """One piece of the pack. Shown in the inspector so a person sees exactly what is sent."""

    section: str
    kind: str
    ref: str | None
    title: str
    tokens: int
    reason: str
    # How strongly the Link System connected this record to the work, 0 to 1. None when it
    # came in another way (the task itself, a checkpoint, a global rule).
    confidence: float | None = None
    # True when this agent session was already sent the item, unchanged, by an earlier pack:
    # it still applies but is not repeated in the text.
    repeat: bool = False


class ExcludedItem(BaseModel):
    """A record that came close but was left out, and why. Titles only, never content."""

    title: str
    reason: str
    confidence: float | None = None


class ContextSection(BaseModel):
    key: str
    title: str
    tokens: int
    items: int


class ContextPack(BaseModel):
    project_id: str
    project_name: str
    task: str | None
    # How the pack's task was chosen: given (task=), session (the agent session's own task),
    # focus (the project's current focus) or inferred (the request names it, or plainly matches
    # the one task in motion). None for a project overview.
    task_source: Literal["given", "session", "focus", "inferred"] | None = None
    detail_level: DetailLevel
    budget: int
    estimated_tokens: int
    over_budget: bool
    text: str
    sections: list[ContextSection]
    items: list[ContextItem]
    # Counts of records left out, by reason. Never contains their content.
    omitted: dict[str, int]
    warnings: list[str]
    # Every shelf of the project with how strongly this work woke it. Empty without shelves.
    shelves: list[ShelfActivation] = Field(default_factory=list)
    # The kind of work detected (or given): debugging, design, coding... Links can be
    # stronger for some kinds of work than others.
    operation: str = "coding"
    # Set when an agent's pack was recorded, so it can report back what helped.
    retrieval_id: str | None = None
    excluded: list[ExcludedItem] = Field(default_factory=list)
    # The start-up brief an agent gets for this project at the start of every session, in
    # estimated tokens. Set only for the app's agent view of a pack (``agent=true``).
    brief_tokens: int | None = None
    # A repeat request in one agent session: the earlier pack (R-...) whose items were not sent
    # again. None for a first pack or a preview.
    repeat_of: str | None = None
