from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.project import utc_now


class AppSetting(Base):
    """One app-wide setting. Stored in the database so the MCP server sees the same value."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
