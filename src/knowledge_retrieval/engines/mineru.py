"""Wraps the `mineru` CLI (mineru[core]) for batch PDF -> Markdown conversion."""
# pylint: disable=duplicate-code
# mineru.py and paddleocr.py share the same "resolve pdf_files, workers<=1 vs
# sharded" shape by design, so they read the same at a glance - that's
# deliberate consistency across sibling modules, not copy-paste debt.

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PACKAGE = "mineru[core]"
COMMAND = "mineru"


def _run(path: Path, output_dir: Path, extra_args: list[str]) -> None:
    """Run one `mineru` invocation over a single file or directory."""
    try:
        subprocess.run(
            [COMMAND, "-p", str(path), "-o", str(output_dir), *extra_args],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        # A failure inside one document (e.g. mineru's own "N task(s) failed"
        # for a malformed/unsupported chapter PDF) surfaces as a non-zero
        # exit here. Re-raise as RuntimeError so callers (pipeline.py) treat
        # it the same as any other engine failure - a clean, catchable error
        # for this one file/batch - instead of an uncaught CalledProcessError
        # crashing the whole run (and, in --queue mode, the entire batch).
        raise RuntimeError(f"mineru failed converting {path} (exit code {exc.returncode})") from exc


def _run_shard(paths: list[Path], output_dir: Path, extra_args: list[str]) -> None:
    """Convert a shard of files sequentially, one `mineru` process per file."""
    for path in paths:
        _run(path, output_dir, extra_args)


def _flatten_doc_dir(doc_dir: Path) -> None:
    """mineru writes to <doc_dir>/<backend-or-method-subdir>/<stem>.md - move that
    subdir's contents up so output matches marker's `<stem>/<stem>.md` shape.
    """
    stem = doc_dir.name
    if not doc_dir.is_dir() or (doc_dir / f"{stem}.md").exists():
        return
    for md_path in doc_dir.rglob(f"{stem}.md"):
        nested_dir = md_path.parent
        if nested_dir == doc_dir:
            continue
        for item in nested_dir.iterdir():
            shutil.move(str(item), str(doc_dir / item.name))
        nested_dir.rmdir()
        return


def convert(input_dir: Path, output_dir: Path, workers: int, extra_args: list[str]) -> None:
    """Convert every PDF in `input_dir` to Markdown via the `mineru` CLI."""
    if shutil.which(COMMAND) is None:
        raise RuntimeError(
            f"'{COMMAND}' was not found on PATH. Install it with 'pip install {PACKAGE}'."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        return

    if workers <= 1:
        # One mineru process loads its model stack once and batches every file
        # in input_dir - the cheapest option, and the default.
        _run(input_dir, output_dir, extra_args)
    else:
        # Opt-in only: each shard is its own mineru process with its own full
        # model stack loaded, same tradeoff as marker's --workers.
        shards = [pdf_files[i::workers] for i in range(workers)]
        shards = [shard for shard in shards if shard]
        with ThreadPoolExecutor(max_workers=len(shards)) as executor:
            futures = [
                executor.submit(_run_shard, shard, output_dir, extra_args)
                for shard in shards
            ]
            for future in futures:
                future.result()

    for pdf_path in pdf_files:
        _flatten_doc_dir(output_dir / pdf_path.stem)
