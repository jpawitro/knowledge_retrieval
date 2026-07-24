"""Batch crawl pipeline CLI: fetch a list of URLs, convert each to Markdown
via the tiered router (Crawl4AI/Trafilatura by default, Firecrawl for
`known-hard` URLs or Tier 1 failures, the PDF engines for URLs that point
directly at a PDF), dedup against previous runs by content hash, and write
Markdown + a metadata sidecar per URL to the output directory.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from knowledge_retrieval.crawl_dedup import content_hash, load_index
from knowledge_retrieval.crawl_pdf import handle_pdf_url
from knowledge_retrieval.crawl_router import URLEntry, decide_tier, load_url_list
from knowledge_retrieval.web import slugify_url
from knowledge_retrieval.web_engines import crawl4ai, firecrawl

# Below this many characters, treat Tier 1's output as a failure (JS wall,
# anti-bot block page, etc.) and fall back to Firecrawl rather than keep it.
MIN_CONTENT_CHARS = 200


def _process_crawl4ai(entry: URLEntry, name: str, output_dir: Path) -> dict:
    """Tier 1: fetch with Crawl4AI, extract with Trafilatura, keep both
    outputs side by side (no auto-picked winner yet). Falls back to Firecrawl
    if the fetch fails or both outputs come back near-empty."""
    try:
        html, crawl4ai_markdown = crawl4ai.fetch(entry.url)
        trafilatura_markdown = crawl4ai.extract_with_trafilatura(html, entry.url)
    except RuntimeError as exc:
        print(f"  Crawl4AI failed ({exc}); falling back to Firecrawl")
        return _process_firecrawl(entry, name, output_dir, tier="firecrawl-fallback")

    primary = trafilatura_markdown or crawl4ai_markdown or ""
    if len(primary.strip()) < MIN_CONTENT_CHARS:
        print("  Crawl4AI/Trafilatura content is near-empty; falling back to Firecrawl")
        return _process_firecrawl(entry, name, output_dir, tier="firecrawl-fallback")

    extractors = []
    if crawl4ai_markdown and crawl4ai_markdown.strip():
        (output_dir / f"{name}.crawl4ai.md").write_text(crawl4ai_markdown, encoding="utf-8")
        extractors.append("crawl4ai")
    if trafilatura_markdown and trafilatura_markdown.strip():
        (output_dir / f"{name}.trafilatura.md").write_text(trafilatura_markdown, encoding="utf-8")
        extractors.append("trafilatura")

    return {"tier": "crawl4ai", "extractors": extractors, "content": primary}


def _process_firecrawl(entry: URLEntry, name: str, output_dir: Path, tier: str = "firecrawl") -> dict:
    """Tier 2: scrape via the hosted Firecrawl API."""
    markdown = firecrawl.scrape(entry.url)
    (output_dir / f"{name}.md").write_text(markdown, encoding="utf-8")
    return {"tier": tier, "extractors": ["firecrawl"], "content": markdown}


def _process_pdf(entry: URLEntry, name: str, output_dir: Path) -> dict:
    """PDF branch: hand off to the existing PDF-to-Markdown engines."""
    doc_dir = handle_pdf_url(entry.url, name, output_dir)
    md_path = doc_dir / f"{name}.md"
    content = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    return {"tier": "pdf", "extractors": ["pdf"], "content": content}


def process_entry(entry: URLEntry, output_dir: Path) -> dict:
    """Run one URL through the tiered pipeline. Returns a dict with `tier`,
    `extractors`, `content` (used for the dedup hash), and `name`."""
    name = slugify_url(entry.url)
    tier = decide_tier(entry)
    if tier == "pdf":
        result = _process_pdf(entry, name, output_dir)
    elif tier == "firecrawl":
        result = _process_firecrawl(entry, name, output_dir)
    else:
        result = _process_crawl4ai(entry, name, output_dir)
    result["name"] = name
    return result


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the batch crawl CLI."""
    parser = argparse.ArgumentParser(
        prog="knowledge-retrieval-crawl",
        description="Batch-scrape a list of URLs to Markdown via the tiered Crawl4AI/Firecrawl/PDF pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s --input urls.txt --output out/
  %(prog)s --input urls.csv --output out/ --force   # ignore dedup, reprocess everything

input file format:
  urls.txt (one per line, optional ",known-hard" tag):
    https://example.com/article
    https://example.com/app,known-hard
    # comments and blank lines are ignored

  urls.csv (header row, optional known_hard column):
    url,known_hard
    https://example.com/article,
    https://example.com/app,true
""",
    )
    parser.add_argument(
        "--input", required=True, type=Path,
        help="path to the URL list (.csv, or one URL per line otherwise)",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="output directory for Markdown files, metadata sidecars, and the dedup index",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="reprocess every URL even if its content hash is unchanged since the last run",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    return parser


def main() -> None:  # pylint: disable=too-many-locals
    """CLI entry point: crawl every URL in the input list."""
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Input file not found: {args.input}")

    entries = load_url_list(args.input)
    if not entries:
        parser.error(f"No URLs found in {args.input}")

    args.output.mkdir(parents=True, exist_ok=True)
    index = load_index(args.output)

    written = skipped = failed = 0
    for entry in entries:
        print(entry.url)
        try:
            result = process_entry(entry, args.output)
        except Exception as exc:  # pylint: disable=broad-except
            # A single bad URL shouldn't abort the whole batch run.
            print(f"  FAILED: {exc}")
            failed += 1
            continue

        hash_ = content_hash(result["content"])
        if not args.force and index.is_unchanged(entry.url, hash_):
            print("  unchanged since last crawl, skipping")
            skipped += 1
            continue

        name = result["name"]
        fetched_at = datetime.now(timezone.utc).isoformat()
        meta = {
            "source_url": entry.url,
            "fetched_at": fetched_at,
            "tier": result["tier"],
            "extractors": result["extractors"],
            "content_hash": hash_,
        }
        (args.output / f"{name}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        index.update(entry.url, hash_, name=name, tier=result["tier"], fetched_at=fetched_at)
        written += 1
        print(f"  wrote {name} (tier={result['tier']})")

    index.save()
    print(f"\n{written} written, {skipped} unchanged, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
