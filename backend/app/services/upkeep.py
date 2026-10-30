"""Keeping the brain healthy over time (Link System Phase 3).

- Weak-link decay: a link that no pack has used and no feedback has touched for a month starts
  to fade, a little each day, down to a floor. It is never deleted, only less likely to be
  followed. Links a person made do not fade; built-in links (task relationships, memory links)
  are facts and do not fade either.
- Guessed links nobody confirmed or used in two months are archived: observed, never useful.
- Shelves tidy themselves (HealthService.organize): unfiled clusters are filed, members and
  keywords are learned, noise leaves.
- The graph version: database triggers bump it whenever knowledge changes, so the path cache
  can tell in one query whether what it holds is still fresh.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.models.graph import DataLink, GraphState
from app.models.project import utc_now
from app.services.graph import WEAK_BELOW, GraphService

DECAY_GRACE = timedelta(days=30)  # idle this long before a link starts to fade
DECAY_PER_DAY = 0.002  # about 0.06 a month
DECAY_FLOOR = 0.1  # fading alone never takes a link lower than this
CANDIDATE_EXPIRY = timedelta(days=60)
DECAY_EVERY = timedelta(hours=20)
DECAY_SETTING = "link_decay_at"
MAX_CATCH_UP_DAYS = 90.0


def graph_version(session: Session) -> int:
    return session.scalar(select(GraphState.version).where(GraphState.id == 1)) or 0


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def last_touched(row: DataLink) -> datetime:
    """When the link last did something: made, used in a pack, or taught by feedback."""
    times = [_aware(t) for t in (row.created_at, row.last_used_at, row.last_reinforced_at)]
    return max(t for t in times if t is not None)


def decay_links(session: Session, now: datetime | None = None) -> dict:
    """Fade idle links and archive stale guesses. Runs at most about once a day; the first run
    only starts the clock. Returns what changed."""
    now = now or utc_now()
    setting = session.get(AppSetting, DECAY_SETTING)
    last = datetime.fromisoformat(setting.value) if setting and setting.value else None
    result = {"faded": 0, "weakened": 0, "archived": 0, "ran": False}
    if last is not None and now - last < DECAY_EVERY:
        return result
    if setting is None:
        setting = AppSetting(key=DECAY_SETTING)
        session.add(setting)
    setting.value = now.isoformat()
    setting.updated_at = now
    if last is None:
        session.commit()
        return result
    elapsed = min(MAX_CATCH_UP_DAYS, (now - last).total_seconds() / 86400)
    result["ran"] = True
    rows = session.scalars(
        select(DataLink).where(DataLink.status.in_(("active", "weak", "candidate")))
    ).all()
    for row in rows:
        idle = now - last_touched(row)
        if row.status == "candidate":
            if idle >= CANDIDATE_EXPIRY:
                row.status = "archived"
                row.updated_at = now
                GraphService._add_provenance(
                    row, "upkeep", f"archived: a guess nobody confirmed or used in {idle.days} days"
                )
                result["archived"] += 1
            continue
        if row.created_by == "user" or idle <= DECAY_GRACE:
            continue
        days = min(elapsed, (idle - DECAY_GRACE).total_seconds() / 86400)
        amount = DECAY_PER_DAY * days
        if row.strength <= DECAY_FLOOR or amount <= 0:
            continue
        row.strength = round(max(DECAY_FLOOR, row.strength - amount), 4)
        if row.contextual_weights:
            row.contextual_weights = {
                op: round(max(DECAY_FLOOR, w - amount), 4) if w > DECAY_FLOOR else w
                for op, w in row.contextual_weights.items()
            }
        result["faded"] += 1
        if row.status == "active" and row.strength < WEAK_BELOW:
            row.status = "weak"
            GraphService._add_provenance(
                row, "upkeep", f"faded to weak: not used for {idle.days} days"
            )
            result["weakened"] += 1
        row.updated_at = now
    session.commit()
    # Phase 4: once a day, look for links nobody made. Never fails the upkeep itself.
    from app.models.project import Project
    from app.services.discovery import DiscoveryService

    result["missing"] = 0
    for project_id in session.scalars(select(Project.id).where(Project.status != "archived")):
        try:
            result["missing"] += DiscoveryService(session).find_missing(project_id)["missing"]
        except Exception:  # noqa: BLE001 - logged; decay already saved
            session.rollback()
            logging.getLogger(__name__).exception("Missing-link discovery failed")
    from app.services.health import HealthService

    result["organized"] = 0
    for project_id in session.scalars(select(Project.id).where(Project.status != "archived")):
        try:
            result["organized"] += sum(HealthService(session).organize(project_id).values())
        except Exception:  # noqa: BLE001 - logged; decay already saved
            session.rollback()
            logging.getLogger(__name__).exception("Shelf upkeep failed")
    try:
        HealthService(session).snapshot_clusters()
    except Exception:  # noqa: BLE001 - logged; decay already saved
        session.rollback()
        logging.getLogger(__name__).exception("Cluster snapshot failed")
    return result
