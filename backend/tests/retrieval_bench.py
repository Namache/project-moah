"""Retrieval benchmark: how well context packs find what a task needs, and what it costs.

A fixed, made-up game project (no personal records) with words that overlap on purpose:
"save", "old", "party", "capacity", "settings", "screen", "crash", "loading". Any-word search
matches many records for every task; only some of them help.

Two measurements:

1. Pack quality. For each case (a task and/or a question), the records that should be in the
   pack are listed. Precision = needed memory records in the pack / memory records in the pack.
   Recall = needed records in the pack / needed records.

2. Sessions. Scripted agent sessions replayed as an agent that follows its brief literally: it
   reads the startup brief once, then for each request decides whether to fetch a pack. Each
   request is tagged with why it might need context (``kind``). The ``every_request`` policy is
   the brief before November 2026 ("call brain_context_pack FIRST for every request"); the
   ``on_demand`` policy fetches only for the kinds the brief lists (``brief.RETRIEVE_WHEN``).
   - unnecessary retrieval: a pack fetched when everything the request needs was already known
   - missed: a request needed a record the agent never got, so the task fails
   - tokens: brief + every pack, counted with the app's own token counter
   - tokens per completed task: total tokens / sessions with nothing missed
   The ``on_demand_repeat_aware`` policy fetches like ``on_demand`` but replays the MCP server's
   memory of what the session was already sent (PROJ-015): a repeat pack sends only what is new.

3. Exploring (PROJ-014). Packs are predictable by default; with exploring on (Settings) link
   weights are sampled. The pack cases are run ``EXPLORE_RUNS`` times with exploring on and
   compared with the predictable run.

Run ``python -m tests.retrieval_bench`` from backend/ to print the numbers as JSON.
Real agents may not follow the brief literally; that needs live runs (see the 2026-10 logs).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from httpx import AsyncClient

from app.models.project import Project
from app.services import brief as brief_module
from app.services.context import ContextService, SentRecords

# ---- the fixture -----------------------------------------------------------------------------

TASKS = {
    "save": dict(title="Load old save files without crashing", prefix="SAVE"),
    "camp": dict(title="Camp party capacity", prefix="CAMP"),
    "ui": dict(title="Settings screen layout", prefix="UI"),
    "audio": dict(title="Mixer volume sliders", prefix="AUDIO"),
}

# label: (type, title, content, task label or None, importance)
MEMORY: dict[str, tuple[str, str, str, str | None, str]] = {
    # needed records
    "b_save": (
        "bug",
        "Old saves lack the camp_capacity field",
        "Loading them crashes.",
        "save",
        "high",
    ),
    "w_save": (
        "warning",
        "Never write saves while autosave runs",
        "Two writers corrupt the file.",
        None,
        "normal",
    ),
    "r_save": (
        "rule",
        "Save migrations preserve older saves",
        "Migrate, never drop fields.",
        None,
        "normal",
    ),
    "d_party": ("decision", "Party size is 6", "Six folk fit the camp UI.", "camp", "high"),
    "d_ui": (
        "decision",
        "Settings use tabs, not one long scroll",
        "Tabs: General, Audio, Controls.",
        "ui",
        "normal",
    ),
    "f_audio": (
        "fact",
        "The mixer has four buses",
        "Master, music, effects, voice.",
        "audio",
        "normal",
    ),
    # noise: shares words with the tasks, helps none of them
    "n_button": ("fact", "Save button colour in settings is green", "", None, "normal"),
    "n_hats": ("idea", "Party hats for the old camp", "", None, "low"),
    "n_art": ("decision", "Old camp art style is watercolour", "", None, "normal"),
    "n_tips": ("fact", "Loading screen shows gameplay tips", "", None, "normal"),
    "n_files": ("decision", "Files menu layout follows the settings screen", "", None, "normal"),
    "n_buffer": ("fact", "Capacity of the music crossfade buffer is 2 seconds", "", None, "normal"),
    "n_crash": ("fact", "The crash reporter sends nothing while offline", "", None, "normal"),
    "n_slider": ("note", "Volume slider knobs look old", "", None, "low"),
    "n_party_ui": ("note", "Party screen font is too small", "", None, "low"),
    "n_save_icon": ("note", "Save icon is a floppy disk", "", None, "low"),
}

# Links between records. Verified = made or confirmed by a person (active, full confidence);
# guessed = an inferred candidate nobody checked.
VERIFIED = [
    ("b_save", "caused_by", "w_save"),
    ("task:save", "governed_by", "r_save"),
]
GUESSED = [("task:save", "relates_to", "n_tips")]
SUPERSEDED = ("d_party", "Party size is 8", "Old value before the camp rework.")


@dataclass
class Case:
    name: str
    task: str | None
    query: str | None
    needed: set[str]
    forbidden: set[str] = field(default_factory=set)
    fine: set[str] = field(default_factory=set)  # related enough: neither needed nor noise


CASES = [
    Case(
        "task with a bug, a linked warning and a governing rule",
        "save",
        None,
        {"b_save", "w_save", "r_save"},
    ),
    Case("task with a superseded decision", "camp", None, {"d_party"}, forbidden={"d_party_old"}),
    Case(
        "decision question, no task", None, "what did we decide about the settings screen", {"d_ui"}
    ),
    Case("small task, one fact", "audio", None, {"f_audio"}),
    Case(
        "bug question, no task",
        None,
        "why do old saves crash on load",
        {"b_save", "w_save"},
        fine={"r_save"},
    ),
]


@dataclass
class Request:
    text: str
    kind: str  # why it might need context; see brief.RETRIEVE_WHEN
    needs: set[str] = field(default_factory=set)


@dataclass
class Script:
    name: str
    task: str
    requests: list[Request]


SESSIONS = [
    Script(
        "fix the old-save crash",
        "save",
        [
            Request("Work on SAVE-1", "start_task", {"b_save", "w_save", "r_save"}),
            Request("Add a fallback for the missing field", "follow_up"),
            Request("Rename the helper to migrate_save", "small_edit"),
            Request("Run the tests", "small_edit"),
            Request("Why did old saves break in the first place?", "history", {"b_save"}),
        ],
    ),
    Script(
        "camp capacity",
        "camp",
        [
            Request("Work on CAMP-1", "start_task", {"d_party"}),
            Request("Show the count in the camp header", "follow_up"),
            Request("Fix the typo in the tooltip", "small_edit"),
            Request("Recruiting a seventh folk crashes the camp", "debugging", {"d_party"}),
        ],
    ),
    Script(
        "settings layout",
        "ui",
        [
            Request("Work on UI-1", "start_task", {"d_ui"}),
            Request("Move the volume options into the Audio tab", "follow_up"),
            Request("The mixer bus list is wrong, check AUDIO-1", "names_record", {"f_audio"}),
            Request("Make the tab labels bold", "small_edit"),
            Request("Now make the mixer remember volumes", "unfamiliar_area", {"f_audio"}),
        ],
    ),
]


def _on_demand(kind: str) -> bool:
    return kind in getattr(brief_module, "RETRIEVE_WHEN", {})


# policy: (fetch a pack for this kind of request?, remember what the session was sent?)
POLICIES = {
    "every_request": (lambda kind: True, False),
    "on_demand": (_on_demand, False),
    "on_demand_repeat_aware": (_on_demand, True),
}
EXPLORE_RUNS = 30


# ---- running it ------------------------------------------------------------------------------


async def _post(client: AsyncClient, path: str, **body: object) -> dict:
    response = await client.post(path, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def seed(client: AsyncClient) -> tuple[str, dict[str, str], dict[str, str]]:
    """Create the fixture. Returns project id, task label -> human id, memory label -> id."""
    pid = (await _post(client, "/api/projects", name="Benchmark Game"))["id"]
    base = f"/api/projects/{pid}"
    tasks: dict[str, dict] = {}
    for label, body in TASKS.items():
        tasks[label] = await _post(client, f"{base}/tasks", **body)
    memory: dict[str, dict] = {}
    keep, old_title, old_content = SUPERSEDED
    for label, (kind, title, content, task, importance) in MEMORY.items():
        body: dict = dict(type=kind, title=title, content=content, importance=importance)
        if task:
            body["task_ids"] = [tasks[task]["id"]]
        if label == keep:
            # The current decision replaces an older one; the older one must never show up.
            body.update(title=old_title, content=old_content)
            old = await _post(client, f"{base}/memory", **body)
            memory[f"{label}_old"] = old
            memory[label] = await _post(
                client, f"{base}/memory/{old['id']}/supersede", title=title, content=content
            )
            continue
        memory[label] = await _post(client, f"{base}/memory", **body)

    def node(ref: str) -> str:
        if ref.startswith("task:"):
            return tasks[ref[5:]]["human_id"]
        return f"memory:{memory[ref]['human_id']}"

    for source, relationship, target in VERIFIED:
        await _post(
            client,
            f"{base}/links",
            source=node(source),
            relationship=relationship,
            target=node(target),
            strength=0.9,
        )
    for source, relationship, target in GUESSED:
        await _post(
            client,
            f"{base}/links",
            source=node(source),
            relationship=relationship,
            target=node(target),
            strength=0.6,
            confidence=0.5,
            status="candidate",
        )
    return (
        pid,
        {label: t["human_id"] for label, t in tasks.items()},
        {label: m["id"] for label, m in memory.items()},
    )


def _pack(
    session,
    pid: str,
    task: str | None,
    query: str | None,
    *,
    explore: bool = False,
    sent: SentRecords | None = None,
):
    # A session that remembers what it was sent records its packs like the MCP server does, so
    # a repeat names the pack it repeats. Running last, it cannot change the other numbers.
    return ContextService(session).build(
        pid,
        task=task,
        query=query,
        detail="balanced",
        global_rules=False,
        explore=explore,
        record_for="claude" if sent is not None else None,
        sent=sent,
    )


def _count(text: str) -> int:
    """Claude tokens, counted locally (services/tokens.py), so runs on old code compare."""
    from app.services.tokens import count_tokens

    return count_tokens(text, "claude")


def _quality(session, pid, task_ids, label_of, explore: bool = False) -> dict:
    cases = []
    for case in CASES:
        task = task_ids.get(case.task) if case.task else None
        pack = _pack(session, pid, task, case.query, explore=explore)
        got = {label_of.get(i.ref, i.ref) for i in pack.items if i.kind.startswith("memory")}
        got -= case.fine
        hit = got & case.needed
        cases.append(
            {
                "case": case.name,
                "precision": round(len(hit) / len(got), 3) if got else 0.0,
                "recall": round(len(hit) / len(case.needed), 3),
                "noise": sorted(got - case.needed),
                "missing": sorted(case.needed - got),
                "forbidden_found": sorted(got & case.forbidden),
                "tokens": _count(pack.text),
                "text": pack.text,
            }
        )
    n = len(cases)
    return {
        "precision": round(sum(c["precision"] for c in cases) / n, 3),
        "recall": round(sum(c["recall"] for c in cases) / n, 3),
        "pack_tokens_avg": round(sum(c["tokens"] for c in cases) / n),
        "cases": cases,
    }


def _explore(session, pid, task_ids, label_of, predictable: dict) -> dict:
    """The pack cases with exploring on, ``EXPLORE_RUNS`` times."""
    runs = [_quality(session, pid, task_ids, label_of, explore=True) for _ in range(EXPLORE_RUNS)]
    differ = [
        sum(1 for run in runs if run["cases"][k]["text"] != case["text"])
        for k, case in enumerate(predictable["cases"])
    ]
    return {
        "runs": EXPLORE_RUNS,
        "precision_avg": round(sum(r["precision"] for r in runs) / len(runs), 3),
        "precision_min": min(r["precision"] for r in runs),
        "recall_avg": round(sum(r["recall"] for r in runs) / len(runs), 3),
        "recall_min": min(r["recall"] for r in runs),
        "pack_tokens_avg": round(sum(r["pack_tokens_avg"] for r in runs) / len(runs)),
        # per case: in how many runs the pack differed from the predictable one
        "packs_that_differed": differ,
    }


def measure(session, pid: str, task_ids: dict[str, str], memory_ids: dict[str, str]) -> dict:
    label_of = {v: k for k, v in memory_ids.items()}
    quality = _quality(session, pid, task_ids, label_of)
    # Same request twice, exploring off: the packs must be identical (PROJ-014).
    again = _quality(session, pid, task_ids, label_of)
    quality["repeatable"] = all(
        a["text"] == b["text"] for a, b in zip(quality["cases"], again["cases"], strict=True)
    )
    explore = _explore(session, pid, task_ids, label_of, quality)
    for case in quality["cases"]:
        del case["text"]

    project = session.get(Project, pid)
    brief_tokens = _count(brief_module.build_brief(session, project))
    sessions = {}
    for policy, (wants, remembers) in POLICIES.items():
        total = retrievals = unnecessary = missed_requests = completed = 0
        unnecessary_tokens: list[int] = []
        for script in SESSIONS:
            known: set[str] = set()
            sent = SentRecords() if remembers else None
            tokens = brief_tokens
            failed = False
            for request in script.requests:
                if wants(request.kind):
                    retrievals += 1
                    needless = request.needs <= known
                    query = None if request.kind == "start_task" else request.text
                    pack = _pack(session, pid, task_ids[script.task], query, sent=sent)
                    cost = _count(pack.text)
                    tokens += cost
                    if needless:
                        unnecessary += 1
                        unnecessary_tokens.append(cost)
                    known |= {
                        label_of.get(i.ref, i.ref)
                        for i in pack.items
                        if i.kind.startswith("memory")
                    }
                if not request.needs <= known:
                    missed_requests += 1
                    failed = True
            total += tokens
            completed += 0 if failed else 1
        sessions[policy] = {
            "requests": sum(len(s.requests) for s in SESSIONS),
            "retrievals": retrievals,
            "unnecessary_retrievals": unnecessary,
            "unnecessary_retrieval_tokens": unnecessary_tokens,
            "missed_requests": missed_requests,
            "completed_tasks": completed,
            "tasks": len(SESSIONS),
            "total_tokens": total,
            "tokens_per_completed_task": round(total / completed) if completed else None,
        }
    return {
        "brief_tokens": brief_tokens,
        "quality": quality,
        "explore": explore,
        "sessions": sessions,
    }


async def run(database_url: str) -> dict:
    from tests.conftest import app_client

    async with app_client(database_url) as client:
        pid, task_ids, memory_ids = await seed(client)
        factory = client._transport.app.state.session_factory  # type: ignore[attr-defined]
        with factory() as session:
            return measure(session, pid, task_ids, memory_ids)


def main() -> None:
    os.environ.setdefault("PROJECT_BRAIN_EXPLORE", "0")
    with tempfile.TemporaryDirectory() as folder:
        url = f"sqlite:///{Path(folder) / 'bench.db'}"
        print(json.dumps(asyncio.run(run(url)), indent=2))


if __name__ == "__main__":
    main()
