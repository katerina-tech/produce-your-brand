"""Reading German public procurement into a board a print shop can use.

The export is a zip of twenty CSVs with facts at two levels, and every test
here is a shape in that data that cost a reading when it was missed. The
fixtures are written by hand rather than downloaded, so the suite never depends
on a federal server being awake or on what Germany happened to tender that week.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.enums import ProductionMethod
from app.domain.tender import CPV_FAMILIES, Tender, family_for
from app.main import create_app
from app.repositories import db
from app.repositories.tender_repo import TenderRepository
from app.services.tender_import import deadlines_from_eforms, read_export, summarise

TODAY = date(2026, 9, 16)


# ------------------------------------------------------------------- the CPV gate


def test_the_families_cover_what_these_companies_actually_do() -> None:
    assert {family.label for family in CPV_FAMILIES} >= {
        "Druckerzeugnisse",
        "Druckdienstleistungen",
        "Arbeitskleidung & Textilien",
    }


@pytest.mark.parametrize(
    ("code", "label"),
    [
        ("22000000", "Druckerzeugnisse"),
        ("22462000", "Druckerzeugnisse"),
        ("79800000", "Druckdienstleistungen"),
        ("79810000", "Druckdienstleistungen"),
        ("30199000", "Geschäftsdrucksachen"),
        ("39298700", "Pokale & Gravuren"),
        ("18100000", "Arbeitskleidung & Textilien"),
        ("79341000", "Werbung & Kampagnen"),
    ],
)
def test_codes_land_in_the_family_a_print_shop_would_expect(code: str, label: str) -> None:
    family = family_for(code)

    assert family is not None
    assert family.label == label


def test_the_longest_prefix_wins() -> None:
    """30199000 is printed stationery and 39298700 is trophies. A shorter
    neighbour claiming either would make the filter answer a different question
    than the one it names on screen."""
    stationery = family_for("30199000")
    trophies = family_for("39298700")

    assert stationery is not None and stationery.prefix == "30199"
    assert trophies is not None and trophies.prefix == "39298"


@pytest.mark.parametrize("code", ["45422100", "71000000", "09310000", "", "not-a-code"])
def test_everything_else_is_none(code: str) -> None:
    """23,000 notices a month become 200. Road resurfacing and electricity
    supply are not this product's business, and a board that listed them would
    be a board nobody trusted twice."""
    assert family_for(code) is None


def test_a_method_is_implied_only_where_it_obviously_is() -> None:
    """Printing implies printing. "Occupational clothing" is a purchase of
    garments, and whether it wants embroidery is a question for the tender
    document rather than for a lookup table."""
    printing = family_for("79800000")
    clothing = family_for("18100000")

    assert printing is not None and printing.implied_method is ProductionMethod.DIGITAL_PRINTING
    assert clothing is not None and clothing.implied_method is None


# --------------------------------------------------------------- the export


def _zip(tables: dict[str, list[dict[str, str]]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, rows in tables.items():
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(name, out.getvalue())
    return buffer.getvalue()


def _export(
    *,
    cpv: str = "79800000",
    lot: str = "LOT-0001",
    place_lot: str = "",
    sme_lot: str = "LOT-0001",
    sme: str = "true",
    title: str = "Druck von Broschüren",
) -> bytes:
    return _zip(
        {
            "notice.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "noticeType": "cn-standard",
                    "publicationDate": "2026-09-14T00:00:00+02:00",
                }
            ],
            "purpose.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "lotIdentifier": lot,
                    "title": title,
                    "description": "Broschüren, 4/4-farbig, geheftet.",
                    "estimatedValue": "48000",
                    "estimatedValueCurrency": "EUR",
                }
            ],
            "classification.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "lotIdentifier": lot,
                    "classificationType": "cpv",
                    "mainClassificationCode": cpv,
                    "additionalClassificationCodes": "",
                }
            ],
            "placeOfPerformance.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "lotIdentifier": place_lot,
                    "placePerformanceCity": "Berlin",
                    "placePerformanceCountrySubdivision": "DE300",
                }
            ],
            "additionalInformation.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "lotIdentifier": sme_lot,
                    "suitableForSMEs": sme,
                }
            ],
            "organisation.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "organisationName": "Bezirksamt Mitte von Berlin",
                    "organisationCity": "Berlin",
                    "organisationRole": "buyer",
                }
            ],
            "procedure.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "procedureType": "open",
                }
            ],
        }
    )


def test_a_printing_notice_is_read_whole() -> None:
    found = read_export(_export())

    assert len(found) == 1
    tender = found[0]
    assert tender.title == "Druck von Broschüren"
    assert tender.family_label == "Druckdienstleistungen"
    assert tender.buyer == "Bezirksamt Mitte von Berlin"
    assert tender.estimated_value == 48000
    assert tender.is_berlin is True


def test_a_notice_outside_the_families_never_arrives() -> None:
    assert read_export(_export(cpv="45422100")) == ()


def test_a_notice_level_fact_stands_in_for_a_lot_that_lacks_one() -> None:
    """placeOfPerformance often carries one row with an empty lot identifier and
    nothing per lot. Reading only the lot would have left every such tender
    with no location, and the Berlin filter would have hidden them all."""
    found = read_export(_export(place_lot=""))

    assert found[0].is_berlin is True


def test_the_sme_flag_is_found_on_any_lot_of_the_contract() -> None:
    """The bug this caught: the declaration is made per lot, the CPV match is
    often on the notice-level row, and reading only that one reported "not
    stated" for every tender in Germany - wrong about fifty-six a month."""
    found = read_export(_export(lot="", sme_lot="LOT-0001"))

    assert found[0].suitable_for_smes is True


def test_the_buyer_did_not_say_is_not_the_buyer_saying_no() -> None:
    found = read_export(_export(sme=""))

    assert found[0].suitable_for_smes is None


def test_the_winner_is_never_mistaken_for_the_buyer() -> None:
    """An award notice lists both. Attributing the contract to the company that
    won it would name the wrong organisation on every completed tender."""
    tables = _zip(
        {
            "notice.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "noticeType": "can-standard",
                    "publicationDate": "2026-09-14T00:00:00+02:00",
                }
            ],
            "purpose.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "lotIdentifier": "",
                    "title": "Druckerzeugnisse",
                    "description": "",
                    "estimatedValue": "",
                    "estimatedValueCurrency": "",
                }
            ],
            "classification.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "lotIdentifier": "",
                    "classificationType": "cpv",
                    "mainClassificationCode": "22000000",
                    "additionalClassificationCodes": "",
                }
            ],
            "organisation.csv": [
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "organisationName": "Gewinner Druck GmbH",
                    "organisationCity": "Hamburg",
                    "organisationRole": "winner",
                },
                {
                    "noticeIdentifier": "n1",
                    "noticeVersion": "01",
                    "organisationName": "Senatsverwaltung",
                    "organisationCity": "Berlin",
                    "organisationRole": "buyer",
                },
            ],
        }
    )

    found = read_export(tables)

    assert found[0].buyer == "Senatsverwaltung"


def test_a_notice_with_no_title_is_dropped() -> None:
    """A row nobody can act on is a row that fills a page rather than answering
    a question."""
    assert read_export(_export(title="")) == ()


def test_the_counts_a_person_watching_a_run_would_want() -> None:
    counts = summarise(read_export(_export()))

    assert counts == {"kept": 1, "berlin": 1, "sme_suitable": 1, "with_value": 1}


# -------------------------------------------------------------- the deadline


def _eforms(deadlines: list[tuple[str, str]]) -> bytes:
    blocks = "".join(
        f"<cac:TenderSubmissionDeadlinePeriod>"
        f"<cbc:EndDate>{day}</cbc:EndDate><cbc:EndTime>{clock}</cbc:EndTime>"
        f"</cac:TenderSubmissionDeadlinePeriod>"
        for day, clock in deadlines
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("n1-01.xml", f"<root>{blocks}</root>")
    return buffer.getvalue()


def test_the_deadline_comes_from_the_xml_because_it_is_nowhere_else() -> None:
    """Checked in all three formats the service offers: the CSV export does not
    carry a submission deadline and neither does the OCDS one. It exists only in
    eForms - and a tender board without deadlines is a list of things you cannot
    tell whether you have missed."""
    found = deadlines_from_eforms(_eforms([("2026-10-20+02:00", "08:00:00+02:00")]))

    assert found == {"n1": datetime.fromisoformat("2026-10-20T08:00:00+02:00")}


def test_the_earliest_deadline_wins_when_a_notice_states_several() -> None:
    """A bidder needs the date by which they must have acted. The latest lot's
    deadline would tell them they have longer than they do."""
    found = deadlines_from_eforms(
        _eforms([("2026-11-01+02:00", "12:00:00+02:00"), ("2026-10-20+02:00", "08:00:00+02:00")])
    )

    assert found["n1"].date() == date(2026, 10, 20)


def test_a_notice_with_no_deadline_gets_none_rather_than_a_guess() -> None:
    assert deadlines_from_eforms(_eforms([])) == {}


def test_the_deadline_reaches_the_tender() -> None:
    deadlines = deadlines_from_eforms(_eforms([("2026-10-20+02:00", "08:00:00+02:00")]))

    found = read_export(_export(), deadlines=deadlines)

    assert found[0].deadline is not None
    assert found[0].deadline.date() == date(2026, 10, 20)


# ------------------------------------------------------------- the repository


@pytest.fixture
def tenders(tmp_path: Path) -> TenderRepository:
    connection = db.connect(tmp_path / "tenders.db")
    db.initialize_schema(connection)
    return TenderRepository(connection)


def _tender(
    identifier: str = "t1",
    *,
    prefix: str = "798",
    label: str = "Druckdienstleistungen",
    region: str = "DE300",
    smes: bool | None = True,
    deadline: datetime | None = None,
    title: str = "Druck von Broschüren",
) -> Tender:
    return Tender(
        id=identifier,
        title=title,
        cpv="79800000",
        family_prefix=prefix,
        family_label=label,
        place_region=region,
        published_on=date(2026, 9, 14),
        deadline=deadline,
        suitable_for_smes=smes,
    )


def test_a_tender_round_trips(tenders: TenderRepository) -> None:
    tenders.save_all((_tender(),))

    stored = tenders.get("t1")

    assert stored is not None
    assert stored.title == "Druck von Broschüren"
    assert stored.suitable_for_smes is True


def test_the_three_valued_flag_survives_the_database(tenders: TenderRepository) -> None:
    """An INTEGER column that lost the difference would make "we don't know"
    indistinguishable from "not for you"."""
    tenders.save_all(
        (_tender("yes", smes=True), _tender("no", smes=False), _tender("q", smes=None))
    )

    assert tenders.get("yes").suitable_for_smes is True  # type: ignore[union-attr]
    assert tenders.get("no").suitable_for_smes is False  # type: ignore[union-attr]
    assert tenders.get("q").suitable_for_smes is None  # type: ignore[union-attr]


def test_a_corrected_notice_replaces_rather_than_duplicates(tenders: TenderRepository) -> None:
    """A notice is republished when it is corrected, and the corrected version
    is the one worth showing."""
    tenders.save_all((_tender(title="erste Fassung"),))
    tenders.save_all((_tender(title="korrigierte Fassung"),))

    assert tenders.count() == 1
    assert tenders.get("t1").title == "korrigierte Fassung"  # type: ignore[union-attr]


def test_closed_tenders_are_out_of_the_way_by_default(tenders: TenderRepository) -> None:
    """A board of contracts nobody can bid for is a board nobody can use."""
    past = datetime(2026, 9, 1, 12, 0)
    future = datetime(2026, 12, 1, 12, 0)
    tenders.save_all((_tender("old", deadline=past), _tender("new", deadline=future)))

    open_now = tenders.search(today=TODAY)

    assert [tender.id for tender in open_now] == ["new"]
    assert len(tenders.search(open_only=False, today=TODAY)) == 2


def test_a_tender_with_no_stated_deadline_counts_as_open(tenders: TenderRepository) -> None:
    """Hiding it because a field was empty would be this product deciding a
    contract is closed on no evidence."""
    tenders.save_all((_tender("undated", deadline=None),))

    assert len(tenders.search(today=TODAY)) == 1


def test_the_soonest_deadline_comes_first(tenders: TenderRepository) -> None:
    """And a notice that states one outranks a notice that does not: a date is
    more actionable than its absence."""
    tenders.save_all(
        (
            _tender("undated", deadline=None),
            _tender("later", deadline=datetime(2026, 12, 1, 12, 0)),
            _tender("sooner", deadline=datetime(2026, 10, 1, 12, 0)),
        )
    )

    assert [t.id for t in tenders.search(today=TODAY)] == ["sooner", "later", "undated"]


def test_filtering_to_berlin_by_nuts_rather_than_by_spelling(tenders: TenderRepository) -> None:
    """A buyer writes "Berlin-Mitte", "10115 Berlin" or nothing at all. DE3 is
    the same answer every time."""
    tenders.save_all((_tender("here", region="DE300"), _tender("away", region="DE712")))

    assert [t.id for t in tenders.search(berlin_only=True, today=TODAY)] == ["here"]
    assert tenders.berlin_count() == 1


def test_filtering_to_small_firms(tenders: TenderRepository) -> None:
    """Only where the buyer said yes. A tender where they said nothing is not
    hidden from the board, but it does not answer this question."""
    tenders.save_all(
        (_tender("sme", smes=True), _tender("big", smes=False), _tender("q", smes=None))
    )

    assert [t.id for t in tenders.search(smes_only=True, today=TODAY)] == ["sme"]


def test_searching_reads_the_buyer_too(tenders: TenderRepository) -> None:
    stored = _tender().model_copy(update={"buyer": "Bezirksamt Pankow"})
    tenders.save_all((stored,))

    assert tenders.search(query="pankow", today=TODAY)


def test_the_families_are_counted_from_the_data(tenders: TenderRepository) -> None:
    tenders.save_all(
        (_tender("a"), _tender("b"), _tender("c", prefix="22", label="Druckerzeugnisse"))
    )

    counts = {label: n for _, label, n in tenders.families()}

    assert counts["Druckdienstleistungen"] == 2


# ------------------------------------------------------------ the schedule


def test_an_empty_database_knows_it_has_nowhere_to_resume_from(
    tenders: TenderRepository,
) -> None:
    assert tenders.newest_published() is None


def test_the_newest_day_held_is_where_a_catch_up_starts(tenders: TenderRepository) -> None:
    """Read from the data rather than counted back from today. A run that was
    skipped, or a month with 31 days, cannot then leave a hole nobody sees."""
    older = _tender("a").model_copy(update={"published_on": date(2026, 9, 1)})
    newer = _tender("b").model_copy(update={"published_on": date(2026, 9, 14)})
    tenders.save_all((older, newer))

    assert tenders.newest_published() == date(2026, 9, 14)


# ---------------------------------------------------------------- the wire


def test_the_english_family_name_reaches_the_wire(tmp_path: Path) -> None:
    """CPV_FAMILIES has always carried an English name alongside the German
    label - Druckdienstleistungen / "Printing services" - and it never reached
    a response. An English-language product showing only the German jargon is
    not a translation problem to fix later; it is the one thing standing
    between a visitor and knowing what they are looking at."""
    settings = Settings(app_db_path=tmp_path / "wire.db", upload_dir=tmp_path / "uploads")
    with TestClient(create_app(settings)) as client:
        connection = db.connect(settings.app_db_path)
        TenderRepository(connection).save_all((_tender("t1"),))

        body = client.get("/api/tenders").json()

        assert body["tenders"][0]["family_english"] == "Printing services"
        assert body["families"][0]["english"] == "Printing services"
