"""Wraps Crawl4AI (headless-browser crawler) + Trafilatura (content extraction)
for URL -> Markdown conversion. This is the default web engine.

Crawl4AI renders the page (JS included) the same way a hosted scraper like
Firecrawl does; Trafilatura then extracts the main content from that rendered
HTML. Trafilatura's extraction consistently matches or beats readability-style
extractors in independent benchmarks, so this combination is meant to match or
beat Firecrawl's own markdown output on real-world pages.

`fetch()` and `extract_with_trafilatura()` are also used directly by the batch
crawl pipeline (`knowledge-retrieval-crawl`), which keeps both Crawl4AI's own
markdown and Trafilatura's extraction side by side rather than picking one.
"""

import asyncio
import importlib.util
from pathlib import Path

PACKAGE = "crawl4ai trafilatura"


def extract_with_trafilatura(html: str, url: str) -> str | None:
    """Run Trafilatura's main-content extractor over rendered HTML."""
    import trafilatura  # pylint: disable=import-outside-toplevel

    return trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        with_metadata=True,
        include_links=True,
        include_images=True,
        include_tables=True,
    )


async def _fetch(url: str) -> tuple[str, str]:
    from crawl4ai import (  # pylint: disable=import-outside-toplevel
        AsyncWebCrawler,
        BrowserConfig,
        CacheMode,
        CrawlerRunConfig,
    )

    browser_config = BrowserConfig(headless=True)
    run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

    if not result.success:
        raise RuntimeError(f"Crawl4AI failed to fetch {url}: {result.error_message}")

    fallback_markdown = result.markdown.fit_markdown or result.markdown.raw_markdown
    return result.html, fallback_markdown


def fetch(url: str) -> tuple[str, str]:
    """Render `url` with Crawl4AI's headless browser; return (html, crawl4ai_markdown)."""
    if importlib.util.find_spec("crawl4ai") is None:
        raise RuntimeError(
            f"'crawl4ai' is not installed. Install it with 'pip install {PACKAGE}'."
        )
    return asyncio.run(_fetch(url))


def convert(url: str, output_path: Path) -> None:
    """Fetch `url` and write cleaned Markdown to `output_path`."""
    html, fallback_markdown = fetch(url)

    markdown = None
    if importlib.util.find_spec("trafilatura") is not None:
        markdown = extract_with_trafilatura(html, url)

    if not markdown or not markdown.strip():
        markdown = fallback_markdown

    if not markdown or not markdown.strip():
        raise RuntimeError(f"No extractable content found at {url}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
