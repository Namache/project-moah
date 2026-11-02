# Claude Code guidance

Asked to install or connect Project Moah? Follow [INSTALL.md](INSTALL.md).

This repository uses Project Moah as the canonical source for task state, project decisions, checkpoints and durable development memory.

When the Project Moah MCP server is connected (Claude Code: see `docs/MCP.md`):

- Call `brain_context_pack` when you continue unfinished work from an earlier session, start or switch tasks, meet an ID you have no pack for, need past decisions or known traps, change an area new to you this session, or debug; then read the source files it names. Skip it only for small edits, or when a pack from this session already covers the work. Do not infer completion from conversation history.
- Check Project Moah before asking the person anything: their earlier answers are recorded there. Ask only what Moah and the code leave open.
- Keep projects separate. If the project is ambiguous, ask; never guess.
- Writing to Project Moah needs no permission: record answers and settled choices as decisions, and call `brain_create_checkpoint` before your final reply on work that changed files. Suggest changes to global rules and locked memory with `brain_create_proposal` for a person to review.
- Never change locked memory. Ideas are not requirements.

Before claiming completion, check the acceptance criteria, run the relevant tests, and report what was actually verified, separating implemented, tested, verified by hand, and not yet verified. Keep this file short: product state belongs in Project Moah, not here.
