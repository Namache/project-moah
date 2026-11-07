---
title: Review
category: Core features
summary: Check what Claude Code and Codex finished, answer their questions, and accept the work or send it back with comments.
keywords: review, inbox, finished, accept, send back, reject, reopen, comments, screenshots, question, blocked, answer, follow-up, criteria, suggestion, proposal, locked
related: tasks, memory, troubleshooting-bad-proposal
---

When Claude Code or Codex finishes a task, the task moves to **Review** and the agent hands you a short report: what it did, what it did not do, how to check it, and screenshots of anything you can see. It only moves to Done when you accept it.

**Review** in the sidebar fills the whole window. On the left is a list of tasks from every project, in three groups:

- *Questions from agents*: an agent stopped in the middle of a task and waits for your reply.
- *Finished work to check*: an agent says the task is done. Accept it or send it back.
- *Reviewed*: what you already accepted or sent back.

Each row shows the task, its column on the board (with the same colours as the board), which agent did it, when it finished, and when you accepted it or sent it back. Press a group's arrow to fold it away; *Reviewed* starts folded, and each group stays as you left it. *Show* picks one project. Use the Up and Down arrows (or J and K) to move through the rows you can see. Drag the line between the list and the report to make either side wider; double-click it to put it back. Each project's *Review* tab shows the same, for that project only.

On the right is the selected report, in colour: green for what was done, red for what was not, and the screenshots. Click a screenshot to see it large. The quote button next to any line copies it into your comment.

Under the report is your comment box. Type, or press the microphone to dictate. Attach files or images with the paperclip, by dragging them in, or by pasting a screenshot.

- **Accept and move to Done** moves the task to *Done* on the board. Nothing else happens: no new tasks are made.
- **Send back** needs a comment or a file. The task goes back to *In progress* with your comments, and the next agent that works on it sees them first. *Open in Claude Code* (or Codex) opens the agent with the fix typed in, for you to read and send. Moah never starts an agent itself.

Changed your mind about accepted work? Select it under *Reviewed* and press **Reopen**. Say what is wrong: the task goes back to *In progress*, and the next agent sees your comment first, as if you had sent it back.

If an agent moved a task to Review without writing a report, Moah shows the task itself: its description and acceptance criteria. The agent's checkpoint notes are folded underneath.

Moving a task on the board counts too. Dragging a task out of Review to *Done* accepts the work, and dragging it to any other column sends it back without a comment. Either way it moves to *Reviewed*, marked *Moved to … on the board*.

## Acceptance criteria and leftovers

While the work waits, the task's acceptance criteria are ticked. Untick any that isn't met before you accept: Accept records your ticks. When you send work back, only the ones you unticked are recorded.

Each line under *Not done* has a **Make a task** button, which makes it a new task in *To do*, related to this one. Only the lines you choose become tasks. A line that became a task shows that task and its column.

## Questions from agents

When an agent can't go on without you (a choice, a fact, an approval), it asks in Review instead of guessing. The task moves to *Blocked* and the question waits under *Questions from agents*, at the top, until you answer it. Pick one of the agent's suggested answers or write your own, then press **Send answer**. The task goes back to *In progress*, and the next agent that opens the project sees your answer first. *Open in Claude Code with my answer* hands it over now.

Agents often ask in the chat instead. Once you connect them (Help, Connect agents), Claude Code and Codex hand Moah the question their turn ends on, so it waits here too, marked as asked by that agent. That needs the task they work on: the one they picked in Moah, or, before they pick one, the task your message names by ID or plainly by its title. Questions that ask for nothing ("Anything else?") and offers after the work is handed over ("Want me to add tests too?") stay out. When you reply in the same chat, the question is settled there and shows as *Answered in the chat*, so Review never keeps one the agent already has an answer to.

Only real questions wait here. A task that is just *Blocked*, by an agent that didn't ask anything or by you on the board, stays on the board and out of Review. Moving a task out of *Blocked* on the board settles its question too.

## Suggestions

Agents can also suggest changes, such as editing a locked decision or adding a known issue. Suggestions wait in the same timeline, marked *Suggestion*. Nothing changes until you accept one. You can **Accept**, **Edit and accept**, or **Dismiss** it, and *Accept all* applies everything waiting in that project, oldest first.

Accepting a change to a locked memory applies it because you reviewed it. The memory stays locked.
