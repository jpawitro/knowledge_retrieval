"""Unit tests for the web-scraping CLI's pure logic - URL slugging and the
Trafilatura extraction step used by the crawl4ai engine. Deliberately avoids
network access and the headless browser (that part is exercised manually /
in a live smoke test), so these run fast and every time.
"""

import importlib.util

import pytest

from knowledge_retrieval.web import slugify_url

SAMPLE_HTML = """\
<html>
<head><title>Sample Article</title></head>
<body>
<nav>Home | About | Contact</nav>
<article>
<h1>Sample Article</h1>
<p>This is the first paragraph of the real content, long enough for
Trafilatura's extractor to consider it a genuine article body rather than
boilerplate navigation or footer text.</p>
<p>This is a second paragraph with more real content, to make sure the
extractor recognizes this as the main body of the page and returns it.</p>
</article>
<footer>Copyright 2026</footer>
</body>
</html>
"""


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://example.com/blog/my-post", "example-com-blog-my-post"),
        ("https://example.com/", "example-com"),
        ("http://Example.com/A/B?x=1", "example-com-a-b"),
    ],
)
def test_slugify_url(url, expected):
    assert slugify_url(url) == expected


@pytest.mark.skipif(
    importlib.util.find_spec("trafilatura") is None, reason="trafilatura not installed"
)
def test_trafilatura_extracts_main_content_not_boilerplate():
    from knowledge_retrieval.web_engines.crawl4ai import extract_with_trafilatura  # pylint: disable=import-outside-toplevel

    markdown = extract_with_trafilatura(SAMPLE_HTML, "https://example.com/article")

    assert markdown is not None
    assert "first paragraph of the real content" in markdown
    assert "Home | About | Contact" not in markdown
    assert "Copyright 2026" not in markdown
