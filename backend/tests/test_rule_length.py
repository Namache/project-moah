"""Rules have a character cap on title and text; rules written before it stay as they are."""

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.models.memory import Memory
from app.models.project import Project
from app.services.brief import build_brief
from app.services.memory import RULE_BODY_MAX, RULE_TITLE_MAX

pytestmark = pytest.mark.anyio

LONG_TITLE = "t" * (RULE_TITLE_MAX + 1)
LONG_BODY = "b" * (RULE_BODY_MAX + 1)


async def make(client: AsyncClient, pid: str, **body: object):
    return await client.post(f"/api/projects/{pid}/memory", json={"type": "rule", **body})


async def project(client: AsyncClient, name: str) -> str:
    return (await client.post("/api/projects", json={"name": name})).json()["id"]


def stretch(database_url: str, memory_id: str, title: str, content: str) -> None:
    """Make a rule as long as one written before the cap existed."""
    with make_session_factory(make_engine(database_url))() as session:
        row = session.get(Memory, memory_id)
        row.title, row.content = title, content
        session.commit()


async def test_a_new_rule_over_the_cap_is_refused_with_advice(client: AsyncClient) -> None:
    pid = await project(client, "Lantern Keep")
    exact = await make(client, pid, title="t" * RULE_TITLE_MAX, content="b" * RULE_BODY_MAX)
    assert exact.status_code == 201, exact.text
    title = await make(client, pid, title=LONG_TITLE, content="Short.")
    assert title.status_code == 422
    assert f"at most {RULE_TITLE_MAX} characters" in title.json()["detail"]
    body = await make(client, pid, title="Short", content=LONG_BODY)
    assert body.status_code == 422 and "split it into two rules" in body.json()["detail"]
    # Other kinds of memory have no such cap.
    fact = await client.post(
        f"/api/projects/{pid}/memory",
        json={"type": "fact", "title": LONG_TITLE, "content": LONG_BODY},
    )
    assert fact.status_code == 201


async def test_an_older_long_rule_can_stay_or_shrink_but_not_grow(
    client: AsyncClient, database_url: str
) -> None:
    pid = await project(client, "Lantern Keep")
    rule = (await make(client, pid, title="Old rule", content="Short.")).json()
    stretch(database_url, rule["id"], LONG_TITLE, LONG_BODY)
    url = f"/api/projects/{pid}/memory/{rule['id']}"

    same = await client.patch(url, json={"title": LONG_TITLE, "content": LONG_BODY})
    assert same.status_code == 200, same.text
    other_field = await client.patch(url, json={"importance": "high"})
    assert other_field.status_code == 200
    shorter = await client.patch(url, json={"content": LONG_BODY[:-1]})
    assert shorter.status_code == 200 and len(shorter.json()["content"]) == RULE_BODY_MAX
    grown = await client.patch(url, json={"content": LONG_BODY})
    assert grown.status_code == 422  # it shrank to the cap, so the cap applies again
    assert (await client.get(url)).json()["title"] == LONG_TITLE  # nothing trimmed

    longer_title = await client.patch(url, json={"title": LONG_TITLE + "x"})
    assert longer_title.status_code == 422


async def test_replacing_an_older_long_rule_keeps_its_length_at_most(
    client: AsyncClient, database_url: str
) -> None:
    pid = await project(client, "Lantern Keep")
    rule = (await make(client, pid, title="Old rule", content="Short.")).json()
    stretch(database_url, rule["id"], "Old rule", LONG_BODY)
    url = f"/api/projects/{pid}/memory/{rule['id']}/supersede"
    grown = await client.post(url, json={"title": "Old rule", "content": LONG_BODY + "b"})
    assert grown.status_code == 422
    kept = await client.post(url, json={"title": "Old rule v2", "content": LONG_BODY})
    assert kept.status_code == 201, kept.text


async def test_an_agent_proposal_with_a_long_rule_is_refused_when_made(
    client: AsyncClient,
) -> None:
    pid = await project(client, "Lantern Keep")
    response = await client.post(
        f"/api/projects/{pid}/proposals",
        json={
            "proposal_type": "create_memory",
            "payload": {"type": "rule", "title": "Fine", "content": LONG_BODY},
            "reason": "Because",
            "agent": "codex",
        },
    )
    assert response.status_code == 422 and "at most" in response.text


async def test_the_brief_lists_every_rule_title_even_in_a_big_project(
    client: AsyncClient, database_url: str
) -> None:
    pid = await project(client, "Lantern Keep")
    titles = [f"Rule number {n}" for n in range(30)]
    for title in titles:
        assert (await make(client, pid, title=title, content="Do it.")).status_code == 201
    # More other records than the brief's general record limit, so rules can't be cut by it.
    with make_session_factory(make_engine(database_url))() as session:
        from app.schemas.memory import MemoryCreate
        from app.services.memory import MemoryService

        for n in range(320):
            MemoryService(session).create(pid, MemoryCreate(type="fact", title=f"Fact {n}"))
        brief = build_brief(session, session.get(Project, pid))
    for title in titles:
        assert f" {title}\n" in brief, title
