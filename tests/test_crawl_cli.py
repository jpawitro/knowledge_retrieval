"""Unit tests for the batch crawl pipeline's tier dispatch and Tier-1-to-
Tier-2 fallback orchestration in crawl_cli.py. Crawl4AI, Firecrawl, and the
PDF branch are all mocked here - no network calls, no browser, no PDF engine.
"""

from knowledge_retrieval import crawl_cli
from knowledge_retrieval.crawl_router import URLEntry


def test_known_hard_entry_skips_crawl4ai_and_goes_straight_to_firecrawl(monkeypatch, tmp_path):
    def fail_if_called(url):  # pylint: disable=unused-argument
        raise AssertionError("crawl4ai.fetch should not be called for known-hard URLs")

    monkeypatch.setattr(crawl_cli.crawl4ai, "fetch", fail_if_called)
    monkeypatch.setattr(
        crawl_cli.firecrawl, "scrape",
        lambda url: "Firecrawl content, long enough to pass any length checks. " * 5,
    )

    entry = URLEntry(url="https://example.com/app", known_hard=True)
    result = crawl_cli.process_entry(entry, tmp_path)

    assert result["tier"] == "firecrawl"
    assert result["extractors"] == ["firecrawl"]
    assert (tmp_path / f"{result['name']}.md").is_file()


def test_crawl4ai_success_keeps_both_outputs_side_by_side(monkeypatch, tmp_path):
    long_text = "Real article content. " * 20
    monkeypatch.setattr(crawl_cli.crawl4ai, "fetch", lambda url: ("<html>...</html>", long_text))
    monkeypatch.setattr(crawl_cli.crawl4ai, "extract_with_trafilatura", lambda html, url: long_text.upper())

    entry = URLEntry(url="https://example.com/article")
    result = crawl_cli.process_entry(entry, tmp_path)

    assert result["tier"] == "crawl4ai"
    assert set(result["extractors"]) == {"crawl4ai", "trafilatura"}
    assert (tmp_path / f"{result['name']}.crawl4ai.md").is_file()
    assert (tmp_path / f"{result['name']}.trafilatura.md").is_file()
    # Trafilatura's extraction is preferred as the primary/dedup content when present.
    assert result["content"] == long_text.upper()


def test_crawl4ai_fetch_failure_falls_back_to_firecrawl(monkeypatch, tmp_path):
    def fail(url):  # pylint: disable=unused-argument
        raise RuntimeError("Crawl4AI failed to fetch")

    monkeypatch.setattr(crawl_cli.crawl4ai, "fetch", fail)
    monkeypatch.setattr(crawl_cli.firecrawl, "scrape", lambda url: "Firecrawl rescued this page. " * 20)

    entry = URLEntry(url="https://example.com/hard-page")
    result = crawl_cli.process_entry(entry, tmp_path)

    assert result["tier"] == "firecrawl-fallback"


def test_crawl4ai_near_empty_content_falls_back_to_firecrawl(monkeypatch, tmp_path):
    monkeypatch.setattr(crawl_cli.crawl4ai, "fetch", lambda url: ("<html></html>", "short"))
    monkeypatch.setattr(crawl_cli.crawl4ai, "extract_with_trafilatura", lambda html, url: None)
    monkeypatch.setattr(crawl_cli.firecrawl, "scrape", lambda url: "Firecrawl content, long enough this time. " * 10)

    entry = URLEntry(url="https://example.com/js-heavy-app")
    result = crawl_cli.process_entry(entry, tmp_path)

    assert result["tier"] == "firecrawl-fallback"


def test_pdf_url_uses_pdf_branch_not_crawl4ai_or_firecrawl(monkeypatch, tmp_path):
    def fake_handle_pdf_url(url, name, output_dir, engine_name="mineru"):  # pylint: disable=unused-argument
        doc_dir = output_dir / name
        doc_dir.mkdir(parents=True)
        (doc_dir / f"{name}.md").write_text("# PDF content", encoding="utf-8")
        return doc_dir

    def fail_if_called(*args, **kwargs):
        raise AssertionError("web engines should not be called for PDF URLs")

    monkeypatch.setattr(crawl_cli, "handle_pdf_url", fake_handle_pdf_url)
    monkeypatch.setattr(crawl_cli.crawl4ai, "fetch", fail_if_called)
    monkeypatch.setattr(crawl_cli.firecrawl, "scrape", fail_if_called)

    entry = URLEntry(url="https://example.com/reports/annual.pdf")
    result = crawl_cli.process_entry(entry, tmp_path)

    assert result["tier"] == "pdf"
    assert result["content"] == "# PDF content"
