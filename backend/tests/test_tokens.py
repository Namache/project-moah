# ruff: noqa: E501  (reference texts are kept on one line, exactly as they were counted)
"""Local token counting (services/tokens.py) against OpenAI's o200k_base tokenizer.

Reference counts were made once with the gpt-tokenizer package (o200k_base), 2026-11-01. The app
itself never downloads a tokenizer or calls a provider.
"""

import math

import pytest

from app.services.tokens import PROVIDER_FACTOR, base_tokens, count_tokens

SAMPLES = {
    "prose": (
        "Project Moah keeps the rules, decisions and memory that Claude Code and Codex share. Agents fetch a context pack only when the work needs more than the brief: a new task, a record they have no pack for, the history behind a decision, or a bug they are tracking down.",
        59,
    ),
    "russian": (
        "Проект Моах хранит правила, решения и память, общие для Claude Code и Codex. Агенты запрашивают пакет контекста только тогда, когда работе нужно больше, чем даёт вводная.",
        73,
    ),
    "python": (
        "def count_tokens(text: str, provider: str | None = None) -> int:\n    if not text:\n        return 0\n    return math.ceil(base_tokens(text) * factor(provider))\n",
        40,
    ),
    "pack": (
        "PROJECT\nBenchmark Game\n\nCURRENT TASK\nSAVE-001 — Load old save files without crashing\n\nKNOWN ISSUES\nBUG-001\nOld saves lack the camp_capacity field\nLoading them crashes.\n\nWARNINGS\nWARN-001\nNever write saves while autosave runs",
        53,
    ),
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_counts_stay_close_to_the_real_tokenizer(name: str) -> None:
    text, real = SAMPLES[name]
    assert abs(base_tokens(text) - real) / real <= 0.16, (name, base_tokens(text), real)


def test_beats_characters_divided_by_four_on_russian() -> None:
    text, real = SAMPLES["russian"]
    assert abs(base_tokens(text) - real) < abs(math.ceil(len(text) / 4) - real) / 3


def test_providers_scale_and_empty_text_is_free() -> None:
    text, _ = SAMPLES["prose"]
    assert count_tokens(text, "codex") == base_tokens(text)
    assert count_tokens(text, "claude") == math.ceil(base_tokens(text) * PROVIDER_FACTOR["claude"])
    assert count_tokens("", "claude") == 0
    assert count_tokens(text, "something-else") == count_tokens(text, "claude")
