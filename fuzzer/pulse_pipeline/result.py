from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TargetSampleResult:
    """Final packaged result for one (client, unknown callee, location) target.

    Variables ending in `_in` came from Z3/random input sampling, and variables
    ending in `_out` came from calling the real shared-library implementation.
    """

    target_key: str
    callee: str
    status: str
    attempts: int = 0
    values: dict[str, int] = field(default_factory=dict)
    model: dict[str, str] = field(default_factory=dict)
    rejected_unsat: int = 0
    rejected_duplicate: int = 0
    draws: int = 0
    reason: str | None = None

    @property
    def has_values(self) -> bool:
        return bool(self.values)

    @property
    def is_bug(self) -> bool:
        return self.status == "bug_found"

    @property
    def can_emit_stub(self) -> bool:
        return self.status in {"bug_found", "sampled_no_bug"} and self.has_values

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "callee": self.callee,
            "status": self.status,
            "attempts": self.attempts,
            "draws": self.draws,
            "rejected_duplicate": self.rejected_duplicate,
            "rejected_unsat": self.rejected_unsat,
            "values": dict(sorted(self.values.items())),
            "model": dict(sorted(self.model.items())),
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result
