from __future__ import annotations

import json
import re
from pathlib import Path

from .pulse_to_il import ExtractedTarget
from .result import TargetSampleResult
from .z3_builder import issue_key
from .z3_sampler import target_constraint_summary


def safe_filename(text: str) -> str:
    """Make a stable filename from a target key without losing human-readable context."""

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "target"


def write_target_summaries(
    target_dir: Path, targets: list[ExtractedTarget], results: list[TargetSampleResult]
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in target_dir.glob("*.json"):
        path.unlink()

    # Remove the old global summary so a fresh run cannot be mistaken for the previous format.
    legacy_summary = target_dir.parent / "debug_summary.json"
    if legacy_summary.exists():
        legacy_summary.unlink()

    results_by_key = {result.target_key: result for result in results}
    written: list[Path] = []
    for target in targets:
        key = issue_key(target)
        result = results_by_key[key]
        target_json = target.to_json()
        target_json.pop("constraints", None)
        payload = {
            "target_key": key,
            "target": target_json,
            "constraints": target_constraint_summary(target),
            "result": result.to_json(),
        }
        path = target_dir / f"{safe_filename(key)}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        written.append(path)
    return written
