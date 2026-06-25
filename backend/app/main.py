from __future__ import annotations

from contextlib import asynccontextmanager

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
except ImportError:  # pragma: no cover - allows service tests without optional runtime deps.
    FastAPI = None


def create_app():
    if FastAPI is None:
        raise RuntimeError("FastAPI is required to run the API server")
    from app.routes import register_routes
    from app.processing.worker import start_processing_worker

    @asynccontextmanager
    async def lifespan(_app):
        start_processing_worker()
        yield

    app = FastAPI(title="Agent Observer", lifespan=lifespan)
    register_routes(app, HTTPException, FileResponse)
    return app


app = create_app() if FastAPI is not None else None
