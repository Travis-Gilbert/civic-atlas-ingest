"""Scenario-aware KPI compute helpers for Phase E."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .kpi_evaluator import FormulaEvaluationError, evaluate_formula
from .kpi_schema import KPIDefinitionRecord, KPIResultRecord, KPIScope, MultiplierRecord


@dataclass(frozen=True)
class KPIComputationInput:
    city_pack: str
    scenario_id: str
    scope: KPIScope
    scope_id: str
    variables: dict[str, float]
    source_summary: str


def compute_kpi_bundle(
    *,
    definitions: tuple[KPIDefinitionRecord, ...],
    multipliers: tuple[MultiplierRecord, ...],
    inputs: KPIComputationInput,
) -> tuple[KPIResultRecord, ...]:
    multiplier_lookup = {row.multiplier_id: row for row in multipliers}
    rows: list[KPIResultRecord] = []
    for definition in definitions:
        if not definition.active or definition.scope != inputs.scope:
            continue
        value = evaluate_formula(
            definition.formula,
            variables=inputs.variables,
            functions={"multiplier": lambda key: _multiplier_value(multiplier_lookup, key)},
        )
        low, high = _uncertainty_range(
            value=value,
            definition=definition,
            multipliers=multiplier_lookup,
        )
        rows.append(
            KPIResultRecord(
                city_pack=inputs.city_pack,
                scenario_id=inputs.scenario_id,
                scope=inputs.scope,
                scope_id=inputs.scope_id,
                kpi_id=definition.kpi_id,
                value=round(value, definition.precision),
                unit=definition.unit,
                computed_at=datetime.now(UTC),
                inputs_hash=_inputs_hash(definition, inputs, multipliers),
                source_summary=inputs.source_summary,
                uncertainty_low=round(low, definition.precision) if low is not None else None,
                uncertainty_high=round(high, definition.precision) if high is not None else None,
                payload={"formula": definition.formula},
            )
        )
    return tuple(rows)


def aggregate_envelope_variables(rows: tuple[Any, ...]) -> dict[str, float]:
    total_buildable = 0.0
    total_headroom = 0.0
    total_units = 0.0
    max_height = 0.0
    for row in rows:
        envelope = getattr(row, "envelope", row)
        total_buildable += float(envelope.buildable_floor_area_m2 or 0)
        total_headroom += float(envelope.headroom_floor_area_m2 or 0)
        total_units += float(envelope.max_units_estimated or 0)
        max_height = max(max_height, float(envelope.max_height_m or 0))
    return {
        "envelope_count": float(len(rows)),
        "total_buildable_floor_area_m2": total_buildable,
        "total_headroom_floor_area_m2": total_headroom,
        "total_units": total_units,
        "max_height_m": max_height,
    }


def _multiplier_value(
    multiplier_lookup: dict[str, MultiplierRecord],
    multiplier_id: str,
) -> float:
    if multiplier_id not in multiplier_lookup:
        raise FormulaEvaluationError(f"unknown multiplier: {multiplier_id}")
    return multiplier_lookup[multiplier_id].value


def _uncertainty_range(
    *,
    value: float,
    definition: KPIDefinitionRecord,
    multipliers: dict[str, MultiplierRecord],
) -> tuple[float | None, float | None]:
    low_factor = 1.0
    high_factor = 1.0
    saw_range = False
    for multiplier_id in definition.required_multipliers:
        multiplier = multipliers[multiplier_id]
        if multiplier.uncertainty_low is None or multiplier.uncertainty_high is None:
            continue
        if multiplier.value == 0:
            continue
        low_factor *= multiplier.uncertainty_low / multiplier.value
        high_factor *= multiplier.uncertainty_high / multiplier.value
        saw_range = True
    if not saw_range:
        return None, None
    low = min(value * low_factor, value * high_factor)
    high = max(value * low_factor, value * high_factor)
    return low, high


def _inputs_hash(
    definition: KPIDefinitionRecord,
    inputs: KPIComputationInput,
    multipliers: tuple[MultiplierRecord, ...],
) -> str:
    payload = {
        "definition": definition.kpi_id,
        "formula": definition.formula,
        "multipliers": [
            {
                "id": multiplier.multiplier_id,
                "value": multiplier.value,
                "low": multiplier.uncertainty_low,
                "high": multiplier.uncertainty_high,
            }
            for multiplier in sorted(multipliers, key=lambda row: row.multiplier_id)
        ],
        "scope": inputs.scope,
        "scope_id": inputs.scope_id,
        "scenario_id": inputs.scenario_id,
        "variables": inputs.variables,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
