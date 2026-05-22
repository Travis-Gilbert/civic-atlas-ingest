"""Typed Phase C zoning/envelope records for ingest outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

SourceKind = Literal["html", "pdf", "arcgis-rest-metadata", "arcgis-rest-query", "geojson"]


@dataclass(frozen=True)
class ZoningSourceSnapshotRecord:
    city_pack: str
    source_key: str
    source_url: str
    source_kind: SourceKind
    retrieved_at: datetime
    content_sha256: str
    byte_count: int
    final_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.source_key, "source_key")
        _require_text(self.source_url, "source_url")
        if len(self.content_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.content_sha256
        ):
            raise ValueError("content_sha256 must be a lowercase 64-character SHA-256 hex digest")
        if self.byte_count < 0:
            raise ValueError("byte_count must be non-negative")


@dataclass(frozen=True)
class ZoningRuleRecord:
    city_pack: str
    rule_id: str
    zoning_code: str
    display_name: str = ""
    max_height_m: float | None = None
    max_stories: float | None = None
    max_far: float | None = None
    max_lot_coverage: float | None = None
    min_front_setback_m: float | None = None
    min_side_setback_m: float | None = None
    min_rear_setback_m: float | None = None
    allowed_uses: tuple[str, ...] = ()
    conditional_uses: tuple[str, ...] = ()
    source_key: str | None = None
    source_section: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    confidence: float = 0.7
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.rule_id, "rule_id")
        _require_text(self.zoning_code, "zoning_code")
        _require_non_negative_optional(self.max_height_m, "max_height_m")
        _require_non_negative_optional(self.max_stories, "max_stories")
        _require_non_negative_optional(self.max_far, "max_far")
        _require_unit_interval_optional(self.max_lot_coverage, "max_lot_coverage")
        _require_non_negative_optional(self.min_front_setback_m, "min_front_setback_m")
        _require_non_negative_optional(self.min_side_setback_m, "min_side_setback_m")
        _require_non_negative_optional(self.min_rear_setback_m, "min_rear_setback_m")
        _require_unit_interval(self.confidence, "confidence")
        _require_valid_dates(self.valid_from, self.valid_to)
        if any(not use.strip() for use in self.allowed_uses):
            raise ValueError("allowed_uses cannot contain blank values")
        if any(not use.strip() for use in self.conditional_uses):
            raise ValueError("conditional_uses cannot contain blank values")


@dataclass(frozen=True)
class ZoningBoundarySeed:
    city_pack: str
    scenario_id: str
    parcel_key: str
    zoning_code: str
    geometry: dict[str, Any]
    pid_dash: str | None = None
    land_use: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.scenario_id, "scenario_id")
        _require_text(self.parcel_key, "parcel_key")
        _require_text(self.zoning_code, "zoning_code")
        _require_geojson_geometry(self.geometry)
        _require_valid_dates(self.valid_from, self.valid_to)


@dataclass(frozen=True)
class BuildableEnvelopeSeed:
    city_pack: str
    scenario_id: str
    parcel_key: str
    zoning_code: str
    base_geometry: dict[str, Any]
    envelope_geometry: dict[str, Any]
    max_height_m: float
    max_stories: float | None = None
    max_far: float | None = None
    buildable_floor_area_m2: float | None = None
    existing_floor_area_m2: float | None = None
    headroom_floor_area_m2: float | None = None
    max_units_estimated: int | None = None
    binding_constraint: str = ""
    asset_uri: str | None = None
    content_hash: str | None = None
    warnings: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.city_pack, "city_pack")
        _require_text(self.scenario_id, "scenario_id")
        _require_text(self.parcel_key, "parcel_key")
        _require_text(self.zoning_code, "zoning_code")
        _require_geojson_geometry(self.base_geometry)
        _require_geojson_geometry(self.envelope_geometry)
        _require_non_negative(self.max_height_m, "max_height_m")
        _require_non_negative_optional(self.max_stories, "max_stories")
        _require_non_negative_optional(self.max_far, "max_far")
        _require_non_negative_optional(self.buildable_floor_area_m2, "buildable_floor_area_m2")
        _require_non_negative_optional(self.existing_floor_area_m2, "existing_floor_area_m2")
        _require_non_negative_optional(self.headroom_floor_area_m2, "headroom_floor_area_m2")
        _require_non_negative_int_optional(self.max_units_estimated, "max_units_estimated")


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_non_negative(value: float, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _require_non_negative_optional(value: float | None, field_name: str) -> None:
    if value is not None:
        _require_non_negative(value, field_name)


def _require_non_negative_int_optional(value: int | None, field_name: str) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _require_unit_interval(value: float, field_name: str) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")


def _require_unit_interval_optional(value: float | None, field_name: str) -> None:
    if value is not None:
        _require_unit_interval(value, field_name)


def _require_valid_dates(valid_from: date | None, valid_to: date | None) -> None:
    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise ValueError("valid_to cannot be before valid_from")


def _require_geojson_geometry(geometry: dict[str, Any]) -> None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("geometry must be a Polygon or MultiPolygon GeoJSON geometry")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("geometry coordinates must be a non-empty list")
