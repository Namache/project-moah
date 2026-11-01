"""Regression guard for retrieval: precision, recall, unnecessary retrievals and tokens per
completed task, measured by tests/retrieval_bench.py on a fixed made-up project.

The baseline (main 0632aa4, before on-demand retrieval) is in docs/benchmarks/. These limits
only move in the better direction.
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
