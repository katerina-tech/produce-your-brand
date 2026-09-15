"""Build a dataset of real Berlin businesses from OpenStreetMap.

Run this to refresh ``data/berlin_partners.json``:

    uv run python scripts/build_berlin_partners.py

**What this file is.** Real, named Berlin businesses, with whatever contact
details they have published to OpenStreetMap themselves. Nothing here is
invented: every field is either copied from an OSM tag or left out.

**What it deliberately is not.** It is not a partner list with capabilities.
OpenStreetMap knows that a business is tagged ``craft=printer``; it does not
know which materials they handle, their minimum order, whether they will work
on goods a customer already owns, or how long they take. Those are exactly the
fields the scorer reads, and inventing them for a company that exists by name
would be the product making claims about a real business that nobody ever
asked it. So they are absent, and every record says ``verified: false``.

That is why these are leads rather than scored matches - the same separation
the live nearby-studios search already keeps, for the same reason.

Attribution: the data is © OpenStreetMap contributors, available under the
Open Database Licence. Anything derived from it carries that attribution, which
is why ``attribution`` is written into the file rather than left to a reader to
remember.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = BACKEND_ROOT / "data" / "berlin_partners.json"

# Berlin, generously bounded - a business just outside the city line is still a
# Berlin option for somebody standing in Berlin.
BERLIN_BBOX = "52.33,13.08,52.68,13.77"

# One OSM tag, one thing it actually means. A print shop certainly prints
# digitally; whether it also does screen or pad printing is a question for the
# shop, not for a map tag, so this claims the narrow thing and leaves the rest
# to the conversation the product exists to start.
TAG_MEANS = {
    ("craft", "printer"): "digital_printing",
    ("shop", "copyshop"): "digital_printing",
    ("shop", "printing"): "digital_printing",
    ("craft", "embroiderer"): "embroidery",
    ("craft", "engraver"): "laser_engraving",
    ("shop", "trophy"): "laser_engraving",
    ("craft", "sign_maker"): "laser_engraving",
}

# What each tag is called by the people who run these businesses. One label per
# tag, never two tags sharing one - a "Druckerei" and a "Copyshop" are
# different shops to anybody in Berlin, and collapsing them would make the
# filter answer a question nobody asked.
#
# This is kept separate from TAG_MEANS because the two say different things:
# the method is what the shop can physically do, and the label is what it calls
# itself. Six of these labels map onto three methods, which is exactly why the
# method was useless as a filter - 134 of 135 companies came back
# "digital printing".
TAG_LABELS = {
    ("craft", "printer"): "Druckerei",
    ("shop", "copyshop"): "Copyshop",
    ("shop", "printing"): "Druckservice",
    ("craft", "embroiderer"): "Stickerei",
    ("craft", "engraver"): "Gravur",
    ("shop", "trophy"): "Pokale & Gravuren",
    ("craft", "sign_maker"): "Schilder & Werbetechnik",
}

ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
)

USER_AGENT = "produce-your-brand/0.1 (dataset build; contact via the repository)"


class TagUnavailableError(RuntimeError):
    """Every mirror refused this tag. Not the same as the tag being empty."""


def _fetch(key: str, value: str) -> list[dict[str, Any]]:
    """One tag, from whichever mirror answers. Overpass is volunteer-run, so
    this waits between attempts rather than hammering a free service.

    Raises rather than returning an empty list when every mirror fails. The two
    outcomes look identical in a result set and mean opposite things: "Berlin
    has no sign makers" is a finding, and "Overpass rate-limited us" is a gap.
    A survey that reports the second as the first is worse than one that admits
    it came back short.
    """
    query = (
        f"[out:json][timeout:90];"
        f'(node["{key}"="{value}"]({BERLIN_BBOX});way["{key}"="{value}"]({BERLIN_BBOX}););'
        f"out center 400;"
    )
    for url in ENDPOINTS:
        for _attempt in range(3):
            try:
                request = urllib.request.Request(
                    url,
                    data=urllib.parse.urlencode({"data": query}).encode(),
                    headers={"User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    return list(json.loads(response.read())["elements"])
            # A mirror being down or rate-limiting is routine, not exceptional:
            # this is a volunteer service and the loop simply tries the next one.
            except Exception as error:
                print(f"  {key}={value} via {url.split('/')[2]}: {error}", file=sys.stderr)
                time.sleep(15)
    raise TagUnavailableError(f"{key}={value}")


def _tag(tags: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        if tags.get(key):
            return tags[key]
    return None


def _address(tags: dict[str, str]) -> str | None:
    parts = [
        tags.get("addr:street"),
        tags.get("addr:housenumber"),
        tags.get("addr:postcode"),
        tags.get("addr:city"),
    ]
    joined = " ".join(part for part in parts if part)
    return joined or None


def _record(
    element: dict[str, Any], method: str, category: str, label: str
) -> dict[str, Any] | None:
    tags: dict[str, str] = element.get("tags") or {}
    name = tags.get("name")
    if not name:
        # An unnamed point cannot be written to, and a lead nobody can contact
        # is not a lead.
        return None

    centre = element.get("center") or element
    return {
        "osm_id": f"{element['type']}/{element['id']}",
        "name": name,
        "method_implied_by_tag": method,
        # The tag this business was found under, and what that tag is called.
        # Kept because the derived method turned out to answer almost nothing:
        # three of the seven tags mean "digital printing", so filtering by it
        # showed 134 of 135 companies.
        "osm_category": category,
        "category_label": label,
        "address": _address(tags),
        "city": tags.get("addr:city") or "Berlin",
        "website": _tag(tags, "website", "contact:website"),
        "email": _tag(tags, "email", "contact:email"),
        "phone": _tag(tags, "phone", "contact:phone"),
        "lat": centre.get("lat"),
        "lon": centre.get("lon"),
    }


def _previous() -> dict[str, dict[str, Any]]:
    """What the last survey found, by id.

    Read so that a re-survey adds to the record rather than replacing it. Two
    reasons, and the second is the important one:

    * Placing each company in its Ortsteil costs 135 requests to a donated
      geocoder, and throwing that away on every re-survey would mean asking for
      it again.
    * Overpass is volunteer-run. A run where one mirror hiccups would otherwise
      silently delete every company under that tag, and a directory that
      quietly shrinks is worse than one that is out of date.
    """
    if not OUTPUT.is_file():
        return {}
    try:
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {record["osm_id"]: record for record in existing.get("partners", [])}


# Facts this survey does not gather and must therefore never overwrite: they
# were derived afterwards, by other scripts, at a cost.
DERIVED_FIELDS = ("district", "borough")


def main() -> int:
    collected: dict[str, dict[str, Any]] = {}

    missed: list[str] = []
    known = _previous()

    for (key, value), method in TAG_MEANS.items():
        category = f"{key}={value}"
        try:
            elements = _fetch(key, value)
        except TagUnavailableError:
            missed.append(category)
            print(f"{category:20} -> NOT FETCHED", file=sys.stderr)
            time.sleep(8)
            continue
        for element in elements:
            record = _record(element, method, category, TAG_LABELS[(key, value)])
            if record is None:
                continue
            # First tag wins, so a business tagged twice keeps one entry and the
            # narrower meaning it was found under first.
            collected.setdefault(record["osm_id"], record)
        print(f"{category:20} -> {len(elements):4} elements", file=sys.stderr)
        time.sleep(8)

    # Carry the derived fields across, and keep anybody this run did not reach.
    for osm_id, record in collected.items():
        for field in DERIVED_FIELDS:
            if known.get(osm_id, {}).get(field):
                record[field] = known[osm_id][field]
    kept = [record for osm_id, record in known.items() if osm_id not in collected]
    if kept:
        print(f"{len(kept)} companies kept from the previous survey", file=sys.stderr)
    for record in kept:
        collected[record["osm_id"]] = record

    partners = sorted(collected.values(), key=lambda record: record["name"].lower())
    contactable = [p for p in partners if p["email"]]

    OUTPUT.write_text(
        json.dumps(
            {
                "attribution": "© OpenStreetMap contributors, Open Database Licence (ODbL)",
                "source": "https://overpass-api.de",
                "area": "Berlin",
                "verified": False,
                "incomplete_categories": missed,
                "note": (
                    "Real businesses with the contact details they published "
                    "themselves. Capabilities are NOT included: OpenStreetMap "
                    "does not know them, and this product does not invent them."
                ),
                "partners": partners,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"\n{len(partners)} real Berlin businesses", file=sys.stderr)
    print(f"{len(contactable)} of them publish an email address", file=sys.stderr)
    if missed:
        print(
            f"INCOMPLETE: {', '.join(missed)} could not be fetched and are missing "
            "from this file entirely - re-run later rather than reading a gap as a finding.",
            file=sys.stderr,
        )
    print(f"written to {OUTPUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
