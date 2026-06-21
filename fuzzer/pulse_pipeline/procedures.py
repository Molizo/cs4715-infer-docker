from __future__ import annotations

import re
from dataclasses import dataclass


INTEGER_TYPES = {"int"}
BOOLEAN_TYPES = {"_Bool"} # todo: maybe add some more


@dataclass(frozen=True)
class CType:
    raw: str
    base: str
    pointer_depth: int

    @property
    def is_void(self) -> bool:
        return self.pointer_depth == 0 and self.base == "void"

    @property
    def is_int_value(self) -> bool:
        return self.pointer_depth == 0 and self.base in INTEGER_TYPES

    @property
    def is_bool_value(self) -> bool:
        return self.pointer_depth == 0 and self.base in BOOLEAN_TYPES

    @property
    def is_int_pointer(self) -> bool:
        return self.pointer_depth == 1 and self.base in INTEGER_TYPES

    @property
    def is_bool_pointer(self) -> bool:
        return self.pointer_depth == 1 and self.base in BOOLEAN_TYPES

    @property
    def is_supported_formal(self) -> bool:
        return self.is_int_value or self.is_int_pointer or self.is_bool_value or self.is_bool_pointer

    def c_decl(self, name: str) -> str:
        stars = "*" * self.pointer_depth
        if stars:
            return f"{self.base} {stars}{name}"
        return f"{self.base} {name}"


@dataclass(frozen=True)
class Formal:
    name: str
    ctype: CType


@dataclass
class Procedure:
    name: str
    source_file: str | None = None
    defined: bool | None = None
    formals: list[Formal] | None = None
    ret_type: CType | None = None
    callees: list[str] | None = None

    @property
    def is_supported_unknown(self) -> bool:
        if self.defined is not False or self.ret_type is None or self.formals is None:
            return False
        return self.ret_type.is_void and all(formal.ctype.is_supported_formal for formal in self.formals)

    def unsupported_reason(self) -> str | None:
        if self.defined is not False:
            return "callee is not an undefined procedure"
        if self.ret_type is None or self.formals is None:
            return "missing procedure signature"
        if not self.ret_type.is_void:
            return f"unsupported return type {self.ret_type.raw!r}"
        for formal in self.formals:
            if not formal.ctype.is_supported_formal:
                return f"unsupported formal {formal.name}: {formal.ctype.raw!r}"
        return None


def normalize_type(raw: str) -> CType:
    typ = " ".join(raw.strip().split())
    pointer_depth = typ.count("*")
    base = " ".join(typ.replace("*", " ").split())
    return CType(raw=raw.strip(), base=base, pointer_depth=pointer_depth)


def parse_formals(text: str) -> list[Formal]:
    body = text.strip()
    if body == "[]":
        return []
    if body.startswith("[") and body.endswith("]"):
        body = body[1:-1]
    formals: list[Formal] = []
    for match in re.finditer(r"\(([^,]+),([^)]*)\)", body):
        formals.append(Formal(match.group(1).strip(), normalize_type(match.group(2).strip())))
    return formals


def split_procedure_blocks(debug_output: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in debug_output.splitlines():
        if line and not line.startswith(" ") and not line.startswith("["):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def parse_procedures(debug_output: str) -> dict[str, Procedure]:
    procedures: dict[str, Procedure] = {}
    for block in split_procedure_blocks(debug_output):
        lines = block.splitlines()
        if not lines:
            continue
        procedure = Procedure(name=lines[0].strip(), formals=[], callees=[])
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("source_file:"):
                procedure.source_file = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("defined:"):
                procedure.defined = stripped.split(":", 1)[1].strip() == "true"
            elif "formals=" in stripped:
                procedure.formals = parse_formals(stripped.split("formals=", 1)[1].strip())
            elif "ret_type=" in stripped:
                procedure.ret_type = normalize_type(stripped.split("ret_type=", 1)[1].strip())
            elif stripped.startswith("callees:"):
                callees = stripped.split(":", 1)[1].strip()
                procedure.callees = [callee.strip() for callee in callees.split(",") if callee.strip()]
        procedures[procedure.name] = procedure
    return procedures
