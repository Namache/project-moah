"""Token counts, worked out on this computer: no tokenizer download, no provider API.

The old rule (characters / 4) is fine for English code but far off elsewhere: on Moah's own
Russian text it undercounts by about 40%, and on English prose it overcounts by about 20%.

``count_tokens`` splits text the way modern byte-pair tokenizers do (words with their leading
space, runs of up to three digits, punctuation runs, line breaks with their indentation) and
prices each piece by its script and length. Its constants were fitted against OpenAI's
o200k_base tokenizer (GPT-4o and later, which Codex uses) on Moah's own code, docs and
Russian strings, 2026-11-01. Weighted error on held-out text: Markdown and prose 2.6%,
Russian 4.5%, TypeScript 5%, Python 11% (it overcounts code a little; characters / 4 was off
by 23%, 42%, 5% and 11%).

Claude's tokenizer is not public, so a Claude count is the o200k estimate times a factor: 1.2
until Project Moah has measured it from Claude Code's own logs on this computer
(services/token_calibration.py; newer Claude models measured nearer 2 on packs). What an agent
really used comes from its own logs (services/usage.py), never from this module.
"""

from __future__ import annotations

import math
import re

# Fitted against o200k_base (see the module docstring).
WORD_ONE_TOKEN = 10  # an ASCII word up to this many letters is usually one token
WORD_EXTRA_PER = 8  # longer words: one more token per this many letters
NON_LATIN_PER = 2.5  # Cyrillic, Greek, Hebrew, Arabic...: letters per token
PUNCT_PER = 4  # punctuation run: characters per token
SPACE_PER = 16  # a run of spaces or tabs: characters per token

# Tokens per o200k token. Codex models use o200k itself. Claude's figure is an estimate:
# its tokenizer splits text into somewhat more pieces than o200k does.
PROVIDER_FACTOR: dict[str, float] = {"openai": 1.0, "codex": 1.0, "claude": 1.2}
DEFAULT_PROVIDER = "claude"  # the larger count, so budgets err on the safe side

PIECE = re.compile(
    r"'(?:s|t|re|ve|m|ll|d)\b| ?[^\W\d_]+| ?\d{1,3}| ?[^\s\w]+|\s*\n[ \t]*|[ \t]+|_+",
    re.IGNORECASE,
)


def _is_cjk(ch: str) -> bool:
    return "぀" <= ch <= "鿿" or "가" <= ch <= "힯"


def base_tokens(text: str) -> int:
    """Estimated o200k_base tokens."""
    total = 0
    for match in PIECE.finditer(text):
        piece = match.group()
        if piece.isspace():
            total += 1 if "\n" in piece else math.ceil(len(piece) / SPACE_PER)
            continue
        word = piece.lstrip(" ")
        first = word[0]
        if first.isalpha():
            if word.isascii():
                extra = len(word) - WORD_ONE_TOKEN
                total += 1 + (math.ceil(extra / WORD_EXTRA_PER) if extra > 0 else 0)
            elif _is_cjk(first):
                total += len(word)
            else:
                total += math.ceil(len(word) / NON_LATIN_PER)
        elif first.isdigit() or first == "_":
            total += 1
        else:
            total += math.ceil(len(word) / PUNCT_PER)
    return total


# Factors measured on this computer from the agents' own logs (services/token_calibration.py),
# which replace the fixed ones above once enough packs were measured.
_measured: dict[str, float] = {}


def use_measured(provider: str, value: float | None) -> None:
    """Use a measured factor for ``provider`` (None goes back to the fixed one)."""
    if value is None:
        _measured.pop(provider, None)
    else:
        _measured[provider] = value


def factor(provider: str | None) -> float:
    name = (provider or DEFAULT_PROVIDER).casefold()
    if name not in PROVIDER_FACTOR:
        name = "claude"
    return _measured.get(name, PROVIDER_FACTOR[name])


def count_tokens(text: str, provider: str | None = None) -> int:
    """Estimated tokens of ``text`` for ``provider`` ("claude", "codex" or "openai")."""
    if not text:
        return 0
    return math.ceil(base_tokens(text) * factor(provider))
