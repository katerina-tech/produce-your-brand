"""FastAPI entrypoint.

Run with::

    uv run uvicorn app.main:app --reload --port 8000

The application factory installs the single logging configuration and the error
handlers that guarantee clients never receive a stack trace or raw model output.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dto import ErrorDetail, ErrorResponse
from app.api.routes import router
from app.config import Settings, get_settings
from app.graph.workflow import checkpointer_for, compile_workflow, production_deps
from app.llm.factory import get_image_provider
from app.logging_config import Event, configure_logging, log_event
from app.repositories import db
from app.repositories.project_repo import ProjectRepository
from app.repositories.supplier_repo import SupplierRepository
from app.services.osm_search import get_osm_search
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)


def _error_response(status_code: int, detail: ErrorDetail) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=detail).model_dump(mode="json"),
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the service once, then hold it for the process lifetime.

    Both SQLite connections and the compiled workflow are long-lived on purpose:
    the checkpointer must keep its connection open across requests, which is why
    ``SqliteSaver.from_conn_string`` (a context manager that closes on exit) is
    the wrong tool here.
    """
    settings: Settings = app.state.settings

    connection = db.connect(settings.app_db_path)
    db.initialize_schema(connection)

    deps = production_deps(settings)
    workflow = compile_workflow(deps, checkpointer_for(settings.checkpoint_db_path))

    app.state.project_service = ProjectService(workflow, ProjectRepository(connection))
    app.state.image_provider = get_image_provider(settings)
    app.state.osm_search = get_osm_search(settings)

    # Validate the supplier dataset at startup rather than on the first request:
    # a malformed file should fail loudly here, not surface later as an
    # inexplicably empty match list.
    suppliers = SupplierRepository(settings.suppliers_file)
    try:
        app.state.supplier_count = suppliers.count()
    except (OSError, ValueError):
        logger.exception("supplier dataset failed to load", extra={"event": Event.TOOL_ERROR.value})
        app.state.supplier_count = 0

    log_event(
        logger,
        Event.API_STARTED,
        "api ready",
        model=settings.model_name,
        gateway=settings.openai_base_url or "openai",
        api_key_configured=settings.has_api_key,
        suppliers=app.state.supplier_count,
    )
    try:
        yield
    finally:
        connection.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Accepts injected settings so tests stay isolated."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    app = FastAPI(
        lifespan=_lifespan,
        title="Produce Your Brand API",
        description=(
            "AI-powered sourcing and production orchestration. All model calls "
            "happen server-side; the frontend never holds credentials."
        ),
        version="0.1.0",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Malformed input is the client's to fix, so it is reported as recoverable."""
        log_event(
            logger,
            Event.VALIDATION_ERROR,
            "request validation failed",
            level=logging.WARNING,
            path=request.url.path,
            error_count=len(exc.errors()),
        )
        return _error_response(
            422,
            ErrorDetail(
                code="invalid_request",
                message="The request body did not match the expected schema.",
                recoverable=True,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _on_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            exc.status_code,
            ErrorDetail(
                code=f"http_{exc.status_code}",
                message=str(exc.detail),
                recoverable=exc.status_code < 500,
            ),
        )

    @app.exception_handler(Exception)
    async def _on_unhandled(request: Request, _exc: Exception) -> JSONResponse:
        """Log the detail, return none of it.

        The exception type is recorded server-side; the client receives a generic
        message so internal structure is never leaked through the API.
        """
        logger.exception(
            "unhandled error",
            extra={"event": "unhandled_error", "path": request.url.path},
        )
        return _error_response(
            500,
            ErrorDetail(
                code="internal_error",
                message="An unexpected error occurred. The incident has been logged.",
                recoverable=False,
            ),
        )

    app.include_router(router)
    return app


app = create_app()
