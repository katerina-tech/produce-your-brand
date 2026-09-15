"""Fetching a company's own website.

This module is the only place the product follows a URL somebody else wrote,
and those URLs come from OpenStreetMap, which anybody may edit. So most of this
file is about refusing: the interesting cases are the addresses that must never
be requested, not the pages that parse nicely.

No test touches the network. httpx.MockTransport stands in, the same way
test_osm_search.py does it.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.site_fetch import (
    FetchedPage,
    SiteFetchError,
    address_refusal,
    fetch_page,
    is_fetchable,
    service_links,
)

PAGE = """
<html><head><title>Spree Druck</title>
<style>.nav{color:red}</style>
<script>var tracking = "Siebdruck auf allem";</script>
</head><body>
<nav><a href="/leistungen">Leistungen</a> <a href="/kontakt">Kontakt</a></nav>
<h1>Spree Textildruck</h1>
<p>Wir drucken auf Textilien seit 1998.</p>
<ul><li>Siebdruck</li><li>Transferdruck</li><li>Stickerei</li></ul>
<p>Mindestauflage 50 St&uuml;ck. Lieferzeit 10 Werktage.</p>
<p>Seit 1998 veredeln wir Textilien f&uuml;r Agenturen, Vereine und Unternehmen in
Berlin und Brandenburg. Wir bedrucken T-Shirts, Hoodies, Taschen und Arbeitskleidung
in kleinen wie in gro&szlig;en Auflagen. Kundeneigene Ware nehmen wir nach
Absprache an, sofern das Material f&uuml;r das gew&auml;hlte Verfahren geeignet ist.
Fragen Sie uns gern nach einem Muster vor der Produktion.</p>
<a href="https://anderer-anbieter.de/leistungen">Partner</a>
<a href="mailto:info@spree.de">Mail</a>
</body></html>
"""


# A public address, so the guard allows it. Injected rather than looked up:
# a suite that needed DNS to check an SSRF guard would stop checking it offline.
PUBLIC = {"93.184.216.34"}


def _resolves_public(host: str) -> set[str]:
    return PUBLIC


def _fetch(url: str = "https://spree.example/", **kwargs: object) -> FetchedPage:
    """fetch_page with the stub resolver, which every test here wants."""
    client = kwargs.pop("client", None) or _client()
    return fetch_page(url, client=client, resolve=_resolves_public)  # type: ignore[arg-type]


def _client(
    body: str = PAGE,
    status: int = 200,
    content_type: str = "text/html; charset=utf-8",
    robots: str = "",
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200 if robots else 404, text=robots)
        return httpx.Response(status, text=body, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler))


# ------------------------------------------------ what must never be fetched


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata: hands out credentials
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://127.0.0.1:8000/api/health",  # our own API
        "http://localhost/admin",
        "http://192.168.1.1/",
        "http://10.0.0.5/",
        "file:///etc/passwd",
        "gopher://evil.example/",
        "ftp://example.com/x",
        "not a url at all",
        "",
    ],
)
def test_addresses_that_must_never_be_requested(url: str) -> None:
    """Server-side request forgery, in its textbook form. The website field in
    OpenStreetMap is editable by anybody, and this server is the one making the
    request - so the guard is the feature, not a precaution."""
    assert is_fetchable(url) is False


def test_a_refused_address_is_not_even_attempted() -> None:
    """The check happens before the client is touched, so a blocked address
    costs no connection at all."""
    with pytest.raises(SiteFetchError, match="private or reserved"):
        fetch_page("http://169.254.169.254/", client=_client())


def test_an_ordinary_company_address_is_allowed() -> None:
    assert is_fetchable("https://spree.example/", resolve=_resolves_public) is True


# -------------------------------------------------------------- reading a page


def test_the_readable_words_survive_and_the_machinery_does_not() -> None:
    """Script and style content is not what a company does. A tracking script
    that happens to contain the word 'Siebdruck' must not become a capability."""
    page = _fetch()

    assert "Wir drucken auf Textilien seit 1998." in page.text
    assert "Siebdruck" in page.text
    assert "var tracking" not in page.text
    assert "color:red" not in page.text


def test_list_items_do_not_run_into_one_another() -> None:
    """Without a break at block tags, three capabilities arrive as
    'SiebdruckTransferdruckStickerei' - one word that matches nothing."""
    page = _fetch()

    assert "SiebdruckTransferdruck" not in page.text
    lines = page.text.splitlines()
    assert "Siebdruck" in lines
    assert "Transferdruck" in lines


def test_html_entities_come_back_as_the_characters_they_are() -> None:
    """A German page is full of them, and 'St&uuml;ck' matches nothing."""
    page = _fetch()

    assert "Stück" in page.text


def test_a_page_with_almost_no_words_is_not_worth_reading() -> None:
    """A cookie wall or a redirect stub. Running an extraction over it costs a
    model call to learn nothing."""
    stub = fetch_page(
        "https://spree.example/",
        client=_client("<html><body>Cookies</body></html>"),
        resolve=_resolves_public,
    )

    assert stub.is_substantial is False
    assert (
        fetch_page(
            "https://spree.example/", client=_client(), resolve=_resolves_public
        ).is_substantial
        is True
    )


# ----------------------------------------------------------------- refusals


def test_robots_txt_is_obeyed() -> None:
    """This reads other people's sites. A tool that ignores their robots.txt is
    one their operators are entitled to block."""
    disallowing = _client(robots="User-agent: *\nDisallow: /")

    with pytest.raises(SiteFetchError, match="robots"):
        _fetch("https://spree.example/leistungen", client=disallowing)


def test_a_site_with_no_robots_file_is_allowed() -> None:
    """404 on robots.txt means no rules, which the standard reads as permitted."""
    assert fetch_page(
        "https://spree.example/", client=_client(robots=""), resolve=_resolves_public
    ).text


def test_a_robots_file_that_allows_us_is_followed() -> None:
    allowing = _client(robots="User-agent: *\nDisallow: /admin")

    assert _fetch("https://spree.example/leistungen", client=allowing).text


def test_a_pdf_is_refused_rather_than_parsed_as_html() -> None:
    with pytest.raises(SiteFetchError, match="not HTML"):
        fetch_page(
            "https://spree.example/x",
            client=_client(content_type="application/pdf"),
            resolve=_resolves_public,
        )


def test_an_error_page_is_refused() -> None:
    with pytest.raises(SiteFetchError, match="404"):
        fetch_page("https://spree.example/", client=_client(status=404), resolve=_resolves_public)


def test_a_network_failure_becomes_a_typed_error() -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(SiteFetchError, match="could not be fetched"):
        fetch_page(
            "https://spree.example/",
            client=httpx.Client(transport=httpx.MockTransport(explode)),
            resolve=_resolves_public,
        )


# ------------------------------------------------------------ following links


def test_links_that_look_like_a_services_page_are_found() -> None:
    page = _fetch()

    assert "https://spree.example/leistungen" in service_links(page)


def test_a_link_to_somebody_else_is_never_followed() -> None:
    """Same-site only. A crawler that followed an outbound link would end up
    reading a page it never agreed to read, at an address nobody checked."""
    page = _fetch()

    assert all("anderer-anbieter" not in link for link in service_links(page))


def test_mailto_and_anchors_are_not_links_to_follow() -> None:
    page = _fetch()

    assert all(not link.startswith("mailto:") for link in service_links(page))


def test_a_page_with_no_links_yields_none() -> None:
    bare = FetchedPage(url="https://spree.example/", text="words " * 60)

    assert service_links(bare) == ()


# ------------------------------------------- telling the two refusals apart


def test_a_dead_domain_and_a_blocked_address_are_different_findings() -> None:
    """Six of eighty-nine Berlin companies in the survey had a website that no
    longer resolves - closed businesses, not attempted intrusions. Reporting
    both as "not a public address" made stale directory data look like a
    security event, and hid a fact worth acting on."""
    gone = address_refusal("https://closed-print-shop.example/", resolve=lambda _host: set())
    blocked = address_refusal("http://169.254.169.254/", resolve=lambda _host: {"169.254.169.254"})

    assert gone is not None and "does not resolve" in gone
    assert blocked is not None and "private or reserved" in blocked
    assert gone != blocked


def test_an_address_that_is_fine_has_no_refusal() -> None:
    assert address_refusal("https://spree.example/", resolve=_resolves_public) is None


def test_a_wrong_scheme_says_which_problem_it_is() -> None:
    refusal = address_refusal("file:///etc/passwd", resolve=_resolves_public)

    assert refusal is not None and "http" in refusal


def test_one_private_address_among_public_ones_still_refuses() -> None:
    """A hostname can answer with both, and a client taking the first would be
    trivially steered."""
    mixed = address_refusal(
        "https://sneaky.example/", resolve=lambda _host: {"93.184.216.34", "127.0.0.1"}
    )

    assert mixed is not None and "private or reserved" in mixed
