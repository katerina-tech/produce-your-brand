"""Two-stage matching: retrieve plausible companies, then check each one.

The embedder here is HashingEmbedder, which gives real lexical similarity
rather than noise - so these tests assert actual ranking, not merely that the
plumbing runs.

The property worth the most: a model that says "yes" without being able to
quote the company's own words does not produce a match. Similarity is a hint;
a recommendation needs a sentence somebody wrote.
"""

from __future__ import annotations

from datetime import date

from app.domain.capability import CapabilityClaim, SupplierCapabilities
from app.services.capability_match import (
    CapabilityIndex,
    MatchVerdict,
    find_matches,
    verify_candidate,
)
from tests.fakes import FailingEmbedder, FailingProvider, HashingEmbedder, ScriptedProvider

TODAY = date(2026, 9, 15)


def _company(
    partner_id: str, name: str, *claims: str, methods: tuple[object, ...] = ()
) -> SupplierCapabilities:
    return SupplierCapabilities(
        partner_id=partner_id,
        partner_name=name,
        source_urls=(f"https://{partner_id}.example/leistungen",),
        claims=tuple(CapabilityClaim(text=claim, quote=claim) for claim in claims),
        extracted_on=TODAY,
    )


TEXTILE = _company(
    "textil",
    "Spree Textildruck",
    "Siebdruck auf Baumwolle und Mischgewebe",
    "Transferdruck auf Textilien und beschichteten Oberflaechen",
    "Stickerei auf Arbeitskleidung",
)
METAL = _company(
    "metall",
    "Kreuzberg Laser Atelier",
    "Lasergravur auf Edelstahl und Aluminium",
    "Gravur von Typenschildern und Werkzeugen",
)
PAPER = _company(
    "papier",
    "Mitte Copyshop",
    "Digitaldruck von Broschueren und Visitenkarten",
    "Plakate und Flyer in kleinen Auflagen",
)

ALL = (TEXTILE, METAL, PAPER)


def _index(companies: tuple[SupplierCapabilities, ...] = ALL) -> CapabilityIndex:
    index = CapabilityIndex(HashingEmbedder())
    index.build(companies)
    return index


# ----------------------------------------------------------------- retrieval


def test_retrieval_finds_the_company_whose_own_words_fit() -> None:
    """No keyword search finds "Transferdruck auf beschichteten Oberflaechen"
    from a request about printing on a coated mat. Similarity over what the
    company wrote does."""
    candidates = _index().search("Transferdruck auf beschichteten Oberflaechen Textilien")

    assert candidates[0].partner_id == "textil"


def test_a_request_about_metal_does_not_rank_the_textile_shop_first() -> None:
    candidates = _index().search("Lasergravur auf Edelstahl Typenschilder")

    assert candidates[0].partner_id == "metall"


def test_every_candidate_carries_the_claims_it_was_retrieved_on() -> None:
    """Verification needs something to quote, and a buyer needs something to
    read. A candidate that arrived as an id and a number would give neither."""
    candidate = _index().search("Siebdruck Baumwolle")[0]

    assert candidate.claims
    assert "Siebdruck auf Baumwolle und Mischgewebe" in candidate.evidence_text


def test_the_number_of_candidates_is_bounded() -> None:
    """Each one costs a model call in the next stage."""
    assert len(_index().search("Druck", limit=2)) == 2


def test_a_company_with_nothing_read_from_it_is_not_in_the_index() -> None:
    """An empty record is a company whose site could not be read, not a company
    that does nothing - but it cannot be retrieved on words it never gave."""
    silent = SupplierCapabilities(
        partner_id="stumm", partner_name="Quiet GmbH", source_urls=(), extracted_on=TODAY
    )

    index = _index((*ALL, silent))

    assert index.size == 3
    assert all(c.partner_id != "stumm" for c in index.search("Druck", limit=10))


def test_an_empty_query_retrieves_nothing_rather_than_everything() -> None:
    assert _index().search("   ") == ()


def test_an_embedding_outage_costs_retrieval_not_the_product() -> None:
    """The caller still has the deterministic matcher it always had."""
    index = CapabilityIndex(FailingEmbedder())

    assert index.build(ALL) == 0
    assert index.search("Siebdruck") == ()


# --------------------------------------------------------------- verification


def _verdict(**fields: object) -> ScriptedProvider:
    return ScriptedProvider({MatchVerdict: MatchVerdict.model_validate(fields)})


def test_a_yes_that_quotes_the_company_is_a_supported_match() -> None:
    candidate = _index().search("Siebdruck Baumwolle")[0]

    match = verify_candidate(
        "100 cotton shirts with a printed logo",
        candidate,
        _verdict(
            can_do_it=True,
            reason="They screen-print on cotton.",
            quote="Siebdruck auf Baumwolle und Mischgewebe",
        ),
    )

    assert match.is_supported is True
    assert match.quote_verified is True


def test_a_yes_whose_quote_the_company_never_wrote_is_demoted_to_unclear() -> None:
    """The property this stage exists for. A model that cannot point at where a
    company said something must not have that company recommended on it - and
    the company stays in the list, because all that was established is that the
    model could not find the words, not that the shop cannot do the work."""
    candidate = _index().search("Siebdruck Baumwolle")[0]

    match = verify_candidate(
        "100 cotton shirts",
        candidate,
        _verdict(
            can_do_it=True,
            reason="They print on everything.",
            quote="Wir bedrucken alle Materialien",
        ),
    )

    assert match.quote_verified is False
    assert match.is_supported is False
    assert match.candidate.partner_id == "textil", "still listed, just not supported"


def test_unclear_is_an_ordinary_answer() -> None:
    candidate = _index().search("Siebdruck Baumwolle")[0]

    match = verify_candidate(
        "anodised aluminium name plates",
        candidate,
        _verdict(can_do_it=None, reason="Nothing here mentions metal.", quote=""),
    )

    assert match.can_do_it is None
    assert match.is_supported is False


def test_without_a_model_nothing_is_claimed() -> None:
    """An unchecked candidate is exactly as informative as no candidate.
    Showing a similarity score as if it were a judgement would be the one thing
    this whole design is against."""
    candidate = _index().search("Siebdruck Baumwolle")[0]

    match = verify_candidate("100 cotton shirts", candidate, None)

    assert match.can_do_it is None
    assert match.is_supported is False
    assert "no model is configured" in match.reason.lower()


def test_a_failed_call_does_not_read_as_a_missing_model() -> None:
    """Two different repairs, so two different sentences.

    "No model is configured" sends somebody to the settings. A call that did not
    go through sends them to the gateway - which is where an exhausted balance
    or a rate limit actually is, and where this product's real outage was while
    its own message pointed elsewhere.
    """
    candidate = _index().search("Siebdruck Baumwolle")[0]

    match = verify_candidate("100 cotton shirts", candidate, FailingProvider())

    assert match.can_do_it is None
    assert match.is_supported is False
    assert "did not go through" in match.reason
    assert "no model is configured" not in match.reason.lower()


# ------------------------------------------------------------ the two together


def test_supported_matches_come_first_and_the_rest_are_kept() -> None:
    """ "We looked and could not tell" is information a buyer can act on: it is
    the list of companies worth a phone call."""
    provider = _verdict(
        can_do_it=True,
        reason="They screen-print on cotton.",
        quote="Siebdruck auf Baumwolle und Mischgewebe",
    )

    matches = find_matches("100 cotton shirts with a printed logo", _index(), provider, limit=3)

    assert len(matches) == 3, "unsupported candidates are kept, not dropped"
    assert matches[0].is_supported is True
    assert matches[0].candidate.partner_id == "textil"
    assert all(not m.is_supported for m in matches[1:])


def test_nothing_retrieved_means_nothing_verified() -> None:
    empty = CapabilityIndex(HashingEmbedder())

    assert find_matches("anything at all", empty, _verdict(can_do_it=True, reason="x")) == ()


def test_the_verdict_schema_cannot_rank_or_score() -> None:
    """The model answers one question about one company. Ordering is decided by
    code afterwards, because a model's ordering is one nobody can explain."""
    fields = set(MatchVerdict.model_fields)

    assert "score" not in fields
    assert "rank" not in fields
    assert fields == {"can_do_it", "reason", "quote"}
