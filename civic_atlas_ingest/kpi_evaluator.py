"""Locked-down formula evaluator for Phase E KPI definitions."""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Mapping
from typing import Any

Number = int | float
FormulaFunction = Callable[..., Any]
MAX_FORMULA_LENGTH = 1_000
MAX_ABS_EXPONENT = 12.0

DEFAULT_FUNCTIONS: dict[str, FormulaFunction] = {
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
    "max": max,
    "min": min,
    "round": round,
    "sqrt": math.sqrt,
}


class FormulaEvaluationError(ValueError):
    """Raised when a KPI formula uses syntax outside the allowed DSL."""


def evaluate_formula(
    expression: str,
    *,
    variables: Mapping[str, Any],
    functions: Mapping[str, FormulaFunction] | None = None,
) -> float:
    if not expression.strip():
        raise FormulaEvaluationError("formula expression must be non-empty")
    if len(expression) > MAX_FORMULA_LENGTH:
        raise FormulaEvaluationError("formula expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FormulaEvaluationError("formula expression is invalid") from exc
    evaluator = _SafeFormulaEvaluator(
        variables=variables,
        functions={**DEFAULT_FUNCTIONS, **(functions or {})},
    )
    value = evaluator.visit(tree)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FormulaEvaluationError("formula must produce a number")
    result = float(value)
    if not math.isfinite(result):
        raise FormulaEvaluationError("formula result must be finite")
    return result


class _SafeFormulaEvaluator(ast.NodeVisitor):
    def __init__(
        self,
        *,
        variables: Mapping[str, Any],
        functions: Mapping[str, FormulaFunction],
    ) -> None:
        self._variables = variables
        self._functions = functions

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, bool | int | float | str):
            return node.value
        raise FormulaEvaluationError("formula constants must be strings or numbers")

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id.startswith("__"):
            raise FormulaEvaluationError("dunder names are not allowed")
        if node.id not in self._variables:
            raise FormulaEvaluationError(f"unknown variable: {node.id}")
        return self._variables[node.id]

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -_require_number(operand)
        if isinstance(node.op, ast.UAdd):
            return _require_number(operand)
        if isinstance(node.op, ast.Not):
            return not bool(operand)
        raise FormulaEvaluationError("unsupported unary operation")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = _require_number(self.visit(node.left))
        right = _require_number(self.visit(node.right))
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise FormulaEvaluationError("division by zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_ABS_EXPONENT:
                raise FormulaEvaluationError("exponent is too large")
            return left**right
        raise FormulaEvaluationError("unsupported binary operation")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        values = [bool(self.visit(value)) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise FormulaEvaluationError("unsupported boolean operation")

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            right = self.visit(comparator)
            if isinstance(operator, ast.Eq):
                passed = left == right
            elif isinstance(operator, ast.NotEq):
                passed = left != right
            elif isinstance(operator, ast.Lt):
                passed = _require_number(left) < _require_number(right)
            elif isinstance(operator, ast.LtE):
                passed = _require_number(left) <= _require_number(right)
            elif isinstance(operator, ast.Gt):
                passed = _require_number(left) > _require_number(right)
            elif isinstance(operator, ast.GtE):
                passed = _require_number(left) >= _require_number(right)
            else:
                raise FormulaEvaluationError("unsupported comparison operation")
            if not passed:
                return False
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        return self.visit(node.body if bool(self.visit(node.test)) else node.orelse)

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise FormulaEvaluationError("only named function calls are allowed")
        function_name = node.func.id
        if function_name.startswith("__") or function_name not in self._functions:
            raise FormulaEvaluationError(f"unknown function: {function_name}")
        args = [self.visit(arg) for arg in node.args]
        kwargs: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise FormulaEvaluationError("expanded keyword arguments are not allowed")
            kwargs[keyword.arg] = self.visit(keyword.value)
        try:
            return self._functions[function_name](*args, **kwargs)
        except Exception as exc:
            raise FormulaEvaluationError(f"function failed: {function_name}") from exc

    def generic_visit(self, node: ast.AST) -> Any:
        raise FormulaEvaluationError(f"unsupported formula syntax: {type(node).__name__}")


def _require_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FormulaEvaluationError("operation requires a number")
    return float(value)
