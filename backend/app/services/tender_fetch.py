"""Downloading a day of German procurement notices.

Lifted out of ``scripts/fetch_tenders.py`` because two callers need it now: the
scheduled job, and the application itself, which fills an empty board on its
first boot so a fresh deployment is not a tender page with nothing on it.

**This is an API, not a scrape.** Germany's Datenservice Öffentlicher Einkauf
publishes every federal, state and municipal notice as open data under CC0.

Two formats for the same day, because neither alone is enough: the CSV states
the structured fields cleanly, and the submission deadline exists only in the
eForms XML. A tender board without deadlines is a list of things you cannot
tell whether you have missed.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

from app.domain.tender import Tender
from app.logging_config import Event, log_event
from app.services.tender_import import deadlines_from_eforms, read_export

logger = logging.getLogger(__name__)

ENDPOINT = "https://oeffentlichevergabe.de/api/notice-exports"
CSV_TYPE = "application/vnd.bekanntmachungsservice.csv.zip+zip"
EFORMS_TYPE = "application/vnd.bekanntmachungsservice.eforms.zip+zip"

# One request a second or so, though this is open data with no stated limit. It
# is a public service somebody pays for, and neither caller is in a hurry.
PAUSE_SECONDS = 1.0

TIMEOUT_SECONDS = 300.0


def new_client() -> httpx.Client:
    """The one place this product constructs a client for that service."""
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)


def download(client: httpx.Client, params: dict[str, str], media_type: str) -> bytes | None:
    """One export, or None with a line in the log saying why not.

    Never raises. A federal server having a bad morning is not a reason for a
    scheduled job to exit non-zero, nor for an application to fail to start -
    both simply have less data than they hoped for, which the counts show.
    """
    try:
        response = client.get(ENDPOINT, params=params, headers={"Accept": media_type})
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as error:
        log_event(
            logger,
            Event.TOOL_ERROR,
            "tender export could not be fetched",
            level=logging.WARNING,
            params=str(params),
            error_type=type(error).__name__,
        )
        return None


def fetch_day(
    client: httpx.Client, day: date, *, with_deadlines: bool = True
) -> tuple[Tender, ...]:
    """Every printing, textile or engraving tender published on one day."""
    params = {"pubDay": day.isoformat()}
    payload = download(client, params, CSV_TYPE)
    if payload is None:
        return ()

    deadlines = {}
    if with_deadlines:
        eforms = download(client, params, EFORMS_TYPE)
        if eforms:
            deadlines = deadlines_from_eforms(eforms)

    return read_export(payload, fallback_day=day, deadlines=deadlines)


def fetch_month(client: httpx.Client, month: str) -> tuple[Tender, ...]:
    """A whole month, without deadlines.

    A month of eForms is about 90 MB against 17 MB of CSV. That is a fair trade
    for a deliberate backfill and a poor one for anything automatic, which is
    why only ``--month`` reaches this and it says plainly what it gives up.
    """
    payload = download(client, {"pubMonth": month}, CSV_TYPE)
    return read_export(payload) if payload else ()
