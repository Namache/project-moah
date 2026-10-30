from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, *, include_archived: bool = False) -> list[Project]:
        statement = select(Project).where(Project.kind == "project")
        if not include_archived:
            statement = statement.where(Project.status != "archived")
        return list(self.session.scalars(statement.order_by(Project.created_at.desc(), Project.id)))

    def get(self, project_id: str) -> Project | None:
        return self.session.get(Project, project_id)

    def get_by_name_key(self, name_key: str) -> Project | None:
        return self.session.scalar(select(Project).where(Project.name_key == name_key))

    def slug_exists(self, slug: str) -> bool:
        return self.session.scalar(select(Project.id).where(Project.slug == slug)) is not None
