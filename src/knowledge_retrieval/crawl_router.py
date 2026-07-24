"""Tiering logic for the batch crawl pipeline: decide which fetcher a URL
should go through, and load the input URL list.

Tiers:
  - "pdf"       - the URL points at a PDF; hand off to the existing PDF engines
                  instead of scraping it as a web page.
  - "firecrawl" - the URL is tagged `known-hard` (pre-identified as anti-bot,
                  an SPA, or login-gated), so go straight to the hosted
                  fallback instead of wasting a Crawl4AI attempt.
  - "crawl4ai"  - everything else; the default, cheaper Tier 1 path. Note that
                  a "crawl4ai" decision can still fall back to Firecrawl at
                  runtime if the fetch fails or returns near-empty content -
                  that fallback is decided by the caller after the fetch,
                  since it depends on the actual response, not just the URL.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class URLEntry:
    """One row from the input URL list."""

    url: str
    known_hard: bool = False


def is_pdf_url(url: str) -> bool:
    """True if `url` looks like it points directly at a PDF file."""
    return urlparse(url).path.lower().endswith(".pdf")


def decide_tier(entry: URLEntry) -> str:
    """Decide the initial tier for `entry`, based only on the URL/tag - no network."""
    if is_pdf_url(entry.url):
        return "pdf"
    if entry.known_hard:
        return "firecrawl"
    return "crawl4ai"


def load_url_list(path: Path) -> list[URLEntry]:
    """Load URLs from `path`.

    - `.csv`: header row with an `url` column and an optional `known_hard`
      column (any of "1"/"true"/"yes", case-insensitive, means tagged hard).
    - anything else: one URL per line; a line may end with `,known-hard` to
      tag it (e.g. `https://example.com/app,known-hard`). Blank lines and
      lines starting with `#` are ignored.
    """
    if path.suffix.lower() == ".csv":
        return _load_csv(path)
    return _load_lines(path)


def _load_csv(path: Path) -> list[URLEntry]:
    entries = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            known_hard = (row.get("known_hard") or "").strip().lower() in ("1", "true", "yes")
            entries.append(URLEntry(url=url, known_hard=known_hard))
    return entries


def _load_lines(path: Path) -> list[URLEntry]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url, _, tag = line.partition(",")
        known_hard = tag.strip().lower() == "known-hard"
        entries.append(URLEntry(url=url.strip(), known_hard=known_hard))
    return entries
