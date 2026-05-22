from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from civic_atlas_ingest.scenario_schema import (
    ScenarioReconstructionOverride,
    ScenarioRecord,
    ScenarioZoningOverride,
)

POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-83.7, 43.0],
            [-83.69, 43.0],
            [-83.69, 43.01],
            [-83.7, 43.01],
            [-83.7, 43.0],
        ]
    ],
}


def test_scenario_record_round_trips_core_fields() -> None:
    published_at = datetime.now(UTC)
    scenario = ScenarioRecord(
        city_pack="flint",
        scenario_id="riverfront-upzone",
        name="Riverfront upzone",
        state="published",
        provenance="future",
        created_at=published_at,
        created_by="planner",
        base_scenario_id="current",
        published_at=published_at,
        tags=("zoning", "capacity"),
    )

    payload = asdict(scenario)

    assert payload["scenario_id"] == "riverfront-upzone"
    assert payload["base_scenario_id"] == "current"


def test_scenario_record_rejects_self_base() -> None:
    with pytest.raises(ValueError, match="base_scenario_id"):
        ScenarioRecord(
            city_pack="flint",
            scenario_id="same",
            name="Same",
            state="draft",
            provenance="future",
            created_at=datetime.now(UTC),
            created_by="planner",
            base_scenario_id="same",
        )


def test_zoning_override_requires_one_override_pattern() -> None:
    now = datetime.now(UTC)
    replacement = ScenarioZoningOverride(
        city_pack="flint",
        scenario_id="riverfront-upzone",
        override_id="replace-gn1-with-gn2",
        geometry=POLYGON,
        created_at=now,
        created_by="planner",
        replacement_rule_id="flint-gn-2-current",
    )

    assert replacement.replacement_rule_id == "flint-gn-2-current"

    with pytest.raises(ValueError, match="exactly one"):
        ScenarioZoningOverride(
            city_pack="flint",
            scenario_id="riverfront-upzone",
            override_id="ambiguous",
            geometry=POLYGON,
            created_at=now,
            created_by="planner",
            replacement_rule_id="flint-gn-2-current",
            rule_patch={"max_height_m": 18.0},
        )


def test_reconstruction_override_accepts_embedded_future_spec() -> None:
    override = ScenarioReconstructionOverride(
        city_pack="flint",
        scenario_id="lost-flint-comparison",
        override_id="proposed-corner-building",
        parcel_key="40-01-154-012",
        provenance="future",
        confidence=0.65,
        created_at=datetime.now(UTC),
        created_by="planner",
        reconstruction_spec={"massings": [{"height_m": 12.0}]},
    )

    assert override.reconstruction_spec["massings"][0]["height_m"] == 12.0


def test_reconstruction_override_rejects_partial_spec_reference() -> None:
    with pytest.raises(ValueError, match="must be provided together"):
        ScenarioReconstructionOverride(
            city_pack="flint",
            scenario_id="lost-flint-comparison",
            override_id="bad-ref",
            parcel_key="40-01-154-012",
            provenance="future",
            confidence=0.65,
            created_at=datetime.now(UTC),
            created_by="planner",
            reconstruction_spec_id="spec-1",
        )
