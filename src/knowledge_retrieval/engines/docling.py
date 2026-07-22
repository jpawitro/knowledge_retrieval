"""Wraps the `docling convert` CLI for batch PDF -> Markdown conversion."""
# pylint: disable=duplicate-code
# The engine wrapper modules share a uniform "check binary, build command,
# subprocess.run" shape by design, so each one reads the same at a glance -
# that's deliberate consistency across sibling modules, not copy-paste debt.

import shutil
import subprocess
from pathlib import Path

PACKAGE = "docling"
COMMAND = "docling"


def convert(input_dir: Path, output_dir: Path, workers: int, extra_args: list[str]) -> None:
    """Convert every PDF in `input_dir` to Markdown via the `docling` CLI."""
    if shutil.which(COMMAND) is None:
        raise RuntimeError(
            f"'{COMMAND}' was not found on PATH. Install it with 'pip install {PACKAGE}'."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        COMMAND, "convert", str(input_dir),
        "--to", "md",
        "--output", str(output_dir),
        "--num-threads", str(workers),
        *extra_args,
    ]
    subprocess.run(command, check=True)
