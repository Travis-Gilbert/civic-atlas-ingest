"""Flint zoning ordinance seed extraction for Phase C."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .zoning_schema import ZoningRuleRecord
from .zoning_sources import FLINT_ZONING_CODE_URL, FLINT_ZONING_USE_TABLE_URL

CITY_PACK = "flint"
CURRENT_RULE_VALID_FROM = date(2025, 12, 7)
USE_TABLE_VALID_FROM = date(2026, 3, 5)
FT_TO_M = 0.3048


def feet(value: float) -> float:
    return round(value * FT_TO_M, 4)


def current_flint_zoning_rules() -> tuple[ZoningRuleRecord, ...]:
    """Return source-backed current Flint zoning district rules.

    These records are a deterministic transcription of the dimensional standard
    tables in the current zoning code. Use permissions are intentionally broad
    Phase A categories until a full Comprehensive Use Table parser lands.
    """
    rules = [
        _rule(
            "GN-1",
            "Green Neighborhood-Low Density",
            source_section="Table 50-24A Bulk and Site Standards: GN Districts",
            max_height_ft=35,
            max_stories=2.5,
            max_lot_coverage=0.30,
            front_ft=25,
            side_ft=15,
            rear_ft=25,
            allowed=("residential", "civic", "vacant_or_auxiliary"),
            conditional=("commercial",),
            confidence=0.9,
            notes={"coverage_exception": "non-residential use then 80%"},
        ),
        _rule(
            "GN-2",
            "Green Neighborhood-Medium Density",
            source_section="Table 50-24A Bulk and Site Standards: GN Districts",
            max_height_ft=35,
            max_stories=2.5,
            max_lot_coverage=0.60,
            front_ft=25,
            side_ft=5,
            rear_ft=25,
            allowed=("residential", "civic", "vacant_or_auxiliary"),
            conditional=("commercial",),
            confidence=0.85,
            notes={
                "coverage_exception": "non-residential use then 80%",
                "setback_exception": (
                    "non-residential use has larger side setbacks and smaller rear setback"
                ),
            },
        ),
        _rule(
            "TN-1",
            "Traditional Neighborhood-Low Density",
            source_section="Table 50-24B Bulk and Site Standards: TN Districts",
            max_height_ft=35,
            max_stories=2.5,
            max_lot_coverage=0.45,
            front_ft=30,
            side_ft=10,
            rear_ft=35,
            allowed=("residential", "civic", "vacant_or_auxiliary"),
            conditional=("commercial",),
        ),
        _rule(
            "TN-2",
            "Traditional Neighborhood-Medium Density",
            source_section="Table 50-24B Bulk and Site Standards: TN Districts",
            max_height_ft=35,
            max_stories=2.5,
            max_lot_coverage=0.60,
            front_ft=20,
            side_ft=5,
            rear_ft=25,
            allowed=("residential", "civic", "vacant_or_auxiliary"),
            conditional=("commercial",),
        ),
        _rule(
            "MR-1",
            "Mixed-Residential-Low Density",
            source_section="Table 50-24C Bulk and Site Standards: MR-1 District",
            max_height_ft=35,
            max_stories=2.5,
            max_lot_coverage=0.70,
            front_ft=20,
            side_ft=0,
            rear_ft=25,
            allowed=("residential", "mixed_use", "civic", "vacant_or_auxiliary"),
            conditional=("commercial",),
            confidence=0.85,
            notes={
                "variant": (
                    "detached/two-family side setback is 2 ft; attached residential "
                    "side setback is 0 ft"
                )
            },
        ),
        _rule(
            "MR-2",
            "Mixed-Residential-Medium Density",
            source_section="Table 50-24D Bulk Site Standards: MR-2 and MR-3 Districts",
            max_height_ft=45,
            max_stories=4,
            max_lot_coverage=0.80,
            front_ft=0,
            side_ft=0,
            rear_ft=20,
            allowed=("residential", "mixed_use", "commercial", "civic"),
            conditional=("industrial",),
            confidence=0.8,
            notes={"variant": "lower residential forms are limited to 2.5 stories / 35 ft"},
        ),
        _rule(
            "MR-3",
            "Mixed-Residential-High Density",
            source_section="Table 50-24D Bulk Site Standards: MR-2 and MR-3 Districts",
            max_height_ft=100,
            max_stories=None,
            max_lot_coverage=0.90,
            front_ft=0,
            side_ft=0,
            rear_ft=20,
            allowed=("residential", "mixed_use", "commercial", "civic"),
            conditional=("industrial",),
            confidence=0.8,
            notes={"height_note": "table specifies max 100 ft and minimum 2 stories"},
        ),
        _rule(
            "NC",
            "Neighborhood Center",
            source_section="Table 50-31A Lot and Bulk Standards: NC and CC Districts",
            max_height_ft=50,
            max_stories=4,
            front_ft=0,
            side_ft=0,
            rear_ft=20,
            allowed=("commercial", "mixed_use", "residential", "civic"),
            conditional=("industrial",),
            confidence=0.8,
            notes={
                "setback_exception": (
                    "interior side setback is 10 ft in wider lots against residential use"
                )
            },
        ),
        _rule(
            "CC",
            "City Corridor",
            source_section="Table 50-31A Lot and Bulk Standards: NC and CC Districts",
            max_height_ft=50,
            max_stories=4,
            front_ft=0,
            side_ft=0,
            rear_ft=20,
            allowed=("commercial", "mixed_use", "residential", "civic"),
            conditional=("industrial",),
            confidence=0.75,
            notes={
                "variant": (
                    "lots 140 ft deep or more have larger max front/corner and rear setbacks"
                )
            },
        ),
        _rule(
            "DE",
            "Downtown-Edge",
            source_section="Table 50-31B Lot and Bulk Standards: D-E and D-C Districts",
            max_height_ft=75,
            front_ft=0,
            side_ft=0,
            rear_ft=0,
            allowed=("commercial", "mixed_use", "residential", "civic"),
            conditional=("industrial",),
            confidence=0.8,
            notes={"setback_exception": "side/rear setbacks apply when against TN or MR district"},
        ),
        _rule(
            "DC",
            "Downtown-Core",
            source_section="Table 50-31B Lot and Bulk Standards: D-E and D-C Districts",
            max_height_ft=125,
            front_ft=0,
            side_ft=0,
            rear_ft=0,
            allowed=("commercial", "mixed_use", "residential", "civic"),
            conditional=("industrial",),
            confidence=0.85,
            notes={"height_note": "table specifies max 125 ft and min 35 ft"},
        ),
        _rule(
            "CE",
            "Commerce and Employment",
            source_section="Table 50-38 Employment Districts Bulk and Site Standards",
            front_ft=10,
            side_ft=0,
            rear_ft=0,
            allowed=("commercial", "industrial", "civic"),
            conditional=("mixed_use",),
            confidence=0.75,
            notes={"setback_exception": "larger setbacks apply abutting residential development"},
        ),
        _rule(
            "PC",
            "Production Center",
            source_section="Table 50-38 Employment Districts Bulk and Site Standards",
            front_ft=30,
            side_ft=0,
            rear_ft=0,
            allowed=("industrial", "commercial", "civic"),
            conditional=("mixed_use",),
            confidence=0.75,
            notes={"setback_exception": "larger setbacks apply abutting residential development"},
        ),
        _rule(
            "GI-2",
            "Green Innovation-High Intensity",
            source_section="Table 50-38 Employment Districts Bulk and Site Standards",
            front_ft=30,
            side_ft=30,
            rear_ft=25,
            allowed=("industrial", "commercial", "civic"),
            conditional=("mixed_use", "residential"),
            confidence=0.75,
        ),
        _rule(
            "IC",
            "Institutional Campus",
            source_section="Table 50-44 Institutional Districts Bulk and Site Standards",
            max_height_ft=70,
            front_ft=0,
            side_ft=0,
            rear_ft=0,
            allowed=("civic", "residential", "commercial"),
            conditional=("mixed_use",),
            confidence=0.8,
            notes={
                "setback_exception": (
                    "larger setbacks apply abutting or fronting on residential development"
                )
            },
        ),
        _rule(
            "UC",
            "University Core",
            source_section="Table 50-44 Institutional Districts Bulk and Site Standards",
            max_height_ft=70,
            front_ft=10,
            side_ft=0,
            rear_ft=0,
            allowed=("civic", "residential", "mixed_use", "commercial"),
            conditional=("industrial",),
            confidence=0.7,
            notes={
                "variant": (
                    "district-wide height is 60 ft; University Avenue frontage may allow "
                    "70 ft with 2-story minimum"
                ),
                "setback_exception": (
                    "height and setbacks reduce near TN/GN or residential ground-floor adjacency"
                ),
            },
        ),
        _rule(
            "GI-1",
            "Green Innovation-Medium Intensity",
            source_section="Table 50-44 Institutional Districts Bulk and Site Standards",
            max_height_ft=35,
            max_stories=2.5,
            max_lot_coverage=0.30,
            front_ft=25,
            side_ft=15,
            rear_ft=25,
            allowed=("industrial", "commercial", "civic", "residential"),
            conditional=("mixed_use",),
            confidence=0.65,
            notes={
                "variant": (
                    "GI-1 has residential and industrial rows; industrial row height is "
                    "not clearly extractable from PDF text"
                )
            },
        ),
        _rule(
            "OS",
            "Open Space",
            source_section="Table 50-50 Open Space District Bulk and Site Standards",
            max_lot_coverage=0.35,
            front_ft=0,
            side_ft=15,
            rear_ft=30,
            allowed=("civic", "vacant_or_auxiliary", "commercial"),
            conditional=("industrial",),
            confidence=0.8,
        ),
    ]
    return tuple(rules)


def rules_to_jsonable(rules: tuple[ZoningRuleRecord, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule in rules:
        row = asdict(rule)
        row["valid_from"] = rule.valid_from.isoformat() if rule.valid_from else None
        row["valid_to"] = rule.valid_to.isoformat() if rule.valid_to else None
        rows.append(row)
    return rows


def write_current_flint_zoning_rules(output_path: Path) -> dict[str, Any]:
    rules = current_flint_zoning_rules()
    payload = {
        "city_pack": CITY_PACK,
        "source_url": FLINT_ZONING_CODE_URL,
        "use_table_url": FLINT_ZONING_USE_TABLE_URL,
        "valid_from": CURRENT_RULE_VALID_FROM.isoformat(),
        "use_table_valid_from": USE_TABLE_VALID_FROM.isoformat(),
        "rule_count": len(rules),
        "rules": rules_to_jsonable(rules),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _rule(
    code: str,
    name: str,
    *,
    source_section: str,
    allowed: tuple[str, ...],
    front_ft: float,
    side_ft: float,
    rear_ft: float,
    max_height_ft: float | None = None,
    max_stories: float | None = None,
    max_lot_coverage: float | None = None,
    conditional: tuple[str, ...] = (),
    confidence: float = 0.9,
    notes: dict[str, Any] | None = None,
) -> ZoningRuleRecord:
    payload = {
        "source_url": FLINT_ZONING_CODE_URL,
        "use_table_url": FLINT_ZONING_USE_TABLE_URL,
        "source_basis": "manual transcription from pdftotext extracted ordinance tables",
        "use_policy": (
            "allowed_uses and conditional_uses are Phase A typology hints, not a legal "
            "replacement for the Comprehensive Use Table P/S/A/ARU semantics"
        ),
        "notes": notes or {},
    }
    return ZoningRuleRecord(
        city_pack=CITY_PACK,
        rule_id=f"us-mi-flint-{code.lower()}-current",
        zoning_code=code,
        display_name=name,
        max_height_m=feet(max_height_ft) if max_height_ft is not None else None,
        max_stories=max_stories,
        max_lot_coverage=max_lot_coverage,
        min_front_setback_m=feet(front_ft),
        min_side_setback_m=feet(side_ft),
        min_rear_setback_m=feet(rear_ft),
        allowed_uses=allowed,
        conditional_uses=conditional,
        source_key="flint-zoning-code-2025-v1-5-1",
        source_section=source_section,
        valid_from=CURRENT_RULE_VALID_FROM,
        confidence=confidence,
        payload=payload,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write current Flint zoning rule seed rows.")
    parser.add_argument(
        "--output",
        default="city_packs/flint/zoning/rules-current.json",
        help="Rule seed path to write.",
    )
    args = parser.parse_args(argv)
    payload = write_current_flint_zoning_rules(Path(args.output))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
