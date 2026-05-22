"""Dirty parcel detection for Phase D scenario overrides."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .scenario_schema import ScenarioReconstructionOverride, ScenarioZoningOverride


class ParcelLike(Protocol):
    parcel_key: str
    geometry: Mapping[str, Any]


def dirty_parcel_keys(
    *,
    parcels: Iterable[ParcelLike],
    zoning_overrides: Iterable[ScenarioZoningOverride] = (),
    reconstruction_overrides: Iterable[ScenarioReconstructionOverride] = (),
) -> tuple[str, ...]:
    dirty: set[str] = set()
    parcel_shapes = tuple(
        (parcel.parcel_key, _shape_from_geojson(parcel.geometry, f"parcel {parcel.parcel_key}"))
        for parcel in parcels
    )

    for override in zoning_overrides:
        override_shape = _shape_from_geojson(
            override.geometry,
            f"zoning override {override.override_id}",
        )
        for parcel_key, parcel_shape in parcel_shapes:
            if _intersects_or_touches(parcel_shape, override_shape):
                dirty.add(parcel_key)

    for override in reconstruction_overrides:
        dirty.add(override.parcel_key)

    return tuple(sorted(dirty))


def _intersects_or_touches(left: BaseGeometry, right: BaseGeometry) -> bool:
    return left.intersects(right) or left.touches(right)


def _shape_from_geojson(geometry: Mapping[str, Any], label: str) -> BaseGeometry:
    try:
        geometry_shape = shape(dict(geometry))
    except Exception as exc:
        raise ValueError(f"{label} has invalid GeoJSON geometry") from exc
    if geometry_shape.is_empty:
        raise ValueError(f"{label} geometry cannot be empty")
    return geometry_shape
