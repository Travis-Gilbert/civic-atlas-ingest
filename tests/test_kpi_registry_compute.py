from __future__ import annotations

from pathlib import Path

import pytest

from civic_atlas_ingest.kpi_compute import KPIComputationInput, compute_kpi_bundle
from civic_atlas_ingest.kpi_registry import (
    load_demographic_baselines,
    load_kpi_registry,
    load_kpi_source_catalog,
)


def test_load_kpi_registry_validates_multiplier_references() -> None:
    definitions, multipliers = load_kpi_registry(
        Path("city_packs/flint/kpi/registry-current.json")
    )

    assert {definition.kpi_id for definition in definitions} >= {
        "population_capacity",
        "tax_base_capacity",
    }
    assert {multiplier.multiplier_id for multiplier in multipliers} >= {
        "residential_people_per_unit"
    }


def test_compute_kpi_bundle_returns_uncertainty_from_multipliers() -> None:
    definitions, multipliers = load_kpi_registry(
        Path("city_packs/flint/kpi/registry-current.json")
    )
    results = compute_kpi_bundle(
        definitions=definitions,
        multipliers=multipliers,
        inputs=KPIComputationInput(
            city_pack="flint",
            scenario_id="upzone",
            scope="city",
            scope_id="flint",
            variables={
                "total_units": 10,
                "total_buildable_floor_area_m2": 1000,
                "total_headroom_floor_area_m2": 600,
                "max_height_m": 18,
            },
            source_summary="Fixture envelope aggregate.",
        ),
    )

    by_id = {row.kpi_id: row for row in results}

    assert by_id["population_capacity"].value == 21
    assert by_id["population_capacity"].uncertainty_low == 18
    assert by_id["population_capacity"].uncertainty_high == 24
    assert by_id["tax_base_capacity"].value == 42000


def test_load_demographic_baselines_preserves_source_context() -> None:
    baselines = load_demographic_baselines(
        Path("city_packs/flint/kpi/registry-current.json")
    )

    by_id = {row.metric_id: row for row in baselines}

    assert by_id["population"].source_name.startswith("ACS")
    assert by_id["population"].uncertainty_low == 76000
    assert by_id["households"].unit == "households"


def test_load_kpi_source_catalog_tracks_candidate_public_sources() -> None:
    sources = load_kpi_source_catalog(Path("city_packs/flint/kpi/registry-current.json"))
    by_id = {row.source_id: row for row in sources}

    assert by_id["epa_smart_location"].access_pattern == "public_download"
    assert "walkability_index" in by_id["epa_smart_location"].candidate_metrics
    assert by_id["hud_usps_vacancy"].access_pattern == "registration_required_api"
    assert "tract" in by_id["census_tiger_geocoder"].geography


def test_load_kpi_registry_rejects_missing_multiplier(tmp_path) -> None:
    path = tmp_path / "bad-registry.json"
    path.write_text(
        """
        {
          "kpi_definitions": [
            {
              "city_pack": "flint",
              "kpi_id": "bad",
              "scope": "city",
              "display_name": "Bad",
              "unit": "people",
              "formula": "multiplier('missing')",
              "source_note": "bad",
              "required_multipliers": ["missing"]
            }
          ],
          "multipliers": []
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing multipliers"):
        load_kpi_registry(path)
