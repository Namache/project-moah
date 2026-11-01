"""Predictable packs (PROJ-014) and repeat packs that send only what is new (PROJ-015)."""

import pytest
from httpx import AsyncClient

from app.mcp.linking import IDLE_SECONDS, SessionPacks
from app.services.context import ContextService, SentRecords, mark_context_reset
from tests.retrieval_bench import seed

pytestmark = pytest.mark.anyio


def factory(client: AsyncClient):
    return client._transport.app.state.session_factory  # type: ignore[attr-defined]


async def test_agent_packs_are_the_same_for_the_same_request(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PROJECT_BRAIN_EXPLORE", raising=False)
    pid, tasks, _ = await seed(client)
    settings = (await client.get("/api/settings/agents")).json()
    assert settings["explore_packs"] is False
    with factory(client)() as session:
        packs = []
        for _ in range(2):
            service = ContextService(session)
            packs.append(service.build(pid, task=tasks["save"], record_for="claude"))
            assert service.sample is None  # no Thompson sampling unless switched on
        first, second = packs
        assert first.text == second.text
        assert [(i.ref, i.section) for i in first.items] == [
            (i.ref, i.section) for i in second.items
        ]
        assert first.retrieval_id != second.retrieval_id  # both still recorded for feedback


async def test_the_explore_setting_turns_sampling_on(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PROJECT_BRAIN_EXPLORE", raising=False)
    pid, tasks, _ = await seed(client)
    response = await client.patch("/api/settings/agents", json={"explore_packs": True})
    assert response.status_code == 200 and response.json()["explore_packs"] is True
    with factory(client)() as session:
        agent = ContextService(session)
        agent.build(pid, task=tasks["save"], record_for="claude")
        assert agent.sample is not None
        preview = ContextService(session)
        preview.build(pid, task=tasks["save"])
        assert preview.sample is None  # the app's previews never explore
        monkeypatch.setenv("PROJECT_BRAIN_EXPLORE", "0")
        trial = ContextService(session)
        trial.build(pid, task=tasks["save"], record_for="claude")
        assert trial.sample is None


async def test_a_repeat_pack_names_what_was_sent_and_sends_only_changes(
    client: AsyncClient,
) -> None:
    pid, tasks, memory = await seed(client)
    sent = SentRecords()

    def build(session, **kwargs):
        return ContextService(session).build(
            pid, task=tasks["save"], record_for="claude", global_rules=False, sent=sent, **kwargs
        )

    with factory(client)() as session:
        first = build(session)
        assert first.repeat_of is None and "BUG-001" in first.text
        assert not any(i.repeat for i in first.items)

        again = build(session)
        short = first.retrieval_id[:8]
        assert again.text == (
            f"Nothing new since R-{short}. Still applies: BUG-001, RULE-001, WARN-001."
        )
        assert again.retrieval_id is None  # nothing to learn from, no feedback asked
        assert again.repeat_of == short
        assert all(i.repeat for i in again.items)
        assert again.estimated_tokens < 40 < first.estimated_tokens

    # An edited record counts as new; the rest is only named.
    response = await client.patch(
        f"/api/projects/{pid}/memory/{memory['w_save']}",
        json={"content": "Two writers corrupt the file. Autosave holds a lock now."},
    )
    assert response.status_code == 200, response.text
    with factory(client)() as session:
        changed = build(session)
        assert changed.text.startswith(
            f"Already sent since R-{short}, unchanged, still applies: BUG-001, RULE-001."
        )
        assert "NEW OR CHANGED" in changed.text and "Autosave holds a lock now" in changed.text
        assert "Loading them crashes" not in changed.text  # BUG-001 is not repeated
        assert changed.retrieval_id is not None
        assert [i.title for i in changed.items if not i.repeat] == [
            "Never write saves while autosave runs"
        ]
        # The next repeat counts from the pack that sent the change.
        assert build(session).text.startswith(f"Nothing new since R-{changed.retrieval_id[:8]}.")

        # Previews and packs without a session memory are unchanged.
        preview = ContextService(session).build(pid, task=tasks["save"], global_rules=False)
        assert "Loading them crashes" in preview.text and "Nothing new" not in preview.text


async def test_records_already_sent_cost_no_budget(client: AsyncClient) -> None:
    pid, tasks, _ = await seed(client)
    sent = SentRecords()
    with factory(client)() as session:
        full = ContextService(session).build(pid, task=tasks["save"], global_rules=False)
        tight = ContextService(session).build(
            pid, task=tasks["save"], global_rules=False, budget=100, sent=sent, record_for="claude"
        )
        missing = {i.ref for i in full.items} - {i.ref for i in tight.items}
        assert missing, "the tight budget should leave something out"
        follow_up = ContextService(session).build(
            pid, task=tasks["save"], global_rules=False, budget=100, sent=sent, record_for="claude"
        )
        # What was sent is named for free, so the budget goes to what did not fit before.
        assert missing & {i.ref for i in follow_up.items if not i.repeat}


async def test_the_session_forgets_what_it_sent_when_context_resets(client: AsyncClient) -> None:
    pid, tasks, _ = await seed(client)
    now = [0.0]
    packs = SessionPacks(clock=lambda: now[0])
    with factory(client)() as session:
        sent = packs.get(session, pid)
        ContextService(session).build(pid, task=tasks["save"], record_for="claude", sent=sent)
        assert packs.get(session, pid).items

        # A session started, was cleared or was compacted (the start-up hook): send it all again.
        mark_context_reset(session)
        assert not packs.get(session, pid).items
        sent = packs.get(session, pid)
        ContextService(session).build(pid, task=tasks["save"], record_for="claude", sent=sent)
        assert packs.get(session, pid).items  # an older reset does not clear it twice

        # A long pause ends the working session too.
        now[0] += IDLE_SECONDS + 1
        packs.tick()
        assert not packs.get(session, pid).items
