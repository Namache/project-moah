"""The words of a text, as Moah compares them: search terms, light stems and meaningful words.

Search, shelf filing, context packs, Brain health and the MCP server's duplicate hints all
compare work with records by its words. The shared pieces live here, in a module that imports
nothing of the app, so any service can use them at the top of its file.
"""

from __future__ import annotations

import re
from functools import lru_cache

TERM_PATTERN = re.compile(r"\w+", re.UNICODE)
WORD = re.compile(r"[\w']+")
# Record IDs typed in a request ("check AUDIO-1"): an exact match beats any word match.
REF_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*-\d+\b")

# Words too common to say whether a record is related; only dropped when any word may match.
STOPWORDS = frozenset(
    "a an and are as at be but by do for from has have how if in into is it its of on or so"
    " that the their then there these this to was we were what when which while who why will"
    " with without you your add fix make use update set get".split()
)
# Chat filler that says nothing about which records matter.
FILLER = frozenset(
    "about again also any can could did does done just know let lets look need now please"
    " should show still tell think want would".split()
)


@lru_cache(maxsize=16384)
def stem(word: str) -> str:
    """A light stem so 'inventories', 'saving' and 'saved' meet 'inventory' and 'save'."""
    w = word.casefold().strip("'")
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[: -len(suffix)] + replacement
    return w


def stems(text: str) -> set[str]:
    return {stem(w) for w in WORD.findall(text)}


def match_keys(text: str) -> set[str]:
    """The meaningful words of a text, lightly stemmed, for comparing work with records."""
    keys = set()
    for word in WORD.findall(text.replace("’", "'")):
        low = word.casefold().strip("'")
        if low.endswith("'s"):
            low = low[:-2]  # possessives and "let's": the word itself
        if low in STOPWORDS or low in FILLER or low.isdigit() or REF_PATTERN.fullmatch(word):
            continue
        key = stem(low)
        keys.add(key[:-1] if len(key) > 3 and key.endswith("e") else key)  # save, saves: sav
    return keys


def title_words(text: str) -> set[str]:
    """The meaningful words of a title that can name a topic: "no" and "up" have none."""
    return {k for k in match_keys(text) if len(k) > 2}
