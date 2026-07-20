"""Wraps the `docling convert` CLI for batch PDF -> Markdown conversion."""

import shutil
import subprocess
from pathlib import Path

PACKAGE = "docling"
COMMAND = "docling"


def convert(input_dir: Path, output_dir: Path, workers: int, extra_args: list[str]) -> None:
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
