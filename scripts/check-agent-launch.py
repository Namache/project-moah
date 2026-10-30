"""Check that an installed package's agent command works: the session brief and an MCP handshake.

Usage: python scripts/check-agent-launch.py COMMAND [ARGS...]
Example: python scripts/check-agent-launch.py project-moah-mcp

Runs against a throwaway database, so it never touches real data.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

TIMEOUT = 60


def read_line(stream, timeout: float) -> str:
    """One line from the server's stdout, or an error if it does not answer in time."""
    result: list[str] = []
    reader = threading.Thread(
        target=lambda: result.append(stream.readline()), daemon=True
    )
    reader.start()
    reader.join(timeout)
    if not result or not result[0]:
        raise SystemExit("The MCP server did not answer.")
    return result[0]


def main(command: list[str]) -> int:
    if not command:
        print(__doc__, file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as folder:
        env = {**os.environ, "PROJECT_BRAIN_DB_PATH": str(Path(folder) / "check.db")}

        brief = subprocess.run(
            [*command, "--brief", "--cwd", folder],
            check=False,
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        if brief.returncode != 0 or not brief.stdout.strip():
            print(brief.stderr, file=sys.stderr)
            raise SystemExit(f"The session brief failed (exit {brief.returncode}).")
        print(f"Brief: {len(brief.stdout.splitlines())} lines")

        server = subprocess.Popen(
            [*command, "--agent", "package-check"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:

            def send(message: dict) -> None:
                server.stdin.write(json.dumps(message) + "\n")
                server.stdin.flush()

            send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "package-check", "version": "1"},
                    },
                }
            )
            hello = json.loads(read_line(server.stdout, TIMEOUT))
            name = hello["result"]["serverInfo"]["name"]
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            listed = json.loads(read_line(server.stdout, TIMEOUT))["result"]["tools"]
            tools = {tool["name"] for tool in listed}
            if "brain_context_pack" not in tools:
                raise SystemExit(f"brain_context_pack is missing: {sorted(tools)}")
            print(f"MCP: {name} answered with {len(tools)} tools")
        finally:
            server.stdin.close()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
