"""Unified CLI: split a PDF into chapters, then convert each chapter to Markdown.

Runs the full pipeline in one command:
  1. split the source PDF into per-chapter PDFs under <references-dir>/<name>/
  2. convert those PDFs to Markdown under <outputs-dir>/<name>/ with the selected engine
"""

import argparse
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from pypdf import PdfReader

from knowledge_retrieval.engines import DEFAULT_ENGINE, ENGINES, get_engine
from knowledge_retrieval.split_chapters import (
    build_ranges,
    compute_page_chunks,
    load_queue,
    resolve_job_options,
    write_chapters,
)


@contextmanager
def single_file_dir(path: Path):
    """Yield a scratch directory containing only `path`, since every engine's
    `convert()` batch-processes whatever PDFs it finds in a directory. Also
    used by the crawl pipeline's PDF branch (crawl_pdf.py) for the same
    reason - a downloaded PDF is a single file, not a directory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / path.name).symlink_to(path.resolve())
        yield tmp_dir


@contextmanager
def subset_dir(paths: list[Path]):
    """Yield a scratch directory containing symlinks to just `paths`, so a
    batch engine's directory scan only sees the subset that still needs
    converting rather than every PDF sitting in the source directory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for path in paths:
            (tmp_dir / path.name).symlink_to(path.resolve())
        yield tmp_dir


def is_already_converted(output_dir: Path, stem: str) -> bool:
    """A chapter counts as already converted if <output_dir>/<stem>/<stem>.md
    exists anywhere under that directory - the flattened `<stem>/<stem>.md`
    shape engines write today, or an older/nested one such as mineru's
    pre-flatten `<stem>/<backend>/<stem>.md` (e.g. `<stem>/hybrid_auto/<stem>.md`)."""
    doc_dir = output_dir / stem
    return doc_dir.is_dir() and any(doc_dir.rglob(f"{stem}.md"))


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the unified split+convert CLI."""
    parser = argparse.ArgumentParser(
        prog="knowledge-retrieval",
        description="Split a PDF into chapters and convert each chapter to Markdown.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s input.pdf                          # split + convert with mineru, 1 worker
  %(prog)s input.pdf --engine marker          # use marker instead
  %(prog)s input.pdf --workers 8              # more parallelism
  %(prog)s input.pdf --name tb880             # override the output folder name
  %(prog)s input.pdf --skip-split             # convert an already-split references/<name>/
  %(prog)s input.pdf -- --disable_image_extraction   # extra args passed to the engine's own CLI
  %(prog)s --queue queue.yaml                 # batch: split + convert every PDF listed in a YAML queue

queue.yaml (batch mode - see README for the full schema; same file format as
knowledge-retrieval-split's --queue, plus pipeline-only keys name/references_dir/
outputs_dir/engine/workers/skip_split/force/engine_args):
  defaults:
    outputs_dir: outputs
    engine: mineru

  files:
    - path: /path/to/book1.pdf
      chapters:                       # manual page ranges - skips detection entirely
        - chapter 1, 1-10
        - chapter 2, 11-20
    - path: /path/to/book2.pdf         # no `chapters`: falls back to bookmark/heading detection
      bookmark_level: 1                # per-file override of the defaults/CLI setup
""",
    )
    parser.add_argument("input", type=Path, nargs="?", default=None, help="path to the source PDF file")
    parser.add_argument(
        "--name", default=None,
        help="output folder name for this document (default: input file stem)",
    )
    parser.add_argument(
        "--references-dir", type=Path, default=None,
        help="parent directory for split-out chapter PDFs (default: references; "
             "with --skip-split, defaults to the input file's own directory instead)",
    )
    parser.add_argument(
        "--outputs-dir", type=Path, default=Path("outputs"),
        help="parent directory for converted Markdown (default: outputs)",
    )
    parser.add_argument(
        "--mode", choices=["auto", "bookmarks", "headings"], default="auto",
        help="chapter-detection strategy (default: auto - try bookmarks, fall back to headings)",
    )
    parser.add_argument(
        "--bookmark-level", type=int, default=0,
        help="exact bookmark nesting level to treat as chapters: 0 = top-level "
        "(default), 1 = second-level (children of top-level bookmarks), etc.",
    )
    parser.add_argument(
        "--exclude-title", default=None,
        help="regex (case-insensitive): drop any bookmark at --bookmark-level whose "
        "title matches, e.g. non-hierarchical 'Figures'/'Tables' grouping entries",
    )
    parser.add_argument(
        "--min-gap", type=int, default=2,
        help="minimum pages between detected headings, filters false positives (default: 2)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=30,
        help="split any chapter longer than this into roughly-equal, max-size "
             "sub-parts, e.g. '<name>_01.pdf', '<name>_02.pdf' (default: 30)",
    )
    parser.add_argument(
        "--engine", choices=sorted(ENGINES), default=DEFAULT_ENGINE,
        help=f"PDF-to-Markdown conversion engine (default: {DEFAULT_ENGINE})",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="parallel workers/threads for the conversion engine (default: 1)",
    )
    parser.add_argument(
        "--skip-split", action="store_true",
        help="skip splitting; convert the PDF(s) already in <references-dir>/<name>/ if "
             "--references-dir was given, otherwise in the input file's own directory",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="reconvert every chapter even if <outputs-dir>/<name>/<stem>/<stem>.md "
             "already exists (default: skip chapters already converted)",
    )
    parser.add_argument(
        "--queue", type=Path, default=None,
        help="YAML file listing multiple PDFs to split and convert in one run, instead of "
        "a single positional input (see the epilog above for the schema)",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    return parser


def process_one(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    input_path: Path,
    name: str | None,
    references_dir: Path | None,
    outputs_dir: Path,
    mode: str,
    bookmark_level: int,
    exclude_title: str | None,
    min_gap: int,
    max_pages: int,
    engine_name: str,
    workers: int,
    skip_split: bool,
    force: bool,
    engine_args: list[str],
    manual_chapters: list | None = None,
) -> None:
    """Split one PDF into chapters (unless `skip_split`) and convert whatever
    chapter PDFs result to Markdown. Raises FileNotFoundError/ValueError for
    bad input/config, RuntimeError if the engine itself fails - callers
    decide whether that's fatal (single file) or a skip-and-continue (queue)."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    doc_name = name or input_path.stem
    output_dir = outputs_dir / doc_name

    single_file = None
    if skip_split:
        if references_dir:
            # Caller pointed us at an existing <references-dir>/<name>/ of
            # already-split chapters - convert the whole thing, as before.
            split_dir = references_dir / doc_name
            if not split_dir.is_dir():
                raise FileNotFoundError(f"--skip-split given but {split_dir} does not exist")
        else:
            # No references-dir given: `input` is already a single, presumably
            # pre-split chapter PDF. Convert just that file rather than every
            # other PDF that happens to sit alongside it in the same directory.
            single_file = input_path
            split_dir = input_path
    else:
        split_dir = (references_dir or Path("references")) / doc_name
        reader = PdfReader(str(input_path))
        page_count = len(reader.pages)
        exclude_pattern = re.compile(exclude_title, re.IGNORECASE) if exclude_title else None

        ranges = build_ranges(
            reader, page_count, mode, bookmark_level, exclude_pattern, min_gap,
            manual_chapters=manual_chapters,
        )

        print()
        for ch, start, end in ranges:
            print(f"  pages {start + 1:>4}-{end:<4} ({end - start:>3} pages)  {ch.title}")
        print()

        write_chapters(reader, ranges, split_dir, max_pages=max_pages)
        file_count = sum(len(compute_page_chunks(end - start, max_pages)) for _, start, end in ranges)
        print(f"Wrote {file_count} chapter file(s) to {split_dir}\n")

    convert = get_engine(engine_name)

    if single_file is not None:
        pdf_files = [single_file]
    else:
        pdf_files = sorted(split_dir.glob("*.pdf"))

    if force:
        todo = pdf_files
    else:
        todo = [p for p in pdf_files if not is_already_converted(output_dir, p.stem)]
        skipped = len(pdf_files) - len(todo)
        if skipped:
            print(f"Skipping {skipped} chapter(s) already converted in {output_dir} (use --force to redo)")

    if not todo:
        print(f"Nothing to convert - {output_dir} is already up to date.")
        return

    print(f"Converting {len(todo)} file(s) from {split_dir} -> {output_dir} "
          f"with engine '{engine_name}' ({workers} workers)")
    if len(todo) == 1:
        with single_file_dir(todo[0]) as tmp_dir:
            convert(tmp_dir, output_dir, workers, engine_args)
    elif len(todo) == len(pdf_files):
        convert(split_dir, output_dir, workers, engine_args)
    else:
        with subset_dir(todo) as tmp_dir:
            convert(tmp_dir, output_dir, workers, engine_args)

    print(f"Wrote Markdown output to {output_dir}")


# Per-file option keys that a YAML queue's `defaults` block and each file
# entry may override for the full pipeline. engine_args isn't here since it
# isn't a real argparse attribute (it comes from `--` on the command line) -
# it's merged separately in main().
PIPELINE_QUEUE_OPTION_KEYS = (
    "name", "references_dir", "outputs_dir", "mode", "bookmark_level",
    "exclude_title", "min_gap", "max_pages", "engine", "workers", "skip_split", "force",
)


def main() -> None:  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """CLI entry point: split the input PDF(s) into chapters, then convert them."""
    parser = build_parser()

    argv = sys.argv[1:]
    if "--" in argv:
        sep = argv.index("--")
        engine_args = argv[sep + 1:]
        argv = argv[:sep]
    else:
        engine_args = []

    args = parser.parse_args(argv)

    if args.queue and args.input:
        parser.error("pass either a single input PDF or --queue, not both")
    if not args.queue and args.input is None:
        parser.error("an input PDF is required unless --queue is given")

    if not args.queue:
        try:
            process_one(
                input_path=args.input,
                name=args.name,
                references_dir=args.references_dir,
                outputs_dir=args.outputs_dir,
                mode=args.mode,
                bookmark_level=args.bookmark_level,
                exclude_title=args.exclude_title,
                min_gap=args.min_gap,
                max_pages=args.max_pages,
                engine_name=args.engine,
                workers=args.workers,
                skip_split=args.skip_split,
                force=args.force,
                engine_args=engine_args,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            parser.error(str(e))
        return

    try:
        yaml_defaults, file_entries = load_queue(args.queue)
    except (FileNotFoundError, ValueError) as e:
        parser.error(str(e))
    if not file_entries:
        parser.error(f"no files listed in queue file {args.queue}")

    had_error = False
    for i, file_entry in enumerate(file_entries, start=1):
        if not isinstance(file_entry, dict) or "path" not in file_entry:
            print(f"[{i}/{len(file_entries)}] SKIPPED: queue entry missing 'path': {file_entry!r}")
            had_error = True
            continue

        input_path = Path(file_entry["path"]).expanduser()
        options = resolve_job_options(args, yaml_defaults, file_entry, keys=PIPELINE_QUEUE_OPTION_KEYS)
        job_engine_args = file_entry.get("engine_args", yaml_defaults.get("engine_args", engine_args))

        # process_one() always appends /<doc_name> itself, so a shared vs.
        # per-file references_dir/outputs_dir behave identically here - same
        # as split_chapters.py's output_dir; no special-casing needed.
        references_dir = Path(options["references_dir"]).expanduser() if options["references_dir"] else None
        outputs_dir = Path(options["outputs_dir"]).expanduser()

        print(f"\n=== [{i}/{len(file_entries)}] {input_path} ===")
        try:
            process_one(
                input_path=input_path,
                name=options["name"],
                references_dir=references_dir,
                outputs_dir=outputs_dir,
                mode=options["mode"],
                bookmark_level=options["bookmark_level"],
                exclude_title=options["exclude_title"],
                min_gap=options["min_gap"],
                max_pages=options["max_pages"],
                engine_name=options["engine"],
                workers=options["workers"],
                skip_split=options["skip_split"],
                force=options["force"],
                engine_args=job_engine_args,
                manual_chapters=file_entry.get("chapters"),
            )
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"  ERROR: {e}")
            had_error = True

    if had_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
