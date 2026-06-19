from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .procedures import Procedure, parse_procedures
from .pulse_json import PulseProcedureNodes, ProcedureSummary, load_node_json_files, parse_summaries


LOG = logging.getLogger(__name__)
IMPORTANT_OUTPUT = re.compile(r"\b(warning|error|unsupported|not implemented|not supported)\b", re.I)


@dataclass(frozen=True)
class InferData:
    reports: list[dict[str, Any]]
    summaries: dict[str, ProcedureSummary]
    node_procedures: dict[str, PulseProcedureNodes]
    procedures: dict[str, Procedure]


def write_command_log(
    path: Path | None, cmd: list[str], output: str, returncode: int, cwd: Path | None = None
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"$ {shlex.join(cmd)}",
                f"cwd: {cwd}" if cwd is not None else "cwd: <current>",
                f"exit_code: {returncode}",
                "",
                output,
            ]
        )
    )


def log_important_output(cmd: list[str], output: str) -> None:
    """Surface Infer warnings/errors without forcing users to open artifact files first."""

    label = shlex.join(cmd)
    for line in output.splitlines():
        if IMPORTANT_OUTPUT.search(line):
            LOG.warning("%s: %s", label, line)


def run_command(cmd: list[str], log_path: Path | None = None, cwd: Path | None = None) -> str:
    LOG.info("running %s", shlex.join(cmd))
    proc = subprocess.run(
        cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    write_command_log(log_path, cmd, proc.stdout, proc.returncode, cwd)
    log_important_output(cmd, proc.stdout)
    if proc.returncode != 0:
        LOG.error("command failed with exit code %s: %s", proc.returncode, shlex.join(cmd))
        raise RuntimeError(
            f"command failed with exit code {proc.returncode}: {' '.join(cmd)}\n{proc.stdout}"
        )
    return proc.stdout


def run_capture(
    infer_bin: str,
    infer_out: Path,
    compile_cmd: list[str],
    *,
    cwd: Path,
    log_path: Path | None = None,
) -> None:
    run_command(
        [
            infer_bin,
            "capture",
            "--results-dir",
            str(infer_out),
            "--force-delete-results-dir",
            "--",
            *compile_cmd,
        ],
        log_path,
        cwd=cwd,
    )


def regenerate_node_states(infer_bin: str, infer_out: Path, log_path: Path | None = None) -> None:
    if not infer_out.exists():
        raise FileNotFoundError(f"Infer output directory does not exist: {infer_out}")
    pulse_dir = infer_out / "pulse"
    if pulse_dir.exists():
        for path in pulse_dir.glob("pulse-node-states-*.json"):
            path.unlink()
    run_command(
        [
            infer_bin,
            "analyze",
            "--results-dir",
            str(infer_out),
            "--pulse-only",
            "--pulse-experimental-track-all-unknown-calls",
        ],
        log_path,
    )


def load_reports(infer_out: Path) -> list[dict[str, Any]]:
    report_path = infer_out / "report.json"
    if not report_path.exists():
        return []
    reports = json.loads(report_path.read_text())
    if not isinstance(reports, list):
        raise ValueError(f"expected report.json to contain a list: {report_path}")
    return [report for report in reports if isinstance(report, dict)]


def load_summary_json(
    infer_bin: str,
    infer_out: Path,
    log_path: Path | None = None,
) -> dict[str, ProcedureSummary]:
    output = run_command(
        [
            infer_bin,
            "debug",
            "--results-dir",
            str(infer_out),
            "--procedures",
            "--procedures-summary-json",
            "--select",
            "all",
        ],
        log_path,
    )
    return parse_summaries(json.loads(output))


def load_procedures(
    infer_bin: str,
    infer_out: Path,
    log_path: Path | None = None,
) -> dict[str, Procedure]:
    output = run_command(
        [
            infer_bin,
            "debug",
            "--results-dir",
            str(infer_out),
            "--procedures",
            "--procedures-attributes",
            "--procedures-callees",
            "--select",
            "all",
        ],
        log_path,
    )
    return parse_procedures(output)


def collect(
    infer_bin: str,
    infer_out: Path,
    out_dir: Path | None = None,
    *,
    capture_cmd: list[str] | None = None,
    capture_cwd: Path | None = None,
) -> InferData:
    command_dir = None if out_dir is None else out_dir / "infer_commands"
    if capture_cmd is not None:
        if capture_cwd is None:
            raise ValueError("capture_cwd is required when capture_cmd is provided")
        run_capture(
            infer_bin,
            infer_out,
            capture_cmd,
            cwd=capture_cwd,
            log_path=None if command_dir is None else command_dir / "infer_capture.log",
        )
    regenerate_node_states(
        infer_bin,
        infer_out,
        None if command_dir is None else command_dir / "infer_analyze.log",
    )
    reports = load_reports(infer_out)
    summaries = load_summary_json(
        infer_bin,
        infer_out,
        None if command_dir is None else command_dir / "infer_debug_summaries.log",
    )
    procedures = load_procedures(
        infer_bin,
        infer_out,
        None if command_dir is None else command_dir / "infer_debug_procedures.log",
    )
    node_procedures = load_node_json_files(infer_out)
    if not node_procedures:
        raise RuntimeError(
            f"no Pulse node-state JSON files were produced under {infer_out / 'pulse'}"
        )
    return InferData(
        reports=reports,
        summaries=summaries,
        node_procedures=node_procedures,
        procedures=procedures,
    )
