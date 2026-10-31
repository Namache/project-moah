"""Run the packaged API and frontend for the native desktop window."""

import asyncio
import os
import socket
import sys
from contextlib import suppress
from pathlib import Path
from threading import Thread

import uvicorn

from app.core.resources import resource_path
from app.main import create_app


async def serve() -> bool:
    """Start on an available loopback port and announce it after startup succeeds."""
    token = os.getenv("PROJECT_BRAIN_DESKTOP_TOKEN")
    if not token:
        print("PROJECT_BRAIN_DESKTOP_TOKEN is required", file=sys.stderr)
        return False

    frontend_dist = resource_path("frontend/dist")
    if not getattr(sys, "frozen", False) and (override := os.getenv("PROJECT_BRAIN_FRONTEND_DIST")):
        frontend_dist = Path(override)
    application = create_app(frontend_dist=frontend_dist, desktop_token=token, warm_usage=True)
    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        access_log=False,
        proxy_headers=False,
    )
    server = uvicorn.Server(config)

    def stop_when_stdin_closes() -> None:
        """Let Electron close its pipe to stop the service on every platform."""
        if sys.stdin is None:
            return
        while os.read(sys.stdin.fileno(), 1):
            pass
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(setattr, server, "should_exit", True)

    loop = asyncio.get_running_loop()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        Thread(target=stop_when_stdin_closes, daemon=True).start()

        async def announce_ready() -> None:
            while not server.started and not server.should_exit:
                await asyncio.sleep(0.01)
            if server.started:
                print(f"PROJECT_BRAIN_READY {port}", flush=True)

        announcer = asyncio.create_task(announce_ready())
        try:
            await server.serve(sockets=[listener])
        finally:
            announcer.cancel()
            with suppress(asyncio.CancelledError):
                await announcer

    return server.started


def main() -> int:
    if "--connect" in sys.argv:
        from app.services.agent_connect import main as connect_main

        return connect_main()
    if "--mcp" in sys.argv:
        # The same executable also serves agents over stdio: `project-brain-backend --mcp`.
        from app.mcp.server import main as mcp_main

        return mcp_main([a for a in sys.argv[1:] if a != "--mcp"])
    try:
        return 0 if asyncio.run(serve()) else 1
    except Exception as error:
        print(f"Project Moah failed to start: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
