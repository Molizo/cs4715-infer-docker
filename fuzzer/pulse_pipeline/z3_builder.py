from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import z3

from .il import ConstraintSet, Expr, Predicate, render_predicate
from .pulse_to_il import ExtractedTarget


@dataclass(frozen=True)
class SolverCheck:
    name: str
    status: str
    constraints: tuple[str, ...]
    model: dict[str, str]

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "constraints": list(self.constraints),
            "model": self.model,
        }


@dataclass(frozen=True)
class Z3TargetResult:
    issue_key: str
    status: str
    variables: tuple[str, ...]
    checks: dict[str, SolverCheck]
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "variables": list(self.variables),
            "checks": {name: check.to_json() for name, check in self.checks.items()},
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


def issue_key(target: ExtractedTarget) -> str:
    issue = target.issue
    callee = target.callee or "<unknown>"
    return f"{issue.procedure}:{issue.line}:{issue.column}:{callee}"


def z3_const(value: Fraction) -> z3.ArithRef:
    if value.denominator == 1:
        return z3.IntVal(value.numerator)
    return z3.Q(value.numerator, value.denominator)


def expr_to_z3(expr: Expr, env: dict[str, z3.ArithRef]) -> z3.ArithRef:
    if expr.kind == "const":
        assert isinstance(expr.value, Fraction)
        return z3_const(expr.value)
    if expr.kind == "var":
        assert isinstance(expr.value, str)
        env.setdefault(expr.value, z3.Int(expr.value))
        return env[expr.value]
    if expr.kind == "neg":
        return -expr_to_z3(expr.args[0], env)
    if expr.kind == "add":
        return expr_to_z3(expr.args[0], env) + expr_to_z3(expr.args[1], env)
    if expr.kind == "sub":
        return expr_to_z3(expr.args[0], env) - expr_to_z3(expr.args[1], env)
    if expr.kind == "mul":
        return expr_to_z3(expr.args[0], env) * expr_to_z3(expr.args[1], env)
    if expr.kind == "div":
        return expr_to_z3(expr.args[0], env) / expr_to_z3(expr.args[1], env)
    if expr.kind == "mod":
        return expr_to_z3(expr.args[0], env) % expr_to_z3(expr.args[1], env)
    raise ValueError(f"unsupported IL expression kind: {expr.kind}")


def predicate_to_z3(predicate: Predicate, env: dict[str, z3.ArithRef]) -> z3.BoolRef:
    left = expr_to_z3(predicate.left, env)
    right = expr_to_z3(predicate.right, env)
    if predicate.op == "==":
        return left == right
    if predicate.op == "!=":
        return left != right
    if predicate.op == "<":
        return left < right
    if predicate.op == "<=":
        return left <= right
    if predicate.op == ">":
        return left > right
    if predicate.op == ">=":
        return left >= right
    raise ValueError(f"unsupported IL predicate operator: {predicate.op}")


def predicates_to_z3(
    predicates: tuple[Predicate, ...], env: dict[str, z3.ArithRef]
) -> list[z3.BoolRef]:
    return [predicate_to_z3(predicate, env) for predicate in predicates]


def model_to_json(model: z3.ModelRef, env: dict[str, z3.ArithRef]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in sorted(env):
        result[name] = str(model.eval(env[name], model_completion=True))
    return result


def check_solver(
    name: str, constraints: list[z3.BoolRef], rendered_constraints: tuple[str, ...], env: dict[str, z3.ArithRef]
) -> SolverCheck:
    solver = z3.Solver()
    solver.add(*constraints)
    status = solver.check()
    model = model_to_json(solver.model(), env) if status == z3.sat else {}
    return SolverCheck(
        name=name,
        status=str(status),
        constraints=rendered_constraints,
        model=model,
    )


def all_variables(constraints: ConstraintSet, target: ExtractedTarget) -> tuple[str, ...]:
    names: set[str] = set()
    for predicate in (*constraints.pre, *constraints.bad_post):
        names.update(predicate.vars())
    if target.call_boundary is not None:
        names.update(target.call_boundary.input_variables.values())
        names.update(target.call_boundary.output_variables.values())
    return tuple(sorted(names))


def build_for_target(target: ExtractedTarget) -> Z3TargetResult:
    key = issue_key(target)
    if target.status != "supported" or target.constraints is None:
        return Z3TargetResult(
            issue_key=key,
            status="unsupported",
            variables=(),
            checks={},
            reason=target.reason or "target was not extracted",
        )

    constraints = target.constraints
    env: dict[str, z3.ArithRef] = {}
    pre_z3 = predicates_to_z3(constraints.pre, env)
    bad_z3 = predicates_to_z3(constraints.bad_post, env)
    if target.call_boundary is not None:
        for name in (
            *target.call_boundary.input_variables.values(),
            *target.call_boundary.output_variables.values(),
        ):
            env.setdefault(name, z3.Int(name))
    pre_rendered = tuple(render_predicate(predicate) for predicate in constraints.pre)
    bad_rendered = tuple(render_predicate(predicate) for predicate in constraints.bad_post)
    checks = {
        "pre": check_solver("pre", pre_z3, pre_rendered, env),
        "pre_and_bad": check_solver(
            "pre_and_bad", [*pre_z3, *bad_z3], (*pre_rendered, *bad_rendered), env
        ),
    }
    return Z3TargetResult(
        issue_key=key,
        status="z3_ready",
        variables=all_variables(constraints, target),
        checks=checks,
    )


def build_all(targets: list[ExtractedTarget]) -> dict[str, Z3TargetResult]:
    return {issue_key(target): build_for_target(target) for target in targets}
