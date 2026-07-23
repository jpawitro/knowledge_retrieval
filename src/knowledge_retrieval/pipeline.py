"""Unified CLI: split a PDF into chapters, then convert each chapter to Markdown.

Runs the full pipeline in one command:
  1. split the source PDF into per-chapter PDFs under <references-dir>/<name>/
  2. convert those PDFs to Markdown under <outputs-dir>/<name>/ with the selected engine
"""

import argparse
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from pypdf import PdfReader

from knowledge_retrieval.engines import DEFAULT_ENGINE, ENGINES, get_engine
from knowledge_retrieval.split_chapters import (
    detect_heading_chapters,
    get_bookmark_chapters,
    merge_same_page_chapters,
    split_by_chapters,
    write_chapters,
)


@contextmanager
def _single_file_dir(path: Path):
    """Yield a scratch directory containing only `path`, since every engine's
    `convert()` batch-processes whatever PDFs it finds in a directory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / path.name).symlink_to(path.resolve())
        yield tmp_dir


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
""",
    )
    parser.add_argument("input", type=Path, help="path to the source PDF file")
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
        "--split-mode", choices=["auto", "bookmarks", "headings"], default="auto",
        help="chapter-detection strategy (default: auto - try bookmarks, fall back to headings)",
    )
    parser.add_argument(
        "--depth", type=int, default=0,
        help="bookmark nesting depth to treat as chapters (default: 0, top-level only)",
    )
    parser.add_argument(
        "--min-gap", type=int, default=2,
        help="minimum pages between detected headings, filters false positives (default: 2)",
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
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    return parser


def main() -> None:  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """CLI entry point: split the input PDF into chapters, then convert them."""
    parser = build_parser()

    argv = sys.argv[1:]
    if "--" in argv:
        sep = argv.index("--")
        engine_args = argv[sep + 1:]
        argv = argv[:sep]
    else:
        engine_args = []

    args = parser.parse_args(argv)

    if not args.input.is_file():
        parser.error(f"Input file not found: {args.input}")

    name = args.name or args.input.stem
    output_dir = args.outputs_dir / name

    single_file = None
    if args.skip_split:
        if args.references_dir:
            # Caller pointed us at an existing <references-dir>/<name>/ of
            # already-split chapters - convert the whole thing, as before.
            split_dir = args.references_dir / name
            if not split_dir.is_dir():
                parser.error(f"--skip-split given but {split_dir} does not exist")
        else:
            # No references-dir given: `input` is already a single, presumably
            # pre-split chapter PDF. Convert just that file rather than every
            # other PDF that happens to sit alongside it in the same directory.
            single_file = args.input
            split_dir = args.input
    else:
        split_dir = (args.references_dir or Path("references")) / name
        reader = PdfReader(str(args.input))
        page_count = len(reader.pages)

        chapters = []
        if args.split_mode in ("auto", "bookmarks"):
            chapters = get_bookmark_chapters(reader, max_depth=args.depth)
            if chapters:
                print(f"Found {len(chapters)} chapters from embedded bookmarks.")
            elif args.split_mode == "bookmarks":
                parser.error("No embedded bookmarks found in this PDF.")

        if not chapters and args.split_mode in ("auto", "headings"):
            chapters = detect_heading_chapters(reader, min_gap=args.min_gap)
            print(f"Found {len(chapters)} chapters via heading-detection heuristic.")

        if not chapters:
            parser.error(
                "No chapters detected. Try --split-mode headings with a smaller "
                "--min-gap, or check the PDF manually - this heuristic won't catch every layout."
            )

        original_count = len(chapters)
        chapters = merge_same_page_chapters(chapters)
        if len(chapters) < original_count:
            print(
                f"Merged {original_count - len(chapters)} chapter(s) that shared a "
                "start page with the next chapter (e.g. Scope + Normative "
                "references landing on the same page)."
            )

        ranges = split_by_chapters(chapters, page_count)

        # Safety net: a zero-page range would produce an empty PDF that PDFium
        # refuses to open. Should be unreachable after the merge above, but skip
        # and warn rather than silently write a broken file if it ever recurs.
        safe_ranges = []
        for ch, start, end in ranges:
            if end <= start:
                print(f"  WARNING: skipping '{ch.title}' - empty page range ({start}, {end})")
                continue
            safe_ranges.append((ch, start, end))
        ranges = safe_ranges

        print()
        for ch, start, end in ranges:
            print(f"  pages {start + 1:>4}-{end:<4} ({end - start:>3} pages)  {ch.title}")
        print()

        write_chapters(reader, ranges, split_dir)
        print(f"Wrote {len(ranges)} chapter files to {split_dir}\n")

    convert = get_engine(args.engine)
    print(f"Converting {split_dir} -> {output_dir} with engine '{args.engine}' ({args.workers} workers)")
    try:
        if single_file is not None:
            with _single_file_dir(single_file) as tmp_dir:
                convert(tmp_dir, output_dir, args.workers, engine_args)
        else:
            convert(split_dir, output_dir, args.workers, engine_args)
    except RuntimeError as exc:
        parser.error(str(exc))

    print(f"Wrote Markdown output to {output_dir}")


if __name__ == "__main__":
    main()
