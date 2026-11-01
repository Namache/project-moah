# Claude Code guidance

Asked to install or connect Project Moah? Follow [INSTALL.md](INSTALL.md).

This repository uses Project Moah as the canonical source for task state, project decisions, checkpoints and durable development memory.

When the Project Moah MCP server is connected (Claude Code: see `docs/MCP.md`):

- Call `brain_context_pack` when you start or switch tasks, when a request names an ID you have no pack for, when you need the history behind something (decisions, known bugs, traps), before changing an area you have not touched this session, and when debugging; then read the source files it names. Skip it for follow-ups and small edits. Do not infer completion from conversation history.
- Keep projects separate. If the project is ambiguous, ask; never guess.
- After meaningful work, call `brain_create_checkpoint`. Suggest durable changes with `brain_create_proposal` for a person to review.
- Never change locked memory. Ideas are not requirements.

Before claiming completion, check the acceptance criteria, run the relevant tests, and report what was actually verified, separating implemented, tested, verified by hand, and not yet verified. Keep this file short: product state belongs in Project Moah, not here.
