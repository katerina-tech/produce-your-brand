"""Fill an empty tender board on first boot, in the background.

A deployment that has never run the job shows a tender page with nothing on it,
and a board with nothing on it teaches a visitor that there is nothing there.
So the application seeds itself once - the same discipline already applied to
the Berlin company directory, which fills an empty table from its survey file
at startup.

Three properties make this safe to do from a web process:

* **Only when the board is empty.** Not "when it is stale" - keeping it fresh
  is the scheduled job's work, and a web process that quietly re-fetched would
  be a second schedule nobody configured.
* **After startup, never during it.** A daemon thread, so the API is already
  answering while this runs. The comment that used to sit in ``main.py`` said a
  boot should not depend on a federal server being awake; this honours that by
  not being part of the boot at all.
* **Bounded.** Two weeks, not the forty-five a catch-up would take. Enough that
  the board is worth looking at within a minute of a deploy, and little enough
  that it is a minute rather than ten.

It opens its own connection rather than borrowing the application's. psycopg3
connections are not safe to use from two threads at once, and a seeder that
shared one would corrupt whatever a request happened to be doing.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, date, timedelta

from app.config import Settings
from app.logging_config import Event, log_event
from app.repositories import db
from app.repositories.tender_repo import TenderRepository
from app.services.tender_fetch import PAUSE_SECONDS, fetch_day, new_client

logger = logging.getLogger(__name__)

# Enough for a board worth reading, short enough to finish in about a minute.
# The scheduled job's catch-up reaches forty-five days; this is not that, and
# should not become it.
SEED_DAYS = 14


def _run(settings: Settings) -> None:
    connection = db.connect(settings.app_db_path, url=settings.database_url or None)
    try:
        # Its own connection means its own responsibility for the schema.
        # The application happens to have built it already, but a module that
        # is only correct because of who called it first is a module that
        # breaks the day somebody calls it second. Idempotent, so this costs
        # nothing.
        db.initialize_schema(connection)
        repository = TenderRepository(connection)
        if repository.count() > 0:
            return

        yesterday = datetime_today() - timedelta(days=1)
        added = 0
        with new_client() as client:
            for offset in range(SEED_DAYS):
                found = fetch_day(client, yesterday - timedelta(days=offset))
                if found:
                    added += repository.save_all(found)
                time.sleep(PAUSE_SECONDS)

        log_event(
            logger,
            Event.SUPPLIER_CANDIDATES_FOUND,
            "tender board seeded on first boot",
            added=added,
            days=SEED_DAYS,
        )
    except Exception:
        # Never lets a network problem escape into the application. The board
        # stays empty, the page says so, and the scheduled job will fill it.
        logger.exception(
            "tender board could not be seeded", extra={"event": Event.TOOL_ERROR.value}
        )
    finally:
        connection.close()


def datetime_today() -> date:
    """Today, in UTC. Its own function so a test can replace it."""
    from datetime import datetime

    return datetime.now(UTC).date()


def seed_in_background(settings: Settings) -> threading.Thread | None:
    """Start the seed if it is wanted. Returns the thread, or None.

    Returns the thread so a test can wait for it. Nothing in production does:
    the point is that the application does not.
    """
    if not settings.seed_tenders_on_boot:
        return None

    thread = threading.Thread(target=_run, args=(settings,), name="tender-seed", daemon=True)
    thread.start()
    return thread
