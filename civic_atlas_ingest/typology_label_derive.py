"""
Derive TypologyClass labels from the joined parcel + OSM data.

The label hierarchy (most-specific wins) and source-tracking:

  1. STRONG signal — OSM `building` tag in CIVIC_BUILDING_TAGS, OR
     OSM `name` matching CIVIC_NAME_PATTERNS → CIVIC.
     label_source = "osm_civic"
  2. STRONG signal — parcel `Use_Type` ∈ {Residential, Commercial,
     Industrial} → corresponding TypologyClass.
     label_source = "parcel"
  3. WEAK fallback — when no parcel match (the parcel join missed
     this footprint), check the OSM `building` tag against
     PRIMARY_WEAK_TAG_MAP for residential/commercial/industrial
     signals. This recovers ~600 of the ~4,400 parcel-less buildings
     for training. Noisier than parcel labels — the classifier
     learns to weight them differently via the `label_source`
     feature column.
     label_source = "osm_weak"
  4. UNKNOWN — no signal in either source.
     label_source = "unknown"

CIVIC overrides parcel class because civic buildings often sit on
parcels classified by their nominal use (e.g., a church building on a
residential parcel before the exempt-status flag was applied). The
OSM tag is the more reliable civic signal.

MIXED_USE is defined in the TypologyClass enum but NOT predicted in
v0.1.x. The current Flint parcel data has no clean mixed-use signal
(zoning codes CC / DC / UC suggest downtown but don't distinguish
mixed-use from pure commercial). v0.2.0 may add a mixed-use class once
a better signal source exists.

Label-source tracking matters because the WEAK fallback is intrinsically
noisier than the STRONG parcel/civic signals — `building=apartments`
in OSM is reliable for residential-multi but lower-confidence than the
assessor's parcel Use_Type. The classifier gets `label_source` as a
feature so it can downweight weak-labeled rows implicitly.

The output is consumed by typology_train (as training labels with a
label_source side-channel) and by typology_infer (as the inference
target for buildings without a training row, falling through to the
classifier).
"""

from __future__ import annotations

import re
from typing import Any

from civic_atlas_ingest.typology_schema import TypologyClass


# OSM building tag values that signal CIVIC use directly. Most are
# religious; the rest cover schools, hospitals, government facilities.
LabelSource = str  # Literal["parcel", "osm_civic", "osm_weak", "unknown"]


# OSM `building` tag values that map to a non-civic primary class.
# Used ONLY as a weak fallback when the parcel join misses the
# footprint. Conservative coverage — only tags with unambiguous use
# semantics. `yes` is excluded (it's the catch-all "this is a
# building" tag, no class signal).
PRIMARY_WEAK_TAG_MAP: dict[str, TypologyClass] = {
    "house": TypologyClass.RESIDENTIAL,
    "detached": TypologyClass.RESIDENTIAL,
    "semidetached_house": TypologyClass.RESIDENTIAL,
    "terrace": TypologyClass.RESIDENTIAL,
    "residential": TypologyClass.RESIDENTIAL,
    "apartments": TypologyClass.RESIDENTIAL,
    "bungalow": TypologyClass.RESIDENTIAL,
    "dormitory": TypologyClass.RESIDENTIAL,
    "commercial": TypologyClass.COMMERCIAL,
    "retail": TypologyClass.COMMERCIAL,
    "office": TypologyClass.COMMERCIAL,
    "hotel": TypologyClass.COMMERCIAL,
    "supermarket": TypologyClass.COMMERCIAL,
    "kiosk": TypologyClass.COMMERCIAL,
    "industrial": TypologyClass.INDUSTRIAL,
    "warehouse": TypologyClass.INDUSTRIAL,
    "factory": TypologyClass.INDUSTRIAL,
    "manufacture": TypologyClass.INDUSTRIAL,
    "hangar": TypologyClass.INDUSTRIAL,
}


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


def _osm_weak_primary_label(osm_props: dict[str, Any]) -> TypologyClass | None:
    """Return the OSM-tag-derived primary-class label, or None if no signal."""
    building_tag_raw = osm_props.get("building")
    if not isinstance(building_tag_raw, str):
        return None
    tag = building_tag_raw.strip().lower()
    return PRIMARY_WEAK_TAG_MAP.get(tag)


def derive_label(
    osm_props: dict[str, Any],
    parcel_use_type: str | None,
) -> tuple[TypologyClass, LabelSource]:
    """
    Derive a single (TypologyClass, label_source) pair for one building.

    Resolution order:
      1. OSM-tag-derived CIVIC overrides parcel-class signal.
      2. Parcel Use_Type drives residential/commercial/industrial.
      3. No parcel match → OSM-tag weak fallback for primary classes.
      4. No signal anywhere → UNKNOWN.

    The label_source string is consumed by feature extraction as a
    side-channel so the classifier can implicitly downweight weak-
    labeled training rows.
    """
    if _osm_signals_civic(osm_props):
        return TypologyClass.CIVIC, "osm_civic"
    parcel_class = _parcel_use_to_class(parcel_use_type)
    if parcel_class is not TypologyClass.UNKNOWN:
        return parcel_class, "parcel"
    # Parcel join missed — try the OSM weak fallback.
    weak = _osm_weak_primary_label(osm_props)
    if weak is not None:
        return weak, "osm_weak"
    return TypologyClass.UNKNOWN, "unknown"


def derive_labels_for_joined(
    joined_buildings: Any,
) -> tuple[list[TypologyClass], list[LabelSource]]:
    """
    Apply derive_label() across every row of a joined GeoDataFrame
    produced by typology_join.join_buildings_to_parcels.

    Returns (labels, label_sources), both aligned to the input
    DataFrame's row order.
    """
    labels: list[TypologyClass] = []
    sources: list[LabelSource] = []
    for _, row in joined_buildings.iterrows():
        osm_props = {
            "building": row.get("building"),
            "name": row.get("name"),
            "use": row.get("use"),
        }
        label, source = derive_label(osm_props, row.get("parcel_use_type"))
        labels.append(label)
        sources.append(source)
    return labels, sources
