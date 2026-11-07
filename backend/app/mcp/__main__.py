import sys

from app.services.hook_text import nothing_to_record

# A turn that did not end on a question needs nothing else: end before loading the database.
if nothing_to_record(sys.argv[1:]):
    raise SystemExit(0)

from app.mcp.cli import main  # noqa: E402 - only once the hook has something to record

raise SystemExit(main())
