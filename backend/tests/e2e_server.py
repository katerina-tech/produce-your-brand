"""Runs the real API on a scripted LLM provider, as an actual server process.

Every unit test in this suite runs the app in-process (``TestClient`` or a
compiled graph invoked directly). This is the one place that boots it as a
real HTTP server instead, for manual or browser-driven verification against a
real running frontend - without touching the network or a model API key.

    uv run python -m tests.e2e_server

Mirrors exactly what tests/test_api.py's ``api`` fixture wires up (see its
docstring): the real app, its real lifespan, with the project service and
image provider swapped for the same scripted doubles every other test in this
suite uses. There is deliberately one definition of "a clean scripted run" -
tests/test_graph.py's ``_scripted()`` - reused here rather than duplicated.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from app.config import Settings
from app.graph.workflow import GraphDeps, checkpointer_for, compile_workflow
from app.main import _lifespan as _real_lifespan
from app.main import create_app
from app.repositories import db
from app.repositories.project_repo import ProjectRepository
from app.repositories.supplier_repo import SupplierRepository
from app.services.project_service import ProjectService
from app.tools.registry import ProductionTools
from tests.conftest import TODAY
from tests.fakes import ScriptedImageProvider
from tests.test_graph import _full_requirement, _scripted

_RUN_DIR = Path(tempfile.gettempdir()) / "pys-e2e-run"


def _settings() -> Settings:
    return Settings(upload_dir=_RUN_DIR / "uploads")


@asynccontextmanager
async def _e2e_lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    async with _real_lifespan(app):
        # The real lifespan just built a project_service/image_provider that
        # would call the actual model API. Swap both for scripted doubles -
        # everything else (routing, the graph, supplier matching, RFQ
        # assembly, the database) stays production code.
        connection = db.connect(_RUN_DIR / "e2e.db")
        db.initialize_schema(connection)
        # Missing one field on purpose (repeated several times): manual
        # verification wants to actually see the clarification screen, not
        # skip straight to brief review the way every other test's clean
        # `_scripted()` run does. The provider is shared across every project
        # this process serves, so the queue is sized for a few manual runs,
        # not one.
        incomplete = _full_requirement().model_copy(update={"customer_owns_product": None})
        deps = GraphDeps(
            provider=_scripted(ProductionRequirement=[incomplete] * 6 + [_full_requirement()]),
            tools=ProductionTools(SupplierRepository(settings.suppliers_file)),
            today=TODAY,
        )
        workflow = compile_workflow(deps, checkpointer_for(_RUN_DIR / "e2e_ckpt.db"))
        app.state.project_service = ProjectService(
            workflow, ProjectRepository(connection), today=TODAY, settings=settings
        )
        app.state.image_provider = ScriptedImageProvider()
        try:
            yield
        finally:
            connection.close()


def main() -> None:
    if _RUN_DIR.exists():
        shutil.rmtree(_RUN_DIR)
    _RUN_DIR.mkdir(parents=True)

    app = create_app(_settings())
    app.router.lifespan_context = _e2e_lifespan
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
