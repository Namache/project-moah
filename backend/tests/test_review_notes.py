"""Picking one task's lines out of an agent's checkpoint notes (app/services/review_notes.py).

The notes are written the way agents write them in a busy project: one note for a batch of tasks,
sentences that name several tasks at once, decisions and bugs named beside tasks."""

from app.services.review_notes import Note, draft, pick, task_refs

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


def test_bare_numbers_listed_after_a_task_are_tasks_too() -> None:
    text = (
        "Builds on GitHub: build-12 battle (TRAIL-448, 435, 445, 457), "
        "build-13 camp (TRAIL-449, 432, 441-443, 452)."
    )
    assert task_refs(text, "TRAIL") == {
        "TRAIL-448", "TRAIL-435", "TRAIL-445", "TRAIL-457",
        "TRAIL-449", "TRAIL-432", "TRAIL-441", "TRAIL-442", "TRAIL-443", "TRAIL-452",
    }  # fmt: skip
    # A count or a size after a task is not a task.
    assert task_refs("TRAIL-5, 218 px cards. TRAIL-449, 200 tests pass.", "TRAIL") == {
        "TRAIL-5",
        "TRAIL-449",
    }
    # A list carries on past a bug named with a task, and a commit hash is not a number.
    assert task_refs("menus (TRAIL-456 with BUG-175, 450), 914b8a71 TRAIL-438", "TRAIL") == {
        "TRAIL-456",
        "TRAIL-450",
        "TRAIL-438",
    }


def test_a_task_only_listed_with_others_keeps_the_line_they_share_never_a_bare_list() -> None:
    text = (
        "The three batches are on GitHub: build-12 battle (TRAIL-448, 435, 445, 457), "
        "build-13 camp (TRAIL-449, 432, 441, 452), build-14 waits for every foe (BUG-181)."
    )
    assert pick(text, "TRAIL-432", "TRAIL") == ["Build-13 camp (TRAIL-449, 432, 441, 452)"]
    # This one used to read "432, 441, 452, plus a".
    camp = "Started helpers: and camp (TRAIL-449, 432, 441, 452, plus a TRAIL-464 mockup)."
    assert pick(camp, "TRAIL-449", "TRAIL") == [
        "Camp (TRAIL-449, 432, 441, 452, plus a TRAIL-464 mockup)"
    ]


def test_a_label_before_or_after_the_task_reads_as_its_own_line() -> None:
    text = (
        "Updated the design doc (kill pop TRAIL-253, nested tooltips TRAIL-269, pluck TRAIL-264, "
        "Plants nature TRAIL-229/DEC-184, Settings TRAIL-242)."
    )
    assert pick(text, "TRAIL-269", "TRAIL") == ["Nested tooltips"]
    # Used to read "/DEC-184, Settings".
    assert pick(text, "TRAIL-229", "TRAIL") == ["Plants nature"]
    # One word says nothing the task's title doesn't; nor does the rest of the list.
    assert pick(text, "TRAIL-264", "TRAIL") == []
    batch = "Merged: TRAIL-448 Slimelings flee, TRAIL-435 218 px cards, TRAIL-445 XP once."
    assert pick(batch, "TRAIL-435", "TRAIL") == ["218 px cards"]


def test_refs_hashes_and_list_headings_alone_say_nothing() -> None:
    text = (
        "Camp helper batch: TRAIL-449 (DEC-379) 3784f03b, TRAIL-432 (DEC-389) f32f5313, "
        "TRAIL-452 (DEC-393, WARN-051 fix) d7ce1e9f, all set to review"
    )
    assert [pick(text, ref, "TRAIL") for ref in ("TRAIL-449", "TRAIL-432", "TRAIL-452")] == [
        [],
        [],
        [],
    ]
    # A commit hash in front of the task's own line is dropped with the ref.
    assert pick("1644e4b8 TRAIL-256 butler shadows on the court page.", "TRAIL-256", "TRAIL") == [
        "Butler shadows on the court page."
    ]


def test_words_heading_a_list_of_tasks_are_not_one_tasks_line() -> None:
    text = (
        "Owner review of TRAIL-381, TRAIL-382, BUG-135 in the game. Next: TRAIL-415 to TRAIL-418."
    )
    assert pick(text, "TRAIL-381", "TRAIL") == []
    assert "TRAIL-416" in task_refs(text, "TRAIL")
    assert pick("Earlier: TRAIL-415 to TRAIL-418, DEC-337 to DEC-343.", "TRAIL-415", "TRAIL") == []


def test_a_line_that_only_says_where_the_task_is_is_left_out() -> None:
    assert pick("TRAIL-412 stays in review. TRAIL-413 set to review.", "TRAIL-412", "TRAIL") == []
    assert pick("TRAIL-412: in review.", "TRAIL-412", "TRAIL") == []


def test_listed_numbers_keep_the_tasks_zero_padding() -> None:
    text = "build-13 camp (CAMP-001, 002, 003-004) and CAMP-020, 9"
    assert task_refs(text, "CAMP") == {
        "CAMP-001", "CAMP-002", "CAMP-003", "CAMP-004", "CAMP-020", "CAMP-009",
    }  # fmt: skip


def test_test_counts_after_a_task_are_not_tasks() -> None:
    # QA 2026-11-08: our own agents write test counts right after a ref.
    assert task_refs("PROJ-041, 380 passed / 1 skipped", "PROJ") == {"PROJ-041"}
    assert task_refs("CAMP-100, 250 frontend, 352 backend", "CAMP") == {"CAMP-100"}
    # A word that joins a number to more keeps it a task.
    assert task_refs("CAMP-448, 435 with the recheck", "CAMP") == {"CAMP-448", "CAMP-435"}
