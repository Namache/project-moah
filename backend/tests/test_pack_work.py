"""Packs for unfinished work (the realistic test of 2026-11-02).

Agents asked the person questions that recorded decisions already answered. The answers were in
the in-progress task's linked decisions and its latest checkpoint, which a pack built from a
request alone never reached. Here: a request with no task= finds the task it continues, the
records the task's own work names come along, a shelf woken by one word adds no noise, agents'
packs carry only what they act on, and a checkpoint naming what helped counts as feedback.
"""

import re
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.models.graph import RetrievalSession
from app.models.project import Project
from app.services.brief import build_brief, listed_rules, work_refs
from app.services.context import ContextService
from app.services.memory import MemoryService
from app.services.words import match_keys
from tests.conftest import app_client
from tests.test_mcp import agent, call

pytestmark = pytest.mark.anyio


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def pack(client: AsyncClient, pid: str, **params: object) -> dict:
    response = await client.get(f"/api/projects/{pid}/context", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def titles(p: dict) -> set[str]:
    return {i["title"] for i in p["items"]}


def reason(p: dict, title: str) -> str:
    return next(i["reason"] for i in p["items"] if i["title"] == title)


async def build_camp(client: AsyncClient) -> tuple[str, dict]:
    """An idle game halfway through "offline progress": two tasks in progress, no focus set,
    decisions only the task's own work names, and an Economy shelf the word "gold" wakes."""
    pid = (await post(client, "/api/projects", name="Idle Camp"))["id"]
    base = f"/api/projects/{pid}"
    await post(client, f"{base}/shelves", name="Economy", keywords=["gold", "currency"])
    await post(client, f"{base}/shelves", name="Balance", keywords=["pacing", "tuning"])

    def memory(**body: object):
        return post(client, f"{base}/memory", **body)

    rec = {
        # Named by the checkpoint, on a shelf nothing wakes, sharing no word with the work.
        "cap": await memory(
            type="decision", title="At most 8 hours, at half rate", tags=["Balance"]
        ),
        # Named by an unfinished criterion.
        "fresh": await memory(type="decision", title="A save without lastSeen gets nothing"),
        # Named by the checkpoint's problems.
        "bump": await memory(type="warning", title="A new save field needs a version bump"),
        # Named only by a finished criterion: that part of the work is done.
        "done": await memory(type="fact", title="Timers tick once a second"),
        # Named by the checkpoint, but hidden from agents.
        "secret": await memory(type="decision", title="Secret tuning", ai_visibility="hidden"),
        # On the Economy shelf only: "gold" in the task's title is all that ties them.
        "prices": await memory(
            type="decision", title="Building prices grow 15% each", tags=["Economy"]
        ),
        "floor": await memory(type="rule", title="Floor money only when shown", tags=["Economy"]),
    }
    ref = {k: v["human_id"] for k, v in rec.items()}
    offline = await post(
        client,
        f"{base}/tasks",
        title="Offline progress: gold for time away",
        prefix="IDLE",
        status="in_progress",
        acceptance_criteria=[f"Old saves follow {ref['fresh']}", f"Ticks per {ref['done']}"],
    )
    await client.patch(
        f"{base}/tasks/{offline['id']}/criteria/{offline['acceptance_criteria'][1]['id']}",
        json={"is_completed": True},
    )
    sound = await post(
        client, f"{base}/tasks", title="Sound settings menu", prefix="IDLE", status="in_progress"
    )
    shipped = await post(
        client, f"{base}/tasks", title="Welcome screen", prefix="IDLE", status="completed"
    )
    await post(
        client,
        f"{base}/checkpoints",
        task_id=offline["human_id"],
        title="Offline formula started",
        remaining_work=f"Apply the cap ({ref['cap']}); respect {ref['secret']}.",
        problems=f"Unsure how {ref['bump']} applies here.",
        next_steps="Store lastSeen.",
    )
    # The checkpoint's guessed link to the cap is rejected, so only its text names the cap: the
    # Balance shelf stays dormant and no link or word leads to the record.
    links = await client.get(f"{base}/links", params={"node": offline["human_id"]})
    [guess] = [x for x in links.json()["links"] if x["node"]["label"] == ref["cap"]]
    assert (await client.delete(f"{base}/links/{guess['id']}")).status_code == 204
    rec.update(offline=offline, sound=sound, shipped=shipped)
    return pid, rec


def test_match_keys_drop_possessives() -> None:
    assert match_keys("Let's fix the player's save") == match_keys("fix player save")
    assert match_keys("let’s go") == match_keys("go")
    assert not any(k.endswith("'") for k in match_keys("players' let's it's"))


async def test_a_request_with_no_task_uses_the_task_it_continues(client: AsyncClient) -> None:
    pid, rec = await build_camp(client)
    offline, sound = rec["offline"]["human_id"], rec["sound"]["human_id"]

    p = await pack(client, pid, q="Finish the offline progress feature.")
    assert p["task"] == offline and p["task_source"] == "inferred"
    assert p["warnings"] == [
        f"No task was given; the request matches {offline} (in progress), so it was used. "
        "Pass task= for another."
    ]
    assert (await pack(client, pid, q="Let's finish the offline gold."))["task"] == offline

    # An ID typed in the request wins, typed the short way too; a closed task does not.
    short = offline.replace("-00", "-")
    named = await pack(client, pid, q=f"Continue with {short}, please")
    assert named["task"] == offline and "the request names" in named["warnings"][0]
    closed = await pack(client, pid, q=f"Continue with {rec['shipped']['human_id']}")
    assert closed["task"] is None and closed["task_source"] is None

    # Too little in common, or nothing at all: a project overview, as before.
    for vague in ("How do building prices grow?", "gold balance", "Fix the progress bar"):
        overview = await pack(client, pid, q=vague)
        assert overview["task"] is None, vague
        assert "this is a project overview" in overview["warnings"][0]

    # "Continue." names nothing: it means the unfinished task the brief shows, here the task
    # of the latest checkpoint, though two tasks are in progress.
    bare = await pack(client, pid, q="Continue.")
    assert bare["task"] == offline and bare["task_source"] == "inferred"
    assert bare["warnings"] == [
        f"No task was given; {offline} is the unfinished task in your brief, so it was used. "
        "Pass task= for another."
    ]

    # The current focus still comes first.
    await post(client, f"/api/projects/{pid}/tasks/{sound}/start")
    focus = await pack(client, pid, q="Finish the offline progress feature.")
    assert focus["task"] == sound and focus["task_source"] == "focus"


async def test_tied_tasks_are_not_guessed(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Shop"))["id"]
    prices, layout = [
        await post(client, f"/api/projects/{pid}/tasks", title=title, status="in_progress")
        for title in ("Gold shop prices", "Gold shop layout")
    ]
    assert (await pack(client, pid, q="Continue the gold shop"))["task"] is None
    assert (await pack(client, pid, q="Continue the gold shop prices"))["task"] is not None
    # Two in progress and no checkpoint: the brief shows none, and "Continue." picks none.
    assert (await pack(client, pid, q="Continue."))["task"] is None
    response = await client.patch(
        f"/api/projects/{pid}/tasks/{layout['human_id']}", json={"status": "todo"}
    )
    assert response.status_code == 200, response.text
    assert (await pack(client, pid, q="Continue."))["task"] == prices["human_id"]


def test_work_refs_read_both_spellings_and_skip_global_records() -> None:
    checkpoint = SimpleNamespace(remaining_work="See global RULE-3 and BUG-4.", problems="")
    checkpoint.next_steps = None
    where = work_refs("Follow DEC-1.", ["Per WARN-002"], checkpoint)
    assert where["DEC-001"] == where["DEC-1"] == where["WARN-002"] == "the task"
    assert where["BUG-004"] == "the latest checkpoint"
    assert "RULE-003" not in where and "RULE-3" not in where  # a Global record


def assert_pack_holds_the_brief(session, pid: str, task: str) -> None:
    """Every record the brief lists as already decided for ``task`` is a memory item of the
    pack it tells the agent to fetch, and of a bare "Continue." pack: at minimal detail by
    title, at balanced with its text."""
    brief = build_brief(session, session.get(Project, pid))
    assert f"UNFINISHED: {task} " in brief
    decided = [line.split()[1] for line in brief.splitlines() if line.startswith("  - ")]
    assert decided
    records = {m.human_id: m for m in MemoryService(session).list(pid, statuses=["active"])}
    for detail in ("balanced", "minimal"):
        for asked in ({"task": task}, {"query": "Continue."}):
            mine = ContextService(session).build(
                pid, detail=detail, record_for="claude", global_rules=False, **asked
            )
            assert mine.task == task, (detail, asked)
            held = {i.ref for i in mine.items if i.kind.startswith("memory")}
            missing = [d for d in decided if records[d].id not in held]
            assert not missing, (detail, asked, missing, mine.omitted)
            if detail == "balanced":
                for ref in decided:
                    assert records[ref].content in mine.text, ref


async def test_the_brief_and_the_pack_agree_on_the_work(
    client: AsyncClient, database_url: str
) -> None:
    """The brief's UNFINISHED task is the task a bare "Continue." pack uses, and every record
    the brief lists as already decided for it is in that pack."""
    pid, rec = await build_camp(client)
    offline = rec["offline"]["human_id"]
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        brief = build_brief(session, session.get(Project, pid))
        decided = [line.split()[1] for line in brief.splitlines() if line.startswith("  - ")]
        assert sorted(decided) == sorted(rec[k]["human_id"] for k in ("cap", "fresh", "bump"))
        assert_pack_holds_the_brief(session, pid, offline)


async def test_the_pack_keeps_every_record_the_brief_lists_past_its_caps(
    client: AsyncClient, database_url: str
) -> None:
    """Section caps and the minimal filter used to drop records the brief promised: facts past
    three (none at minimal), decisions past three at minimal, and records tied to the task by a
    stored link rather than by the memory's own tasks."""
    base = "/api/projects"
    # A: five facts linked to the task, nothing else.
    a = (await post(client, base, name="Shop"))["id"]
    work = await post(
        client, f"{base}/{a}/tasks", title="Tune the shop", prefix="SHOP", status="in_progress"
    )
    for n in range(5):
        await post(
            client,
            f"{base}/{a}/memory",
            type="fact",
            title=f"Shop fact {n}",
            content=f"Body of fact {n}.",
            task_ids=[work["id"]],
        )
    await post(client, f"{base}/{a}/checkpoints", task_id=work["human_id"], title="Started")
    # B: four decisions the checkpoint names, one tied by a typed link, a fact the next action
    # names.
    b = (await post(client, base, name="Named"))["id"]
    named = [
        (
            await post(
                client,
                f"{base}/{b}/memory",
                type="decision",
                title=f"Choice {n}",
                content=f"Why choice {n}.",
            )
        )["human_id"]
        for n in range(4)
    ]
    typed = await post(
        client, f"{base}/{b}/memory", type="decision", title="Typed", content="Why typed."
    )
    fact = await post(client, f"{base}/{b}/memory", type="fact", title="Known", content="Known.")
    gold = await post(
        client,
        f"{base}/{b}/tasks",
        title="Offline gold",
        prefix="GOLD",
        status="in_progress",
        next_action=f"Read {fact['human_id']} first.",
    )
    made = await client.post(
        f"{base}/{b}/links",
        json={
            "source": typed["human_id"],
            "relationship": "applies_to",
            "target": gold["human_id"],
        },
    )
    assert made.status_code == 201, made.text
    await post(
        client,
        f"{base}/{b}/checkpoints",
        task_id=gold["human_id"],
        title="Gold started",
        remaining_work="Follow " + ", ".join(named) + ".",
    )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        assert_pack_holds_the_brief(session, a, work["human_id"])
        assert_pack_holds_the_brief(session, b, gold["human_id"])


async def test_records_the_work_names_join_its_pack(client: AsyncClient) -> None:
    pid, rec = await build_camp(client)
    task = rec["offline"]["human_id"]
    title = {k: v["title"] for k, v in rec.items()}
    for detail in ("balanced", "minimal"):
        p = await pack(client, pid, task=task, detail=detail)
        found = titles(p)
        # Dormant shelf, no shared word, normal importance: named, so in, even at minimal.
        assert title["cap"] in found, detail
        assert reason(p, title["cap"]) == "named in the latest checkpoint"
        assert title["fresh"] in found and reason(p, title["fresh"]) == "named in the task"
        assert title["bump"] in found, detail
        assert title["done"] not in found  # its criterion is finished
        assert title["secret"] not in found and p["omitted"]["hidden"] >= 1
    # A request with no task is not this work: its checkpoint names nothing for it.
    overview = await pack(client, pid, q="How do building prices grow?")
    assert overview["task"] is None and title["cap"] not in titles(overview)


async def test_a_shelf_woken_by_one_word_adds_no_decisions_to_a_task(client: AsyncClient) -> None:
    pid, rec = await build_camp(client)
    p = await pack(client, pid, task=rec["offline"]["human_id"])
    assert rec["prices"]["title"] not in titles(p)
    assert p["omitted"]["weak shelf match"] >= 1
    assert rec["floor"]["title"] in titles(p)  # rules still wake with the domain they govern
    # With no task, the shelf may be all a request has to go on.
    overview = await pack(client, pid, q="gold balance")
    assert overview["task"] is None and rec["prices"]["title"] in titles(overview)


async def test_agent_packs_carry_only_what_the_agent_acts_on(
    client: AsyncClient, database_url: str
) -> None:
    pid, rec = await build_camp(client)
    task = rec["offline"]["human_id"]
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        preview = ContextService(session).build(pid, task=task)
        assert "ACTIVE SHELVES" in preview.text and "RECENT ACTIVITY" in preview.text
        assert rec["floor"]["title"] in preview.text

        mine = ContextService(session).build(
            pid, task=task, record_for="claude", global_rules=False
        )
        assert "ACTIVE SHELVES" not in mine.text and "RECENT ACTIVITY" not in mine.text
        # The agent's brief lists the project's rule by title only, so the pack sends it in full.
        assert rec["floor"]["title"] in mine.text
        assert mine.task_source == "given"

        explained = ContextService(session).build(
            pid, task=task, record_for="claude", global_rules=False, for_agent=False
        )
        assert "ACTIVE SHELVES" in explained.text


async def test_the_brief_lists_every_rule_by_title_and_the_pack_sends_them_in_full(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Rulebook"))["id"]
    words = "apple banana cherry damson elder fig grape hazel iris juniper kiwi lime mango nectar"
    word_of = {}
    for word in words.split():
        made = await post(
            client,
            f"/api/projects/{pid}/memory",
            type="rule",
            title=f"On {word}",
            content=f"Peel every {word} first.",
        )
        word_of[made["id"]] = word
    await post(
        client,
        f"/api/projects/{pid}/memory",
        type="rule",
        title="Only when asked",
        ai_visibility="manual_only",
    )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        brief = build_brief(session, session.get(Project, pid))
        chosen = listed_rules(MemoryService(session), pid)
        assert len(chosen) == 14  # every rule the agent may see, no cap
        everything = MemoryService(session).list(pid, statuses=["active"], limit=300)
        for m in everything:
            assert (f"\n- {m.human_id} {m.title}\n" in brief) == (m in chosen), m.title
        assert "Only when asked" not in brief
        assert "Peel every" not in brief  # titles only
    # A task whose words match two listed rules gets both in full.
    first, second = chosen[1].id, chosen[13].id
    title = f"{word_of[first].title()} {word_of[second]}"
    work = await post(client, f"/api/projects/{pid}/tasks", title=title)
    with factory() as session:
        mine = ContextService(session).build(
            pid, task=work["human_id"], record_for="claude", global_rules=False
        )
        assert {first, second} <= {i.ref for i in mine.items}
        assert f"Peel every {word_of[first]} first." in mine.text
        assert "already in your brief" not in mine.omitted


async def test_a_continue_request_through_mcp_sets_the_task_and_feedback(
    database_url: str,
) -> None:
    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
    task, cap, fresh, bump = (
        rec["offline"]["human_id"],
        rec["cap"]["human_id"],
        rec["fresh"]["human_id"],
        rec["bump"]["human_id"],
    )
    async with agent(database_url) as session:
        failed, text = await call(
            session, "brain_context_pack", query="Finish the offline progress feature.", project=pid
        )
        assert not failed
        body, footer = text.split("\n\n---\n")
        assert f"CURRENT TASK\n{task}" in body and "ACTIVE SHELVES" not in body
        assert footer.splitlines()[:2] == [
            f"No task was given; the request matches {task} (in progress), so it was used. "
            "Pass task= for another.",
            f"This session's task is {task}: what you write now is linked to it.",
        ]
        short = re.search(r'retrieval="(R-[0-9a-f]{8})"', footer).group(1)
        assert "brain_create_checkpoint" in footer and "tokens" not in footer
        failed, state = await call(session, "brain_project_state", project=pid)
        assert not failed and state["session_task"] == task

        # Records the pack held that the checkpoint names as done or next helped; its problems
        # do not count.
        failed, made = await call(
            session,
            "brain_create_checkpoint",
            title="Offline gold capped",
            completed_work=f"Capped offline gold ({cap}).",
            problems=f"{bump} still unclear.",
            next_steps=f"Handle saves per {fresh}.",
            project=pid,
        )
        assert not failed and made["task"] == task
        assert made["feedback"] == f"counted as feedback for {short}: {cap}, {fresh}"
        # The pack has its feedback now; a later checkpoint does not count it again.
        failed, again = await call(
            session,
            "brain_create_checkpoint",
            title="More",
            completed_work=f"{cap} tested.",
            project=pid,
        )
        assert not failed and "feedback" not in again
    factory = make_session_factory(make_engine(database_url))
    with factory() as db:
        stored = db.query(RetrievalSession).filter(RetrievalSession.id.startswith(short[2:])).one()
        verdicts = {i["label"]: i.get("verdict") for i in stored.items if i["kind"] == "memory"}
        assert stored.outcome == "feedback"
        assert verdicts[rec["cap"]["title"]] == "useful"
        assert verdicts[rec["bump"]["title"]] is None


async def test_a_pack_with_no_arguments_uses_the_unfinished_task_in_the_brief(
    database_url: str,
) -> None:
    """An agent's first call can be brain_context_pack() with nothing in it. It means the work
    the brief shows as unfinished, never a project overview that disagrees with the brief."""
    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
    task = rec["offline"]["human_id"]
    async with agent(database_url) as session:
        failed, text = await call(session, "brain_context_pack", project=pid)
        assert not failed and f"CURRENT TASK\n{task}" in text
        assert f"No task was given; {task} is the unfinished task in your brief" in text
        failed, state = await call(session, "brain_project_state", project=pid)
        assert not failed and state["session_task"] == task


def retrieval_of(text: str) -> str:
    return re.search(r'retrieval="(R-[0-9a-f]{8})"', text).group(1)


async def test_a_pack_with_no_task_stays_on_the_session_task(database_url: str) -> None:
    """A question asked in the middle of a task is about that task: it never moves the session
    to the task the brief shows or a request matches, so later records and checkpoints stay
    on the task the agent works on."""
    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
    offline, sound = rec["offline"]["human_id"], rec["sound"]["human_id"]
    async with agent(database_url) as session:
        failed, _ = await call(session, "brain_context_pack", task=sound, project=pid)
        assert not failed
        failed, text = await call(session, "brain_context_pack", query="Continue.", project=pid)
        assert not failed and text.startswith("Nothing new since R-")  # the same pack
        for query in ("Finish the offline progress feature.", "Continue."):
            failed, text = await call(
                session, "brain_context_pack", query=query, project=pid, full=True
            )
            assert not failed and f"CURRENT TASK\n{sound}" in text, query
            assert f"No task was given; {sound} is this session's task, so it was used." in text, (
                query
            )
            assert "project overview" not in text
        failed, made = await call(
            session,
            "brain_create_memory",
            type="decision",
            title="The sound menu has a mute toggle",
            project=pid,
        )
        assert not failed and sound in str(made)
        failed, cp = await call(session, "brain_create_checkpoint", title="Menu drawn", project=pid)
        assert not failed and cp["task"] == sound
        # Naming a task is how to switch.
        failed, text = await call(session, "brain_context_pack", task=offline, project=pid)
        assert not failed and f"This session's task is {offline}" in text


async def test_packs_send_project_rules_whether_or_not_the_brief_showed_the_project(
    database_url: str,
) -> None:
    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
    task, floor = rec["offline"]["human_id"], rec["floor"]["human_id"]
    async with agent(database_url) as session:
        failed, _ = await call(session, "brain_brief", cwd="/nonexistent/elsewhere")
        assert not failed
        failed, text = await call(session, "brain_context_pack", task=task, project=pid)
        assert not failed and f"\n{floor}\n" in text  # that brief showed no project rules
        failed, brief = await call(session, "brain_brief", project=pid)
        assert not failed and f"- {floor} {rec['floor']['title']}\n" in brief  # title only
        failed, text = await call(
            session, "brain_context_pack", task=task, project=pid, explain=True, full=True
        )
        assert not failed and f"\n{floor}\n" in text


async def test_a_task_pack_after_the_brief_sends_its_left_to_do_once(database_url: str) -> None:
    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
        task = rec["offline"]["human_id"]
        changed = await client.patch(
            f"/api/projects/{pid}/tasks/{task}", json={"next_action": "Store lastSeen."}
        )
        assert changed.status_code == 200, changed.text
    async with agent(database_url) as session:
        failed, _ = await call(session, "brain_brief", project=pid)
        failed, text = await call(session, "brain_context_pack", task=task, project=pid)
        assert not failed and "Remaining: as in your brief" in text
        # The checkpoint's next step is the task's next action: shown once.
        assert text.count("Store lastSeen.") == 1
    async with agent(database_url) as session:  # no brief for this project: all of it
        failed, text = await call(session, "brain_context_pack", task=task, project=pid)
        assert not failed and f"Remaining: Apply the cap ({rec['cap']['human_id']})" in text


async def test_feedback_counts_once_per_session_and_reaches_every_pack(database_url: str) -> None:
    from app.models.graph import NodeUsefulness

    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
    task = rec["offline"]["human_id"]
    cap, bump, floor = (rec[k]["human_id"] for k in ("cap", "bump", "floor"))
    async with agent(database_url) as session:
        failed, first = await call(session, "brain_context_pack", task=task, project=pid)
        assert not failed and f"\n{floor}\n" in first
        failed, second = await call(
            session,
            "brain_context_pack",
            query="Is the cap 8 hours?",
            detail="minimal",
            full=True,
            project=pid,
        )
        assert not failed and f"\n{floor}\n" not in second  # minimal: no rules
        a, b = retrieval_of(first), retrieval_of(second)
        # Each record counts for the latest pack that held it.
        failed, made = await call(
            session,
            "brain_create_checkpoint",
            title="Cap done",
            completed_work=f"Capped ({cap}), following {floor}.",
            project=pid,
        )
        assert not failed
        assert made["feedback"] == (
            f"counted as feedback for {b}: {cap}; counted as feedback for {a}: {floor}"
        )
        # Saying it again, on either pack, does not count again; a new verdict does.
        failed, said = await call(
            session,
            "brain_retrieval_feedback",
            retrieval=a,
            useful=[cap, floor],
            not_useful=[bump],
            project=pid,
        )
        assert not failed and said["already_counted"] == [cap, floor]
        # Changing a verdict on the same pack moves the count.
        failed, said = await call(
            session, "brain_retrieval_feedback", retrieval=b, not_useful=[cap], project=pid
        )
        assert not failed and "already_counted" not in said
    factory = make_session_factory(make_engine(database_url))
    with factory() as db:
        ids = {m.human_id: m.id for m in MemoryService(db).list(pid, statuses=["active"])}
        counts: dict[str, list[int]] = {}
        for row in db.query(NodeUsefulness).filter(NodeUsefulness.project_id == pid):
            total = counts.setdefault(row.node_id, [0, 0])
            total[0] += row.useful
            total[1] += row.not_useful
        assert counts[ids[cap]] == [0, 1]
        assert counts[ids[floor]] == [1, 0]
        assert counts[ids[bump]] == [0, 1]


async def test_a_checkpoint_after_working_from_the_brief_alone_finds_its_task(
    database_url: str,
) -> None:
    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
    task, cap = rec["offline"]["human_id"], rec["cap"]["human_id"]
    async with agent(database_url) as session:
        failed, _ = await call(session, "brain_brief", project=pid)
        # No pack, so no session task: a checkpoint that names nothing of the task keeps none.
        failed, small = await call(session, "brain_create_checkpoint", title="Typo", project=pid)
        assert not failed and small["task"] is None
        failed, done = await call(
            session,
            "brain_create_checkpoint",
            title="Feature finished",
            completed_work=f"Offline gold capped per {cap}.",
            project=pid,
        )
        assert not failed and done["task"] == task and task in done["task_note"]
    factory = make_session_factory(make_engine(database_url))
    with factory() as db:
        brief = build_brief(db, db.get(Project, pid))
        # The old checkpoint's "Left to do" is gone with it.
        assert f"UNFINISHED: {task} " in brief and "Offline formula started" not in brief


async def test_a_checkpoint_lands_on_the_task_it_names(
    database_url: str,
) -> None:
    """Checkpoints kept landing on the task the session touched last, even a note that names
    another task by its ID."""
    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
    offline, sound = rec["offline"]["human_id"], rec["sound"]["human_id"]
    number = int(sound.rsplit("-", 1)[1])
    async with agent(database_url) as session:
        failed, _ = await call(session, "brain_context_pack", task=offline, project=pid)
        assert not failed
        # Naming the session's own task too keeps the note there.
        failed, same = await call(
            session,
            "brain_create_checkpoint",
            title=f"Cap applied in {offline}",
            summary=f"Volume slider ({sound}) waits for it.",
            project=pid,
        )
        assert not failed and same["task"] == offline
        # Written as IDLE-6, not IDLE-006: still the sound task, and it becomes the session's.
        failed, other = await call(
            session,
            "brain_create_checkpoint",
            title=f"Volume slider for IDLE-{number} laid out",
            project=pid,
        )
        assert not failed and other["task"] == sound and offline in other["task_note"]
        failed, after = await call(
            session, "brain_create_checkpoint", title="Slider styled", project=pid
        )
        assert not failed and after["task"] == sound


async def test_a_checkpoint_that_only_mentions_another_task_stays_on_its_own(
    database_url: str,
) -> None:
    """QA 2026-11-08: "Unblocked by PROJ-044" or a task named in passing in the summary moved the
    note, and the session, to that task. Only the headline decides."""
    async with app_client(database_url) as client:
        pid, rec = await build_camp(client)
    offline, sound = rec["offline"]["human_id"], rec["sound"]["human_id"]
    async with agent(database_url) as session:
        failed, _ = await call(session, "brain_context_pack", task=offline, project=pid)
        assert not failed
        for title, summary in [
            (f"Cap applied, unblocked by {sound}", None),
            ("Cap applied", f"Same cause as the bug in {sound}."),
            (f"Cap applied after {sound}", None),
        ]:
            extra = {"summary": summary} if summary else {}
            failed, note = await call(
                session, "brain_create_checkpoint", title=title, project=pid, **extra
            )
            assert not failed and note["task"] == offline, (title, note)
        # A summary that opens with the ref is about that task.
        failed, moved = await call(
            session,
            "brain_create_checkpoint",
            title="Slider laid out",
            summary=f"{sound}: the volume slider is laid out.",
            project=pid,
        )
        assert not failed and moved["task"] == sound
