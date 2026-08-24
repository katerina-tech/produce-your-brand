"""A real, unscored business found on OpenStreetMap.

This is deliberately a *different* shape from :mod:`app.domain.supplier` - it
carries only what OpenStreetMap actually publishes (a name, a rough location,
sometimes contact details), never a capability list, MOQ or lead time, because
OpenStreetMap does not have that data. Presenting a :class:`NearbyStudio` next
to a scored :class:`~app.domain.matching.MatchResult` and inviting the same
comparison would overstate what is known about it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NearbyStudio(BaseModel):
    """One OpenStreetMap point-of-interest matched to a production method."""

    model_config = ConfigDict(extra="forbid")

    osm_id: str = Field(description="OpenStreetMap type/id, e.g. 'node/12345'.")
    name: str
    osm_category: str = Field(description="The OSM tag that matched, e.g. 'craft=embroiderer'.")
    address: str | None = Field(default=None, description="Assembled from addr:* tags, if present.")
    website: str | None = None
    phone: str | None = None
    lat: float
    lon: float
