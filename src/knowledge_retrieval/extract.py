"""CLI to extract a page range/subset from a PDF into a new PDF file."""

import argparse
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter

PAGE_TOKEN_RE = re.compile(r"^\d+(-\d+)?$")


def parse_pages(spec: str, page_count: int) -> list[int]:  # pylint: disable=too-many-branches
    """Parse a page spec like '1-5' or '1,3,5' or '1-3,7,9-10' into 0-indexed page numbers."""
    spec = spec.strip()
    if not spec:
        raise ValueError("Page spec must not be empty")

    pages: list[int] = []
    seen: set[int] = set()

    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if not PAGE_TOKEN_RE.match(token):
            raise ValueError(f"Invalid page token: '{token}'")

        if "-" in token:
            start_str, end_str = token.split("-")
            start, end = int(start_str), int(end_str)
            if start < 1 or end < 1:
                raise ValueError(f"Page numbers must be >= 1: '{token}'")
            if start > end:
                raise ValueError(f"Range start must be <= end: '{token}'")
            page_range = range(start, end + 1)
        else:
            page_num = int(token)
            if page_num < 1:
                raise ValueError(f"Page numbers must be >= 1: '{token}'")
            page_range = range(page_num, page_num + 1)

        for page_num in page_range:
            if page_num > page_count:
                raise ValueError(
                    f"Page {page_num} is out of range (PDF has {page_count} pages)"
                )
            if page_num not in seen:
                seen.add(page_num)
                pages.append(page_num - 1)

    if not pages:
        raise ValueError("No pages parsed from spec")

    return pages


def extract_pdf(input_path: Path, pages_spec: str, output_path: Path) -> None:
    """Write the pages matching `pages_spec` from `input_path` to `output_path`."""
    reader = PdfReader(str(input_path))
    page_indices = parse_pages(pages_spec, len(reader.pages))

    writer = PdfWriter()
    for index in page_indices:
        writer.add_page(reader.pages[index])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)


def main() -> None:
    """CLI entry point: parse args and extract the requested pages."""
    parser = argparse.ArgumentParser(
        prog="knowledge-retrieval-extract",
        description="Extract a page range/subset from a PDF into a new PDF file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s input.pdf -p 3-7 -o out.pdf
  %(prog)s input.pdf -p 1,4,9 -o out.pdf
  %(prog)s input.pdf -p 1-3,7,10-12 -o out.pdf
""",
    )
    parser.add_argument("input", type=Path, help="path to the source PDF file")
    parser.add_argument(
        "-p",
        "--pages",
        required=True,
        metavar="SPEC",
        help="pages to extract, 1-indexed (e.g. '3-7', '1,4,9', or '1-3,7,10-12')",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        type=Path,
        metavar="PATH",
        help="path to the output PDF file",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Input file not found: {args.input}")

    try:
        extract_pdf(args.input, args.pages, args.output)
    except ValueError as exc:
        parser.error(str(exc))

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
