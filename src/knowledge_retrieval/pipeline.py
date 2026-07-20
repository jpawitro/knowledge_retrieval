"""Unified CLI: split a PDF into chapters, then convert each chapter to Markdown.

Runs the full pipeline in one command:
  1. split the source PDF into per-chapter PDFs under <references-dir>/<name>/
  2. convert those PDFs to Markdown under <outputs-dir>/<name>/ with the selected engine
"""

import argparse
import sys
from pathlib import Path

from pypdf import PdfReader

from knowledge_retrieval.engines import DEFAULT_ENGINE, ENGINES, get_engine
from knowledge_retrieval.split_chapters import (
    detect_heading_chapters,
    get_bookmark_chapters,
    split_by_chapters,
    write_chapters,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowledge-retrieval",
        description="Split a PDF into chapters and convert each chapter to Markdown.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s input.pdf                          # split + convert with marker, 4 workers
  %(prog)s input.pdf --engine docling         # use docling instead
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
        "--references-dir", type=Path, default=Path("references"),
        help="parent directory for split-out chapter PDFs (default: references)",
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
        "--workers", type=int, default=4,
        help="parallel workers/threads for the conversion engine (default: 4)",
    )
    parser.add_argument(
        "--skip-split", action="store_true",
        help="skip splitting; convert whatever already exists in <references-dir>/<name>/",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    return parser


def main() -> None:
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
    split_dir = args.references_dir / name
    output_dir = args.outputs_dir / name

    if not args.skip_split:
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

        ranges = split_by_chapters(chapters, page_count)

        print()
        for ch, start, end in ranges:
            print(f"  pages {start + 1:>4}-{end:<4} ({end - start:>3} pages)  {ch.title}")
        print()

        write_chapters(reader, ranges, split_dir)
        print(f"Wrote {len(ranges)} chapter files to {split_dir}\n")
    elif not split_dir.is_dir():
        parser.error(f"--skip-split given but {split_dir} does not exist")

    convert = get_engine(args.engine)
    print(f"Converting {split_dir} -> {output_dir} with engine '{args.engine}' ({args.workers} workers)")
    try:
        convert(split_dir, output_dir, args.workers, engine_args)
    except RuntimeError as exc:
        parser.error(str(exc))

    print(f"Wrote Markdown output to {output_dir}")


if __name__ == "__main__":
    main()
