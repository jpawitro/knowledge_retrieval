"""Wraps the `marker` CLI (marker-pdf) for batch PDF -> Markdown conversion."""
# pylint: disable=duplicate-code
# The engine wrapper modules share a uniform "check binary, build command,
# subprocess.run" shape by design, so each one reads the same at a glance -
# that's deliberate consistency across sibling modules, not copy-paste debt.

import shutil
import subprocess
from pathlib import Path

PACKAGE = "marker-pdf"
COMMAND = "marker"


def convert(input_dir: Path, output_dir: Path, workers: int, extra_args: list[str]) -> None:
    """Convert every PDF in `input_dir` to Markdown via the `marker` CLI."""
    if shutil.which(COMMAND) is None:
        raise RuntimeError(
            f"'{COMMAND}' was not found on PATH. Install it with 'pip install {PACKAGE}'."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        COMMAND,
        str(input_dir),
        "--output_dir", str(output_dir),
        "--workers", str(workers),
        *extra_args,
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        # Same rationale as mineru.py's _run(): translate a non-zero exit
        # into a RuntimeError so callers (pipeline.py) can catch and report
        # it per-file/per-batch instead of crashing on an uncaught
        # CalledProcessError.
        raise RuntimeError(f"marker failed converting {input_dir} (exit code {exc.returncode})") from exc
