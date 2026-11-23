"""What an agent's hook is handed, read without loading the database.

Hooks run at every session start, every turn, every message and every tool call, so this module
uses only the standard library: a turn that does not end on a question, or a tool call that is not
one of Moah's own, costs a Python start and nothing else (the entry points check
``nothing_to_record`` before they load the rest of Project Moah).
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
    r"look (?:good|right|ok(?:ay)?)))\b"
    # "Got it?", "Okay?", "Sounds good?" and "All good?" ask for nothing only as the whole
    # question: "Got it, should I push?" and "Ok, which one do you want?" are real questions.
    r"|^\W*(?:(?:so|also|and)\W+)?(?:sounds? good|ok(?:ay)?|all good|got it)\W*$"
    # "What's next?" after a hand-over asks the person for nothing, but only when it is the whole
    # question (not "What's next for the migration?"), alone or after a short "Got it," or "Done,".
    # Questions that ask for a go-ahead ("Shall I continue?", "Should I push?") are real: not here.
    r"|^\W*(?:(?:so|and|got it|done|ok(?:ay)?|understood|thanks?)\W+)*"
    r"what(?:['’]?s| is)? next\W*$",
    re.IGNORECASE,
)

# The Moah tools whose calls say what a chat works on: the ones that make a task the session's
# task in the MCP server (mcp/tools/*.py, ``working.set``). The first three also write a question
# or a report to Review.
REVIEW_TOOLS = ("brain_ask_person", "brain_submit_review", "brain_create_checkpoint")
TASK_TOOLS = (
    *REVIEW_TOOLS,
    "brain_context_pack",
    "brain_create_task",
    "brain_update_task",
)
# Agents name an MCP tool "mcp__<server>__<tool>". The desktop app's own server is project-brain,
# the one Connect writes is project-moah; some clients turn hyphens in a server name into
# underscores.
MOAH_TOOL = re.compile(r"^mcp__project[-_](?:moah|brain)__(\w+)$")

_taken: tuple[object, dict] | None = None  # standard input, read once per process


def valid_id(value: object) -> str | None:
    return value if isinstance(value, str) and VALID_ID.match(value) else None


def moah_tool(name: object) -> str | None:
    """The short name ("brain_ask_person") of a Moah tool whose call tells a hook what the chat
    works on, from the tool name the agent gives its hook, or None for any other tool."""
    found = MOAH_TOOL.match(name) if isinstance(name, str) else None
    return found[1] if found is not None and found[1] in TASK_TOOLS else None


def _json_object(text: str) -> dict | None:
    if not text.lstrip().startswith("{"):
        return None
    try:
        found = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return found if isinstance(found, dict) else None


def _from_blocks(blocks: object) -> dict:
    """The JSON object in the first text block of an MCP result's content, else {}."""
    for block in blocks if isinstance(blocks, list) else ():
        if isinstance(block, dict) and block.get("type") == "text":
            found = _json_object(block["text"]) if isinstance(block.get("text"), str) else None
            if found is not None:
                return found
    return {}


def tool_arguments(value: object) -> dict:
    """What a tool call was made with, from the dict or JSON text an agent hands its hook."""
    if isinstance(value, dict):
        return value
    return (_json_object(value) if isinstance(value, str) else None) or {}


def tool_outcome(response: object) -> dict | None:
    """What a Moah tool call gave back, as the tool's own dict, from whatever shape the agent
    hands its hook: that dict, JSON text, a list of text blocks, or an MCP result (Codex's
    shape), where ``structuredContent`` is read before the JSON in ``content``. {} when the tool
    gave back something else (a context pack is plain text), None when the call failed
    (``isError``). Never raises."""
    if isinstance(response, str):
        return _json_object(response) or {}
    if isinstance(response, list):
        return _from_blocks(response)
    if not isinstance(response, dict):
        return {}
    if response.get("isError") is True or response.get("is_error") is True:
        return None
    structured = response.get("structuredContent") or response.get("structured_content")
    if isinstance(structured, dict):
        inner = structured.get("result") if set(structured) == {"result"} else structured
        if isinstance(inner, dict):
            return inner
        return (_json_object(inner) if isinstance(inner, str) else None) or {}
    if "content" in response:
        return _from_blocks(response["content"])
    return response  # the result itself


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
    """The words a Stop hook's turn ended on. Not guarded by ``stop_hook_active``, Claude Code's
    flag for a stop that a hook already continued: Moah's hooks never block a stop, so it would
    protect nothing here, and the wake of a waiting hook (chat_wait.py) may set it for the very
    turn whose question has to be recorded."""
    if valid_id(hook_input.get("session_id")) is None:
        return None
    message = hook_input.get("last_assistant_message")
    if isinstance(message, str) and message.strip():
        return message
    return last_message(hook_input.get("transcript_path"))


def hook_agent(argv: list[str]) -> str:
    """Who a hook command line says it runs for, as the command itself names it (cli.run_hook):
    ``--agent claude`` or ``--agent=claude``, the last one wins, and no ``--agent`` at all is
    Claude Code (the name a hook was written with before Connect passed one)."""
    name = "agent"
    for index, item in enumerate(argv):
        if item == "--agent" and index + 1 < len(argv):
            name = argv[index + 1]
        elif item.startswith("--agent="):
            name = item.split("=", 1)[1]
    return "claude" if name == "agent" else name.strip().casefold()


def option_value(argv: list[str], name: str) -> str | None:
    """What a command line says for ``--name value`` or ``--name=value`` (the last one wins), or
    None. Hooks read their few options themselves: argparse loads the rest of Project Moah's
    command, and some hooks end before that."""
    found = None
    for index, item in enumerate(argv):
        if item == name and index + 1 < len(argv):
            found = argv[index + 1]
        elif item.startswith(f"{name}="):
            found = item.split("=", 1)[1]
    return found


def hook_kind(argv: list[str]) -> str | None:
    """The hook a command line runs (``--hook stop``), or None for any other command."""
    if "--hook" not in argv:
        return None
    found = argv[argv.index("--hook") + 1 : argv.index("--hook") + 2]
    return found[0] if found else None


def nothing_to_record(argv: list[str]) -> bool:
    """For ``--hook stop``: True when the turn did not end on a question. For ``--hook tool``:
    True unless the call was one of Moah's own tools in a chat with a valid session id (the hook
    fires on every tool call an agent makes). The command can then end before it loads the
    database. Every other command goes on as usual."""
    kind = hook_kind(argv)
    if kind == "stop":
        return question_parts(stop_message(read_hook_input())) is None
    if kind == "tool":
        data = read_hook_input()
        return moah_tool(data.get("tool_name")) is None or valid_id(data.get("session_id")) is None
    return False
