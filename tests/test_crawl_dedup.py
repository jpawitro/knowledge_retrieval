"""Unit tests for the batch crawl pipeline's content-hash dedup index. No
network calls - operates purely on strings and a JSON file on disk.
"""

from knowledge_retrieval.crawl_dedup import content_hash, load_index


def test_content_hash_is_deterministic_and_sensitive_to_change():
    a = content_hash("hello world")
    b = content_hash("hello world")
    c = content_hash("hello world!")

    assert a == b
    assert a != c


def test_unseen_url_is_not_unchanged(tmp_path):
    index = load_index(tmp_path)
    assert index.is_unchanged("https://example.com/a", content_hash("x")) is False


def test_update_then_save_then_reload_roundtrips(tmp_path):
    index = load_index(tmp_path)
    hash_ = content_hash("some article text")
    index.update("https://example.com/a", hash_, name="example-com-a", tier="crawl4ai")
    index.save()

    reloaded = load_index(tmp_path)
    assert reloaded.is_unchanged("https://example.com/a", hash_) is True
    assert reloaded.is_unchanged("https://example.com/a", content_hash("different text")) is False


def test_is_unchanged_false_after_content_changes(tmp_path):
    index = load_index(tmp_path)
    index.update("https://example.com/a", content_hash("version 1"))
    index.save()

    reloaded = load_index(tmp_path)
    assert reloaded.is_unchanged("https://example.com/a", content_hash("version 2")) is False
