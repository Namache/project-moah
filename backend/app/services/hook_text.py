"""What an agent's hook is handed, read without loading the database.

Hooks run at every session start, every turn and every message, so this module uses only the
standard library: a turn that does not end on a question costs a Python start and nothing else
(the entry points check ``nothing_to_record`` before they load the rest of Project Moah).
"""

from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from typing import IO

HOOK_INPUT_LIMIT = 1 << 20  # characters: an agent's last message can be long
TRANSCRIPT_TAIL = 1 << 18  # bytes read from the end of a transcript
VALID_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

FENCE = re.compile(r"^\s*(```|~~~).*?(^\s*\1[^\n]*$|\Z)", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+")
ASKS = re.compile(r"\?(?=[\s\"'”’)*_]|$)")
SENTENCE = re.compile(r"[^.!?\n]*\?")
# Questions that ask for nothing: a turn ending on only these is not waiting for the person.
COURTESY = re.compile(
    r"^\W*(?:so|also|and)?,?\s*(?:is there\s+)?(?:anything else|what else|"
    r"any (?:other |more |further )?questions|"
    r"(?:does|did|do) (?:that|this|it|these|those) (?:all )?(?:help|make sense|work for you|"
    r"look (?:good|right|ok(?:ay)?))|sounds? good|ok(?:ay)?|all good|got it)\b",
    re.IGNORECASE,
)

_taken: tuple[object, dict] | None = None  # standard input, read once per process


def valid_id(value: object) -> str | None:
    return value if isinstance(value, str) and VALID_ID.match(value) else None


def read_hook_input(stream: IO[str] | None = None, timeout: float = 1.0) -> dict:
    """The JSON a hook gets on standard input, or {} when there is none.

    Never blocks for long: run by hand or by another agent, standard input may stay open. Read
    once: a second call for the same stream returns what the first one read."""
    global _taken
    stream = stream if stream is not None else sys.stdin
    if _taken is not None and _taken[0] is stream:
        return _taken[1]
    try:
        if stream is None or stream.isatty():
            return {}
    except (OSError, ValueError):
        return {}
    box: list[str] = []

    def read() -> None:
        try:
            box.append(stream.read(HOOK_INPUT_LIMIT))
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    data: dict = {}
    if box:
        try:
            parsed = json.loads(box[0])
        except ValueError:
            parsed = {}
        data = parsed if isinstance(parsed, dict) else {}
    _taken = (stream, data)
    return data


def asks(paragraph: str) -> bool:
    """Whether a paragraph asks something: a question mark ends a sentence outside code."""
    plain = URL.sub("", INLINE_CODE.sub("", paragraph))
    return ASKS.search(plain) is not None


def _courtesy_only(text: str) -> bool:
    plain = URL.sub("", INLINE_CODE.sub("", text))
    asked = [s.strip() for s in SENTENCE.findall(plain) if s.strip(" ?")]
    return bool(asked) and all(COURTESY.match(s) for s in asked)


def question_parts(message: str | None) -> tuple[list[str], int] | None:
    """The message's paragraphs and where the question it ends on starts, or None.

    The question is the run of paragraphs at the end that ask something, with a heading such as
    "Questions:" just before it and one closing line after it ("Tell me and I'll start."). None
    when the message does not end on a question, or only asks "Anything else?" and the like.
    Code blocks, inline code and links never count as asking."""
    text = FENCE.sub("", (message or "").replace("\r\n", "\n")).strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return None
    end = len(paragraphs)
    if end > 1 and not asks(paragraphs[-1]) and asks(paragraphs[-2]):
        if "\n" not in paragraphs[-1] and len(paragraphs[-1]) <= 200:
            end -= 1  # a closing line belongs to the question
    start = end
    while start > 0 and asks(paragraphs[start - 1]):
        start -= 1
    if start == end:
        return None
    heading = paragraphs[start - 1] if start else ""
    if heading.endswith(":") and "\n" not in heading and len(heading) <= 80:
        start -= 1
    if _courtesy_only("\n\n".join(paragraphs[start:])):
        return None
    return paragraphs, start


def last_message(transcript_path: object) -> str | None:
    """The agent's last words from a Claude Code transcript, for hooks that are not given them
    (Claude Code before last_assistant_message, or a Codex build without it)."""
    if not isinstance(transcript_path, str) or not transcript_path.endswith(".jsonl"):
        return None
    path = Path(transcript_path)
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - TRANSCRIPT_TAIL))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            texts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            if any(text.strip() for text in texts):
                return "\n\n".join(texts)
    return None


def stop_message(hook_input: dict) -> str | None:
    """The words a Stop hook's turn ended on, unless the hook is already running again."""
    if hook_input.get("stop_hook_active") is True or valid_id(hook_input.get("session_id")) is None:
        return None
    message = hook_input.get("last_assistant_message")
    if isinstance(message, str) and message.strip():
        return message
    return last_message(hook_input.get("transcript_path"))


def nothing_to_record(argv: list[str]) -> bool:
    """For ``--hook stop``: True when the turn did not end on a question, so the command can
    end before it loads the database. Every other command goes on as usual."""
    if "--hook" not in argv:
        return False
    at = argv.index("--hook")
    if argv[at + 1 : at + 2] != ["stop"]:
        return False
    return question_parts(stop_message(read_hook_input())) is None
