"""Build the platform-native, self-contained API sidecar for Electron packaging."""

import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    frontend = repo / "frontend"
    built_index = frontend / "dist/index.html"
    if not built_index.is_file():
        print("Build the frontend first: cd frontend && npm run build", file=sys.stderr)
        return 1
    source_files = [
        *frontend.joinpath("src").rglob("*"),
        frontend / "index.html",
        frontend / "package.json",
        frontend / "vite.config.ts",
    ]
    if any(
        path.is_file() and path.stat().st_mtime > built_index.stat().st_mtime
        for path in source_files
    ):
        print(
            "Frontend output is older than its source. Run npm run build --prefix frontend first.",
            file=sys.stderr,
        )
        return 1
    if importlib.util.find_spec("PyInstaller") is None:
        print(
            "Install PyInstaller in this Python environment before building.",
            file=sys.stderr,
        )
        return 1

    # Which build this is, so an agent session still running an older one can be told to restart.
    build_info = repo / "build/build_info.json"
    build_info.parent.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    build_info.write_text(
        json.dumps({"stamp": int(time.time()), "commit": commit or None}), encoding="utf-8"
    )

    # A folder build, not --onefile: a one-file executable unpacks itself into a temporary folder
    # on every start, which cost about a second for each agent session's brief and MCP server.
    # The executable keeps its path (desktop/bin/project-brain-backend) with its libraries in
    # desktop/bin/_internal beside it, so agents connected with the old path keep working.
    staging = repo / "build/pyinstaller-dist"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--name",
        "project-brain-backend",
        "--distpath",
        str(staging),
        "--workpath",
        str(repo / "build/pyinstaller"),
        "--specpath",
        str(repo / "build/pyinstaller"),
        "--paths",
        str(repo / "backend"),
        "--add-data",
        f"{repo / 'backend/alembic.ini'}:backend",
        "--add-data",
        f"{build_info}:backend",
        "--add-data",
        f"{repo / 'backend/migrations'}:backend/migrations",
        "--add-data",
        f"{repo / 'frontend/dist'}:frontend/dist",
        "--collect-submodules",
        "sqlalchemy.dialects.sqlite",
        "--collect-submodules",
        "alembic",
        "--collect-submodules",
        "mcp.server",
        "--collect-submodules",
        "mcp.shared",
        "--collect-submodules",
        "mcp.types",
        "--collect-data",
        "mcp",
        "--copy-metadata",
        "mcp",
        "backend/app/desktop_server.py",
    ]
    result = subprocess.call(command, cwd=repo)
    if result != 0:
        return result
    bin_dir = repo / "desktop/bin"
    shutil.rmtree(bin_dir, ignore_errors=True)
    shutil.move(staging / "project-brain-backend", bin_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
