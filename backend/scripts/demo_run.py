"""End-to-end demo against the real model. The only code here that spends money.

The test suite runs entirely on a scripted provider, so this script is what
verifies the prompts actually work against a live model - separating "is the
control flow correct" from "does the model behave".

    uv run python scripts/demo_run.py

Every human gate is auto-approved so the run is unattended. Nothing is sent to
any supplier; the RFQ is printed and discarded.
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.domain.enums import Stage
from app.graph.workflow import (
    checkpointer_for,
    compile_workflow,
    production_deps,
)
from app.logging_config import configure_logging
from app.repositories import db
from app.repositories.project_repo import ProjectRepository
from app.services import rfq_builder
from app.services.project_service import ProjectService

DEMO_REQUEST = (
    "I have 100 black yoga mats. I already own them. I want my gold logo added "
    "and need them in Berlin by September 15."
)

# Fixed so match scores are reproducible between demo runs.
REFERENCE_DATE = date(2026, 8, 21)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> int:
    configure_logging(level="WARNING", fmt="console")
    logging.getLogger("app").setLevel(logging.WARNING)

    settings = get_settings()
    if not settings.has_api_key:
        print("No API key configured. Copy .env.example to .env and set OPENAI_API_KEY.")
        return 1

    print(f"model    : {settings.model_name}")
    print(f"gateway  : {settings.openai_base_url or 'api.openai.com (direct)'}")
    print(f"reference: {REFERENCE_DATE.isoformat()}")

    scratch = settings.data_dir / "demo"
    scratch.mkdir(parents=True, exist_ok=True)
    connection = db.connect(scratch / "demo_app.db")
    db.initialize_schema(connection)

    deps = production_deps(settings, today=REFERENCE_DATE)
    workflow = compile_workflow(deps, checkpointer_for(scratch / "demo_ckpt.db"))
    service = ProjectService(workflow, ProjectRepository(connection), today=REFERENCE_DATE)

    rule("STEP 1 - natural-language request")
    print(DEMO_REQUEST)

    view = service.create(DEMO_REQUEST)

    # The clarification loop may fire if the model leaves a critical field null.
    while view.stage is Stage.CLARIFYING:
        assert view.payload is not None
        rule("CLARIFICATION - the agent asks for one missing field")
        print(f"field    : {view.payload['field']}")
        print(f"question : {view.payload['question']}")
        answer = "They are PVC mats, and yes, I already own them."
        print(f"answer   : {answer}")
        view = service.resume(view.project_id, "answer_clarification", {"answer": answer})

    if view.stage is Stage.FAILED:
        rule("FAILED")
        print("\n".join(view.errors))
        return 1

    rule("STEP 2 - extracted Production Brief (human gate 1)")
    assert view.payload is not None
    for field, value in view.payload["requirement"].items():
        marker = " " if value not in (None, [], "") else "?"
        print(f"  {marker} {field:<28} {value}")

    view = service.resume(view.project_id, "confirm_brief", {})
    if view.stage is Stage.FAILED:
        rule("FAILED")
        print("\n".join(view.errors))
        return 1

    rule("STEP 3 - production method recommendation (human gate 2)")
    assert view.payload is not None
    rec = view.payload["recommendation"]

    # The agentic-RAG evidence: whether knowledge was consulted, and what for.
    print(f"  retrieval   : {'consulted' if rec['retrieval_used'] else 'not needed'}")
    for citation in rec.get("sources") or []:
        print(f"     source   : {citation['title']}")
    print()
    print(f"  primary     : {rec['primary']}")
    print(f"  alternative : {rec['alternative']}")
    print(f"  confidence  : {rec['confidence']}")
    print(f"  rationale   : {rec['rationale']}")
    for key in ("constraints", "artwork_requirements", "open_questions"):
        for item in rec.get(key) or []:
            print(f"  {key[:12]:<12}: {item}")

    view = service.resume(view.project_id, "confirm_method", {"method": rec["primary"]})
    if view.stage is Stage.FAILED:
        rule("FAILED")
        print("\n".join(view.errors))
        return 1

    rule("STEP 4 - supplier matches, deterministic scores (human gate 3)")
    assert view.payload is not None
    matches = view.payload["matches"]
    for match in matches:
        print(f"\n  {match['score']:.1f}%  {match['supplier_name']}  [{match['supplier_id']}]")
        for factor in match["factors"]:
            mark = {"match": "+", "partial": "~", "unknown": "?", "mismatch": "-"}[
                factor["verdict"]
            ]
            print(
                f"      {mark} {factor['factor']:<16}"
                f"{factor['awarded']:>5.1f}/{factor['max_points']:<5.1f} {factor['explanation']}"
            )
        for flag in match["risk_flags"]:
            print(f"      ! {flag}")
        if match.get("ai_explanation"):
            print(f"      AI: {match['ai_explanation']}")

    chosen = matches[0]["supplier_id"]
    print(f"\n  selecting {chosen}")
    view = service.resume(view.project_id, "select_supplier", {"supplier_id": chosen})
    if view.stage is Stage.FAILED:
        rule("FAILED")
        print("\n".join(view.errors))
        return 1

    rule("STEP 5 - generated RFQ, pending approval (human gate 4)")
    assert view.payload is not None
    print(view.payload["rendered"])
    print(f"\n  approved before the gate: {view.payload['rfq']['approved']}")

    view = service.resume(view.project_id, "approve_rfq", {"approved": True})

    rule("RESULT")
    print(f"  stage    : {view.stage.value}")
    print(f"  complete : {view.is_complete}")

    stored = ProjectRepository(connection).get(view.project_id)
    if stored and stored.rfq:
        print(f"  persisted: approved={stored.rfq.approved} supplier={stored.selected_supplier_id}")
        print(f"  rendered RFQ length: {len(rfq_builder.render_markdown(stored.rfq))} chars")

    human_events = [
        event.event_type
        for event in ProjectRepository(connection).events(view.project_id)
        if event.actor == "human"
    ]
    print(f"  human decisions audited: {human_events}")

    connection.close()
    return 0 if view.is_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
