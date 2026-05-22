from __future__ import annotations

from pathlib import Path

from civic_atlas_ingest.zoning_ingest import (
    current_flint_zoning_rules,
    feet,
    write_current_flint_zoning_rules,
)


def test_current_flint_rules_cover_all_current_district_codes() -> None:
    rules = current_flint_zoning_rules()
    codes = {rule.zoning_code for rule in rules}

    assert len(rules) == 18
    assert codes == {
        "GN-1",
        "GN-2",
        "TN-1",
        "TN-2",
        "MR-1",
        "MR-2",
        "MR-3",
        "NC",
        "CC",
        "DE",
        "DC",
        "CE",
        "PC",
        "GI-2",
        "IC",
        "UC",
        "GI-1",
        "OS",
    }


def test_residential_rules_include_height_coverage_and_setbacks() -> None:
    rule = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}["GN-1"]

    assert rule.max_height_m == feet(35)
    assert rule.max_stories == 2.5
    assert rule.max_lot_coverage == 0.30
    assert rule.min_front_setback_m == feet(25)
    assert rule.min_side_setback_m == feet(15)
    assert rule.min_rear_setback_m == feet(25)
    assert "residential" in rule.allowed_uses
    assert "Table 50-24A" in (rule.source_section or "")


def test_downtown_core_rule_keeps_maximum_building_height() -> None:
    rule = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}["DC"]

    assert rule.max_height_m == feet(125)
    assert rule.max_lot_coverage is None
    assert "mixed_use" in rule.allowed_uses
    assert rule.confidence >= 0.8


def test_ambiguous_rules_have_lower_confidence_and_notes() -> None:
    rules = {rule.zoning_code: rule for rule in current_flint_zoning_rules()}

    assert rules["GI-1"].confidence < 0.8
    assert rules["UC"].confidence < 0.8
    assert rules["GI-1"].payload["notes"]
    assert rules["UC"].payload["notes"]


def test_write_current_flint_zoning_rules(tmp_path: Path) -> None:
    output_path = tmp_path / "rules-current.json"
    payload = write_current_flint_zoning_rules(output_path)

    assert output_path.exists()
    assert payload["rule_count"] == 18
    assert payload["city_pack"] == "flint"
    assert payload["rules"][0]["valid_from"] == "2025-12-07"
    assert payload["rules"][0]["source_key"] == "flint-zoning-code-2025-v1-5-1"
