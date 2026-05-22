from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from civic_atlas_ingest.scenario_dirty_set import dirty_parcel_keys
from civic_atlas_ingest.scenario_schema import (
    ScenarioReconstructionOverride,
    ScenarioZoningOverride,
)


@dataclass(frozen=True)
class ParcelFixture:
    parcel_key: str
    geometry: dict[str, Any]


def square(xmin: float, ymin: float, xmax: float, ymax: float) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [xmin, ymin],
                [xmax, ymin],
                [xmax, ymax],
                [xmin, ymax],
                [xmin, ymin],
            ]
        ],
    }


def test_dirty_parcels_include_zoning_intersections_and_reconstruction_targets() -> None:
    now = datetime.now(UTC)
    parcels = (
        ParcelFixture(parcel_key="parcel-a", geometry=square(0, 0, 1, 1)),
        ParcelFixture(parcel_key="parcel-b", geometry=square(2, 0, 3, 1)),
        ParcelFixture(parcel_key="parcel-c", geometry=square(4, 0, 5, 1)),
    )
    zoning_override = ScenarioZoningOverride(
        city_pack="flint",
        scenario_id="upzone",
        override_id="touch-a-b",
        geometry=square(0.5, 0.25, 2.5, 0.75),
        created_at=now,
        created_by="planner",
        rule_patch={"max_height_m": 18.0},
    )
    reconstruction_override = ScenarioReconstructionOverride(
        city_pack="flint",
        scenario_id="upzone",
        override_id="new-building-c",
        parcel_key="parcel-c",
        provenance="future",
        confidence=0.75,
        created_at=now,
        created_by="planner",
        reconstruction_spec={"massings": [{"height_m": 9.0}]},
    )

    dirty = dirty_parcel_keys(
        parcels=parcels,
        zoning_overrides=(zoning_override,),
        reconstruction_overrides=(reconstruction_override,),
    )

    assert dirty == ("parcel-a", "parcel-b", "parcel-c")


def test_dirty_parcels_are_deterministic_and_deduplicated() -> None:
    now = datetime.now(UTC)
    parcels = (
        ParcelFixture(parcel_key="parcel-b", geometry=square(2, 0, 3, 1)),
        ParcelFixture(parcel_key="parcel-a", geometry=square(0, 0, 1, 1)),
    )
    zoning_override = ScenarioZoningOverride(
        city_pack="flint",
        scenario_id="upzone",
        override_id="replace-a",
        geometry=square(0.2, 0.2, 0.8, 0.8),
        created_at=now,
        created_by="planner",
        rule_patch={"max_height_m": 18.0},
    )
    reconstruction_override = ScenarioReconstructionOverride(
        city_pack="flint",
        scenario_id="upzone",
        override_id="new-building-a",
        parcel_key="parcel-a",
        provenance="future",
        confidence=0.75,
        created_at=now,
        created_by="planner",
        reconstruction_spec={"massings": [{"height_m": 9.0}]},
    )

    dirty = dirty_parcel_keys(
        parcels=parcels,
        zoning_overrides=(zoning_override,),
        reconstruction_overrides=(reconstruction_override,),
    )

    assert dirty == ("parcel-a",)
