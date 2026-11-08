"""Run the packaged API and frontend for the native desktop window."""

import asyncio
import os
import socket
import sys
from contextlib import suppress
from pathlib import Path
from threading import Thread

from app.core.resources import resource_path

PORT_ENV = "PROJECT_BRAIN_PORT"


def preferred_port() -> int | None:
    """The port the desktop app used last time, which Electron passes back on the next start."""
    value = os.getenv(PORT_ENV, "")
    return int(value) if value.isdigit() and 1024 <= int(value) <= 65535 else None


def loopback_listener(preferred: int | None = None) -> socket.socket:
    """A listening loopback socket, on the preferred port when it is free, else on any free port.

    The window's page storage (theme, language, folded sections and other small choices) belongs
    to its address, port included, so a new port on every start would forget them all.
    """
    for port in (preferred, 0) if preferred else (0,):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Lets the port be used again right after the last run closed. Windows needs no such
            # option, and there it would let another program share the port.
            if port and os.name != "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            return listener
        except OSError:
            listener.close()
            if not port:
                raise
    raise OSError("No loopback port is free")


def wait_for_end_of_input(fd: int, poll_seconds: float = 0.25) -> None:
    """Return once the other end of this input (Electron's pipe) is closed.

    On Windows a read that waits on a pipe holds the pipe for as long as it waits, and anything
    else that touches the service's standard input meanwhile waits too. Loading numpy for the
    speech engine does, while it holds the interpreter lock, so the whole service froze (Settings
    and Diagnostics load it). There the pipe is only peeked at, which never waits.
    """
    if os.name == "nt" and _peek_windows_pipe_until_closed(fd, poll_seconds):
        return
    # Elsewhere, and on Windows when someone starts the service by hand from a console.
    while os.read(fd, 1):
        pass


def _peek_windows_pipe_until_closed(fd: int, poll_seconds: float) -> bool:
    """False, at once, when the input is no pipe."""
    import ctypes
    import msvcrt
    import time
    from ctypes import wintypes

    file_type_pipe = 3
    kernel32 = ctypes.WinDLL("kernel32")
    handle = msvcrt.get_osfhandle(fd)
    kernel32.GetFileType.argtypes = [wintypes.HANDLE]
    kernel32.GetFileType.restype = wintypes.DWORD
    if kernel32.GetFileType(handle) != file_type_pipe:
        return False
    kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL
    waiting = wintypes.DWORD()
    # Fails once the other end is closed (ERROR_BROKEN_PIPE).
    while kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(waiting), None):
        if waiting.value:
            os.read(fd, waiting.value)  # this much is there already, so this never waits
        else:
            time.sleep(poll_seconds)
    return True


async def serve() -> bool:
    """Start on the last run's loopback port, or a free one, and announce it once started."""
    # Imported here, not at the top: the same executable serves agents (--mcp) and their
    # start-up brief, which need neither the web server nor the app's HTTP routes.
    import uvicorn

    from app.core import error_log
    from app.main import create_app
    from app.services.agent_connect import refresh_connections

    error_log.install("service")
    # After an update, agents connected before keep working without Connect. A throwaway
    # database (the package checks) means nobody's agents are involved.
    if not os.getenv("PROJECT_BRAIN_DB_PATH"):
        Thread(target=refresh_connections, name="agent-refresh", daemon=True).start()

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
        wait_for_end_of_input(sys.stdin.fileno())
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(setattr, server, "should_exit", True)

    loop = asyncio.get_running_loop()

    with loopback_listener(preferred_port()) as listener:
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
        from app.services.hook_text import nothing_to_record

        # A turn that did not end on a question needs nothing else (services/hook_text.py).
        if nothing_to_record(sys.argv[1:]):
            return 0
        # The same executable also serves agents over stdio: `project-brain-backend --mcp`.
        from app.mcp.cli import main as mcp_main
        from app.services.system import open_app_in_tray

        if "--brief" not in sys.argv and "--hook" not in sys.argv:
            open_app_in_tray()
        return mcp_main([a for a in sys.argv[1:] if a != "--mcp"])
    try:
        return 0 if asyncio.run(serve()) else 1
    except Exception as error:
        print(f"Project Moah failed to start: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
