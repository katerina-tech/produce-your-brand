"""A company account: somebody who has proved they speak for a listing.

The directory names 136 real Berlin businesses. Letting anybody sign up and say
"that one is mine" would be worse than having no accounts at all - a badge
saying a named company confirmed something is only worth anything if the
company confirmed it.

**Proof is control of the website the directory already holds.** Not an address
the claimer types: the website came from OpenStreetMap, from the business's own
map entry, before anybody asked to claim anything. Whoever can put a file on
that site controls that business's web presence, which is as close to "is the
company" as a directory can honestly get.

Why not email, which would be easier for a copyshop owner: the product sends no
mail, and adding an outbound path so that claiming a company sends a message to
that company would make claiming into a way to mail 136 businesses. The flow
here is shaped so an emailed code can be added later as a second proof - the
token, the record and the expiry are all the same - but the proof that needs no
new infrastructure and cannot be turned into a spam cannon comes first.

Forty-six of the 136 publish neither a website nor an email. They cannot claim
themselves and are confirmed by an operator by hand, which is what the flag
already meant before accounts existed.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

# Long enough that guessing is hopeless, short enough to paste into a text file
# without a mistake. URL-safe so it survives being copied through a browser.
TOKEN_BYTES = 24

# A claim that is started and never finished should not hold a company for
# ever: a business that mislaid the token must be able to start again, and a
# squatter must not be able to hold a listing by never proving anything.
CLAIM_VALID_HOURS = 48

# The conventional place for a machine-readable proof, and one a hosting panel
# will serve as plain text without argument.
WELL_KNOWN_PATH = "/.well-known/produce-your-brand.txt"


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


# A hostname, not merely something urlsplit was willing to parse. Without this,
# "javascript:alert(1)" produced a proof URL: urlsplit reads it as the host
# "javascript" on port "alert(1)", which is a valid parse of a string that is
# plainly not a website. At least one dot, because a directory of Berlin
# businesses has no single-label hosts in it and a bare word is a typo.
_HOSTNAME = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$")


def proof_url(website: str) -> str | None:
    """Where the token must appear, derived from the directory's own website.

    Derived rather than accepted: if the claimer chose the URL, the proof would
    show only that they control *a* website. Anything but http or https is
    refused here rather than later, because a scheme this product will not
    fetch is not a site somebody can prove.
    """
    if not website or " " in website.strip():
        return None
    parts = urlsplit(website if "//" in website else f"//{website}", scheme="https")
    if parts.scheme not in {"http", "https"}:
        return None
    host = parts.hostname or ""
    if not _HOSTNAME.match(host):
        return None
    # Rebuilt from the parsed host and port rather than reusing netloc, so any
    # userinfo an address carried - "user:pass@site" - is dropped rather than
    # sent on to somebody's server.
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, WELL_KNOWN_PATH, "", ""))


class CompanyClaim(BaseModel):
    """One attempt to prove an account speaks for a company."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    partner_id: str
    user_id: str
    token: str
    created_at: datetime
    verified_at: datetime | None = Field(
        default=None, description="When the proof was accepted. None while it is outstanding."
    )

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    def expires_at(self) -> datetime:
        return self.created_at + timedelta(hours=CLAIM_VALID_HOURS)

    def is_live_at(self, moment: datetime | None = None) -> bool:
        """Whether this claim still holds the company.

        A verified claim never expires - the account keeps the company until
        somebody takes it away deliberately. An unverified one does, so a
        listing cannot be held by a claim nobody ever completed.
        """
        if self.is_verified:
            return True
        return (moment or datetime.now(UTC)) < self.expires_at()
