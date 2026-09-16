"""Pull German public tenders for printing, textiles and engraving.

    uv run python scripts/fetch_tenders.py [--day 2026-09-15] [--month 2026-08]
    uv run python scripts/fetch_tenders.py --days 7        # the last week
    uv run python scripts/fetch_tenders.py --catch-up      # everything since last time

**This is an API, not a scrape.** Germany's Datenservice Öffentlicher Einkauf
publishes every federal, state and municipal notice as open data, dedicated to
the public domain under CC0. There is no robots.txt to weigh, no rate limit to
tiptoe around, and no terms to read twice - the service exists to be consumed.

It also carries **below-threshold** notices, which never reach TED. That is the
half that matters for a directory of small Berlin shops: an EU-threshold
contract is too large for a copyshop, and the small municipal ones are exactly
the reachable work.

Two formats are fetched for the same day, because neither alone is enough. The
CSV states the structured fields cleanly; the submission deadline appears only
in the eForms XML, and a tender board without deadlines is a list of things you
cannot tell whether you have missed.

``--catch-up`` is what a schedule should run. It starts from the newest day the
database already holds rather than counting back a fixed number, so a run that
was skipped, a month with 31 days, or a container that failed halfway cannot
leave a hole nobody notices. Re-reading a day is free of consequence: notices
are stored by their own identifier and a second pass overwrites rather than
duplicates.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.repositories import db  # noqa: E402
from app.repositories.tender_repo import TenderRepository  # noqa: E402
from app.services.tender_fetch import (  # noqa: E402
    PAUSE_SECONDS,
    fetch_day,
    fetch_month,
    new_client,
)
from app.services.tender_import import summarise  # noqa: E402

# How far back a catch-up will reach when the database is empty or long
# neglected. Beyond this it is a backfill somebody should ask for by name with
# --month, not something a scheduled job decides to do on its own at four in
# the morning.
MAX_CATCH_UP_DAYS = 45


def _catch_up_days(repository: TenderRepository, yesterday: date) -> list[str]:
    """Every publication day from where the database got to, up to yesterday.

    One day of overlap on purpose: a notice published late on the newest day
    held may not have been in the export when that day was fetched, and
    re-reading it costs one request and overwrites nothing that matters.
    """
    newest = repository.newest_published()
    start = (
        (newest - timedelta(days=1)) if newest else (yesterday - timedelta(days=MAX_CATCH_UP_DAYS))
    )
    start = max(start, yesterday - timedelta(days=MAX_CATCH_UP_DAYS))
    if start > yesterday:
        return []
    span = (yesterday - start).days
    return [(start + timedelta(days=n)).isoformat() for n in range(span + 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", help="One publication day, YYYY-MM-DD.")
    parser.add_argument("--month", help="A whole month, YYYY-MM. No deadlines; see the module.")
    parser.add_argument("--days", type=int, default=0, help="The last N days, ending yesterday.")
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help="Every day since the newest already held. What a schedule should run.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report, write nothing.")
    args = parser.parse_args()

    settings = get_settings()
    connection = db.connect(settings.app_db_path, url=settings.database_url or None)
    db.initialize_schema(connection)
    repository = TenderRepository(connection)

    yesterday = date.today() - timedelta(days=1)
    days: list[str] = []
    if args.day:
        days = [args.day]
    elif args.days:
        days = [(yesterday - timedelta(days=n)).isoformat() for n in range(args.days)]
    elif args.catch_up:
        days = _catch_up_days(repository, yesterday)
        if not days:
            print("Already up to date.")
            return 0
        print(f"Catching up {len(days)} day(s): {days[0]} to {days[-1]}.")
    elif not args.month:
        # The default is yesterday: notices are published through the day, and
        # a run at breakfast that asked for today would keep missing the rest.
        days = [yesterday.isoformat()]

    total_added = 0
    labels = [*days, *([args.month] if args.month else [])]
    with new_client() as client:
        for label in labels:
            if args.month and label == args.month:
                tenders = fetch_month(client, args.month)
            else:
                tenders = fetch_day(client, date.fromisoformat(label))

            counts = summarise(tenders)
            print(
                f"{label}: {counts['kept']:4} relevant "
                f"({counts['berlin']} in Berlin, {counts['sme_suitable']} for SMEs, "
                f"{sum(1 for t in tenders if t.deadline)} with a deadline)"
            )

            if not args.dry_run:
                total_added += repository.save_all(tenders)
            if len(labels) > 1:
                time.sleep(PAUSE_SECONDS)

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    today = datetime.now(UTC).date()
    print(f"\nAdded {total_added} new notices.")
    print(
        f"Database holds {repository.count()} tenders, {repository.berlin_count()} in Berlin; "
        f"{len(repository.search(limit=1000, today=today))} still open."
    )
    for prefix, label, count in repository.families():
        print(f"  {label:30} {count:4}  (CPV {prefix}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
