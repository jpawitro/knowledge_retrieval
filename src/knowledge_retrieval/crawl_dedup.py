"""Content-hash dedup for the batch crawl pipeline: skip re-processing a URL
on recrawl if its extracted content hasn't changed. Backed by a single JSON
index file rather than a database - the crawl volumes this targets (a
personal list of URLs, run manually or via cron) don't need more than that.
"""

import json
from pathlib import Path

INDEX_FILENAME = ".dedup_index.json"


def content_hash(text: str) -> str:
    """SHA-256 hex digest of `text`, used to detect unchanged pages on recrawl."""
    import hashlib  # pylint: disable=import-outside-toplevel

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DedupIndex:
    """Tracks the last-seen content hash for each URL, persisted as JSON."""

    def __init__(self, path: Path):
        self.path = path
        if path.is_file():
            self._records: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        else:
            self._records = {}

    def is_unchanged(self, url: str, new_hash: str) -> bool:
        """True if `url` was already processed with the same content hash."""
        record = self._records.get(url)
        return record is not None and record.get("content_hash") == new_hash

    def update(self, url: str, content_hash_: str, **extra) -> None:
        """Record `url`'s latest content hash (plus any extra metadata fields)."""
        self._records[url] = {"content_hash": content_hash_, **extra}

    def save(self) -> None:
        """Write the index back to `self.path`."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._records, indent=2, sort_keys=True), encoding="utf-8")


def load_index(output_dir: Path) -> DedupIndex:
    """Load (or initialize) the dedup index for `output_dir`."""
    return DedupIndex(output_dir / INDEX_FILENAME)
