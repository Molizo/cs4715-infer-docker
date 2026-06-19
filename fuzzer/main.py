from __future__ import annotations

import logging
from pathlib import Path

from tqdm import tqdm

from pulse_pipeline import (
    infer_runner,
    object_runner,
    pulse_to_il,
    stub_builder,
    summary_writer,
    z3_sampler,
)
from pulse_pipeline.procedures import Procedure
from pulse_pipeline.result import TargetSampleResult
from pulse_pipeline.z3_builder import issue_key


ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger(__name__)

# Paths / commands
INFER_OUT = ROOT / Path("examples/alphabet_soup/infer-out")
SOURCE_ROOT = ROOT / Path("examples/alphabet_soup")
INFER_BIN = "infer"
UNKNOWN_OBJECT = SOURCE_ROOT / "real_unknowns.so"
CAPTURE_CMD = ["clang", "-c", "clients.c"]

# Output
OUT_DIR = ROOT / Path("generated")
TARGET_SUMMARY_DIR = OUT_DIR / "targets"
STUB_OUT = OUT_DIR / "unknown_stubs.c"

# Search behavior
MAX_ATTEMPTS_PER_TARGET = 2**16


def unsupported_result(
    target: pulse_to_il.ExtractedTarget,
    reason: str,
    *,
    callee: str | None = None,
) -> TargetSampleResult:
    LOG.warning("%s unsupported: %s", issue_key(target), reason)
    return TargetSampleResult(
        target_key=issue_key(target),
        callee=callee or target.callee or "<unknown>",
        status="unsupported",
        reason=reason,
    )


def run_target(
    target: pulse_to_il.ExtractedTarget,
    runner: object_runner.ObjectRunner,
    procedures: dict[str, Procedure],
    max_attempts: int,
) -> TargetSampleResult:
    """Run one target through the simplified pre/random/real-call/post flow.

    `z3_sampler.run_target` owns the solver loop.  `main.py` only resolves the callee metadata and
    provides the small callback that invokes the shared-library runner for this target.
    """

    if target.status != "supported" or target.callee is None:
        return unsupported_result(target, target.reason or "target was not supported")
    procedure = procedures.get(target.callee)
    if procedure is None:
        return unsupported_result(target, "missing procedure metadata", callee=target.callee)

    return z3_sampler.run_target(
        target,
        max_attempts,
        lambda values: runner.call(procedure, values),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    data = infer_runner.collect(
        INFER_BIN,
        INFER_OUT,
        OUT_DIR,
        capture_cmd=CAPTURE_CMD,
        capture_cwd=SOURCE_ROOT,
    )
    targets = pulse_to_il.extract_targets(data.reports, data.node_procedures, data.procedures)
    runner = object_runner.ObjectRunner(UNKNOWN_OBJECT)
    results = [
        run_target(target, runner, data.procedures, MAX_ATTEMPTS_PER_TARGET)
        for target in tqdm(targets, desc="targets", unit="target")
    ]
    stub_builder.write_stub(STUB_OUT, data.procedures, results)
    summary_paths = summary_writer.write_target_summaries(TARGET_SUMMARY_DIR, targets, results)
    LOG.info("wrote %s", STUB_OUT.relative_to(ROOT))
    for path in summary_paths:
        LOG.info("wrote %s", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
