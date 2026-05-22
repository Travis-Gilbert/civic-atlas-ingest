"""City-pack KPI registry loader for Phase E."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .kpi_schema import (
    DemographicBaselineRecord,
    KPIDefinitionRecord,
    KPISourceCatalogRecord,
    MultiplierRecord,
)


def load_kpi_registry(
    path: Path,
) -> tuple[tuple[KPIDefinitionRecord, ...], tuple[MultiplierRecord, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("KPI registry must be a JSON object")
    definitions = payload.get("kpi_definitions")
    multipliers = payload.get("multipliers")
    if not isinstance(definitions, list):
        raise ValueError("KPI registry requires a kpi_definitions list")
    if not isinstance(multipliers, list):
        raise ValueError("KPI registry requires a multipliers list")
    definition_records = tuple(_definition_from_json(row) for row in definitions)
    multiplier_records = tuple(_multiplier_from_json(row) for row in multipliers)
    _validate_registry_references(definition_records, multiplier_records)
    return definition_records, multiplier_records


def load_demographic_baselines(path: Path) -> tuple[DemographicBaselineRecord, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("KPI registry must be a JSON object")
    rows = payload.get("demographic_baselines", [])
    if not isinstance(rows, list):
        raise ValueError("demographic_baselines must be a list")
    return tuple(_demographic_from_json(row) for row in rows)


def load_kpi_source_catalog(path: Path) -> tuple[KPISourceCatalogRecord, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("KPI registry must be a JSON object")
    rows = payload.get("kpi_source_catalog", [])
    if not isinstance(rows, list):
        raise ValueError("kpi_source_catalog must be a list")
    return tuple(_source_catalog_from_json(row) for row in rows)


def _definition_from_json(row: Any) -> KPIDefinitionRecord:
    if not isinstance(row, dict):
        raise ValueError("KPI definition rows must be objects")
    return KPIDefinitionRecord(
        city_pack=str(row["city_pack"]),
        kpi_id=str(row["kpi_id"]),
        scope=row["scope"],
        display_name=str(row["display_name"]),
        unit=str(row["unit"]),
        formula=str(row["formula"]),
        source_note=str(row["source_note"]),
        required_multipliers=tuple(str(item) for item in row.get("required_multipliers", [])),
        description=str(row.get("description", "")),
        precision=int(row.get("precision", 2)),
        active=bool(row.get("active", True)),
        payload=dict(row.get("payload", {})),
    )


def _multiplier_from_json(row: Any) -> MultiplierRecord:
    if not isinstance(row, dict):
        raise ValueError("KPI multiplier rows must be objects")
    return MultiplierRecord(
        city_pack=str(row["city_pack"]),
        multiplier_id=str(row["multiplier_id"]),
        value=float(row["value"]),
        unit=str(row["unit"]),
        source_name=str(row["source_name"]),
        source_url=str(row["source_url"]),
        source_vintage=str(row["source_vintage"]),
        applies_to=tuple(str(item) for item in row.get("applies_to", [])),
        uncertainty_low=_optional_float(row.get("uncertainty_low")),
        uncertainty_high=_optional_float(row.get("uncertainty_high")),
        valid_from=_optional_date(row.get("valid_from")),
        valid_to=_optional_date(row.get("valid_to")),
        payload=dict(row.get("payload", {})),
    )


def _demographic_from_json(row: Any) -> DemographicBaselineRecord:
    if not isinstance(row, dict):
        raise ValueError("demographic baseline rows must be objects")
    return DemographicBaselineRecord(
        city_pack=str(row["city_pack"]),
        scope=row["scope"],
        scope_id=str(row["scope_id"]),
        metric_id=str(row["metric_id"]),
        value=float(row["value"]),
        unit=str(row["unit"]),
        source_name=str(row["source_name"]),
        source_url=str(row["source_url"]),
        source_vintage=str(row["source_vintage"]),
        observed_at=_required_date(row["observed_at"]),
        uncertainty_low=_optional_float(row.get("uncertainty_low")),
        uncertainty_high=_optional_float(row.get("uncertainty_high")),
        payload=dict(row.get("payload", {})),
    )


def _source_catalog_from_json(row: Any) -> KPISourceCatalogRecord:
    if not isinstance(row, dict):
        raise ValueError("KPI source catalog rows must be objects")
    return KPISourceCatalogRecord(
        city_pack=str(row["city_pack"]),
        source_id=str(row["source_id"]),
        name=str(row["name"]),
        steward=str(row["steward"]),
        source_url=str(row["source_url"]),
        access_pattern=row["access_pattern"],
        update_frequency=str(row["update_frequency"]),
        geography=tuple(str(item) for item in row.get("geography", [])),
        candidate_metrics=tuple(str(item) for item in row.get("candidate_metrics", [])),
        notes=str(row["notes"]),
        payload=dict(row.get("payload", {})),
    )


def _validate_registry_references(
    definitions: tuple[KPIDefinitionRecord, ...],
    multipliers: tuple[MultiplierRecord, ...],
) -> None:
    multiplier_ids = {row.multiplier_id for row in multipliers}
    for definition in definitions:
        missing = set(definition.required_multipliers) - multiplier_ids
        if missing:
            raise ValueError(
                f"{definition.kpi_id} references missing multipliers: {', '.join(sorted(missing))}"
            )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("date fields must be ISO strings")
    return date.fromisoformat(value)


def _required_date(value: Any) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise ValueError("date field is required")
    return parsed
