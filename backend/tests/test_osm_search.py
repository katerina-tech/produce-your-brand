"""app/services/osm_search.py - never touches the real Overpass API.

httpx.MockTransport stands in for the network, exactly the way ScriptedProvider
stands in for the model: the parsing, caching and error handling are production
code, and only the HTTP round-trip is faked.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.domain.enums import ProductionMethod
from app.services.osm_search import (
    METHOD_TAGS,
    OSMSearchError,
    OverpassStudioSearch,
    build_query,
)

_NAMED_NODE = {
    "type": "node",
    "id": 1,
    "lat": 52.5,
    "lon": 13.4,
    "tags": {
        "craft": "printer",
        "name": "Kreuzberg Foil Works",
        "addr:street": "Skalitzer Str.",
        "addr:housenumber": "1",
        "addr:postcode": "10999",
        "addr:city": "Berlin",
        "website": "https://example.invalid",
    },
}

_NAMED_WAY_WITH_CENTER = {
    "type": "way",
    "id": 2,
    "center": {"lat": 52.51, "lon": 13.41},
    "tags": {"craft": "printer", "name": "Neukoelln Screens", "contact:phone": "+49 30 000"},
}

_UNNAMED_NODE = {
    "type": "node",
    "id": 3,
    "lat": 52.52,
    "lon": 13.42,
    "tags": {"craft": "printer"},
}


def _client(
    handler: Callable[[httpx.Request], httpx.Response], **overrides: Any
) -> OverpassStudioSearch:
    return OverpassStudioSearch(
        base_url="https://overpass.example/api/interpreter",
        timeout_seconds=5.0,
        result_limit=12,
        cache_ttl_seconds=overrides.get("cache_ttl_seconds", 3600),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _json_response(elements: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"elements": elements})


def test_method_tags_cover_every_production_method() -> None:
    """The mapping must be exhaustive - `search` indexes it directly, on purpose."""
    for method in ProductionMethod:
        assert method in METHOD_TAGS
        assert METHOD_TAGS[method]  # at least one tag pair


def test_build_query_includes_the_bbox_and_every_tag() -> None:
    query = build_query((("craft", "printer"), ("shop", "trophy")), limit=5)

    assert "52.34,13.09,52.68,13.76" in query
    assert '"craft"="printer"' in query
    assert '"shop"="trophy"' in query
    assert "out center 5;" in query


def test_search_parses_named_elements_with_direct_or_centre_coordinates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response([_NAMED_NODE, _NAMED_WAY_WITH_CENTER])

    results = _client(handler).search(ProductionMethod.SCREEN_PRINTING)

    assert [studio.name for studio in results] == ["Kreuzberg Foil Works", "Neukoelln Screens"]
    node, way = results
    assert node.osm_id == "node/1"
    assert node.address == "Skalitzer Str. 1 10999 Berlin"
    assert node.website == "https://example.invalid"
    assert node.osm_category == "craft=printer"
    assert way.osm_id == "way/2"
    assert way.lat == 52.51 and way.lon == 13.41
    assert way.phone == "+49 30 000"


def test_search_skips_elements_with_no_name() -> None:
    """An unnamed point is not something a person can contact - it is dropped."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response([_UNNAMED_NODE])

    results = _client(handler).search(ProductionMethod.SCREEN_PRINTING)

    assert results == []


def test_search_dedupes_by_osm_id() -> None:
    """The query has multiple clauses (node + way per tag); a real element can
    legitimately match more than one and must only be returned once."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response([_NAMED_NODE, _NAMED_NODE])

    results = _client(handler).search(ProductionMethod.SCREEN_PRINTING)

    assert len(results) == 1


def test_search_caches_within_the_ttl() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return _json_response([_NAMED_NODE])

    client = _client(handler, cache_ttl_seconds=3600)
    client.search(ProductionMethod.SCREEN_PRINTING)
    client.search(ProductionMethod.SCREEN_PRINTING)

    assert calls["count"] == 1


def test_search_does_not_cache_across_a_zero_ttl() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return _json_response([_NAMED_NODE])

    client = _client(handler, cache_ttl_seconds=0)
    client.search(ProductionMethod.SCREEN_PRINTING)
    client.search(ProductionMethod.SCREEN_PRINTING)

    assert calls["count"] == 2


def test_search_wraps_an_http_failure_as_osm_search_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    with pytest.raises(OSMSearchError):
        _client(handler).search(ProductionMethod.SCREEN_PRINTING)


def test_search_wraps_unparseable_json_as_osm_search_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(OSMSearchError):
        _client(handler).search(ProductionMethod.SCREEN_PRINTING)


def test_search_sends_the_query_as_form_data() -> None:
    """Overpass expects `data=<query>` in the POST body, not JSON."""
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return _json_response([])

    _client(handler).search(ProductionMethod.EMBROIDERY)

    body = captured["request"].read().decode()
    assert body.startswith("data=")
    assert "craft" in body and "embroiderer" in body
