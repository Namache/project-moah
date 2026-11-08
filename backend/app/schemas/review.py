from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import UtcModel

ReviewStatus = Literal["pending", "accepted", "rejected", "answered", "replaced"]
ReviewKind = Literal["work", "question"]
ReviewFileKind = Literal["screenshot", "feedback"]
Verdict = Literal["accept", "reject", "answer", "approve"]
FollowUpColumn = Literal["todo", "backlog"]

SUMMARY_LIMIT = 2000
ITEM_LIMIT = 500
ITEMS_LIMIT = 40
DETAILS_LIMIT = 40_000
OPTIONS_LIMIT = 6
OPTION_LIMIT = 200


def _clean_items(items: list[str]) -> list[str]:
    return [" ".join(item.split()) for item in items if item and item.strip()]


class ReviewSubmit(BaseModel):
    """What an agent writes when it finishes a task."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=SUMMARY_LIMIT)
    done: list[str] = Field(min_length=1, max_length=ITEMS_LIMIT)
    not_done: list[str] = Field(default_factory=list, max_length=ITEMS_LIMIT)
    how_to_check: str | None = Field(default=None, max_length=SUMMARY_LIMIT * 2)
    details: str | None = Field(default=None, max_length=DETAILS_LIMIT)

    @field_validator("summary")
    @classmethod
    def summary_has_words(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write a short summary of what was done")
        return value.strip()

    @field_validator("done", "not_done")
    @classmethod
    def items_are_short(cls, items: list[str]) -> list[str]:
        cleaned = _clean_items(items)
        if any(len(item) > ITEM_LIMIT for item in cleaned):
            raise ValueError(f"Keep each item under {ITEM_LIMIT} characters; put more in details")
        return cleaned

    @field_validator("how_to_check", "details")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class AskPerson(BaseModel):
    """What an agent writes when it cannot go on without the person's answer."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=SUMMARY_LIMIT)
    context: str | None = Field(default=None, max_length=DETAILS_LIMIT)
    options: list[str] = Field(default_factory=list, max_length=OPTIONS_LIMIT)

    @field_validator("question")
    @classmethod
    def question_has_words(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write the question for the person")
        return value.strip()

    @field_validator("options")
    @classmethod
    def options_are_short(cls, items: list[str]) -> list[str]:
        cleaned = _clean_items(items)
        if any(len(item) > OPTION_LIMIT for item in cleaned):
            raise ValueError(f"Keep each option under {OPTION_LIMIT} characters")
        return cleaned

    @field_validator("context")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CriterionTick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=36)
    met: bool


class ReviewDecision(BaseModel):
    """accept or reject finished work, or answer an agent's question (approve: answer "go on"
    without words, for a question a checkpoint opened). With accept, criteria
    records which acceptance criteria are met and follow_ups become new tasks; with reject, only
    the criteria marked not met are recorded."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    comment: str | None = Field(default=None, max_length=20_000)
    criteria: list[CriterionTick] = Field(default_factory=list, max_length=100)
    follow_ups: list[str] = Field(default_factory=list, max_length=ITEMS_LIMIT * 2)
    follow_up_status: FollowUpColumn = "todo"

    @field_validator("follow_ups")
    @classmethod
    def follow_ups_are_lines(cls, items: list[str]) -> list[str]:
        return _clean_items(items)


class ReviewReopen(BaseModel):
    """Taking back an acceptance: what is wrong, for the next agent."""

    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=1, max_length=20_000)

    @field_validator("comment")
    @classmethod
    def comment_has_words(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Say what is wrong, so the agent knows what to fix")
        return value.strip()


class FollowUpCreate(BaseModel):
    """Lines of a review (what was not done, an unmet criterion) to make into tasks."""

    model_config = ConfigDict(extra="forbid")

    items: list[str] = Field(min_length=1, max_length=ITEMS_LIMIT * 2)
    status: FollowUpColumn = "todo"

    @field_validator("items")
    @classmethod
    def items_are_lines(cls, items: list[str]) -> list[str]:
        cleaned = _clean_items(items)
        if not cleaned:
            raise ValueError("Give at least one line to make into a task")
        return cleaned


class CheckpointNote(UtcModel):
    """A checkpoint a drafted review was picked from, shown whole under the review."""

    title: str
    created_at: datetime
    agent: str | None
    summary: str
    completed_work: str
    remaining_work: str
    problems: str
    next_steps: str
    # False when the checkpoint was filed under another task and only names this one.
    filed_here: bool


class FollowUp(BaseModel):
    """A task the person made from a line of the review."""

    text: str
    task_id: str
    task_ref: str
    task_status: str


class ReviewFileRead(UtcModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: ReviewFileKind
    filename: str
    media_type: str
    size_bytes: int
    width: int | None
    height: int | None
    caption: str | None
    created_by: str | None
    created_at: datetime


class ReviewRound(UtcModel):
    """One round of a task's review: the agent's account and the person's answer to it."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None  # None for a review Moah shows from the checkpoint but has not stored yet
    round: int
    agent: str
    kind: ReviewKind = "work"
    status: ReviewStatus
    summary: str  # for a question, the question
    done: list[str]
    not_done: list[str]
    how_to_check: str | None
    details: str | None
    options: list[str] = Field(default_factory=list)
    generated: bool
    created_at: datetime
    reviewed_at: datetime | None
    comment: str | None
    moved_to: str | None = None
    follow_ups: list[FollowUp] = Field(default_factory=list)
    screenshots: list[ReviewFileRead] = Field(default_factory=list)
    feedback: list[ReviewFileRead] = Field(default_factory=list)
    # For a review drafted from checkpoints (generated): what the agent planned next, the
    # checkpoints it came from, and whether lines about other tasks were left out.
    next_steps: list[str] = Field(default_factory=list)
    notes: list[CheckpointNote] = Field(default_factory=list)
    left_out: bool = False
    # A question Moah opened from the agent's checkpoint that waited for the person.
    from_note: bool = False


class ReviewCriterion(BaseModel):
    id: str
    description: str
    is_completed: bool


class ReviewDetail(UtcModel):
    """Everything the Review screen shows for one task."""

    project_id: str
    project_name: str
    project_slug: str
    task_id: str
    task_ref: str
    task_title: str
    task_status: str
    task_description: str | None
    criteria: list[ReviewCriterion]
    current: ReviewRound
    earlier: list[ReviewRound]


class ReviewItem(UtcModel):
    """One line of the Review timeline: a task's review, or an agent's suggestion."""

    kind: Literal["task", "suggestion"]
    key: str  # unique in the timeline, used to select it
    project_id: str
    project_name: str
    project_icon: str | None
    project_accent: str | None
    ref: str  # PROJ-12 for a task, PROP-4 for a suggestion
    title: str
    summary: str
    agent: str
    done_at: datetime
    reviewed_at: datetime | None
    verdict: Literal["accepted", "rejected", "answered"] | None
    question: bool = False  # an agent's question waiting for (or given) the person's answer
    # The task's board column now (backlog … completed, archived); None for a suggestion.
    task_status: str | None = None
    moved_to: str | None = None  # decided by moving the task on the board, to this column
    round: int = 1
    screenshots: int = 0
    generated: bool = False
    # Finished work one agent note covered together ("Camp batch: CAMP-4, 5, 6"): the note's
    # id, and its title, so Review can show and accept the batch as one.
    batch: str | None = None
    batch_title: str | None = None


class ReviewTimeline(BaseModel):
    waiting: list[ReviewItem]
    reviewed: list[ReviewItem]


class PendingReviewItem(BaseModel):
    key: str
    kind: Literal["task", "suggestion"]
    project_name: str
    agent: str
    title: str
    question: bool = False


class PendingReviews(BaseModel):
    """How much waits for the person, for badges and the desktop app's notifications."""

    total: int
    by_project: dict[str, int]
    newest: list[PendingReviewItem] = Field(default_factory=list)
