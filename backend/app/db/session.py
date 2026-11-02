from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request


def make_engine(database_url: str) -> Engine:
    is_sqlite = database_url.startswith("sqlite:")
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
    )

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # The app and an agent's MCP server share one file; wait briefly instead of failing.
            cursor.execute("PRAGMA busy_timeout=5000")
            # Write-ahead logging: readers and the writer no longer block each other (the app,
            # agents' MCP servers and their start-up briefs share the file), and a write syncs
            # the disk once instead of about three times. Kept in the file once set; full sync
            # stays on, so a power cut still loses nothing that was saved.
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:  # noqa: BLE001 - another process holding a lock: try next time
                pass
            cursor.close()
            # Unicode-aware case folding for searches; SQLite's lower() only folds ASCII.
            dbapi_connection.create_function(
                "casefold",
                1,
                lambda value: value.casefold() if isinstance(value, str) else value,
                deterministic=True,
            )

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session
