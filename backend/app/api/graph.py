"""Link System routes: typed links between records, and Specialty Shelves."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.graph import (
    CandidateLink,
    DiscoverRequest,
    LinkCreate,
    LinkRead,
    NodeLinks,
    OrphanRead,
    RelationshipType,
    ShelfActivation,
    ShelfCreate,
    ShelfDetail,
    ShelfMemberChange,
    ShelfRead,
    ShelfUpdate,
)
from app.services.discovery import DiscoveryService
from app.services.graph import GraphService
from app.services.health import HealthService
from app.services.shelves import ShelfService
from app.services.upkeep import decay_links, graph_version

router = APIRouter(prefix="/api/projects/{project_id}", tags=["links"])
workspace_router = APIRouter(prefix="/api", tags=["links"])
DatabaseSession = Annotated[Session, Depends(get_session)]
NodeRef = Annotated[str, Query(min_length=1, max_length=1100)]
SuggestionKey = Annotated[str, Body(embed=True, min_length=3, max_length=200)]


@router.get("/links/relationships", response_model=list[RelationshipType])
def relationship_types(project_id: str) -> list[RelationshipType]:
    return GraphService.relationship_types()


@router.get("/links", response_model=NodeLinks)
def node_links(project_id: str, node: NodeRef, session: DatabaseSession) -> NodeLinks:
    return GraphService(session).node_links(project_id, node)


@router.post("/links", response_model=LinkRead, status_code=status.HTTP_201_CREATED)
def create_link(project_id: str, payload: LinkCreate, session: DatabaseSession) -> LinkRead:
    service = GraphService(session)
    edge = service.link(
        project_id,
        payload.source,
        payload.relationship,
        payload.target,
        strength=payload.strength,
        confidence=payload.confidence,
        status=payload.status,
        note=payload.note,
    )
    return service.link_read(project_id, edge)


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(project_id: str, link_id: str, session: DatabaseSession) -> Response:
    GraphService(session).unlink(project_id, link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shelves", response_model=list[ShelfRead])
def list_shelves(project_id: str, session: DatabaseSession) -> list[ShelfRead]:
    return ShelfService(session).list(project_id)


@router.post("/shelves", response_model=ShelfRead, status_code=status.HTTP_201_CREATED)
def create_shelf(project_id: str, payload: ShelfCreate, session: DatabaseSession) -> ShelfRead:
    return ShelfService(session).create(project_id, payload)


@router.get("/shelves/activation", response_model=list[ShelfActivation])
def shelf_activation(
    project_id: str,
    session: DatabaseSession,
    text: Annotated[str, Query(max_length=2000)] = "",
    task: Annotated[str | None, Query(max_length=64)] = None,
) -> list[ShelfActivation]:
    """Which shelves a piece of work would wake. For trying keywords out."""
    from app.services.context import ContextService

    return ContextService(session).shelf_activation(project_id, task=task, query=text)


@router.get("/shelves/{shelf}", response_model=ShelfDetail)
def get_shelf(project_id: str, shelf: str, session: DatabaseSession) -> ShelfDetail:
    return ShelfService(session).detail(project_id, shelf)


@router.patch("/shelves/{shelf}", response_model=ShelfRead)
def update_shelf(
    project_id: str, shelf: str, payload: ShelfUpdate, session: DatabaseSession
) -> ShelfRead:
    return ShelfService(session).update(project_id, shelf, payload)


@router.delete("/shelves/{shelf}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shelf(project_id: str, shelf: str, session: DatabaseSession) -> Response:
    ShelfService(session).delete(project_id, shelf)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/shelves/{shelf}/members", response_model=ShelfDetail)
def add_shelf_member(
    project_id: str, shelf: str, payload: ShelfMemberChange, session: DatabaseSession
) -> ShelfDetail:
    service = ShelfService(session)
    service.add_member(project_id, shelf, payload.node)
    return service.detail(project_id, shelf)


@router.delete("/shelves/{shelf}/members", response_model=ShelfDetail)
def remove_shelf_member(
    project_id: str, shelf: str, node: NodeRef, session: DatabaseSession
) -> ShelfDetail:
    service = ShelfService(session)
    service.remove_member(project_id, shelf, node)
    return service.detail(project_id, shelf)


@router.post("/links/{link_id}/confirm", response_model=LinkRead)
def confirm_link(project_id: str, link_id: str, session: DatabaseSession) -> LinkRead:
    service = GraphService(session)
    return service.link_read(project_id, service.confirm(project_id, link_id))


@router.post("/links/{link_id}/reject", response_model=LinkRead)
def reject_link(project_id: str, link_id: str, session: DatabaseSession) -> LinkRead:
    service = GraphService(session)
    return service.link_read(project_id, service.reject(project_id, link_id))


@router.get("/links/candidates", response_model=list[CandidateLink])
def candidate_links(project_id: str, session: DatabaseSession) -> list[dict]:
    return DiscoveryService(session).candidates(project_id)


@router.get("/links/orphans", response_model=list[OrphanRead])
def orphans(project_id: str, session: DatabaseSession) -> list[dict]:
    return DiscoveryService(session).orphans(project_id)


@router.post("/links/discover")
def discover_links(project_id: str, payload: DiscoverRequest, session: DatabaseSession) -> dict:
    """Look for links for one record, or across the project when no node is given."""
    service = DiscoveryService(session)
    if payload.node:
        return service.discover(project_id, payload.node, actor="human")
    return service.discover_all(project_id)


@router.get("/graph")
def graph_view(project_id: str, session: DatabaseSession) -> dict:
    """Every visible record and the links between them, for the Brain View."""
    return GraphService(session).view(project_id)


@router.get("/graph/activation")
def graph_activation(
    project_id: str,
    session: DatabaseSession,
    task: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=2000)] = None,
) -> dict:
    """What a context pack for this work would light up: node scores, the paths that carried
    them, and shelf activation. Nothing is recorded."""
    from app.services.context import ContextService

    context = ContextService(session)
    pack = context.build(project_id, task=task, query=q, detail="detailed")
    graph = context.graph_context
    kept = {f"{i.kind.split(':')[0]}:{i.ref}" for i in pack.items if i.ref and i.kind != "shelves"}
    return {
        "operation": pack.operation,
        "nodes": {f"{n.kind}:{n.id}": round(p.score, 3) for n, p in graph.paths.items()},
        "included": sorted(kept),
        "paths": [
            [f"{h[0].kind}:{h[0].id}" for h in p.hops] + [f"{n.kind}:{n.id}"]
            for n, p in graph.paths.items()
            if p.hops and f"{n.kind}:{n.id}" in kept
        ],
        "shelves": {a.id: a.activation for a in pack.shelves},
    }


@workspace_router.get("/brain")
def brain_view(session: DatabaseSession) -> dict:
    """The whole workspace as one brain, for the Brain View: every project that isn't
    archived and the global rules, with their records, links and shelves."""
    return GraphService(session).view_all()


@workspace_router.get("/brain/version")
def brain_version(session: DatabaseSession) -> dict:
    """A number that grows whenever knowledge changes, in the app or through an agent's MCP
    server. The Brain View asks for it every few seconds and reloads only when it moves."""
    return {"version": graph_version(session)}


@workspace_router.get("/brain/health")
def brain_health(session: DatabaseSession) -> dict:
    """Health of every project's graph, knowledge clusters and shelf suggestions. Idle links
    fade here too (at most once a day), so upkeep runs even when no agent is connected."""
    decay_links(session)
    return HealthService(session).workspace()


@router.get("/graph/health")
def graph_health(project_id: str, session: DatabaseSession) -> dict:
    service = HealthService(session)
    return {**service.project(project_id), "suggestions": service.suggestions(project_id)}


@router.post("/shelf-suggestions/accept")
def accept_shelf_suggestion(project_id: str, key: SuggestionKey, session: DatabaseSession) -> dict:
    return HealthService(session).accept(project_id, key)


@router.post("/shelf-suggestions/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_shelf_suggestion(
    project_id: str, key: SuggestionKey, session: DatabaseSession
) -> Response:
    HealthService(session).dismiss(project_id, key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
