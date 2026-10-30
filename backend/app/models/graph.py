"""The Link System: typed links between existing records, and Specialty Shelves.

A knowledge node is not a row of its own. It is a reference ``(kind, id)`` to a record that
already exists (a task, a memory, a file, ...), so nothing is copied and nothing drifts.

The relationships the app already stores (task relationships, memory links, memory-task and
file links, supersession) are read as typed links by the graph service. ``data_links`` holds
every other link. A ``data_links`` row for the same pair and relationship as a built-in link
overrides the built-in strength, confidence and status.

Endpoints are polymorphic, so they carry no foreign keys. Triggers created by the migration
delete a link when either endpoint is deleted.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.project import utc_now

NODE_KINDS = ("task", "memory", "file", "checkpoint", "milestone", "shelf")
LINK_CREATORS = ("user", "system", "inferred", "imported")
# "candidate": inferred, waiting to be confirmed, reinforced or used; never traversed.
# "rejected": a person or agent said no; kept so the same link is not inferred again.
LINK_STATUSES = (
    "active",
    "weak",
    "candidate",
    "disputed",
    "superseded",
    "archived",
    "rejected",
)
# Kinds of work a link can be more or less useful for (contextual weights).
OPERATIONS = ("coding", "debugging", "design", "testing", "art", "documentation", "planning")

# Stored relationship -> (inverse read from the other end, group).
# Only the stored direction is written; the inverse is derived, never stored.
RELATIONSHIPS: dict[str, tuple[str, str]] = {
    # structural
    "contains": ("part_of", "structural"),
    "belongs_to": ("has_member", "structural"),
    "implements": ("implemented_by", "structural"),
    "uses": ("used_by", "structural"),
    "depends_on": ("dependency_of", "structural"),
    "owns": ("owned_by", "structural"),
    "affects": ("affected_by", "structural"),
    # knowledge
    "relates_to": ("relates_to", "knowledge"),
    "explains": ("explained_by", "knowledge"),
    "supports": ("supported_by", "knowledge"),
    "contradicts": ("contradicts", "knowledge"),
    "refines": ("refined_by", "knowledge"),
    "extends": ("extended_by", "knowledge"),
    "references": ("referenced_by", "knowledge"),
    # temporal
    "preceded_by": ("followed_by", "temporal"),
    "supersedes": ("superseded_by", "temporal"),
    # development
    "created_by": ("created", "development"),
    "modified_by": ("modified", "development"),
    "resolved_by": ("resolves", "development"),
    "caused_by": ("causes", "development"),
    "blocked_by": ("blocks", "development"),
    "tested_by": ("tests", "development"),
    # learning
    "learned_from": ("taught", "learning"),
    "reinforces": ("reinforced_by", "learning"),
    "violates": ("violated_by", "learning"),
    "corrects": ("corrected_by", "learning"),
    "applies_to": ("governed_by", "learning"),
    "exception_to": ("has_exception", "learning"),
    # design
    "constrained_by": ("constrains", "design"),
    "inspired_by": ("inspired", "design"),
    "uses_style_of": ("style_used_by", "design"),
    "follows_convention": ("convention_followed_by", "design"),
    # negative: these keep dots apart. Retrieval never travels across them.
    "independent_of": ("independent_of", "negative"),
    "must_not_depend_on": ("must_not_be_depended_on_by", "negative"),
    "not_applicable_to": ("not_governed_by", "negative"),
    "excluded_from": ("excludes", "negative"),
}
# Inverse names accepted on input; they are stored as the forward type with endpoints swapped.
INVERSES = {inverse: forward for forward, (inverse, _) in RELATIONSHIPS.items()}
NEGATIVE = {name for name, (_, group) in RELATIONSHIPS.items() if group == "negative"}


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class DataLink(Base):
    __tablename__ = "data_links"
    __table_args__ = (
        CheckConstraint(_in("source_kind", NODE_KINDS), name="ck_data_links_source_kind"),
        CheckConstraint(_in("target_kind", NODE_KINDS), name="ck_data_links_target_kind"),
        CheckConstraint(_in("created_by", LINK_CREATORS), name="ck_data_links_created_by"),
        CheckConstraint(_in("status", LINK_STATUSES), name="ck_data_links_status"),
        CheckConstraint("strength >= 0 AND strength <= 1", name="ck_data_links_strength"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_data_links_confidence"),
        CheckConstraint(
            "NOT (source_kind = target_kind AND source_id = target_id)",
            name="ck_data_links_not_self",
        ),
        UniqueConstraint(
            "source_kind",
            "source_id",
            "target_kind",
            "target_id",
            "relationship",
            name="uq_data_links_edge",
        ),
        Index("ix_data_links_source", "project_id", "source_kind", "source_id"),
        Index("ix_data_links_target", "project_id", "target_kind", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    relationship: Mapped[str] = mapped_column(String(40), nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    actor: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    note: Mapped[str | None] = mapped_column(Text)
    # Operation -> strength for that kind of work, learned from retrieval feedback.
    contextual_weights: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Why the link exists: a list of {source, detail, at}, newest last, capped.
    provenance: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    traversal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reinforced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Shelf(Base):
    """A knowledge domain (Inventory, Save System, Testing...). Dormant until work activates it."""

    __tablename__ = "shelves"
    __table_args__ = (
        UniqueConstraint("project_id", "name_key", name="uq_shelves_project_name"),
        UniqueConstraint("id", "project_id", name="uq_shelves_id_project"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_shelves_not_self"),
        ForeignKeyConstraint(
            ["parent_id", "project_id"],
            ["shelves.id", "shelves.project_id"],
            name="fk_shelves_parent_same_project",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[str | None] = mapped_column(String(36))
    # Concept signals: comma-separated words that activate the shelf when a task mentions them.
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ShelfMember(Base):
    """A node on a shelf. A node may sit on many shelves; it still exists once."""

    __tablename__ = "shelf_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shelf_id", "project_id"],
            ["shelves.id", "shelves.project_id"],
            ondelete="CASCADE",
            name="fk_shelf_members_shelf_same_project",
        ),
        CheckConstraint(_in("node_kind", NODE_KINDS), name="ck_shelf_members_kind"),
        Index("ix_shelf_members_node", "node_kind", "node_id"),
    )

    shelf_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RetrievalSession(Base):
    """One context pack an agent asked for, kept so feedback can reinforce the paths it used."""

    __tablename__ = "retrieval_sessions"
    __table_args__ = (Index("ix_retrieval_sessions_task", "project_id", "task_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    query: Mapped[str | None] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(String(120))
    # [{kind, id, label, path: [[source_kind, source_id, target_kind, target_id, rel], ...]}]
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    outcome: Mapped[str | None] = mapped_column(String(20))
    tokens: Mapped[int | None] = mapped_column(Integer)  # size of the pack the agent got
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NodeUsefulness(Base):
    """How often a record helped, or was noise, for one kind of work (retrieval learning).

    Links learn which paths lead somewhere useful; this learns about the record itself, so a
    record that keeps coming in as noise ranks lower even when a search hit, not a link,
    brought it in."""

    __tablename__ = "node_usefulness"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    node_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation: Mapped[str] = mapped_column(String(20), primary_key=True)
    useful: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_useful: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GraphState(Base):
    """One row whose version database triggers bump on every change to knowledge (0014)."""

    __tablename__ = "graph_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_graph_state_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
