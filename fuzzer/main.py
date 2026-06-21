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

INFER_BIN = "infer"

def c_sources(source_dir: Path) -> list[Path]:
    if not source_dir.is_dir():
        raise NotADirectoryError(f"source directory does not exist: {source_dir}")
    sources = sorted(path for path in source_dir.glob("*.c") if path.is_file())
    if not sources:
        raise FileNotFoundError(f"no .c files found in source directory: {source_dir}")
    return sources


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


def main(
    source_dir: str,
    shared_library: str,
    *,
    max_attempts_per_target: int = 2**16,
    out_dir: str = "generated",
) -> None:
    """
    :param source_dir: Directory containing the .c files to scan.
    :param shared_library: Path to the .so that exports the unknown functions.
    :param max_attempts_per_target: Maximum solver samples to try for each target.
    :param out_dir: Directory for outputting logs and the stub.
    """

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    source_root = Path(source_dir).expanduser().resolve()
    unknown_object = Path(shared_library).expanduser().resolve()
    output_dir = Path(out_dir).expanduser().resolve()
    if max_attempts_per_target <= 0:
        raise ValueError("max_attempts_per_target must be positive")

    sources = c_sources(source_root)
    capture_cmd = ["clang", "-c", *(path.name for path in sources)]
    infer_out = output_dir / "infer-out"
    target_summary_dir = output_dir / "targets"
    stub_out = output_dir / "unknown_stubs.c"

    data = infer_runner.collect(
        INFER_BIN,
        infer_out,
        output_dir,
        capture_cmd=capture_cmd,
        capture_cwd=source_root,
    )
    targets = pulse_to_il.extract_targets(data.reports, data.node_procedures, data.procedures)
    runner = object_runner.ObjectRunner(unknown_object)
    results = [
        run_target(target, runner, data.procedures, max_attempts_per_target)
        for target in tqdm(targets, desc="targets", unit="target")
    ]
    stub_builder.write_stub(stub_out, data.procedures, results)
    summary_paths = summary_writer.write_target_summaries(target_summary_dir, targets, results)
    LOG.info("wrote %s", stub_out)
    for path in summary_paths:
        LOG.info("wrote %s", path)


if __name__ == "__main__":
    from clize import run
    run(main)
