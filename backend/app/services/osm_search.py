"""Live search for real Berlin businesses on OpenStreetMap.

Added at explicit user request, as an unscored complement to the curated (and
currently synthetic - see README's Known limitations) supplier dataset. Not a
graph tool and not called by any LangGraph node: it is invoked directly from a
route (``GET /api/projects/{id}/nearby-studios``, see ``app/api/routes.py``),
entirely outside the approval workflow, on purpose. Overpass is a shared,
best-effort public service with no uptime guarantee, and a human-in-the-loop
gate must never be able to stall on it.

**Why these are not supplier matches.** ``app/services/matching.py`` scores a
:class:`~app.domain.supplier.Supplier` against six weighted factors - method,
material, quantity, ownership, deadline, location - because the dataset
records all of that. OpenStreetMap records none of it: a business tagged
``craft=embroiderer`` might have a 2-week backlog or refuse customer-owned
goods, and there is no way to know from the tag alone. So a
:class:`~app.domain.studio.NearbyStudio` is never scored or ranked against a
:class:`~app.domain.matching.MatchResult` - it is presented as an unverified
lead, and the UI says so.

**Why the tag mapping is approximate.** OpenStreetMap has no per-technique
tag for production methods. ``craft=printer`` is the one umbrella tag that
covers screen, digital and pad printing and heat transfer alike;
``craft=embroiderer`` is the one exact match in this table. Every result
carries the specific tag it matched under (``osm_category``), so nothing here
claims more precision than the data actually has.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import Settings
from app.domain.enums import ProductionMethod
from app.domain.studio import NearbyStudio
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)


class OSMSearchError(RuntimeError):
    """Overpass could not be reached, timed out, or returned unparseable JSON."""


# Berlin only, for now - matching the rest of the product's scope (see README's
# target user). A bounding box resolves faster and more reliably on Overpass
# than an `area[name="Berlin"]` lookup. (south, west, north, east)
BERLIN_BBOX: tuple[float, float, float, float] = (52.34, 13.09, 52.68, 13.76)

# See the module docstring's note on precision. `craft=printer` is deliberately
# reused across every print-adjacent method; `craft=embroiderer` is the one
# tag that is actually specific.
METHOD_TAGS: dict[ProductionMethod, tuple[tuple[str, str], ...]] = {
    ProductionMethod.LASER_ENGRAVING: (("shop", "trophy"), ("craft", "sign_maker")),
    ProductionMethod.SCREEN_PRINTING: (("craft", "printer"),),
    ProductionMethod.DIGITAL_PRINTING: (("craft", "printer"), ("shop", "copyshop")),
    ProductionMethod.PAD_PRINTING: (("craft", "printer"),),
    ProductionMethod.HEAT_TRANSFER: (("craft", "printer"),),
    ProductionMethod.EMBROIDERY: (("craft", "embroiderer"),),
    ProductionMethod.LABEL_APPLICATION: (("craft", "printer"),),
    ProductionMethod.PACKAGING_PRINT: (("craft", "printer"),),
}


def build_query(
    tags: tuple[tuple[str, str], ...],
    limit: int,
    bbox: tuple[float, float, float, float] = BERLIN_BBOX,
) -> str:
    """An Overpass QL query matching any of ``tags`` within ``bbox``."""
    south, west, north, east = bbox
    clauses = "\n".join(
        f'  node["{key}"="{value}"]({south},{west},{north},{east});\n'
        f'  way["{key}"="{value}"]({south},{west},{north},{east});'
        for key, value in tags
    )
    return f"[out:json][timeout:25];\n(\n{clauses}\n);\nout center {limit};"


def _address_from_tags(tags: dict[str, str]) -> str | None:
    parts = [
        tags.get("addr:street"),
        tags.get("addr:housenumber"),
        tags.get("addr:postcode"),
        tags.get("addr:city"),
    ]
    joined = " ".join(part for part in parts if part)
    return joined or None


def _matched_category(tags: dict[str, str], candidates: tuple[tuple[str, str], ...]) -> str:
    for key, value in candidates:
        if tags.get(key) == value:
            return f"{key}={value}"
    return "unknown"


def _parse_element(
    element: dict[str, Any], candidates: tuple[tuple[str, str], ...]
) -> NearbyStudio | None:
    tags = element.get("tags") or {}
    name = tags.get("name")
    if not name:
        return None  # An unnamed point is not something a person can contact.

    center = element.get("center") or {}
    lat = element.get("lat", center.get("lat"))
    lon = element.get("lon", center.get("lon"))
    if lat is None or lon is None:
        return None

    return NearbyStudio(
        osm_id=f"{element.get('type', 'node')}/{element.get('id')}",
        name=name,
        osm_category=_matched_category(tags, candidates),
        address=_address_from_tags(tags),
        website=tags.get("website") or tags.get("contact:website"),
        phone=tags.get("phone") or tags.get("contact:phone"),
        lat=float(lat),
        lon=float(lon),
    )


class OverpassStudioSearch:
    """Queries the public Overpass API, with a short-lived in-memory cache.

    The cache exists because Overpass is a shared, fair-use public service:
    without it, reopening one project's partner-matches screen a few times in
    a row would re-fire the same query for data that has not changed. It is
    process-local and never persisted - losing it on a restart is a non-issue
    for something this cheap to recompute, and persisting it would make this
    module a second, uncounted "supplier data" store in spirit if not in the
    architecture audit's literal rule.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        result_limit: int,
        cache_ttl_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._limit = result_limit
        self._ttl = cache_ttl_seconds
        self._client = client or httpx.Client()
        self._cache: dict[ProductionMethod, tuple[float, list[NearbyStudio]]] = {}

    def search(self, method: ProductionMethod) -> list[NearbyStudio]:
        cached = self._cache.get(method)
        if cached is not None and (time.monotonic() - cached[0]) < self._ttl:
            return cached[1]

        # Indexed directly, not `.get(..., default)`: METHOD_TAGS is meant to be
        # exhaustive over ProductionMethod (see test_osm_search.py), so a
        # missing entry is a bug to surface immediately, not paper over.
        tags = METHOD_TAGS[method]
        query = build_query(tags, self._limit)

        try:
            response = self._client.post(
                self._base_url,
                data={"data": query},
                timeout=self._timeout,
                # Overpass's own usage policy asks for an identifiable client;
                # some front-ends also reject the bare default httpx UA outright.
                headers={"User-Agent": "produce-your-stuff/0.1 (github.com/katerina-tech)"},
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            log_event(
                logger,
                Event.TOOL_ERROR,
                "osm search failed",
                level=logging.ERROR,
                method=method.value,
            )
            raise OSMSearchError(f"OpenStreetMap search failed: {error}") from error

        results: list[NearbyStudio] = []
        seen_ids: set[str] = set()
        for element in body.get("elements", []):
            studio = _parse_element(element, tags)
            if studio is not None and studio.osm_id not in seen_ids:
                seen_ids.add(studio.osm_id)
                results.append(studio)

        self._cache[method] = (time.monotonic(), results)
        log_event(
            logger,
            Event.OSM_SEARCH_COMPLETED,
            "osm search completed",
            method=method.value,
            result_count=len(results),
        )
        return results


def get_osm_search(settings: Settings) -> OverpassStudioSearch:
    """The one construction site for :class:`OverpassStudioSearch`."""
    return OverpassStudioSearch(
        base_url=settings.osm_overpass_url,
        timeout_seconds=settings.osm_request_timeout_seconds,
        result_limit=settings.osm_result_limit,
        cache_ttl_seconds=settings.osm_cache_ttl_seconds,
    )
