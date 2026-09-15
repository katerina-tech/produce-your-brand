"""Where a reading of a company's website is kept.

The properties here are about the difference between kinds of absence. "Nobody
looked", "we looked and they said nothing", "we looked and the model fell over"
all produce a company with no claims, and treating them alike would either
write off companies a bad afternoon touched or re-bill every company on every
run. Each test below is one of those confusions, made impossible.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.domain.capability import CapabilityClaim, SupplierCapabilities
from app.domain.enums import ProductionMethod
from app.repositories import db
from app.repositories.capability_repo import CapabilityRepository
from app.repositories.database import Database
from app.repositories.partner_repo import PartnerRepository

DIRECTORY = Path(__file__).resolve().parent.parent / "data" / "berlin_partners.json"
READ_ON = date(2026, 9, 15)


@pytest.fixture
def connection(tmp_path: Path) -> Database:
    """One database with the directory already seeded: a capability row points
    at a company, so the company has to be there first."""
    database = db.connect(tmp_path / "caps.db")
    db.initialize_schema(database)
    PartnerRepository(database, DIRECTORY).seed_if_empty()
    return database


@pytest.fixture
def partners(connection: Database) -> PartnerRepository:
    return PartnerRepository(connection)


@pytest.fixture
def repository(connection: Database) -> CapabilityRepository:
    return CapabilityRepository(connection)


@pytest.fixture
def partner_id(partners: PartnerRepository) -> str:
    return partners.all()[0].id


def _reading(partner_id: str, *claims: str) -> SupplierCapabilities:
    return SupplierCapabilities(
        partner_id=partner_id,
        partner_name="A company",
        source_urls=("https://example.de/leistungen",),
        claims=tuple(
            CapabilityClaim(text=text, quote=f"wir bieten {text}", kind="method") for text in claims
        ),
        extracted_on=READ_ON,
    )


# ------------------------------------------------------------------ round trip


def test_a_reading_comes_back_with_its_quotes(
    repository: CapabilityRepository, partner_id: str
) -> None:
    """The quote is the whole point. A claim without the words it came from is
    this product's summary of a named business rather than the business."""
    repository.save(_reading(partner_id, "Siebdruck auf Textilien"))

    stored = repository.get(partner_id)

    assert stored is not None
    assert [claim.text for claim in stored.capabilities.claims] == ["Siebdruck auf Textilien"]
    assert stored.capabilities.claims[0].quote == "wir bieten Siebdruck auf Textilien"


def test_claims_keep_the_order_they_were_read_in(
    repository: CapabilityRepository, partner_id: str
) -> None:
    """A list that reshuffles between page loads is one nobody can check
    methodically, and checking is the entire purpose of showing it."""
    repository.save(_reading(partner_id, "erste", "zweite", "dritte"))

    stored = repository.get(partner_id)

    assert stored is not None
    assert [claim.text for claim in stored.capabilities.claims] == ["erste", "zweite", "dritte"]


def test_a_method_survives_the_round_trip(
    repository: CapabilityRepository, partner_id: str
) -> None:
    """The enum is a subset of what a company can do, and the deterministic
    gates are its only reader - so it has to arrive intact or not at all."""
    repository.save(
        SupplierCapabilities(
            partner_id=partner_id,
            partner_name="A company",
            source_urls=("https://example.de/",),
            claims=(
                CapabilityClaim(
                    text="Siebdruck",
                    quote="Siebdruck",
                    kind="method",
                    method=ProductionMethod.SCREEN_PRINTING,
                ),
            ),
            extracted_on=READ_ON,
        )
    )

    stored = repository.get(partner_id)

    assert stored is not None
    assert stored.capabilities.claims[0].method is ProductionMethod.SCREEN_PRINTING


def test_a_company_nobody_read_is_none_rather_than_empty(
    repository: CapabilityRepository, partner_id: str
) -> None:
    """None and an empty reading mean opposite things. If this returned an empty
    record, "we have not looked" would read as "there is nothing there"."""
    assert repository.get(partner_id) is None


# --------------------------------------------------------------- re-reading


def test_reading_again_replaces_rather_than_accumulates(
    repository: CapabilityRepository, partner_id: str
) -> None:
    """A second run over the same site is a better reading of one company, not a
    second company - and a reading that used to have three claims and now has
    one must not leave two behind."""
    repository.save(_reading(partner_id, "erste", "zweite", "dritte"))
    repository.save(_reading(partner_id, "nur eine"))

    stored = repository.get(partner_id)

    assert stored is not None
    assert [claim.text for claim in stored.capabilities.claims] == ["nur eine"]
    assert repository.claim_count() == 1


def test_a_finished_reading_is_skipped_on_the_next_run(
    repository: CapabilityRepository, partner_id: str
) -> None:
    """Each company costs a model call. A run that died at company sixty must
    resume rather than pay for the first fifty-nine again."""
    repository.save(_reading(partner_id, "Siebdruck"))

    assert partner_id in repository.already_read()


def test_a_reading_that_found_nothing_still_counts_as_read(
    repository: CapabilityRepository, partner_id: str
) -> None:
    """ "We read this site and it said nothing about what they make" is a
    finding, and paying to rediscover it every run would be the same answer at
    the same price."""
    repository.save(_reading(partner_id))

    assert partner_id in repository.already_read()
    assert repository.count() == 1
    assert repository.with_claims_count() == 0


def test_a_failed_model_call_is_retried_rather_than_written_off(
    repository: CapabilityRepository, partner_id: str
) -> None:
    """The one that actually happened: an exhausted balance answered 402 for
    every company. That row records an outage, not a company - and skipping it
    would quietly condemn everything a bad afternoon touched until somebody
    thought to re-read all ninety."""
    repository.save(_reading(partner_id), model_failed=True)

    assert partner_id not in repository.already_read()
    reading = repository.get(partner_id)
    assert reading is not None
    assert "did not complete" in reading.explanation


def test_a_blocked_site_is_not_retried(repository: CapabilityRepository, partner_id: str) -> None:
    """Unlike an outage, a page the injection screen refuses will be refused
    again. Re-reading it is a model call spent to reach the same conclusion."""
    repository.save(_reading(partner_id), blocked=True)

    assert partner_id in repository.already_read()
    reading = repository.get(partner_id)
    assert reading is not None
    assert "injection screen" in reading.explanation


# ------------------------------------------------------------- confirmation


def test_confirmation_is_read_from_the_company_not_stored_twice(
    repository: CapabilityRepository, partners: PartnerRepository, partner_id: str
) -> None:
    """``confirmed_by_human`` is one fact. Writing it in two tables would be two
    places that can disagree about whether somebody vouched for a business."""
    repository.save(_reading(partner_id, "Siebdruck"))
    assert repository.get(partner_id).capabilities.confirmed_by_human is False  # type: ignore[union-attr]

    partners.mark_verified(partner_id)

    assert repository.get(partner_id).capabilities.confirmed_by_human is True  # type: ignore[union-attr]


def test_re_reading_a_site_does_not_undo_a_confirmation(
    repository: CapabilityRepository, partners: PartnerRepository, partner_id: str
) -> None:
    """A confirmation is somebody's work. A refresh of the pages is not a reason
    to throw it away - and because it lives on the company, it cannot be."""
    repository.save(_reading(partner_id, "Siebdruck"))
    partners.mark_verified(partner_id)

    repository.save(_reading(partner_id, "Siebdruck", "Digitaldruck"))

    assert repository.get(partner_id).capabilities.confirmed_by_human is True  # type: ignore[union-attr]


# ------------------------------------------------------------------- counting


def test_the_index_only_sees_companies_that_said_something(
    repository: CapabilityRepository, partners: PartnerRepository
) -> None:
    """Embedding an empty reading would put a company in the search results with
    no reason a buyer could read."""
    ids = [partner.id for partner in partners.all()[:3]]
    repository.save(_reading(ids[0], "Siebdruck"))
    repository.save(_reading(ids[1]))
    repository.save(_reading(ids[2], "Digitaldruck", "Buchbinderei"))

    assert repository.count() == 3
    assert repository.with_claims_count() == 2
    assert repository.claim_count() == 3
    assert sum(1 for record in repository.all() if not record.is_empty) == 2
