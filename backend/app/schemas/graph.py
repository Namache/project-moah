from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import UtcModel, clean_optional

NodeKind = Literal["task", "memory", "file", "checkpoint", "milestone", "shelf"]
LinkStatus = Literal[
    "active", "weak", "candidate", "disputed", "superseded", "archived", "rejected"
]


class NodeRead(BaseModel):
    kind: NodeKind
    id: str
    label: str
    title: str
    subtype: str | None = None
    status: str | None = None


class LinkRead(UtcModel):
    """A link as seen from one node: ``relationship`` reads from that node to ``node``."""

    id: str | None  # None for built-in links that have no stored override
    relationship: str
    stored_relationship: str
    direction: Literal["outgoing", "incoming"]
    group: str
    node: NodeRead
    strength: float
    confidence: float
    status: LinkStatus
    origin: str
    created_by: str
    note: str | None = None
    # Why the link exists, oldest first: [{source, detail, at?}].
    provenance: list[dict] = Field(default_factory=list)
    contextual_weights: dict[str, float] = Field(default_factory=dict)
    success_count: int = 0
    failure_count: int = 0


class NodeLinks(BaseModel):
    node: NodeRead
    links: list[LinkRead]


class LinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=1100)
    relationship: str = Field(min_length=1, max_length=40)
    target: str = Field(min_length=1, max_length=1100)
    strength: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: LinkStatus | None = None
    note: str | None = Field(default=None, max_length=1000)


class RelationshipType(BaseModel):
    name: str
    inverse: str
    group: str


class ShelfFields(BaseModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned or len(cleaned) > 80:
            raise ValueError("shelf names must contain 1 to 80 characters")
        if ">" in cleaned:
            raise ValueError("shelf names cannot contain >, which separates shelves in a path")
        return cleaned

    @field_validator("description", check_fields=False)
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return clean_optional(value)

    @field_validator("keywords", check_fields=False)
    @classmethod
    def clean_keywords(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        out: list[str] = []
        for item in value:
            word = " ".join(item.split()).casefold()
            if word and word not in out:
                out.append(word[:60])
        return out[:40]


class ShelfCreate(ShelfFields):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    parent: str | None = None
    keywords: list[str] = Field(default_factory=list)


class ShelfUpdate(ShelfFields):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    parent: str | None = None
    keywords: list[str] | None = None


class ShelfRead(UtcModel):
    id: str
    name: str
    description: str | None
    parent_id: str | None
    keywords: list[str]
    member_count: int


class ShelfMemberChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str = Field(min_length=1, max_length=1100)


class ShelfDetail(ShelfRead):
    members: list[NodeRead]


class ShelfActivation(BaseModel):
    id: str
    name: str
    activation: float
    active: bool
    reason: str
    path: str = ""  # the shelf under its parents: "Gameplay > Combat > Boss"
    parent_id: str | None = None
    scope: str = "project"  # "global" for a Global shelf woken in a project's pack


class CandidateLink(BaseModel):
    link_id: str
    source: NodeRead
    relationship: str
    target: NodeRead
    confidence: float
    why: str


class OrphanRead(BaseModel):
    id: str
    type: str
    title: str
    node: str


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str | None = Field(default=None, max_length=1100)
