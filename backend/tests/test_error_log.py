import json
import logging
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core import error_log

pytestmark = pytest.mark.anyio


@pytest.fixture
def logs(tmp_path: Path, monkeypatch, database_url: str) -> Path:
    monkeypatch.setenv("PROJECT_BRAIN_DATABASE_URL", database_url)
    monkeypatch.delenv(error_log.DIR_ENV, raising=False)
    desktop = tmp_path / "settings" / "errors-desktop.log"
    desktop.parent.mkdir()
    monkeypatch.setenv(error_log.DESKTOP_LOG_ENV, str(desktop))
    return tmp_path / "logs"


def test_entries_sit_beside_the_database_and_hide_private_text(logs: Path, monkeypatch) -> None:
    home = Path("/home/someone")
    monkeypatch.setattr(Path, "home", lambda: home)
    error_log.write(
        "service",
        f"IntegrityError at {home / 'repo'}",
        "[SQL: INSERT INTO tasks (title) VALUES (?)]\n[parameters: ('Top secret plan',)]",
    )
    line = json.loads((logs / "errors-service.log").read_text(encoding="utf-8"))
    assert line["source"] == "service"
    assert line["message"] == f"IntegrityError at {Path('~') / 'repo'}"
    assert "Top secret plan" not in line["detail"] and "[parameters hidden]" in line["detail"]


def test_files_rotate_and_reading_merges_every_source(logs: Path, monkeypatch) -> None:
    monkeypatch.setattr(error_log, "MAX_BYTES", 600)
    for i in range(12):
        error_log.write("mcp", f"tool failed {i}", "x" * 60)
    error_log.write("window", "TypeError in the app window")
    desktop = Path(error_log.os.environ[error_log.DESKTOP_LOG_ENV])
    desktop.write_text(
        json.dumps(
            {
                "time": "2099-01-01T00:00:00+00:00",
                "source": "desktop",
                "level": "error",
                "message": "The local service stopped",
                "detail": "",
            }
        )
        + "\nnot json\n",
        encoding="utf-8",
    )
    assert (logs / "errors-mcp.log.1").exists() and (logs / "errors-mcp.log").stat().st_size <= 600
    log = error_log.read()
    assert log["entries"][0]["source"] == "desktop"  # newest first
    assert {e["source"] for e in log["entries"]} == {"mcp", "window", "desktop"}
    error_log.clear()
    assert error_log.read() == {"total": 0, "entries": []} and not desktop.exists()


def test_logging_errors_are_written_once_and_warnings_are_not(logs: Path) -> None:
    handler = error_log.ErrorLogHandler("service")
    logger = logging.getLogger("moah.test")
    logger.addHandler(handler)
    logging.getLogger().addHandler(handler)
    try:
        logger.warning("just a warning")
        try:
            raise RuntimeError("upkeep broke")
        except RuntimeError:
            logger.exception("Shelf upkeep failed")
    finally:
        logger.removeHandler(handler)
        logging.getLogger().removeHandler(handler)
    entries = error_log.read()["entries"]
    assert len(entries) == 1 and entries[0]["message"] == "moah.test: Shelf upkeep failed"
    assert "RuntimeError: upkeep broke" in entries[0]["detail"]


def test_mcp_logs_only_errors_of_the_app() -> None:
    from starlette.exceptions import HTTPException

    from app.mcp.server import _unexpected

    assert not _unexpected(ValueError("Unknown task CAMP-999"))
    assert not _unexpected(HTTPException(404, "Task not found"))
    assert _unexpected(HTTPException(500, "boom")) and _unexpected(KeyError("x"))


async def test_api_reads_records_and_clears_the_log(client: AsyncClient, logs: Path) -> None:
    assert (
        await client.post(
            "/api/system/errors",
            json={"message": "TypeError: x is undefined", "detail": "at Board"},
        )
    ).status_code == 204
    log = (await client.get("/api/system/errors")).json()
    assert log["total"] == 1 and log["entries"][0]["source"] == "window"
    report = (await client.get("/api/system/diagnostics")).json()
    assert report["errors"]["total"] == 1 and report["errors"]["last_day"] == 1
    assert "TypeError" not in json.dumps(report)  # the report counts errors, it never quotes them
    assert (await client.delete("/api/system/errors")).status_code == 204
    assert (await client.get("/api/system/errors")).json()["total"] == 0
