"""Scenario envelope delta helpers for Phase D compare mode."""

from __future__ import annotations

from dataclasses import dataclass

from .envelope_batch import EnvelopeBatchRecord


@dataclass(frozen=True)
class ScenarioEnvelopeDelta:
    parcel_key: str
    base_scenario_id: str | None
    target_scenario_id: str | None
    max_height_delta_m: float | None
    floor_area_delta_m2: float | None
    unit_delta: int | None
    binding_constraint_changed: bool


def diff_envelope_records(
    *,
    base_scenario_id: str,
    target_scenario_id: str,
    base_rows: tuple[EnvelopeBatchRecord, ...],
    target_rows: tuple[EnvelopeBatchRecord, ...],
) -> tuple[ScenarioEnvelopeDelta, ...]:
    base_by_key = {row.parcel_key: row for row in base_rows}
    target_by_key = {row.parcel_key: row for row in target_rows}
    parcel_keys = sorted(set(base_by_key) | set(target_by_key))
    deltas: list[ScenarioEnvelopeDelta] = []

    for parcel_key in parcel_keys:
        base = base_by_key.get(parcel_key)
        target = target_by_key.get(parcel_key)
        if base is None or target is None:
            deltas.append(
                ScenarioEnvelopeDelta(
                    parcel_key=parcel_key,
                    base_scenario_id=base_scenario_id if base is not None else None,
                    target_scenario_id=target_scenario_id if target is not None else None,
                    max_height_delta_m=None,
                    floor_area_delta_m2=None,
                    unit_delta=None,
                    binding_constraint_changed=True,
                )
            )
            continue

        height_delta = target.envelope.max_height_m - base.envelope.max_height_m
        floor_delta = _optional_delta(
            base.envelope.buildable_floor_area_m2,
            target.envelope.buildable_floor_area_m2,
        )
        unit_delta = _optional_int_delta(
            base.envelope.max_units_estimated,
            target.envelope.max_units_estimated,
        )
        binding_changed = (
            target.envelope.binding_constraint != base.envelope.binding_constraint
        )
        if (
            abs(height_delta) < 0.0001
            and (floor_delta is None or abs(floor_delta) < 0.0001)
            and (unit_delta is None or unit_delta == 0)
            and not binding_changed
        ):
            continue
        deltas.append(
            ScenarioEnvelopeDelta(
                parcel_key=parcel_key,
                base_scenario_id=base_scenario_id,
                target_scenario_id=target_scenario_id,
                max_height_delta_m=round(height_delta, 4),
                floor_area_delta_m2=round(floor_delta, 4) if floor_delta is not None else None,
                unit_delta=unit_delta,
                binding_constraint_changed=binding_changed,
            )
        )

    return tuple(deltas)


def _optional_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return right - left


def _optional_int_delta(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return right - left
