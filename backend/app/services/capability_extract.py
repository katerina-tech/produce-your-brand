"""Read a company's pages into capability claims, and delete what they do not support.

The same discipline as :mod:`app.services.quote_capture`, pointed at a
different kind of text. A model reads prose and proposes structure; a pure
Python check then deletes every claim whose quoted words are not on the page.

Why that matters more here than almost anywhere else: these claims decide which
companies a buyer is shown, and they are claims *about a named business*. A
model that infers "they probably do embroidery too" from a photo caption would
have this product telling a buyer that a real Berlin firm offers something
nobody ever said it did. The verifier makes that impossible rather than
unlikely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.capability import CapabilityClaim, ClaimKind, SupplierCapabilities
from app.domain.enums import ProductionMethod
from app.llm.factory import LLMError, LLMProvider
from app.logging_config import Event, log_event
from app.security.guard import InjectionGuard, Provenance
from app.services.site_fetch import FetchedPage
from app.services.text_normalise import fold

logger = logging.getLogger(__name__)

# A page long enough to bury the model's attention. Company sites run to
# thousands of words of history and imprint; the services text is near the top.
MAX_CHARS_READ = 12_000


class ExtractedClaim(BaseModel):
    """What the model may report about one capability.

    No id, no partner, no confirmation flag, no date. Identity and provenance
    are decided by code, so an injection hidden in a company's page has nothing
    here worth setting.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=2, max_length=300)
    quote: str = Field(min_length=2, max_length=300)
    kind: ClaimKind = "other"
    method: ProductionMethod | None = None


class ExtractedCapabilities(BaseModel):
    """The model's reading of one company's pages."""

    model_config = ConfigDict(extra="forbid")

    claims: tuple[ExtractedClaim, ...] = ()


@dataclass(frozen=True)
class ExtractionOutcome:
    """The capabilities, plus why they may be thinner than the pages looked."""

    capabilities: SupplierCapabilities
    blocked: bool = False
    model_failed: bool = False

    @property
    def nothing_was_read(self) -> bool:
        return self.capabilities.is_empty


_PROMPT = """You are reading a production company's own website to record what it says it can do.

Rules:
- Report only what the page states. Never infer a capability from a photo, a
  client logo, or an industry the company merely mentions.
- Every claim must carry `quote`: an exact, verbatim substring of the page text.
  If you cannot quote it, do not report it.
- Keep `text` close to the company's own wording. Do not translate it into a
  category it did not use.
- Set `method` only when the text plainly names one of the known methods.
  Leaving it empty is normal and correct.

Page text:
---
{page_text}
---"""


def _verify(claims: tuple[ExtractedClaim, ...], source: str) -> tuple[list[CapabilityClaim], int]:
    """Keep the claims whose words are genuinely on the page.

    Folded comparison, so a page that writes "Siebdruck­verfahren" with a soft
    hyphen, or in different case, still supports a quote that does not. The
    check stays literal: no fuzzy matching, because "close enough" is how an
    invented capability gets through.
    """
    # casefold on top of fold: fold strips obfuscation without touching case,
    # which is right for the security guard that shares it, and too strict here
    # - a page writing "STICKEREI" in a heading supports a quote that does not
    # shout. Case is the only latitude given; the match stays literal, because
    # "close enough" is how an invented capability gets through.
    folded_source = fold(source).casefold()
    kept: list[CapabilityClaim] = []
    dropped = 0

    for claim in claims:
        folded_quote = fold(claim.quote).casefold()
        if folded_quote and folded_quote in folded_source:
            kept.append(
                CapabilityClaim(
                    text=claim.text, quote=claim.quote, kind=claim.kind, method=claim.method
                )
            )
        else:
            dropped += 1

    return kept, dropped


def extract_capabilities(
    *,
    pages: tuple[FetchedPage, ...],
    partner_id: str,
    partner_name: str,
    extracted_on: date,
    guard: InjectionGuard,
    provider: LLMProvider | None,
) -> ExtractionOutcome:
    """Read one company's pages into verified capability claims.

    Returns an honest empty record rather than raising: a company whose site
    could not be read still exists, and losing it from the directory would be a
    worse answer than recording that nothing was learned.
    """
    empty = SupplierCapabilities(
        partner_id=partner_id,
        partner_name=partner_name,
        source_urls=tuple(page.url for page in pages),
        extracted_on=extracted_on,
    )

    readable = [page for page in pages if page.is_substantial]
    if not readable:
        return ExtractionOutcome(capabilities=empty)

    combined = "\n\n".join(page.text for page in readable)[:MAX_CHARS_READ]

    # A company's own website is not a trusted source: it is text this product
    # did not write, fetched from an address anybody could have edited into a
    # map. Screened on the same footing as a supplier's emailed reply.
    screening = guard.assess(combined, Provenance.SUPPLIER_REPLY)
    if screening.blocked:
        log_event(
            logger,
            Event.INJECTION_SUSPECTED,
            "company page blocked; no capabilities read",
            level=logging.WARNING,
            partner_id=partner_id,
            signals=list(screening.signals),
            score=screening.score,
        )
        return ExtractionOutcome(capabilities=empty, blocked=True)

    if provider is None:
        return ExtractionOutcome(capabilities=empty, model_failed=True)

    try:
        reading = provider.structured(
            ExtractedCapabilities,
            [{"role": "user", "content": _PROMPT.format(page_text=screening.text)}],  # type: ignore[list-item]
        )
    except LLMError:
        log_event(
            logger,
            Event.LLM_ERROR,
            "capability extraction failed",
            level=logging.WARNING,
            partner_id=partner_id,
        )
        return ExtractionOutcome(capabilities=empty, model_failed=True)

    kept, dropped = _verify(reading.claims, screening.text)

    log_event(
        logger,
        Event.COMPANY_PAGE_FETCHED,
        "capabilities extracted",
        partner_id=partner_id,
        pages=len(readable),
        proposed=len(reading.claims),
        kept=len(kept),
        dropped=dropped,
    )

    return ExtractionOutcome(
        capabilities=SupplierCapabilities(
            partner_id=partner_id,
            partner_name=partner_name,
            source_urls=tuple(page.url for page in readable),
            claims=tuple(kept),
            extracted_on=extracted_on,
            dropped_count=dropped,
        )
    )
