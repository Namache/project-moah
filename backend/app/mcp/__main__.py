import sys

from app.services.chat_wait import before_loading

# A hook that has nothing to do (a turn that did not end on a question, a chat with nothing open
# in Review) ends here, before the database is loaded; Claude Code's stop hook waits here too.
code = before_loading(sys.argv[1:])
if code is not None:
    raise SystemExit(code)

from app.mcp.cli import main  # noqa: E402 - only once the command has something to do

raise SystemExit(main())
