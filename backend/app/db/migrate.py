from alembic import command
from alembic.config import Config

from app.core.config import ensure_sqlite_directory
from app.core.resources import resource_path


def upgrade_database(database_url: str) -> None:
    """Apply checked-in migrations; never build production tables from ORM metadata."""
    ensure_sqlite_directory(database_url)
    config_path = resource_path("backend/alembic.ini")
    config = Config(str(config_path))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
