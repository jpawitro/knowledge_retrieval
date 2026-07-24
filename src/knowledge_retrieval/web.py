"""CLI to scrape a URL and convert it to Markdown via pluggable engines."""

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from knowledge_retrieval.web_engines import DEFAULT_ENGINE, ENGINES, get_engine

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def slugify_url(url: str) -> str:
    """Derive a filesystem-safe name from a URL, e.g. https://a.com/b/c -> a.com-b-c."""
    parsed = urlparse(url)
    raw = f"{parsed.netloc}{parsed.path}".strip("/")
    slug = _SLUG_RE.sub("-", raw).strip("-").lower()
    return slug or "page"


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the web-scraping CLI."""
    parser = argparse.ArgumentParser(
        prog="knowledge-retrieval-web",
        description="Scrape a URL and convert it to Markdown.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s https://example.com/article                     # crawl4ai + trafilatura (default)
  %(prog)s https://example.com/article --engine firecrawl   # use the Firecrawl API
  %(prog)s https://example.com/article -o article.md        # write to a specific file
""",
    )
    parser.add_argument("url", help="URL of the page to scrape")
    parser.add_argument(
        "--engine", choices=sorted(ENGINES), default=DEFAULT_ENGINE,
        help=f"web scraping engine (default: {DEFAULT_ENGINE})",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None, metavar="PATH",
        help="output Markdown file path (default: <outputs-dir>/<slug-of-url>.md)",
    )
    parser.add_argument(
        "--outputs-dir", type=Path, default=Path("outputs"),
        help="parent directory for scraped Markdown when --output isn't given (default: outputs)",
    )
    parser.add_argument(
        "--name", default=None,
        help="output file stem, used with --outputs-dir (default: derived from the URL)",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    return parser


def main() -> None:
    """CLI entry point: scrape the given URL and write Markdown output."""
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    output_path = args.output
    if output_path is None:
        name = args.name or slugify_url(args.url)
        output_path = args.outputs_dir / f"{name}.md"

    convert = get_engine(args.engine)
    print(f"Scraping {args.url} -> {output_path} with engine '{args.engine}'")
    try:
        convert(args.url, output_path)
    except RuntimeError as exc:
        parser.error(str(exc))

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
