"""Proving that an account speaks for a company, by control of its website.

The badge in the directory says a named Berlin business confirmed something.
That is only worth anything if the business confirmed it - so this module is
the whole of the difference between a directory anybody can edit and one worth
believing.

**The URL is derived, never supplied.** The website comes from the company's own
OpenStreetMap entry, recorded before anybody asked to claim anything. A claimer
who could name the URL would be proving they control *a* website, which proves
nothing at all.

**The fetch is the same guarded one used everywhere else.** Every resolved
address is checked before a byte is requested, so a claim naming an internal
host cannot turn this into a probe of the network the server sits in. The reply
is capped at a few kilobytes: a proof is forty characters, and anything willing
to send megabytes is not answering the question.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from app.domain.company import CompanyClaim, new_token, proof_url
from app.domain.partner import Partner
from app.logging_config import Event, log_event
from app.services.site_fetch import USER_AGENT, Resolver, _resolve, address_refusal

logger = logging.getLogger(__name__)

# A proof is one line. Anything beyond this is not an answer to the question,
# and reading it would only be a way to spend memory on somebody's behalf.
MAX_PROOF_BYTES = 8_192
TIMEOUT_SECONDS = 15.0


class ClaimError(RuntimeError):
    """The claim cannot proceed, and the message says why in words."""


def start(partner: Partner, user_id: str, *, now: datetime | None = None) -> CompanyClaim:
    """Issue a token for this company, or refuse with a reason.

    Refusing early matters: a company with no website cannot prove itself this
    way, and telling somebody that before they go looking for a file to upload
    is the difference between a dead end and a mystery.
    """
    if not partner.website:
        raise ClaimError(
            "This company publishes no website, so there is nothing to prove control of. "
            "Ask us to confirm it by hand."
        )
    if proof_url(partner.website) is None:
        raise ClaimError(f"{partner.website} is not an address this can check.")

    return CompanyClaim(
        partner_id=partner.id,
        user_id=user_id,
        token=new_token(),
        created_at=now or datetime.now(UTC),
    )


def instructions(partner: Partner, claim: CompanyClaim) -> tuple[str, str]:
    """Where to put the token and what to put there."""
    url = proof_url(partner.website or "")
    return (url or "", claim.token)


def check(
    partner: Partner,
    claim: CompanyClaim,
    *,
    client: httpx.Client | None = None,
    resolve: Resolver = _resolve,
    now: datetime | None = None,
) -> None:
    """Fetch the proof and accept it, or raise with the reason it failed.

    Raises rather than returning false, because every failure here has a
    different remedy - the file is missing, the token is wrong, the claim has
    expired, the site will not answer - and "no" would collapse four
    instructions into one shrug.
    """
    if not claim.is_live_at(now):
        raise ClaimError("This claim has expired. Start again to get a fresh token.")

    url = proof_url(partner.website or "")
    if url is None:
        raise ClaimError("This company publishes no website to check.")

    refusal = address_refusal(url, resolve)
    if refusal is not None:
        raise ClaimError(f"That address cannot be checked: {refusal}")

    owned = client is None
    http = client or httpx.Client(follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        response = http.get(url, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        raise ClaimError(
            f"{url} could not be reached ({type(error).__name__}). "
            "Check the file is published and try again."
        ) from error
    finally:
        if owned:
            http.close()

    if response.status_code >= 400:
        raise ClaimError(f"{url} answered {response.status_code}. Upload the file and try again.")

    body = response.text[:MAX_PROOF_BYTES]
    if claim.token not in body:
        # Deliberately does not say what was found. A claimer who controls the
        # site knows what they put there; one who does not should learn nothing
        # about it from us.
        raise ClaimError(
            "The file does not contain this token. Check it was saved, and that the "
            "address serves it as plain text."
        )

    log_event(
        logger,
        Event.COMPANY_CLAIM_VERIFIED,
        "company proved control of its website",
        partner_id=partner.id,
        url=url,
    )
