"""Whether an agent's checkpoint says the work now waits for the person.

Agents stop halfway to ask for an OK on a plan, a mockup or a commit, and they say so in the
checkpoint they write ("mockup ready for review", "waiting for the owner's pick"), but they
rarely hand the task over or ask through Moah. Such a checkpoint opens a question in Review
(see ReviewService.wait_from_checkpoint), so nothing that waits for the person is missed.

An agent can say it outright with waiting_for_person; without it the title is read. Only the
title: the other fields quote earlier waits ("after the owner's OK...") and would misfire.
English only, and on purpose narrow: a wait it misses still reaches the chat, while a false one
puts a question in Review that nobody asked.
"""

from __future__ import annotations

import re

# What the person is asked for.
_ASK = (
    r"(?:ok|okay|yes|go|go[- ]ahead|review|approval|answer|decision|feedback|reply|choice|pick"
    r"|verdict|input|word|sign[- ]off|confirmation|listen|test|testing|selection)"
)
# Who is waited on: the person in any words, or a capitalised name. A capitalised word with a
# hyphen after it is a task ref (BUG-12), not a name.
_WHO = r"(?:you|the\s+person|the\s+user|the\s+owner|her|him|them|(?-i:[A-Z][a-z]{2,}))"
_WHOSE = rf"(?:(?:the|your|her|his|their)\s+|(?:{_WHO}|owner)'s\s+)"
# The ask ends its phrase. Followed by another noun it only names something else: "waiting for
# the Review hand-over PRs", "waiting for test results".
_END = (
    r"\b(?=\s*(?:$|[.,;:!?()\[\]\"'“”‘’—–]|-\s|(?:on|of|for|from|by|in|at|to|before|after"
    r"|and|or|so|then|now|first|again|please|with|about|while|until|when|if)\b))"
)
_WAITED_FOR = rf"(?:{_WHO}\b(?!-)|{_WHOSE}?(?:\w+\s+)?{_ASK}{_END})"

WAITS = re.compile(
    rf"""
    \bwait(?:s|ing)?\s+(?:for|on)\s+{_WAITED_FOR}
  | \bawaiting\s+{_WAITED_FOR}
  | \b(?:ready|sent|submitted|prepared|saved|scoped)\s+for\s+(?:
        (?:the\s+)?owner\b
      | (?:your|her|(?:{_WHO}|owner)'s|the\s+owner's|owner)\s+{_ASK}{_END}
      | (?:visual\s+)?(?:review|approval|selection|testing){_END}
      | {_WHO}\s*$
    )
  | \bneeds?\s+(?:your|her|(?:{_WHO}|owner)'s)\s+{_ASK}{_END}
    """,
    re.IGNORECASE | re.VERBOSE,
)


def waits_on_person(title: str, said: bool | None = None) -> bool:
    """True when the checkpoint waits for the person: the agent said so (said), or, when it
    said nothing, the title reads that way."""
    if said is not None:
        return said
    return bool(WAITS.search(title or ""))
