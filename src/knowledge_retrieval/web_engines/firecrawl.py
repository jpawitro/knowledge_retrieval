"""Wraps the hosted Firecrawl API (firecrawl-py) for URL -> Markdown scraping.

Used both as a selectable engine for the single-URL `knowledge-retrieval-web`
CLI and as the Tier 2 fallback in the batch crawl pipeline (`knowledge-
retrieval-crawl`), for URLs tagged `known-hard` or where Crawl4AI's fetch
failed or returned near-empty content.
"""

import importlib.util
import os
from pathlib import Path

PACKAGE = "firecrawl-py"
ENV_VAR = "FIRECRAWL_API_KEY"


def scrape(url: str) -> str:
    """Scrape `url` via the Firecrawl API and return its Markdown."""
    if importlib.util.find_spec("firecrawl") is None:
        raise RuntimeError(
            f"'firecrawl' is not installed. Install it with 'pip install {PACKAGE}'."
        )

    api_key = os.environ.get(ENV_VAR)
    if not api_key:
        raise RuntimeError(
            f"{ENV_VAR} is not set. Add it to a .env file in the project root "
            "(see .env.example) or export it in your shell."
        )

    from firecrawl import FirecrawlApp  # pylint: disable=import-outside-toplevel

    app = FirecrawlApp(api_key=api_key)
    result = app.scrape(url, formats=["markdown"])

    # Response shape has changed across firecrawl-py major versions (plain
    # dict vs. a pydantic Document) - handle both rather than pin to one.
    markdown = result.get("markdown") if isinstance(result, dict) else getattr(result, "markdown", None)
    if not markdown or not markdown.strip():
        raise RuntimeError(f"Firecrawl returned no markdown content for {url}")

    return markdown


def convert(url: str, output_path: Path) -> None:
    """Scrape `url` via Firecrawl and write its Markdown to `output_path`."""
    markdown = scrape(url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
