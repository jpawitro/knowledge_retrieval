"""Registry of URL -> Markdown web-scraping engines.

Each engine module exposes a `convert(url, output_path)` function that writes
Markdown for that URL to `output_path`.
"""

from . import crawl4ai, firecrawl

ENGINES = {
    "crawl4ai": crawl4ai.convert,
    "firecrawl": firecrawl.convert,
}

DEFAULT_ENGINE = "crawl4ai"


def get_engine(name: str):
    """Look up a registered web engine's `convert` function by name."""
    try:
        return ENGINES[name]
    except KeyError:
        raise ValueError(
            f"Unknown engine '{name}'. Available engines: {', '.join(sorted(ENGINES))}"
        ) from None
