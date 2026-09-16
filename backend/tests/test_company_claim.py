"""Proving that an account speaks for a named Berlin business.

This file exists because of a hole that shipped: ``POST /partners/verification``
asked for no account at all, so anybody on the internet could mark any of 136
real companies as confirmed. A badge saying a business stands behind something
is worth exactly as much as the check behind it, and there was none.

Most of what follows is therefore about refusal - who may not do this, and why
each "may not" is a different answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.company import CLAIM_VALID_HOURS, CompanyClaim, new_token, proof_url
from app.domain.partner import Partner
from app.main import create_app
from app.repositories.claim_repo import ClaimRepository
from app.services import company_claim
from app.services.company_claim import ClaimError

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
SITE = "https://druckerei.example"


def _partner(website: str | None = SITE) -> Partner:
    return Partner(id="node/1", name="Beispiel Druckerei", website=website)


def _claim(token: str = "tok", *, user: str = "u1", when: datetime = NOW) -> CompanyClaim:
    return CompanyClaim(partner_id="node/1", user_id=user, token=token, created_at=when)


def _resolves(_host: str) -> set[str]:
    """A public address, so the guard lets the fetch through. The guard itself
    has its own tests; these are about the proof."""
    return {"93.184.216.34"}


def _client(body: str, status: int = 200) -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------- the proof URL


def test_the_url_is_derived_from_the_directory_not_from_the_claimer() -> None:
    """The website came from the company's own OpenStreetMap entry, recorded
    before anybody asked to claim anything. A claimer who could name the URL
    would be proving they control *a* website, which proves nothing."""
    assert proof_url("https://druckerei.de") == (
        "https://druckerei.de/.well-known/produce-your-brand.txt"
    )
    assert proof_url("http://www.aw-digital.de/kontakt") == (
        "http://www.aw-digital.de/.well-known/produce-your-brand.txt"
    )


@pytest.mark.parametrize("website", ["", "ftp://files.example", "javascript:alert(1)", "not a url"])
def test_an_address_this_cannot_fetch_is_not_a_proof(website: str) -> None:
    assert proof_url(website) is None


def test_a_company_with_no_website_cannot_claim_itself() -> None:
    """Forty-six of the 136 publish neither a website nor an email. Telling
    somebody that up front is the difference between a dead end and a mystery."""
    with pytest.raises(ClaimError, match="no website"):
        company_claim.start(_partner(website=None), "u1")


def test_tokens_are_not_guessable_and_not_reused() -> None:
    assert new_token() != new_token()
    assert len(new_token()) > 24


# ------------------------------------------------------------------ expiry


def test_an_unverified_claim_expires() -> None:
    """Otherwise starting a claim and never finishing it would hold a real
    business's listing for ever - denial of service dressed as a feature."""
    claim = _claim()

    assert claim.is_live_at(NOW) is True
    assert claim.is_live_at(NOW + timedelta(hours=CLAIM_VALID_HOURS + 1)) is False


def test_a_verified_claim_does_not() -> None:
    """The account keeps the company until somebody takes it away deliberately."""
    claim = _claim().model_copy(update={"verified_at": NOW})

    assert claim.is_live_at(NOW + timedelta(days=365)) is True


# ------------------------------------------------------------- the checking


def test_the_right_token_on_the_right_site_is_accepted() -> None:
    company_claim.check(
        _partner(), _claim("secret"), resolve=_resolves, client=_client("secret\n"), now=NOW
    )


def test_a_wrong_token_is_refused_without_saying_what_was_there() -> None:
    """A claimer who controls the site knows what they put there. One who does
    not should learn nothing about it from us."""
    with pytest.raises(ClaimError) as raised:
        company_claim.check(
            _partner(),
            _claim("secret"),
            resolve=_resolves,
            client=_client("somethingelse"),
            now=NOW,
        )

    assert "does not contain this token" in str(raised.value)
    assert "somethingelse" not in str(raised.value)


def test_a_missing_file_says_so() -> None:
    with pytest.raises(ClaimError, match="answered 404"):
        company_claim.check(
            _partner(), _claim("secret"), resolve=_resolves, client=_client("", 404), now=NOW
        )


def test_an_expired_claim_is_not_checked_at_all() -> None:
    with pytest.raises(ClaimError, match="expired"):
        company_claim.check(
            _partner(),
            _claim("secret"),
            resolve=_resolves,
            client=_client("secret"),
            now=NOW + timedelta(hours=CLAIM_VALID_HOURS + 1),
        )


def test_a_website_pointing_into_private_space_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same guard the capability survey uses. A claim naming an internal
    host must not turn this into a probe of the network the server sits in."""
    monkeypatch.setattr(
        company_claim,
        "address_refusal",
        lambda _url, _resolve: "it resolves into private address space",
    )

    with pytest.raises(ClaimError, match="private address space"):
        company_claim.check(
            _partner(), _claim("secret"), resolve=_resolves, client=_client("secret"), now=NOW
        )


# --------------------------------------------------------------- the API


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        app_db_path=tmp_path / "claims.db",
        upload_dir=tmp_path / "uploads",
        session_secret="x" * 32,
        operator_emails="boss@example.de",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _sign_up(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/auth/register", json={"email": email, "password": "a-long-enough-password"}
    )
    assert response.status_code in {200, 201}, response.text


def _a_partner_with_a_website(client: TestClient) -> str:
    body = client.get("/api/partners?limit=200").json()
    return next(p["id"] for p in body["partners"] if p["website"])


def test_nobody_signed_out_may_confirm_a_named_business(client: TestClient) -> None:
    """The hole this file exists for. It answered 200 to anybody."""
    partner_id = _a_partner_with_a_website(client)

    response = client.post(f"/api/partners/verification/{partner_id}", json={"verified": True})

    assert response.status_code == 401


def test_signing_in_is_not_enough(client: TestClient) -> None:
    """An account is not a claim. Anybody can make an account."""
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "stranger@example.de")

    response = client.post(f"/api/partners/verification/{partner_id}", json={"verified": True})

    assert response.status_code == 403
    assert "own account" in response.json()["error"]["message"]


def test_starting_a_claim_is_not_enough_either(client: TestClient) -> None:
    """Between starting and proving, nothing has been established."""
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "claimer@example.de")
    assert client.post(f"/api/partners/claim/{partner_id}").status_code == 200

    response = client.post(f"/api/partners/verification/{partner_id}", json={"verified": True})

    assert response.status_code == 403


def test_a_claim_hands_back_a_token_and_the_address_it_must_appear_at(
    client: TestClient,
) -> None:
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "claimer@example.de")

    body = client.post(f"/api/partners/claim/{partner_id}").json()

    assert body["state"] == "pending"
    assert body["token"]
    assert body["proof_url"].endswith("/.well-known/produce-your-brand.txt")


def test_the_token_is_never_shown_to_another_account(client: TestClient) -> None:
    """A token anybody could read is a proof anybody could satisfy."""
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "first@example.de")
    client.post(f"/api/partners/claim/{partner_id}")
    client.post("/api/auth/logout")
    _sign_up(client, "second@example.de")

    body = client.get(f"/api/partners/claim/{partner_id}").json()

    assert body["token"] is None
    assert body["state"] == "pending"
    assert body["claimable"] is False


def test_a_second_account_cannot_take_a_live_claim(client: TestClient) -> None:
    """An unverified claim expires by itself, so waiting is the remedy. Letting
    a second account overwrite the first would make the queue a race."""
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "first@example.de")
    client.post(f"/api/partners/claim/{partner_id}")
    client.post("/api/auth/logout")
    _sign_up(client, "second@example.de")

    assert client.post(f"/api/partners/claim/{partner_id}").status_code == 409


def test_verifying_a_claim_that_is_not_yours(client: TestClient) -> None:
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "first@example.de")
    client.post(f"/api/partners/claim/{partner_id}")
    client.post("/api/auth/logout")
    _sign_up(client, "second@example.de")

    assert client.post(f"/api/partners/proof/{partner_id}").status_code == 404


def test_a_proved_company_may_confirm_itself_and_the_badge_says_who(
    client: TestClient,
) -> None:
    """The whole point: the strongest signal this directory can carry is the
    company itself, and the badge has to be able to say so."""
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "owner@example.de")
    client.post(f"/api/partners/claim/{partner_id}")
    # Accept the proof directly: fetching a real Berlin print shop's website
    # from a test suite is neither reliable nor polite.
    claims: ClaimRepository = client.app.state.claim_repository
    claims.mark_verified(partner_id)

    response = client.post(f"/api/partners/verification/{partner_id}", json={"verified": True})

    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert response.json()["verified_by"] == "company"


def test_proving_one_company_does_not_speak_for_another(client: TestClient) -> None:
    body = client.get("/api/partners?limit=200").json()
    ids = [p["id"] for p in body["partners"] if p["website"]]
    mine, other = ids[0], ids[1]
    _sign_up(client, "owner@example.de")
    client.post(f"/api/partners/claim/{mine}")
    claims: ClaimRepository = client.app.state.claim_repository
    claims.mark_verified(mine)

    response = client.post(f"/api/partners/verification/{other}", json={"verified": True})

    assert response.status_code == 403


def test_an_operator_may_confirm_by_hand_and_the_badge_says_that_instead(
    client: TestClient,
) -> None:
    """The only route for the forty-six companies that publish neither a
    website nor an email."""
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "boss@example.de")

    response = client.post(f"/api/partners/verification/{partner_id}", json={"verified": True})

    assert response.status_code == 200
    assert response.json()["verified_by"] == "operator"


def test_an_empty_operator_list_grants_nobody_anything(tmp_path: Path) -> None:
    """A misconfigured deployment should grant no power rather than all of it."""
    settings = Settings(
        app_db_path=tmp_path / "none.db",
        upload_dir=tmp_path / "uploads",
        session_secret="x" * 32,
    )
    with TestClient(create_app(settings)) as bare:
        partner_id = _a_partner_with_a_website(bare)
        _sign_up(bare, "boss@example.de")

        response = bare.post(f"/api/partners/verification/{partner_id}", json={"verified": True})

        assert response.status_code == 403


def test_the_proof_route_is_not_behind_the_greedy_segment(client: TestClient) -> None:
    """The trap this codebase documents and then walked into anyway.

    An OpenStreetMap id ends in a greedy path segment, and a greedy segment
    swallows whatever follows it. Spelt "claim/{id}/verify", the request
    matched the *start* route with an id of "node/123/verify" and answered 404
    to every attempt to prove anything - which looked exactly like a claim that
    had never been made.
    """
    partner_id = _a_partner_with_a_website(client)
    _sign_up(client, "owner@example.de")
    client.post(f"/api/partners/claim/{partner_id}")

    # Reaches the proof route, finds no file, and says so - rather than 404.
    response = client.post(f"/api/partners/proof/{partner_id}")

    assert response.status_code == 422
    assert (
        "404" in response.json()["error"]["message"]
        or "could not be reached" in (response.json()["error"]["message"])
    )
