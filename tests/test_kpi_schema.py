from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime

import pytest

from civic_atlas_ingest.kpi_schema import (
    DemographicBaselineRecord,
    KPIDefinitionRecord,
    KPIResultRecord,
    KPISourceCatalogRecord,
    MultiplierRecord,
)


def test_multiplier_record_requires_source_and_uncertainty_order() -> None:
    multiplier = MultiplierRecord(
        city_pack="flint",
        multiplier_id="residential_people_per_unit",
        value=2.1,
        unit="people/unit",
        source_name="ACS 5-year",
        source_url="https://www.census.gov/programs-surveys/acs",
        source_vintage="2024",
        applies_to=("residential",),
        uncertainty_low=1.8,
        uncertainty_high=2.4,
        valid_from=date(2024, 1, 1),
    )

    assert asdict(multiplier)["unit"] == "people/unit"

    with pytest.raises(ValueError, match="uncertainty_high"):
        MultiplierRecord(
            city_pack="flint",
            multiplier_id="bad",
            value=2.1,
            unit="people/unit",
            source_name="ACS 5-year",
            source_url="https://www.census.gov/programs-surveys/acs",
            source_vintage="2024",
            uncertainty_low=2.5,
            uncertainty_high=2.4,
        )


def test_kpi_definition_keeps_formula_as_data() -> None:
    definition = KPIDefinitionRecord(
        city_pack="flint",
        kpi_id="population_capacity",
        scope="parcel",
        display_name="Population capacity",
        unit="people",
        formula="max_units_estimated * multiplier('residential_people_per_unit')",
        source_note="Uses local envelope units and ACS household-size assumptions.",
        required_multipliers=("residential_people_per_unit",),
    )

    assert definition.formula.startswith("max_units_estimated")


def test_demographic_baseline_validates_source_context() -> None:
    baseline = DemographicBaselineRecord(
        city_pack="flint",
        scope="ward",
        scope_id="ward-1",
        metric_id="population",
        value=9400,
        unit="people",
        source_name="ACS 5-year",
        source_url="https://www.census.gov/programs-surveys/acs",
        source_vintage="2024",
        observed_at=date(2024, 12, 31),
    )

    assert baseline.scope_id == "ward-1"


def test_kpi_source_catalog_record_requires_metric_and_geography_names() -> None:
    source = KPISourceCatalogRecord(
        city_pack="flint",
        source_id="epa_smart_location",
        name="Smart Location Database",
        steward="U.S. EPA",
        source_url="https://www.epa.gov/smartgrowth/smart-location-mapping",
        access_pattern="public_download",
        update_frequency="periodic",
        geography=("block_group",),
        candidate_metrics=("walkability_index",),
        notes="Useful built-environment source.",
    )

    assert source.candidate_metrics == ("walkability_index",)

    with pytest.raises(ValueError, match="candidate_metrics"):
        KPISourceCatalogRecord(
            city_pack="flint",
            source_id="bad",
            name="Bad",
            steward="Bad",
            source_url="https://example.com",
            access_pattern="public_api",
            update_frequency="annual",
            geography=("tract",),
            candidate_metrics=("",),
            notes="bad",
        )


def test_kpi_result_requires_hash_and_uncertainty_bracket() -> None:
    result = KPIResultRecord(
        city_pack="flint",
        scenario_id="current",
        scope="city",
        scope_id="flint",
        kpi_id="population_capacity",
        value=125000,
        unit="people",
        computed_at=datetime.now(UTC),
        inputs_hash="a" * 64,
        source_summary="Envelope units multiplied by ACS household-size assumption.",
        uncertainty_low=110000,
        uncertainty_high=140000,
    )

    assert result.inputs_hash == "a" * 64

    with pytest.raises(ValueError, match="inputs_hash"):
        KPIResultRecord(
            city_pack="flint",
            scenario_id="current",
            scope="city",
            scope_id="flint",
            kpi_id="population_capacity",
            value=125000,
            unit="people",
            computed_at=datetime.now(UTC),
            inputs_hash="bad",
            source_summary="Envelope units multiplied by ACS household-size assumption.",
        )
