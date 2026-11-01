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
    assert quality["precision"] >= 0.44  # baseline 0.449
