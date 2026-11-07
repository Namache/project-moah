"""Picking one task's lines out of an agent's checkpoint notes (app/services/review_notes.py).

The notes are written the way agents write them in a busy project: one note for a batch of tasks,
sentences that name several tasks at once, decisions and bugs named beside tasks."""

from app.services.review_notes import Note, draft, pick

BATCH = (
    "Merged the camp helper's 3 commits (TRAIL-12 bedroll goal, TRAIL-14 keeper walk, "
    "TRAIL-17 lantern trophy with the chest fix). Spreadsheet conflicts: kept main's."
)


def test_a_sentence_naming_several_tasks_keeps_only_this_tasks_part() -> None:
    assert pick(BATCH, "TRAIL-17", "TRAIL") == ["Lantern trophy with the chest fix"]
    assert pick(BATCH, "TRAIL-14", "TRAIL") == ["Keeper walk"]
    # Naming a task only in a list says nothing about it.
    assert pick("Covers TRAIL-12, TRAIL-14 and TRAIL-17.", "TRAIL-17", "TRAIL") == []


def test_sentences_after_a_task_is_named_belong_to_it() -> None:
    text = (
        "Three tasks in this batch. The TRAIL-17 part: the trophy drops once per night "
        "(DEC-31); a test checks 400 nights. The TRAIL-12 part: bedroll goal added. "
        "Its icon is a placeholder."
    )
    assert pick(text, "TRAIL-17", "TRAIL") == [
        "The TRAIL-17 part: the trophy drops once per night (DEC-31); a test checks 400 nights."
    ]
    assert pick(text, "TRAIL-12", "TRAIL") == [
        "The TRAIL-12 part: bedroll goal added. Its icon is a placeholder."
    ]


def test_decisions_and_bugs_are_not_tasks() -> None:
    text = "Owner to pick for TRAIL-20 (BUG-9). Open question on TRAIL-17: one trophy per boss?"
    assert pick(text, "TRAIL-17", "TRAIL") == ["Open question on TRAIL-17: one trophy per boss?"]


def test_a_note_filed_under_the_task_is_about_it_until_another_task_is_named() -> None:
    text = "- Edited the balance notes\n- Pushed as build-9\n- TRAIL-30 still needs a sim run"
    assert pick(text, "TRAIL-17", "TRAIL", filed_here=True) == [
        "Edited the balance notes",
        "Pushed as build-9",
    ]
    # Filed elsewhere, it says nothing about this task.
    assert pick(text, "TRAIL-17", "TRAIL") == []


def test_each_line_starts_over_unless_it_follows_a_heading() -> None:
    text = (
        "TRAIL-12: bedroll goal added.\n"
        "Spanish text still missing.\n"
        "TRAIL-17:\n"
        "- trophy lands in storage once\n"
        "- glow animated"
    )
    assert pick(text, "TRAIL-17", "TRAIL") == ["Trophy lands in storage once", "Glow animated"]
    assert pick(text, "TRAIL-12", "TRAIL") == ["Bedroll goal added."]


def note(task_id: str, **fields: str) -> Note:
    base = dict(
        title="Note",
        created_at=None,
        agent="claude",
        summary="",
        completed_work="",
        remaining_work="",
        problems="",
        next_steps="",
    )
    return Note(task_id=task_id, **{**base, **fields})


def test_a_draft_collects_the_work_and_takes_whats_left_from_the_newest_note() -> None:
    older = note(
        "t17",
        summary="Trophy modelled in 3D, waiting for the owner's pick.",
        completed_work="Three trophy options rendered\nMockups in the decisions folder",
        remaining_work="Owner picks an option",
    )
    newer = note(
        "t12",
        summary=BATCH,
        completed_work="",
        remaining_work="TRAIL-12 icon is a placeholder. Owner to pick the colour.",
        next_steps="TRAIL-17: play one night to see the trophy arrive.",
    )
    picked = draft([newer, older], "t17", "TRAIL-17")
    assert picked.done == [
        "Three trophy options rendered",
        "Mockups in the decisions folder",
        "Lantern trophy with the chest fix",
    ]
    # The newest note about this task lists nothing left for it (its leftover is another
    # task's), and the older note's "owner picks" has since been settled.
    assert picked.not_done == []
    assert picked.next_steps == ["Play one night to see the trophy arrive."]
    assert picked.summary == "Trophy modelled in 3D, waiting for the owner's pick."
    assert picked.left_out is True


def test_a_single_task_note_is_shown_whole() -> None:
    only = note(
        "t17",
        summary="Trophy done.",
        completed_work="1. Trophy placed in camp storage\n2. Folk react to it",
        problems="Glow flickers at 30 fps",
    )
    picked = draft([only], "t17", "TRAIL-17")
    assert picked.done == ["Trophy placed in camp storage", "Folk react to it"]
    assert picked.not_done == ["Glow flickers at 30 fps"]
    assert picked.summary == "Trophy done." and picked.left_out is False
