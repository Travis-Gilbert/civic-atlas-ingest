"""Scenario-aware envelope recompute for Phase D."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .envelope_batch import EnvelopeBatchRecord, EnvelopeBatchResult, compute_current_envelope_batch
from .parcel_sources import ParcelEnvelopeInput
from .scenario_dirty_set import dirty_parcel_keys
from .scenario_schema import ScenarioReconstructionOverride, ScenarioZoningOverride
from .zoning_schema import ZoningRuleRecord


@dataclass(frozen=True)
class ScenarioInheritedEnvelope:
    parcel_key: str
    source_scenario_id: str
    envelope: EnvelopeBatchRecord


@dataclass(frozen=True)
class ScenarioEnvelopeRecomputeResult:
    scenario_id: str
    dirty_parcel_keys: tuple[str, ...]
    recomputed: EnvelopeBatchResult
    inherited: tuple[ScenarioInheritedEnvelope, ...]
    content_hash: str


def recompute_scenario_envelopes(
    *,
    scenario_id: str,
    parcels: tuple[ParcelEnvelopeInput, ...],
    rules_by_code: dict[str, ZoningRuleRecord],
    road_geometries: tuple[dict[str, object], ...],
    base_envelopes: tuple[EnvelopeBatchRecord, ...],
    zoning_overrides: tuple[ScenarioZoningOverride, ...] = (),
    reconstruction_overrides: tuple[ScenarioReconstructionOverride, ...] = (),
    base_scenario_id: str = "current",
    asset_root: Path | None = None,
) -> ScenarioEnvelopeRecomputeResult:
    dirty_keys = dirty_parcel_keys(
        parcels=parcels,
        zoning_overrides=zoning_overrides,
        reconstruction_overrides=reconstruction_overrides,
    )
    dirty_key_set = set(dirty_keys)
    scenario_parcels, scenario_rules = _apply_zoning_overrides(
        parcels=tuple(parcel for parcel in parcels if parcel.parcel_key in dirty_key_set),
        rules_by_code=rules_by_code,
        zoning_overrides=zoning_overrides,
    )
    recomputed = compute_current_envelope_batch(
        parcels=scenario_parcels,
        rules_by_code=scenario_rules,
        road_geometries=road_geometries,
        scenario_id=scenario_id,
        asset_root=asset_root,
    )
    inherited = tuple(
        ScenarioInheritedEnvelope(
            parcel_key=row.parcel_key,
            source_scenario_id=base_scenario_id,
            envelope=row,
        )
        for row in sorted(base_envelopes, key=lambda candidate: candidate.parcel_key)
        if row.parcel_key not in dirty_key_set
    )
    content_hash = _scenario_hash(
        scenario_id=scenario_id,
        dirty_keys=dirty_keys,
        recomputed=recomputed,
        inherited=inherited,
    )
    return ScenarioEnvelopeRecomputeResult(
        scenario_id=scenario_id,
        dirty_parcel_keys=dirty_keys,
        recomputed=recomputed,
        inherited=inherited,
        content_hash=content_hash,
    )


def _apply_zoning_overrides(
    *,
    parcels: tuple[ParcelEnvelopeInput, ...],
    rules_by_code: dict[str, ZoningRuleRecord],
    zoning_overrides: tuple[ScenarioZoningOverride, ...],
) -> tuple[tuple[ParcelEnvelopeInput, ...], dict[str, ZoningRuleRecord]]:
    rules_by_rule_id = {rule.rule_id: rule for rule in rules_by_code.values()}
    scenario_rules = dict(rules_by_code)
    scenario_parcels: list[ParcelEnvelopeInput] = []

    for parcel in parcels:
        base_rule = rules_by_code.get(parcel.zoning_code)
        next_parcel = parcel
        for override in zoning_overrides:
            if not _override_applies_to_parcel(override, parcel):
                continue
            if override.replacement_rule_id is not None:
                replacement = rules_by_rule_id.get(override.replacement_rule_id)
                if replacement is None:
                    raise ValueError(
                        f"unknown replacement_rule_id: {override.replacement_rule_id}"
                    )
                next_parcel = replace(parcel, zoning_code=replacement.zoning_code)
            elif base_rule is not None:
                synthetic_code = f"{parcel.zoning_code}::{override.override_id}"
                scenario_rules[synthetic_code] = _patched_rule(
                    base_rule,
                    synthetic_code=synthetic_code,
                    override=override,
                )
                next_parcel = replace(parcel, zoning_code=synthetic_code)
        scenario_parcels.append(next_parcel)

    return tuple(scenario_parcels), scenario_rules


def _override_applies_to_parcel(
    override: ScenarioZoningOverride,
    parcel: ParcelEnvelopeInput,
) -> bool:
    return parcel.parcel_key in dirty_parcel_keys(
        parcels=(parcel,),
        zoning_overrides=(override,),
    )


def _patched_rule(
    base_rule: ZoningRuleRecord,
    *,
    synthetic_code: str,
    override: ScenarioZoningOverride,
) -> ZoningRuleRecord:
    allowed_fields = {
        "max_height_m",
        "max_stories",
        "max_far",
        "max_lot_coverage",
        "min_front_setback_m",
        "min_side_setback_m",
        "min_rear_setback_m",
        "allowed_uses",
        "conditional_uses",
        "confidence",
    }
    unknown = set(override.rule_patch) - allowed_fields
    if unknown:
        raise ValueError(f"unsupported zoning rule patch fields: {', '.join(sorted(unknown))}")
    patch: dict[str, Any] = dict(override.rule_patch)
    for key in ("allowed_uses", "conditional_uses"):
        if key in patch:
            patch[key] = tuple(str(value) for value in patch[key])
    return replace(
        base_rule,
        rule_id=f"{base_rule.rule_id}::{override.override_id}",
        zoning_code=synthetic_code,
        payload={**base_rule.payload, "scenario_override_id": override.override_id},
        **patch,
    )


def _scenario_hash(
    *,
    scenario_id: str,
    dirty_keys: tuple[str, ...],
    recomputed: EnvelopeBatchResult,
    inherited: tuple[ScenarioInheritedEnvelope, ...],
) -> str:
    payload = "|".join(
        [
            scenario_id,
            ",".join(dirty_keys),
            recomputed.content_hash,
            ",".join(f"{row.parcel_key}:{row.envelope.glb_sha256}" for row in inherited),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()
