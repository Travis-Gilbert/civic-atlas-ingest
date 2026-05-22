"""Typed Phase D scenario records for scenario-aware envelope recompute."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

ScenarioState = Literal["draft", "published", "archived"]
ScenarioProvenance = Literal["proposed", "actual", "historical", "future"]


@dataclass(frozen=True)
class ScenarioRecord:
    city_pack: str
    scenario_id: str
    name: str
    state: ScenarioState
    provenance: ScenarioProvenance
    created_at: datetime
    created_by: str
    base_scenario_id: str | None = "current"
    description: str = ""
    published_at: datetime | None = None
    archived_at: datetime | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.scenario_id, "scenario_id")
        _require_text(self.name, "name")
        _require_text(self.created_by, "created_by")
        if self.base_scenario_id is not None:
            _require_text(self.base_scenario_id, "base_scenario_id")
            if self.base_scenario_id == self.scenario_id:
                raise ValueError("base_scenario_id cannot equal scenario_id")
        if self.state == "published" and self.published_at is None:
            raise ValueError("published scenarios require published_at")
        if self.state == "archived" and self.archived_at is None:
            raise ValueError("archived scenarios require archived_at")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("tags cannot contain blank values")


@dataclass(frozen=True)
class ScenarioZoningOverride:
    city_pack: str
    scenario_id: str
    override_id: str
    geometry: dict[str, Any]
    created_at: datetime
    created_by: str
    replacement_rule_id: str | None = None
    rule_patch: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.scenario_id, "scenario_id")
        _require_text(self.override_id, "override_id")
        _require_text(self.created_by, "created_by")
        _require_geojson_geometry(self.geometry)
        if self.replacement_rule_id is not None:
            _require_text(self.replacement_rule_id, "replacement_rule_id")
        has_replacement = self.replacement_rule_id is not None
        has_patch = bool(self.rule_patch)
        if has_replacement == has_patch:
            raise ValueError("exactly one of replacement_rule_id or rule_patch is required")


@dataclass(frozen=True)
class ScenarioReconstructionOverride:
    city_pack: str
    scenario_id: str
    override_id: str
    parcel_key: str
    provenance: ScenarioProvenance
    confidence: float
    created_at: datetime
    created_by: str
    reconstruction_spec_id: str | None = None
    reconstruction_spec_version: int | None = None
    reconstruction_spec: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.scenario_id, "scenario_id")
        _require_text(self.override_id, "override_id")
        _require_text(self.parcel_key, "parcel_key")
        _require_text(self.created_by, "created_by")
        _require_unit_interval(self.confidence, "confidence")
        has_ref = (
            self.reconstruction_spec_id is not None
            or self.reconstruction_spec_version is not None
        )
        if has_ref:
            if self.reconstruction_spec_id is None or self.reconstruction_spec_version is None:
                raise ValueError(
                    "reconstruction_spec_id and reconstruction_spec_version "
                    "must be provided together"
                )
            _require_text(self.reconstruction_spec_id, "reconstruction_spec_id")
            if self.reconstruction_spec_version <= 0:
                raise ValueError("reconstruction_spec_version must be positive")
        has_payload = bool(self.reconstruction_spec)
        if has_ref == has_payload:
            raise ValueError("exactly one of reconstruction spec reference or payload is required")


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_unit_interval(value: float, field_name: str) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")


def _require_geojson_geometry(geometry: dict[str, Any]) -> None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("geometry must be a Polygon or MultiPolygon GeoJSON geometry")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("geometry coordinates must be a non-empty list")
