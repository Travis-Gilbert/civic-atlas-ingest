"""Target cities for the corpus ingestion sweep.

Priority order is set by the Phases 4-6 spec. Bounding boxes use
(min_lat, min_lon, max_lat, max_lon) in WGS84.

City selection is morphologically motivated: ten Rust-Belt cities
whose late-19th and early-20th-century housing stock overlaps with
Flint's. This is what gives the building head enough morphology
variance to learn from without bleeding into completely unrelated
styles (Spanish colonial, prairie, modernist, etc).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CityTarget:
    slug: str
    display_name: str
    state: str
    # WGS84 bbox: (min_lat, min_lon, max_lat, max_lon)
    bbox: tuple[float, float, float, float]
    # Whether assessor data is publicly downloadable. False => skip
    # the assessor lane for this city.
    assessor_public: bool


# Bounding boxes are conservative city limits, not metros.
# Verified against OSM admin_level=8 boundaries 2026-05-18.
CITY_TARGETS: tuple[CityTarget, ...] = (
    CityTarget(
        slug="detroit",
        display_name="Detroit",
        state="MI",
        bbox=(42.255, -83.288, 42.450, -82.910),
        assessor_public=True,
    ),
    CityTarget(
        slug="buffalo",
        display_name="Buffalo",
        state="NY",
        bbox=(42.825, -78.910, 42.965, -78.795),
        assessor_public=True,
    ),
    CityTarget(
        slug="cleveland",
        display_name="Cleveland",
        state="OH",
        bbox=(41.390, -81.880, 41.605, -81.530),
        assessor_public=True,
    ),
    CityTarget(
        slug="pittsburgh",
        display_name="Pittsburgh",
        state="PA",
        bbox=(40.360, -80.095, 40.501, -79.866),
        assessor_public=True,
    ),
    CityTarget(
        slug="toledo",
        display_name="Toledo",
        state="OH",
        bbox=(41.580, -83.755, 41.730, -83.430),
        assessor_public=True,
    ),
    CityTarget(
        slug="akron",
        display_name="Akron",
        state="OH",
        bbox=(40.998, -81.620, 41.165, -81.418),
        assessor_public=True,
    ),
    CityTarget(
        slug="milwaukee",
        display_name="Milwaukee",
        state="WI",
        bbox=(42.920, -88.070, 43.195, -87.860),
        assessor_public=True,
    ),
    CityTarget(
        slug="saginaw",
        display_name="Saginaw",
        state="MI",
        bbox=(43.380, -84.020, 43.475, -83.880),
        assessor_public=False,
    ),
    CityTarget(
        slug="bay-city",
        display_name="Bay City",
        state="MI",
        bbox=(43.560, -83.960, 43.640, -83.860),
        assessor_public=False,
    ),
    CityTarget(
        slug="youngstown",
        display_name="Youngstown",
        state="OH",
        bbox=(41.060, -80.730, 41.150, -80.580),
        assessor_public=True,
    ),
)


def get_target(slug: str) -> CityTarget:
    """Look up a city target by slug. Raises if not found."""
    for target in CITY_TARGETS:
        if target.slug == slug:
            return target
    raise KeyError(f"unknown city slug: {slug!r}")
