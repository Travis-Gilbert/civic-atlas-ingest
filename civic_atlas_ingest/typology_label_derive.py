"""
Derive TypologyClass labels from the joined parcel + OSM data.

The label hierarchy (most-specific wins):

  1. OSM `building` tag of {church, chapel, cathedral, mosque, temple,
     synagogue, school, university, college, hospital, civic, public,
     government, library, museum, fire_station} → CIVIC
  2. OSM `name` matching civic regex (Bishop Airport, City Hall,
     Public Library, Hospital, School, Church, etc.) → CIVIC
  3. Parcel `Use_Type` == "Industrial" (Michigan 300s) → INDUSTRIAL
  4. Parcel `Use_Type` == "Commercial" (Michigan 200s) → COMMERCIAL
  5. Parcel `Use_Type` == "Residential" (Michigan 400s) → RESIDENTIAL
  6. Everything else → UNKNOWN (no parcel match, or parcel class 1/2
     "Ref. Real", or building outside Flint's public parcel extent)

CIVIC overrides parcel class because civic buildings often sit on
parcels classified by their nominal use (e.g., a church building on a
residential parcel before the exempt-status flag was applied). The
OSM tag is the more reliable civic signal.

MIXED_USE is defined in the TypologyClass enum but NOT predicted in
v0.1.0. The current Flint parcel data has no clean mixed-use signal
(zoning codes CC / DC / UC suggest downtown but don't distinguish
mixed-use from pure commercial). v0.2.0 may add a mixed-use class once
a better signal source exists (rooftop solar / use-permit data /
hand-labels).

The output is consumed by typology_train (as training labels) and by
typology_infer (as the inference target for buildings without a
training row, falling through to the classifier).
"""

from __future__ import annotations

import re
from typing import Any

from civic_atlas_ingest.typology_schema import TypologyClass


# OSM building tag values that signal CIVIC use directly. Most are
# religious; the rest cover schools, hospitals, government facilities.
CIVIC_BUILDING_TAGS: frozenset[str] = frozenset(
    {
        "church",
        "chapel",
        "cathedral",
        "mosque",
        "temple",
        "synagogue",
        "school",
        "university",
        "college",
        "kindergarten",
        "hospital",
        "clinic",
        "civic",
        "public",
        "government",
        "library",
        "museum",
        "fire_station",
        "police",
        "courthouse",
        "monastery",
        "convent",
        "presbytery",
    }
)

# Regex over OSM `name` field for civic uses where the building tag is
# generic (`yes`). Conservative — false positives on partial matches
# would mislabel residential buildings, so each pattern is anchored on
# strong civic-only vocabulary.
CIVIC_NAME_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(?:city hall|courthouse|fire station|police station|police department)\b",
        r"\b(?:public library|carnegie library)\b",
        r"\b(?:hospital|medical center|health center|clinic)\b",
        r"\b(?:elementary school|middle school|high school|academy|college|university)\b",
        r"\b(?:church|cathedral|temple|synagogue|mosque|chapel)\b",
        r"\b(?:museum|conservatory)\b",
        r"\b(?:airport|airfield)\b",  # Bishop International Airport
        r"\bymca\b|\bywca\b",
    ]
)


def _osm_signals_civic(osm_props: dict[str, Any]) -> bool:
    """True when OSM tags / name indicate a civic building."""
    building_tag_raw = osm_props.get("building")
    building_tag = (
        building_tag_raw.strip().lower() if isinstance(building_tag_raw, str) else ""
    )
    if building_tag in CIVIC_BUILDING_TAGS:
        return True
    name = osm_props.get("name")
    if not isinstance(name, str) or not name.strip():
        return False
    for pattern in CIVIC_NAME_PATTERNS:
        if pattern.search(name):
            return True
    return False


def _parcel_use_to_class(use_type: Any) -> TypologyClass:
    """Map parcel Use_Type to TypologyClass for the 3 primary classes."""
    if not isinstance(use_type, str) or not use_type.strip():
        return TypologyClass.UNKNOWN
    normalized = use_type.strip().lower()
    if normalized == "residential":
        return TypologyClass.RESIDENTIAL
    if normalized == "commercial":
        return TypologyClass.COMMERCIAL
    if normalized == "industrial":
        return TypologyClass.INDUSTRIAL
    # "Ref. Real" and any future codes fall through.
    return TypologyClass.UNKNOWN


def derive_label(
    osm_props: dict[str, Any],
    parcel_use_type: str | None,
) -> TypologyClass:
    """
    Derive a single TypologyClass label for one building.

    OSM-tag-derived CIVIC overrides parcel-class signal. Otherwise the
    parcel Use_Type drives the class. No parcel match → UNKNOWN.
    """
    if _osm_signals_civic(osm_props):
        return TypologyClass.CIVIC
    return _parcel_use_to_class(parcel_use_type)


def derive_labels_for_joined(joined_buildings: Any) -> list[TypologyClass]:
    """
    Apply derive_label() across every row of a joined GeoDataFrame
    produced by typology_join.join_buildings_to_parcels.

    Returns a list of TypologyClass aligned to joined_buildings.index.
    """
    labels: list[TypologyClass] = []
    for _, row in joined_buildings.iterrows():
        osm_props = {
            "building": row.get("building"),
            "name": row.get("name"),
            "use": row.get("use"),
        }
        label = derive_label(osm_props, row.get("parcel_use_type"))
        labels.append(label)
    return labels
