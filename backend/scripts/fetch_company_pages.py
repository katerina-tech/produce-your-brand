"""Fetch the websites of the directory's companies and store their readable text.

    uv run python scripts/fetch_company_pages.py [--limit N]

Separated from extraction on purpose. Fetching is free and slow; reading with a
model costs money and is fast. Keeping the text means the reading can be re-run
- after a prompt change, a model change, or a top-up - without asking ninety
German print shops for their homepage again.

Politeness is not optional here. These are small businesses whose sites this
product reads uninvited, so: their robots.txt is obeyed, one company at a time,
a pause between them, and at most a handful of pages each. A survey that got
this wrong would be a survey they are entitled to block, and right to.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.repositories.partner_repo import PartnerRepository  # noqa: E402
from app.services.site_fetch import (  # noqa: E402
    USER_AGENT,
    FetchedPage,
    SiteFetchError,
    fetch_page,
    service_links,
)

OUTPUT = BACKEND_ROOT / "data" / "company_pages.json"
DIRECTORY = BACKEND_ROOT / "data" / "berlin_partners.json"

# Seconds between companies. Slow on purpose: this is a one-off survey against
# other people's servers, and nothing here is in a hurry.
PAUSE_SECONDS = 2.0
PAGES_PER_COMPANY = 3


def _pages_for(url: str, client: httpx.Client) -> tuple[list[FetchedPage], str | None]:
    """The home page plus a couple of service pages, or why there are none."""
    try:
        home = fetch_page(url, client=client)
    except SiteFetchError as refused:
        return [], str(refused)

    pages = [home]
    for link in service_links(home, limit=PAGES_PER_COMPANY - 1):
        time.sleep(PAUSE_SECONDS / 2)
        try:
            pages.append(fetch_page(link, client=client))
        except SiteFetchError:
            # One unreachable sub-page is not a reason to lose the home page.
            continue
    return pages, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="stop after N companies")
    args = parser.parse_args()

    partners = PartnerRepository(DIRECTORY)
    with_site = [partner for partner in partners.all() if partner.website]
    if args.limit:
        with_site = with_site[: args.limit]

    print(f"{len(with_site)} of {partners.count()} companies publish a website", file=sys.stderr)

    records: list[dict[str, Any]] = []
    read = skipped = 0

    with httpx.Client(follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for index, partner in enumerate(with_site, start=1):
            assert partner.website is not None
            pages, refusal = _pages_for(partner.website, client)
            substantial = [page for page in pages if page.is_substantial]

            if substantial:
                read += 1
                words = sum(len(page.text.split()) for page in substantial)
                status = f"{len(substantial)} page(s), {words} words"
            else:
                skipped += 1
                status = refusal or "nothing substantial"

            print(f"[{index:3}/{len(with_site)}] {partner.name[:38]:38} {status}", file=sys.stderr)

            records.append(
                {
                    "partner_id": partner.id,
                    "partner_name": partner.name,
                    "website": partner.website,
                    # Both recorded: a site that refused and a site that was
                    # empty are different facts, and a later run should know
                    # which it is looking at.
                    "skipped_reason": None if substantial else (refusal or "nothing substantial"),
                    "pages": [{"url": page.url, "text": page.text} for page in substantial],
                }
            )
            time.sleep(PAUSE_SECONDS)

    OUTPUT.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "user_agent": USER_AGENT,
                "note": (
                    "Readable text from companies' own public websites, fetched once "
                    "with robots.txt honoured. Capabilities are NOT in here - reading "
                    "these into claims is a separate, model-driven step."
                ),
                "companies": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"\nread {read}, skipped {skipped}", file=sys.stderr)
    print(f"written to {OUTPUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
