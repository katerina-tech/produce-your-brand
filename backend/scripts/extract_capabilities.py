"""Turn the fetched company pages into verified capability claims in the database.

    uv run python scripts/extract_capabilities.py [--limit N] [--refresh] [--partner ID]

The second half of the reviewer's pipeline. ``fetch_company_pages.py`` asked
ninety German print shops for their homepage once and kept the text; this reads
that text with a model, deletes every claim whose words are not actually on the
page, and stores what survives.

**Resumable by default.** A company already read is skipped, because each one
costs a model call and a run that dies at company sixty should not pay for the
first fifty-nine again. ``--refresh`` is how you deliberately re-read after a
prompt or model change - it is an explicit act, never a side effect.

**A reading that found nothing is still recorded.** "We read this site and it
said nothing about what they make" is a finding; never having looked is not.
Storing both the same way would make the two indistinguishable next run.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.llm.factory import get_provider  # noqa: E402
from app.repositories import db  # noqa: E402
from app.repositories.capability_repo import CapabilityRepository  # noqa: E402
from app.security.guard import build_guard  # noqa: E402
from app.services.capability_extract import extract_capabilities  # noqa: E402
from app.services.site_fetch import FetchedPage  # noqa: E402

PAGES_FILE = BACKEND_ROOT / "data" / "company_pages.json"


def _pages_of(company: dict[str, Any]) -> tuple[FetchedPage, ...]:
    return tuple(
        FetchedPage(url=str(page["url"]), text=str(page["text"]))
        for page in company.get("pages", [])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many companies.")
    parser.add_argument(
        "--refresh", action="store_true", help="Re-read companies already in the database."
    )
    parser.add_argument("--partner", default="", help="Read one company by id.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be read, call no model."
    )
    args = parser.parse_args()

    if not PAGES_FILE.is_file():
        print(f"No fetched pages at {PAGES_FILE}. Run scripts/fetch_company_pages.py first.")
        return 1

    payload = json.loads(PAGES_FILE.read_text(encoding="utf-8"))
    companies: list[dict[str, Any]] = payload.get("companies", [])

    settings = get_settings()
    connection = db.connect(settings.app_db_path, url=settings.database_url or None)
    db.initialize_schema(connection)
    repository = CapabilityRepository(connection)

    done = set() if args.refresh else repository.already_read()
    today = datetime.now(UTC).date()

    queue = [
        company
        for company in companies
        if _pages_of(company)
        and (not args.partner or company["partner_id"] == args.partner)
        and company["partner_id"] not in done
    ]
    if args.limit > 0:
        queue = queue[: args.limit]

    print(
        f"{len(companies)} companies fetched | {len(done)} already read | {len(queue)} to read now"
    )
    if args.dry_run:
        for company in queue:
            pages = _pages_of(company)
            words = sum(len(page.text.split()) for page in pages)
            print(f"  would read {company['partner_name']}: {len(pages)} pages, {words} words")
        return 0
    if not queue:
        print("Nothing to do. Pass --refresh to read them again.")
        return 0

    # Built once outside the loop: the guard and the provider are stateless, and
    # rebuilding them per company would be ninety pointless constructions.
    guard = build_guard()
    provider = get_provider(settings)

    read = 0
    claims_total = 0
    empty = 0
    blocked = 0
    failed = 0

    for index, company in enumerate(queue, start=1):
        name = str(company["partner_name"])
        outcome = extract_capabilities(
            pages=_pages_of(company),
            partner_id=str(company["partner_id"]),
            partner_name=name,
            extracted_on=today,
            guard=guard,
            provider=provider,
        )
        repository.save(
            outcome.capabilities, blocked=outcome.blocked, model_failed=outcome.model_failed
        )

        read += 1
        count = len(outcome.capabilities.claims)
        claims_total += count
        if outcome.blocked:
            blocked += 1
            note = "blocked by the injection screen"
        elif outcome.model_failed:
            failed += 1
            note = "model call failed"
        elif count == 0:
            empty += 1
            note = "nothing specific said"
        else:
            dropped = outcome.capabilities.dropped_count
            note = f"{count} claims" + (f", {dropped} unsupported deleted" if dropped else "")
        print(f"  [{index}/{len(queue)}] {name}: {note}")

    print(
        f"\nRead {read} companies: {claims_total} claims kept, "
        f"{empty} said nothing, {blocked} blocked, {failed} failed."
    )
    print(
        f"Database now holds {repository.count()} readings, "
        f"{repository.with_claims_count()} with claims, {repository.claim_count()} claims total."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
