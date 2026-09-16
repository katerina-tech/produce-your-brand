"""Filling an empty tender board on first boot.

The property worth the most here is a negative one: **this must not reach the
network unless it was asked to.** A seed that ran by default would make a test
run and a developer's laptop dial a federal server, and a default that only
bites in one environment is a default nobody remembers.

Everything below is exercised without a network: the fetch is replaced, and
what is tested is the decision to call it and what is done with the result.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.domain.tender import Tender
from app.repositories import db
from app.repositories.tender_repo import TenderRepository
from app.services import tender_seed


def _settings(tmp_path: Path, *, seed: bool) -> Settings:
    return Settings(
        app_db_path=tmp_path / "seed.db",
        upload_dir=tmp_path / "uploads",
        seed_tenders_on_boot=seed,
    )


def _tender(identifier: str) -> Tender:
    return Tender(
        id=identifier,
        title="Druck von Broschüren",
        cpv="79800000",
        family_prefix="798",
        family_label="Druckdienstleistungen",
        place_region="DE300",
        published_on=date(2026, 9, 14),
    )


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    """Replace the download with a record of which days were asked for."""
    asked: list[date] = []

    class _Client:
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fetch_day(_client: object, day: date, **_: object) -> tuple[Tender, ...]:
        asked.append(day)
        return (_tender(f"t-{day.isoformat()}"),)

    monkeypatch.setattr(tender_seed, "new_client", _Client)
    monkeypatch.setattr(tender_seed, "fetch_day", fetch_day)
    monkeypatch.setattr(tender_seed, "PAUSE_SECONDS", 0.0)
    return asked


def _finish(thread: threading.Thread | None) -> None:
    assert thread is not None
    thread.join(timeout=10)
    assert not thread.is_alive()


# ------------------------------------------------------- the negative property


def test_it_does_nothing_unless_asked(tmp_path: Path, no_network: list[date]) -> None:
    """Off by default, switched on in the Dockerfile. Anything that dials out
    from a boot should be opt-in."""
    assert Settings(app_db_path=tmp_path / "x.db").seed_tenders_on_boot is False

    assert tender_seed.seed_in_background(_settings(tmp_path, seed=False)) is None
    assert no_network == []


def test_a_board_that_already_has_notices_is_left_alone(
    tmp_path: Path, no_network: list[date]
) -> None:
    """Only when empty - not "when it is stale". Keeping it fresh is the
    scheduled job's work, and a web process that re-fetched would be a second
    schedule nobody configured."""
    settings = _settings(tmp_path, seed=True)
    connection = db.connect(settings.app_db_path)
    db.initialize_schema(connection)
    TenderRepository(connection).save_all((_tender("already-here"),))
    connection.close()

    _finish(tender_seed.seed_in_background(settings))

    assert no_network == []


# ------------------------------------------------------------- when it runs


def test_an_empty_board_is_filled(
    tmp_path: Path, no_network: list[date], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tender_seed, "datetime_today", lambda: date(2026, 9, 16))
    settings = _settings(tmp_path, seed=True)

    _finish(tender_seed.seed_in_background(settings))

    connection = db.connect(settings.app_db_path)
    assert TenderRepository(connection).count() == tender_seed.SEED_DAYS
    connection.close()


def test_it_asks_for_yesterday_backwards_and_stops(
    tmp_path: Path, no_network: list[date], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yesterday, because notices are published through the day. Bounded at two
    weeks, because this is the thing that makes a fresh deploy worth looking at
    - not the forty-five-day catch-up, which belongs to the job."""
    monkeypatch.setattr(tender_seed, "datetime_today", lambda: date(2026, 9, 16))

    _finish(tender_seed.seed_in_background(_settings(tmp_path, seed=True)))

    assert no_network[0] == date(2026, 9, 15)
    assert len(no_network) == tender_seed.SEED_DAYS
    assert no_network[-1] == date(2026, 9, 15) - timedelta(days=tender_seed.SEED_DAYS - 1)


def test_a_federal_server_having_a_bad_morning_is_not_a_failed_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The board stays empty, the page says so, and the scheduled job will fill
    it. Nothing escapes into the application."""

    def explode(*_: object, **__: object) -> tuple[Tender, ...]:
        raise OSError("connection reset")

    monkeypatch.setattr(tender_seed, "fetch_day", explode)
    monkeypatch.setattr(tender_seed, "PAUSE_SECONDS", 0.0)
    settings = _settings(tmp_path, seed=True)

    _finish(tender_seed.seed_in_background(settings))

    connection = db.connect(settings.app_db_path)
    db.initialize_schema(connection)
    assert TenderRepository(connection).count() == 0
    connection.close()


def test_the_seed_does_not_block_the_caller(
    tmp_path: Path, no_network: list[date], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon thread, so the API is already answering while this runs. The
    boot does not wait for a federal server because it is not part of the boot."""
    monkeypatch.setattr(tender_seed, "datetime_today", lambda: date(2026, 9, 16))

    thread = tender_seed.seed_in_background(_settings(tmp_path, seed=True))

    assert thread is not None
    assert thread.daemon is True
    _finish(thread)
