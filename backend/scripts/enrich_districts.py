"""Work out which part of Berlin each company is in, from its coordinates.

    uv run python scripts/enrich_districts.py [--limit N] [--refresh]

Why coordinates and not the address: every one of the 135 records has a
position, and only 82 have an address with a postcode in it. Parsing the street
line would answer the question for three companies in five and silently invent
nothing for the rest - which is the worse kind of gap, because a filter would
look complete while quietly hiding a third of the directory.

Two names are stored, because they answer different questions. The **Ortsteil**
(Kreuzberg, Wedding, Prenzlauer Berg) is what a person says out loud. The
**Bezirk** is one of Berlin's twelve, and is the only one of the two that makes
a filter somebody will actually read. Businesses just outside the city keep
their town name and no Bezirk, which is the honest answer rather than the
nearest Berlin label.

The result is written to the survey file, because that is where facts the
survey gathered belong - the database then picks them up at seed time, or
through ``fill_in_districts`` for a table that already exists. Facts a person
established, like a confirmed capability, never travel this way.

Nominatim is a free service run on donated hardware. Its usage policy asks for
at most one request a second and a User-Agent that identifies the caller, and
both are obeyed here. 135 companies take about three minutes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.repositories import db  # noqa: E402
from app.repositories.partner_repo import PartnerRepository  # noqa: E402

SURVEY = BACKEND_ROOT / "data" / "berlin_partners.json"
ENDPOINT = "https://nominatim.openstreetmap.org/reverse"

# Their usage policy asks for an identifying agent and no more than one request
# a second. A survey that ignored either would be one they are right to block.
USER_AGENT = (
    "ProduceYourStuff/0.1 (Berlin production directory; +https://produceyourstuff.up.railway.app)"
)
PAUSE_SECONDS = 1.2

# zoom=14 is the level that answers with a suburb rather than a street or a
# whole city. Lower and every company in Berlin comes back "Berlin".
ZOOM = 14

# Berlin's twelve Bezirke, unchanged since the 2001 reform. Written out rather
# than trusted from the response, because the geocoder answers a *nearby*
# administrative name for an address outside the city - the first run of this
# script put Stahnsdorf, a Brandenburg town, in the borough filter beside
# Pankow and Mitte. Checking against the real list makes that impossible rather
# than unlikely.
BERLIN_BOROUGHS = frozenset(
    {
        "Mitte",
        "Friedrichshain-Kreuzberg",
        "Pankow",
        "Charlottenburg-Wilmersdorf",
        "Spandau",
        "Steglitz-Zehlendorf",
        "Tempelhof-Schöneberg",
        "Neukölln",
        "Treptow-Köpenick",
        "Marzahn-Hellersdorf",
        "Lichtenberg",
        "Reinickendorf",
    }
)


def look_up(client: httpx.Client, lat: float, lon: float) -> tuple[str | None, str | None]:
    """The Ortsteil and Bezirk at one position, or two Nones.

    Never raises: a directory entry with an unknown district is a directory
    entry, and losing the company over it would be a worse answer than an empty
    filter value.
    """
    try:
        response = client.get(
            ENDPOINT,
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": ZOOM, "addressdetails": 1},
        )
        response.raise_for_status()
        address: dict[str, Any] = response.json().get("address", {})
    except (httpx.HTTPError, ValueError):
        return None, None

    # suburb is the Ortsteil inside Berlin. Outside it, the town is the honest
    # answer - and it deliberately gets no Bezirk, because it is not in one.
    district = address.get("suburb") or address.get("town") or address.get("village")
    borough = address.get("borough")
    return (
        str(district) if district else None,
        str(borough) if borough in BERLIN_BOROUGHS else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many companies.")
    parser.add_argument(
        "--refresh", action="store_true", help="Look up companies that already have a district."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be looked up, ask nothing."
    )
    args = parser.parse_args()

    if not SURVEY.is_file():
        print(f"No survey at {SURVEY}. Run scripts/build_berlin_partners.py first.")
        return 1

    payload = json.loads(SURVEY.read_text(encoding="utf-8"))
    partners: list[dict[str, Any]] = payload.get("partners", [])

    queue = [
        partner
        for partner in partners
        if partner.get("lat") is not None
        and partner.get("lon") is not None
        and (args.refresh or not partner.get("district"))
    ]
    if args.limit > 0:
        queue = queue[: args.limit]

    known = sum(1 for partner in partners if partner.get("district"))
    print(f"{len(partners)} companies | {known} already placed | {len(queue)} to look up now")
    if args.dry_run:
        return 0
    if not queue:
        print("Nothing to do. Pass --refresh to look them up again.")
        return 0

    print(f"About {len(queue) * PAUSE_SECONDS / 60:.1f} minutes at one request a second.\n")

    placed = 0
    outside = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0) as client:
        for index, partner in enumerate(queue, start=1):
            district, borough = look_up(client, partner["lat"], partner["lon"])
            partner["district"] = district
            partner["borough"] = borough

            if district:
                placed += 1
                where = f"{district}" + (f" ({borough})" if borough else " - outside Berlin")
            else:
                where = "not placed"
            if district and not borough:
                outside += 1
            print(f"  [{index}/{len(queue)}] {partner['name']}: {where}")

            # Written after every company rather than at the end: a run
            # interrupted at ninety has done ninety companies' work, and
            # throwing it away would mean asking a donated server for it twice.
            SURVEY.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            if index < len(queue):
                time.sleep(PAUSE_SECONDS)

    print(f"\nPlaced {placed} of {len(queue)}; {outside} sit outside Berlin's boroughs.")

    settings = get_settings()
    connection = db.connect(settings.app_db_path, url=settings.database_url or None)
    db.initialize_schema(connection)
    repository = PartnerRepository(connection, SURVEY)
    filled = repository.fill_in_districts()
    print(f"Filled in {filled} database rows that had no district.")
    for borough, count in repository.boroughs():
        print(f"  {borough}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
