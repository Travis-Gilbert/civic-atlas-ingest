"""Typed Phase E KPI and multiplier records."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

KPIScope = Literal["parcel", "block", "ward", "city"]
KPIAccessPattern = Literal[
    "public_api",
    "public_download",
    "registration_required_api",
]


@dataclass(frozen=True)
class MultiplierRecord:
    city_pack: str
    multiplier_id: str
    value: float
    unit: str
    source_name: str
    source_url: str
    source_vintage: str
    applies_to: tuple[str, ...] = ()
    uncertainty_low: float | None = None
    uncertainty_high: float | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.multiplier_id, "multiplier_id")
        _require_finite_number(self.value, "value")
        _require_text(self.unit, "unit")
        _require_text(self.source_name, "source_name")
        _require_text(self.source_url, "source_url")
        _require_text(self.source_vintage, "source_vintage")
        _require_range(self.uncertainty_low, self.uncertainty_high, "uncertainty")
        _require_valid_dates(self.valid_from, self.valid_to)
        if any(not target.strip() for target in self.applies_to):
            raise ValueError("applies_to cannot contain blank values")


@dataclass(frozen=True)
class KPIDefinitionRecord:
    city_pack: str
    kpi_id: str
    scope: KPIScope
    display_name: str
    unit: str
    formula: str
    source_note: str
    required_multipliers: tuple[str, ...] = ()
    description: str = ""
    precision: int = 2
    active: bool = True
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.kpi_id, "kpi_id")
        _require_text(self.display_name, "display_name")
        _require_text(self.unit, "unit")
        _require_text(self.formula, "formula")
        _require_text(self.source_note, "source_note")
        if self.precision < 0 or self.precision > 8:
            raise ValueError("precision must be between 0 and 8")
        if any(not multiplier.strip() for multiplier in self.required_multipliers):
            raise ValueError("required_multipliers cannot contain blank values")


@dataclass(frozen=True)
class DemographicBaselineRecord:
    city_pack: str
    scope: KPIScope
    scope_id: str
    metric_id: str
    value: float
    unit: str
    source_name: str
    source_url: str
    source_vintage: str
    observed_at: date
    uncertainty_low: float | None = None
    uncertainty_high: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.scope_id, "scope_id")
        _require_text(self.metric_id, "metric_id")
        _require_finite_number(self.value, "value")
        _require_text(self.unit, "unit")
        _require_text(self.source_name, "source_name")
        _require_text(self.source_url, "source_url")
        _require_text(self.source_vintage, "source_vintage")
        _require_range(self.uncertainty_low, self.uncertainty_high, "uncertainty")


@dataclass(frozen=True)
class KPISourceCatalogRecord:
    city_pack: str
    source_id: str
    name: str
    steward: str
    source_url: str
    access_pattern: KPIAccessPattern
    update_frequency: str
    geography: tuple[str, ...]
    candidate_metrics: tuple[str, ...]
    notes: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.source_id, "source_id")
        _require_text(self.name, "name")
        _require_text(self.steward, "steward")
        _require_text(self.source_url, "source_url")
        _require_text(self.update_frequency, "update_frequency")
        _require_text(self.notes, "notes")
        if any(not geography.strip() for geography in self.geography):
            raise ValueError("geography cannot contain blank values")
        if any(not metric.strip() for metric in self.candidate_metrics):
            raise ValueError("candidate_metrics cannot contain blank values")


@dataclass(frozen=True)
class KPIResultRecord:
    city_pack: str
    scenario_id: str
    scope: KPIScope
    scope_id: str
    kpi_id: str
    value: float
    unit: str
    computed_at: datetime
    inputs_hash: str
    source_summary: str
    uncertainty_low: float | None = None
    uncertainty_high: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.scenario_id, "scenario_id")
        _require_text(self.scope_id, "scope_id")
        _require_text(self.kpi_id, "kpi_id")
        _require_finite_number(self.value, "value")
        _require_text(self.unit, "unit")
        _require_text(self.source_summary, "source_summary")
        if len(self.inputs_hash) != 64 or any(
            c not in "0123456789abcdef" for c in self.inputs_hash
        ):
            raise ValueError("inputs_hash must be a lowercase 64-character SHA-256 hex digest")
        _require_range(self.uncertainty_low, self.uncertainty_high, "uncertainty")
        if self.uncertainty_low is not None and self.value < self.uncertainty_low:
            raise ValueError("value cannot be below uncertainty_low")
        if self.uncertainty_high is not None and self.value > self.uncertainty_high:
            raise ValueError("value cannot be above uncertainty_high")


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_finite_number(value: float, field_name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _require_range(low: float | None, high: float | None, field_name: str) -> None:
    if low is not None:
        _require_finite_number(low, f"{field_name}_low")
    if high is not None:
        _require_finite_number(high, f"{field_name}_high")
    if low is not None and high is not None and high < low:
        raise ValueError(f"{field_name}_high cannot be below {field_name}_low")


def _require_valid_dates(valid_from: date | None, valid_to: date | None) -> None:
    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise ValueError("valid_to cannot be before valid_from")
