"""Pull German public tenders for printing, textiles and engraving.

    uv run python scripts/fetch_tenders.py [--day 2026-09-15] [--month 2026-08]
    uv run python scripts/fetch_tenders.py --days 7        # the last week

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
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.repositories import db  # noqa: E402
from app.repositories.tender_repo import TenderRepository  # noqa: E402
from app.services.tender_import import (  # noqa: E402
    deadlines_from_eforms,
    read_export,
    summarise,
)

ENDPOINT = "https://oeffentlichevergabe.de/api/notice-exports"
CSV_TYPE = "application/vnd.bekanntmachungsservice.csv.zip+zip"
EFORMS_TYPE = "application/vnd.bekanntmachungsservice.eforms.zip+zip"

# A month of eForms is about 90 MB against 17 MB of CSV, so a month-sized run
# skips the deadlines rather than pulling that twice. A daily run - which is
# what this is for - takes both and costs a few hundred kilobytes.
EFORMS_DAY_ONLY = True


def _download(client: httpx.Client, params: dict[str, str], media_type: str) -> bytes | None:
    try:
        response = client.get(ENDPOINT, params=params, headers={"Accept": media_type})
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as error:
        print(f"  could not fetch {params} as {media_type.split('.')[-2]}: {error}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", help="One publication day, YYYY-MM-DD.")
    parser.add_argument("--month", help="A whole month, YYYY-MM. No deadlines; see the module.")
    parser.add_argument("--days", type=int, default=0, help="The last N days, ending yesterday.")
    parser.add_argument("--dry-run", action="store_true", help="Report, write nothing.")
    args = parser.parse_args()

    days: list[str] = []
    if args.day:
        days = [args.day]
    elif args.days:
        today = date.today()
        days = [(today - timedelta(days=n)).isoformat() for n in range(1, args.days + 1)]
    elif not args.month:
        # The default is yesterday: notices are published through the day, and
        # a run at breakfast that asked for today would keep missing the rest.
        days = [(date.today() - timedelta(days=1)).isoformat()]

    settings = get_settings()
    connection = db.connect(settings.app_db_path, url=settings.database_url or None)
    db.initialize_schema(connection)
    repository = TenderRepository(connection)

    total_added = 0
    with httpx.Client(timeout=300.0, follow_redirects=True) as client:
        batches: list[tuple[dict[str, str], bool]] = [({"pubDay": day}, True) for day in days]
        if args.month:
            batches.append(({"pubMonth": args.month}, not EFORMS_DAY_ONLY))

        for params, want_deadlines in batches:
            label = params.get("pubDay") or params.get("pubMonth", "")
            payload = _download(client, params, CSV_TYPE)
            if payload is None:
                continue

            deadlines = {}
            if want_deadlines:
                eforms = _download(client, params, EFORMS_TYPE)
                if eforms:
                    deadlines = deadlines_from_eforms(eforms)

            fallback = date.fromisoformat(params["pubDay"]) if "pubDay" in params else None
            tenders = read_export(payload, fallback_day=fallback, deadlines=deadlines)
            counts = summarise(tenders)
            print(
                f"{label}: {counts['kept']:4} relevant "
                f"({counts['berlin']} in Berlin, {counts['sme_suitable']} for SMEs, "
                f"{sum(1 for t in tenders if t.deadline)} with a deadline)"
            )

            if not args.dry_run:
                total_added += repository.save_all(tenders)

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
