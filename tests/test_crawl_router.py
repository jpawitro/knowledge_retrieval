"""Unit tests for the batch crawl pipeline's tiering decision and URL-list
loading. No network calls - `decide_tier` only looks at the URL string and
the `known_hard` tag.
"""

from knowledge_retrieval.crawl_router import URLEntry, decide_tier, is_pdf_url, load_url_list


def test_pdf_url_takes_pdf_tier_even_if_tagged_known_hard():
    entry = URLEntry(url="https://example.com/reports/annual.pdf", known_hard=True)
    assert is_pdf_url(entry.url)
    assert decide_tier(entry) == "pdf"


def test_pdf_detection_is_case_insensitive_and_ignores_query_string():
    assert is_pdf_url("https://example.com/doc.PDF?download=1")
    assert not is_pdf_url("https://example.com/doc.pdf.html")


def test_known_hard_url_takes_firecrawl_tier():
    entry = URLEntry(url="https://example.com/spa-app", known_hard=True)
    assert decide_tier(entry) == "firecrawl"


def test_plain_url_takes_crawl4ai_tier():
    entry = URLEntry(url="https://example.com/blog/post")
    assert decide_tier(entry) == "crawl4ai"


def test_load_url_list_from_txt_supports_tag_and_comments(tmp_path):
    path = tmp_path / "urls.txt"
    path.write_text(
        "\n".join([
            "# a comment",
            "",
            "https://example.com/a",
            "https://example.com/b,known-hard",
            "  https://example.com/c  ",
        ]),
        encoding="utf-8",
    )

    entries = load_url_list(path)

    assert entries == [
        URLEntry(url="https://example.com/a", known_hard=False),
        URLEntry(url="https://example.com/b", known_hard=True),
        URLEntry(url="https://example.com/c", known_hard=False),
    ]


def test_load_url_list_from_csv(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(
        "url,known_hard\n"
        "https://example.com/a,\n"
        "https://example.com/b,true\n",
        encoding="utf-8",
    )

    entries = load_url_list(path)

    assert entries == [
        URLEntry(url="https://example.com/a", known_hard=False),
        URLEntry(url="https://example.com/b", known_hard=True),
    ]
