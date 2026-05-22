"""
Spatial join between OSM building footprints and Flint parcels.

For each OSM building, finds the parcel whose polygon contains the
building's centroid. Returns a joined GeoDataFrame carrying every OSM
property + the parcel's Prop_Class, Use_Type, Zoning, and a few derived
geometric features (parcel area, building/parcel area ratio).

Parcel source: civic_atlas_ingest/scripts/fetch_flint_parcels.py output.
OSM source: src/data/open-flint-atlas/fixtures/osm-buildings.json
in the Open-Flint-Atlas-main-release repo.

Why centroid-in-parcel rather than max-overlap-area:
  - Most Flint buildings are wholly contained in one parcel.
  - Centroid join is O(N log M) vs O(N*M) for pairwise overlap.
  - For the small minority that straddle parcels, the centroid still
    picks a deterministic single parcel.
  - When the building footprint has no parcel containing its centroid
    (rural / right-of-way / data gaps), the row gets parcel_class=None
    and propagates as TypologyClass.UNKNOWN downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


def load_parcels(parcels_geojson_path: Path) -> gpd.GeoDataFrame:
    """Load the Flint parcel layer, keep only the fields typology cares about."""
    parcels = gpd.read_file(parcels_geojson_path)
    keep = ["Prop_Class", "Use_Type", "Zoning", "Owner_Name", "Prop_Add", "geometry"]
    available = [c for c in keep if c in parcels.columns]
    return parcels[available].copy()


def load_osm_buildings(osm_geojson_path: Path) -> gpd.GeoDataFrame:
    """Load OSM building footprints from the Open-Flint-Atlas fixture."""
    return gpd.read_file(osm_geojson_path)


def join_buildings_to_parcels(
    buildings: gpd.GeoDataFrame,
    parcels: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Spatial join: each building gets the parcel attributes for the
    parcel containing its centroid.

    Returns a GeoDataFrame with the original building geometry + every
    parcel field (prefixed `parcel_`), plus:
      - `parcel_area_m2`: area of the matched parcel (or NaN if no match)
      - `parcel_area_ratio`: building area / parcel area (or NaN)
      - `has_parcel_join`: True when a parcel was matched

    Both layers must be in compatible CRSes; this function reprojects
    to EPSG:3857 (Web Mercator) for the join because the spatial
    operations are cheaper and the parcel data was published in that
    projection.
    """
    if buildings.crs is None:
        buildings = buildings.set_crs("EPSG:4326")
    if parcels.crs is None:
        parcels = parcels.set_crs("EPSG:4326")
    buildings_m = buildings.to_crs(epsg=3857)
    parcels_m = parcels.to_crs(epsg=3857)

    # Use centroids for the join. Save original geometry for return.
    original_geom = buildings_m["geometry"]
    building_area_m2 = buildings_m["geometry"].area
    centroids = buildings_m.copy()
    centroids["geometry"] = buildings_m["geometry"].centroid

    parcels_for_join = parcels_m.rename(
        columns={
            "Prop_Class": "parcel_prop_class",
            "Use_Type": "parcel_use_type",
            "Zoning": "parcel_zoning",
            "Owner_Name": "parcel_owner",
            "Prop_Add": "parcel_address",
        }
    ).copy()
    parcels_for_join["parcel_area_m2"] = parcels_for_join["geometry"].area

    joined = gpd.sjoin(
        centroids,
        parcels_for_join,
        how="left",
        predicate="within",
    )
    # sjoin can produce duplicate rows when a centroid falls on a parcel
    # boundary and matches multiple parcels. Keep the first match
    # deterministically.
    joined = joined[~joined.index.duplicated(keep="first")].copy()

    # Restore original building geometry (not the centroid).
    joined["geometry"] = original_geom
    joined["building_area_m2"] = building_area_m2.values
    joined["has_parcel_join"] = joined["parcel_prop_class"].notna()
    joined["parcel_area_ratio"] = (
        joined["building_area_m2"] / joined["parcel_area_m2"]
    ).where(joined["has_parcel_join"])

    # Drop sjoin's internal index column
    joined = joined.drop(columns=[c for c in joined.columns if c.startswith("index_")])

    return joined.to_crs(epsg=4326)


def join_report(joined: gpd.GeoDataFrame) -> dict[str, Any]:
    """Quick sanity stats on the join result."""
    total = len(joined)
    matched = int(joined["has_parcel_join"].sum())
    return {
        "total_buildings": total,
        "matched_to_parcel": matched,
        "match_rate": matched / total if total else 0.0,
        "unmatched": total - matched,
        "parcel_class_distribution": joined["parcel_prop_class"]
        .value_counts(dropna=False)
        .to_dict(),
        "parcel_use_type_distribution": joined["parcel_use_type"]
        .value_counts(dropna=False)
        .to_dict(),
    }
