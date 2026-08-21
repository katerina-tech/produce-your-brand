"""RAG contracts.

Retrieved knowledge is untrusted DATA. It carries citations so the UI can show
where a technical claim came from, and it is screened by
:mod:`app.security.guard` before it ever reaches a prompt.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProductionMethod


class KnowledgeCitation(BaseModel):
    """Attribution for a technical claim shown in the UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    source: str | None = None
    source_url: str | None = None
    updated_at: date | None = None


class KnowledgeSnippet(BaseModel):
    """One retrieved chunk plus its metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    citation: KnowledgeCitation
    production_method: ProductionMethod | None = None
    materials: tuple[str, ...] = ()
    score: float = Field(description="Cosine similarity, higher is closer.")


class RetrievalDecision(BaseModel):
    """The agentic-RAG routing decision.

    Produced by an LLM router so the agent decides whether technical knowledge is
    needed, rather than retrieval firing on every request. A supplier lookup
    ("who in Berlin does engraving?") must route to the supplier repository; a
    feasibility question ("can I engrave anodised aluminium?") must route here.
    """

    model_config = ConfigDict(extra="forbid")

    needs_retrieval: bool
    query: str | None = Field(
        default=None, description="Search query to use when needs_retrieval is True."
    )
    reason: str = Field(description="Short justification, surfaced in logs and the UI.")
