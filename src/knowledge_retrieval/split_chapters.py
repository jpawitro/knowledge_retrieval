"""CLI to split a PDF into one file per chapter, using embedded bookmarks
if present, else a heading-detection heuristic on page text."""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter


@dataclass
class Chapter:
    title: str
    start_page: int  # 0-indexed


def get_bookmark_chapters(reader: PdfReader, max_depth: int = 0) -> list[Chapter]:
    """Extract bookmarks as chapter boundaries, if the PDF has any.

    pypdf represents the outline as a flat list where each item's children
    appear as a nested list immediately after it, e.g.:
        [chapter1, [sub1a, sub1b], chapter2, [sub2a], chapter3]
    max_depth=0 (default) takes only the top-level items (chapter1, chapter2,
    chapter3) and ignores their nested child lists entirely - use a higher
    max_depth only if you deliberately want sub-chapters included too.
    """
    chapters: list[Chapter] = []

    def walk(outline_items, depth=0):
        for item in outline_items:
            if isinstance(item, list):
                if depth < max_depth:
                    walk(item, depth + 1)
                continue  # nested children beyond max_depth: skip, don't extract
            if depth <= max_depth:
                try:
                    page_num = reader.get_destination_page_number(item)
                except Exception:
                    continue
                chapters.append(Chapter(title=item.title, start_page=page_num))

    walk(reader.outline)
    chapters.sort(key=lambda c: c.start_page)
    return chapters


# Adjust/add patterns to match your document family. These two cover the most
# common technical-report styles: "12. Case study 8: ..." and "Chapter 3: ...".
HEADING_PATTERNS = [
    re.compile(r"^\s*(\d{1,2})\.\s+([A-Z][^\n]{3,80})", re.MULTILINE),
    re.compile(r"^\s*Chapter\s+(\d{1,2})[:.]?\s+([^\n]{3,80})", re.MULTILINE | re.IGNORECASE),
]


def detect_heading_chapters(reader: PdfReader, min_gap: int = 2) -> list[Chapter]:
    """Heuristic: scan the top of each page's text for a heading pattern.
    Chapters must be at least `min_gap` pages apart, which filters out a
    heading-like phrase mid-paragraph or a repeated running header."""
    chapters: list[Chapter] = []
    last_start = -min_gap

    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        top_text = "\n".join(text.splitlines()[:6])  # only near the top of the page

        for pattern in HEADING_PATTERNS:
            m = pattern.search(top_text)
            if m:
                if i - last_start < min_gap:
                    break  # too close to the previous match, skip
                title = m.group(0).strip().replace("\n", " ")
                chapters.append(Chapter(title=title, start_page=i))
                last_start = i
                break

    return chapters


def merge_same_page_chapters(chapters: list[Chapter]) -> list[Chapter]:
    """Collapse consecutive chapters whose bookmarks land on the same page.

    When two headings (e.g. "1. Scope" and "2. Normative references") sit on
    the same physical page, splitting them as separate chapters gives the
    first one a zero-page range once end - start is computed - pypdf writes
    that as a technically-valid-but-empty PDF, which pypdfium2/Marker then
    refuses to open ("Failed to load document (PDFium: Success)"). Merging
    same-start-page chapters into one entry avoids ever producing that file.
    """
    if not chapters:
        return chapters

    merged: list[Chapter] = [chapters[0]]
    for ch in chapters[1:]:
        if ch.start_page == merged[-1].start_page:
            merged[-1] = Chapter(
                title=f"{merged[-1].title} + {ch.title}",
                start_page=merged[-1].start_page,
            )
        else:
            merged.append(ch)
    return merged


def split_by_chapters(chapters: list[Chapter], page_count: int) -> list[tuple[Chapter, int, int]]:
    """Turn chapter start pages into (chapter, start, end_exclusive) ranges."""
    ranges = []
    for idx, ch in enumerate(chapters):
        end = chapters[idx + 1].start_page if idx + 1 < len(chapters) else page_count
        ranges.append((ch, ch.start_page, end))
    return ranges


def sanitize_filename(title: str, max_len: int = 60) -> str:
    name = re.sub(r"[^\w\s-]", "", title).strip()
    name = re.sub(r"\s+", "_", name)
    return name[:max_len] or "chapter"


def write_chapters(reader: PdfReader, ranges, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for i, (ch, start, end) in enumerate(ranges, start=1):
        if end <= start:
            print(f"  SKIPPED (zero-page range): {ch.title} (page {start + 1})")
            continue
        writer = PdfWriter()
        for p in range(start, end):
            writer.add_page(reader.pages[p])
        fname = f"{i:02d}_{sanitize_filename(ch.title)}.pdf"
        out_path = output_dir / fname
        with open(out_path, "wb") as f:
            writer.write(f)
        print(f"  {fname}: pages {start + 1}-{end} ({end - start} pages) - {ch.title}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="knowledge-retrieval-split",
        description="Split a PDF into one file per chapter, using embedded "
        "bookmarks if present, else a heading-detection heuristic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s input.pdf -o chapters/                  # auto: bookmarks, else heuristic
  %(prog)s input.pdf -o chapters/ --mode bookmarks  # force bookmarks only
  %(prog)s input.pdf -o chapters/ --mode headings   # force heading-detection
  %(prog)s input.pdf --list                         # just list chapters, write nothing
""",
    )
    parser.add_argument("input", type=Path, help="path to the source PDF file")
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=None,
        help="directory to write one PDF per chapter into (required unless --list)",
    )
    parser.add_argument(
        "--mode", choices=["auto", "bookmarks", "headings"], default="auto",
        help="chapter-detection strategy (default: auto - try bookmarks, fall back to headings)",
    )
    parser.add_argument(
        "--depth", type=int, default=0,
        help="bookmark nesting depth to treat as chapters: 0 = top-level only "
        "(default), 1 = include first-level sub-bookmarks, etc.",
    )
    parser.add_argument(
        "--min-gap", type=int, default=2,
        help="minimum pages between detected headings, filters false positives (default: 2)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="only print detected chapters and page ranges; write no files",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Input file not found: {args.input}")
    if not args.list and args.output_dir is None:
        parser.error("--output-dir is required unless --list is given")

    reader = PdfReader(str(args.input))
    page_count = len(reader.pages)

    chapters: list[Chapter] = []
    if args.mode in ("auto", "bookmarks"):
        chapters = get_bookmark_chapters(reader, max_depth=args.depth)
        if chapters:
            print(f"Found {len(chapters)} chapters from embedded bookmarks.")
        elif args.mode == "bookmarks":
            parser.error("No embedded bookmarks found in this PDF.")

    if not chapters and args.mode in ("auto", "headings"):
        chapters = detect_heading_chapters(reader, min_gap=args.min_gap)
        print(f"Found {len(chapters)} chapters via heading-detection heuristic.")

    if not chapters:
        parser.error(
            "No chapters detected. Try --mode headings with a smaller --min-gap, "
            "or check the PDF manually - this heuristic won't catch every layout."
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

    if args.list:
        return

    write_chapters(reader, ranges, args.output_dir)
    print(f"\nWrote {len(ranges)} chapter files to {args.output_dir}")


if __name__ == "__main__":
    main()
