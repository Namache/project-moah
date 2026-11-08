import errno
import os
import queue
import socket
import subprocess
import sys
from pathlib import Path
from threading import Thread

import pytest
from httpx import ASGITransport, AsyncClient, Client

from app import desktop_server
from app.core.resources import resource_path
from app.main import create_app


@pytest.mark.anyio
async def test_desktop_serves_frontend_and_protects_api(database_url: str, tmp_path: Path) -> None:
    frontend_dist = tmp_path / "dist"
    (frontend_dist / "assets").mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<html>Project Moah</html>")
    (frontend_dist / "assets/app.js").write_text("console.log('desktop')")
    application = create_app(
        database_url, frontend_dist=frontend_dist, desktop_token="desktop-test-token"
    )
    headers = {"X-Project-Brain-Token": "desktop-test-token"}

    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1:54321"
        ) as client:
            assert (await client.get("/")).text == "<html>Project Moah</html>"
            assert (await client.get("/projects/example")).text == "<html>Project Moah</html>"
            assert (await client.get("/assets/app.js")).text == "console.log('desktop')"
            assert (await client.get("/assets/missing.js")).status_code == 404

            assert (await client.get("/api/health")).status_code == 401
            assert (await client.get("/api/health", headers=headers)).json() == {"status": "ok"}
            assert (await client.get("/api/projects", headers=headers)).json() == []
            assert (await client.get("/api/unknown", headers=headers)).status_code == 404
            assert (await client.post("/api/projects", json={"name": "Blocked"})).status_code == 401


@pytest.mark.anyio
async def test_desktop_rejects_unexpected_host(database_url: str, tmp_path: Path) -> None:
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("Project Moah")
    application = create_app(
        database_url, frontend_dist=frontend_dist, desktop_token="desktop-test-token"
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://example.com"
        ) as client:
            response = await client.get(
                "/api/health", headers={"X-Project-Brain-Token": "desktop-test-token"}
            )
            assert response.status_code == 400


def test_resources_use_pyinstaller_bundle_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.core.resources.sys._MEIPASS", str(tmp_path), raising=False)
    assert resource_path("frontend/dist") == tmp_path / "frontend/dist"


def skip_without_loopback() -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
            pass
    except PermissionError as error:
        if error.errno == errno.EPERM:
            pytest.skip("This sandbox blocks loopback sockets")
        raise


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_service_keeps_last_runs_port_so_the_window_keeps_its_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skip_without_loopback()
    wanted = free_port()
    with desktop_server.loopback_listener(wanted) as listener:
        assert listener.getsockname() == ("127.0.0.1", wanted)
        # Taken (here by the first listener): any free port instead of failing to start.
        with desktop_server.loopback_listener(wanted) as other:
            assert other.getsockname()[1] not in (wanted, 0)
    # Free again right after it closed.
    with desktop_server.loopback_listener(wanted) as again:
        assert again.getsockname()[1] == wanted
    with desktop_server.loopback_listener(None) as anywhere:
        assert anywhere.getsockname()[1] > 0

    for value, port in [("51234", 51234), ("80", None), ("70000", None), ("x", None), ("", None)]:
        monkeypatch.setenv(desktop_server.PORT_ENV, value)
        assert desktop_server.preferred_port() == port


def test_desktop_server_announces_port_and_stops_on_stdin_eof(tmp_path: Path) -> None:
    skip_without_loopback()
    wanted = free_port()

    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("Project Moah desktop")
    environment = os.environ.copy()
    environment.update(
        PROJECT_BRAIN_DESKTOP_TOKEN="desktop-integration-token",
        PROJECT_BRAIN_FRONTEND_DIST=str(frontend_dist),
        PROJECT_BRAIN_DB_PATH=str(tmp_path / "desktop.db"),
        PROJECT_BRAIN_PORT=str(wanted),
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "app.desktop_server"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdin is not None
    output: queue.Queue[str] = queue.Queue()
    Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()

    try:
        ready = output.get(timeout=15)
        assert ready.startswith("PROJECT_BRAIN_READY ")
        port = int(ready.removeprefix("PROJECT_BRAIN_READY ").strip())
        assert port == wanted  # the port Electron remembered from the last run
        with Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            assert client.get("/").text == "Project Moah desktop"
            assert client.get("/api/health").status_code == 401
            assert client.get(
                "/api/health", headers={"X-Project-Brain-Token": "desktop-integration-token"}
            ).json() == {"status": "ok"}

        process.stdin.close()
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_diagnostics_answer_while_the_service_waits_on_its_input(tmp_path: Path) -> None:
    """Like the desktop app: Electron keeps the service's input open, and Diagnostics runs Git.

    On Windows, Git that inherits the waiting input can hang; Diagnostics must still answer.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
            pass
    except PermissionError as error:
        if error.errno == errno.EPERM:
            pytest.skip("This sandbox blocks loopback sockets")
        raise
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("Project Moah desktop")
    environment = os.environ.copy()
    environment.update(
        PROJECT_BRAIN_DESKTOP_TOKEN="desktop-diagnostics-token",
        PROJECT_BRAIN_FRONTEND_DIST=str(frontend_dist),
        PROJECT_BRAIN_DB_PATH=str(tmp_path / "desktop.db"),
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "app.desktop_server"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert process.stdout is not None and process.stdin is not None
    output: queue.Queue[str] = queue.Queue()
    Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()
    try:
        port = int(output.get(timeout=15).removeprefix("PROJECT_BRAIN_READY ").strip())
        headers = {"X-Project-Brain-Token": "desktop-diagnostics-token"}
        with Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
            report = client.get("/api/system/diagnostics", headers=headers)
            assert report.status_code == 200
            assert report.json()["database"]["integrity"] == "ok"
        process.stdin.close()
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
