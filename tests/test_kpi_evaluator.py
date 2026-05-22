from __future__ import annotations

import pytest

from civic_atlas_ingest.kpi_evaluator import FormulaEvaluationError, evaluate_formula


def test_evaluate_formula_uses_variables_and_whitelisted_functions() -> None:
    multipliers = {"residential_people_per_unit": 2.2}

    def multiplier(multiplier_id: str) -> float:
        return multipliers[multiplier_id]

    value = evaluate_formula(
        "max_units_estimated * multiplier('residential_people_per_unit')",
        variables={"max_units_estimated": 10},
        functions={"multiplier": multiplier},
    )

    assert value == 22.0


def test_evaluate_formula_allows_safe_conditionals() -> None:
    value = evaluate_formula(
        "headroom_floor_area_m2 / 80 if headroom_floor_area_m2 > 0 else 0",
        variables={"headroom_floor_area_m2": 320},
    )

    assert value == 4.0


@pytest.mark.parametrize(
    "formula",
    [
        "__import__('os').system('echo no')",
        "(1).__class__",
        "[value for value in values]",
        "open('secret.txt')",
    ],
)
def test_evaluate_formula_rejects_hostile_python_syntax(formula: str) -> None:
    with pytest.raises(FormulaEvaluationError):
        evaluate_formula(formula, variables={"values": [1, 2, 3]})


def test_evaluate_formula_rejects_non_numeric_results() -> None:
    with pytest.raises(FormulaEvaluationError, match="must produce a number"):
        evaluate_formula("'not-a-number'", variables={})


def test_evaluate_formula_rejects_division_by_zero() -> None:
    with pytest.raises(FormulaEvaluationError, match="division by zero"):
        evaluate_formula("10 / denominator", variables={"denominator": 0})


def test_evaluate_formula_rejects_unbounded_exponents() -> None:
    with pytest.raises(FormulaEvaluationError, match="exponent"):
        evaluate_formula("10 ** 1000", variables={})
