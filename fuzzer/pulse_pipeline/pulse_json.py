from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


Json = Any


@dataclass(frozen=True)
class Location:
    file: str
    line: int
    col: int

    def to_json(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "col": self.col}


@dataclass(frozen=True)
class PulseState:
    """One Pulse execution state with explicit names for state components.

    `current` is the current symbolic state at this program point.
    `abductive_pre` is Pulse's abduced precondition, not a source-line pre-state.
    """

    kind: str
    current: dict[str, Any]
    abductive_pre: dict[str, Any]
    path_condition: dict[str, Any]
    skipped_calls: list[Any]
    diagnostic: Any | None = None
    raw: Any | None = None

    @property
    def unknown_values(self) -> bool:
        if isinstance(self.raw, dict):
            return bool(self.raw.get("unknown_values", False))
        return False


@dataclass(frozen=True)
class PulseNode:
    id: int
    location: Location
    instrs: tuple[str, ...]
    succs: tuple[int, ...]
    pre_states: tuple[PulseState, ...]
    post_states: tuple[PulseState, ...]


@dataclass(frozen=True)
class PulseProcedureNodes:
    procedure: str
    nodes: tuple[PulseNode, ...]


@dataclass(frozen=True)
class ProcedureSummary:
    procedure: str
    states: tuple[PulseState, ...]


def procname_to_string(procname: Any) -> str:
    if isinstance(procname, list) and len(procname) == 2 and procname[0] == "C":
        payload = procname[1]
        if isinstance(payload, dict):
            c_name = payload.get("c_name")
            if isinstance(c_name, list):
                return "::".join(str(part) for part in c_name)
    return str(procname)


def location_from_json(raw: Any) -> Location:
    if not isinstance(raw, dict):
        return Location(file="<unknown>", line=-1, col=-1)
    file_json = raw.get("file", "<unknown>")
    if isinstance(file_json, list) and len(file_json) == 2:
        file_name = str(file_json[1])
    else:
        file_name = str(file_json)
    return Location(file=file_name, line=int(raw.get("line", -1)), col=int(raw.get("col", -1)))


def skipped_call_name(raw: Any) -> str | None:
    if not (isinstance(raw, list) and raw):
        return None
    return procname_to_string(raw[0])


def skipped_call_location(raw: Any) -> Location | None:
    if not (isinstance(raw, list) and len(raw) >= 2):
        return None
    trace = raw[1]
    if isinstance(trace, list) and len(trace) == 2 and isinstance(trace[1], dict):
        location = trace[1].get("location")
        if location is not None:
            return location_from_json(location)
    return None


def parse_execution_state(raw: Any) -> PulseState | None:
    if not (isinstance(raw, list) and raw):
        return None
    tag = raw[0]
    if tag == "ContinueProgram" and len(raw) == 2 and isinstance(raw[1], dict):
        astate = raw[1]
        return PulseState(
            kind="ContinueProgram",
            current=astate.get("post", {}),
            abductive_pre=astate.get("pre", {}),
            path_condition=astate.get("path_condition", {}),
            skipped_calls=astate.get("skipped_calls", []),
            raw=astate,
        )
    if tag == "Stopped" and len(raw) == 2:
        stopped = raw[1]
        if isinstance(stopped, list) and len(stopped) == 2 and stopped[0] == "AbortProgram":
            payload = stopped[1]
            if isinstance(payload, dict):
                astate = payload.get("astate", {})
                return PulseState(
                    kind="AbortProgram",
                    current=astate.get("post", {}),
                    abductive_pre=astate.get("pre", {}),
                    path_condition=astate.get("path_condition", {}),
                    skipped_calls=astate.get("skipped_calls", []),
                    diagnostic=payload.get("diagnostic"),
                    raw=astate,
                )
    return PulseState(
        kind=str(tag),
        current={},
        abductive_pre={},
        path_condition={},
        skipped_calls=[],
        raw=raw,
    )


def parse_execution_states(raw: Any) -> tuple[PulseState, ...]:
    if not isinstance(raw, list):
        return ()
    states = [state for item in raw if (state := parse_execution_state(item)) is not None]
    return tuple(states)


def parse_node(raw: dict[str, Any]) -> PulseNode:
    state = raw.get("state", {})
    return PulseNode(
        id=int(raw["id"]),
        location=location_from_json(raw.get("location", {})),
        instrs=tuple(str(instr) for instr in raw.get("instrs", [])),
        succs=tuple(int(succ) for succ in raw.get("succs", [])),
        pre_states=parse_execution_states(state.get("pre", [])),
        post_states=parse_execution_states(state.get("post", [])),
    )


def parse_node_document(raw: dict[str, Any]) -> PulseProcedureNodes:
    return PulseProcedureNodes(
        procedure=str(raw.get("procedure", "")),
        nodes=tuple(parse_node(node) for node in raw.get("nodes", []) if isinstance(node, dict)),
    )


def parse_summary(raw: Any) -> ProcedureSummary | None:
    if not (isinstance(raw, list) and len(raw) == 2):
        return None
    procedure = procname_to_string(raw[0])
    payloads = raw[1]
    if not isinstance(payloads, list):
        return ProcedureSummary(procedure=procedure, states=())
    states: list[PulseState] = []
    for payload in payloads:
        if not (isinstance(payload, list) and len(payload) == 2 and payload[0] == "pulse"):
            continue
        pulse = payload[1]
        if not isinstance(pulse, dict):
            continue
        main = pulse.get("main", {})
        if not isinstance(main, dict):
            continue
        for item in main.get("pre_post_list", []):
            state = parse_execution_state(item)
            if state is not None:
                states.append(state)
    return ProcedureSummary(procedure=procedure, states=tuple(states))


def parse_summaries(raw: Any) -> dict[str, ProcedureSummary]:
    if not isinstance(raw, list):
        raise ValueError("expected procedure summary JSON to be a list")
    result: dict[str, ProcedureSummary] = {}
    for item in raw:
        summary = parse_summary(item)
        if summary is not None:
            result[summary.procedure] = summary
    return result


def load_node_json_files(infer_out: Path) -> dict[str, PulseProcedureNodes]:
    pulse_dir = infer_out / "pulse"
    if not pulse_dir.exists():
        return {}
    procedures: dict[str, PulseProcedureNodes] = {}
    import json

    for path in sorted(pulse_dir.glob("pulse-node-states-*.json")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            parsed = parse_node_document(json.loads(line))
            procedures[parsed.procedure] = parsed
    return procedures


def domain_heap_derefs(domain: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for addr, edges in domain.get("heap", []):
        if not isinstance(addr, str) or not isinstance(edges, list):
            continue
        for access, value_hist in edges:
            if access == ["Dereference"] and isinstance(value_hist, list) and value_hist:
                value = value_hist[0]
                if isinstance(value, str):
                    result[addr] = value
    return result


def stack_addresses(domain: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for var_json, origin in domain.get("stack", []):
        if not (
            isinstance(var_json, list)
            and len(var_json) == 2
            and var_json[0] == "ProgramVar"
            and isinstance(var_json[1], dict)
        ):
            continue
        if isinstance(origin, list) and len(origin) >= 2 and isinstance(origin[1], str):
            plain = var_json[1].get("plain")
            if isinstance(plain, str):
                result[plain] = origin[1]
    return result


def address_attrs(domain: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value, attrs in domain.get("attrs", []):
        if not isinstance(value, str) or not isinstance(attrs, list):
            continue
        for attr in attrs:
            if (
                isinstance(attr, list)
                and len(attr) >= 3
                and attr[0] == "AddressOfStackVariable"
                and isinstance(attr[1], list)
                and len(attr[1]) == 2
                and isinstance(attr[1][1], dict)
            ):
                plain = attr[1][1].get("plain")
                if isinstance(plain, str):
                    result[plain] = value
    return result


def local_addresses(domain: dict[str, Any]) -> dict[str, str]:
    result = stack_addresses(domain)
    result.update(address_attrs(domain))
    return result


def attrs_for_value(domain: dict[str, Any], value: str) -> list[Any]:
    for attr_value, attrs in domain.get("attrs", []):
        if attr_value == value and isinstance(attrs, list):
            return attrs
    return []

