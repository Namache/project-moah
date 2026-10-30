from datetime import datetime

from pydantic import ConfigDict

from app.schemas.common import UtcModel


class ImageRead(UtcModel):
    """An attached image without its bytes; GET .../images/{id} serves the picture."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    media_type: str
    size_bytes: int
    width: int | None
    height: int | None
    created_by: str | None
    created_at: datetime
