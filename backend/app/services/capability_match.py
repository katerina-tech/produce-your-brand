"""Two-stage matching: find plausible companies, then check each one.

The reviewer's recommendation, with the part that keeps it defensible.

**Stage one, embeddings.** A buyer writes "gold logo onto PVC yoga mats I
already own". No keyword search finds the shop whose site says "Transferdruck
auf beschichteten Oberflächen", and no enum of eight methods holds that phrase
either. Similarity over what companies wrote about themselves does.

**Stage two, verification.** Similarity is a hint, not an answer: "Textildruck"
and "Textilreinigung" sit close together in any embedding space, and one of
them cannot print a logo. So each candidate is checked by a model that must
quote the company's own claim, and a pure-Python check deletes any verdict
whose quote is not in that company's claims.

**Stage three is the existing scorer**, unchanged, applied afterwards wherever
real figures exist. Retrieval widens the field; nothing here decides. That
order is what keeps "why this company" answerable - the reason a buyer sees is
the company's own sentence, not a cosine distance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.domain.capability import SupplierCapabilities
from app.llm import prompts
from app.llm.factory import EmbeddingProvider, LLMError, LLMProvider
from app.logging_config import Event, log_event
from app.services.text_normalise import fold

logger = logging.getLogger(__name__)

# How many candidates retrieval hands to verification. Wide enough that a
# company phrased unusually still gets looked at, narrow enough that the
# verification bill stays one model call per candidate.
DEFAULT_CANDIDATES = 8


@dataclass(frozen=True)
class Candidate:
    """One company retrieval thinks is worth checking."""

    partner_id: str
    partner_name: str
    similarity: float
    claims: tuple[str, ...]

    @property
    def evidence_text(self) -> str:
        return "\n".join(f"- {claim}" for claim in self.claims)


class CapabilityIndex:
    """Capability claims, embedded once and searched by cosine similarity.

    In memory, rebuilt on load. A city's worth of companies is a few thousand
    short vectors, and a numpy dot product over that is faster than the file
    handling an index on disk would need. FAISS earns its place in the
    knowledge base, where the corpus is fixed and the index is worth persisting;
    here it would be machinery guarding nothing.
    """

    def __init__(self, embedder: EmbeddingProvider) -> None:
        self._embedder = embedder
        self._matrix: np.ndarray | None = None
        self._entries: list[SupplierCapabilities] = []

    def build(self, capabilities: tuple[SupplierCapabilities, ...]) -> int:
        """Embed every company that has something to say. Returns how many."""
        usable = [item for item in capabilities if not item.is_empty]
        if not usable:
            self._matrix, self._entries = None, []
            return 0

        try:
            vectors = self._embedder.embed_documents([item.searchable_text for item in usable])
        except LLMError:
            # A retrieval outage costs candidate generation, never the product:
            # the caller falls back to the deterministic matcher it always had.
            log_event(
                logger,
                Event.LLM_ERROR,
                "capability index could not be built",
                level=logging.WARNING,
                companies=len(usable),
            )
            self._matrix, self._entries = None, []
            return 0

        matrix = np.asarray(vectors, dtype=np.float32)
        # Normalised once here, so similarity is a dot product rather than a
        # division repeated per query.
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self._matrix = matrix / np.where(norms == 0, 1.0, norms)
        self._entries = usable
        return len(usable)

    def search(self, query: str, *, limit: int = DEFAULT_CANDIDATES) -> tuple[Candidate, ...]:
        """The companies whose own words are closest to this request."""
        if self._matrix is None or not self._entries or not query.strip():
            return ()

        try:
            raw = self._embedder.embed_query(query)
        except LLMError:
            log_event(
                logger,
                Event.LLM_ERROR,
                "capability query could not be embedded",
                level=logging.WARNING,
            )
            return ()

        vector = np.asarray(raw, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return ()
        scores = self._matrix @ (vector / norm)

        order = np.argsort(-scores)[:limit]
        return tuple(
            Candidate(
                partner_id=self._entries[int(index)].partner_id,
                partner_name=self._entries[int(index)].partner_name,
                similarity=round(float(scores[int(index)]), 4),
                claims=tuple(claim.text for claim in self._entries[int(index)].claims),
            )
            for index in order
        )

    @property
    def size(self) -> int:
        return len(self._entries)


class MatchVerdict(BaseModel):
    """What the model may say about one candidate.

    No score and no ranking: the model answers one question about one company,
    and ordering is decided afterwards by code. A model that could rank would
    be a model whose ordering nobody could explain.
    """

    model_config = ConfigDict(extra="forbid")

    can_do_it: bool | None = Field(
        default=None,
        description=(
            "True only when a claim plainly covers the request. None for unclear, "
            "which is the honest answer far more often than either of the others."
        ),
    )
    reason: str = Field(max_length=300, description="One sentence, for a person to read.")
    quote: str = Field(
        default="",
        min_length=0,
        max_length=300,
        description="The company's own claim that supports this. Verified afterwards.",
    )


@dataclass(frozen=True)
class VerifiedMatch:
    """A candidate, after a model looked at it and a verifier checked the model."""

    candidate: Candidate
    can_do_it: bool | None
    reason: str
    quote: str
    quote_verified: bool

    @property
    def is_supported(self) -> bool:
        """Whether this may be shown as a positive match.

        An unverified quote demotes the verdict to "unclear" rather than
        removing the company: the shop may well be able to do the job, and all
        that has been established is that the model could not point at where it
        said so.
        """
        return self.can_do_it is True and self.quote_verified


def verify_candidate(
    requirement: str, candidate: Candidate, provider: LLMProvider | None
) -> VerifiedMatch:
    """Ask whether one company can do one job, then check the answer.

    Without a model this returns "unclear" rather than guessing: an unchecked
    candidate is exactly as informative as no candidate, and pretending
    otherwise would put a similarity score in front of a buyer as if it were a
    judgement.
    """
    unclear = VerifiedMatch(
        candidate=candidate,
        can_do_it=None,
        reason="Not checked: no model available.",
        quote="",
        quote_verified=False,
    )
    if provider is None:
        return unclear

    try:
        verdict = provider.structured(
            MatchVerdict,
            prompts.match_verification_messages(requirement, candidate.evidence_text),
            purpose="classifier",
        )
    except LLMError:
        return unclear

    # The same rule as everywhere else: a claim the company did not make cannot
    # be used to recommend them.
    haystack = fold(candidate.evidence_text).casefold()
    needle = fold(verdict.quote).casefold()
    verified = bool(needle) and needle in haystack

    return VerifiedMatch(
        candidate=candidate,
        can_do_it=verdict.can_do_it,
        reason=verdict.reason,
        quote=verdict.quote,
        quote_verified=verified,
    )


def find_matches(
    requirement: str,
    index: CapabilityIndex,
    provider: LLMProvider | None,
    *,
    limit: int = DEFAULT_CANDIDATES,
) -> tuple[VerifiedMatch, ...]:
    """Retrieve, then verify. Supported matches first, in similarity order.

    Unsupported candidates are kept rather than dropped, because "we looked and
    could not tell" is information a buyer can act on - it is the list of
    companies worth a phone call.
    """
    candidates = index.search(requirement, limit=limit)
    verified = tuple(verify_candidate(requirement, candidate, provider) for candidate in candidates)

    log_event(
        logger,
        Event.SUPPLIER_MATCHING_COMPLETED,
        "capability matching completed",
        retrieved=len(candidates),
        supported=sum(1 for match in verified if match.is_supported),
        unverified_quotes=sum(
            1 for match in verified if match.can_do_it is True and not match.quote_verified
        ),
    )

    return tuple(
        sorted(verified, key=lambda match: (not match.is_supported, -match.candidate.similarity))
    )
