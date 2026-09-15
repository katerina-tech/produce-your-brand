"""Read each company's own website for the address and the summary it publishes.

    uv run python scripts/enrich_contacts.py [--dry-run] [--limit N]

A short manual check found the gap this closes. A&W Digitaldruck publishes
``info [at] aw-digital.de`` on its homepage, and the directory said "no email
published" beside their name: the survey only ever read OpenStreetMap's
``email`` tag, and the fetched page text was read for capabilities and never
for contacts.

Everything here is a regular expression and a ranking rule - no model, no cost,
nothing to top up. It runs over pages already fetched, so it asks nothing of
anybody's server.

**An address from a map tag is never overwritten.** Somebody maintains those,
and a line scraped off a homepage is not an improvement on a fact a person put
in OpenStreetMap on purpose. This only fills in where there was nothing.

The summary is the company's own meta description - the line somebody at the
business wrote to describe the business, and the same line a search engine
shows them. Not a sentence picked out of their page body, which is as often a
cookie notice as a description, and not a model's paraphrase.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.repositories import db  # noqa: E402
from app.repositories.partner_repo import PartnerRepository  # noqa: E402
from app.services.contact_extract import best_email, clean_summary  # noqa: E402

SURVEY = BACKEND_ROOT / "data" / "berlin_partners.json"
PAGES = BACKEND_ROOT / "data" / "company_pages.json"


def _summary_for(company: dict[str, Any]) -> str:
    """The first meta description any of this company's pages carries.

    First rather than longest: the homepage is fetched first and describes the
    business, while a deeper page describes that page.
    """
    for page in company.get("pages", []):
        summary = clean_summary(str(page.get("description") or ""))
        if summary:
            return summary
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many companies.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change, write nothing."
    )
    args = parser.parse_args()

    for path in (SURVEY, PAGES):
        if not path.is_file():
            print(f"Missing {path.name}. Run the survey and the page fetch first.")
            return 1

    survey = json.loads(SURVEY.read_text(encoding="utf-8"))
    pages = json.loads(PAGES.read_text(encoding="utf-8"))
    by_id = {record["osm_id"]: record for record in survey.get("partners", [])}
    queue = pages.get("companies", [])
    if args.limit > 0:
        queue = queue[: args.limit]

    found_email = 0
    found_summary = 0
    already = 0

    for company in queue:
        record = by_id.get(company["partner_id"])
        if record is None:
            continue

        text = "\n".join(page.get("text", "") for page in company.get("pages", []))
        mailto = tuple(
            address for page in company.get("pages", []) for address in page.get("mailto", [])
        )

        summary = _summary_for(company)
        if summary and not record.get("summary"):
            record["summary"] = summary
            found_summary += 1

        if record.get("email"):
            record.setdefault("email_source", "openstreetmap")
            already += 1
            continue

        candidate = best_email(text, mailto=mailto, website=company.get("website"))
        if candidate is None:
            continue

        record["email"] = candidate.address
        record["email_source"] = "website"
        found_email += 1
        why = []
        if candidate.from_mailto:
            why.append("linked")
        if candidate.matches_website:
            why.append("own domain")
        if candidate.is_role:
            why.append("role box")
        print(f"  {company['partner_name'][:38]:38} {candidate.address:38} ({', '.join(why)})")

    contactable = sum(1 for record in survey["partners"] if record.get("email"))
    print(
        f"\n{found_email} addresses recovered from company websites, "
        f"{already} already known from OpenStreetMap."
    )
    print(f"{found_summary} companies now carry their own one-line summary.")
    print(f"Contactable: {contactable} of {len(survey['partners'])}.")

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    SURVEY.write_text(json.dumps(survey, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    settings = get_settings()
    connection = db.connect(settings.app_db_path, url=settings.database_url or None)
    db.initialize_schema(connection)
    repository = PartnerRepository(connection, SURVEY)
    repository.seed_missing()
    repository.fill_in_districts()
    print(f"\nDatabase: {repository.contactable_count()} of {repository.count()} contactable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
