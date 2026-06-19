from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .il import ConstraintSet, Expr, Predicate, binary, const, rename_expr, render_predicate, unary, var
from .procedures import Procedure
from .pulse_json import (
    Location,
    PulseNode,
    PulseProcedureNodes,
    PulseState,
    attrs_for_value,
    domain_heap_derefs,
    local_addresses,
    skipped_call_location,
    skipped_call_name,
)


@dataclass(frozen=True)
class IssueRef:
    bug_type: str
    procedure: str
    file: str
    line: int
    column: int

    def to_json(self) -> dict[str, Any]:
        return {
            "bug_type": self.bug_type,
            "procedure": self.procedure,
            "file": self.file,
            "line": self.line,
            "column": self.column,
        }


@dataclass(frozen=True)
class UnknownCallBoundary:
    callee: str
    location: Location
    actuals: tuple[str, ...]
    pulse_value_names: dict[str, str]
    input_variables: dict[str, str]
    output_variables: dict[str, str]
    output_pointer_addresses: dict[str, str]

    def to_json(self) -> dict[str, Any]:
        return {
            "callee": self.callee,
            "location": self.location.to_json(),
            "actuals": list(self.actuals),
            "pulse_value_names": dict(sorted(self.pulse_value_names.items())),
            "input_variables": dict(sorted(self.input_variables.items())),
            "output_variables": dict(sorted(self.output_variables.items())),
            "output_pointer_addresses": dict(sorted(self.output_pointer_addresses.items())),
        }


@dataclass(frozen=True)
class ExtractedTarget:
    status: str
    issue: IssueRef
    callee: str | None = None
    call_boundary: UnknownCallBoundary | None = None
    constraints: ConstraintSet | None = None
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.status, "issue": self.issue.to_json()}
        if self.callee is not None:
            result["callee"] = self.callee
        if self.reason is not None:
            result["reason"] = self.reason
        if self.call_boundary is not None:
            result["call_boundary"] = self.call_boundary.to_json()
        if self.constraints is not None:
            result["constraints"] = {
                "pre": [render_predicate(pred) for pred in self.constraints.pre],
                "bad_post": [render_predicate(pred) for pred in self.constraints.bad_post],
            }
        return result


def report_depends_on_unknown(report: dict[str, Any]) -> bool:
    return bool(
        report.get("extras", {})
        .get("may_depend_on_an_unknown_value", {})
        .get("value", False)
    )


def issue_from_report(report: dict[str, Any]) -> IssueRef:
    return IssueRef(
        bug_type=str(report.get("bug_type", "")),
        procedure=str(report.get("procedure", "")),
        file=str(report.get("file", "")),
        line=int(report.get("line", -1)),
        column=int(report.get("column", -1)),
    )


def diagnostic_depends_on_unknown(state: PulseState) -> bool:
    diagnostic = state.diagnostic
    if isinstance(diagnostic, list) and len(diagnostic) == 2 and isinstance(diagnostic[1], dict):
        return bool(diagnostic[1].get("may_depend_on_an_unknown_value", False))
    return bool(state.skipped_calls)


def find_abort_node(proc_nodes: PulseProcedureNodes, issue: IssueRef) -> tuple[PulseNode, PulseState] | None:
    fallback: tuple[PulseNode, PulseState] | None = None
    for node in proc_nodes.nodes:
        for state in node.post_states:
            if state.kind != "AbortProgram" or not diagnostic_depends_on_unknown(state):
                continue
            if fallback is None:
                fallback = (node, state)
            if node.location.line == issue.line:
                return node, state
    return fallback


def first_unknown_skipped_call(
    state: PulseState, procedures: dict[str, Procedure]
) -> tuple[str, Location] | None:
    for skipped in state.skipped_calls:
        callee = skipped_call_name(skipped)
        location = skipped_call_location(skipped)
        if callee is None or location is None:
            continue
        procedure = procedures.get(callee)
        if procedure is not None and procedure.defined is False:
            return callee, location
    return None


CALL_RE = re.compile(r"_fun_(?P<callee>[A-Za-z_][A-Za-z0-9_]*)\((?P<args>.*)\)\s*\[")
LOAD_RE = re.compile(r"(?P<tmp>n\$\d+)=\*&(?P<name>[A-Za-z_][A-Za-z0-9_]*)[: ]")


def parse_temp_loads(instrs: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for instr in instrs:
        match = LOAD_RE.search(instr)
        if match:
            result[match.group("tmp")] = match.group("name")
    return result


def split_actuals(args: str) -> tuple[str, ...]:
    result: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(args):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            result.append(args[start:index].strip())
            start = index + 1
    tail = args[start:].strip()
    if tail:
        result.append(tail)
    return tuple(clean_actual(actual) for actual in result)


def clean_actual(actual: str) -> str:
    actual = actual.strip()
    if ":" in actual:
        actual = actual.split(":", 1)[0]
    return actual.strip()


def parse_call_actuals(node: PulseNode, callee: str) -> tuple[str, ...] | None:
    for instr in node.instrs:
        match = CALL_RE.search(instr)
        if match and match.group("callee") == callee:
            return split_actuals(match.group("args"))
    return None


def find_call_node(
    proc_nodes: PulseProcedureNodes, callee: str, call_location: Location
) -> PulseNode | None:
    fallback: PulseNode | None = None
    needle = f"_fun_{callee}("
    for node in proc_nodes.nodes:
        if not any(needle in instr for instr in node.instrs):
            continue
        if fallback is None:
            fallback = node
        if node.location.line == call_location.line:
            return node
    return fallback


def first_continue(states: tuple[PulseState, ...]) -> PulseState | None:
    for state in states:
        if state.kind == "ContinueProgram":
            return state
    return None


def returned_from_unknown_values(domain: dict[str, Any]) -> tuple[str, ...]:
    for value, attrs in domain.get("attrs", []):
        if not isinstance(value, str) or not isinstance(attrs, list):
            continue
        for attr in attrs:
            if (
                isinstance(attr, list)
                and len(attr) == 2
                and attr[0] == "ReturnedFromUnknown"
                and isinstance(attr[1], list)
            ):
                return tuple(item for item in attr[1] if isinstance(item, str))
    return ()


def add_pointer_names(
    names: dict[str, str],
    formal_name: str,
    pointer_addr: str | None,
    pre_derefs: dict[str, str],
    post_derefs: dict[str, str],
    input_vars: dict[str, str],
    output_vars: dict[str, str],
    output_pointer_addresses: dict[str, str],
) -> None:
    if pointer_addr is None:
        return
    input_name = f"{formal_name}_in"
    input_vars[formal_name] = input_name
    output_vars[formal_name] = f"{formal_name}_out"
    output_pointer_addresses[formal_name] = pointer_addr
    # TODO: Sample NULL for pointer formals too.  For each pointer variable, store a companion
    # `<name>_is_null` boolean, read any known nullness from the Pulse summaries, then always include
    # that boolean in pointer sampling.  This should probably be represented with Optional-style
    # input values rather than as a one-off special case.  The real call should also run in a
    # separate multiprocessing child process so a sampled NULL crash does not take down the analysis
    # pipeline.
    input_value = pre_derefs.get(pointer_addr)
    if input_value is not None:
        input_vars[formal_name] = names.setdefault(input_value, input_name)
    output_value = post_derefs.get(pointer_addr)
    if output_value is not None:
        output_name = f"{formal_name}_out"
        names[output_value] = output_name


def build_call_boundary(
    callee: str,
    location: Location,
    procedure: Procedure,
    call_node: PulseNode,
) -> UnknownCallBoundary | str:
    if procedure.formals is None:
        return "missing callee formals"
    pre_state = first_continue(call_node.pre_states)
    post_state = first_continue(call_node.post_states)
    if pre_state is None or post_state is None:
        return "call node is missing ContinueProgram pre/post states"
    actuals = parse_call_actuals(call_node, callee)
    if actuals is None:
        return "could not parse call instruction actuals"
    if len(actuals) != len(procedure.formals):
        return f"call actual count {len(actuals)} does not match formal count {len(procedure.formals)}"

    temp_loads = parse_temp_loads(call_node.instrs)
    pre_domain = pre_state.current
    post_domain = post_state.current
    pre_locals = local_addresses(pre_domain)
    post_locals = local_addresses(post_domain)
    pre_derefs = domain_heap_derefs(pre_domain)
    post_derefs = domain_heap_derefs(post_domain)
    names: dict[str, str] = {}
    input_vars: dict[str, str] = {}
    output_vars: dict[str, str] = {}
    output_pointer_addresses: dict[str, str] = {}

    for formal, actual in zip(procedure.formals, actuals, strict=True):
        if formal.ctype.is_int_value:
            local_name = temp_loads.get(actual, actual)
            local_addr = pre_locals.get(local_name) or post_locals.get(local_name)
            value = pre_derefs.get(local_addr or "")
            if value is None:
                return f"could not map int actual {actual!r} for formal {formal.name}"
            # If two formals carry the same Pulse value, map them to the same Z3 variable instead
            # of adding a separate equality predicate due to possible sharing of memory addr.
            # The sampler expands that shared value back into both C arguments before calling the real unknown.
            variable_name = names.setdefault(value, formal.name)
            input_vars[formal.name] = variable_name
        elif formal.ctype.is_int_pointer:
            if actual.startswith("&"):
                local_name = actual[1:]
                pointer_addr = pre_locals.get(local_name) or post_locals.get(local_name)
            else:
                local_name = temp_loads.get(actual, actual)
                local_addr = pre_locals.get(local_name) or post_locals.get(local_name)
                pointer_addr = pre_derefs.get(local_addr or "")
            add_pointer_names(
                names,
                formal.name,
                pointer_addr,
                pre_derefs,
                post_derefs,
                input_vars,
                output_vars,
                output_pointer_addresses,
            )

    returned_values = returned_from_unknown_values(post_domain)
    for index, formal in enumerate(procedure.formals):
        if index >= len(returned_values):
            break
        value = returned_values[index]
        if formal.ctype.is_int_value and value not in names:
            names.setdefault(value, formal.name)
            input_vars[formal.name] = formal.name
        elif formal.ctype.is_int_pointer:
            add_pointer_names(
                names,
                formal.name,
                value,
                pre_derefs,
                post_derefs,
                input_vars,
                output_vars,
                output_pointer_addresses,
            )

    if not input_vars and not output_vars:
        return "could not map any call-boundary Pulse values to formal variables"
    return UnknownCallBoundary(
        callee=callee,
        location=location,
        actuals=actuals,
        pulse_value_names=names,
        input_variables=input_vars,
        output_variables=output_vars,
        output_pointer_addresses=output_pointer_addresses,
    )


def number_to_fraction(raw: Any) -> Fraction | None:
    if not isinstance(raw, dict):
        return None
    try:
        return Fraction(int(str(raw.get("num", "0"))), int(str(raw.get("den", "1"))))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def parse_linear_body(raw: Any) -> Expr | None:
    if not (isinstance(raw, list) and len(raw) == 2):
        return None
    raw_coeffs, raw_const = raw
    constant = number_to_fraction(raw_const)
    if constant is None or not isinstance(raw_coeffs, list):
        return None
    expr = const(constant)
    for raw_coeff in raw_coeffs:
        if not (
            isinstance(raw_coeff, list)
            and len(raw_coeff) == 2
            and isinstance(raw_coeff[0], str)
        ):
            return None
        coeff = number_to_fraction(raw_coeff[1])
        if coeff is None:
            return None
        expr = binary("add", expr, binary("mul", const(coeff), var(raw_coeff[0])))
    return expr


def parse_term(raw: Any) -> Expr | None:
    if isinstance(raw, str):
        return var(raw)
    if not (isinstance(raw, list) and raw):
        return None
    tag = raw[0]
    if tag == "Var" and len(raw) == 2 and isinstance(raw[1], str):
        return var(raw[1])
    if tag == "Const" and len(raw) == 2:
        value = number_to_fraction(raw[1])
        return None if value is None else const(value)
    if tag == "Linear" and len(raw) == 2:
        return parse_linear_body(raw[1])
    if tag == "Add" and len(raw) == 3:
        left = parse_term(raw[1])
        right = parse_term(raw[2])
        return None if left is None or right is None else binary("add", left, right)
    if tag == "Minus":
        if len(raw) == 2:
            child = parse_term(raw[1])
            return None if child is None else unary("neg", child)
        if len(raw) == 3:
            left = parse_term(raw[1])
            right = parse_term(raw[2])
            return None if left is None or right is None else binary("sub", left, right)
    if tag == "Mult" and len(raw) == 3:
        left = parse_term(raw[1])
        right = parse_term(raw[2])
        return None if left is None or right is None else binary("mul", left, right)
    if tag == "DivI" and len(raw) == 3:
        left = parse_term(raw[1])
        right = parse_term(raw[2])
        return None if left is None or right is None else binary("div", left, right)
    if tag == "Mod" and len(raw) == 3:
        left = parse_term(raw[1])
        right = parse_term(raw[2])
        return None if left is None or right is None else binary("mod", left, right)
    return None


def parse_atom(raw: Any, source: str) -> Predicate | None:
    if not (isinstance(raw, list) and len(raw) == 3 and isinstance(raw[0], str)):
        return None
    op_json, left_raw, right_raw = raw
    if isinstance(left_raw, list) and left_raw and left_raw[0] == "IsInt":
        return None
    if isinstance(right_raw, list) and right_raw and right_raw[0] == "IsInt":
        return None
    op = {
        "Equal": "==",
        "NotEqual": "!=",
        "LessThan": "<",
        "LessEqual": "<=",
    }.get(op_json)
    if op is None:
        return None
    left = parse_term(left_raw)
    right = parse_term(right_raw)
    if left is None or right is None:
        return None
    return Predicate(op=op, left=left, right=right, source=source)


def predicates_from_path_condition(path_condition: dict[str, Any], source: str) -> list[Predicate]:
    predicates: list[Predicate] = []
    for item in path_condition.get("conditions", []):
        if isinstance(item, list) and item:
            predicate = parse_atom(item[0], f"{source}.conditions")
            if predicate is not None:
                predicates.append(predicate)
    phi = path_condition.get("phi", {})
    if isinstance(phi, dict):
        for item in phi.get("atoms", []):
            predicate = parse_atom(item, f"{source}.phi.atoms")
            if predicate is not None:
                predicates.append(predicate)
        for item in phi.get("term_eqs", []):
            if isinstance(item, list) and len(item) == 2:
                left = parse_term(item[0])
                right = parse_term(item[1])
                if left is not None and right is not None:
                    predicates.append(Predicate("==", left, right, f"{source}.phi.term_eqs"))
        for item in phi.get("linear_eqs", []):
            if isinstance(item, list) and len(item) == 2 and isinstance(item[0], str):
                right = parse_linear_body(item[1])
                if right is not None:
                    predicates.append(Predicate("==", var(item[0]), right, f"{source}.phi.linear_eqs"))
    return predicates


def rename_predicate(predicate: Predicate, names: dict[str, str]) -> Predicate:
    return Predicate(
        op=predicate.op,
        left=rename_expr(predicate.left, names),
        right=rename_expr(predicate.right, names),
        source=predicate.source,
    )


def dedupe_predicates(predicates: list[Predicate]) -> tuple[Predicate, ...]:
    result: list[Predicate] = []
    seen: set[str] = set()
    for predicate in predicates:
        key = render_predicate(predicate)
        if key in seen:
            continue
        seen.add(key)
        result.append(predicate)
    return tuple(result)


def reachable_from(start: int, nodes: dict[int, PulseNode]) -> set[int]:
    seen: set[int] = set()
    stack = [start]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes.get(node_id)
        if node is not None:
            stack.extend(succ for succ in node.succs if succ not in seen)
    return seen


def can_reach(target: int, nodes: dict[int, PulseNode]) -> set[int]:
    reverse: dict[int, list[int]] = {}
    for node in nodes.values():
        for succ in node.succs:
            reverse.setdefault(succ, []).append(node.id)
    seen: set[int] = set()
    stack = [target]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(reverse.get(node_id, []))
    return seen


def state_mentions_callee(state: PulseState, callee: str) -> bool:
    return any(skipped_call_name(skipped) == callee for skipped in state.skipped_calls)


def extract_constraints(
    proc_nodes: PulseProcedureNodes,
    call_node: PulseNode,
    abort_node: PulseNode,
    callee: str,
    boundary: UnknownCallBoundary,
) -> ConstraintSet | str:
    pre_state = first_continue(call_node.pre_states)
    if pre_state is None:
        return "call node does not have a usable pre-state"
    pre = [
        rename_predicate(pred, boundary.pulse_value_names)
        for pred in predicates_from_path_condition(pre_state.path_condition, f"node:{call_node.id}:pre")
    ]

    nodes_by_id = {node.id: node for node in proc_nodes.nodes}
    on_path = reachable_from(call_node.id, nodes_by_id) & can_reach(abort_node.id, nodes_by_id)
    bad: list[Predicate] = []
    for node in proc_nodes.nodes:
        if node.id not in on_path:
            continue
        for state in node.post_states:
            if state.kind != "ContinueProgram" or not state_mentions_callee(state, callee):
                continue
            state_names = names_for_state(boundary, state)
            for predicate in predicates_from_path_condition(
                state.path_condition, f"node:{node.id}:post"
            ):
                bad.append(rename_predicate(predicate, state_names))

    constraints = ConstraintSet(pre=dedupe_predicates(pre), bad_post=dedupe_predicates(bad))
    if not constraints.bad_post:
        return "no post-call path predicates were found on the path to the abort"
    return constraints


def names_for_state(boundary: UnknownCallBoundary, state: PulseState) -> dict[str, str]:
    names = dict(boundary.pulse_value_names)
    derefs = domain_heap_derefs(state.current)
    for formal, pointer_addr in boundary.output_pointer_addresses.items():
        output_value = derefs.get(pointer_addr)
        output_name = boundary.output_variables.get(formal)
        if output_value is not None and output_name is not None:
            names[output_value] = output_name
    return names


def output_var_names(boundary: UnknownCallBoundary) -> set[str]:
    return set(boundary.output_variables.values())


def bad_mentions_output(constraints: ConstraintSet, boundary: UnknownCallBoundary) -> bool:
    outputs = output_var_names(boundary)
    if not outputs:
        return False
    return any(predicate.vars() & outputs for predicate in constraints.bad_post)


def extract_one(
    report: dict[str, Any],
    node_procedures: dict[str, PulseProcedureNodes],
    procedures: dict[str, Procedure],
) -> ExtractedTarget:
    issue = issue_from_report(report)
    proc_nodes = node_procedures.get(issue.procedure)
    if proc_nodes is None:
        return ExtractedTarget(status="unsupported", issue=issue, reason="missing node JSON")
    abort = find_abort_node(proc_nodes, issue)
    if abort is None:
        return ExtractedTarget(
            status="unsupported", issue=issue, reason="could not find matching AbortProgram node"
        )
    abort_node, abort_state = abort
    skipped = first_unknown_skipped_call(abort_state, procedures)
    if skipped is None:
        return ExtractedTarget(
            status="unsupported", issue=issue, reason="AbortProgram did not record an unknown callee"
        )
    callee, call_location = skipped
    callee_proc = procedures.get(callee)
    if callee_proc is None:
        return ExtractedTarget(
            status="unsupported",
            issue=issue,
            callee=callee,
            reason="missing callee procedure metadata",
        )
    unsupported = callee_proc.unsupported_reason()
    if unsupported is not None:
        return ExtractedTarget(status="unsupported", issue=issue, callee=callee, reason=unsupported)
    call_node = find_call_node(proc_nodes, callee, call_location)
    if call_node is None:
        return ExtractedTarget(
            status="unsupported",
            issue=issue,
            callee=callee,
            reason="could not find unknown call node",
        )
    boundary_or_reason = build_call_boundary(callee, call_location, callee_proc, call_node)
    if isinstance(boundary_or_reason, str):
        return ExtractedTarget(
            status="unsupported", issue=issue, callee=callee, reason=boundary_or_reason
        )
    constraints_or_reason = extract_constraints(
        proc_nodes, call_node, abort_node, callee, boundary_or_reason
    )
    if isinstance(constraints_or_reason, str):
        return ExtractedTarget(
            status="unsupported",
            issue=issue,
            callee=callee,
            call_boundary=boundary_or_reason,
            reason=constraints_or_reason,
        )
    if not bad_mentions_output(constraints_or_reason, boundary_or_reason):
        return ExtractedTarget(
            status="unsupported",
            issue=issue,
            callee=callee,
            call_boundary=boundary_or_reason,
            constraints=constraints_or_reason,
            reason="bad postconditions do not mention a mapped unknown output",
        )
    return ExtractedTarget(
        status="supported",
        issue=issue,
        callee=callee,
        call_boundary=boundary_or_reason,
        constraints=constraints_or_reason,
    )


def extract_targets(
    reports: list[dict[str, Any]],
    node_procedures: dict[str, PulseProcedureNodes],
    procedures: dict[str, Procedure],
) -> list[ExtractedTarget]:
    targets: list[ExtractedTarget] = []
    for report in reports:
        if report_depends_on_unknown(report):
            targets.append(extract_one(report, node_procedures, procedures))
    return targets
