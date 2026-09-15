"""Reading a contact address off a page that does not want it read.

The case that started this file is real and was found by hand: A&W Digitaldruck
publishes ``info [at] aw-digital.de``, and the directory said "no email
published" beside their name. Thirty-two other Berlin companies were in the
same position.

The property worth the most here is not "finds more addresses". It is **finds
the right one**: a page carries a role box, sometimes a named employee, and
often the web designer in the footer, and sending a buyer's request to the
wrong one of those is worse than showing no address at all.
"""

from __future__ import annotations

import pytest

from app.services.contact_extract import (
    MAX_SUMMARY_CHARS,
    best_email,
    clean_summary,
    find_emails,
)

SITE = "https://www.aw-digital.de/"


# ------------------------------------------------------------ de-obfuscation


@pytest.mark.parametrize(
    "written",
    [
        "info@aw-digital.de",
        "info [at] aw-digital.de",
        "info (at) aw-digital.de",
        "info[at]aw-digital.de",
        "info [ät] aw-digital.de",
        "info at aw-digital.de",
        "info [at] aw-digital [dot] de",
        "info (at) aw-digital (punkt) de",
        "INFO [AT] AW-DIGITAL.DE",
    ],
)
def test_the_ways_a_german_print_shop_hides_its_address(written: str) -> None:
    """Every spelling here was seen on a real site. Each is one separator
    standing in for one character, which makes undoing them a rule rather than
    a judgement."""
    found = best_email(f"Schreiben Sie uns: {written}", website=SITE)

    assert found is not None
    assert found.address == "info@aw-digital.de"


def test_the_case_that_was_actually_missed() -> None:
    """Verbatim from aw-digital.de, which the survey read and reported as
    having no email."""
    page = "A&W Digitaldruck\nTelefon 030 4515813\ninfo [at] aw-digital.de\nImpressum"

    found = best_email(page, website="http://www.aw-digital.de")

    assert found is not None
    assert found.address == "info@aw-digital.de"
    assert found.matches_website is True


# ------------------------------------------------------------------ choosing


def test_a_sentence_is_not_swallowed_into_the_local_part() -> None:
    """The bug the first pass had. RFC 5322 permits "!" in a local part, so
    "schreiben Sie uns! info@..." parsed as an address beginning "uns!" - a
    technically valid reading of a sentence that plainly meant otherwise."""
    found = best_email("schreiben Sie uns! info@berliner-buchdruck.de")

    assert found is not None
    assert found.address == "info@berliner-buchdruck.de"


def test_the_company_s_own_domain_wins() -> None:
    """The strongest signal that an address belongs to *this* company rather
    than to whoever built their website."""
    page = "info@example-agentur.de baute diese Seite. Kontakt: post@druckerei.de"

    found = best_email(page, website="https://druckerei.de")

    assert found is not None
    assert found.address == "post@druckerei.de"


def test_a_role_box_beats_a_named_person_at_the_same_company() -> None:
    """Two reasons, and the second is not about data quality: a directory
    should carry the box a business put up to be written to, not an individual's
    work address they never offered for the purpose."""
    page = "Kontakt: info@druckerei.de - Ansprechpartnerin: simone.priess@druckerei.de"

    found = best_email(page, website="https://druckerei.de")

    assert found is not None
    assert found.address == "info@druckerei.de"


def test_a_stranger_s_named_address_is_not_used_at_all() -> None:
    """A named person at an unrelated domain is far more likely to be the web
    designer in the footer than the shop. No address is better than that one."""
    page = "Design und Umsetzung: max.mustermann@webagentur-mitte.de"

    assert best_email(page, website="https://druckerei.de") is None


def test_a_role_box_elsewhere_is_still_offered() -> None:
    """Small businesses really do use gmail, and a group of workshops really
    does share one domain. A role box is a box somebody watches."""
    found = best_email("Kontakt: kontakt@gmail.com", website="https://druckerei.de")

    assert found is not None
    assert found.address == "kontakt@gmail.com"


def test_a_mailto_link_is_preferred_over_the_same_address_spelled_out() -> None:
    """A site that obfuscates in the body will often still link the address
    honestly, and a link needs no de-obfuscation to be read."""
    found = find_emails(
        "info [at] druckerei.de", mailto=("info@druckerei.de",), website="https://druckerei.de"
    )

    assert found[0].address == "info@druckerei.de"
    assert found[0].from_mailto is True


def test_a_page_with_no_address_finds_none() -> None:
    assert best_email("Wir freuen uns auf Ihren Besuch. Rufen Sie an.") is None


def test_the_word_at_in_a_sentence_is_not_an_address() -> None:
    """ "look at openstreetmap.org" is a sentence, not a contact."""
    assert best_email("Mehr at openstreetmap.org finden Sie", website="https://x.de") is None


@pytest.mark.parametrize(
    "junk",
    ["logo@2x.png", "sprite@2x.jpg", "example@example.com", "your@email.de"],
)
def test_things_that_look_like_addresses_and_are_not(junk: str) -> None:
    assert best_email(f"Kontakt {junk}", website="https://x.de") is None


def test_a_subdomain_still_counts_as_the_company() -> None:
    found = best_email("mail@shop.druckerei.de", website="https://druckerei.de")

    assert found is not None
    assert found.matches_website is True


# ----------------------------------------------------------------- summaries


def test_the_summary_is_the_company_s_own_line() -> None:
    """Their meta description, not a sentence picked out of the page body.
    Somebody at the business wrote it to describe the business."""
    assert clean_summary("  Der Copyshop  im Herzen   Berlins ") == "Der Copyshop im Herzen Berlins"


def test_a_long_summary_is_cut_on_a_word() -> None:
    """A line ending mid-word reads as a bug rather than as an abbreviation."""
    summary = clean_summary("Wir drucken " + "Broschueren " * 60)

    assert len(summary) <= MAX_SUMMARY_CHARS + 1
    assert summary.endswith("…")
    assert not summary[:-1].endswith(" ")


@pytest.mark.parametrize(
    "boilerplate",
    [
        "Willkommen auf unserer Homepage der Firma",
        "Herzlich willkommen auf unserer neuen Internetseite",
        "Just another WordPress site for your business",
        "Diese Website benutzt Cookies um Ihnen das beste Erlebnis zu bieten",
    ],
)
def test_boilerplate_is_dropped_rather_than_shown(boilerplate: str) -> None:
    """136 identical "Willkommen" lines would be worse than 136 blanks, because
    they look like content."""
    assert clean_summary(boilerplate) == ""


def test_too_short_to_say_anything_is_empty() -> None:
    assert clean_summary("Druckerei") == ""
    assert clean_summary("") == ""
