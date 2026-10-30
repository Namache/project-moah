"""Proposal review routes. Accepting and rejecting are human actions."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.proposal import (
    AcceptAllResult,
    PendingCount,
    ProposalAccept,
    ProposalCreate,
    ProposalRead,
    ProposalReject,
    ProposalStatus,
)
from app.services.proposals import ProposalService

router = APIRouter(prefix="/api", tags=["proposals"])
DatabaseSession = Annotated[Session, Depends(get_session)]
P = "/projects/{project_id}/proposals"


@router.get("/proposals/pending", response_model=PendingCount)
def pending_proposals(session: DatabaseSession) -> PendingCount:
    return ProposalService(session).pending_counts()


@router.get(P, response_model=list[ProposalRead])
def list_proposals(
    project_id: str,
    session: DatabaseSession,
    status_filter: Annotated[list[ProposalStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProposalRead]:
    return ProposalService(session).list(
        project_id, statuses=status_filter, limit=limit, offset=offset
    )


@router.post(P, response_model=ProposalRead, status_code=status.HTTP_201_CREATED)
def create_proposal(
    project_id: str, payload: ProposalCreate, session: DatabaseSession
) -> ProposalRead:
    return ProposalService(session).create(project_id, payload)


@router.post(P + "/accept-all", response_model=AcceptAllResult)
def accept_all(project_id: str, session: DatabaseSession) -> AcceptAllResult:
    return ProposalService(session).accept_all(project_id)


@router.get(P + "/{ref}", response_model=ProposalRead)
def get_proposal(project_id: str, ref: str, session: DatabaseSession) -> ProposalRead:
    return ProposalService(session).read(project_id, ref)


@router.post(P + "/{ref}/accept", response_model=ProposalRead)
def accept_proposal(
    project_id: str, ref: str, session: DatabaseSession, payload: ProposalAccept | None = None
) -> ProposalRead:
    return ProposalService(session).accept(project_id, ref, payload)


@router.post(P + "/{ref}/reject", response_model=ProposalRead)
def reject_proposal(
    project_id: str, ref: str, session: DatabaseSession, payload: ProposalReject | None = None
) -> ProposalRead:
    return ProposalService(session).reject(project_id, ref, payload.note if payload else None)
