"""The directory's HTTP surface.

Four endpoints, and each of the last three exists because something upstream of it is not
trustworthy on its own. The detail view exists so a person can read a company's
own words before vouching for them. The verification endpoint exists because no
amount of scraping produces somebody's judgement. The match endpoint exists
because a similarity score is a hint, and what a buyer needs is a sentence a
company actually wrote.

The app is built for real - routing, validation and the error envelope under
test are production code - and only the model and the embedder are scripted.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.config import Settings
from app.domain.capability import CapabilityClaim, SupplierCapabilities
from app.main import create_app
from app.repositories.capability_repo import CapabilityRepository
from app.services.capability_match import CapabilityIndex, MatchVerdict
from tests.fakes import HashingEmbedder, ScriptedProvider

READ_ON = date(2026, 9, 15)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The real application over a throwaway database."""
    monkeypatch.setenv("PYS_APP_DB_PATH", str(tmp_path / "api.db"))
    settings = Settings(
        app_db_path=tmp_path / "api.db",
        upload_dir=tmp_path / "uploads",
        session_secret="x" * 32,
        operator_emails="boss@example.de",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _as_operator(client: TestClient) -> None:
    """Confirming a company is no longer something anybody may do.

    It asks two questions now - who is asking, and whether they speak for this
    business - so a test that confirms one has to answer them. See
    tests/test_company_claim.py for the rule itself.
    """
    response = client.post(
        "/api/auth/register", json={"email": "boss@example.de", "password": "a-long-password"}
    )
    assert response.status_code in {200, 201}, response.text


def _seeded_partner(client: TestClient) -> dict[str, object]:
    """One company from the directory the deployment seeds at startup."""
    response = client.get("/api/partners?limit=1")
    assert response.status_code == 200
    partners = response.json()["partners"]
    assert partners, "the directory seeds itself at startup"
    return partners[0]  # type: ignore[no-any-return]


def _store(client: TestClient, partner_id: str, *claims: str, **flags: bool) -> None:
    repository: CapabilityRepository = client.app.state.capability_repository
    repository.save(
        SupplierCapabilities(
            partner_id=partner_id,
            partner_name="A company",
            source_urls=("https://example.de/leistungen",),
            claims=tuple(
                CapabilityClaim(text=claim, quote=f"Wir bieten {claim} an.") for claim in claims
            ),
            extracted_on=READ_ON,
        ),
        **flags,
    )


# ----------------------------------------------------------------- the detail


def test_an_id_with_a_slash_in_it_reaches_its_company(client: TestClient) -> None:
    """The bug this endpoint's shape exists for. OpenStreetMap ids look like
    "node/6532305050", and a plain path parameter stops at the slash - so every
    company in the directory answered 404 until the route took the rest of the
    path."""
    partner = _seeded_partner(client)
    assert "/" in str(partner["id"]), "the ids really do carry a slash"

    response = client.get(f"/api/partners/detail/{partner['id']}")

    assert response.status_code == 200
    assert response.json()["partner"]["name"] == partner["name"]


def test_a_reading_arrives_with_the_words_it_came_from(client: TestClient) -> None:
    """A claim without its quote is this product's summary of a named business.
    The person confirming needs the second to judge the first."""
    partner = _seeded_partner(client)
    _store(client, str(partner["id"]), "Siebdruck auf Textilien")

    body = client.get(f"/api/partners/detail/{partner['id']}").json()

    assert body["claims"] == [
        {
            "text": "Siebdruck auf Textilien",
            "quote": "Wir bieten Siebdruck auf Textilien an.",
            "kind": "other",
            "method": None,
        }
    ]
    assert body["extracted_on"] == "2026-09-15"
    assert body["source_urls"] == ["https://example.de/leistungen"]


def test_a_company_nobody_read_says_so_in_words(client: TestClient) -> None:
    """Not an empty list with no explanation: "we have not looked" and "they
    said nothing" are different answers, and the screen shows which."""
    partner = _seeded_partner(client)

    body = client.get(f"/api/partners/detail/{partner['id']}").json()

    assert body["claims"] == []
    assert body["extracted_on"] is None
    assert "not been read" in body["reading_note"]


def test_a_reading_that_failed_says_it_can_be_retried(client: TestClient) -> None:
    """An exhausted balance is not a fact about a Berlin print shop, and the
    screen must not leave somebody thinking it was."""
    partner = _seeded_partner(client)
    _store(client, str(partner["id"]), model_failed=True)

    note = client.get(f"/api/partners/detail/{partner['id']}").json()["reading_note"]

    assert "did not complete" in note


def test_deleted_claims_are_counted_on_screen_rather_than_hidden(client: TestClient) -> None:
    """A reading where the verifier threw away half of what the model proposed
    is a reading worth looking at twice."""
    partner = _seeded_partner(client)
    repository: CapabilityRepository = client.app.state.capability_repository
    repository.save(
        SupplierCapabilities(
            partner_id=str(partner["id"]),
            partner_name="A company",
            source_urls=("https://example.de/",),
            claims=(CapabilityClaim(text="Siebdruck", quote="Siebdruck"),),
            extracted_on=READ_ON,
            dropped_count=4,
        )
    )

    assert client.get(f"/api/partners/detail/{partner['id']}").json()["dropped_count"] == 4


def test_an_unknown_company_is_a_404(client: TestClient) -> None:
    assert client.get("/api/partners/detail/node/does-not-exist").status_code == 404


# ----------------------------------------------------------- the confirmation


def test_confirming_sticks(client: TestClient) -> None:
    partner = _seeded_partner(client)
    _as_operator(client)

    posted = client.post(f"/api/partners/verification/{partner['id']}", json={"verified": True})

    assert posted.status_code == 200
    assert posted.json()["verified"] is True
    assert client.get(f"/api/partners/detail/{partner['id']}").json()["partner"]["verified"] is True


def test_a_confirmation_can_be_withdrawn(client: TestClient) -> None:
    """Reversible on purpose. A confirmation made in error that cannot be taken
    back is a confirmation people stop making."""
    partner = _seeded_partner(client)
    _as_operator(client)
    client.post(f"/api/partners/verification/{partner['id']}", json={"verified": True})

    withdrawn = client.post(f"/api/partners/verification/{partner['id']}", json={"verified": False})

    assert withdrawn.json()["verified"] is False


def test_confirming_shows_up_on_the_reading(client: TestClient) -> None:
    """``confirmed_by_human`` lives on the company, not on the reading, so a
    re-read cannot silently drop it."""
    partner = _seeded_partner(client)
    _as_operator(client)
    _store(client, str(partner["id"]), "Siebdruck")
    client.post(f"/api/partners/verification/{partner['id']}", json={"verified": True})

    assert client.get(f"/api/partners/detail/{partner['id']}").json()["partner"]["verified"] is True


def test_confirming_a_company_that_does_not_exist(client: TestClient) -> None:
    _as_operator(client)
    response = client.post(
        "/api/partners/verification/node/does-not-exist", json={"verified": True}
    )

    assert response.status_code == 404


def test_a_confirmation_drops_the_search_index(client: TestClient) -> None:
    """The index is a cache over what has been read. Dropping it after a change
    is cheaper and more honest than patching it in place."""
    partner = _seeded_partner(client)
    _as_operator(client)
    client.app.state.capability_index = CapabilityIndex(HashingEmbedder())

    client.post(f"/api/partners/verification/{partner['id']}", json={"verified": True})

    assert client.app.state.capability_index is None


# ------------------------------------------------------------------ the match


def test_matching_before_anything_was_read_explains_itself(client: TestClient) -> None:
    """Not an empty list. An empty list reads as "nobody in Berlin can do this",
    which would be a claim about 135 companies rather than about this product."""
    body = client.post("/api/partners/match", json={"requirement": "gold logo on mats"}).json()

    assert body["matches"] == []
    assert body["companies_indexed"] == 0
    assert "extract_capabilities" in body["note"]


def test_a_supported_match_carries_the_company_s_own_sentence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end of the reviewer's pipeline, through HTTP: retrieval finds it, a
    model says yes, and the answer a buyer reads is the company's words."""
    partner = _seeded_partner(client)
    _store(client, str(partner["id"]), "Siebdruck auf Textilien und Baumwolle")

    monkeypatch.setattr(routes, "get_embedding_provider", lambda _settings: HashingEmbedder())
    monkeypatch.setattr(
        routes,
        "get_provider",
        lambda _settings: ScriptedProvider(
            {
                MatchVerdict: MatchVerdict(
                    can_do_it=True,
                    reason="They print on textiles.",
                    quote="Siebdruck auf Textilien und Baumwolle",
                )
            }
        ),
    )

    body = client.post(
        "/api/partners/match", json={"requirement": "Siebdruck auf Baumwolle"}
    ).json()

    assert body["companies_indexed"] == 1
    assert len(body["matches"]) == 1
    match = body["matches"][0]
    assert match["supported"] is True
    assert match["quote_verified"] is True
    assert match["quote"] == "Siebdruck auf Textilien und Baumwolle"


def test_a_quote_the_company_never_wrote_demotes_the_verdict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule that makes this defensible rather than plausible. A model that
    answers yes but cannot point at where the company said so does not produce a
    match - and the company stays on the list, because all that was established
    is that the model could not find the sentence."""
    partner = _seeded_partner(client)
    _store(client, str(partner["id"]), "Siebdruck auf Textilien")

    monkeypatch.setattr(routes, "get_embedding_provider", lambda _settings: HashingEmbedder())
    monkeypatch.setattr(
        routes,
        "get_provider",
        lambda _settings: ScriptedProvider(
            {
                MatchVerdict: MatchVerdict(
                    can_do_it=True,
                    reason="They say they do everything.",
                    quote="Wir bedrucken auch Yogamatten aus PVC",
                )
            }
        ),
    )

    match = client.post("/api/partners/match", json={"requirement": "PVC mats"}).json()["matches"][
        0
    ]

    assert match["quote_verified"] is False
    assert match["supported"] is False


def test_a_company_that_was_read_and_said_nothing_is_not_searched(client: TestClient) -> None:
    """Embedding an empty reading would put a company in front of a buyer with
    no reason they could read."""
    partner = _seeded_partner(client)
    _store(client, str(partner["id"]))

    body = client.post("/api/partners/match", json={"requirement": "anything at all"}).json()

    assert body["companies_indexed"] == 0
    assert body["matches"] == []


def test_a_requirement_too_short_to_search_is_refused(client: TestClient) -> None:
    """422 rather than an empty result: two characters is a slip, and answering
    it with "nobody can do this" would be worse than saying so."""
    assert client.post("/api/partners/match", json={"requirement": "a"}).status_code == 422


# -------------------------------------------------------------- the listing


def test_the_listing_carries_where_each_company_is(client: TestClient) -> None:
    """The district is what a person recognises - "a printer in Wedding" - and
    it is derived from coordinates, so every company has one."""
    body = client.get("/api/partners?limit=5").json()

    assert body["partners"]
    assert all(partner["district"] for partner in body["partners"])


def test_the_boroughs_come_back_with_their_counts(client: TestClient) -> None:
    """So a filter can be drawn from the data rather than from a constant that
    can drift out of step with it."""
    body = client.get("/api/partners?limit=1").json()

    assert body["boroughs"]
    assert all(item["count"] > 0 for item in body["boroughs"])
    assert sum(item["count"] for item in body["boroughs"]) <= body["total"]


def test_filtering_to_one_borough(client: TestClient) -> None:
    body = client.get("/api/partners?limit=1").json()
    name = body["boroughs"][0]["name"]

    filtered = client.get(f"/api/partners?borough={name}").json()

    assert filtered["shown"] == body["boroughs"][0]["count"]
    assert all(partner["borough"] == name for partner in filtered["partners"])


def test_the_borough_list_does_not_shrink_as_you_filter(client: TestClient) -> None:
    """A filter that removes its own options is one you cannot get back out of
    without knowing to clear it by hand."""
    unfiltered = client.get("/api/partners?limit=1").json()["boroughs"]
    name = unfiltered[0]["name"]

    filtered = client.get(f"/api/partners?borough={name}&limit=1").json()["boroughs"]

    assert filtered == unfiltered


def test_the_kinds_of_business_come_back_with_their_counts(client: TestClient) -> None:
    """So the filter is drawn from the data rather than from a constant list
    that can drift out of step with it."""
    body = client.get("/api/partners?limit=1").json()

    assert body["categories"]
    assert all(item["count"] > 0 for item in body["categories"])
    assert all("=" in item["tag"] for item in body["categories"])


def test_filtering_to_one_kind_of_business(client: TestClient) -> None:
    body = client.get("/api/partners?limit=1").json()
    kind = body["categories"][0]

    filtered = client.get(f"/api/partners?category={kind['tag']}").json()

    assert filtered["shown"] == kind["count"]
    assert all(partner["category"] == kind["tag"] for partner in filtered["partners"])


def test_the_two_filters_narrow_together(client: TestClient) -> None:
    """ "Druckereien in Pankow" - the question somebody actually arrives with."""
    body = client.get("/api/partners?limit=1").json()
    tag = body["categories"][0]["tag"]
    borough = body["boroughs"][0]["name"]

    both = client.get(f"/api/partners?category={tag}&borough={borough}").json()

    assert all(
        partner["category"] == tag and partner["borough"] == borough for partner in both["partners"]
    )
