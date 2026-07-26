"""CLI to split a PDF into one file per chapter, using embedded bookmarks
if present, else a heading-detection heuristic on page text."""

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pypdf import PdfReader, PdfWriter


@dataclass
class Chapter:
    """A detected chapter: its title and 0-indexed start page."""

    title: str
    start_page: int  # 0-indexed


def get_bookmark_chapters(
    reader: PdfReader, level: int = 0, exclude_title: re.Pattern | None = None
) -> list[Chapter]:
    """Extract bookmarks at one exact nesting level as chapter boundaries.

    pypdf represents the outline as a flat list where each item's children
    appear as a nested list immediately after it, e.g.:
        [chapter1, [sub1a, sub1b], chapter2, [sub2a], chapter3]
    level=0 (default) takes only the top-level items (chapter1, chapter2,
    chapter3). level=1 takes only their direct children (sub1a, sub1b, sub2a)
    and ignores chapter1/chapter2/chapter3 themselves - useful for PDFs (e.g.
    many ISO/IEC/EN standards) whose top-level outline entries are just
    file/container wrappers with no real page destination, and the actual
    sections live one level deeper. Only items at the requested level are
    used; shallower and deeper items are always ignored, so levels never mix.

    Some outlines also mix in non-hierarchical "grouping" bookmarks at the
    same level as real chapters (e.g. a "Figures" or "Tables" entry that just
    points at wherever the first figure/table happens to appear, slicing into
    whatever real chapter that page belongs to). Pass `exclude_title` - a
    compiled regex tested against each candidate title - to drop those.
    """
    chapters: list[Chapter] = []

    def walk(outline_items, depth=0):
        """Recurse through the whole outline, collecting items at `level`."""
        for item in outline_items:
            if isinstance(item, list):
                walk(item, depth + 1)
                continue
            if depth == level:
                if exclude_title and exclude_title.search(item.title):
                    continue
                try:
                    page_num = reader.get_destination_page_number(item)
                # Malformed bookmark destinations can raise a range of pypdf
                # errors depending on what's broken; skip the entry rather
                # than aborting the whole split over one bad bookmark. A
                # destination that resolves to no page at all comes back as
                # None (e.g. a container bookmark with no target page) -
                # skip that too rather than let it poison the sort below.
                except Exception:  # pylint: disable=broad-exception-caught
                    continue
                if page_num is None:
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


def parse_page_range(spec) -> tuple[int, int]:
    """Parse a 1-indexed, inclusive page spec into a 0-indexed (start,
    end_exclusive) tuple, e.g. '12-20' -> (11, 20), '12' -> (11, 12),
    [12, 20] -> (11, 20)."""
    if isinstance(spec, (list, tuple)):
        first, last = int(spec[0]), int(spec[-1])
    else:
        text = str(spec).strip()
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", text)
        first, last = (int(m.group(1)), int(m.group(2))) if m else (int(text), int(text))
    if first < 1 or last < first:
        raise ValueError(f"invalid page range: {spec!r}")
    return first - 1, last


def parse_manual_chapter(entry, index: int) -> tuple[Chapter, int, int]:
    """Parse one manually-specified chapter into a (Chapter, start, end)
    range, 0-indexed. `entry` is either a mapping ({title, pages} or {name,
    pages}) or the shorthand string "<title>, <pages>", e.g. "Chapter 1, 1-10".
    """
    if isinstance(entry, dict):
        title = entry.get("title") or entry.get("name") or f"Chapter {index}"
        pages = entry["pages"]
    elif isinstance(entry, str):
        title, _, pages = entry.rpartition(",")
        title = title.strip() or f"Chapter {index}"
        pages = pages.strip()
    else:
        raise ValueError(f"invalid chapter entry: {entry!r}")
    start, end = parse_page_range(pages)
    return Chapter(title=title, start_page=start), start, end


def load_queue(queue_path: Path) -> tuple[dict, list[dict]]:
    """Load a YAML queue file listing multiple PDFs to process in one run.

    Accepts either a bare list of file entries, or a mapping with a top-level
    `defaults` block (applied to every file unless a file overrides a given
    key) and a `files` list. Each file entry is a mapping with at least
    `path`; optionally `chapters` (manual page ranges - see
    parse_manual_chapter) and any of the per-file option overrides
    (output_dir, mode, bookmark_level, exclude_title, min_gap, max_pages).
    """
    with open(queue_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if isinstance(data, list):
        return {}, data
    if isinstance(data, dict):
        return dict(data.get("defaults") or {}), list(data.get("files") or [])
    raise ValueError(f"queue file must be a YAML list or mapping, got {type(data).__name__}")


# Per-file option keys that a YAML queue's `defaults` block and each file
# entry may override. `output_dir` is always a *parent* directory - see
# process_one(), which nests every document's chapters under
# output_dir/<input-stem>/ regardless of whether output_dir came from the
# CLI, `defaults`, or a file's own entry - matching knowledge-retrieval's
# references_dir/outputs_dir convention.
QUEUE_OPTION_KEYS = ("output_dir", "mode", "bookmark_level", "exclude_title", "min_gap", "max_pages")


def resolve_job_options(
    cli_args: argparse.Namespace, yaml_defaults: dict, file_entry: dict, keys: tuple[str, ...] = QUEUE_OPTION_KEYS
) -> dict:
    """Merge one queue file's options: CLI flags are the base, the YAML
    `defaults` block overrides them, and the file entry's own keys win over
    both - so anything present in the YAML overrides the CLI/base setup.
    `keys` lets other CLIs (e.g. the full split+convert pipeline) reuse this
    with their own set of overridable option names."""
    options = {key: getattr(cli_args, key) for key in keys}
    for key in keys:
        if key in yaml_defaults:
            options[key] = yaml_defaults[key]
    for key in keys:
        if key in file_entry:
            options[key] = file_entry[key]
    return options


def build_ranges(
    reader: PdfReader,
    page_count: int,
    mode: str,
    bookmark_level: int,
    exclude_title: re.Pattern | None,
    min_gap: int,
    manual_chapters: list | None = None,
) -> list[tuple[Chapter, int, int]]:
    """Compute (chapter, start, end) ranges for one PDF: from manually
    specified page ranges if given, else from bookmark/heading detection.
    Manual ranges still flow through the same `write_chapters` sub-splitting
    as detected ones - `max_pages` is applied uniformly downstream regardless
    of how a chapter's boundaries were determined.
    """
    if manual_chapters:
        ranges = []
        for i, entry in enumerate(manual_chapters, start=1):
            ch, start, end = parse_manual_chapter(entry, i)
            if end > page_count:
                raise ValueError(f"chapter '{ch.title}' end page {end} exceeds document length {page_count}")
            ranges.append((ch, start, end))
        return ranges

    chapters: list[Chapter] = []
    if mode in ("auto", "bookmarks"):
        chapters = get_bookmark_chapters(reader, level=bookmark_level, exclude_title=exclude_title)
        if chapters:
            print(f"Found {len(chapters)} chapters from embedded bookmarks.")
        elif mode == "bookmarks":
            raise ValueError("No embedded bookmarks found in this PDF.")

    if not chapters and mode in ("auto", "headings"):
        chapters = detect_heading_chapters(reader, min_gap=min_gap)
        print(f"Found {len(chapters)} chapters via heading-detection heuristic.")

    if not chapters:
        raise ValueError(
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
    return safe_ranges


def process_one(
    input_path: Path,
    output_dir: Path | None,
    mode: str,
    bookmark_level: int,
    exclude_title: str | None,
    min_gap: int,
    max_pages: int,
    list_only: bool,
    manual_chapters: list | None = None,
) -> None:
    """Detect (or apply manual) chapters for one PDF, print them, and write
    them out unless `list_only`. `output_dir` is the *parent* directory -
    chapters are written to output_dir/<input-stem>/, matching
    knowledge-retrieval's convention of nesting each document's output under
    its own <name>/ subfolder."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if not list_only and output_dir is None:
        raise ValueError("an output directory is required unless listing only")

    reader = PdfReader(str(input_path))
    page_count = len(reader.pages)
    exclude_pattern = re.compile(exclude_title, re.IGNORECASE) if exclude_title else None

    ranges = build_ranges(
        reader, page_count, mode, bookmark_level, exclude_pattern, min_gap, manual_chapters=manual_chapters
    )

    print()
    for ch, start, end in ranges:
        print(f"  pages {start + 1:>4}-{end:<4} ({end - start:>3} pages)  {ch.title}")
    print()

    if list_only:
        return

    final_dir = output_dir / input_path.stem
    write_chapters(reader, ranges, final_dir, max_pages=max_pages)
    file_count = sum(len(compute_page_chunks(end - start, max_pages)) for _, start, end in ranges)
    print(f"\nWrote {file_count} chapter file(s) to {final_dir}")


def compute_page_chunks(total_pages: int, max_pages: int) -> list[int]:
    """Split `total_pages` into as few roughly-equal chunks as possible, each
    capped at `max_pages`. All but the last chunk share the same size
    (ceil(total_pages / parts)); the last one takes whatever remains, e.g.
    35 pages at max 30 -> [18, 17], 98 pages at max 30 -> [25, 25, 25, 23]."""
    if total_pages <= max_pages:
        return [total_pages]
    parts = math.ceil(total_pages / max_pages)
    chunk_size = math.ceil(total_pages / parts)
    chunks = [chunk_size] * (parts - 1)
    chunks.append(total_pages - chunk_size * (parts - 1))
    return chunks


def sanitize_filename(title: str, max_len: int = 60) -> str:
    """Turn a chapter title into a safe, length-capped filename fragment."""
    name = re.sub(r"[^\w\s-]", "", title).strip()
    name = re.sub(r"\s+", "_", name)
    return name[:max_len] or "chapter"


def _write_one(reader: PdfReader, start: int, end: int, out_path: Path) -> None:
    """Write pages [start, end) from `reader` to a new PDF at `out_path`."""
    writer = PdfWriter()
    for p in range(start, end):
        writer.add_page(reader.pages[p])
    with open(out_path, "wb") as f:
        writer.write(f)


def write_chapters(reader: PdfReader, ranges, output_dir: Path, max_pages: int = 30) -> None:
    """Write one PDF file per (chapter, start, end) range into output_dir.

    A chapter longer than `max_pages` is automatically divided into
    roughly-equal sub-parts (see compute_page_chunks), each written as its
    own file with a `_NN` suffix, e.g. a 98-page chapter becomes
    `..._01.pdf` (25p), `..._02.pdf` (25p), `..._03.pdf` (25p), `..._04.pdf` (23p).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for i, (ch, start, end) in enumerate(ranges, start=1):
        if end <= start:
            print(f"  SKIPPED (zero-page range): {ch.title} (page {start + 1})")
            continue

        base_name = f"{i:02d}_{sanitize_filename(ch.title)}"
        chunks = compute_page_chunks(end - start, max_pages)

        if len(chunks) == 1:
            fname = f"{base_name}.pdf"
            _write_one(reader, start, end, output_dir / fname)
            print(f"  {fname}: pages {start + 1}-{end} ({end - start} pages) - {ch.title}")
            continue

        part_start = start
        for part_num, chunk_pages in enumerate(chunks, start=1):
            part_end = part_start + chunk_pages
            fname = f"{base_name}_{part_num:02d}.pdf"
            _write_one(reader, part_start, part_end, output_dir / fname)
            print(
                f"  {fname}: pages {part_start + 1}-{part_end} ({chunk_pages} pages) "
                f"- {ch.title} (part {part_num}/{len(chunks)})"
            )
            part_start = part_end


def main() -> None:  # pylint: disable=too-many-branches
    """CLI entry point: detect chapters in the input PDF(s) and write them out."""
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
  %(prog)s input.pdf -o chapters/ --bookmark-level 1  # chapters are the 2nd-level bookmarks
  %(prog)s input.pdf --list                         # just list chapters, write nothing
  %(prog)s --queue queue.yaml                       # batch: split every PDF listed in a YAML queue

queue.yaml (batch mode - see README for the full schema):
  defaults:
    output_dir: chapters      # each file gets its own chapters/<stem>/ subfolder
    max_pages: 30             # still applies to manual chapters below, same as CLI

  files:
    - path: /path/to/book1.pdf
      chapters:                       # manual page ranges - skips detection entirely
        - chapter 1, 1-10
        - chapter 2, 11-20
    - path: /path/to/book2.pdf
      chapters:
        - chapter 1, 1-14
        - chapter 2, 15-43
    - path: /path/to/book3.pdf         # no `chapters`: falls back to bookmark/heading detection
      bookmark_level: 1                # per-file override of the defaults/CLI setup
""",
    )
    parser.add_argument("input", type=Path, nargs="?", default=None, help="path to the source PDF file")
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=None,
        help="parent directory to write chapters into - each document gets its own "
        "<output-dir>/<input-stem>/ subfolder (required unless --list)",
    )
    parser.add_argument(
        "--mode", choices=["auto", "bookmarks", "headings"], default="auto",
        help="chapter-detection strategy (default: auto - try bookmarks, fall back to headings)",
    )
    parser.add_argument(
        "--bookmark-level", type=int, default=0,
        help="exact bookmark nesting level to treat as chapters: 0 = top-level "
        "(default), 1 = second-level (children of top-level bookmarks), etc. "
        "Only this level is used - use --list to check which level lines up "
        "with real chapter boundaries before writing files.",
    )
    parser.add_argument(
        "--exclude-title", default=None,
        help="regex (case-insensitive): drop any bookmark at --bookmark-level whose "
        "title matches, e.g. non-hierarchical 'Figures'/'Tables' grouping entries "
        "that some outlines mix in alongside real chapters",
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
        "--list", action="store_true",
        help="only print detected chapters and page ranges; write no files",
    )
    parser.add_argument(
        "--queue", type=Path, default=None,
        help="YAML file listing multiple PDFs to process in one run, optionally with "
        "manual per-chapter page ranges per file, instead of a single positional input "
        "(see the epilog above for the schema)",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    args = parser.parse_args()

    if args.queue and args.input:
        parser.error("pass either a single input PDF or --queue, not both")
    if not args.queue and args.input is None:
        parser.error("an input PDF is required unless --queue is given")
    if not args.queue and not args.list and args.output_dir is None:
        parser.error("-o/--output-dir is required unless --list is given")

    if not args.queue:
        try:
            process_one(
                input_path=args.input,
                output_dir=args.output_dir,
                mode=args.mode,
                bookmark_level=args.bookmark_level,
                exclude_title=args.exclude_title,
                min_gap=args.min_gap,
                max_pages=args.max_pages,
                list_only=args.list,
            )
        except (FileNotFoundError, ValueError) as e:
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
        options = resolve_job_options(args, yaml_defaults, file_entry)
        out_dir = Path(options["output_dir"]).expanduser() if options["output_dir"] else None

        print(f"\n=== [{i}/{len(file_entries)}] {input_path} ===")
        try:
            process_one(
                input_path=input_path,
                output_dir=out_dir,
                mode=options["mode"],
                bookmark_level=options["bookmark_level"],
                exclude_title=options["exclude_title"],
                min_gap=options["min_gap"],
                max_pages=options["max_pages"],
                list_only=args.list,
                manual_chapters=file_entry.get("chapters"),
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"  ERROR: {e}")
            had_error = True

    if had_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
