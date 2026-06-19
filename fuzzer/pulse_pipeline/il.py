from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any


@dataclass(frozen=True)
class Expr:
    """Small integer expression language for Pulse arithmetic terms."""

    kind: str
    value: str | int | Fraction | None = None
    args: tuple["Expr", ...] = ()

    def vars(self) -> set[str]:
        if self.kind == "var":
            assert isinstance(self.value, str)
            return {self.value}
        result: set[str] = set()
        for arg in self.args:
            result.update(arg.vars())
        return result


@dataclass(frozen=True)
class Predicate:
    """Boolean predicate over integer expressions."""

    op: str
    left: Expr
    right: Expr
    source: str = ""

    def vars(self) -> set[str]:
        return self.left.vars() | self.right.vars()


@dataclass(frozen=True)
class ConstraintSet:
    """Preconditions and bad postconditions for one unknown call target."""

    pre: tuple[Predicate, ...]
    bad_post: tuple[Predicate, ...]


CONST_ZERO = Expr("const", Fraction(0))
CONST_ONE = Expr("const", Fraction(1))


def const(value: int | Fraction) -> Expr:
    return Expr("const", Fraction(value))


def var(name: str) -> Expr:
    return Expr("var", name)


def unary(kind: str, expr: Expr) -> Expr:
    if kind == "neg" and expr.kind == "const":
        assert isinstance(expr.value, Fraction)
        return const(-expr.value)
    return Expr(kind, args=(expr,))


def binary(kind: str, left: Expr, right: Expr) -> Expr:
    if left.kind == "const" and right.kind == "const":
        assert isinstance(left.value, Fraction)
        assert isinstance(right.value, Fraction)
        if kind == "add":
            return const(left.value + right.value)
        if kind == "sub":
            return const(left.value - right.value)
        if kind == "mul":
            return const(left.value * right.value)
        if kind == "div" and right.value != 0:
            return const(left.value // right.value)
        if kind == "mod" and right.value != 0:
            return const(left.value % right.value)
    return Expr(kind, args=(left, right))


def rename_expr(expr: Expr, names: dict[str, str]) -> Expr:
    """Rename Pulse variables into user-facing or auxiliary Z3 variable names."""

    if expr.kind == "var":
        assert isinstance(expr.value, str)
        return var(names.get(expr.value, f"pulse_{expr.value}"))
    if not expr.args:
        return expr
    return Expr(expr.kind, expr.value, tuple(rename_expr(arg, names) for arg in expr.args))


def expr_to_json(expr: Expr) -> Any:
    if expr.kind == "const":
        assert isinstance(expr.value, Fraction)
        if expr.value.denominator == 1:
            return {"const": expr.value.numerator}
        return {"const": f"{expr.value.numerator}/{expr.value.denominator}"}
    if expr.kind == "var":
        return {"var": expr.value}
    return {expr.kind: [expr_to_json(arg) for arg in expr.args]}


def predicate_to_json(pred: Predicate) -> dict[str, Any]:
    return {
        "op": pred.op,
        "left": expr_to_json(pred.left),
        "right": expr_to_json(pred.right),
        "source": pred.source,
    }


def render_expr(expr: Expr, parent_prec: int = 0) -> str:
    prec = {
        "add": 1,
        "sub": 1,
        "mul": 2,
        "div": 2,
        "mod": 2,
        "neg": 3,
        "const": 4,
        "var": 4,
    }.get(expr.kind, 4)

    if expr.kind == "const":
        assert isinstance(expr.value, Fraction)
        if expr.value.denominator == 1:
            text = str(expr.value.numerator)
        else:
            text = f"{expr.value.numerator}/{expr.value.denominator}"
    elif expr.kind == "var":
        text = str(expr.value)
    elif expr.kind == "neg":
        text = f"-{render_expr(expr.args[0], prec)}"
    elif expr.kind in {"add", "sub", "mul", "div", "mod"}:
        op = {"add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%"}[expr.kind]
        text = f" {op} ".join(render_expr(arg, prec) for arg in expr.args)
    else:
        text = str(expr.value)

    if prec < parent_prec:
        return f"({text})"
    return text


def render_predicate(pred: Predicate) -> str:
    return f"{render_expr(pred.left)} {pred.op} {render_expr(pred.right)}"

