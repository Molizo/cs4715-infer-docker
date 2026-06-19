from __future__ import annotations

from pathlib import Path

from .procedures import Procedure
from .result import TargetSampleResult


STATUS_RANK = {
    "bug_found": 3,
    "sampled_no_bug": 2,
    "exhausted": 1,
    "unsupported": 0,
}


def c_int(value: int) -> str:
    return f"(int){value}LL"


def prototype(procedure: Procedure) -> str:
    assert procedure.formals is not None
    assert procedure.ret_type is not None
    args = ", ".join(formal.ctype.c_decl(formal.name) for formal in procedure.formals)
    if not args:
        args = "void"
    return f"{procedure.ret_type.base} {procedure.name}({args})"


def render_effect(procedure: Procedure, values: dict[str, int]) -> list[str]:
    assert procedure.formals is not None
    lines: list[str] = []
    for formal in procedure.formals:
        if formal.ctype.is_int_pointer:
            output_name = f"{formal.name}_out"
            lines.append(f"  if ({formal.name} != NULL) *{formal.name} = {c_int(values.get(output_name, 0))};")
    lines.append("  return;")
    return lines


def render_function(
    procedure: Procedure, result: TargetSampleResult, skipped: list[TargetSampleResult]
) -> str:
    values = result.values
    header = [f"  // Status: {result.status}"]
    if result.reason is not None:
        header.append(f"  // Reason: {result.reason}")
    details = ", ".join(f"{key} = {value}" for key, value in sorted(values.items()))
    lines = [prototype(procedure) + " {", *header, f"  // Example: {details}"]
    if skipped:
        lines.append(f"  // Other targets for this callee collapsed into this stub: {len(skipped)}")
    lines.append("")
    lines.append("  // Prototype intentionally reduces the unknown to this focused sample.")
    lines.extend(render_effect(procedure, values))
    lines.append("}")
    return "\n".join(lines)


def choose_results(
    results: list[TargetSampleResult],
) -> dict[str, tuple[TargetSampleResult, list[TargetSampleResult]]]:
    by_callee: dict[str, list[TargetSampleResult]] = {}
    for result in results:
        by_callee.setdefault(result.callee, []).append(result)
    chosen: dict[str, tuple[TargetSampleResult, list[TargetSampleResult]]] = {}
    for callee, callee_results in by_callee.items():
        ordered = sorted(
            callee_results,
            key=lambda result: (STATUS_RANK.get(result.status, 0), -result.attempts),
            reverse=True,
        )
        chosen[callee] = (ordered[0], ordered[1:])
    return chosen


def write_stub(path: Path, procedures: dict[str, Procedure], results: list[TargetSampleResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        "// Stubs generated for unknown procedures",
        "// Re-run infer capture + analyze with this file included alongside your original sources",
        "",
        "#include <stdint.h>",
        "#include <stdlib.h>",
        "",
    ]
    for callee, (result, skipped) in sorted(choose_results(results).items()):
        procedure = procedures.get(callee)
        if procedure is None or not result.can_emit_stub:
            reason = result.reason or "no observed sample available"
            parts.append(f"// TODO: no stub emitted for {callee}: {reason}")
            parts.append("")
            continue
        parts.append(render_function(procedure, result, skipped))
        parts.append("")
    path.write_text("\n".join(parts))
