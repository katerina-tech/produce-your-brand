"""Publishing a buyer's request, and everything that must not be published with it.

Most of this file is about omissions. A listing is the one place in this
product where a private brief becomes public text, and the failure mode is not
a crash - it is a page that quietly carries somebody's street address, their
budget, or the URL of their private project. Each test below is one of those,
made impossible rather than unlikely.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.demand import DEFAULT_DAYS_LIVE, draft_from, new_request_id
from app.domain.enums import ProductionMethod
from app.domain.project import Project
from app.domain.requirement import ProductionRequirement
from app.main import create_app
from app.repositories import db
from app.repositories.database import Database
from app.repositories.demand_repo import DemandRepository

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
TODAY = NOW.date()


def _project(
    *,
    confirmed: bool = True,
    product: str | None = "Yoga mats",
    location: str | None = "Wrangelstraße 12, 10997 Berlin",
    budget: float | None = 2500.0,
    deadline: date | None = date(2026, 11, 1),
    owns: bool | None = True,
    method: ProductionMethod | None = ProductionMethod.SCREEN_PRINTING,
) -> Project:
    return Project(
        id="p1",
        thread_id="t1",
        raw_request="100 yoga mats with a gold logo",
        created_at=NOW,
        updated_at=NOW,
        brief_confirmed=confirmed,
        confirmed_method=method,
        requirement=ProductionRequirement(
            product=product,
            material="PVC",
            quantity=100,
            customer_owns_product=owns,
            deadline=deadline,
            budget_eur=budget,
            location=location,
            customization_description="Gold logo, 12 cm wide",
        ),
    )


# --------------------------------------------------- what never gets published


def test_the_street_and_the_postcode_are_dropped() -> None:
    """``location`` in a requirement is "as stated" and is routinely a doorstep.
    A listing carries the city and nothing finer."""
    draft = draft_from(_project(), now=NOW)

    assert draft is not None
    assert draft.city == "Berlin"
    assert "Wrangel" not in draft.city
    assert "10997" not in draft.city


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Wrangelstraße 12, 10997 Berlin", "Berlin"),
        ("10997 Berlin", "Berlin"),
        ("Berlin", "Berlin"),
        ("Hauptstr. 5, 14482 Potsdam", "Potsdam"),
        ("", ""),
        (None, ""),
    ],
)
def test_the_city_out_of_however_somebody_typed_it(written: str | None, expected: str) -> None:
    draft = draft_from(_project(location=written), now=NOW)

    assert draft is not None
    assert draft.city == expected


def test_the_budget_is_hidden_unless_the_buyer_says_otherwise() -> None:
    """The one figure that weakens their position in every negotiation that
    follows. Off by default, and a thing they tick rather than a thing they have
    to remember to clear."""
    default = draft_from(_project(), now=NOW)
    chosen = draft_from(_project(), show_budget=True, now=NOW)

    assert default is not None and default.budget_eur is None
    assert chosen is not None and chosen.budget_eur == 2500.0


def test_the_public_id_reveals_nothing_about_the_project() -> None:
    """A project id in a public URL is the address of a private page. Random
    rather than derived, because anything derived can be worked backwards."""
    draft = draft_from(_project(), now=NOW)

    assert draft is not None
    assert "p1" not in draft.id
    assert draft.id.startswith("req_")
    assert new_request_id() != new_request_id()


def test_the_brief_s_own_free_text_does_not_travel() -> None:
    """``customization_description`` was written for this product, not for
    strangers. The note is the buyer's words for the public, and it is empty
    until they write it."""
    draft = draft_from(_project(), now=NOW)

    assert draft is not None
    assert draft.note == ""
    assert "Gold logo" not in draft.note


def test_the_wire_shape_carries_no_project_id(tmp_path: Path) -> None:
    """The domain object needs it so the buyer's own screens can find their
    listing. The response must not have it."""
    from app.api.dto import PublicRequestResponse

    assert "project_id" not in PublicRequestResponse.model_fields


def test_no_contact_field_exists_to_leak(tmp_path: Path) -> None:
    """Not "is left empty" - absent from the schema, so a later careless copy
    cannot fill it in."""
    from app.api.dto import PublicRequestResponse

    forbidden = {"email", "name", "buyer", "phone", "address", "owner_id", "location"}

    assert forbidden.isdisjoint(set(PublicRequestResponse.model_fields))


# ------------------------------------------------------- when it may be published


def test_an_unconfirmed_brief_cannot_be_published() -> None:
    """A listing is a claim the buyer makes to strangers, and a model's first
    reading of their sentence is not yet theirs."""
    assert draft_from(_project(confirmed=False), now=NOW) is None


def test_a_brief_with_no_product_cannot_be_published() -> None:
    """A row nobody can act on is a row that fills a board rather than
    answering a question."""
    assert draft_from(_project(product=None), now=NOW) is None


# ------------------------------------------------------------------- expiry


def test_the_deadline_is_the_end_date_when_there_is_one() -> None:
    draft = draft_from(_project(), now=NOW)

    assert draft is not None
    assert draft.expires_on == date(2026, 11, 1)


def test_an_undated_request_still_ends() -> None:
    """Unlike a tender, where an undated notice is still a real notice. A board
    of forgotten requests is worse than a small one: a company that answers a
    dead request once does not come back."""
    draft = draft_from(_project(deadline=None), now=NOW)

    assert draft is not None
    assert draft.expires_on == TODAY + timedelta(days=DEFAULT_DAYS_LIVE)
    assert draft.is_open_on(TODAY) is True
    assert draft.is_open_on(draft.expires_on + timedelta(days=1)) is False


# --------------------------------------------------------------- the repository


@pytest.fixture
def connection(tmp_path: Path) -> Database:
    database = db.connect(tmp_path / "demand.db")
    db.initialize_schema(database)
    with database:
        for identifier in ("p1", "p2"):
            database.execute(
                "INSERT INTO projects (id, thread_id, stage, raw_request, brief_confirmed,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (identifier, f"t-{identifier}", "completed", "x", 1, "2026-09-16", "2026-09-16"),
            )
    return database


@pytest.fixture
def demand(connection: Database) -> DemandRepository:
    return DemandRepository(connection)


def test_a_listing_round_trips(demand: DemandRepository) -> None:
    draft = draft_from(_project(), note="Logo als Vektordatei.", now=NOW)
    assert draft is not None

    live = demand.publish(draft)

    stored = demand.get(live.id)
    assert stored is not None
    assert stored.product == "Yoga mats"
    assert stored.note == "Logo als Vektordatei."
    assert stored.customer_owns_product is True


def test_publishing_twice_replaces_rather_than_duplicates(demand: DemandRepository) -> None:
    """One row per project, enforced by the database rather than remembered."""
    demand.publish(draft_from(_project(), note="erst", now=NOW))  # type: ignore[arg-type]
    demand.publish(draft_from(_project(), note="dann", now=NOW))  # type: ignore[arg-type]

    assert demand.count_open(TODAY) == 1
    listing = demand.for_project("p1")
    assert listing is not None and listing.note == "dann"


def test_the_public_link_survives_an_edit(demand: DemandRepository) -> None:
    """Somebody may already have shared it. Editing a note is not a reason for
    their link to break."""
    first = demand.publish(draft_from(_project(), note="erst", now=NOW))  # type: ignore[arg-type]

    second = demand.publish(draft_from(_project(), note="dann", now=NOW))  # type: ignore[arg-type]

    assert second.id == first.id


def test_taking_it_down_deletes_rather_than_hides(
    demand: DemandRepository, connection: Database
) -> None:
    """Everything in that table is text somebody agreed to publish, and
    "present but hidden" is a state a future reader will get wrong."""
    live = demand.publish(draft_from(_project(), now=NOW))  # type: ignore[arg-type]

    assert demand.withdraw("p1") is True
    assert demand.get(live.id) is None
    rows = connection.execute("SELECT COUNT(*) AS n FROM public_requests").fetchone()
    assert dict(rows)["n"] == 0


def test_taking_down_what_was_never_up(demand: DemandRepository) -> None:
    assert demand.withdraw("p2") is False


def test_an_expired_listing_is_never_searched(demand: DemandRepository) -> None:
    expired = draft_from(_project(deadline=date(2026, 9, 1)), now=NOW)
    assert expired is not None
    demand.publish(expired)

    assert demand.search(today=TODAY) == ()
    assert demand.count_open(TODAY) == 0


def test_expired_listings_are_deleted_not_merely_hidden(demand: DemandRepository) -> None:
    """Not about correctness - the search already hides them. It is about not
    keeping a buyer's published text one day longer than they agreed to."""
    demand.publish(draft_from(_project(deadline=date(2026, 9, 1)), now=NOW))  # type: ignore[arg-type]

    assert demand.purge_expired(TODAY) == 1
    assert demand.for_project("p1") is None


def test_the_soonest_deadline_comes_first(demand: DemandRepository) -> None:
    sooner = draft_from(_project(deadline=date(2026, 10, 1)), now=NOW)
    later = draft_from(_project(deadline=date(2026, 12, 1)), now=NOW)
    assert sooner is not None and later is not None
    demand.publish(sooner)
    demand.publish(later.model_copy(update={"project_id": "p2", "id": new_request_id()}))

    order = [listing.deadline for listing in demand.search(today=TODAY)]

    assert order == [date(2026, 10, 1), date(2026, 12, 1)]


def test_filtering_to_goods_the_buyer_already_owns(demand: DemandRepository) -> None:
    """Many shops will not touch customer-owned stock. The ones that will need
    to find these."""
    owned = draft_from(_project(owns=True), now=NOW)
    fresh = draft_from(_project(owns=None), now=NOW)
    assert owned is not None and fresh is not None
    demand.publish(owned)
    demand.publish(fresh.model_copy(update={"project_id": "p2", "id": new_request_id()}))

    found = demand.search(customer_owned=True, today=TODAY)

    assert len(found) == 1
    assert found[0].customer_owns_product is True


def test_searching_reads_the_note_too(demand: DemandRepository) -> None:
    demand.publish(draft_from(_project(), note="Siebdruck bevorzugt", now=NOW))  # type: ignore[arg-type]

    assert demand.search(query="siebdruck", today=TODAY)


# ------------------------------------------------------------------- the API


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(app_db_path=tmp_path / "api.db", upload_dir=tmp_path / "uploads")
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_the_board_starts_empty_and_says_so(client: TestClient) -> None:
    body = client.get("/api/requests").json()

    assert body == {"requests": [], "total": 0, "shown": 0}


def test_a_withdrawn_link_answers_the_same_as_one_that_never_existed(
    client: TestClient,
) -> None:
    """404 either way. A link that has been taken down should not confirm that
    it used to be there."""
    assert client.get("/api/requests/detail/req_never").status_code == 404


def test_publishing_needs_a_project_that_exists(client: TestClient) -> None:
    response = client.post("/api/projects/nope/publication", json={"show_budget": False})

    assert response.status_code == 404


def test_the_publication_view_of_an_unknown_project(client: TestClient) -> None:
    assert client.get("/api/projects/nope/publication").status_code == 404
