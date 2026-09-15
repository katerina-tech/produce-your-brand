"""The real-company directory.

The property this file protects is a type distinction, not a behaviour: a
Partner is a business that exists, and a Supplier is one somebody established
facts about. If those two ever become interchangeable, the product will start
telling buyers that a named Berlin company accepts customer-owned goods
because a map tag said "printer".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.enums import ProductionMethod
from app.domain.partner import Partner
from app.domain.supplier import Supplier
from app.repositories import db
from app.repositories.partner_repo import PartnerRepository

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = BACKEND_ROOT / "data" / "berlin_partners.json"


@pytest.fixture
def partners(tmp_path: Path) -> PartnerRepository:
    """A repository seeded from the shipped survey, as a deployment seeds itself."""
    connection = db.connect(tmp_path / "partners.db")
    db.initialize_schema(connection)
    repository = PartnerRepository(connection, DIRECTORY)
    repository.seed_if_empty()
    return repository


def test_the_shipped_directory_loads_and_validates(partners: PartnerRepository) -> None:
    assert partners.count() > 100, "the Berlin survey found 135; a collapse here is a broken file"
    assert partners.contactable_count() > 0


def test_a_partner_carries_no_capability_a_source_could_not_know() -> None:
    """The whole reason Partner and Supplier are different types.

    OpenStreetMap knows a business is tagged 'printer'. It does not know its
    materials, minimum order, lead time, or whether it will touch goods a
    customer already owns - and those are exactly the fields the scorer reads.
    """
    scored_only = {
        "supported_materials",
        "min_order_quantity",
        "max_order_quantity",
        "typical_lead_time_days",
        "accepts_customer_owned_products",
        "supported_methods",
        "product_categories",
    }

    assert scored_only <= set(Supplier.model_fields), "the scorer's fields, for reference"
    assert scored_only.isdisjoint(set(Partner.model_fields)), (
        "a Partner must not carry a field the scorer reads, or it will eventually "
        "be scored - and the product will make claims nobody asked the company"
    )


def test_what_a_tag_implies_is_named_as_an_implication(partners: PartnerRepository) -> None:
    """``implied_method``, never ``supported_methods``. The field name is the
    guard: nobody copies it into a Supplier by accident."""
    with_method = [p for p in partners.all() if p.implied_method is not None]

    assert with_method, "the survey maps every category to one method"
    assert "implied_method" in Partner.model_fields
    assert "supported_methods" not in Partner.model_fields


def test_every_seeded_partner_starts_unverified(partners: PartnerRepository) -> None:
    """Nothing collected automatically has been confirmed by anybody. Verifying
    is a person's act, which is why it is now a column somebody can set."""
    assert all(partner.verified is False for partner in partners.all())


def test_the_attribution_travels_with_the_data(partners: PartnerRepository) -> None:
    """OpenStreetMap is ODbL-licensed. A derived database that dropped the
    attribution would be a licence breach, not an oversight."""
    directory = partners.directory()

    assert "OpenStreetMap" in directory.attribution
    assert "ODbL" in directory.attribution or "Open Database" in directory.attribution


def test_categories_the_survey_missed_are_carried_not_hidden(
    partners: PartnerRepository,
) -> None:
    """A silent zero and a real zero mean opposite things: "Berlin has no sign
    makers" is a finding, "Overpass rate-limited us" is a gap."""
    raw = json.loads(DIRECTORY.read_text(encoding="utf-8"))

    assert partners.directory().incomplete_categories == tuple(raw["incomplete_categories"])


# --------------------------------------------------------------------- search


def test_searching_looks_at_the_address_too(partners: PartnerRepository) -> None:
    """ "Kreuzberg" is how somebody looks for a printer near them, and it lives
    in the address as often as in the name."""
    by_district = partners.search(query="Berlin")

    assert by_district, "every record is in Berlin, by address or by city"


def test_searching_ignores_case_and_surrounding_space(partners: PartnerRepository) -> None:
    assert partners.search(query="  COPY  ") == partners.search(query="copy")


def test_filtering_to_the_contactable_is_the_question_actually_asked(
    partners: PartnerRepository,
) -> None:
    """Which of these can I write to today."""
    results = partners.search(with_email=True)

    assert results
    assert all(partner.email for partner in results)
    assert len(results) < partners.count(), "not every business publishes one"


def test_filtering_by_implied_method(partners: PartnerRepository) -> None:
    results = partners.search(method=ProductionMethod.DIGITAL_PRINTING)

    assert results
    assert all(partner.implied_method is ProductionMethod.DIGITAL_PRINTING for partner in results)


def test_results_come_back_in_a_stable_order(partners: PartnerRepository) -> None:
    """A directory that reshuffles between page loads is a directory nobody can
    work through methodically."""
    assert [p.id for p in partners.search()] == [p.id for p in partners.search()]


def test_the_limit_is_honoured(partners: PartnerRepository) -> None:
    assert len(partners.search(limit=5)) == 5


# ------------------------------------------------------------------- distance


def test_distance_is_in_kilometres_rather_than_same_city() -> None:
    """Kreuzberg and Spandau are both "Berlin", and only one of them is
    somewhere you would drive a pallet of yoga mats."""
    brandenburg_gate = Partner(id="a", name="A", lat=52.5163, lon=13.3777)

    to_alexanderplatz = brandenburg_gate.distance_km(52.5219, 13.4132)

    assert to_alexanderplatz is not None
    assert 2.0 < to_alexanderplatz < 3.5, "the real distance is about 2.4 km"


def test_a_partner_with_no_position_has_no_distance() -> None:
    """None, not zero. Zero would sort it to the top as the nearest."""
    unplaced = Partner(id="b", name="B")

    assert unplaced.distance_km(52.5219, 13.4132) is None


def test_contactable_means_any_way_of_reaching_them() -> None:
    assert Partner(id="c", name="C", email="a@b.de").is_contactable is True
    assert Partner(id="d", name="D", phone="+49 30 123").is_contactable is True
    assert Partner(id="e", name="E", website="https://x.de").is_contactable is True
    assert Partner(id="f", name="F").is_contactable is False


def test_a_missing_seed_file_is_empty_rather_than_fatal(tmp_path: Path) -> None:
    """A deployment that has not run the survey has no directory, which is not
    the same as a broken one - and the rest of the product works."""
    connection = db.connect(tmp_path / "empty.db")
    db.initialize_schema(connection)
    repository = PartnerRepository(connection, tmp_path / "absent.json")

    assert repository.seed_if_empty() == 0
    assert repository.all() == ()
    assert repository.count() == 0


def test_seeding_runs_once_and_never_overwrites_afterwards(
    partners: PartnerRepository,
) -> None:
    """The reason the file stopped being storage. A deployment restarts for all
    sorts of reasons, and none of them may undo a confirmation somebody made by
    hand."""
    first = partners.count()
    confirmed = partners.all()[0]
    partners.mark_verified(confirmed.id)

    assert partners.seed_if_empty() == 0, "a full table is not re-seeded"
    assert partners.count() == first
    reloaded = partners.get(confirmed.id)
    assert reloaded is not None
    assert reloaded.verified is True, "the confirmation survived"


def test_confirming_a_company_that_does_not_exist(partners: PartnerRepository) -> None:
    assert partners.mark_verified("node/does-not-exist") is False


def test_the_list_reads_the_way_a_person_scans_it(partners: PartnerRepository) -> None:
    """SQL sorts uppercase before lowercase by default, which puts
    "Bundesdruckerei" above "bigcopy" - nonsense in a list somebody is working
    through by eye."""
    names = [partner.name for partner in partners.all()]

    assert names == sorted(names, key=str.casefold)
