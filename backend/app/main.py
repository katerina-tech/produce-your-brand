"""FastAPI entrypoint.

Run with::

    uv run uvicorn app.main:app --reload --port 8000

The application factory installs the single logging configuration and the error
handlers that guarantee clients never receive a stack trace or raw model output.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dto import ErrorDetail, ErrorResponse
from app.api.routes import router
from app.config import Settings, get_settings
from app.logging_config import Event, configure_logging, log_event

logger = logging.getLogger(__name__)


def _error_response(status_code: int, detail: ErrorDetail) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=detail).model_dump(mode="json"),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Accepts injected settings so tests stay isolated."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    app = FastAPI(
        title="Produce Your Stuff API",
        description=(
            "AI-powered sourcing and production orchestration. All model calls "
            "happen server-side; the frontend never holds credentials."
        ),
        version="0.1.0",
    )

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

    log_event(
        logger,
        Event.API_STARTED,
        "api started",
        model=settings.model_name,
        api_key_configured=settings.has_api_key,
    )
    return app


app = create_app()
