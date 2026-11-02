"""Regression guard for retrieval: precision, recall, unnecessary retrievals and tokens per
completed task, measured by tests/retrieval_bench.py on fixed made-up projects.

The baseline (main 0632aa4, before on-demand retrieval) is in docs/benchmarks/, and so are the
work-in-progress cases (retrieval-continue.json). These limits only move in the better
direction.
"""

import pytest

from tests.retrieval_bench import run

pytestmark = pytest.mark.anyio


async def test_packs_find_what_tasks_need(database_url: str) -> None:
    report = await run(database_url)
    quality = report["quality"]
    for case in quality["cases"]:
        assert case["recall"] == 1.0, case
        assert not case["forbidden_found"], case
    assert quality["precision"] >= 0.85  # baseline 0.449 (any-word matches)


async def test_on_demand_retrieval_skips_packs_without_missing_anything(database_url: str) -> None:
    report = await run(database_url)
    every, on_demand = report["sessions"]["every_request"], report["sessions"]["on_demand"]
    assert on_demand["missed_requests"] == 0
    assert on_demand["completed_tasks"] == on_demand["tasks"]
    assert on_demand["retrievals"] < every["retrievals"]
    assert on_demand["unnecessary_retrievals"] < every["unnecessary_retrievals"]
    assert on_demand["tokens_per_completed_task"] < every["tokens_per_completed_task"]
    # Baseline (old brief, old matching): 1,249 tokens per completed task.
    assert on_demand["tokens_per_completed_task"] <= 700


def test_the_brief_lists_every_reason_to_fetch_a_pack() -> None:
    from app.services.brief import HOW_TO, RETRIEVE_WHEN

    assert "FIRST for every request" not in HOW_TO
    for when in RETRIEVE_WHEN.values():
        assert when in HOW_TO


async def test_packs_are_repeatable_and_exploring_keeps_recall(database_url: str) -> None:
    report = await run(database_url)
    assert report["quality"]["repeatable"]  # same request, same pack (PROJ-014)
    assert report["explore"]["recall_min"] == 1.0


async def test_repeat_packs_send_only_what_is_new(database_url: str) -> None:
    report = await run(database_url)
    on_demand = report["sessions"]["on_demand"]
    aware = report["sessions"]["on_demand_repeat_aware"]
    assert aware["missed_requests"] == 0
    assert aware["retrievals"] == on_demand["retrievals"]
    # The unnecessary fetches cost ~100 tokens each before (PROJ-015 asks for ~20).
    assert aware["unnecessary_retrieval_tokens"]
    assert max(aware["unnecessary_retrieval_tokens"]) <= 35
    assert aware["tokens_per_completed_task"] < on_demand["tokens_per_completed_task"]


async def test_packs_for_unfinished_work_find_what_its_checkpoint_names(database_url: str) -> None:
    report = await run(database_url)
    work = report["continue"]
    rows = {(r["detail"], r["case"]): r for r in work["cases"]}
    for detail in ("balanced", "minimal"):
        # "Continue" with no task= and no focus: the request picks the task in progress, and
        # the records its latest checkpoint names come along (main: recall 0.0).
        for case in ("continue, query only", "continue, bare request"):
            row = rows[(detail, case)]
            assert row["task"] == work["task"] and row["task_source"] == "inferred", row
            assert row["recall"] == 1.0 and row["precision"] >= 0.85, row
        # With the task given, minimal detail keeps them too (main: recall 0.333).
        row = rows[(detail, "continue, task given")]
        assert row["task_source"] == "given" and row["recall"] == 1.0, row
        # A question about something else stays a project overview.
        row = rows[(detail, "off-topic question")]
        assert row["task"] is None, row
    assert rows[("balanced", "off-topic question")]["recall"] == 1.0
