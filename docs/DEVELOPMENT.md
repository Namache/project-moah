# Development

## Layout

`backend/` is the FastAPI service, SQLAlchemy models, Alembic migrations, and the MCP server (`app/mcp`). `frontend/` is the React app; its Help articles are Markdown in `src/content/help/`, and vendor setup commands live only in `src/content/integrations.ts`. `desktop/` is the Electron shell and Flatpak files. `scripts/` holds the checks and build scripts.

## Everyday checks

```bash
./scripts/check.sh          # backend tests and lint, frontend types, tests and build
```

Backend only, from `backend/`: `python -m pytest -q`, `ruff check .`, `ruff format --check .`.

**Test on the Python the app ships with.** The packaged app runs Python 3.13 from the Flatpak SDK. A newer local Python once hid a failure that only appeared when packaged. Run the backend tests there too:

```bash
flatpak run --filesystem="$PWD" --cwd="$PWD/backend" --command=sh org.freedesktop.Sdk//25.08 -c "../.venv-flatpak/bin/python -m pytest -q"
```

Create that environment once with the build steps in [desktop packaging](DESKTOP_PACKAGING.md).

## Rules for changes

- Every project-owned table carries `project_id` and links to other project-owned tables through composite foreign keys. Add a test that another project's record is "not found".
- Domain rules live in services. HTTP routes and the MCP server only translate.
- Schema changes need an Alembic migration with a working downgrade, and a test that upgrades a populated older database.
- Anything an agent can do must respect locks and attribution. Add the case to the MCP tests.
- Long SQL files and the MCP tool list are exempt from the line-length rule; nothing else is.

## Tests worth knowing

`test_search.py` (index sync, scope, ranking, hostile queries), `test_context.py` (the safety rules, budgets, handoff), `test_files.py` (real temporary Git repositories), `test_proposals.py`, and `test_mcp.py`, which runs the real server as a subprocess over stdio. Frontend tests include an automated accessibility scan (`accessibility.test.tsx`) that checks structure; contrast and layout still need a look by eye.

## Packaging

See [desktop packaging](DESKTOP_PACKAGING.md). Build the frontend before the sidecar, and the sidecar before the Electron directory. Updating an installed Flatpak with `flatpak install --reinstall` deletes its data; update by opening the bundle or by running `flatpak install` without that flag.
