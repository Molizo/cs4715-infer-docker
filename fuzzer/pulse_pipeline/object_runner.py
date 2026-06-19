from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Any

from .procedures import Procedure


class ObjectRunner:
    """ctypes runner for an existing shared library with C ABI symbols.

    `main.py` owns one instance and passes it into the per-target sampler.  This keeps dynamic
    loading separate from Z3: the sampler chooses `_in` values, this runner mutates C pointer
    arguments through the real unknown function, then returns the merged `_in`/`_out` dictionary.
    """

    def __init__(self, shared_library: Path) -> None:
        if not shared_library.exists():
            raise FileNotFoundError(
                f"unknown implementation shared library does not exist: {shared_library}\n"
                "Compile it separately and update UNKNOWN_OBJECT in main.py."
            )
        try:
            self.library = ctypes.CDLL(str(shared_library))
        except OSError as exc:
            raise RuntimeError(
                f"failed to load {shared_library}: {exc}\n"
                "The prototype only loads an existing .so. Build the shared library separately."
            ) from exc

    def call(self, procedure: Procedure, input_values: dict[str, int]) -> dict[str, int]:
        """Call one supported C unknown and return sampled inputs plus observed outputs.

        Scalar `int` formals read their value from the formal name, for example `a`.
        Pointer `int *` formals use `<formal>_in` for the initial cell value and write
        `<formal>_out` after the call.  Missing pointer inputs default to zero so output-only
        pointers can still be passed to C safely.
        """

        if procedure.formals is None or procedure.ret_type is None:
            raise ValueError(f"{procedure.name}: missing procedure signature")
        if not procedure.ret_type.is_void:
            raise ValueError(f"{procedure.name}: only void return functions are supported")
        try:
            fn = getattr(self.library, procedure.name)
        except AttributeError as exc:
            raise RuntimeError(
                f"shared library does not export {procedure.name!r}; rebuild UNKNOWN_OBJECT with this symbol"
            ) from exc

        argtypes: list[Any] = []
        args: list[Any] = []
        pointer_values: dict[str, ctypes.c_int] = {}
        values: dict[str, int] = {}
        for formal in procedure.formals:
            if formal.ctype.is_int_value:
                value = int(input_values.get(formal.name, 0))
                argtypes.append(ctypes.c_int)
                args.append(ctypes.c_int(value))
                values[formal.name] = value
            elif formal.ctype.is_int_pointer:
                input_name = f"{formal.name}_in"
                value = int(input_values.get(input_name, 0))
                cell = ctypes.c_int(value)
                pointer_values[formal.name] = cell
                argtypes.append(ctypes.POINTER(ctypes.c_int))
                args.append(ctypes.byref(cell))
                if input_name in input_values:
                    values[input_name] = value
            else:
                raise ValueError(f"{procedure.name}: unsupported formal {formal.name}")

        fn.argtypes = argtypes
        fn.restype = None
        fn(*args)
        for name, value in sorted(pointer_values.items()):
            values[f"{name}_out"] = int(value.value)
        return values
