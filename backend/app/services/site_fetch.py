"""Fetch a company's own website and reduce it to readable text.

This is the only place in the product that follows a URL somebody else wrote.
The addresses come from OpenStreetMap, which anybody may edit, so every one of
them is untrusted input that this server is about to make a request to. That is
server-side request forgery in its textbook form, and the guards below are the
answer rather than a precaution:

* **only http and https** - no ``file://``, no ``gopher://``
* **no private, loopback or link-local address** - the one that matters is
  ``169.254.169.254``, the cloud metadata endpoint, which on many hosts hands
  out credentials to anything that asks
* **resolved before the request, not after** - a hostname that resolves into
  private space is refused even though it looks public
* **a size cap and a timeout** - a page that never ends must not become a
  process that never returns
* **robots.txt is honoured** - this reads other people's sites, and a tool that
  ignores that is a tool their operators are entitled to block

No HTML parser dependency. The job is "get the readable words out", not
"manipulate a DOM", and the standard library's parser does that in sixty lines
without an install that has already failed twice in this environment.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

USER_AGENT = "ProduceYourBrandBot/0.1 (+capability survey; respects robots.txt)"

# Text inside these never describes what a company does.
_SKIP_CONTENT = {"script", "style", "noscript", "template", "svg"}

# Block-level tags whose end should become a line break, so "Siebdruck" and
# "Textildruck" from two list items do not arrive as one word.
_BREAKS = {
    "p",
    "div",
    "br",
    "li",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "section",
    "article",
    "td",
    "th",
    "figcaption",
    "blockquote",
}

MAX_BYTES = 1_500_000
TIMEOUT_SECONDS = 15.0


class SiteFetchError(RuntimeError):
    """The page could not be fetched, for a reason worth telling somebody."""


class _TextExtractor(HTMLParser):
    """Readable text, plus the links, in one pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth += 1
            return
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []
        if tag in _BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor).strip()))
            self._href = None
            self._anchor = []
        if tag in _BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(data)
        if self._href is not None:
            self._anchor.append(data.strip())

    def text(self) -> str:
        joined = "".join(self.parts)
        lines = [" ".join(line.split()) for line in joined.splitlines()]
        return "\n".join(line for line in lines if line)


@dataclass(frozen=True)
class FetchedPage:
    """One page, reduced to what a reader would see."""

    url: str
    text: str
    links: tuple[tuple[str, str], ...] = field(default=())

    @property
    def is_substantial(self) -> bool:
        """Whether there is enough here to be worth reading.

        A cookie wall or a redirect stub produces a few dozen words and no
        capability information, and running an extraction over it costs a model
        call to learn nothing.
        """
        return len(self.text.split()) >= 40


Resolver = Callable[[str], set[str]]


def _resolve(host: str) -> set[str]:
    """Every address a hostname answers with. Empty when it answers with none."""
    try:
        # sockaddr[0] is the address; typed loosely by the stdlib, narrowed here.
        return {str(info[4][0]) for info in socket.getaddrinfo(host, None)}
    except OSError:
        return set()


def address_refusal(url: str, resolve: Resolver = _resolve) -> str | None:
    """Why this address may not be fetched, in words, or ``None`` if it may.

    The reasons are kept apart because they mean opposite things. A domain that
    no longer resolves is a *dead company website* - a finding about stale
    directory data, worth acting on. An address that resolves into private
    space is an *attempted intrusion*, or a misconfiguration that would become
    one. Reporting both as "not a public address", as this first did, made six
    closed Berlin print shops look like blocked attacks.

    Every resolved address is checked, not just the first: a hostname can
    answer with one public and one private address, and a client that took the
    first would be trivially steered.

    ``resolve`` is injectable so the tests can exercise this without DNS. A
    suite that needed the network to check an SSRF guard would be a suite that
    stopped checking it on a train.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "not an http or https address"
    if not parsed.hostname:
        return "no hostname in the address"

    addresses = resolve(parsed.hostname)
    if not addresses:
        return "the domain does not resolve - the site is probably gone"

    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return "the hostname resolved to something that is not an IP address"
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return "the hostname resolves into private or reserved address space"
    return None


def is_fetchable(url: str, *, resolve: Resolver = _resolve) -> bool:
    """Whether this address may be requested at all."""
    return address_refusal(url, resolve) is None


def _robots_allows(url: str, client: httpx.Client) -> bool:
    """Whether the site's own robots.txt permits this.

    A site that does not publish one, or whose robots.txt cannot be read, is
    treated as allowing - which is what the standard says and what every other
    well-behaved crawler does. A site that publishes a refusal is obeyed.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = client.get(robots_url, timeout=TIMEOUT_SECONDS)
        if response.status_code != 200:
            return True
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        return bool(parser.can_fetch(USER_AGENT, url))
    except Exception:
        return True


def fetch_page(
    url: str, *, client: httpx.Client | None = None, resolve: Resolver = _resolve
) -> FetchedPage:
    """Fetch one page and return its readable text.

    Raises :class:`SiteFetchError` for anything that is not a readable HTML
    page, including a refusal by robots.txt - the caller decides what a skipped
    site means, and silence would make an unread site look like an empty one.
    """
    refusal = address_refusal(url, resolve)
    if refusal is not None:
        raise SiteFetchError(f"not fetching {url!r}: {refusal}")

    owned = client is None
    http = client or httpx.Client(follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        if not _robots_allows(url, http):
            raise SiteFetchError(f"robots.txt disallows {url!r}")

        response = http.get(url, timeout=TIMEOUT_SECONDS)
        if response.status_code >= 400:
            raise SiteFetchError(f"{url!r} answered {response.status_code}")

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            raise SiteFetchError(f"{url!r} is {content_type or 'of unknown type'}, not HTML")

        body = response.text[:MAX_BYTES]
    except SiteFetchError:
        raise
    except Exception as error:
        raise SiteFetchError(f"{url!r} could not be fetched: {type(error).__name__}") from error
    finally:
        if owned:
            http.close()

    extractor = _TextExtractor()
    extractor.feed(body)
    page = FetchedPage(
        url=str(response.url),
        text=extractor.text(),
        links=tuple(extractor.links),
    )
    log_event(
        logger,
        Event.COMPANY_PAGE_FETCHED,
        "company page fetched",
        url=url,
        words=len(page.text.split()),
        substantial=page.is_substantial,
    )
    return page


# Anchor text that tends to lead to the page describing what a company does.
# German first, because these are German companies.
SERVICE_WORDS = (
    "leistung",
    "service",
    "produkt",
    "angebot",
    "technik",
    "verfahren",
    "druck",
    "veredelung",
    "portfolio",
    "was wir",
    "unser",
)


def service_links(page: FetchedPage, *, limit: int = 4) -> tuple[str, ...]:
    """Same-site links whose wording suggests a page about their services.

    Same-site only, and absolute URLs resolved against the page they were found
    on, so a redirect to somebody else's domain cannot pull this crawler
    somewhere it never agreed to go.
    """
    origin = urlparse(page.url)
    found: list[str] = []
    seen: set[str] = {page.url}

    for href, anchor in page.links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        target = urljoin(page.url, href)
        parsed = urlparse(target)
        if parsed.netloc != origin.netloc or target in seen:
            continue
        haystack = f"{anchor} {parsed.path}".casefold()
        if any(word in haystack for word in SERVICE_WORDS):
            seen.add(target)
            found.append(target)
        if len(found) >= limit:
            break

    return tuple(found)
