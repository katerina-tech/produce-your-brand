"""Recover the email address a company publishes but writes so it cannot be read.

A short manual check found what this product had missed: A&W Digitaldruck
publishes ``info [at] aw-digital.de`` on its homepage, and the directory said
"no email published". The address was there; the survey only ever looked at
OpenStreetMap's ``email`` tag, and the fetched page text was read for
capabilities and never for contacts.

So this module does two things, both without a model:

* **De-obfuscates.** German small-business sites write ``[at]``, ``(at)``,
  ``[ät]``, ``at``, and the same tricks for the dot. Each is a separator
  standing in for one character, and undoing them is a regular expression, not
  a judgement.
* **Chooses.** A page often carries several addresses - a role box, a named
  person, sometimes the web designer's. Choosing badly means a buyer writes to
  the wrong company, so the ranking is explicit and conservative rather than
  "first match wins".

Two rules in the ranking are about people rather than data quality. A role
address (``info@``, ``kontakt@``) beats a named person's, and an address whose
domain matches the company's own website beats one that does not. Both push
towards the box a business put on its site to be written to, and away from
publishing an individual's work address in a directory they never asked to be
in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# A separator standing in for "@", and one standing in for ".". Written out
# rather than guessed at: every alternative here was seen on a real Berlin
# print shop's website.
_AT = r"(?:@|\s*[\[(]\s*(?:at|att|ät|a)\s*[\])]\s*|\s+(?:at|ät)\s+)"
_DOT = r"(?:\.|\s*[\[(]\s*(?:dot|punkt)\s*[\])]\s*|\s+(?:dot|punkt)\s+)"

# Deliberately narrower than RFC 5322 allows. The RFC permits "!" in a local
# part, and honouring that turned "schreiben Sie uns! info@..." into an address
# beginning "uns!" - a technically valid reading of a sentence that plainly
# meant something else.
_LOCAL = r"[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9])?"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"

_CANDIDATE = re.compile(rf"({_LOCAL}){_AT}({_LABEL}(?:{_DOT}{_LABEL})+)", re.IGNORECASE)

# The boxes a business puts on its site to be written to, rather than a person
# who happens to work there.
ROLE_NAMES = frozenset(
    {
        "info",
        "kontakt",
        "contact",
        "mail",
        "email",
        "post",
        "office",
        "buero",
        "büro",
        "service",
        "anfrage",
        "anfragen",
        "bestellung",
        "druck",
        "daten",
        "shop",
        "berlin",
        "hello",
        "moin",
    }
)

# Addresses that belong to the page rather than to the business: tracking
# pixels, image files misread as addresses, and the placeholders theme authors
# leave behind.
_NOT_AN_ADDRESS = re.compile(
    r"\.(?:png|jpe?g|gif|webp|svg|css|js|woff2?|ico)$|^(?:example|test|name|your)@", re.IGNORECASE
)


@dataclass(frozen=True)
class FoundEmail:
    """One address, and why it was chosen over the others."""

    address: str
    is_role: bool
    matches_website: bool
    mentions: int
    from_mailto: bool

    @property
    def rank(self) -> tuple[int, int, int, int]:
        """Best first. A same-domain role address in a ``mailto:`` link wins.

        Order matters and is not arbitrary: the domain is the strongest signal
        that this is the right *company*, the role is the strongest signal that
        it is the right *box*, and frequency only breaks ties between two
        addresses that are already plausible.
        """
        return (
            -int(self.matches_website),
            -int(self.is_role),
            -int(self.from_mailto),
            -self.mentions,
        )


def _normalise(local: str, domain: str) -> str:
    domain = re.sub(r"\s*[\[(]\s*(?:dot|punkt)\s*[\])]\s*", ".", domain, flags=re.IGNORECASE)
    domain = re.sub(r"\s+(?:dot|punkt)\s+", ".", domain, flags=re.IGNORECASE)
    return f"{local.strip()}@{re.sub(r'\\s+', '', domain)}".lower().rstrip(".")


def _site_domain(website: str | None) -> str:
    if not website:
        return ""
    host = urlsplit(website if "//" in website else f"//{website}").hostname or ""
    return host.lower().removeprefix("www.")


def _same_site(domain: str, site: str) -> bool:
    """Whether an address belongs to the company whose page it was found on.

    Suffix rather than equality, so ``mail@shop.example.de`` counts as the
    company's when the site is ``example.de``.
    """
    if not site:
        return False
    return domain == site or domain.endswith(f".{site}")


def find_emails(
    text: str, *, mailto: tuple[str, ...] = (), website: str | None = None
) -> tuple[FoundEmail, ...]:
    """Every address on one company's pages, best first.

    ``mailto`` links are passed separately because they are the same fact
    written honestly: a site that obfuscates its address in the body will often
    still link it, and a link needs no de-obfuscation to be read.
    """
    site = _site_domain(website)
    counts: dict[str, int] = {}
    linked: set[str] = set()

    for raw in mailto:
        address = raw.strip().lower()
        if "@" in address and not _NOT_AN_ADDRESS.search(address):
            linked.add(address)
            counts[address] = counts.get(address, 0) + 1

    for match in _CANDIDATE.finditer(text):
        address = _normalise(match.group(1), match.group(2))
        domain = address.split("@")[-1]
        # A bare "a@b" is not an address anybody can write to, and a domain
        # with no dot is almost always a sentence that happened to contain "at".
        if "." not in domain or _NOT_AN_ADDRESS.search(address):
            continue
        counts[address] = counts.get(address, 0) + 1

    found = [
        FoundEmail(
            address=address,
            is_role=address.split("@")[0] in ROLE_NAMES,
            matches_website=_same_site(address.split("@")[-1], site),
            mentions=count,
            from_mailto=address in linked,
        )
        for address, count in counts.items()
    ]
    return tuple(sorted(found, key=lambda item: item.rank))


def best_email(
    text: str, *, mailto: tuple[str, ...] = (), website: str | None = None
) -> FoundEmail | None:
    """The one address to show, or None when nothing on the page qualifies.

    An address whose domain does not match the company's own site is returned
    only when it is a role box. A named person at an unrelated domain is far
    more likely to be the web designer in the page footer than the shop, and
    putting that in a directory would be both wrong and rude.
    """
    for candidate in find_emails(text, mailto=mailto, website=website):
        if candidate.matches_website or candidate.is_role:
            return candidate
    return None


# --------------------------------------------------------------- summaries

# Long enough to say something, short enough to sit under a company name in a
# list. Cut on a word boundary, because a summary ending mid-word reads as a
# bug rather than as an abbreviation.
MAX_SUMMARY_CHARS = 220


def clean_summary(description: str) -> str:
    """A company's own meta description, tidied - or "" when it says nothing.

    Not a sentence picked out of the page body. Somebody at the business wrote
    this line to describe the business, and it is the same text a search engine
    shows them; a first paragraph, by contrast, is as often a cookie notice or
    a navigation list as a description.

    Boilerplate that carries no information about *this* company is dropped
    rather than shown: a directory of 136 identical "Willkommen auf unserer
    Homepage" lines is worse than a directory of blanks, because it looks like
    content.
    """
    summary = " ".join(description.split())
    if len(summary) < 25:
        return ""

    lowered = summary.casefold()
    empty_phrases = (
        "willkommen auf unserer",
        "herzlich willkommen auf",
        "diese website benutzt cookies",
        "just another wordpress",
        "wordpress site",
        "beschreibung der website",
        "lorem ipsum",
    )
    if any(lowered.startswith(phrase) for phrase in empty_phrases):
        return ""

    if len(summary) <= MAX_SUMMARY_CHARS:
        return summary
    # The en and em dashes below are punctuation being stripped from real German
    # marketing copy, not a typo for a hyphen - hence the suppression.
    cut = summary[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:-–—")  # noqa: RUF001
    return f"{cut}…"
