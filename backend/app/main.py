import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest
from mimetypes import guess_type
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.activity import project_router as project_activity_router
from app.api.activity import workspace_router as workspace_activity_router
from app.api.agent_folders import router as agent_folders_router
from app.api.checkpoints import router as checkpoints_router
from app.api.context import router as context_router
from app.api.files import router as files_router
from app.api.graph import router as graph_router
from app.api.graph import workspace_router as brain_router
from app.api.images import router as images_router
from app.api.memory import router as memory_router
from app.api.projects import router as projects_router
from app.api.proposals import router as proposals_router
from app.api.search import router as search_router
from app.api.settings import router as settings_router
from app.api.system import router as system_router
from app.api.tasks import router as tasks_router
from app.api.usage import router as usage_router
from app.core.config import get_database_url
from app.db.migrate import upgrade_database
from app.db.session import make_engine, make_session_factory
from app.services.agent_sync import background_sync
from app.services.usage import UsageReader


def create_app(
    database_url: str | None = None,
    *,
    frontend_dist: Path | None = None,
    desktop_token: str | None = None,
    warm_usage: bool = False,
) -> FastAPI:
    resolved_url = database_url or get_database_url()
    if frontend_dist is not None:
        frontend_dist = frontend_dist.resolve()
        if not (frontend_dist / "index.html").is_file():
            raise FileNotFoundError(f"Frontend build is missing: {frontend_dist / 'index.html'}")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        stop_sync = threading.Event()
        upgrade_database(resolved_url)
        engine = make_engine(resolved_url)
        application.state.session_factory = make_session_factory(engine)
        application.state.usage_reader = UsageReader()
        if warm_usage:
            # Read the agents' usage logs once in the background so the dashboard opens ready.
            reader = application.state.usage_reader
            threading.Thread(target=reader.refresh, name="usage-warmup", daemon=True).start()
            # Sync from agents: give new Claude Code and Codex folders a project every minute.
            threading.Thread(
                target=background_sync,
                args=(application.state.session_factory, stop_sync),
                name="agent-sync",
                daemon=True,
            ).start()
        try:
            yield
        finally:
            stop_sync.set()
            engine.dispose()

    application = FastAPI(title="Project Moah API", version="0.1.1", lifespan=lifespan)
    if desktop_token:
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])

        @application.middleware("http")
        async def require_desktop_token(request: Request, call_next):
            if request.url.path == "/api" or request.url.path.startswith("/api/"):
                provided = request.headers.get("X-Project-Brain-Token", "")
                if not compare_digest(provided, desktop_token):
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return await call_next(request)

    else:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type"],
        )
    application.include_router(projects_router)
    application.include_router(search_router)
    application.include_router(context_router)
    application.include_router(files_router)
    application.include_router(graph_router)
    application.include_router(brain_router)
    application.include_router(proposals_router)
    application.include_router(tasks_router)
    application.include_router(usage_router)
    application.include_router(agent_folders_router)
    application.include_router(settings_router)
    application.include_router(system_router)
    application.include_router(memory_router)
    application.include_router(images_router)
    application.include_router(checkpoints_router)
    application.include_router(project_activity_router)
    application.include_router(workspace_activity_router)

    @application.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    if frontend_dist is not None:

        @application.get("/{full_path:path}", include_in_schema=False)
        async def frontend(full_path: str) -> Response:
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (frontend_dist / full_path).resolve()
            if not candidate.is_relative_to(frontend_dist):
                raise HTTPException(status_code=404)
            if candidate.is_file():
                media_type = guess_type(candidate.name)[0] or "application/octet-stream"
                return Response(candidate.read_bytes(), media_type=media_type)
            if Path(full_path).suffix:
                raise HTTPException(status_code=404)
            return Response((frontend_dist / "index.html").read_bytes(), media_type="text/html")

    return application


app = create_app()
