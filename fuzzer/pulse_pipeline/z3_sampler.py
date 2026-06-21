from __future__ import annotations

import logging
import random
from dataclasses import replace
from fractions import Fraction
from typing import Callable

from typing_extensions import Any

import z3
from tqdm import tqdm

from .il import Predicate, render_predicate
from .pulse_to_il import ExtractedTarget
from .result import TargetSampleResult
from .z3_builder import issue_key, model_to_json, predicate_to_z3
from .procedures import CType


LOG = logging.getLogger(__name__)

# Most interesting C integer examples are near zero.  The gaussian sampler keeps that region hot
# while still occasionally producing larger magnitudes when the tail is useful.
INTEGER_SIGMA = 2.0**8

# Unsatisfiable random draws do not count as attempts because the real unknown is never called.
# This cap prevents very narrow preconditions from spinning forever.
MAX_DRAWS_PER_ATTEMPT = 20


def z3_value_to_int(value: z3.ExprRef) -> int:
    """Convert a Z3 integer/rational model value into a Python int.

    Pulse sometimes produces fractional linear terms even though the sampled unknown inputs are
    ints.  Fractions are truncated through `Fraction`.
    """

    text = str(value)
    try:
        return int(text)
    except ValueError:
        return int(Fraction(text))


def input_variable_names(target: ExtractedTarget) -> tuple[str, ...]:
    if target.call_boundary is None:
        return ()
    return tuple(sorted(target.call_boundary.input_variables.values()))

def input_variable_types(target: ExtractedTarget) -> dict[str, CType]:
    if target.call_boundary is None:
        return {}
    types = target.call_boundary.input_types
    return dict(sorted(types.items()))

def output_variable_names(target: ExtractedTarget) -> tuple[str, ...]:
    if target.call_boundary is None:
        return ()
    return tuple(sorted(target.call_boundary.output_variables.values()))

def output_variable_types(target: ExtractedTarget) -> dict[str, CType]:
    if target.call_boundary is None:
        return {}
    types = target.call_boundary.output_types
    return dict(sorted(types.items()))

def build_env(target: ExtractedTarget) -> dict[str, z3.ArithRef]:
    """Create all Z3 variables used by a target's pre/post constraints.

    The target boundary contributes the public `_in`/`_out` names that later appear in summaries
    and stubs.  Predicate conversion may also add Pulse auxiliary variables.
    """

    env: dict[str, z3.ArithRef] = {}
    if target.constraints is not None:
        for predicate in (*target.constraints.pre, *target.constraints.bad_post):
            predicate_to_z3(predicate, env)
    for name in (*input_variable_names(target), *output_variable_names(target)):
        env.setdefault(name, z3.Int(name))
    return env


def predicates_to_z3(predicates: tuple[Predicate, ...], env: dict[str, z3.ArithRef]) -> list[z3.BoolRef]:
    return [predicate_to_z3(predicate, env) for predicate in predicates]


def simplified_exprs(predicates: tuple[Predicate, ...], env: dict[str, z3.ArithRef]) -> list[z3.BoolRef]:
    """Convert predicates to Z3 and simplify them before solver use.

    Simplifying the conjunction lets Z3 collapse common duplicate Pulse equalities such as
    `x == y` and `y == x` before random sampled assignments are added.
    """

    raw = predicates_to_z3(predicates, env)
    if not raw:
        return []
    simplified = z3.simplify(z3.And(*raw))
    if z3.is_true(simplified):
        return []
    if z3.is_and(simplified):
        return [arg for arg in simplified.children()]
    return [simplified]


def rendered_simplified(exprs: list[z3.BoolRef]) -> list[str]:
    return [str(expr) for expr in exprs]


def target_constraint_summary(target: ExtractedTarget) -> dict[str, list[str]]:
    """Rendered constraints for per-target JSON summaries.

    `raw_*` is close to the Pulse-derived IL.
    `simplified_*` is what the sampler actually adds to the solver.
    """

    if target.constraints is None:
        return {"raw_pre": [], "raw_bad_post": [], "simplified_pre": [], "simplified_bad_post": []}
    env = build_env(target)
    pre = simplified_exprs(target.constraints.pre, env)
    bad = simplified_exprs(target.constraints.bad_post, env)

    # add boolean constraints here too
    input_types = input_variable_types(target)
    output_types = output_variable_types(target)
    pre.extend(boolean_constraints(env, input_types))
    bad.extend(boolean_constraints(env, output_types))

    return {
        "raw_pre": [render_predicate(predicate) for predicate in target.constraints.pre],
        "raw_bad_post": [render_predicate(predicate) for predicate in target.constraints.bad_post],
        "simplified_pre": rendered_simplified(pre),
        "simplified_bad_post": rendered_simplified(bad),
    }


def assignment_constraints(env: dict[str, z3.ArithRef], values: dict[str, int]) -> list[z3.BoolRef]:
    """Create equality constraints for sampled inputs and observed outputs."""

    constraints: list[z3.BoolRef] = []
    for name, value in sorted(values.items()):
        env.setdefault(name, z3.Int(name))
        constraints.append(env[name] == int(value))
    return constraints


def gaussian_int() -> int:
    return int(round(random.gauss(0.0, INTEGER_SIGMA)))

def random_bool() -> int:
    return int(bool(random.getrandbits(1)))

# Booleans are just integers that are either 1 or 0
def random_type(type: CType) -> int:
    if type.is_bool_value or type.is_bool_pointer:
        return random_bool()
    else:
        return gaussian_int()


def sample_inputs(names: tuple[str, ...], types: tuple[CType, ...]) -> dict[str, int]:
    return {name: random_type(type) for name, type in zip(names, types)}


def sample_precondition_model(
    solver: z3.Solver, env: dict[str, z3.ArithRef], names: tuple[str, ...]
) -> dict[str, int]:
    """Return one input assignment from the current satisfiable precondition model."""

    model = solver.model()
    return {name: z3_value_to_int(model.eval(env[name], model_completion=True)) for name in names}


def sampled_no_bug_reason(
    inputs: tuple[str, ...], attempts: int, max_attempts: int, draws: int, max_draws: int
) -> str:
    """Explains why sampling stopped after at least one real call. """

    if not inputs:
        return "only one input-free call exists and it did not satisfy the bad postcondition"
    if attempts >= max_attempts:
        return "attempt budget exhausted without a bug-satisfying output"
    if draws >= max_draws:
        return "draw budget exhausted without a bug-satisfying output"
    return "sampling stopped without a bug-satisfying output"


def expand_call_inputs(target: ExtractedTarget, sampled: dict[str, int]) -> dict[str, int]:
    """Expand shared Z3 input variables back into concrete C formal names.

    For example, if Pulse knows `a` and `c` are the same value, the boundary maps both formals to
    one Z3 variable.  The real C function still needs both arguments, so this block reconstructs
    `{a: value, c: value}` before crossing into `ctypes`.

    We did not deduplicate earlier because sometimes the client code uses the same memory addr
    with different pointer container variables for it, and I wanted to carry along that info
    as far along as possible, in hopes we can make use of it.
    """

    if target.call_boundary is None:
        return dict(sampled)
    call_values: dict[str, int] = {}
    for formal, variable in sorted(target.call_boundary.input_variables.items()):
        if variable not in sampled:
            continue
        # Pointer formals use `<formal>_in` as their sampled cell value because `ObjectRunner`
        # needs to initialize the pointed-to integer before passing `&cell` to C.
        if variable == f"{formal}_in":
            call_values[variable] = sampled[variable]
        else:
            call_values[formal] = sampled[variable]
    return call_values


def result(
    target: ExtractedTarget,
    status: str,
    *,
    attempts: int = 0,
    values: dict[str, int] | None = None,
    model: dict[str, str] | None = None,
    rejected_unsat: int = 0,
    rejected_duplicate: int = 0,
    draws: int = 0,
    reason: str | None = None,
) -> TargetSampleResult:
    return TargetSampleResult(
        target_key=issue_key(target),
        callee=target.callee or "<unknown>",
        status=status,
        attempts=attempts,
        values={} if values is None else values,
        model={} if model is None else model,
        rejected_unsat=rejected_unsat,
        rejected_duplicate=rejected_duplicate,
        draws=draws,
        reason=reason,
    )


def boolean_constraints(env: dict[str, z3.ArithRef], types: dict[str, CType]) -> list[z3.BoolRef]:
    constraints = []
    for name, type in types.items():
        if type.is_bool_value:
            constraints.append(z3.Or(env[name] == 1, env[name] == 0))
    return constraints


def run_target(
    target: ExtractedTarget,
    max_attempts: int,
    call_unknown: Callable[[dict[str, int]], dict[str, int]],
) -> TargetSampleResult:
    """Run the complete model/random/Z3/real-call flow for one extracted target.

    Two persistent solvers are kept warm for the target:

    * `pre_solver` contains only simplified preconditions and is used to derive one model-backed
      sample, then reject invalid random inputs before calling the real unknown.
    * `full_solver` contains simplified preconditions plus the bad postconditions and is used after
      the real call to check whether sampled `_in` and observed `_out` values satisfy the bad path.

    Each attempt pushes only the sampled values onto the relevant solver and pops them immediately,
    keeping both base solvers in their simplified state and reusable across many random draws.
    """
    print("RUNNING TARGET")

    if target.status != "supported" or target.constraints is None:
        reason = target.reason or "target was not supported"
        LOG.warning("%s unsupported: %s", issue_key(target), reason)
        return result(target, "unsupported", reason=reason)

    env = build_env(target)
    pre = simplified_exprs(target.constraints.pre, env)
    bad = simplified_exprs(target.constraints.bad_post, env)
    input_names = input_variable_names(target)
    input_types = input_variable_types(target)
    output_types = output_variable_types(target)

    pre.extend(boolean_constraints(env, input_types))
    bad.extend(boolean_constraints(env, output_types))

    pre_solver = z3.Solver()
    pre_solver.add(*pre)
    pre_status = pre_solver.check()
    if pre_status != z3.sat:
        reason = f"simplified precondition is UNSAT! {pre_status}"
        LOG.warning("%s exhausted before sampling: %s", issue_key(target), reason)
        return result(target, "exhausted", reason=reason)

    full_solver = z3.Solver()
    full_solver.add(*pre)
    full_solver.add(*bad)

    first_sample: TargetSampleResult | None = None
    tried: set[tuple[tuple[str, int], ...]] = set()
    attempts = rejected_unsat = rejected_duplicate = draws = 0
    max_draws = 1 if not input_names else (max_attempts * MAX_DRAWS_PER_ATTEMPT)

    def try_sample(sampled: dict[str, int]) -> TargetSampleResult | None:
        nonlocal attempts, first_sample, rejected_duplicate, rejected_unsat

        if attempts >= max_attempts:
            return None

        key = tuple(sorted(sampled.items()))
        if key in tried:
            rejected_duplicate += 1
            return None
        tried.add(key)

        # Check preconditions in the pre-only solver.  These pushes contain just sampled `_in`
        # values, so a failed check means the real unknown should not be called for this draw.
        pre_solver.push()
        pre_solver.add(*assignment_constraints(env, sampled))
        if pre_solver.check() != z3.sat:
            rejected_unsat += 1
            pre_solver.pop()
            return None

        attempts += 1
        pre_model = model_to_json(pre_solver.model(), env)
        pre_solver.pop()
        observed = call_unknown(expand_call_inputs(target, sampled))

        if first_sample is None:
            first_sample = result(
                target,
                "sampled_no_bug",
                attempts=attempts,
                values=observed,
                model=pre_model,
                rejected_unsat=rejected_unsat,
                rejected_duplicate=rejected_duplicate,
                draws=draws,
                reason="first observed sample; no bug sample found yet",
            )

        # Check full solutions in the solver that already contains pre + bad postconditions.
        # Both sampled `_in` values and observed `_out` values are temporary constraints here.
        full_solver.push()
        full_solver.add(*assignment_constraints(env, observed))
        if full_solver.check() == z3.sat:
            bug_model = model_to_json(full_solver.model(), env)
            full_solver.pop()
            return result(
                target,
                "bug_found",
                attempts=attempts,
                values=observed,
                model=bug_model,
                rejected_unsat=rejected_unsat,
                rejected_duplicate=rejected_duplicate,
                draws=draws,
            )
        full_solver.pop()
        return None

    precondition_inputs = sample_precondition_model(pre_solver, env, input_names)
    model_result = try_sample(precondition_inputs)
    if model_result is not None:
        result_repeat = try_sample(precondition_inputs)
        if model_result != result_repeat:
            return result(
                target,
                "impure",
                attempts=attempts,
                rejected_unsat=rejected_unsat,
                rejected_duplicate=rejected_duplicate,
                draws=draws,
                reason="the function produced two different outputs for identical calls, and has been deemed impure",
            )
        else:
            return model_result

    progress_label = f"{target.callee or '<unknown>'} draws"
    with tqdm(total=max_draws, desc=progress_label, unit="draw", leave=False) as progress:
        while attempts < max_attempts and draws < max_draws:
            draws += 1
            progress.update(1)
            inputs = sample_inputs(input_names, tuple(input_types.values()))
            sample_result = try_sample(inputs)
            if sample_result is not None:
                result_repeat = try_sample(inputs)
                if model_result != result_repeat:
                    return result(
                        target,
                        "impure",
                        attempts=attempts,
                        rejected_unsat=rejected_unsat,
                        rejected_duplicate=rejected_duplicate,
                        draws=draws,
                        reason="the function produced two different outputs for identical calls, and has been deemed impure",
                    )
                else:
                    return sample_result

    if first_sample is not None:
        return replace(
            first_sample,
            attempts=attempts,
            rejected_unsat=rejected_unsat,
            rejected_duplicate=rejected_duplicate,
            draws=draws,
            reason=sampled_no_bug_reason(input_names, attempts, max_attempts, draws, max_draws),
        )
    return result(
        target,
        "exhausted",
        attempts=attempts,
        rejected_unsat=rejected_unsat,
        rejected_duplicate=rejected_duplicate,
        draws=draws,
        reason="no pre-satisfying input sample found before draw budget was exhausted",
    )
